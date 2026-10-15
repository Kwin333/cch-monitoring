"""Voided Records Registry + Cleanup Tool

Components:
- 📜 Tab 1: Voided Records (Restore / Hard Delete)
- 📈 Tab 2: Charts
- 🧹 Tab 3: Cleanup Orphans (admin only)
- 📥 Tab 4: CSV Export

★ v2 — แก้ไข:
- 🔧 Fix: รองรับ `deliverable_review` / `deliverable_review_history`
- 🔧 Fix: เพิ่ม REVIEW_FIELDS ครบชุด (ใช้ร่วมกับ p04_deliverable_review.py)
- 🔧 Fix: `RECORD_TYPE_MAP` + `_get_repo_for_type()` + `_get_repo_by_name()`
- ✨ เพิ่ม REPO FACTORY กลาง (single source of truth)
- ✨ เพิ่ม support สำหรับ resolution_history, meeting_history ที่หลุด
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

from core.void_registry import (
    read_voids, remove_void, count_voids_by_type, get_voided_ids,
)
from core.audit import append_audit
from core.time_util import today_str
from core.permissions import can_hard_delete
from core.ui_helpers import render_hard_delete_form


# ============================================================
# ★ v2: REVIEW_FIELDS (ใช้ร่วมกับ p04_deliverable_review.py)
# ============================================================
REVIEW_FIELDS = [
    "timestamp", "review_id", "deliverable_id", "milestone_id", "tor_clause",
    "version_no", "review_dimension", "reviewer", "review_date",
    "checklist_1_doc", "checklist_2_content", "checklist_3_evidence",
    "checklist_4_plan", "checklist_5_milestone", "checklist_6_prev",
    "checklist_7_fixed", "checklist_8_no_pending",
    "checklist_score",
    "result", "compliance_status", "comment", "evidence_reference",
    "linked_issue_id", "next_action", "next_review_date", "created_by",
]

REVIEW_FILENAME = "deliverable_review_history.csv"


# ============================================================
# MAPPING: record_type → (หน้า, ป้ายชื่อ)
# ============================================================
RECORD_TYPE_MAP = {
    "issue":              ("⚠️ Issue Tracker",       "issue_history"),
    "issue_history":      ("⚠️ Issue Tracker",       "issue_history"),
    "action":             ("✅ Action Tracker",      "action_history"),
    "action_history":     ("✅ Action Tracker",      "action_history"),
    "progress":           ("📈 Progress Update",    "progress_history"),
    "progress_history":   ("📈 Progress Update",    "progress_history"),
    "meeting":            ("📅 ประชุมกำกับดูแล",     "meeting_history"),
    "meeting_history":    ("📅 ประชุมกำกับดูแล",     "meeting_history"),
    "resolution":         ("✅ มติที่ประชุม",        "resolution_history"),
    "resolution_history": ("✅ มติที่ประชุม",        "resolution_history"),
    "acceptance":         ("🔍 ตรวจรับ",             "acceptance_history"),
    "acceptance_history": ("🔍 ตรวจรับ",             "acceptance_history"),
    "payment":            ("💵 เบิกจ่าย",            "payment_history"),
    "payment_history":    ("💵 เบิกจ่าย",            "payment_history"),
    "deliverable":        ("📦 Deliverable Master", "deliverable_master"),
    "deliverable_master": ("📦 Deliverable Master", "deliverable_master"),
    # ★ v2: เพิ่ม Review
    "deliverable_review":         ("🔎 Deliverable Review", REVIEW_FILENAME),
    "deliverable_review_history": ("🔎 Deliverable Review", REVIEW_FILENAME),
}


# ============================================================
# CLEANUP — Orphan Detection
# ============================================================
ORPHAN_TYPES = [
    ("progress",   "📈 Progress",   "#0B5ED7"),
    ("action",     "⚡ Action",     "#F57C00"),
    ("issue",      "⚠️ Issue",      "#D32F2F"),
    ("review",     "🔎 Review",     "#9C27B0"),
    ("acceptance", "🔍 Acceptance", "#00838F"),
    ("payment",    "💵 Payment",    "#1B5E20"),
]


def _find_orphaned_records() -> dict:
    """
    ค้นหา records ที่อ้างถึง entity ที่ถูกลบ

    Returns:
        dict = {
            "progress":   [{"id": ..., "reason": ..., "detail": ..., "repo": ...}, ...],
            "action":     [...],
            ...
        }
    """
    voided = get_voided_ids()
    orphans = {k: [] for k, _, _ in ORPHAN_TYPES}

    if not voided:
        return orphans

    # ---- Progress ----
    try:
        from repositories.progress_repo import ProgressRepo
        df = ProgressRepo().read()
        for _, r in df.iterrows():
            did = str(r.get("deliverable_id", "") or "")
            mid = str(r.get("milestone_id", "") or "")
            reasons = []
            if did and did in voided:
                reasons.append(f"deliverable {did}")
            if mid and mid in voided:
                reasons.append(f"milestone {mid}")
            if reasons:
                orphans["progress"].append({
                    "id":     r.get("progress_id", ""),
                    "reason": ", ".join(reasons),
                    "detail": f"{did} → {r.get('actual_percent', '?')}%",
                    "repo":   "progress",
                })
    except Exception:
        pass

    # ---- Action ----
    try:
        from repositories.action_repo import ActionRepo
        df = ActionRepo().read()
        for _, r in df.iterrows():
            src_type = str(r.get("source_type", "") or "")
            src_id = str(r.get("source_id", "") or "")
            reasons = []
            if src_id and src_id in voided:
                reasons.append(f"source {src_type} {src_id}")
            if reasons:
                orphans["action"].append({
                    "id":     r.get("action_id", ""),
                    "reason": ", ".join(reasons),
                    "detail": f"[{r.get('priority', '?')}] "
                              f"{str(r.get('description', ''))[:50]}",
                    "repo":   "action",
                })
    except Exception:
        pass

    # ---- Issue ----
    try:
        from repositories.issue_repo import IssueRepo
        df = IssueRepo().read()
        for _, r in df.iterrows():
            did = str(r.get("deliverable_id", "") or "")
            mid = str(r.get("milestone_id", "") or "")
            reasons = []
            if did and did in voided:
                reasons.append(f"deliverable {did}")
            if mid and mid in voided:
                reasons.append(f"milestone {mid}")
            if reasons:
                orphans["issue"].append({
                    "id":     r.get("issue_id", ""),
                    "reason": ", ".join(reasons),
                    "detail": f"[{r.get('severity', '?')}] "
                              f"{str(r.get('description', ''))[:50]}",
                    "repo":   "issue",
                })
    except Exception:
        pass

    # ---- Review ----
    try:
        from repositories.base_repo import AppendOnlyRepo
        df = AppendOnlyRepo(REVIEW_FILENAME, REVIEW_FIELDS).read()
        for _, r in df.iterrows():
            did = str(r.get("deliverable_id", "") or "")
            mid = str(r.get("milestone_id", "") or "")
            reasons = []
            if did and did in voided:
                reasons.append(f"deliverable {did}")
            if mid and mid in voided:
                reasons.append(f"milestone {mid}")
            if reasons:
                orphans["review"].append({
                    "id":     r.get("review_id", ""),
                    "reason": ", ".join(reasons),
                    "detail": f"{did} {r.get('version_no', '')} — "
                              f"{r.get('result', '')}",
                    "repo":   "review",
                })
    except Exception:
        pass

    # ---- Acceptance ----
    try:
        from repositories.acceptance_repo import AcceptanceRepo
        df = AcceptanceRepo().read()
        for _, r in df.iterrows():
            mid = str(r.get("milestone_id", "") or "")
            if mid and mid in voided:
                orphans["acceptance"].append({
                    "id":     r.get("acceptance_id", ""),
                    "reason": f"milestone {mid}",
                    "detail": f"{mid} → {r.get('status', '?')}",
                    "repo":   "acceptance",
                })
    except Exception:
        pass

    # ---- Payment ----
    try:
        from repositories.acceptance_repo import PaymentRepo
        df = PaymentRepo().read()
        for _, r in df.iterrows():
            mid = str(r.get("milestone_id", "") or "")
            if mid and mid in voided:
                orphans["payment"].append({
                    "id":     r.get("payment_id", ""),
                    "reason": f"milestone {mid}",
                    "detail": f"{mid} → {r.get('status', '?')}",
                    "repo":   "payment",
                })
    except Exception:
        pass

    return orphans


# ============================================================
# ★ v2: REPO FACTORY — Single Source of Truth
# ============================================================
def _get_repo_by_name(repo_name: str):
    """
    ★ v2: คืน Repo instance จากชื่อ key (ใช้ทั้งใน Cleanup + Hard Delete)
    """
    from repositories.progress_repo import ProgressRepo
    from repositories.action_repo import ActionRepo
    from repositories.issue_repo import IssueRepo
    from repositories.acceptance_repo import AcceptanceRepo, PaymentRepo
    from repositories.meeting_repo import MeetingRepo, ResolutionRepo
    from repositories.deliverable_repo import DeliverableRepo
    from repositories.base_repo import AppendOnlyRepo

    mapping = {
        "progress":           ProgressRepo,
        "progress_history":   ProgressRepo,
        "action":             ActionRepo,
        "action_history":     ActionRepo,
        "issue":              IssueRepo,
        "issue_history":      IssueRepo,
        "acceptance":         AcceptanceRepo,
        "acceptance_history": AcceptanceRepo,
        "payment":            PaymentRepo,
        "payment_history":    PaymentRepo,
        "meeting":            MeetingRepo,
        "meeting_history":    MeetingRepo,
        "resolution":         ResolutionRepo,
        "resolution_history": ResolutionRepo,
        "deliverable":        DeliverableRepo,
        "deliverable_master": DeliverableRepo,
    }

    # ★ Review — ต้องใช้ AppendOnlyRepo + REVIEW_FIELDS
    if repo_name in ("review",
                     "deliverable_review",
                     "deliverable_review_history"):
        return AppendOnlyRepo(REVIEW_FILENAME, REVIEW_FIELDS)

    cls = mapping.get(repo_name)
    return cls() if cls else None


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


def _get_record_type_label(record_type: str) -> str:
    label, _ = RECORD_TYPE_MAP.get(record_type, (record_type, ""))
    return label


def _get_repo_for_type(record_type: str):
    """
    ★ v2: เรียกใช้ _get_repo_by_name() แทน — single source of truth
    """
    return _get_repo_by_name(record_type)


def _after_hard_delete(void_id: str):
    st.session_state.pop(f"show_hd_{void_id}", None)
    st.success("✅ ลบถาวรแล้ว — กลับสู่หน้าแรก")
    st.rerun()


# ============================================================
# RENDER
# ============================================================
def render():
    st.title("🗑️ Voided Records Registry")
    st.caption(
        "ศูนย์กลางข้อมูลที่ถูก Soft Delete — ข้อมูลยังอยู่ใน DB เสมอ "
        "สามารถกู้คืน (Restore) หรือลบถาวร (Hard Delete) ได้"
    )

    role = st.session_state.get("role", "")
    allow_hard_delete = can_hard_delete(role)

    # ---- Info banner ----
    st.markdown(
        """
        <div style="background:#E3F2FD;border-left:4px solid #0B5ED7;
                    padding:12px 16px;border-radius:8px;margin-bottom:14px;
                    font-size:12.5px;color:#0D47A1;">
            ℹ️ <b>Soft Delete = ซ่อนจาก UI เท่านั้น</b> — ข้อมูลจริงยังอยู่ใน
            <code>data/history/*.csv</code> หรือ
            <code>DB tables</code> และ <code>voided_records</code>
            ตามหลัก Audit Trail
            <br>
            🔗 <b>ไม่สับสน:</b> ทุก record ที่ถูกซ่อนจะปรากฏที่นี่ + มี badge
            ในหน้าต้นทาง
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not allow_hard_delete:
        st.markdown(
            """
            <div style="background:#FFF3E0;border-left:4px solid #F57C00;
                        padding:10px 14px;border-radius:8px;
                        font-size:12.5px;color:#E65100;margin-bottom:14px;">
                🔒 <b>Hard Delete / Cleanup Tool</b> เปิดให้เฉพาะ
                <code>admin</code> เท่านั้น
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ============================================================
    # LOAD
    # ============================================================
    void_df = read_voids()

    # ============================================================
    # TABS
    # ============================================================
    if allow_hard_delete:
        t1, t2, t3, t4 = st.tabs([
            "📜 รายการที่ถูกลบ",
            "📈 Charts",
            "🧹 Cleanup Orphans",
            "📥 CSV",
        ])
    else:
        t1, t2, t4 = st.tabs([
            "📜 รายการที่ถูกลบ",
            "📈 Charts",
            "📥 CSV",
        ])
        t3 = None

    # ============================================================
    # TAB 1 — VOIDED LIST
    # ============================================================
    with t1:
        if void_df.empty:
            st.success("✅ ไม่มีข้อมูลที่ถูก Soft Delete ในระบบ")
            st.info(
                "💡 เมื่อผู้ใช้กดปุ่ม 🗑️ ในหน้าใด ๆ รายการจะปรากฏที่นี่ "
                "พร้อมตัวเลือก Restore"
            )
        else:
            void_df = void_df.copy()
            void_df["voided_at_dt"] = pd.to_datetime(
                void_df["voided_at"], errors="coerce"
            )
            void_df = void_df.dropna(subset=["voided_at_dt"])
            void_df = void_df.sort_values(
                "voided_at_dt", ascending=False
            ).reset_index(drop=True)

            # ---- KPI ----
            st.markdown("### 📊 ภาพรวม")
            n_total = len(void_df)
            breakdown = count_voids_by_type()
            n_types = len(breakdown)
            today = date.today()
            n_today = int((void_df["voided_at_dt"].dt.date == today).sum())
            n_7d = int(
                (void_df["voided_at_dt"]
                 >= pd.Timestamp.now() - pd.Timedelta(days=7)).sum()
            )

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.markdown(_tile("🗑️ ทั้งหมด", f"{n_total}",
                                  f"{n_types} ประเภท", "#D32F2F"),
                            unsafe_allow_html=True)
            with k2:
                st.markdown(_tile("📅 วันนี้", f"{n_today}",
                                  "ถูกลบวันนี้", "#F57C00"),
                            unsafe_allow_html=True)
            with k3:
                st.markdown(_tile("📆 7 วันล่าสุด", f"{n_7d}",
                                  "ช่วง 1 สัปดาห์", "#0B5ED7"),
                            unsafe_allow_html=True)
            with k4:
                top_type = max(breakdown, key=breakdown.get) if breakdown else "-"
                top_label = _get_record_type_label(top_type)
                top_short = (
                    top_label.split(" ", 1)[-1] if " " in top_label
                    else top_label
                )
                st.markdown(_tile("🏆 ประเภทที่มากสุด", top_short,
                                  f"{breakdown.get(top_type, 0)} รายการ",
                                  "#6A1B9A"), unsafe_allow_html=True)

            st.markdown("---")

            # ---- Filters ----
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                type_options = sorted(void_df["record_type"].unique().tolist())
                f_types = st.multiselect(
                    "ประเภท",
                    type_options,
                    default=type_options,
                    format_func=_get_record_type_label,
                    key="void_f_type",
                )
            with c2:
                user_options = sorted(
                    void_df["voided_by"].astype(str).unique().tolist()
                )
                f_users = st.multiselect(
                    "ผู้ลบ",
                    user_options,
                    default=user_options,
                    key="void_f_user",
                )
            with c3:
                search = st.text_input(
                    "🔍 Search (Record ID / เหตุผล)",
                    value="", key="void_search",
                )

            view = void_df.copy()
            if f_types:
                view = view[view["record_type"].isin(f_types)]
            if f_users:
                view = view[view["voided_by"].astype(str).isin(f_users)]
            if search.strip():
                s = search.strip().lower()
                view = view[
                    view["record_id"].astype(str).str.lower().str.contains(s, na=False)
                    | view["reason"].astype(str).str.lower().str.contains(s, na=False)
                ]

            st.caption(f"แสดง {len(view)} / {n_total} รายการ")

            if view.empty:
                st.info("ไม่พบรายการที่ตรงกับตัวกรอง")

            for _, r in view.iterrows():
                label = _get_record_type_label(r["record_type"])
                vid = r["void_id"]

                st.markdown(
                    f'<div style="background:#FFFFFF;border-radius:8px;'
                    f'padding:12px 16px;border-left:4px solid #D32F2F;'
                    f'box-shadow:0 1px 4px rgba(0,51,102,0.05);'
                    f'margin-bottom:8px;">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;flex-wrap:wrap;gap:8px;">'
                    f'<div style="font-size:13px;font-weight:700;color:#003366;">'
                    f'<span style="background:#FFEBEE;color:#B71C1C;'
                    f'padding:2px 8px;border-radius:10px;font-size:10.5px;'
                    f'margin-right:6px;">🗑️ {label}</span>'
                    f'<code>{r["record_id"]}</code>'
                    f'</div>'
                    f'<div style="font-size:11.5px;color:#666;font-weight:600;">'
                    f'🕒 {_fmt_dt(r["voided_at"])}</div></div>'
                    f'<div style="font-size:12.5px;color:#333;margin-top:6px;">'
                    f'💬 <b>เหตุผล:</b> {r.get("reason", "-")}</div>'
                    f'<div style="font-size:11.5px;color:#888;margin-top:4px;">'
                    f'👤 {r.get("voided_by", "-")} · '
                    f'📌 Mode: <code>{r.get("mode", "soft")}</code>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

                if allow_hard_delete:
                    c_a, c_b, c_c = st.columns([1, 1, 1])
                else:
                    c_a, c_c = st.columns([1, 3])
                    c_b = None

                with c_a:
                    if st.button(
                        "↩️ Restore",
                        key=f"restore_{vid}",
                        use_container_width=True,
                    ):
                        try:
                            ok = remove_void(str(r["record_id"]))
                            if ok:
                                append_audit(
                                    st.session_state.user,
                                    "RESTORE", "VOID_REGISTRY",
                                    str(r["record_id"]),
                                    old_value="voided", new_value="active",
                                    reason=(
                                        f"Restore from Void Registry — "
                                        f"original reason: "
                                        f"{r.get('reason', '-')}"
                                    ),
                                )
                                st.success(f"✅ คืนค่า `{r['record_id']}` แล้ว")
                                st.rerun()
                            else:
                                st.error("❌ ไม่พบ record ที่จะคืนค่า")
                        except Exception as e:
                            st.error(f"❌ {type(e).__name__}: {e}")

                if allow_hard_delete and c_b is not None:
                    with c_b:
                        if st.button(
                            "🔴 ลบถาวร",
                            key=f"harddel_{vid}",
                            use_container_width=True,
                        ):
                            current = st.session_state.get(
                                f"show_hd_{vid}", False
                            )
                            st.session_state[f"show_hd_{vid}"] = not current
                            st.rerun()

                with c_c:
                    with st.popover("📄 รายละเอียด", use_container_width=True):
                        st.markdown(f"**Void ID:** `{r['void_id']}`")
                        st.markdown(f"**Record Type:** `{r['record_type']}`")
                        st.markdown(f"**Record ID:** `{r['record_id']}`")
                        st.markdown(f"**เหตุผล:** {r.get('reason', '-')}")
                        st.markdown(f"**ผู้ลบ:** {r.get('voided_by', '-')}")
                        st.markdown(f"**เวลาลบ:** {_fmt_dt(r.get('voided_at'))}")
                        st.markdown(f"**Mode:** `{r.get('mode', 'soft')}`")

                # ---- Hard Delete Form ----
                if allow_hard_delete and st.session_state.get(
                    f"show_hd_{vid}", False
                ):
                    repo = _get_repo_for_type(r["record_type"])
                    if repo is None:
                        st.error(
                            f"❌ ไม่พบ Repo สำหรับ `{r['record_type']}`  \n"
                            f"💡 กรุณาแจ้งผู้พัฒนาให้เพิ่ม mapping "
                            f"ใน `_get_repo_by_name()`"
                        )
                        if st.button("❌ ปิด", key=f"close_hd_{vid}"):
                            st.session_state.pop(f"show_hd_{vid}", None)
                            st.rerun()
                    else:
                        st.markdown("---")
                        render_hard_delete_form(
                            repo,
                            record_id=str(r["record_id"]),
                            record_label=f"{r['record_type']} · {r['record_id']}",
                            key_prefix=f"voidreg_hd_{vid}",
                            on_success=lambda _res, v=vid: _after_hard_delete(v),
                        )
                        if st.button("❌ ยกเลิก", key=f"cancel_hd_{vid}"):
                            st.session_state.pop(f"show_hd_{vid}", None)
                            st.rerun()
                        st.markdown("---")

    # ============================================================
    # TAB 2 — CHARTS
    # ============================================================
    with t2:
        st.markdown("### 📈 Charts")

        if void_df.empty:
            st.info("ไม่มีข้อมูลสำหรับแสดงกราฟ")
        else:
            c1, c2 = st.columns(2)

            with c1:
                st.markdown("#### 🥧 สัดส่วนตามประเภท")
                type_counts = void_df["record_type"].value_counts()
                labels = [_get_record_type_label(t) for t in type_counts.index]
                fig1 = go.Figure(data=[go.Pie(
                    labels=labels,
                    values=type_counts.values.tolist(),
                    hole=0.5,
                )])
                fig1.update_layout(
                    height=340, margin=dict(l=10, r=10, t=30, b=10),
                )
                st.plotly_chart(fig1, use_container_width=True)

            with c2:
                st.markdown("#### 👥 ผู้ลบ (Top 10)")
                user_counts = (
                    void_df["voided_by"].astype(str).value_counts().head(10)
                )
                fig2 = go.Figure(data=[go.Bar(
                    x=user_counts.values.tolist(),
                    y=user_counts.index.tolist(),
                    orientation="h",
                    marker_color="#D32F2F",
                    text=user_counts.values.tolist(),
                    textposition="outside",
                )])
                fig2.update_layout(
                    height=340, plot_bgcolor="#FAFBFC",
                    xaxis_title="จำนวน",
                    margin=dict(l=10, r=60, t=20, b=40),
                )
                st.plotly_chart(fig2, use_container_width=True)

            st.markdown("#### 📅 จำนวนการลบต่อวัน (30 วันล่าสุด)")
            daily = (
                void_df.assign(day=void_df["voided_at_dt"].dt.date)
                .groupby("day").size().reset_index(name="count")
                .sort_values("day")
            )
            if len(daily) > 30:
                daily = daily.tail(30)

            fig3 = go.Figure(data=[go.Bar(
                x=daily["day"],
                y=daily["count"],
                marker_color="#F57C00",
            )])
            fig3.update_layout(
                height=300, plot_bgcolor="#FAFBFC",
                xaxis_title="วันที่", yaxis_title="จำนวน",
                margin=dict(l=10, r=10, t=20, b=40),
            )
            st.plotly_chart(fig3, use_container_width=True)

    # ============================================================
    # TAB 3 — CLEANUP ORPHANS (admin only)
    # ============================================================
    if t3 is not None:
        with t3:
            st.markdown("### 🧹 Cleanup Orphaned Records")
            st.caption(
                "ค้นหาและลบ records ที่อ้างถึง entity ที่ถูกลบ — "
                "เหมาะสำหรับการทำความสะอาดระบบเป็นระยะ"
            )

            st.markdown(
                """
                <div style="background:#FFF8E1;border-left:4px solid #F57C00;
                            padding:12px 16px;border-radius:8px;
                            font-size:12.5px;color:#E65100;margin-bottom:14px;">
                    ⚠️ <b>Orphaned records คืออะไร?</b><br>
                    Records ที่ link ไปยัง entity ที่ถูกลบ เช่น<br>
                    • Progress ที่ link ไปยัง Deliverable ที่ถูกลบ<br>
                    • Action ที่ link ไปยัง Issue ที่ถูกลบ<br>
                    • Payment ที่ link ไปยัง Milestone ที่ถูกลบ<br>
                    <br>
                    <b>ทำไมต้อง Cleanup?</b> เพื่อให้ข้อมูลสะอาด สอดคล้อง
                    และลดความสับสนในรายงาน
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ---- Scan button ----
            col_scan, _ = st.columns([1, 3])
            with col_scan:
                scan = st.button(
                    "🔍 สแกนหา Orphans",
                    type="primary",
                    use_container_width=True,
                    key="orphan_scan",
                )

            # Cache scan result ใน session
            if scan or "orphan_scan_result" not in st.session_state:
                with st.spinner("กำลังสแกน..."):
                    st.session_state["orphan_scan_result"] = _find_orphaned_records()

            orphans = st.session_state.get("orphan_scan_result", {})

            total_orphans = sum(len(v) for v in orphans.values())

            # ---- KPI ----
            st.markdown("---")
            st.markdown("#### 📊 ผลการสแกน")

            k1, k2, k3 = st.columns(3)
            with k1:
                color = "#D32F2F" if total_orphans > 0 else "#2E7D32"
                st.markdown(_tile(
                    "🧹 Orphans ทั้งหมด", f"{total_orphans}",
                    "ต้องทำความสะอาด" if total_orphans > 0 else "สะอาด",
                    color,
                ), unsafe_allow_html=True)
            with k2:
                n_types = sum(1 for v in orphans.values() if len(v) > 0)
                st.markdown(_tile(
                    "📦 ประเภทที่มี Orphans", f"{n_types}",
                    f"จาก {len(ORPHAN_TYPES)} ประเภท",
                    "#F57C00",
                ), unsafe_allow_html=True)
            with k3:
                top_type = "-"
                top_n = 0
                for k, v in orphans.items():
                    if len(v) > top_n:
                        top_n = len(v)
                        top_type = k
                top_label = next(
                    (lbl for key, lbl, _ in ORPHAN_TYPES if key == top_type),
                    "-",
                )
                st.markdown(_tile(
                    "🏆 มากที่สุด", top_label,
                    f"{top_n} รายการ", "#6A1B9A",
                ), unsafe_allow_html=True)

            if total_orphans == 0:
                st.success("✅ ไม่พบ Orphans — ระบบสะอาด!")
            else:
                st.markdown("---")

                # ---- Breakdown by type ----
                st.markdown("#### 📋 Breakdown ตามประเภท")

                for key, label, color in ORPHAN_TYPES:
                    items = orphans.get(key, [])
                    if not items:
                        continue

                    with st.expander(
                        f"{label} — **{len(items)}** รายการ",
                        expanded=False,
                    ):
                        rows = [
                            {
                                "ID": it["id"],
                                "เหตุผล (Orphan)": it["reason"],
                                "รายละเอียด": it["detail"],
                            }
                            for it in items
                        ]
                        st.dataframe(
                            pd.DataFrame(rows),
                            use_container_width=True,
                            hide_index=True,
                        )

                st.markdown("---")

                # ---- Actions ----
                st.markdown("#### 🧹 ดำเนินการ")
                st.caption(
                    "เลือกวิธีลบ — Soft Delete = ซ่อน + กู้คืนได้, "
                    "Hard Delete = ลบถาวรพร้อม backup"
                )

                col_sd, col_hd = st.columns(2)

                with col_sd:
                    with st.expander("🟡 Soft Delete All", expanded=False):
                        st.markdown(
                            f"""
                            <div style="font-size:12.5px;color:#333;
                                        margin-bottom:8px;">
                                ซ่อน <b>{total_orphans}</b> records จาก UI<br>
                                • ข้อมูลยังอยู่ใน DB<br>
                                • กู้คืนได้จากหน้า 📜 รายการที่ถูกลบ<br>
                                • ไม่มี backup
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        sd_reason = st.text_input(
                            "เหตุผล (บังคับ)",
                            value="Cleanup orphaned records — "
                                  f"{today_str()}",
                            key="cleanup_sd_reason",
                        )

                        if st.button(
                            "🟡 Soft Delete ทั้งหมด",
                            type="primary",
                            use_container_width=True,
                            key="cleanup_sd_btn",
                        ):
                            if not sd_reason.strip():
                                st.error("⚠️ กรุณาระบุเหตุผล")
                            else:
                                _do_cleanup(
                                    orphans, mode="soft",
                                    reason=sd_reason.strip(),
                                    user=st.session_state.user,
                                )

                with col_hd:
                    with st.expander("🔴 Hard Delete All", expanded=False):
                        st.markdown(
                            f"""
                            <div style="font-size:12.5px;color:#333;
                                        margin-bottom:8px;">
                                <b>ลบถาวร {total_orphans} records</b><br>
                                • ลบทั้ง UI และ DB<br>
                                • <b>ไม่สามารถกู้คืน</b>ได้<br>
                                • มี backup ก่อนลบ
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        hd_reason = st.text_input(
                            "เหตุผล (บังคับ, ≥ 10 ตัวอักษร)",
                            value="",
                            placeholder="เช่น ทำความสะอาดระบบหลัง migration",
                            key="cleanup_hd_reason",
                        )

                        hd_confirm = st.checkbox(
                            "☑️ ข้าพเจ้ายืนยันว่าต้องการลบถาวร",
                            value=False,
                            key="cleanup_hd_confirm",
                        )

                        if st.button(
                            "🔴 Hard Delete ทั้งหมด",
                            type="primary",
                            use_container_width=True,
                            key="cleanup_hd_btn",
                        ):
                            errors = []
                            if not hd_reason.strip():
                                errors.append("❌ ต้องระบุเหตุผล")
                            elif len(hd_reason.strip()) < 10:
                                errors.append("❌ เหตุผลต้อง ≥ 10 ตัวอักษร")
                            if not hd_confirm:
                                errors.append("❌ ต้องติ๊กยืนยัน")

                            if errors:
                                for e in errors:
                                    st.error(e)
                            else:
                                _do_cleanup(
                                    orphans, mode="hard",
                                    reason=hd_reason.strip(),
                                    user=st.session_state.user,
                                )

    # ============================================================
    # TAB 4 (or 3 if not admin) — CSV EXPORT
    # ============================================================
    with t4:
        st.markdown("### 📥 Export")

        if void_df.empty:
            st.info("ไม่มีข้อมูล")
        else:
            st.dataframe(void_df, use_container_width=True, hide_index=True)

            st.download_button(
                "⬇️ ดาวน์โหลด voided_records.csv",
                data=void_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"voided_records_{today_str()}.csv",
                mime="text/csv",
                use_container_width=True,
                key="void_dl_csv",
            )

        st.markdown("---")
        st.markdown("#### 📁 ตำแหน่งไฟล์/ตารางจริง")
        st.code(
            "DB Table: deliverable_review_history  ← Review history\n"
            "DB Table: progress_history             ← Progress snapshots\n"
            "DB Table: issue_history                ← Issues\n"
            "DB Table: action_history               ← Actions\n"
            "DB Table: meeting_history              ← Meetings\n"
            "DB Table: resolution_history           ← Resolutions\n"
            "DB Table: acceptance_history           ← Acceptances\n"
            "DB Table: payment_history              ← Payments\n"
            "DB Table: deliverable_master           ← Deliverables\n"
            "DB Table: voided_records               ← รายการที่ถูกลบ\n"
            "DB Table: audit_log                    ← ประวัติทั้งหมด",
            language="text",
        )


# ============================================================
# CLEANUP EXECUTION
# ============================================================
def _do_cleanup(orphans: dict, mode: str, reason: str, user: str):
    """
    ทำ cleanup ตาม mode
    mode: "soft" | "hard"
    """
    total = sum(len(v) for v in orphans.values())

    if total == 0:
        st.warning("ไม่มี Orphans ให้ทำความสะอาด")
        return

    progress = st.progress(0, text="เริ่มทำความสะอาด...")
    stats = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "errors": [],
    }
    done = 0

    for key, label, _ in ORPHAN_TYPES:
        items = orphans.get(key, [])
        if not items:
            continue

        repo = _get_repo_by_name(items[0].get("repo", key))
        if repo is None:
            stats["errors"].append(f"ไม่พบ Repo สำหรับ {key}")
            stats["failed"] += len(items)
            continue

        for item in items:
            rid = item["id"]
            try:
                if mode == "soft":
                    repo.soft_delete(rid, reason, user)
                else:
                    repo.hard_delete(rid, reason, user)
                stats["success"] += 1
            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append(f"{rid}: {type(e).__name__}: {e}")

            done += 1
            progress.progress(
                done / total,
                text=f"กำลังทำ {done}/{total} — {key}",
            )

    progress.empty()

    # ---- Summary ----
    if stats["success"] > 0:
        st.success(
            f"✅ {mode.title()} Delete สำเร็จ — "
            f"{stats['success']}/{total} records"
        )
    if stats["failed"] > 0:
        st.error(f"❌ ล้มเหลว {stats['failed']} records")
        with st.expander("ดูรายละเอียดข้อผิดพลาด"):
            for err in stats["errors"][:50]:
                st.markdown(f"- `{err}`")

    # ---- Audit ----
    try:
        append_audit(
            user,
            "CLEANUP_ORPHANS",
            "VOID_REGISTRY",
            f"{stats['success']}/{total}",
            old_value=f"mode={mode}",
            new_value=f"cleaned {stats['success']} records",
            reason=reason,
        )
    except Exception:
        pass

    # ---- Clear cache + rerun ----
    st.session_state.pop("orphan_scan_result", None)
    st.rerun()