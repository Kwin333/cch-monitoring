"""Deliverable Master — จัดการรายการส่งมอบตาม TOR

★ v5 — แก้ไข:
- 🔧 Fix: เรียงลำดับตาม `sequence` field (ตรงกับ Excel Timeline)
- เพิ่ม helper `_get_sequence()` + `_sort_by_sequence()`
- แก้ Sort option "Milestone + ID" → ใช้ sequence แทน deliverable_id
- เพิ่มคอลัมน์ "#" (ลำดับที่) แสดงในตาราง + Card list
- รองรับ fallback ถ้า DB ยังไม่มี column `sequence`

★ v4 — แก้ไข:
- 🔧 Fix: Status = "Accepted" / "Closed" → Actual = 100% (override progress_history)
- เพิ่ม helper `_effective_progress()` ที่คำนึงถึง status
- แก้ `_latest_actual()` ให้รับ status param
- แก้ callers ทั้ง 3 จุด (KPI tiles, edit mode, card list)
- เพิ่ม Column "Progress Source" ในตาราง (badge ว่ามาจาก status หรือ history)

★ v3 — แก้ไข:
- ป้องกัน `_latest_progress` (display column) ถูก save ลง DB
- เพิ่ม Weight Audit Panel
"""
import streamlit as st
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

from repositories.deliverable_repo import DeliverableRepo
from repositories.progress_repo import ProgressRepo
from repositories.milestone_repo import MilestoneRepo
from core.time_util import now_str, today_str
from core.audit import append_audit
from core.validator import ValidationError


# ============================================================
# CONSTANTS
# ============================================================
STATUSES = [
    "Not Started", "In Progress", "Submitted", "Under Review",
    "Revision Required", "Accepted", "Closed",
]
COMPLIANCE_STATUSES = [
    "Not Checked", "Compliant", "Partially Compliant",
    "Non-Compliant", "Not Applicable",
]

# เป้าหมายของผลรวม weight (ใช้ตรวจสอบ)
TARGET_WEIGHT_TOTAL = 100.0
WEIGHT_TOLERANCE = 0.01  # ยอมรับส่วนต่าง ±0.01%

# Display columns ที่ห้าม save ลง DB
DISPLAY_COLS = ["_latest_progress", "_progress_source", "_sequence", "_seq"]

# Status ที่นับเป็น "เสร็จสิ้น" → actual = 100%
FINAL_STATUSES = ("Accepted", "Closed")


# ============================================================
# HELPERS
# ============================================================
def _to_date(s):
    try:
        if pd.isna(s) or s in ("", None):
            return None
        return pd.to_datetime(str(s)).date()
    except Exception:
        return None


def _fmt_date(d):
    dd = _to_date(d)
    return dd.strftime("%d/%m/%Y") if dd else "-"


def _status_badge(s):
    m = {
        "Not Started": "⚪ ยังไม่เริ่ม",
        "In Progress": "🔵 กำลังทำ",
        "Submitted": "🟣 ส่งแล้ว",
        "Under Review": "🟠 กำลังตรวจ",
        "Revision Required": "🟠 ต้องแก้ไข",
        "Accepted": "🟢 ตรวจรับแล้ว",
        "Closed": "✅ ปิดแล้ว",
    }
    return m.get(s, s or "-")


def _compliance_badge(s):
    m = {
        "Not Checked": "⚪ ยังไม่ตรวจ",
        "Compliant": "🟢 สอดคล้อง",
        "Partially Compliant": "🟠 บางส่วน",
        "Non-Compliant": "🔴 ไม่สอดคล้อง",
        "Not Applicable": "➖ ไม่เกี่ยวข้อง",
    }
    return m.get(s, s or "-")


def _validate_dl(d: dict):
    name = (d.get("deliverable_name") or "").strip()
    if not name:
        raise ValidationError("⚠️ ต้องระบุชื่อ Deliverable")
    if not (d.get("milestone_id") or "").strip():
        raise ValidationError("⚠️ ต้องระบุ Milestone ID")

    ps = _to_date(d.get("planned_start"))
    pf = _to_date(d.get("planned_finish"))
    if ps and pf and pf < ps:
        raise ValidationError("⚠️ วันที่สิ้นสุดต้องไม่ก่อนวันเริ่ม")

    try:
        w = float(d.get("weight", 0) or 0)
    except Exception:
        w = 0
    if w < 0 or w > 100:
        raise ValidationError("⚠️ Weight ต้องอยู่ระหว่าง 0–100%")


# ============================================================
# ★ v5: SEQUENCE HELPERS
# ============================================================
def _get_sequence(row_or_dict) -> int:
    """
    ดึงค่า sequence จาก row (รองรับทั้ง DataFrame row และ dict)
    ถ้าไม่มี → คืน 9999 (จัดท้าย)
    """
    try:
        val = row_or_dict.get("sequence", None)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            # Fallback: parse จาก deliverable_id
            did = str(row_or_dict.get("deliverable_id", ""))
            # DLV-M1-19 → 19
            if did.startswith("DLV-") and "-" in did[4:]:
                try:
                    return int(did.rsplit("-", 1)[-1])
                except ValueError:
                    return 9999
            return 9999
        return int(float(val))
    except Exception:
        return 9999


