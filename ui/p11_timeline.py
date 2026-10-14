"""Historical Timeline — Comprehensive Version (กับ Orphan Filter + Penalty)

เพิ่มความสามารถ:
- ✅ กรอง Orphaned events (อ้างถึง entity ที่ถูกลบ)
- ✅ แสดง Badge "Orphaned" สำหรับ event ที่ link ไปหาที่ถูกลบ
- ✅ Cross-reference กับ void_registry
- ⚠️ ★ แท็บ Penalty (TOR ข้อ 10) — ค่าปรับล่าช้าตาม Milestone
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta
from pathlib import Path

from repositories.progress_repo import ProgressRepo
from repositories.meeting_repo import MeetingRepo, ResolutionRepo
from repositories.action_repo import ActionRepo
from repositories.issue_repo import IssueRepo
from repositories.acceptance_repo import AcceptanceRepo
from repositories.payment_repo import PaymentRepo
from repositories.deliverable_repo import DeliverableRepo
from core.time_util import today_str
from config_loader import load_settings


# ============================================================
# CONSTANTS
# ============================================================
EVENT_MODULES = {
    "progress":    {"label": "📈 Progress",   "color": "#0B5ED7"},
    "meeting":     {"label": "📅 Meeting",    "color": "#6A1B9A"},
    "resolution":  {"label": "✅ Resolution", "color": "#2E7D32"},
    "action":      {"label": "⚡ Action",     "color": "#F57C00"},
    "issue":       {"label": "⚠️ Issue",      "color": "#D32F2F"},
    "acceptance":  {"label": "🔍 Acceptance", "color": "#00838F"},
    "payment":     {"label": "💵 Payment",    "color": "#1B5E20"},
    "review":      {"label": "🔎 Review",     "color": "#9C27B0"},
}

QUICK_RANGES = {
    "7 วันล่าสุด":   7,
    "30 วันล่าสุด":  30,
    "90 วันล่าสุด":  90,
    "180 วันล่าสุด": 180,
    "365 วันล่าสุด": 365,
}

PAGE_SIZE_OPTIONS = [25, 50, 100, 250, 500]

FINAL_MILESTONE_STATUSES = ("Accepted", "Payment Processing", "Paid", "Closed")

MILESTONE_STATUS_LABELS = {
    "Not Started":         "⚪ ยังไม่เริ่ม",
    "In Progress":         "🔵 กำลังทำ",
    "Submitted":           "🟣 ส่งแล้ว",
    "Under Review":        "🟠 กำลังตรวจ",
    "Revision Required":   "🟠 ต้องแก้ไข",
    "Ready for Acceptance":"🟢 พร้อมตรวจรับ",
    "Accepted":            "🟢 ตรวจรับแล้ว",
    "Payment Processing":  "🟡 กำลังเบิก",
    "Paid":                "✅ จ่ายแล้ว",
    "Closed":              "✅ ปิดแล้ว",
}


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


def _fmt_dt(s):
    try:
        dt = pd.to_datetime(str(s), errors="coerce")
        if pd.isna(dt):
            return str(s) if s else "-"
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(s) if s else "-"


def _fmt_date(d):
    dd = _to_date(d)
    return dd.strftime("%d/%m/%Y") if dd else "-"


def _safe_get(row, key, default=""):
    try:
        val = row.get(key, default)
        if pd.isna(val) or val in ("", None):
            return default
        return val
    except Exception:
        return default


def _shorten(s, n=80):
    if s is None:
        return ""
    s = str(s)
    return s[:n] + "…" if len(s) > n else s


def _tile(label, value, sub, color):
    return f"""
    <div style="background:#FFFFFF;border-radius:10px;padding:12px 14px;
                border-left:4px solid {color};
                box-shadow:0 2px 6px rgba(0,51,102,0.06);height:100%;">
        <div style="font-size:11.5px;color:#5A5A5A;font-weight:600;">{label}</div>
        <div style="font-size:22px;font-weight:700;color:#003366;
                    line-height:1.1;margin:4px 0;">{value}</div>
        <div style="font-size:11px;color:{color};">{sub}</div>
    </div>
    """


def _status_badge(s):
    return MILESTONE_STATUS_LABELS.get(s, s or "-")


def _get_voided_ids() -> set:
    """โหลด voided IDs ทั้งหมด"""
    try:
        from core.void_registry import get_voided_ids
        return get_voided_ids()
    except Exception:
        return set()


def _load_project():
    """โหลดข้อมูล project_master"""
    try:
        from repositories.base_repo import MasterRepo
        PROJECT_FIELDS = [
            "project_id", "project_name", "contract_no", "consultant_name",
            "contract_date", "project_start_date", "project_duration_days",
            "project_end_date", "total_contract_value", "project_manager",
            "status", "created_at", "updated_at",
        ]
        df = MasterRepo("project_master.csv", PROJECT_FIELDS).read()
        if df.empty:
            return None
        return df.iloc[0].to_dict()
    except Exception:
        return None


def _load_milestones():
    """โหลดข้อมูล milestone_master"""
    try:
        from repositories.milestone_repo import MilestoneRepo
        return MilestoneRepo().read()
    except Exception:
        return pd.DataFrame()


def _load_acceptances():
    """โหลด acceptance history"""
    try:
        return AcceptanceRepo().read()
    except Exception:
        return pd.DataFrame()


# ============================================================
# EVENT EXTRACTION
# ============================================================
def _load_events():
    """โหลด events ทั้งหมด + กรอง/ทำเครื่องหมาย Orphaned"""
    records = []
    voided_ids = _get_voided_ids()

    # ---- Progress ----
    try:
        df = ProgressRepo().read()
        if not df.empty and "timestamp" in df.columns:
            for _, r in df.iterrows():
                did = _safe_get(r, "deliverable_id")
                actual = _safe_get(r, "actual_percent", "0")
                delta = _safe_get(r, "progress_delta", "0")
                try:
                    actual_f = float(actual)
                    delta_f = float(delta)
                    detail = f"{did} → {actual_f:.1f}% (Δ {delta_f:+.1f}%)"
                except Exception:
                    detail = f"{did} → {actual}%"
                records.append({
                    "timestamp":  r.get("timestamp"),
                    "module":     "progress",
                    "ref_id":     _safe_get(r, "progress_id"),
                    "detail":     detail,
                    "user":       _safe_get(r, "created_by"),
                    "link_ms":    _safe_get(r, "milestone_id"),
                    "link_dl":    did,
                    "status":     _safe_get(r, "status"),
                    "raw":        dict(r),
                })
    except Exception:
        pass

    # ---- Meeting ----
    try:
        df = MeetingRepo().read()
        if not df.empty and "timestamp" in df.columns:
            for _, r in df.iterrows():
                m_no = _safe_get(r, "meeting_no")
                m_type = _safe_get(r, "meeting_type")
                records.append({
                    "timestamp":  r.get("timestamp"),
                    "module":     "meeting",
                    "ref_id":     _safe_get(r, "meeting_id"),
                    "detail":     f"{m_no} — {m_type} ({_safe_get(r, 'status')})",
                    "user":       _safe_get(r, "created_by"),
                    "link_ms":    _safe_get(r, "linked_milestone_ids"),
                    "link_dl":    "",
                    "status":     _safe_get(r, "status"),
                    "raw":        dict(r),
                })
    except Exception:
        pass

    # ---- Resolution ----
    try:
        df = ResolutionRepo().read()
        if not df.empty and "timestamp" in df.columns:
            for _, r in df.iterrows():
                r_no = _safe_get(r, "resolution_no")
                r_text = _shorten(_safe_get(r, "resolution_text"), 60)
                records.append({
                    "timestamp":  r.get("timestamp"),
                    "module":     "resolution",
                    "ref_id":     _safe_get(r, "resolution_id"),
                    "detail":     f"{r_no}: {r_text}",
                    "user":       _safe_get(r, "created_by"),
                    "link_ms":    "",
                    "link_dl":    "",
                    "status":     _safe_get(r, "status"),
                    "raw":        dict(r),
                })
    except Exception:
        pass

    # ---- Action ----
    try:
        df = ActionRepo().read()
        if not df.empty and "timestamp" in df.columns:
            for _, r in df.iterrows():
                pri = _safe_get(r, "priority")
                desc = _shorten(_safe_get(r, "description"), 60)
                owner = _safe_get(r, "owner")
                records.append({
                    "timestamp":  r.get("timestamp"),
                    "module":     "action",
                    "ref_id":     _safe_get(r, "action_id"),
                    "detail":     f"[{pri}] {desc} → {owner}",
                    "user":       _safe_get(r, "created_by"),
                    "link_ms":    "",
                    "link_dl":    "",
                    "status":     _safe_get(r, "status"),
                    "raw":        dict(r),
                })
    except Exception:
        pass

    # ---- Issue ----
    try:
        df = IssueRepo().read()
        if not df.empty and "timestamp" in df.columns:
            for _, r in df.iterrows():
                sev = _safe_get(r, "severity")
                desc = _shorten(_safe_get(r, "description"), 60)
                records.append({
                    "timestamp":  r.get("timestamp"),
                    "module":     "issue",
                    "ref_id":     _safe_get(r, "issue_id"),
                    "detail":     f"[{sev}] {desc}",
                    "user":       _safe_get(r, "created_by"),
                    "link_ms":    _safe_get(r, "milestone_id"),
                    "link_dl":    _safe_get(r, "deliverable_id"),
                    "status":     _safe_get(r, "status"),
                    "raw":        dict(r),
                })
    except Exception:
        pass

    # ---- Acceptance ----
    try:
        df = AcceptanceRepo().read()
        if not df.empty and "timestamp" in df.columns:
            for _, r in df.iterrows():
                ms = _safe_get(r, "milestone_id")
                st_v = _safe_get(r, "status")
                ref = _safe_get(r, "acceptance_ref")
                records.append({
                    "timestamp":  r.get("timestamp"),
                    "module":     "acceptance",
                    "ref_id":     _safe_get(r, "acceptance_id"),
                    "detail":     f"{ms} → {st_v} (Ref: {ref})",
                    "user":       _safe_get(r, "created_by") or _safe_get(r, "reviewer"),
                    "link_ms":    ms,
                    "link_dl":    "",
                    "status":     st_v,
                    "raw":        dict(r),
                })
    except Exception:
        pass

    # ---- Payment ----
    try:
        df = PaymentRepo().read()
        if not df.empty and "timestamp" in df.columns:
            for _, r in df.iterrows():
                ms = _safe_get(r, "milestone_id")
                st_v = _safe_get(r, "status")
                amt = _safe_get(r, "payment_amount", 0)
                try:
                    amt_f = float(amt)
                    amt_txt = f"{amt_f:,.0f} ฿"
                except Exception:
                    amt_txt = str(amt)
                records.append({
                    "timestamp":  r.get("timestamp"),
                    "module":     "payment",
                    "ref_id":     _safe_get(r, "payment_id"),
                    "detail":     f"{ms} → {st_v} ({amt_txt})",
                    "user":       _safe_get(r, "created_by"),
                    "link_ms":    ms,
                    "link_dl":    "",
                    "status":     st_v,
                    "raw":        dict(r),
                })
    except Exception:
        pass

    # ---- Deliverable Review ----
    try:
        from repositories.base_repo import AppendOnlyRepo
        REVIEW_FIELDS = [
            "timestamp", "review_id", "deliverable_id", "milestone_id",
            "version_no", "review_dimension", "reviewer", "review_date",
            "checklist_score", "result", "compliance_status", "comment",
            "created_by",
        ]
        try:
            rv_repo = AppendOnlyRepo("deliverable_review_history.csv", REVIEW_FIELDS)
            df = rv_repo.read()
            if not df.empty and "timestamp" in df.columns:
                for _, r in df.iterrows():
                    did = _safe_get(r, "deliverable_id")
                    ver = _safe_get(r, "version_no")
                    res = _safe_get(r, "result")
                    records.append({
                        "timestamp":  r.get("timestamp"),
                        "module":     "review",
                        "ref_id":     _safe_get(r, "review_id"),
                        "detail":     f"{did} {ver} — {res}",
                        "user":       _safe_get(r, "created_by") or _safe_get(r, "reviewer"),
                        "link_ms":    _safe_get(r, "milestone_id"),
                        "link_dl":    did,
                        "status":     res,
                        "raw":        dict(r),
                    })
        except Exception:
            pass
    except Exception:
        pass

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp_dt"])

    for col in ["module", "ref_id", "detail", "user", "link_ms", "link_dl", "status"]:
        df[col] = df[col].astype(str).fillna("")

    # ============================================================
    # ★ ORPHAN DETECTION
    # ============================================================
    def _is_orphaned(link_dl_val, link_ms_val):
        """คืน (orphaned, reason)"""
        reasons = []
        if link_dl_val and link_dl_val in voided_ids:
            reasons.append(f"deliverable {link_dl_val}")
        if link_ms_val and link_ms_val in voided_ids:
            reasons.append(f"milestone {link_ms_val}")
        if link_ms_val and "," in str(link_ms_val):
            for mid in str(link_ms_val).split(","):
                mid = mid.strip()
                if mid and mid in voided_ids:
                    reasons.append(f"milestone {mid}")
        return (len(reasons) > 0, ", ".join(reasons))

    df["orphaned"] = df.apply(
        lambda row: _is_orphaned(row["link_dl"], row["link_ms"])[0],
        axis=1,
    )
    df["orphan_reason"] = df.apply(
        lambda row: _is_orphaned(row["link_dl"], row["link_ms"])[1],
        axis=1,
    )

    return df.sort_values("timestamp_dt", ascending=False).reset_index(drop=True)


# ============================================================
# ★ PENALTY CALCULATION (TOR ข้อ 10)
# ============================================================
def _compute_penalties(ms_df, acc_df, total_value, penalty_pct, today):
    """
    คำนวณค่าปรับตาม Milestone ที่เกินกำหนด
    Returns: (overdue_rows, total_penalty, daily_penalty)
    """
    daily_penalty = total_value * penalty_pct / 100.0
    overdue = []
    total_penalty = 0.0

    if ms_df is None or ms_df.empty:
        return overdue, total_penalty, daily_penalty

    for _, m in ms_df.iterrows():
        mid = m["milestone_id"]
        due = _to_date(m.get("due_date"))
        if due is None:
            continue

        # สถานะ Milestone
        ms_status = m.get("status", "Not Started")

        # ตรวจ Acceptance ล่าสุด
        acc_status = "Not Submitted"
        if acc_df is not None and not acc_df.empty:
            sub = acc_df[acc_df["milestone_id"] == mid]
            if not sub.empty:
                sub = sub.copy()
                sub["_ts"] = pd.to_datetime(sub["timestamp"], errors="coerce")
                sub = sub.dropna(subset=["_ts"]).sort_values("_ts")
                if not sub.empty:
                    acc_status = sub.iloc[-1].get("status", "Not Submitted")

        # ถ้าปิดงานแล้ว → ไม่คิดค่าปรับ
        if ms_status in FINAL_MILESTONE_STATUSES or acc_status in FINAL_MILESTONE_STATUSES:
            continue

        days_late = (today - due).days
        if days_late <= 0:
            continue

        penalty = days_late * daily_penalty
        total_penalty += penalty
        overdue.append({
            "milestone_id":   mid,
            "milestone_no":   int(m.get("milestone_no", 0) or 0),
            "milestone_name": str(m.get("milestone_name", "")),
            "due_date":       due,
            "days_late":      days_late,
            "penalty":        penalty,
            "status":         ms_status,
            "acc_status":     acc_status,
        })

    return overdue, total_penalty, daily_penalty


# ============================================================
# MAIN RENDER
# ============================================================
def render():
    st.title("🕓 Historical Timeline")
    st.caption("ภาพรวมเหตุการณ์ทั้งหมดในระบบ — เรียงตามเวลาล่าสุดก่อน")

    with st.spinner("กำลังโหลดข้อมูล Timeline..."):
        events_df = _load_events()

    if events_df.empty:
        st.info("ℹ️ ยังไม่มีเหตุการณ์ใด ๆ ในระบบ — เริ่มบันทึกได้ที่เมนูต่าง ๆ")
        return

    # ============================================================
    # KPI TILES
    # ============================================================
    st.markdown("### 📊 ภาพรวมเหตุการณ์")

    n_total = len(events_df)
    n_orphaned = int(events_df["orphaned"].sum())
    n_active = n_total - n_orphaned

    min_ts = events_df["timestamp_dt"].min()
    max_ts = events_df["timestamp_dt"].max()
    active_days = events_df["timestamp_dt"].dt.date.nunique()

    cutoff_7d = pd.Timestamp.now() - pd.Timedelta(days=7)
    n_7d = int((events_df["timestamp_dt"] >= cutoff_7d).sum())

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(_tile("📋 ทั้งหมด", f"{n_total:,}",
                          f"{active_days} วัน active", "#0B5ED7"),
                    unsafe_allow_html=True)
    with k2:
        st.markdown(_tile("✅ Active", f"{n_active}",
                          "อ้างอิงครบถ้วน", "#2E7D32"),
                    unsafe_allow_html=True)
    with k3:
        orphan_color = "#F57C00" if n_orphaned > 0 else "#9E9E9E"
        st.markdown(_tile("⚠️ Orphaned", f"{n_orphaned}",
                          "อ้างถึงข้อมูลที่ถูกลบ" if n_orphaned else "ไม่มี",
                          orphan_color), unsafe_allow_html=True)
    with k4:
        st.markdown(_tile("📅 7 วันล่าสุด", f"{n_7d}",
                          "เหตุการณ์ใหม่", "#00838F"),
                    unsafe_allow_html=True)
    with k5:
        st.markdown(_tile("📆 ล่าสุด", max_ts.strftime("%d/%m/%Y"),
                          f"{max_ts.strftime('%H:%M')}", "#6A1B9A"),
                    unsafe_allow_html=True)

    # ---- Orphan warning banner ----
    if n_orphaned > 0:
        st.markdown(
            f"""
            <div style="background:#FFF3E0;border-left:4px solid #F57C00;
                        padding:12px 16px;border-radius:8px;font-size:12.5px;
                        margin-top:10px;color:#E65100;">
                ⚠️ <b>พบ {n_orphaned} events ที่อ้างถึงข้อมูลที่ถูกลบ</b><br>
                <span style="font-size:11.5px;">
                    ตัวอย่าง: Progress record ที่ link ไปยัง Deliverable
                    ที่ถูก Soft Delete — เป็นเรื่องปกติถ้าลบ parent entity
                    แต่ยังเหลือ child records
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ============================================================
    # TABS — เพิ่มแท็บ Penalty
    # ============================================================
    t1, t2, t3, t4, t5 = st.tabs([
        "📜 Timeline",
        "📈 Charts",
        "⚠️ Penalty (TOR ข้อ 10)",
        "🔎 Detail",
        "📥 Export",
    ])

    # ============================================================
    # TAB 1 — TIMELINE
    # ============================================================
    with t1:
        st.markdown("### 🔎 Filter")

        # ---- Orphan filter ----
        c0, c1, c2 = st.columns([1, 1, 1])
        with c0:
            orphan_filter = st.selectbox(
                "แสดง Orphaned events",
                ["ซ่อน (แนะนำ)", "แสดงทั้งหมด", "แสดงเฉพาะ Orphaned"],
                index=0,
                key="tl_orphan_filter",
            )

        with c1:
            quick_range = st.selectbox(
                "ช่วงเวลา",
                ["ทั้งหมด"] + list(QUICK_RANGES.keys()) + ["กำหนดเอง"],
                index=1,
                key="tl_quick_range",
            )

        today = date.today()
        if quick_range == "ทั้งหมด":
            default_from = min_ts.date()
            default_to = today
            disabled = True
        elif quick_range == "กำหนดเอง":
            default_from = min_ts.date()
            default_to = today
            disabled = False
        else:
            days = QUICK_RANGES[quick_range]
            default_from = today - timedelta(days=days)
            default_to = today
            disabled = True

        with c2:
            date_from = st.date_input(
                "จากวันที่",
                value=st.session_state.get("tl_date_from", default_from),
                disabled=disabled,
                key="tl_date_from",
            )

        c3, c4, c5 = st.columns([1, 1, 1])
        with c3:
            date_to = st.date_input(
                "ถึงวันที่",
                value=st.session_state.get("tl_date_to", default_to),
                disabled=disabled,
                key="tl_date_to",
            )
        with c4:
            all_modules = sorted(events_df["module"].unique().tolist())
            f_modules = st.multiselect(
                "Module",
                all_modules,
                default=all_modules,
                format_func=lambda x: EVENT_MODULES.get(x, {}).get("label", x),
                key="tl_modules",
            )
        with c5:
            sort_order = st.selectbox(
                "เรียงลำดับ",
                ["ใหม่ → เก่า", "เก่า → ใหม่"],
                key="tl_sort",
            )

        search = st.text_input(
            "🔍 Search (Ref ID / Detail / Status)",
            value="",
            key="tl_search",
        )

        # ---- Apply filters ----
        view = events_df.copy()

        if orphan_filter == "ซ่อน (แนะนำ)":
            view = view[~view["orphaned"]]
        elif orphan_filter == "แสดงเฉพาะ Orphaned":
            view = view[view["orphaned"]]

        if not disabled:
            view = view[
                (view["timestamp_dt"].dt.date >= date_from)
                & (view["timestamp_dt"].dt.date <= date_to)
            ]
        else:
            view = view[
                (view["timestamp_dt"].dt.date >= default_from)
                & (view["timestamp_dt"].dt.date <= default_to)
            ]

        if f_modules:
            view = view[view["module"].isin(f_modules)]
        else:
            view = view.iloc[0:0]

        if search.strip():
            s = search.strip().lower()
            view = view[
                view["ref_id"].astype(str).str.lower().str.contains(s, na=False)
                | view["detail"].astype(str).str.lower().str.contains(s, na=False)
                | view["status"].astype(str).str.lower().str.contains(s, na=False)
            ]

        view = view.sort_values(
            "timestamp_dt", ascending=(sort_order == "เก่า → ใหม่")
        ).reset_index(drop=True)

        # ---- Pagination ----
        st.markdown("---")
        cA, cB = st.columns([1, 3])
        with cA:
            page_size = st.selectbox(
                "แสดงหน้าละ",
                PAGE_SIZE_OPTIONS,
                index=1,
                key="tl_page_size",
            )
        total_pages = max(1, (len(view) + page_size - 1) // page_size)
        with cB:
            st.markdown(
                f"**ผลลัพธ์:** {len(view):,} / {n_total:,} events"
                + (f" · ⚠️ Orphaned: {n_orphaned}" if n_orphaned else "")
            )

        page = st.number_input(
            f"หน้า (1–{total_pages})",
            min_value=1,
            max_value=total_pages,
            value=1,
            step=1,
            key="tl_page_num",
        )

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_view = view.iloc[start_idx:end_idx]

        st.markdown("---")

        if page_view.empty:
            st.info("ไม่พบเหตุการณ์ที่ตรงกับตัวกรอง")
        else:
            current_date = None
            for _, e in page_view.iterrows():
                ev_date = e["timestamp_dt"].date()

                if ev_date != current_date:
                    current_date = ev_date
                    d_label = ev_date.strftime("%A %d/%m/%Y")
                    st.markdown(
                        f'<div style="margin:14px 0 8px 0;padding:6px 12px;'
                        f'background:#F0F4F8;border-radius:6px;'
                        f'font-size:12px;font-weight:700;color:#003366;">'
                        f'📅 {d_label}</div>',
                        unsafe_allow_html=True,
                    )

                meta = EVENT_MODULES.get(e["module"], {})
                label = meta.get("label", e["module"])
                color = meta.get("color", "#0B5ED7")

                orphan_badge = ""
                if e["orphaned"]:
                    reason = _shorten(e.get("orphan_reason", ""), 60)
                    orphan_badge = (
                        f'<span style="background:#FFF3E0;color:#E65100;'
                        f'padding:2px 8px;border-radius:10px;font-size:10px;'
                        f'margin-left:6px;border:1px solid #F57C00;" '
                        f'title="อ้างถึง: {reason}">⚠️ Orphaned</span>'
                    )
                    color = "#9E9E9E"

                time_str = e["timestamp_dt"].strftime("%H:%M")
                user_txt = f' · 👤 {e["user"]}' if e["user"] else ""
                status_txt = f' · <i>{e["status"]}</i>' if e["status"] else ""
                link_txt = ""
                if e["link_ms"]:
                    link_txt += f' · 📌 {e["link_ms"]}'
                if e["link_dl"]:
                    link_txt += f' · 📦 {e["link_dl"]}'

                opacity = "0.7" if e["orphaned"] else "1"

                st.markdown(
                    f'<div style="background:#FFFFFF;border-radius:8px;'
                    f'padding:10px 14px;border-left:4px solid {color};'
                    f'box-shadow:0 1px 4px rgba(0,51,102,0.05);'
                    f'margin-bottom:6px;opacity:{opacity};">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;flex-wrap:wrap;gap:8px;">'
                    f'<div style="font-size:12.5px;font-weight:700;color:#003366;">'
                    f'<span style="background:{color};color:#FFF;'
                    f'padding:2px 8px;border-radius:10px;font-size:10.5px;'
                    f'margin-right:6px;">{label}</span>'
                    f'<code>{e["ref_id"]}</code>'
                    f'{orphan_badge}'
                    f'</div>'
                    f'<div style="font-size:11.5px;color:#666;font-weight:600;">'
                    f'🕒 {time_str}</div></div>'
                    f'<div style="font-size:12.5px;color:#333;margin-top:6px;">'
                    f'{e["detail"]}</div>'
                    f'<div style="font-size:11px;color:#888;margin-top:4px;">'
                    f'{user_txt[3:] if user_txt else ""}{status_txt}{link_txt}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            with st.expander("📋 ตารางแบบละเอียด"):
                tbl = page_view[[
                    "timestamp", "module", "ref_id", "detail",
                    "user", "link_ms", "link_dl", "status", "orphaned",
                ]].copy()
                tbl["timestamp"] = tbl["timestamp"].apply(_fmt_dt)
                tbl["orphaned"] = tbl["orphaned"].apply(
                    lambda x: "⚠️ Yes" if x else "✅ No"
                )
                st.dataframe(tbl, use_container_width=True, hide_index=True)

    # ============================================================
    # TAB 2 — CHARTS
    # ============================================================
    with t2:
        st.markdown("### 📈 Charts สรุปกิจกรรม")

        st.markdown("#### 📊 จำนวนเหตุการณ์ต่อวัน")
        daily = (
            events_df.assign(day=events_df["timestamp_dt"].dt.date)
            .groupby("day").size().reset_index(name="count")
            .sort_values("day")
        )
        if len(daily) > 90:
            daily_view = daily.tail(90)
            st.caption(f"แสดง 90 วันล่าสุด (จากทั้งหมด {len(daily)} วัน)")
        else:
            daily_view = daily

        fig1 = go.Figure()
        fig1.add_trace(go.Bar(
            x=daily_view["day"],
            y=daily_view["count"],
            marker_color="#0B5ED7",
        ))
        fig1.update_layout(
            height=320, plot_bgcolor="#FAFBFC",
            xaxis_title="วันที่", yaxis_title="จำนวนเหตุการณ์",
            margin=dict(l=10, r=10, t=20, b=40),
        )
        st.plotly_chart(fig1, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 🥧 สัดส่วนตาม Module")
            module_counts = events_df["module"].value_counts()
            labels = [
                EVENT_MODULES.get(m, {}).get("label", m)
                for m in module_counts.index
            ]
            colors = [
                EVENT_MODULES.get(m, {}).get("color", "#0B5ED7")
                for m in module_counts.index
            ]
            fig2 = go.Figure(data=[go.Pie(
                labels=labels,
                values=module_counts.values.tolist(),
                hole=0.5,
                marker=dict(colors=colors),
            )])
            fig2.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig2, use_container_width=True)

        with c2:
            st.markdown("#### 📊 จำนวนตาม Module")
            fig3 = go.Figure(data=[go.Bar(
                x=module_counts.values.tolist(),
                y=labels,
                orientation="h",
                marker_color=colors,
                text=module_counts.values.tolist(),
                textposition="outside",
            )])
            fig3.update_layout(
                height=340, plot_bgcolor="#FAFBFC",
                xaxis_title="จำนวน",
                margin=dict(l=10, r=60, t=20, b=40),
            )
            st.plotly_chart(fig3, use_container_width=True)

        st.markdown("#### 👥 กิจกรรมตาม User (Top 10)")
        user_counts = (
            events_df[events_df["user"] != ""]["user"]
            .value_counts().head(10)
        )
        if user_counts.empty:
            st.info("ไม่มีข้อมูล User")
        else:
            fig4 = go.Figure(data=[go.Bar(
                x=user_counts.values.tolist(),
                y=user_counts.index.tolist(),
                orientation="h",
                marker_color="#6A1B9A",
                text=user_counts.values.tolist(),
                textposition="outside",
            )])
            fig4.update_layout(
                height=max(280, len(user_counts) * 38),
                plot_bgcolor="#FAFBFC",
                xaxis_title="จำนวนเหตุการณ์",
                margin=dict(l=10, r=60, t=20, b=40),
            )
            st.plotly_chart(fig4, use_container_width=True)

        if n_orphaned > 0:
            st.markdown("#### ⚠️ Orphaned Events by Module")
            orph_df = events_df[events_df["orphaned"]]
            orph_counts = orph_df["module"].value_counts()
            orph_labels = [
                EVENT_MODULES.get(m, {}).get("label", m)
                for m in orph_counts.index
            ]
            fig5 = go.Figure(data=[go.Bar(
                x=orph_counts.values.tolist(),
                y=orph_labels,
                orientation="h",
                marker_color="#F57C00",
                text=orph_counts.values.tolist(),
                textposition="outside",
            )])
            fig5.update_layout(
                height=max(240, len(orph_counts) * 38),
                plot_bgcolor="#FFF8E1",
                xaxis_title="จำนวน",
                margin=dict(l=10, r=60, t=20, b=40),
            )
            st.plotly_chart(fig5, use_container_width=True)

    # ============================================================
    # ★ TAB 3 — PENALTY (TOR ข้อ 10)
    # ============================================================
    with t3:
        st.markdown("### ⚠️ ค่าปรับล่าช้า (TOR ข้อ 10)")
        st.caption(
            "คำนวณค่าปรับตามอัตราที่กำหนดใน TOR — ใช้สำหรับการวางแผน "
            "และติดตามความเสี่ยงด้านเวลาส่งมอบ"
        )

        # ---- Load data ----
        cfg = load_settings()
        proj = _load_project()
        ms_df = _load_milestones()
        acc_df = _load_acceptances()

        if proj is None:
            st.error("❌ ไม่พบข้อมูลโครงการ — กรุณาตั้งค่าที่เมนู ⚙️ Project / Milestone")
        elif ms_df.empty:
            st.warning("⚠️ ไม่พบข้อมูล Milestone")
        else:
            total_value = float(proj.get("total_contract_value", 0) or 0)
            penalty_cfg = cfg.get("penalty", {})
            penalty_pct = float(penalty_cfg.get("late_delivery_pct_per_day", 0.10))
            daily_penalty = total_value * penalty_pct / 100.0

            # ---- Info banner ----
            st.markdown(
                f"""
                <div style="background:linear-gradient(135deg,#001233 0%,#003366 100%);
                            border-radius:12px;padding:18px 24px;color:#FFF;
                            margin-bottom:16px;">
                    <div style="font-size:12px;opacity:0.85;letter-spacing:0.4px;">
                        📋 TOR ข้อ 10 — อัตราค่าปรับ
                    </div>
                    <div style="font-size:26px;font-weight:800;margin:6px 0;">
                        {penalty_pct:.2f}% <span style="font-size:14px;font-weight:400;">ของราคาจ้างต่อวัน</span>
                    </div>
                    <div style="font-size:14px;opacity:0.95;">
                        = <b>{daily_penalty:,.2f} ฿ / วัน</b>
                        <span style="opacity:0.75;">
                            (จากราคาจ้าง {total_value:,.0f} ฿)
                        </span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ---- คำนวณค่าปรับ ----
            today = date.today()
            overdue, total_penalty, daily_penalty = _compute_penalties(
                ms_df, acc_df, total_value, penalty_pct, today,
            )

            # ---- KPI Tiles ----
            n_overdue = len(overdue)
            n_total_ms = len(ms_df)
            n_on_track = n_total_ms - n_overdue

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.markdown(_tile("📋 Milestones", f"{n_total_ms}",
                                  "งวดงานทั้งหมด", "#0B5ED7"), unsafe_allow_html=True)
            with k2:
                k2_color = "#2E7D32" if n_on_track == n_total_ms else "#F57C00"
                st.markdown(_tile("✅ ตามกำหนด", f"{n_on_track}",
                                  f"{n_on_track}/{n_total_ms} งวด", k2_color),
                            unsafe_allow_html=True)
            with k3:
                k3_color = "#D32F2F" if n_overdue > 0 else "#2E7D32"
                st.markdown(_tile("🔴 เกินกำหนด", f"{n_overdue}",
                                  "ต้องติดตามด่วน" if n_overdue > 0 else "ไม่มี",
                                  k3_color), unsafe_allow_html=True)
            with k4:
                k4_color = "#D32F2F" if total_penalty > 0 else "#2E7D32"
                st.markdown(_tile("💰 ค่าปรับสะสม", f"{total_penalty:,.0f} ฿",
                                  f"{daily_penalty:,.0f} ฿/วัน" if total_penalty > 0 else "ไม่มีค่าปรับ",
                                  k4_color), unsafe_allow_html=True)

            st.markdown("---")

            # ---- ตารางรายละเอียด ----
            if overdue:
                st.markdown("#### 📊 รายละเอียดค่าปรับแต่ละงวด")

                rows = []
                for o in overdue:
                    rows.append({
                        "Milestone":        f"M{o['milestone_no']} {o['milestone_name']}",
                        "Due Date":         _fmt_date(o["due_date"]),
                        "เกินกำหนด (วัน)":   o["days_late"],
                        "ค่าปรับ (฿)":       f"{o['penalty']:,.2f}",
                        "สถานะ":            _status_badge(o["status"]),
                    })
                st.dataframe(pd.DataFrame(rows),
                             use_container_width=True, hide_index=True)

                # ---- Total banner ----
                st.markdown(
                    f'<div style="background:#FFEBEE;border:2px solid #D32F2F;'
                    f'border-radius:10px;padding:14px 20px;margin-top:12px;">'
                    f'<div style="font-size:12px;color:#B71C1C;font-weight:600;">'
                    f'⚠️ ค่าปรับสะสมทั้งหมด (กรณีไม่ปิดงาน)</div>'
                    f'<div style="font-size:28px;font-weight:800;color:#B71C1C;'
                    f'margin:6px 0;">{total_penalty:,.2f} ฿</div>'
                    f'<div style="font-size:12px;color:#666;">'
                    f'จาก {len(overdue)} งวดที่เกินกำหนด · '
                    f'อัตรา {daily_penalty:,.2f} ฿/วัน · '
                    f'ณ วันที่ {today.strftime("%d/%m/%Y")}</div></div>',
                    unsafe_allow_html=True,
                )

                # ---- Chart ----
                st.markdown("---")
                st.markdown("#### 📊 ค่าปรับแยกตาม Milestone")

                fig = go.Figure(data=[go.Bar(
                    x=[f"M{o['milestone_no']}" for o in overdue],
                    y=[o["penalty"] for o in overdue],
                    marker_color="#D32F2F",
                    text=[f"{o['penalty']:,.0f} ฿" for o in overdue],
                    textposition="outside",
                    customdata=[
                        [o["days_late"], o["milestone_name"]]
                        for o in overdue
                    ],
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "%{customdata[1]}<br>"
                        "เกินกำหนด %{customdata[0]} วัน<br>"
                        "ค่าปรับ %{y:,.2f} ฿"
                        "<extra></extra>"
                    ),
                )])
                fig.update_layout(
                    height=380, plot_bgcolor="#FFF8F8",
                    yaxis_title="ค่าปรับ (฿)",
                    xaxis_title="Milestone",
                    margin=dict(l=10, r=10, t=20, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)

            else:
                st.markdown(
                    f"""
                    <div style="background:#E8F5E9;border:2px solid #2E7D32;
                                border-radius:12px;padding:24px;text-align:center;">
                        <div style="font-size:48px;margin-bottom:10px;">✅</div>
                        <div style="font-size:18px;font-weight:700;color:#2E7D32;">
                            ไม่มีค่าปรับ — ทุกงวดงานเป็นไปตามกำหนด
                        </div>
                        <div style="font-size:13px;color:#666;margin-top:8px;">
                            ตรวจสอบ ณ วันที่ {today.strftime('%d/%m/%Y')}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            # ---- ตาราง Milestone ทั้งหมด (Reference) ----
            st.markdown("---")
            st.markdown("#### 📋 Milestone ทั้งหมด (สำหรับอ้างอิง)")

            all_rows = []
            for _, m in ms_df.iterrows():
                due = _to_date(m["due_date"])
                days_left = (due - today).days if due else None

                if m["status"] in FINAL_MILESTONE_STATUSES:
                    time_status = "✅ ปิดงานแล้ว"
                    row_color = "#2E7D32"
                elif days_left is None:
                    time_status = "-"
                    row_color = "#9E9E9E"
                elif days_left < 0:
                    time_status = f"🔴 เกิน {-days_left} วัน"
                    row_color = "#D32F2F"
                elif days_left <= 7:
                    time_status = f"⏰ อีก {days_left} วัน"
                    row_color = "#F57C00"
                else:
                    time_status = f"📅 อีก {days_left} วัน"
                    row_color = "#0B5ED7"

                all_rows.append({
                    "Milestone":   f"M{m['milestone_no']} {m['milestone_name']}",
                    "Due Date":    _fmt_date(m["due_date"]),
                    "Payment %":   f"{float(m['payment_percent']):.1f}%",
                    "สถานะ":       _status_badge(m["status"]),
                    "เวลาคงเหลือ": time_status,
                })
            st.dataframe(pd.DataFrame(all_rows),
                         use_container_width=True, hide_index=True)

            # ---- Disclaimer ----
            st.markdown(
                f'<div style="background:#F0F4F8;border-left:4px solid #0B5ED7;'
                f'padding:12px 16px;border-radius:8px;font-size:12px;'
                f'color:#003366;margin-top:14px;">'
                f'ℹ️ <b>หมายเหตุ:</b> การคำนวณนี้เป็นการประมาณการเพื่อการวางแผน '
                f'ค่าปรับจริงเป็นไปตามที่ระบุในสัญญาและข้อตกลงระหว่างคู่สัญญา · '
                f'อัตราอ้างอิงจาก <code>config/settings.json → penalty.late_delivery_pct_per_day</code>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ============================================================
    # TAB 4 — DETAIL
    # ============================================================
    with t4:
        st.markdown("### 🔎 ดูรายละเอียดเหตุการณ์")

        ref_options = events_df["ref_id"].astype(str).tolist()
        ref_sel = st.selectbox(
            "เลือก Reference ID",
            ref_options,
            format_func=lambda x: (
                f"{x} — "
                f"{_shorten(str(events_df[events_df['ref_id']==x]['detail'].iloc[0]), 60)}"
            ),
            key="tl_detail_ref",
        )

        if ref_sel:
            row = events_df[events_df["ref_id"] == ref_sel].iloc[0]
            meta = EVENT_MODULES.get(row["module"], {})
            color = meta.get("color", "#0B5ED7")
            label = meta.get("label", row["module"])

            st.markdown(
                f'<div style="background:{color};color:#FFF;'
                f'padding:12px 18px;border-radius:10px;font-size:14px;'
                f'font-weight:700;">{label} · <code>{row["ref_id"]}</code></div>',
                unsafe_allow_html=True,
            )

            if row["orphaned"]:
                st.warning(
                    f"⚠️ **Orphaned Record** — อ้างถึง: {row.get('orphan_reason', '-')}"
                )

            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"**🕒 Timestamp:** {_fmt_dt(row['timestamp'])}")
            with c2:
                st.markdown(f"**👤 User:** {row['user'] or '-'}")
            with c3:
                st.markdown(f"**📌 Status:** {row['status'] or '-'}")

            st.markdown(f"**📝 Detail:** {row['detail']}")

            if row["link_ms"]:
                st.markdown(f"**📌 Link Milestone:** `{row['link_ms']}`")
            if row["link_dl"]:
                st.markdown(f"**📦 Link Deliverable:** `{row['link_dl']}`")

            st.markdown("---")
            st.markdown("#### 📋 Raw Data")

            raw = row["raw"]
            raw_display = {}
            for k, v in raw.items():
                if pd.isna(v) if not isinstance(v, (list, dict)) else False:
                    raw_display[k] = ""
                else:
                    raw_display[k] = str(v)

            raw_df = pd.DataFrame([
                {"Field": k, "Value": v} for k, v in raw_display.items()
            ])
            st.dataframe(raw_df, use_container_width=True, hide_index=True, height=400)

    # ============================================================
    # TAB 5 — EXPORT
    # ============================================================
    with t5:
        st.markdown("### 📥 Export Timeline")

        c1, c2 = st.columns(2)
        with c1:
            exp_from = st.date_input(
                "จากวันที่",
                value=min_ts.date(),
                key="tl_exp_from",
            )
        with c2:
            exp_to = st.date_input(
                "ถึงวันที่",
                value=max_ts.date(),
                key="tl_exp_to",
            )

        exp_modules = st.multiselect(
            "Module ที่จะ export",
            sorted(events_df["module"].unique().tolist()),
            default=sorted(events_df["module"].unique().tolist()),
            format_func=lambda x: EVENT_MODULES.get(x, {}).get("label", x),
            key="tl_exp_modules",
        )

        include_orphaned = st.checkbox(
            "รวม Orphaned events",
            value=True,
            key="tl_exp_orphan",
        )

        exp_df = events_df.copy()
        exp_df = exp_df[
            (exp_df["timestamp_dt"].dt.date >= exp_from)
            & (exp_df["timestamp_dt"].dt.date <= exp_to)
        ]
        if exp_modules:
            exp_df = exp_df[exp_df["module"].isin(exp_modules)]
        if not include_orphaned:
            exp_df = exp_df[~exp_df["orphaned"]]

        exp_view = exp_df[[
            "timestamp", "module", "ref_id", "detail",
            "user", "link_ms", "link_dl", "status", "orphaned",
        ]].copy()
        exp_view["module_label"] = exp_view["module"].apply(
            lambda x: EVENT_MODULES.get(x, {}).get("label", x)
        )

        st.markdown(f"**จะ export:** {len(exp_view):,} events")
        st.dataframe(exp_view.head(50), use_container_width=True, hide_index=True)
        if len(exp_view) > 50:
            st.caption(f"แสดงตัวอย่าง 50 แถวแรก (จาก {len(exp_view):,})")

        st.markdown("---")
        cD1, cD2 = st.columns(2)

        with cD1:
            st.download_button(
                "⬇️ ดาวน์โหลด CSV",
                data=exp_view.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"timeline_{today_str()}.csv",
                mime="text/csv",
                use_container_width=True,
                key="tl_dl_csv",
            )

        with cD2:
            try:
                json_bytes = exp_view.to_json(
                    orient="records", force_ascii=False, indent=2,
                ).encode("utf-8")
                st.download_button(
                    "⬇️ ดาวน์โหลด JSON",
                    data=json_bytes,
                    file_name=f"timeline_{today_str()}.json",
                    mime="application/json",
                    use_container_width=True,
                    key="tl_dl_json",
                )
            except Exception as e:
                st.warning(f"⚠️ สร้าง JSON ไม่สำเร็จ: {e}")