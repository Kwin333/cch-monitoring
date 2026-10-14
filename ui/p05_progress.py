"""Progress Update — Snapshot-based Progress Tracking (เวอร์ชันสมบูรณ์)

คุณสมบัติ:
- KPI Tiles + Overview Dashboard
- Form ครบทุก field พร้อม Dynamic Sections (C, E)
- Validation: BR-01, regression, Issue→Action, Review→Comment
- History + Filter + Search + Trend Chart
- Soft Delete (admin/monitoring)
- CSV Export

★ เวอร์ชันนี้แก้:
- C. หลักฐาน — แสดงเฉพาะเมื่อติ๊ก "มีหลักฐานประกอบ"
- E. Action — แสดงเฉพาะเมื่อติ๊ก "มี Action Required"
- ไม่มี default "Draft" หรือ default Date ที่ไม่ต้องการ
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

from core.ids import new_id
from core.time_util import now_str, today_str
from core.audit import append_audit
from core.validator import validate_progress, ValidationError
from repositories.progress_repo import ProgressRepo
from repositories.deliverable_repo import DeliverableRepo
from repositories.milestone_repo import MilestoneRepo
from repositories.meeting_repo import MeetingRepo, ResolutionRepo


# ============================================================
# CONSTANTS
# ============================================================
RISK_LEVELS = ["Low", "Medium", "High", "Critical"]
STATUS_OPTIONS = [
    "Not Started", "In Progress", "Submitted", "Under Review",
    "Revision Required", "Accepted", "Closed",
]
REVIEW_STATUSES = ["-", "Pending", "Approved", "Revision Required"]
EVIDENCE_TYPES = ["Draft", "Booked", "Minutes", "Report", "Invoice", "Photo", "Other"]

PREFIX_KEYS = ("pg_",)  # session_state keys ของหน้านี้


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


def _to_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def _latest_for_dl(prog_df, did):
    """คืน snapshot ล่าสุดของ deliverable ตาม timestamp"""
    if prog_df is None or prog_df.empty:
        return None
    sub = prog_df[prog_df["deliverable_id"] == did].copy()
    if sub.empty:
        return None
    sub["_ts"] = pd.to_datetime(sub["timestamp"], errors="coerce")
    sub = sub.dropna(subset=["_ts"]).sort_values("_ts")
    return sub.iloc[-1] if not sub.empty else None


def _progress_bar_html(pct, color="#0B5ED7", height=10):
    pct = max(0.0, min(100.0, _to_float(pct)))
    return (
        f'<div style="background:#E0E6ED;border-radius:20px;height:{height}px;overflow:hidden;">'
        f'<div style="width:{pct}%;background:{color};height:100%;border-radius:20px;"></div>'
        f'</div>'
    )


def _health(variance):
    """คืน (icon, color, label) จาก variance = actual - planned"""
    if variance >= -3:
        return "🟢", "#2E7D32", "ตามแผน"
    if variance >= -10:
        return "🟠", "#F57C00", "ล่าช้าเล็กน้อย"
    return "🔴", "#D32F2F", "ล่าช้าอย่างมีนัยสำคัญ"


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


def _validate_snapshot(data, prev_actual=None):
    """Validation เพิ่มเติมนอกเหนือจาก validate_progress"""
    # BR-01 ซ้ำ (เผื่อเรียกเดี่ยว)
    if not (0 <= data["actual_percent"] <= 100):
        raise ValidationError("BR-01: actual_percent ต้องอยู่ระหว่าง 0-100")
    if not (0 <= data["planned_percent"] <= 100):
        raise ValidationError("BR-01: planned_percent ต้องอยู่ระหว่าง 0-100")

    # Regression: actual ลดลงเกิน 5%
    if prev_actual is not None:
        drop = prev_actual - data["actual_percent"]
        if drop > 5.0:
            raise ValidationError(
                f"⚠️ Actual ลดลงจาก snapshot ก่อนหน้ามาก ({prev_actual:.1f}% → "
                f"{data['actual_percent']:.1f}%, ลดลง {drop:.1f}%) — "
                f"กรุณาตรวจสอบ (ถ้าต้องการแก้ไขจริง ให้ใช้ Soft Delete snapshot ที่ผิด)"
            )

    # Issue → ต้องมี Action
    if data["issue_flag"] == "Yes" and not (data.get("action_required") or "").strip():
        raise ValidationError("⚠️ ถ้าพบ Issue ต้องระบุ Action Required")

    # Review = Revision Required → ต้องมี Comment
    if data["review_status"] == "Revision Required" and \
       not (data.get("review_comment") or "").strip():
        raise ValidationError("⚠️ Review Status = Revision Required ต้องระบุ Comment")

    # Progress ≥ 50% → ต้องมี Evidence
    if data["actual_percent"] >= 50 and \
       not (data.get("evidence_reference") or "").strip():
        raise ValidationError("⚠️ Progress ≥ 50% ต้องมี Evidence Reference")


def _clear_form_state():
    """ล้างเฉพาะ key ของหน้านี้ (ยกเว้น selectbox หลัก)"""
    preserve = {"pg_dl_sel"}
    for k in list(st.session_state.keys()):
        if k.startswith(PREFIX_KEYS) and k not in preserve:
            st.session_state.pop(k, None)


# ============================================================
# MAIN
# ============================================================
def render():
    st.title("📈 Progress Update (Snapshot-based)")
    st.caption("บันทึกความคืบหน้าแบบ Snapshot — ทุกการบันทึกเพิ่มรายการใหม่ ไม่ทับของเดิม")

    # ---------- Repos ----------
    prog_repo = ProgressRepo()
    dl_repo = DeliverableRepo()

    dl_df = dl_repo.read()
    dl_df = dl_df[dl_df["milestone_id"].astype(str).str.startswith("MLS")].reset_index(drop=True)
    prog_df = prog_repo.read()

    if dl_df.empty:
        st.warning("⚠️ ยังไม่มี Deliverable — กรุณาเพิ่มที่เมนู **📦 Deliverable Master** ก่อน")
        return

    # ---------- Reference data ----------
    try:
        mtg_df = MeetingRepo().read()
    except Exception:
        mtg_df = pd.DataFrame()
    try:
        res_df = ResolutionRepo().read()
    except Exception:
        res_df = pd.DataFrame()

    # ---------- Precompute latest snapshot map ----------
    latest_map = {did: _latest_for_dl(prog_df, did)
                  for did in dl_df["deliverable_id"].astype(str).tolist()}

    # ============================================================
    # KPI TILES
    # ============================================================
    st.markdown("### 📊 ภาพรวมความคืบหน้า")

    n_total = len(dl_df)
    n_snapshot = len(prog_df) if not prog_df.empty else 0
    n_has = sum(1 for v in latest_map.values() if v is not None)
    n_none = n_total - n_has

    total_w, weighted = 0.0, 0.0
    on_track, behind = 0, 0
    for _, d in dl_df.iterrows():
        did = d["deliverable_id"]
        w = _to_float(d.get("weight", 0))
        latest = latest_map.get(did)
        a = _to_float(latest["actual_percent"]) if latest is not None else 0.0
        p = _to_float(latest["planned_percent"]) if latest is not None else 0.0
        total_w += w
        weighted += w * a
        if latest is not None:
            if (a - p) >= -3:
                on_track += 1
            else:
                behind += 1

    overall = (weighted / total_w) if total_w else 0.0

    def _tile(label, value, sub, color):
        return f"""
        <div style="background:#FFFFFF;border-radius:10px;padding:12px 14px;
                    border-left:4px solid {color};box-shadow:0 2px 6px rgba(0,51,102,0.06);height:100%;">
            <div style="font-size:11.5px;color:#5A5A5A;font-weight:600;">{label}</div>
            <div style="font-size:22px;font-weight:700;color:#003366;line-height:1.1;margin:4px 0;">{value}</div>
            <div style="font-size:11px;color:{color};">{sub}</div>
        </div>
        """

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(_tile("🎯 Overall Progress", f"{overall:.1f}%",
                          f"ถ่วงน้ำหนักจาก {n_total} deliverables", "#0B5ED7"),
                    unsafe_allow_html=True)
    with k2:
        st.markdown(_tile("📸 Snapshots", f"{n_snapshot}",
                          f"อัปเดตแล้ว {n_has}/{n_total} รายการ", "#00838F"),
                    unsafe_allow_html=True)
    with k3:
        st.markdown(_tile("🟢 ตามแผน", f"{on_track}",
                          "variance ≥ -3%", "#2E7D32"),
                    unsafe_allow_html=True)
    with k4:
        st.markdown(_tile("🟠 ล่าช้า", f"{behind}",
                          "variance < -3%", "#F57C00"),
                    unsafe_allow_html=True)
    with k5:
        st.markdown(_tile("⏳ ยังไม่เริ่ม", f"{n_none}",
                          "ยังไม่มี snapshot", "#9E9E9E"),
                    unsafe_allow_html=True)

    st.markdown("---")

    # ============================================================
    # TABS
    # ============================================================
    t1, t2, t3, t4 = st.tabs([
        "📊 ภาพรวม",
        "➕ บันทึก Snapshot",
        "📜 ประวัติ",
        "📥 CSV",
    ])

    # ============================================================
    # TAB 1 — OVERVIEW
    # ============================================================
    with t1:
        st.markdown("### 📋 สถานะความคืบหน้าล่าสุดแต่ละ Deliverable")

        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            ms_filter = st.multiselect(
                "Milestone",
                sorted(dl_df["milestone_id"].unique().tolist()),
                default=sorted(dl_df["milestone_id"].unique().tolist()),
                key="pg_ms_filter",
            )
        with c2:
            health_filter = st.selectbox(
                "สถานะ",
                ["ทั้งหมด", "ตามแผน (GREEN)", "ล่าช้าเล็กน้อย (YELLOW)",
                 "ล่าช้ามาก (RED)", "ยังไม่มีข้อมูล"],
                key="pg_health_filter",
            )
        with c3:
            search = st.text_input("🔍 Search (ID / ชื่อ / TOR)",
                                   value="", key="pg_search")

        view = dl_df[dl_df["milestone_id"].isin(ms_filter)].copy()
        if search.strip():
            s = search.strip().lower()
            view = view[
                view["deliverable_id"].astype(str).str.lower().str.contains(s, na=False)
                | view["deliverable_name"].astype(str).str.lower().str.contains(s, na=False)
                | view["tor_clause"].astype(str).str.lower().str.contains(s, na=False)
            ]

        rows = []
        for _, d in view.iterrows():
            did = d["deliverable_id"]
            latest = latest_map.get(did)
            if latest is not None:
                a = _to_float(latest["actual_percent"])
                p = _to_float(latest["planned_percent"])
                var = a - p
                icon, _, label = _health(var)
                upd = str(latest.get("update_date", "-"))
            else:
                a = p = var = 0.0
                icon, label = "⚪", "ยังไม่มีข้อมูล"
                upd = "—"

            rows.append({
                "Deliverable": f"{did} · {str(d['deliverable_name'])[:40]}",
                "Milestone":   d["milestone_id"],
                "TOR":         str(d.get("tor_clause", "-")),
                "Weight":      f"{_to_float(d.get('weight', 0)):.1f}%",
                "Planned":     f"{p:.1f}%" if latest is not None else "—",
                "Actual":      f"{a:.1f}%" if latest is not None else "—",
                "Δ Variance":  f"{var:+.1f}%" if latest is not None else "—",
                "สถานะ":        f"{icon} {label}",
                "อัปเดตล่าสุด":  upd,
            })

        if health_filter != "ทั้งหมด":
            key_map = {
                "ตามแผน (GREEN)": "ตามแผน",
                "ล่าช้าเล็กน้อย (YELLOW)": "ล่าช้าเล็กน้อย",
                "ล่าช้ามาก (RED)": "ล่าช้าอย่างมีนัยสำคัญ",
                "ยังไม่มีข้อมูล": "ยังไม่มีข้อมูล",
            }
            target = key_map[health_filter]
            rows = [r for r in rows if target in r["สถานะ"]]

        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(f"แสดง {len(rows)} / {len(dl_df)} รายการ")
        else:
            st.info("ไม่พบรายการที่ตรงกับตัวกรอง")

        # --- Comparison Chart ---
        st.markdown("---")
        st.markdown("### 📊 เปรียบเทียบ Planned vs Actual (snapshot ล่าสุด)")

        chart_rows = []
        for _, d in dl_df.iterrows():
            did = d["deliverable_id"]
            latest = latest_map.get(did)
            if latest is None:
                continue
            chart_rows.append({
                "name":    f"{did} · {str(d['deliverable_name'])[:30]}",
                "planned": _to_float(latest["planned_percent"]),
                "actual":  _to_float(latest["actual_percent"]),
            })

        if not chart_rows:
            st.info("ยังไม่มี snapshot เพียงพอสำหรับกราฟ")
        else:
            cv = pd.DataFrame(chart_rows).sort_values("actual", ascending=True)
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=cv["planned"], y=cv["name"], orientation="h",
                name="Planned", marker_color="#E0E6ED",
                hovertemplate="Planned: %{x:.1f}%<extra></extra>",
            ))
            fig.add_trace(go.Bar(
                x=cv["actual"], y=cv["name"], orientation="h",
                name="Actual", marker_color="#0B5ED7",
                text=cv["actual"].apply(lambda x: f"{x:.0f}%"),
                textposition="outside",
                hovertemplate="Actual: %{x:.1f}%<extra></extra>",
            ))
            fig.update_layout(
                height=max(300, len(cv) * 38),
                barmode="group",
                xaxis_title="%",
                plot_bgcolor="#FAFBFC",
                legend=dict(orientation="h", y=1.08),
                margin=dict(l=10, r=60, t=30, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)

    # ============================================================
    # TAB 2 — ADD SNAPSHOT
    # ============================================================
    with t2:
        st.markdown("### ➕ บันทึกความคืบหน้าใหม่")
        st.caption("ℹ️ ทุกการบันทึกเป็น snapshot ใหม่ — ไม่ทับของเดิม")

        # --- Select deliverable ---
        dl_sel = st.selectbox(
            "เลือก Deliverable",
            dl_df["deliverable_id"].tolist(),
            format_func=lambda x: (
                f"{x} · {dl_df[dl_df['deliverable_id'] == x]['deliverable_name'].iloc[0][:60]}"
            ),
            key="pg_dl_sel",
        )
        dl_row = dl_df[dl_df["deliverable_id"] == dl_sel].iloc[0]

        # --- Previous snapshot ---
        prev = _latest_for_dl(prog_df, dl_sel)
        prev_actual = _to_float(prev["actual_percent"]) if prev is not None else 0.0
        prev_planned = _to_float(prev["planned_percent"]) if prev is not None else 0.0

        # --- Reference info ---
        info1, info2, info3, info4 = st.columns(4)
        with info1:
            st.markdown(f"**📌 Milestone:** `{dl_row['milestone_id']}`")
        with info2:
            st.markdown(f"**🔗 TOR:** {dl_row.get('tor_clause', '-')}")
        with info3:
            st.markdown(f"**⚖️ Weight:** {_to_float(dl_row.get('weight', 0)):.1f}%")
        with info4:
            st.markdown(f"**📊 Status:** {_status_badge(dl_row.get('status'))}")

        # --- Prev snapshot banner ---
        if prev is not None:
            delta_prev = prev_actual - prev_planned
            icon, color, _ = _health(delta_prev)
            st.markdown(
                f'<div style="background:#F0F7FF;border-left:4px solid #0B5ED7;'
                f'padding:10px 14px;border-radius:8px;font-size:13px;margin:10px 0;">'
                f'📸 <b>Snapshot ล่าสุด:</b> Actual = <b>{prev_actual:.1f}%</b> '
                f'| Planned = {prev_planned:.1f}% '
                f'| Δ = {delta_prev:+.1f}% {icon} '
                f'| วันที่ {prev.get("update_date", "-")} '
                f'| โดย <code>{prev.get("created_by", "-")}</code>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.markdown(_progress_bar_html(prev_actual, color, 8), unsafe_allow_html=True)
        else:
            st.info("ℹ️ ยังไม่มี snapshot ของ Deliverable นี้ — ครั้งนี้จะเป็น **snapshot แรก** (เริ่มจาก 0%)")

        st.markdown("---")

        # ═══════════════════════════════════════════════════════
        # A. Reporting Period
        # ═══════════════════════════════════════════════════════
        st.markdown("#### A. ช่วงเวลาที่รายงาน")
        cA1, cA2 = st.columns(2)
        upd_date = cA1.date_input(
            "Update Date",
            value=pd.Timestamp.today(),
            key="pg_upd_date",
        )
        period = cA2.text_input(
            "Reporting Period (YYYY-MM)",
            value=today_str()[:7],
            key="pg_period",
        )

        # ═══════════════════════════════════════════════════════
        # B. Progress
        # ═══════════════════════════════════════════════════════
        st.markdown("#### B. ความคืบหน้า")
        cB1, cB2, cB3 = st.columns(3)
        planned = cB1.number_input(
            "Planned %",
            min_value=0.0, max_value=100.0,
            value=prev_planned, step=1.0,
            key="pg_planned",
        )
        actual = cB2.number_input(
            "Actual %",
            min_value=0.0, max_value=100.0,
            value=prev_actual, step=1.0,
            key="pg_actual",
        )
        default_stat_idx = (
            STATUS_OPTIONS.index(dl_row["status"])
            if dl_row["status"] in STATUS_OPTIONS else 1
        )
        status = cB3.selectbox(
            "สถานะ Deliverable",
            STATUS_OPTIONS,
            index=default_stat_idx,
            key="pg_status",
        )
        desc = st.text_area("รายละเอียดความคืบหน้า", height=90, key="pg_desc")

        # ═══════════════════════════════════════════════════════
        # ★ C. Evidence — DYNAMIC (เฉพาะเมื่อมีหลักฐาน)
        # ═══════════════════════════════════════════════════════
        st.markdown("#### C. หลักฐาน")

        has_evidence = st.checkbox(
            "📎 มีหลักฐานประกอบ",
            value=False,
            key="pg_has_evidence",
            help="ติ๊กเพื่อระบุ Evidence Reference และประเภทหลักฐาน",
        )

        if has_evidence:
            cC1, cC2 = st.columns(2)
            evi_ref = cC1.text_input(
                "Evidence Reference",
                value="",
                placeholder="เช่น REPORT-M1-V01, MIN-MTG-001",
                key="pg_evi_ref",
            )
            evi_type = cC2.selectbox(
                "ประเภทหลักฐาน",
                EVIDENCE_TYPES,
                key="pg_evi_type",
            )
        else:
            st.markdown(
                """
                <div style="background:#F5F5F5;border-left:4px solid #9E9E9E;
                            padding:8px 14px;border-radius:8px;font-size:12.5px;
                            color:#666;margin:4px 0;">
                    ℹ️ <b>ไม่มีหลักฐาน</b> — ไม่ต้องระบุ Reference หรือประเภท
                    <span style="color:#999;">
                    (แต่ถ้า Progress ≥ 50% ต้องติ๊กเพื่อระบุหลักฐาน)
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            evi_ref = ""
            evi_type = ""

        # ═══════════════════════════════════════════════════════
        # D. Risk / Issue
        # ═══════════════════════════════════════════════════════
        st.markdown("#### D. ความเสี่ยง / Issue")
        cD1, cD2 = st.columns(2)
        issue_flag = cD1.radio(
            "พบ Issue?",
            ["No", "Yes"],
            horizontal=True,
            key="pg_issue_flag",
        )
        risk = cD2.selectbox(
            "Risk Level",
            RISK_LEVELS,
            index=0,
            key="pg_risk",
        )

        # ═══════════════════════════════════════════════════════
        # ★ E. Action — DYNAMIC (เฉพาะเมื่อมี Action)
        # ═══════════════════════════════════════════════════════
        st.markdown("#### E. Action ที่ต้องดำเนินการ")

        has_action = st.checkbox(
            "✅ มี Action ที่ต้องดำเนินการ",
            value=False,
            key="pg_has_action",
            help="ติ๊กเพื่อระบุ Action Required, Owner และ Due Date",
        )

        if has_action:
            cE1, cE2, cE3 = st.columns(3)
            act_req = cE1.text_input(
                "Action Required",
                value="",
                placeholder="ระบุ action ที่ต้องทำ",
                key="pg_act_req",
            )
            act_owner = cE2.text_input(
                "Owner",
                value="",
                placeholder="ผู้รับผิดชอบ",
                key="pg_act_owner",
            )
            act_due = cE3.date_input(
                "Action Due",
                value=pd.Timestamp.today() + pd.Timedelta(days=7),
                key="pg_act_due",
            )
        else:
            st.markdown(
                """
                <div style="background:#F5F5F5;border-left:4px solid #9E9E9E;
                            padding:8px 14px;border-radius:8px;font-size:12.5px;
                            color:#666;margin:4px 0;">
                    ℹ️ <b>ไม่มี Action</b> — ไม่ต้องระบุ Owner หรือ Due Date
                </div>
                """,
                unsafe_allow_html=True,
            )
            act_req = ""
            act_owner = ""
            act_due = None

        # ═══════════════════════════════════════════════════════
        # F. Links (ข้อ 1.3)
        # ═══════════════════════════════════════════════════════
        st.markdown("#### F. ความเชื่อมโยง (ข้อ 1.3)")
        cF1, cF2 = st.columns(2)
        mtg_opts = ["-"] + (
            mtg_df["meeting_id"].astype(str).tolist() if not mtg_df.empty else []
        )
        res_opts = ["-"] + (
            res_df["resolution_id"].astype(str).tolist() if not res_df.empty else []
        )
        mtg_ref = cF1.selectbox("Meeting Reference", mtg_opts, key="pg_mtg_ref")
        res_ref = cF2.selectbox("Resolution Reference", res_opts, key="pg_res_ref")

        # ═══════════════════════════════════════════════════════
        # G. Review
        # ═══════════════════════════════════════════════════════
        st.markdown("#### G. การตรวจสอบ")
        cG1, cG2 = st.columns(2)
        reviewer = cG1.text_input("Reviewer", value="", key="pg_reviewer")
        rev_stat = cG2.selectbox("Review Status", REVIEW_STATUSES, key="pg_rev_stat")
        rev_comment = st.text_area("Review Comment", height=70, key="pg_rev_comment")

        # ═══════════════════════════════════════════════════════
        # BUTTONS
        # ═══════════════════════════════════════════════════════
        st.markdown("---")
        c_btn1, c_btn2 = st.columns([1, 1])

        with c_btn1:
            submitted = st.button(
                "💾 บันทึก Snapshot",
                type="primary",
                use_container_width=True,
                key="pg_submit_btn",
            )
        with c_btn2:
            reset_clicked = st.button(
                "↩️ ล้างฟอร์ม",
                use_container_width=True,
                key="pg_reset_btn",
            )

        # ---- Reset ----
        if reset_clicked:
            _clear_form_state()
            st.rerun()

        # ---- Save ----
        if submitted:
            try:
                # BR-01
                validate_progress(actual, planned)

                # Extra validation
                _validate_snapshot(
                    {
                        "actual_percent":    float(actual),
                        "planned_percent":   float(planned),
                        "issue_flag":        issue_flag,
                        "action_required":   act_req,
                        "review_status":     rev_stat,
                        "review_comment":    rev_comment,
                        "evidence_reference": evi_ref,
                    },
                    prev_actual if prev is not None else None,
                )

                delta = float(actual) - prev_actual
                pid = new_id("progress")

                # version_no = นับ snapshot ของ deliverable นี้ + 1
                n_prev = 0 if prog_df.empty else int(
                    (prog_df["deliverable_id"] == dl_sel).sum()
                )
                version_no = f"v{n_prev + 1}"

                # ★ act_due อาจเป็น None ถ้าไม่มี Action
                act_due_str = str(act_due) if act_due else ""

                row = {
                    "timestamp":            now_str(),
                    "progress_id":          pid,
                    "project_id":           "PRJ-2026-0001",
                    "milestone_id":         dl_row["milestone_id"],
                    "deliverable_id":       dl_sel,
                    "tor_clause":           str(dl_row.get("tor_clause", "")),
                    "update_date":          str(upd_date),
                    "reporting_period":     period,
                    "planned_percent":      float(planned),
                    "actual_percent":       float(actual),
                    "progress_delta":       delta,
                    "status":               status,
                    "progress_description": desc,
                    "evidence_reference":   evi_ref,
                    "evidence_type":        evi_type,
                    "issue_flag":           issue_flag,
                    "risk_level":           risk,
                    "action_required":      act_req,
                    "action_owner":         act_owner,
                    "action_due_date":      act_due_str,
                    "meeting_reference":    "" if mtg_ref == "-" else mtg_ref,
                    "resolution_reference": "" if res_ref == "-" else res_ref,
                    "reviewer":             reviewer,
                    "review_date":          str(upd_date) if rev_stat != "-" and reviewer.strip() else "",
                    "review_status":        rev_stat,
                    "review_comment":       rev_comment,
                    "created_by":           st.session_state.user,
                    "version_no":           version_no,
                }

                prog_repo.append(row)

                append_audit(
                    st.session_state.user,
                    "CREATE", "PROGRESS", pid,
                    old_value=f"{prev_actual:.1f}%",
                    new_value=f"{float(actual):.1f}%",
                    reason=f"Snapshot {version_no} — Δ{delta:+.1f}%",
                )

                st.success(
                    f"✅ บันทึก Snapshot `{pid}` ({version_no}) สำเร็จ — "
                    f"Actual: **{float(actual):.1f}%** (Δ{delta:+.1f}%)"
                )
                st.rerun()

            except ValidationError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"❌ {type(e).__name__}: {e}")

    # ============================================================
    # TAB 3 — HISTORY
    # ============================================================
    with t3:
        st.markdown("### 📜 ประวัติ Snapshot ทั้งหมด")

        if prog_df.empty:
            st.info("ยังไม่มี snapshot — เริ่มบันทึกที่แท็บ **➕ บันทึก Snapshot**")
        else:
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            with c1:
                dl_h_filter = st.multiselect(
                    "Deliverable",
                    sorted(prog_df["deliverable_id"].unique().tolist()),
                    default=sorted(prog_df["deliverable_id"].unique().tolist()),
                    key="pgh_dl_filter",
                )
            with c2:
                st_h_filter = st.multiselect(
                    "Status",
                    STATUS_OPTIONS,
                    default=STATUS_OPTIONS,
                    key="pgh_st_filter",
                )
            with c3:
                sort_h = st.selectbox(
                    "เรียงตาม",
                    ["ใหม่ → เก่า", "เก่า → ใหม่"],
                    key="pgh_sort",
                )
            with c4:
                date_from = st.date_input(
                    "ตั้งแต่วันที่",
                    value=pd.Timestamp.today() - pd.Timedelta(days=180),
                    key="pgh_date_from",
                )

            h_view = prog_df.copy()
            h_view["_ts"] = pd.to_datetime(h_view["timestamp"], errors="coerce")
            h_view = h_view.dropna(subset=["_ts"])

            if dl_h_filter:
                h_view = h_view[h_view["deliverable_id"].isin(dl_h_filter)]
            if st_h_filter:
                h_view = h_view[h_view["status"].isin(st_h_filter)]
            h_view = h_view[h_view["_ts"].dt.date >= date_from]

            h_view = h_view.sort_values("_ts", ascending=(sort_h == "เก่า → ใหม่"))

            show_cols = [c for c in [
                "timestamp", "progress_id", "deliverable_id", "version_no",
                "update_date", "reporting_period",
                "planned_percent", "actual_percent", "progress_delta",
                "status", "evidence_reference",
                "reviewer", "review_status", "created_by",
            ] if c in h_view.columns]

            st.caption(f"แสดง {len(h_view)} / {len(prog_df)} snapshots")
            st.dataframe(
                h_view[show_cols],
                use_container_width=True,
                hide_index=True,
            )

            # --- Soft Delete ---
            if st.session_state.role in ("admin", "monitoring"):
                with st.expander("🗑️ ลบ Snapshot (Soft Delete)", expanded=False):
                    st.caption("⚠️ ซ่อนจาก UI แต่ข้อมูลยังอยู่ใน CSV — Audit ยังคงครบ")
                    ids = prog_df["progress_id"].astype(str).tolist()
                    if ids:
                        del_id = st.selectbox("เลือก Progress ID",
                                              ids, key="pgh_del_sel")
                        del_reason = st.text_input("เหตุผลที่ลบ (บังคับ)",
                                                   key="pgh_del_reason")
                        if st.button("🗑️ Soft Delete", type="primary", key="pgh_del_btn"):
                            if not del_reason.strip():
                                st.error("⚠️ กรุณาระบุเหตุผล")
                            else:
                                try:
                                    prog_repo.soft_delete(
                                        del_id, del_reason, st.session_state.user
                                    )
                                    st.success(f"✅ ซ่อน `{del_id}` แล้ว — ดู Audit Log")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ {e}")

            # --- Trend Chart ---
            st.markdown("---")
            st.markdown("### 📈 แนวโน้มความคืบหน้า (Trend)")

            chart_dl = st.selectbox(
                "เลือก Deliverable",
                sorted(prog_df["deliverable_id"].unique().tolist()),
                key="pgh_chart_dl",
            )
            sub = prog_df[prog_df["deliverable_id"] == chart_dl].copy()
            sub["_ts"] = pd.to_datetime(sub["timestamp"], errors="coerce")
            sub = sub.dropna(subset=["_ts"]).sort_values("_ts")

            if sub.empty:
                st.info("ไม่มีข้อมูล")
            else:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=sub["_ts"], y=sub["actual_percent"],
                    mode="lines+markers", name="Actual %",
                    line=dict(color="#D32F2F", width=3),
                    marker=dict(size=8),
                    hovertemplate="Actual: %{y:.1f}%<extra></extra>",
                ))
                fig.add_trace(go.Scatter(
                    x=sub["_ts"], y=sub["planned_percent"],
                    mode="lines+markers", name="Planned %",
                    line=dict(color="#0B5ED7", width=2, dash="dash"),
                    marker=dict(size=6),
                    hovertemplate="Planned: %{y:.1f}%<extra></extra>",
                ))
                fig.update_layout(
                    height=350, plot_bgcolor="#FAFBFC",
                    yaxis_title="%", xaxis_title="Timestamp",
                    legend=dict(orientation="h", y=1.1),
                    hovermode="x unified",
                )
                st.plotly_chart(fig, use_container_width=True)

    # ============================================================
    # TAB 4 — CSV
    # ============================================================
    with t4:
        st.markdown("### 📥 ข้อมูล CSV (อ่านเท่านั้น)")
        st.caption("ไฟล์จริง: `data/history/progress_history.csv`")

        if prog_df.empty:
            st.info("ยังไม่มีข้อมูล")
        else:
            st.dataframe(prog_df, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ ดาวน์โหลด progress_history.csv",
                data=prog_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"progress_history_{today_str()}.csv",
                mime="text/csv",
                key="pg_dl_csv",
            )