def _sort_by_sequence(df: pd.DataFrame, sequence_col: str = "_sequence") -> pd.DataFrame:
    """
    เรียงลำดับตาม: milestone_id → sequence → planned_start → deliverable_id
    """
    if df.empty:
        return df

    work = df.copy()

    # สร้าง _sequence ถ้ายังไม่มี
    if sequence_col not in work.columns:
        if "sequence" in work.columns:
            work[sequence_col] = pd.to_numeric(
                work["sequence"], errors="coerce"
            ).fillna(9999).astype(int)
        else:
            work[sequence_col] = work.apply(_get_sequence, axis=1)

    return work.sort_values(
        ["milestone_id", sequence_col, "planned_start", "deliverable_id"],
        ascending=[True, True, True, True],
        na_position="last",
    ).reset_index(drop=True)


# ============================================================
# ★ v4: Effective Progress (คำนึงถึง status)
# ============================================================
def _latest_actual(
    deliverable_id: str,
    prog_df,
    status: str = None,
) -> tuple:
    """
    ★ v4: คำนวณ actual % ที่แท้จริง + source

    Priority:
    1. status = "Accepted" / "Closed" → (100.0, "status")
    2. progress_history มีข้อมูล → (latest_actual, "history")
    3. ไม่มี → (0.0, "none")

    Returns:
        (actual_pct: float, source: str)
        source: "status" | "history" | "none"
    """
    # ── Priority 1: Status final → 100% ──
    if status and str(status) in FINAL_STATUSES:
        return 100.0, "status"

    # ── Priority 2: progress_history ──
    if prog_df is None or prog_df.empty:
        return 0.0, "none"

    p = prog_df[prog_df["deliverable_id"] == deliverable_id]
    if p.empty:
        return 0.0, "none"

    try:
        if "timestamp" in p.columns:
            p = p.copy()
            p["_ts"] = pd.to_datetime(p["timestamp"], errors="coerce")
            p = p.dropna(subset=["_ts"]).sort_values("_ts")
        return float(p["actual_percent"].iloc[-1]), "history"
    except Exception:
        return 0.0, "none"


def _latest_actual_value(deliverable_id: str, prog_df, status: str = None) -> float:
    """Wrapper — คืนค่า float เท่านั้น (backward compatible)"""
    val, _ = _latest_actual(deliverable_id, prog_df, status=status)
    return val


def _progress_source_badge(source: str) -> str:
    """Badge แสดงที่มาของ progress"""
    m = {
        "status": "🟢 สถานะ",
        "history": "📊 ประวัติ",
        "none": "⚪ ไม่มี",
    }
    return m.get(source, "-")


def _progress_bar_html(pct: float, color: str = "#0B5ED7", height: int = 10) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    return (
        f'<div style="background:#E0E6ED;border-radius:20px;'
        f'height:{height}px;overflow:hidden;">'
        f'<div style="width:{pct}%;background:{color};height:100%;'
        f'border-radius:20px;"></div></div>'
    )


def _tile(label, value, sub, color):
    """Small KPI tile"""
    return f"""
    <div style="background:#FFFFFF;border-radius:10px;padding:12px 14px;
                border-left:4px solid {color};box-shadow:0 2px 6px rgba(0,51,102,0.06);">
        <div style="font-size:11.5px;color:#5A5A5A;font-weight:600;">{label}</div>
        <div style="font-size:22px;font-weight:700;color:#003366;line-height:1.1;margin:4px 0;">{value}</div>
        <div style="font-size:11px;color:{color};">{sub}</div>
    </div>
    """


def _strip_display_cols(row: dict) -> dict:
    """ลบ display columns ก่อน save (ป้องกัน error)"""
    if not isinstance(row, dict):
        return row
    clean = dict(row)
    for col in DISPLAY_COLS:
        clean.pop(col, None)
    return clean


def _get_weight_summary(df: pd.DataFrame) -> dict:
    """คำนวณสรุป weight จาก df"""
    if df.empty:
        return {
            "total": 0.0,
            "n_items": 0,
            "by_milestone": pd.DataFrame(columns=["Milestone", "Weight", "Count"]),
            "is_valid": False,
            "delta": -TARGET_WEIGHT_TOTAL,
        }

    work = df.copy()
    work["weight"] = pd.to_numeric(work["weight"], errors="coerce").fillna(0.0)

    total = float(work["weight"].sum())
    n_items = len(work)

    by_ms = (
        work.groupby("milestone_id")
        .agg(Weight=("weight", "sum"), Count=("deliverable_id", "count"))
        .reset_index()
        .rename(columns={"milestone_id": "Milestone"})
        .sort_values("Milestone")
    )
    by_ms["Weight"] = by_ms["Weight"].round(2)

    is_valid = abs(total - TARGET_WEIGHT_TOTAL) < WEIGHT_TOLERANCE
    delta = round(total - TARGET_WEIGHT_TOTAL, 2)

    return {
        "total": round(total, 2),
        "n_items": n_items,
        "by_milestone": by_ms,
        "is_valid": is_valid,
        "delta": delta,
    }


# ============================================================
# ★ WEIGHT AUDIT PANEL
# ============================================================
def _render_weight_audit(df: pd.DataFrame):
    """แสดง Weight Audit Panel"""
    st.markdown("---")
    st.markdown("### ⚖️ Weight Audit — ตรวจสอบน้ำหนักคะแนน")

    summary = _get_weight_summary(df)
    total_w = summary["total"]
    n_items = summary["n_items"]
    by_ms = summary["by_milestone"]
    is_valid = summary["is_valid"]
    delta = summary["delta"]

    # ---- KPI Tiles ----
    cA, cB, cC, cD = st.columns(4)

    with cA:
        st.markdown(
            _tile("📦 จำนวน Deliverables", f"{n_items}",
                  "รายการทั้งหมด", "#0B5ED7"),
            unsafe_allow_html=True,
        )

    with cB:
        if is_valid:
            w_color = "#2E7D32"
            w_sub = "✅ ครบ 100%"
        else:
            w_color = "#D32F2F" if delta < 0 else "#F57C00"
            w_sub = f"{delta:+.2f}% จากเป้าหมาย"
        st.markdown(
            _tile("⚖️ Weight รวม", f"{total_w:.2f}%",
                  w_sub, w_color),
            unsafe_allow_html=True,
        )

    with cC:
        ms_color = "#2E7D32" if is_valid else "#F57C00"
        st.markdown(
            _tile("📅 Milestones", f"{len(by_ms)}",
                  "งวดงานที่มี Deliverables", ms_color),
            unsafe_allow_html=True,
        )

    with cD:
        status_icon = "✅" if is_valid else "⚠️"
        status_text = "ถูกต้อง" if is_valid else "ต้องตรวจสอบ"
        status_color = "#2E7D32" if is_valid else "#D32F2F"
        st.markdown(
            _tile(f"{status_icon} สถานะ", status_text,
                  f"เป้าหมาย = {TARGET_WEIGHT_TOTAL:.2f}%", status_color),
            unsafe_allow_html=True,
        )

    # ---- Visual Progress Bar ----
    st.markdown("")
    if is_valid:
        bar_color = "#2E7D32"
    elif total_w < TARGET_WEIGHT_TOTAL:
        bar_color = "#F57C00"
    else:
        bar_color = "#D32F2F"

    st.markdown(
        f'<div style="margin:10px 0;">'
        f'<div style="display:flex;justify-content:space-between;'
        f'font-size:12px;color:#666;margin-bottom:4px;">'
        f'<span>0%</span>'
        f'<span style="font-weight:700;color:{bar_color};">'
        f'{total_w:.2f}% / {TARGET_WEIGHT_TOTAL:.0f}%</span>'
        f'<span>{TARGET_WEIGHT_TOTAL:.0f}%</span></div>'
        + _progress_bar_html(total_w, bar_color, 14) +
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Warning + Fix Hint ----
    if not is_valid:
        if total_w < TARGET_WEIGHT_TOTAL:
            gap_txt = f"ขาดอีก <b>{abs(delta):.2f}%</b>"
            action_hint = (
                "กรุณาเพิ่ม weight ของ Deliverables ที่สำคัญ "
                "หรือใช้เครื่องมือ Rebalance"
            )
        else:
            gap_txt = f"เกินไป <b>{abs(delta):.2f}%</b>"
            action_hint = (
                "กรุณาลด weight ของ Deliverables ที่สำคัญน้อยลง "
                "หรือใช้เครื่องมือ Rebalance"
            )

        st.markdown(
            f"""
            <div style="background:#FFF8E1;border-left:4px solid #F57C00;
                        padding:12px 16px;border-radius:8px;font-size:12.5px;
                        color:#E65100;margin-top:10px;">
                ⚠️ <b>Weight รวม = {total_w:.2f}%</b> — ไม่เท่ากับ
                {TARGET_WEIGHT_TOTAL:.0f}% ({gap_txt})<br>
                <span style="font-size:11.5px;color:#666;">
                    📌 {action_hint} — ไปที่
                    <b>🔧 Settings → 💾 Backup / Export → 
                    ⚖️ Rebalance Deliverable Weights</b>
                    เพื่อปรับอัตโนมัติ
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div style="background:#E8F5E9;border-left:4px solid #2E7D32;
                        padding:10px 14px;border-radius:8px;font-size:12.5px;
                        color:#2E7D32;margin-top:10px;">
                ✅ <b>Weight รวม = {total_w:.2f}%</b> — ถูกต้อง
                สอดคล้องกับ S-Curve ในหน้า Dashboard
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ---- Breakdown Table ----
    st.markdown("")
    st.markdown("#### 📊 Breakdown ต่อ Milestone")

    if by_ms.empty:
        st.info("ไม่มีข้อมูล")
    else:
        display_df = by_ms.copy()
        display_df.columns = ["Milestone", "Weight (%)", "จำนวน Deliverable"]
        display_df["Weight (%)"] = display_df["Weight (%)"].apply(
            lambda x: f"{float(x):.2f}%"
        )

        total_row = pd.DataFrame([{
            "Milestone": "**รวม**",
            "Weight (%)": f"**{total_w:.2f}%**",
            "จำนวน Deliverable": f"**{n_items}**",
        }])
        display_df = pd.concat([display_df, total_row], ignore_index=True)

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
        )

        # ---- Bar chart ----
        if len(by_ms) > 0:
            import plotly.graph_objects as go
            fig = go.Figure(data=[go.Bar(
                x=by_ms["Milestone"].tolist(),
                y=by_ms["Weight"].tolist(),
                marker_color="#0B5ED7",
                text=[f"{w:.2f}%" for w in by_ms["Weight"]],
                textposition="outside",
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Weight: %{y:.2f}%<br>"
                    "<extra></extra>"
                ),
            )])
            fig.update_layout(
                height=320,
                plot_bgcolor="#FAFBFC",
                xaxis_title="Milestone",
                yaxis_title="Weight (%)",
                margin=dict(l=10, r=10, t=20, b=40),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)


# ============================================================
# MAIN
# ============================================================
def render():
    st.title("📦 Deliverable Master")
    st.caption(
        "จัดการรายการส่งมอบตาม TOR (Source of Truth) — "
        "เรียงตามลำดับงานตาม Excel Timeline"
    )

    repo = DeliverableRepo()
    df = repo.read()
    prog_df = ProgressRepo().read()

    # ★ v5: ดึง sequence จาก DB/CSV
    if df.empty:
        df["_sequence"] = pd.Series(dtype=int)
    else:
        if "sequence" in df.columns:
            df["_sequence"] = pd.to_numeric(
                df["sequence"], errors="coerce"
            ).fillna(9999).astype(int)
        else:
            # Fallback: parse จาก deliverable_id
            df["_sequence"] = df.apply(_get_sequence, axis=1)

    # กรองแถวขยะ
    df = df[df["milestone_id"].astype(str).str.startswith("MLS")].reset_index(drop=True)

    # โหลด Milestone list
    try:
        ms_repo = MilestoneRepo()
        ms_df = ms_repo.read()
        ms_ids = ms_df["milestone_id"].tolist() if not ms_df.empty else ["MLS-01"]
    except Exception:
        ms_ids = ["MLS-01"]
        ms_df = pd.DataFrame()

    # ============================================================
    # ★ v4: คำนวณ Progress + Source (คำนึงถึง status)
    # ============================================================
    if not df.empty:
        progress_data = df.apply(
            lambda row: _latest_actual(
                row["deliverable_id"],
                prog_df,
                status=row.get("status"),
            ),
            axis=1,
        )
        df["_latest_progress"] = progress_data.apply(lambda x: x[0])
        df["_progress_source"] = progress_data.apply(lambda x: x[1])
    else:
        df["_latest_progress"] = pd.Series(dtype=float)
        df["_progress_source"] = pd.Series(dtype=str)

    # ============================================================
    # KPI TILES
    # ============================================================
    st.markdown("### 📊 ภาพรวม Deliverables")

    total_dl = len(df)
    total_weight = (
        pd.to_numeric(df["weight"], errors="coerce").fillna(0).sum()
        if not df.empty else 0
    )

    accepted = int((df["status"] == "Accepted").sum()) if not df.empty else 0
    in_progress = int((df["status"] == "In Progress").sum()) if not df.empty else 0
    completed = int((df["status"].isin(FINAL_STATUSES)).sum()) if not df.empty else 0

    k1, k2, k3, k4 = st.columns(4)

    with k1:
        st.markdown(_tile("📦 จำนวน Deliverables", f"{total_dl}",
                          "รายการทั้งหมด", "#0B5ED7"), unsafe_allow_html=True)
    with k2:
        w_valid = abs(total_weight - TARGET_WEIGHT_TOTAL) < WEIGHT_TOLERANCE
        w_color = "#2E7D32" if w_valid else "#F57C00"
        w_sub = "✅ ครบ 100%" if w_valid else f"⚠️ ไม่ครบ ({total_weight:.2f}%)"
        st.markdown(_tile("⚖️ Weight รวม", f"{total_weight:.2f}%",
                          w_sub, w_color), unsafe_allow_html=True)
    with k3:
        st.markdown(_tile("🟢 เสร็จสิ้น", f"{completed}",
                          "Accepted + Closed", "#2E7D32"), unsafe_allow_html=True)
    with k4:
        st.markdown(_tile("🔵 กำลังดำเนินการ", f"{in_progress}",
                          "In Progress", "#00838F"), unsafe_allow_html=True)

    # ---- Global Warning ----
    if not w_valid and total_dl > 0:
        st.markdown(f"""
        <div style="background:#FFF8E1;border-left:4px solid #F57C00;
                    padding:10px 14px;border-radius:8px;margin-top:10px;
                    font-size:13px;color:#E65100;">
            ⚠️ <b>Weight รวม = {total_weight:.2f}%</b> — ควรปรับให้รวมได้
            100.00% เพื่อให้ Overall Progress แม่นยำ<br>
            <span style="font-size:11.5px;color:#666;">
                💡 ดูรายละเอียดที่แท็บ <b>📥 CSV & Weight Audit</b>
                หรือไปที่ <b>🔧 Settings → Rebalance Deliverable Weights</b>
            </span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ============================================================
    # TABS
    # ============================================================
    t1, t2, t3, t4 = st.tabs([
        "📋 รายการทั้งหมด",
        "✏️ เพิ่ม / แก้ไข",
        "🗑️ ลบ (Soft)",
        "📥 CSV & Weight Audit",
    ])

    # ============================================================
    # TAB 1 — LIST + FILTER + SEARCH
    # ============================================================
    with t1:
        if df.empty:
            st.info("ยังไม่มี Deliverable — ไปที่แท็บ ✏️ เพื่อเพิ่มรายการ")
        else:
            # --- Filter row ---
            f1, f2, f3, f4 = st.columns([1, 1, 1, 2])
            with f1:
                ms_filter = st.multiselect(
                    "Milestone",
                    sorted(df["milestone_id"].unique().tolist()),
                    default=sorted(df["milestone_id"].unique().tolist()),
                    key="dl_filter_ms",
                )
            with f2:
                st_filter = st.multiselect(
                    "Status",
                    STATUSES,
                    default=STATUSES,
                    key="dl_filter_st",
                )
            with f3:
                # ★ v5: เปลี่ยน Sort option ให้ชัดเจน
                sort_by = st.selectbox(
                    "Sort",
                    [
                        "📋 ตามลำดับงาน (Sequence)",   # ★ default ใหม่
                        "📈 Progress ↑",
                        "📈 Progress ↓",
                        "⚖️ Weight ↓",
                    ],
                    key="dl_sort",
                )
            with f4:
                search = st.text_input(
                    "🔍 Search (ชื่อ / TOR Clause)", value="", key="dl_search"
                )

            # --- Apply filters ---
            view = df.copy()
            if ms_filter:
                view = view[view["milestone_id"].isin(ms_filter)]
            if st_filter:
                view = view[view["status"].isin(st_filter)]
            if search.strip():
                s = search.strip().lower()
                view = view[
                    view["deliverable_name"].astype(str).str.lower().str.contains(s, na=False)
                    | view["tor_clause"].astype(str).str.lower().str.contains(s, na=False)
                    | view["deliverable_id"].astype(str).str.lower().str.contains(s, na=False)
                ]

            # --- Sort --- ★ v5
            if sort_by == "📋 ตามลำดับงาน (Sequence)":
                view = _sort_by_sequence(view)
            elif sort_by == "📈 Progress ↑":
                view = view.sort_values("_latest_progress", ascending=True)
            elif sort_by == "📈 Progress ↓":
                view = view.sort_values("_latest_progress", ascending=False)
            else:  # Weight ↓
                view = view.sort_values("weight", ascending=False)

            st.caption(
                f"แสดง {len(view)} / {len(df)} รายการ "
                f"· เรียงตาม: **{sort_by}**"
            )

            # --- Render Card-style list ---
            for idx, (_, r) in enumerate(view.iterrows(), 1):
                did = r["deliverable_id"]
                prog = float(r["_latest_progress"])
                source = str(r.get("_progress_source", "none"))
                w = float(r.get("weight", 0) or 0)
                status = str(r.get("status", "") or "")
                seq = int(r.get("_sequence", 9999))

                # สีตาม progress
                if prog >= 100:
                    p_color = "#2E7D32"
                elif prog >= 50:
                    p_color = "#0B5ED7"
                elif prog > 0:
                    p_color = "#F57C00"
                else:
                    p_color = "#9E9E9E"

                with st.container():
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(
                            f"<div style='font-size:14px;font-weight:700;color:#003366;'>"
                            f"<span style='background:#F0F4F8;color:#666;"
                            f"padding:2px 8px;border-radius:8px;font-size:11px;"
                            f"margin-right:6px;' title='sequence={seq}'>#{idx}</span>"
                            f"{did} · {r['deliverable_name']}</div>"
                            f"<div style='font-size:12px;color:#666;margin-top:2px;'>"
                            f"📌 {r['milestone_id']} · TOR {r.get('tor_clause','-')} · "
                            f"Weight <b>{w:.2f}%</b> · "
                            f"📅 {_fmt_date(r.get('planned_start'))} → {_fmt_date(r.get('planned_finish'))}"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    with c2:
                        st.markdown(
                            f"<div style='text-align:right;font-size:16px;"
                            f"font-weight:700;color:{p_color};'>"
                            f"{prog:.0f}%</div>",
                            unsafe_allow_html=True,
                        )

                    # Progress bar
                    st.markdown(_progress_bar_html(prog, p_color), unsafe_allow_html=True)

                    # Status row
                    st.markdown(
                        f"<div style='font-size:12px;color:#555;margin:6px 0 12px 0;'>"
                        f"<b>Status:</b> {_status_badge(status)} &nbsp;|&nbsp; "
                        f"<b>Compliance:</b> {_compliance_badge(r.get('compliance_status'))} &nbsp;|&nbsp; "
                        f"<b>Source:</b> {_progress_source_badge(source)} &nbsp;|&nbsp; "
                        f"<b>Reviewer:</b> {r.get('reviewer') or '-'} "
                        f"({_fmt_date(r.get('review_date'))})"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            # --- Detailed table (toggle) ---
            with st.expander("📋 ดูตารางแบบละเอียด"):
                table = view.drop(columns=DISPLAY_COLS, errors="ignore").copy()
                st.dataframe(table, use_container_width=True, hide_index=True)

    # ============================================================
    # TAB 2 — ADD / EDIT
    # ============================================================
    with t2:
        mode = st.radio(
            "โหมด",
            ["➕ เพิ่มใหม่", "✏️ แก้ไขที่มีอยู่"],
            horizontal=True,
            key="dl_mode",
        )

        def _next_dl_id() -> str:
            if df.empty:
                return "DLV-001"
            nums = []
            for x in df["deliverable_id"].astype(str):
                if x.startswith("DLV-") and x[4:].isdigit():
                    nums.append(int(x[4:]))
            return f"DLV-{(max(nums) + 1) if nums else 1:03d}"

        # ---------- ADD ----------
        if mode == "➕ เพิ่มใหม่":
            st.markdown("### ➕ เพิ่ม Deliverable ใหม่")

            # ★ v5: แสดง sequence สูงสุดปัจจุบัน
            max_seq = int(df["_sequence"].max()) if not df.empty else 0

            auto_id = _next_dl_id()
            with st.form("dl_add_form", clear_on_submit=False):
                c1, c2, c3 = st.columns(3)
                did = c1.text_input("Deliverable ID", value=auto_id, key="dl_new_id")
                msid = c2.selectbox("Milestone ID", ms_ids, key="dl_new_ms")
                clause = c3.text_input("TOR Clause", value="", key="dl_new_clause")

                # ★ v5: sequence input
                c_seq = st.number_input(
                    "ลำดับ (Sequence) — ใช้เรียงในตาราง",
                    min_value=0, max_value=9999,
                    value=max_seq + 1,
                    step=1,
                    key="dl_new_seq",
                    help="ตัวเลขน้อยจะแสดงก่อน — ระบบใช้ sequence เรียงลำดับในตาราง",
                )

                name = st.text_input("ชื่อ Deliverable", value="", key="dl_new_name")
                desc = st.text_area("คำอธิบาย", value="", height=80, key="dl_new_desc")

                c4, c5 = st.columns(2)
                out = c4.text_input("Output ที่ต้องได้", value="", key="dl_new_out")
                evi = c5.text_input("Evidence ที่ต้องส่ง", value="", key="dl_new_evi")

                c6, c7, c8 = st.columns(3)
                w = c6.number_input("Weight (%)", value=5.0, min_value=0.0, max_value=100.0,
                                     step=0.5, key="dl_new_w",
                                     help="น้ำหนักคะแนน — ระบบตรวจสอบผลรวมให้ = 100%")
                ps = c7.date_input("Planned Start", value=pd.Timestamp.today(), key="dl_new_ps")
                pf = c8.date_input("Planned Finish",
                                    value=pd.Timestamp.today() + pd.Timedelta(days=30),
                                    key="dl_new_pf")

                c9, c10 = st.columns(2)
                init_status = c9.selectbox("สถานะเริ่มต้น", STATUSES, key="dl_new_st")
                init_comp = c10.selectbox("Compliance", COMPLIANCE_STATUSES, key="dl_new_comp")

                if total_dl > 0:
                    new_total = total_weight + float(w)
                    delta = new_total - TARGET_WEIGHT_TOTAL
                    if abs(delta) < WEIGHT_TOLERANCE:
                        st.info(
                            f"💡 **Weight หลังเพิ่ม:** {new_total:.2f}% "
                            f"→ ✅ ครบ 100%"
                        )
                    else:
                        st.warning(
                            f"💡 **Weight หลังเพิ่ม:** {new_total:.2f}% "
                            f"({delta:+.2f}% จากเป้าหมาย 100%) — "
                            f"ระบบจะเตือนหลังบันทึก"
                        )

                submit = st.form_submit_button("💾 เพิ่ม Deliverable",
                                                type="primary", use_container_width=True)

            if submit:
                try:
                    row = {
                        "deliverable_id": did.strip(),
                        "milestone_id": msid,
                        "tor_clause": clause,
                        "deliverable_name": name,
                        "description": desc,
                        "required_output": out,
                        "required_evidence": evi,
                        "weight": float(w),
                        "planned_start": str(ps),
                        "planned_finish": str(pf),
                        "actual_start": "",
                        "actual_finish": "",
                        "status": init_status,
                        "compliance_status": init_comp,
                        "reviewer": "",
                        "review_date": "",
                        "review_comment": "",
                        "updated_at": now_str(),
                        "sequence": int(c_seq),   # ★ v5
                    }
                    _validate_dl(row)

                    if did.strip() in df["deliverable_id"].astype(str).values:
                        raise ValidationError(f"⚠️ รหัส `{did}` มีอยู่แล้ว — กรุณาใช้รหัสอื่น")

                    row_clean = _strip_display_cols(row)

                    repo.upsert(row_clean, key="deliverable_id")
                    append_audit(
                        st.session_state.user, "CREATE", "DELIVERABLE",
                        row_clean["deliverable_id"],
                        old_value="",
                        new_value=str(row_clean)[:500],
                        reason="เพิ่ม Deliverable ใหม่",
                    )
                    st.success(f"✅ เพิ่ม `{did}` สำเร็จ (Sequence: {int(c_seq)})")
                    st.rerun()
                except ValidationError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"❌ {type(e).__name__}: {e}")

        # ---------- EDIT ----------
        else:
            st.markdown("### ✏️ แก้ไข Deliverable")

            if df.empty:
                st.info("ยังไม่มี Deliverable ให้แก้ไข")
            else:
                # ★ v5: เรียง dropdown ตาม sequence
                df_sorted = _sort_by_sequence(df)
                dl_sel = st.selectbox(
                    "เลือก Deliverable",
                    df_sorted["deliverable_id"].tolist(),
                    format_func=lambda x: (
                        f"{x} · "
                        f"{df_sorted[df_sorted['deliverable_id']==x]['deliverable_name'].iloc[0][:60]}"
                    ),
                    key="dl_edit_sel",
                )
                r = df[df["deliverable_id"] == dl_sel].iloc[0]

                # --- Reference info ---
                info1, info2, info3 = st.columns(3)
                with info1:
                    st.markdown(f"**📌 Milestone:** `{r['milestone_id']}`  \n"
                                f"**🔗 TOR:** {r.get('tor_clause', '-')}")
                with info2:
                    prog, source = _latest_actual(
                        dl_sel, prog_df, status=r.get("status")
                    )
                    st.markdown(f"**📈 Progress:** {prog:.0f}% "
                                f"({_progress_source_badge(source)})  \n"
                                f"**⚖️ Weight:** {float(r.get('weight', 0) or 0):.2f}%")
                with info3:
                    st.markdown(f"**📅 Updated:** `{r.get('updated_at', '-')}`  \n"
                                f"**#️⃣ Sequence:** `{int(r.get('_sequence', 9999))}`")

                with st.form("dl_edit_form", clear_on_submit=False):
                    c1, c2, c3 = st.columns(3)
                    msid_options = ms_ids if r["milestone_id"] in ms_ids else [r["milestone_id"]] + ms_ids
                    msid_idx = msid_options.index(r["milestone_id"]) if r["milestone_id"] in msid_options else 0
                    msid = c1.selectbox("Milestone ID", msid_options, index=msid_idx, key="dl_edit_ms")
                    clause = c2.text_input("TOR Clause",
                                            value=str(r.get("tor_clause", "")), key="dl_edit_clause")
                    w = c3.number_input("Weight (%)",
                                         value=float(r.get("weight", 0) or 0),
                                         min_value=0.0, max_value=100.0, step=0.5,
                                         key="dl_edit_w")

                    # ★ v5: sequence edit
                    c_seq_edit = st.number_input(
                        "ลำดับ (Sequence)",
                        min_value=0, max_value=9999,
                        value=int(r.get("_sequence", 9999)),
                        step=1,
                        key="dl_edit_seq",
                        help="ตัวเลขน้อยจะแสดงก่อน",
                    )

                    name = st.text_input("ชื่อ Deliverable",
                                          value=str(r.get("deliverable_name", "")), key="dl_edit_name")
                    desc = st.text_area("คำอธิบาย",
                                         value=str(r.get("description", "")),
                                         height=80, key="dl_edit_desc")

                    c4, c5 = st.columns(2)
                    out = c4.text_input("Output ที่ต้องได้",
                                         value=str(r.get("required_output", "")), key="dl_edit_out")
                    evi = c5.text_input("Evidence ที่ต้องส่ง",
                                         value=str(r.get("required_evidence", "")), key="dl_edit_evi")

                    c6, c7 = st.columns(2)
                    ps_val = _to_date(r.get("planned_start")) or date.today()
                    pf_val = _to_date(r.get("planned_finish")) or date.today()
                    ps = c6.date_input("Planned Start", value=ps_val, key="dl_edit_ps")
                    pf = c7.date_input("Planned Finish", value=pf_val, key="dl_edit_pf")

                    c8, c9 = st.columns(2)
                    st_options = STATUSES
                    st_idx = st_options.index(r["status"]) if r["status"] in st_options else 0
                    status = c8.selectbox("สถานะ", st_options, index=st_idx, key="dl_edit_st")

                    comp_options = COMPLIANCE_STATUSES
                    comp_idx = comp_options.index(r["compliance_status"]) if r["compliance_status"] in comp_options else 0
                    comp = c9.selectbox("Compliance", comp_options, index=comp_idx, key="dl_edit_comp")

                    c10, c11 = st.columns(2)
                    reviewer = c10.text_input("Reviewer",
                                               value=str(r.get("reviewer", "")), key="dl_edit_reviewer")
                    rev_date_val = _to_date(r.get("review_date")) or date.today()
                    rev_date = c11.date_input("Review Date", value=rev_date_val, key="dl_edit_revdate")

                    rev_comment = st.text_area("Review Comment",
                                                value=str(r.get("review_comment", "")),
                                                height=80, key="dl_edit_revcomment")

                    old_w = float(r.get("weight", 0) or 0)
                    new_total = total_weight - old_w + float(w)
                    delta_preview = new_total - TARGET_WEIGHT_TOTAL
                    if abs(delta_preview) < WEIGHT_TOLERANCE:
                        st.info(
                            f"💡 **Weight รวมหลังแก้:** {new_total:.2f}% → ✅ ครบ 100%"
                        )
                    else:
                        st.warning(
                            f"💡 **Weight รวมหลังแก้:** {new_total:.2f}% "
                            f"({delta_preview:+.2f}% จากเป้าหมาย 100%)"
                        )

                    # Preview: ถ้าเปลี่ยนเป็น Accepted → actual = 100%
                    if status != r["status"]:
                        old_prog, old_src = _latest_actual(
                            dl_sel, prog_df, status=r.get("status")
                        )
                        new_prog, new_src = _latest_actual(
                            dl_sel, prog_df, status=status
                        )
                        if old_prog != new_prog:
                            st.info(
                                f"📊 **Progress จะเปลี่ยน:** "
                                f"{old_prog:.0f}% → {new_prog:.0f}% "
                                f"({_progress_source_badge(old_src)} → "
                                f"{_progress_source_badge(new_src)})"
                            )

                    c_btn1, c_btn2 = st.columns([1, 1])
                    save_edit = c_btn1.form_submit_button("💾 บันทึก",
                                                            type="primary", use_container_width=True)
                    reset_edit = c_btn2.form_submit_button("↩️ ยกเลิกการแก้ไข",
                                                             use_container_width=True)

                if reset_edit:
                    for k in ["dl_edit_ms", "dl_edit_clause", "dl_edit_w", "dl_edit_name",
                              "dl_edit_desc", "dl_edit_out", "dl_edit_evi", "dl_edit_ps",
                              "dl_edit_pf", "dl_edit_st", "dl_edit_comp", "dl_edit_reviewer",
                              "dl_edit_revdate", "dl_edit_revcomment", "dl_edit_seq"]:
                        st.session_state.pop(k, None)
                    st.rerun()

                if save_edit:
                    try:
                        new_r = _strip_display_cols(r.to_dict())
                        new_r.update({
                            "milestone_id": msid,
                            "tor_clause": clause,
                            "weight": float(w),
                            "deliverable_name": name,
                            "description": desc,
                            "required_output": out,
                            "required_evidence": evi,
                            "planned_start": str(ps),
                            "planned_finish": str(pf),
                            "status": status,
                            "compliance_status": comp,
                            "reviewer": reviewer,
                            "review_date": str(rev_date) if rev_date else "",
                            "review_comment": rev_comment,
                            "updated_at": now_str(),
                            "sequence": int(c_seq_edit),   # ★ v5
                        })
                        _validate_dl(new_r)

                        new_r = _strip_display_cols(new_r)
                        old_r = _strip_display_cols(r.to_dict())

                        repo.upsert(new_r, key="deliverable_id")
                        append_audit(
                            st.session_state.user, "UPDATE", "DELIVERABLE",
                            new_r["deliverable_id"],
                            old_value=str(old_r)[:500],
                            new_value=str(new_r)[:500],
                            reason="แก้ไข Deliverable",
                        )
                        st.success(f"✅ อัปเดต `{dl_sel}` สำเร็จ")
                        st.rerun()
                    except ValidationError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"❌ {type(e).__name__}: {e}")

    # ============================================================
    # TAB 3 — SOFT DELETE
    # ============================================================
    with t3:
        st.markdown("### 🗑️ Soft Delete (ซ่อนจาก UI)")

        if st.session_state.role not in ("admin", "monitoring"):
            st.warning("🔒 ฟังก์ชันนี้ใช้ได้เฉพาะ admin / monitoring")
        elif df.empty:
            st.info("ไม่มี Deliverable ให้ลบ")
        else:
            st.caption("⚠️ ข้อมูลยังอยู่ใน CSV — ซ่อนใน UI เท่านั้น สามารถกู้คืนได้")

            # ★ v5: เรียงตาม sequence ใน dropdown
            df_del_sorted = _sort_by_sequence(df)
            del_id = st.selectbox(
                "เลือก Deliverable ที่จะลบ",
                df_del_sorted["deliverable_id"].astype(str).tolist(),
                key="dl_del_sel",
            )
            target = df[df["deliverable_id"] == del_id].iloc[0]
            st.markdown(f"**จะลบ:** `{del_id}` — {target['deliverable_name']}  \n"
                        f"**Milestone:** {target['milestone_id']} | "
                        f"**Weight:** {target['weight']}% | "
                        f"**Seq:** {int(target.get('_sequence', 9999))}")

            reason = st.text_input("เหตุผลที่ลบ (บังคับ)", key="dl_del_reason")

            if st.button("🗑️ Soft Delete", type="primary", key="dl_btn_soft_del"):
                if not reason.strip():
                    st.error("⚠️ กรุณาระบุเหตุผล")
                else:
                    try:
                        repo.soft_delete(del_id, reason, st.session_state.user)
                        st.success(f"✅ ซ่อน `{del_id}` สำเร็จ — ดู Audit Log เพื่อยืนยัน")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ {e}")

            st.markdown("---")
            st.markdown("### ↩️ คืนค่า (Restore)")
            from core.void_registry import read_voids
            vd = read_voids()
            vd_dl = vd[vd["record_type"] == "deliverable_master"] if not vd.empty else vd

            if vd_dl.empty:
                st.info("ไม่มีรายการที่ถูก Void")
            else:
                rid = st.selectbox("เลือก ID ที่จะคืน",
                                    vd_dl["record_id"].tolist(), key="dl_restore_sel")
                if st.button("↩️ คืนค่า", key="dl_btn_restore"):
                    if repo.restore(rid, st.session_state.user):
                        st.success(f"✅ คืนค่า `{rid}` สำเร็จ")
                        st.rerun()

    # ============================================================
    # TAB 4 — CSV + ★ WEIGHT AUDIT
    # ============================================================
    with t4:
        st.markdown("### 📥 ข้อมูล CSV (อ่านเท่านั้น)")
        st.caption("ข้อมูลจริงอยู่ในไฟล์ `data/master/deliverable_master.csv`")

        # ★ v5: แสดงข้อมูลแบบเรียงตาม sequence
        df_clean = df.drop(columns=DISPLAY_COLS, errors="ignore").copy()
        df_clean = _sort_by_sequence(df)

        # แสดง # ลำดับด้วย
        df_display = df_clean.drop(columns=DISPLAY_COLS, errors="ignore").copy()
        df_display.insert(0, "#", range(1, len(df_display) + 1))

        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "⬇️ ดาวน์โหลด deliverable_master.csv",
            data=df_clean.drop(columns=DISPLAY_COLS, errors="ignore")
                .to_csv(index=False).encode("utf-8-sig"),
            file_name=f"deliverable_master_{today_str()}.csv",
            mime="text/csv",
            key="dl_download_csv",
        )

        # ═══════════════════════════════════════════════════════════
        # ★ WEIGHT AUDIT
        # ═══════════════════════════════════════════════════════════
        if not df_clean.empty:
            _render_weight_audit(
                df_clean.drop(columns=DISPLAY_COLS, errors="ignore")
            )

        if not df_clean.empty:
            with st.expander("📊 สรุปแบบย่อ (Weight by Milestone)", expanded=False):
                wsum = (
                    df_clean.drop(columns=DISPLAY_COLS, errors="ignore")
                    .groupby("milestone_id")["weight"].sum().reset_index()
                )
                wsum.columns = ["Milestone", "Weight รวม (%)"]
                wsum["Weight รวม (%)"] = wsum["Weight รวม (%)"].apply(
                    lambda x: f"{float(x):.2f}%"
                )
                st.dataframe(wsum, use_container_width=True, hide_index=True)

        # ★ v5: Sequence Viewer (debug)
        with st.expander("🔢 ตรวจสอบ Sequence (ใช้สำหรับ debug)", expanded=False):
            if df_clean.empty:
                st.info("ไม่มีข้อมูล")
            else:
                seq_view = df_clean[["deliverable_id", "milestone_id",
                                      "sequence", "_sequence",
                                      "planned_start", "deliverable_name"]].copy()
                seq_view.columns = ["ID", "Milestone", "sequence (DB)",
                                     "_sequence (calc)", "Start", "ชื่อ"]
                seq_view["ชื่อ"] = seq_view["ชื่อ"].astype(str).str.slice(0, 50)
                st.dataframe(seq_view, use_container_width=True, hide_index=True)
                st.caption(
                    "💡 `_sequence` = ค่าที่ใช้เรียงจริง · "
                    "ถ้า `sequence (DB)` = 0 หรือว่าง แสดงว่ายังไม่ได้อัปเดต "
                    "— รัน `python migrations/add_sequence_field.py`"
                )