"""ตรวจรับงานตามงวด (ข้อ 1.5) — Comprehensive Version

ครอบคลุม:
- 📊 KPI Dashboard: Milestones, Accepted, Pending, Blocked, Payment Ready
- 🔍 Pre-condition checks: Deliverable Reviews, Open Issues, Overdue Actions
- ➕ Acceptance form + Committee members + File upload + Auto revision_round
- 📜 History + Filter + Detail viewer + Soft Delete + Restore
- 📈 Charts: Status distribution, Payment timeline
- 🔗 Integration: p04 (deliverable reviews), p08 (issues), p10 (payment readiness)
- 📥 CSV Export
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta
from pathlib import Path

from core.ids import new_id
from core.time_util import now_str, today_str
from core.audit import append_audit
from core.validator import ValidationError, validate_payment_flow
from repositories.acceptance_repo import AcceptanceRepo, PaymentRepo
from repositories.deliverable_repo import DeliverableRepo
from repositories.milestone_repo import MilestoneRepo
from repositories.progress_repo import ProgressRepo
from repositories.issue_repo import IssueRepo
from repositories.action_repo import ActionRepo
from repositories.base_repo import AppendOnlyRepo


# ============================================================
# CONSTANTS
# ============================================================
CHECKLIST_ITEMS = [
    ("chk_1_tor_doc",     "มีเอกสารครบตาม TOR"),
    ("chk_2_content",     "เนื้อหาครบถ้วนตามขอบเขตงาน"),
    ("chk_3_evidence",    "มีหลักฐานประกอบครบถ้วน"),
    ("chk_4_plan",        "สอดคล้องกับแผนงานที่วางไว้"),
    ("chk_5_milestone",   "สอดคล้องกับ Milestone และงวดงาน"),
    ("chk_6_prev",        "สอดคล้องกับงานในงวดก่อนหน้า"),
    ("chk_7_fixed",       "มีการแก้ไขตามข้อสังเกตเดิมแล้ว"),
    ("chk_8_no_pending",  "ไม่มีประเด็นค้างที่กระทบการตรวจรับ"),
]

TOR_COMPLIANCE = [
    "Compliant",
    "Partially Compliant",
    "Non-Compliant",
]

REVIEW_RESULTS = [
    "ผ่าน",
    "ผ่านโดยมีข้อสังเกต",
    "ต้องแก้ไข",
    "ไม่ผ่าน",
]

ACCEPTANCE_STATUSES = [
    "Submitted",
    "Completeness Checked",
    "Under Review",
    "Revision Required",
    "Ready for Acceptance",
    "Accepted",
    "Payment Processing",
    "Paid",
    "Closed",
]

# Statuses ที่ผ่านการตรวจรับแล้ว (final)
FINAL_STATUSES = ("Accepted", "Payment Processing", "Paid", "Closed")

# Roles ที่อนุมัติได้
APPROVAL_ROLES = ("admin", "monitoring", "committee", "supervisor")

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


def _today():
    return date.today()


def _reset_keys(prefix, preserve=()):
    for k in list(st.session_state.keys()):
        if k.startswith(prefix) and k not in preserve:
            st.session_state.pop(k, None)


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
    m = {
        "Submitted": "🟣 ส่งแล้ว",
        "Completeness Checked": "🔵 ตรวจความครบถ้วนแล้ว",
        "Under Review": "🟠 กำลังตรวจ",
        "Revision Required": "🟠 ต้องแก้ไข",
        "Ready for Acceptance": "🟡 พร้อมตรวจรับ",
        "Accepted": "🟢 ตรวจรับแล้ว",
        "Payment Processing": "💰 กำลังเบิก",
        "Paid": "✅ จ่ายแล้ว",
        "Closed": "✅ ปิด",
    }
    return m.get(s, s or "-")


def _result_badge(r):
    return {
        "ผ่าน": "🟢 ผ่าน",
        "ผ่านโดยมีข้อสังเกต": "🟡 ผ่าน (มีข้อสังเกต)",
        "ต้องแก้ไข": "🟠 ต้องแก้ไข",
        "ไม่ผ่าน": "🔴 ไม่ผ่าน",
        "รอตรวจ": "⚪ รอตรวจ",
    }.get(r, r or "-")


def _latest_review_per_dl(review_df):
    """คืน dict: deliverable_id → row (latest)"""
    if review_df is None or review_df.empty:
        return {}
    df = review_df.copy()
    df["_ts"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["_ts"]).sort_values("_ts")
    return {did: sub.iloc[-1] for did, sub in df.groupby("deliverable_id")}


def _latest_progress_per_dl(prog_df):
    if prog_df is None or prog_df.empty:
        return {}
    df = prog_df.copy()
    df["_ts"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["_ts"]).sort_values("_ts")
    return {did: sub.iloc[-1] for did, sub in df.groupby("deliverable_id")}


# ============================================================
# PRE-CONDITION CHECKS
# ============================================================
def _run_prechecks(milestone_id, dl_df, review_df, iss_df, act_df, prog_df):
    """รัน pre-condition checks ทั้งหมดของ milestone → dict"""
    results = {
        "deliverables": {"status": "ok", "msg": "", "details": []},
        "issues":       {"status": "ok", "msg": "", "details": []},
        "actions":      {"status": "ok", "msg": "", "details": []},
        "progress":     {"status": "ok", "msg": "", "details": []},
    }

    # 1) Deliverables reviews
    m_dl = dl_df[dl_df["milestone_id"] == milestone_id] if not dl_df.empty else pd.DataFrame()
    if m_dl.empty:
        results["deliverables"] = {
            "status": "warn",
            "msg": "ไม่พบ Deliverable ใน milestone นี้",
            "details": [],
        }
    else:
        latest_rv = _latest_review_per_dl(review_df)
        not_passed = []
        for _, d in m_dl.iterrows():
            did = d["deliverable_id"]
            row = latest_rv.get(did)
            if row is None:
                not_passed.append((did, "ยังไม่ตรวจ"))
            elif row.get("result") not in ("ผ่าน", "ผ่านโดยมีข้อสังเกต"):
                not_passed.append((did, row.get("result", "-")))
        if not_passed:
            results["deliverables"] = {
                "status": "fail",
                "msg": f"{len(not_passed)}/{len(m_dl)} deliverable ยังไม่ผ่านการ review",
                "details": not_passed,
            }
        else:
            results["deliverables"] = {
                "status": "ok",
                "msg": f"Deliverable ทั้ง {len(m_dl)} รายการ ผ่านการ review แล้ว",
                "details": [],
            }

    # 2) Open Issues (Critical/High) in this milestone
    if iss_df is not None and not iss_df.empty:
        m_iss = iss_df[
            (iss_df["milestone_id"] == milestone_id)
            & (~iss_df["status"].isin(["Closed", "Cancelled"]))
            & (iss_df["severity"].isin(["Critical", "High"]))
        ]
        if not m_iss.empty:
            details = [
                (r["issue_id"], f"{r['severity']} — {str(r['description'])[:60]}")
                for _, r in m_iss.iterrows()
            ]
            results["issues"] = {
                "status": "fail",
                "msg": f"มี {len(m_iss)} issue ระดับ Critical/High ที่ยังเปิดอยู่",
                "details": details,
            }
        else:
            results["issues"] = {
                "status": "ok",
                "msg": "ไม่มี Critical/High issue ที่เปิดอยู่",
                "details": [],
            }
    else:
        results["issues"] = {
            "status": "ok",
            "msg": "ไม่มี Issue ในระบบ",
            "details": [],
        }

    # 3) Overdue actions related to this milestone
    if act_df is not None and not act_df.empty:
        m_dl_ids = set(m_dl["deliverable_id"].astype(str).tolist()) if not m_dl.empty else set()
        today = _today()
        overdue = []
        for _, a in act_df.iterrows():
            if a.get("status") in ("Completed", "Cancelled"):
                continue
            dd = _to_date(a.get("due_date"))
            if dd is None or dd >= today:
                continue
            # Filter by source: issue ใน milestone นี้ หรือ resolution meeting ที่ link milestone
            src_type = a.get("source_type", "")
            src_id = str(a.get("source_id", ""))
            if src_type == "Issue" and iss_df is not None and not iss_df.empty:
                sub = iss_df[iss_df["issue_id"] == src_id]
                if not sub.empty and sub.iloc[0].get("milestone_id") == milestone_id:
                    overdue.append((a["action_id"], f"{src_id} · {str(a.get('description',''))[:50]}"))
        if overdue:
            results["actions"] = {
                "status": "warn",
                "msg": f"มี {len(overdue)} action เกินกำหนดที่เชื่อมโยงกับ milestone นี้",
                "details": overdue,
            }
        else:
            results["actions"] = {
                "status": "ok",
                "msg": "ไม่มี Action เกินกำหนดที่เชื่อมโยง",
                "details": [],
            }
    else:
        results["actions"] = {
            "status": "ok",
            "msg": "ไม่มี Action ในระบบ",
            "details": [],
        }

    # 4) Progress completeness
    if not m_dl.empty:
        latest_p = _latest_progress_per_dl(prog_df)
        total_w, weighted = 0.0, 0.0
        for _, d in m_dl.iterrows():
            w = float(d.get("weight", 0) or 0)
            p = latest_p.get(d["deliverable_id"])
            a = float(p["actual_percent"]) if p is not None else 0.0
            total_w += w
            weighted += w * a
        prog_pct = (weighted / total_w) if total_w else 0.0
        if prog_pct >= 100:
            results["progress"] = {
                "status": "ok",
                "msg": f"Progress รวม = {prog_pct:.1f}%",
                "details": [],
            }
        else:
            results["progress"] = {
                "status": "warn",
                "msg": f"Progress รวม = {prog_pct:.1f}% (ยังไม่ครบ 100%)",
                "details": [],
            }
    else:
        results["progress"] = {"status": "ok", "msg": "-", "details": []}

    return results


def _render_precheck_panel(checks):
    """แสดง pre-condition panel"""
    icon_map = {"ok": "✅", "warn": "⚠️", "fail": "🔴"}
    color_map = {"ok": "#2E7D32", "warn": "#F57C00", "fail": "#D32F2F"}
    bg_map = {"ok": "#E8F5E9", "warn": "#FFF8E1", "fail": "#FFEBEE"}

    labels = {
        "deliverables": "📦 Deliverable Reviews",
        "issues":       "⚠️ Open Critical/High Issues",
        "actions":      "✅ Overdue Actions",
        "progress":     "📈 Progress Completeness",
    }

    for key, chk in checks.items():
        icon = icon_map[chk["status"]]
        color = color_map[chk["status"]]
        bg = bg_map[chk["status"]]
        st.markdown(
            f'<div style="background:{bg};border-left:4px solid {color};'
            f'padding:8px 14px;border-radius:8px;font-size:12.5px;'
            f'margin-bottom:6px;color:#333;">'
            f'{icon} <b>{labels.get(key, key)}:</b> {chk["msg"]}'
            f'</div>',
            unsafe_allow_html=True,
        )
        if chk["details"] and chk["status"] in ("fail", "warn"):
            with st.expander(f"ดูรายละเอียด ({len(chk['details'])} รายการ)", expanded=False):
                for item in chk["details"]:
                    if isinstance(item, tuple):
                        st.markdown(f"- `{item[0]}` — {item[1]}")
                    else:
                        st.markdown(f"- {item}")


def _next_revision_round(milestone_id, acc_df):
    """นับจำนวนรอบที่ผ่านมา"""
    if acc_df is None or acc_df.empty:
        return 0
    sub = acc_df[acc_df["milestone_id"] == milestone_id]
    return len(sub)


def _check_can_accept(checks):
    """ตรวจว่าผ่าน pre-conditions หรือไม่"""
    return all(c["status"] == "ok" for c in checks.values())


# ============================================================
# MAIN RENDER
# ============================================================
def render():
    st.title("🔍 ตรวจรับงานตามงวด (ข้อ 1.5)")
    st.caption(
        "ตรวจรับงานอย่างเป็นระบบ — เชื่อมโยงกับ Deliverable Review (p04), "
        "Issue Tracker (p08) และ Payment (p10)"
    )

    # ============================================================
    # READ ONCE
    # ============================================================
    acc_repo = AcceptanceRepo()
    ms_repo = MilestoneRepo()
    dl_repo = DeliverableRepo()

    acc_df = acc_repo.read()
    ms_df = ms_repo.read()
    dl_df = dl_repo.read()
    dl_df = dl_df[dl_df["milestone_id"].astype(str).str.startswith("MLS")].reset_index(drop=True)

    try:
        prog_df = ProgressRepo().read()
    except Exception:
        prog_df = pd.DataFrame()
    try:
        iss_df = IssueRepo().read()
    except Exception:
        iss_df = pd.DataFrame()
    try:
        act_df = ActionRepo().read()
    except Exception:
        act_df = pd.DataFrame()

    try:
        review_repo = AppendOnlyRepo(
            "deliverable_review_history.csv", REVIEW_FIELDS
        )
        review_df = review_repo.read()
    except Exception:
        review_df = pd.DataFrame()

    if ms_df.empty:
        st.warning("⚠️ ยังไม่มี Milestone — กรุณาตั้งค่าที่เมนู ⚙️ Project / Milestone")
        return

    # ============================================================
    # KPI TILES
    # ============================================================
    st.markdown("### 📊 ภาพรวมการตรวจรับ")

    n_ms = len(ms_df)
    n_accepted = int(ms_df["status"].isin(list(FINAL_STATUSES)).sum())
    n_submitted = int((ms_df["status"] == "Submitted").sum())
    n_review = int((ms_df["status"] == "Under Review").sum())
    n_revreq = int((ms_df["status"] == "Revision Required").sum())
    n_pending = n_ms - n_accepted

    # Payment ready = accepted but no payment record yet
    try:
        pay_df = PaymentRepo().read()
    except Exception:
        pay_df = pd.DataFrame()

    paid_ms = set(pay_df["milestone_id"].astype(str).tolist()) if not pay_df.empty else set()
    n_payment_ready = sum(
        1 for _, m in ms_df.iterrows()
        if m["status"] in FINAL_STATUSES and m["milestone_id"] not in paid_ms
    )

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(_tile("📋 Milestones", f"{n_ms}",
                          "งวดงานทั้งหมด", "#0B5ED7"), unsafe_allow_html=True)
    with k2:
        st.markdown(_tile("🟢 ตรวจรับแล้ว", f"{n_accepted}",
                          f"{n_accepted}/{n_ms} งวด", "#2E7D32"), unsafe_allow_html=True)
    with k3:
        pend_color = "#F57C00" if n_pending > 0 else "#2E7D32"
        st.markdown(_tile("⏳ รอดำเนินการ", f"{n_pending}",
                          f"ส่ง {n_submitted} · ตรวจ {n_review} · แก้ {n_revreq}",
                          pend_color), unsafe_allow_html=True)
    with k4:
        rr_color = "#D32F2F" if n_revreq > 0 else "#2E7D32"
        st.markdown(_tile("🟠 ต้องแก้ไข", f"{n_revreq}",
                          "รอที่ปรึกษาแก้", rr_color), unsafe_allow_html=True)
    with k5:
        pr_color = "#6A1B9A" if n_payment_ready > 0 else "#9E9E9E"
        st.markdown(_tile("💰 พร้อมเบิก", f"{n_payment_ready}",
                          "รอสร้างรายการเบิก", pr_color), unsafe_allow_html=True)

    st.markdown("---")

    # ============================================================
    # TABS
    # ============================================================
    t1, t2, t3, t4 = st.tabs([
        "📝 ตรวจรับรอบใหม่",
        "📜 ประวัติการตรวจรับ",
        "📈 Charts",
        "📥 CSV",
    ])

    # ============================================================
    # TAB 1 — ACCEPTANCE FORM
    # ============================================================
    with t1:
        if "acc_last_saved" in st.session_state:
            info = st.session_state.pop("acc_last_saved")
            st.markdown(
                f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
                f'padding:10px 14px;border-radius:8px;font-size:13px;">'
                f'✅ <b>บันทึกการตรวจรับสำเร็จ</b> — '
                f'Acceptance ID: <code>{info["id"]}</code> · '
                f'Milestone: <code>{info["ms"]}</code> · '
                f'Status: <b>{info["status"]}</b>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown("### 📝 เลือก Milestone ที่จะตรวจรับ")

        ms_options = ms_df["milestone_id"].astype(str).tolist()
        ms_sel = st.selectbox(
            "Milestone",
            ms_options,
            format_func=lambda x: (
                f"{x} — "
                f"{ms_df[ms_df['milestone_id']==x]['milestone_name'].iloc[0]} "
                f"(Due {_fmt_date(ms_df[ms_df['milestone_id']==x]['due_date'].iloc[0])})"
            ),
            key="acc_ms_sel",
        )
        m_row = ms_df[ms_df["milestone_id"] == ms_sel].iloc[0]

        # ============================================================
        # MILESTONE INFO
        # ============================================================
        info1, info2, info3, info4 = st.columns(4)
        with info1:
            st.markdown(f"**📅 Due Date:** {_fmt_date(m_row['due_date'])}")
        with info2:
            pct = float(m_row.get("payment_percent", 0) or 0)
            st.markdown(f"**💰 Payment:** {pct:.1f}%")
        with info3:
            amt = float(m_row.get("payment_amount", 0) or 0)
            st.markdown(f"**💵 ยอด:** {amt:,.0f} ฿")
        with info4:
            st.markdown(f"**📌 Status:** {_status_badge(m_row.get('status'))}")

        # ============================================================
        # DELIVERABLE SUMMARY + REVIEW STATUS
        # ============================================================
        m_dl = dl_df[dl_df["milestone_id"] == ms_sel].copy()
        latest_rv = _latest_review_per_dl(review_df)

        if not m_dl.empty:
            st.markdown("---")
            st.markdown("#### 📦 Deliverables ในงวดนี้")
            dl_rows = []
            for _, d in m_dl.iterrows():
                did = d["deliverable_id"]
                rv = latest_rv.get(did)
                result = rv.get("result", "รอตรวจ") if rv is not None else "รอตรวจ"
                version = rv.get("version_no", "-") if rv is not None else "-"
                dl_rows.append({
                    "Deliverable": f"{did} · {str(d['deliverable_name'])[:40]}",
                    "Weight":      f"{float(d.get('weight', 0) or 0):.1f}%",
                    "Version":     version,
                    "ผล Review":    _result_badge(result),
                    "Reviewer":    rv.get("reviewer", "-") if rv is not None else "-",
                })
            st.dataframe(pd.DataFrame(dl_rows), use_container_width=True, hide_index=True)

        # ============================================================
        # PRE-CONDITIONS
        # ============================================================
        st.markdown("---")
        st.markdown("#### 🧪 Pre-conditions (ต้องผ่านก่อนอนุมัติ)")

        checks = _run_prechecks(ms_sel, dl_df, review_df, iss_df, act_df, prog_df)
        _render_precheck_panel(checks)

        can_accept = _check_can_accept(checks)
        if not can_accept:
            st.warning(
                "⚠️ ยังไม่ผ่าน pre-conditions ทั้งหมด — สามารถบันทึกสถานะ "
                "'Under Review' / 'Revision Required' ได้ "
                "แต่ **ไม่ควร** เลือก 'Accepted' จนกว่าจะผ่านครบ"
            )

        # ============================================================
        # FORM
        # ============================================================
        st.markdown("---")
        st.markdown("#### 📝 บันทึกผลการตรวจรับ")

        auto_round = _next_revision_round(ms_sel, acc_df)

        with st.form("acc_form", clear_on_submit=False):
            # A. Submission
            st.markdown("**A. ข้อมูลการส่งมอบ**")
            cA1, cA2, cA3 = st.columns(3)
            sub_date = cA1.date_input(
                "วันที่ที่ปรึกษาส่งมอบ",
                value=st.session_state.get("acc_sub_date", _today()),
                key="acc_sub_date",
            )
            sub_ref = cA2.text_input(
                "อ้างอิงชุดเอกสาร",
                value=st.session_state.get("acc_sub_ref", ""),
                key="acc_sub_ref",
                placeholder="เช่น REPORT-M1-V01",
            )
            rev_round = cA3.number_input(
                "รอบการแก้ไข (0 = รอบแรก)",
                min_value=0, max_value=20,
                value=int(st.session_state.get("acc_rev_round", auto_round)),
                key="acc_rev_round",
            )

            # B. Checklist 8 items
            st.markdown("**B. Checklist 8 ข้อ**")
            checks_form = {}
            cc1, cc2 = st.columns(2)
            for i, (key, label) in enumerate(CHECKLIST_ITEMS):
                col = cc1 if i % 2 == 0 else cc2
                checks_form[key] = col.checkbox(
                    f"{i+1}. {label}",
                    value=st.session_state.get(f"acc_chk_{key}", False),
                    key=f"acc_chk_{key}",
                )
            n_checked = sum(1 for v in checks_form.values() if v)

            # C. Compliance
            st.markdown("**C. ความสอดคล้องตาม TOR**")
            cC1, cC2 = st.columns(2)
            tor_ok = cC1.radio(
                "TOR Compliance",
                TOR_COMPLIANCE,
                horizontal=True,
                key="acc_tor_ok",
            )
            review_result = cC2.radio(
                "ผลการตรวจ",
                REVIEW_RESULTS,
                horizontal=False,
                key="acc_review_result",
            )

            comment = st.text_area(
                "Comment / Finding",
                value=st.session_state.get("acc_comment", ""),
                height=100,
                key="acc_comment",
                placeholder="ระบุข้อสังเกต ข้อแก้ไข หรือเหตุผล",
            )

            # D. Committee
            st.markdown("**D. คณะกรรมการตรวจรับ**")
            cD1, cD2 = st.columns(2)
            committee_date = cD1.date_input(
                "วันที่คณะกรรมการตรวจรับ",
                value=st.session_state.get("acc_committee_date", _today()),
                key="acc_committee_date",
            )
            acc_ref = cD2.text_input(
                "เลขอ้างอิงการตรวจรับ",
                value=st.session_state.get("acc_ref", ""),
                key="acc_ref",
                placeholder="เช่น ACC-M1-001",
            )
            committee_members = st.text_area(
                "รายชื่อคณะกรรมการ (คั่นด้วย , หรือขึ้นบรรทัดใหม่)",
                value=st.session_state.get("acc_members", ""),
                height=80,
                key="acc_members",
                placeholder="เช่น นายสมชาย (ประธาน), นางสมหญิง (กรรมการ), นายสมศักดิ์ (เลขา)",
            )

            # E. Evidence
            st.markdown("**E. หลักฐานการตรวจรับ**")
            cE1, cE2 = st.columns(2)
            acc_evidence = cE1.text_input(
                "เลขอ้างอิงหลักฐาน",
                value=st.session_state.get("acc_evidence", ""),
                key="acc_evidence",
                placeholder="เช่น MIN-ACCEPT-001",
            )
            uploaded_file = cE2.file_uploader(
                "แนบไฟล์หลักฐาน (optional)",
                type=["pdf", "png", "jpg", "jpeg", "docx"],
                key="acc_file",
            )

            # F. Status
            st.markdown("**F. สถานะการตรวจรับ**")
            cur_idx = ACCEPTANCE_STATUSES.index("Under Review")
            status_sel = st.selectbox(
                "สถานะ",
                ACCEPTANCE_STATUSES,
                index=cur_idx,
                key="acc_status",
            )

            if status_sel == "Accepted" and not can_accept:
                st.warning(
                    "⚠️ Pre-conditions ยังไม่ผ่าน — การเลือก 'Accepted' "
                    "จะต้องมี Comment อธิบายเหตุผล override"
                )

            # Buttons
            cBtn1, cBtn2 = st.columns([1, 1])
            submitted = cBtn1.form_submit_button(
                "💾 บันทึกการตรวจรับ",
                type="primary",
                use_container_width=True,
            )
            reset_clicked = cBtn2.form_submit_button(
                "↩️ ล้างฟอร์ม",
                use_container_width=True,
            )

        # ---- Reset ----
        if reset_clicked:
            _reset_keys("acc_", preserve=("acc_ms_sel",))
            st.rerun()

        # ---- Save ----
        if submitted:
            try:
                # ---- Validations ----
                # BR: Required fields
                if not sub_ref.strip():
                    raise ValidationError("⚠️ ต้องระบุอ้างอิงชุดเอกสาร")
                if not acc_ref.strip():
                    raise ValidationError("⚠️ ต้องระบุเลขอ้างอิงการตรวจรับ")

                # BR-05: Accepted ต้องมี evidence
                if status_sel == "Accepted" and not acc_evidence.strip():
                    raise ValidationError("BR-05: Accepted ต้องมี Acceptance Evidence")

                # BR: ต้องติ๊ก checklist ถ้า "ผ่าน"
                if review_result == "ผ่าน" and n_checked < 8:
                    raise ValidationError(
                        f"⚠️ เลือก 'ผ่าน' ต้องติ๊ก checklist ครบ 8 ข้อ "
                        f"(ปัจจุบัน {n_checked}/8)"
                    )

                # BR: ต้องมี comment ถ้า "ต้องแก้ไข" / "ไม่ผ่าน"
                if review_result in ("ต้องแก้ไข", "ไม่ผ่าน") and not comment.strip():
                    raise ValidationError(
                        "⚠️ เลือก 'ต้องแก้ไข' หรือ 'ไม่ผ่าน' ต้องระบุ Comment / Finding"
                    )

                # BR: ต้องมี comment ถ้า Non-Compliant
                if tor_ok == "Non-Compliant" and not comment.strip():
                    raise ValidationError("⚠️ TOR = Non-Compliant ต้องระบุ Finding")

                # BR-10: committee_date ≥ sub_date
                if committee_date < sub_date:
                    raise ValidationError(
                        f"BR-10: วันที่คณะกรรมการ ({_fmt_date(committee_date)}) "
                        f"ต้องไม่ก่อนวันที่ส่งมอบ ({_fmt_date(sub_date)})"
                    )

                # BR: ห้าม Accepted ถ้าไม่ผ่าน precheck โดยไม่มี override comment
                if status_sel == "Accepted" and not can_accept and not comment.strip():
                    raise ValidationError(
                        "⚠️ Pre-conditions ไม่ผ่าน — ต้องอธิบายเหตุผล override ใน Comment"
                    )

                # ---- Prepare row ----
                aid = new_id("acceptance")
                file_name = ""
                if uploaded_file is not None:
                    # Save reference only (ไม่ save file จริงในเวอร์ชันนี้)
                    file_name = getattr(uploaded_file, "name", "")

                row = {
                    "timestamp":              now_str(),
                    "acceptance_id":          aid,
                    "milestone_id":           ms_sel,
                    "submission_date":        str(sub_date),
                    "submission_ref":         sub_ref.strip(),
                    "completeness_check":     "OK" if n_checked == 8 else f"{n_checked}/8",
                    "tor_compliance_check":   tor_ok,
                    "deliverable_review_result": review_result,
                    "revision_round":         int(rev_round),
                    "committee_date":         str(committee_date),
                    "acceptance_ref":         acc_ref.strip(),
                    "acceptance_evidence":    acc_evidence.strip(),
                    "status":                 status_sel,
                    "reviewer":               st.session_state.user,
                    "review_comment":         comment
                                               + (f"\n[committee] {committee_members}" if committee_members.strip() else "")
                                               + (f"\n[file] {file_name}" if file_name else ""),
                    "created_by":             st.session_state.user,
                }
                acc_repo.append(row)

                # ---- Update Milestone (via MilestoneRepo — มี backup) ----
                new_ms = m_row.to_dict()
                # Sync submission_date
                new_ms["submission_date"] = str(sub_date)
                # Sync acceptance_date
                if status_sel in FINAL_STATUSES:
                    new_ms["acceptance_date"] = str(committee_date)
                new_ms["status"] = status_sel
                new_ms["updated_at"] = now_str()
                ms_repo.upsert(new_ms, key="milestone_id")

                # ---- Audit ----
                append_audit(
                    st.session_state.user, "CREATE", "ACCEPTANCE", aid,
                    old_value=f"MS {ms_sel} status: {m_row.get('status')}",
                    new_value=f"Acceptance {status_sel} ({review_result})",
                    reason=f"Ref: {acc_ref} · Evidence: {acc_evidence or '-'}",
                )

                # ---- Flash ----
                st.session_state["acc_last_saved"] = {
                    "id": aid, "ms": ms_sel, "status": status_sel,
                }
                _reset_keys("acc_", preserve=("acc_ms_sel", "acc_last_saved"))
                st.rerun()

            except ValidationError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"❌ {type(e).__name__}: {e}")

        # ---- Payment readiness hint ----
        if m_row.get("status") in FINAL_STATUSES:
            st.markdown("---")
            st.success(
                f"💰 **Milestone นี้พร้อมสำหรับการเบิกจ่าย** — "
                f"ไปที่เมนู **💵 เบิกจ่าย (1.5)** เพื่อสร้างรายการเบิก"
            )

    # ============================================================
    # TAB 2 — HISTORY
    # ============================================================
    with t2:
        st.markdown("### 📜 ประวัติการตรวจรับ")

        if acc_df.empty:
            st.info("ยังไม่มีการตรวจรับ — เริ่มที่แท็บ 📝")
        else:
            # ---- Filters ----
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                f_ms = st.multiselect(
                    "Milestone",
                    sorted(acc_df["milestone_id"].astype(str).unique().tolist()),
                    default=sorted(acc_df["milestone_id"].astype(str).unique().tolist()),
                    key="h_acc_ms",
                )
            with c2:
                f_stat = st.multiselect(
                    "Status",
                    ACCEPTANCE_STATUSES,
                    default=ACCEPTANCE_STATUSES,
                    key="h_acc_stat",
                )
            with c3:
                search = st.text_input(
                    "🔍 Search (Acceptance ID / Ref / Comment)",
                    value="", key="h_acc_search",
                )

            view = acc_df.copy()
            if f_ms:
                view = view[view["milestone_id"].isin(f_ms)]
            if f_stat:
                view = view[view["status"].isin(f_stat)]
            if search.strip():
                s = search.strip().lower()
                view = view[
                    view["acceptance_id"].astype(str).str.lower().str.contains(s, na=False)
                    | view["acceptance_ref"].astype(str).str.lower().str.contains(s, na=False)
                    | view["review_comment"].astype(str).str.lower().str.contains(s, na=False)
                ]

            view = view.copy()
            view["_ts"] = pd.to_datetime(view["timestamp"], errors="coerce")
            view = view.sort_values("_ts", ascending=False)

            st.caption(f"แสดง {len(view)} / {len(acc_df)} รายการ (เรียงจากใหม่)")

            # ---- Table ----
            show_cols = [c for c in [
                "timestamp", "acceptance_id", "milestone_id",
                "submission_date", "submission_ref",
                "revision_round", "committee_date",
                "acceptance_ref", "acceptance_evidence",
                "status", "deliverable_review_result",
                "tor_compliance_check", "completeness_check",
                "reviewer",
            ] if c in view.columns]
            st.dataframe(
                view[show_cols],
                use_container_width=True,
                hide_index=True,
            )

            # ---- Detail viewer ----
            st.markdown("---")
            st.markdown("#### 🔎 ดูรายละเอียด")

            det_id = st.selectbox(
                "เลือก Acceptance ID",
                view["acceptance_id"].astype(str).tolist(),
                key="h_acc_det",
            )
            det = acc_df[acc_df["acceptance_id"] == det_id].iloc[-1]

            d1, d2, d3, d4 = st.columns(4)
            with d1:
                st.markdown(f"**📌 Milestone:** `{det['milestone_id']}`")
            with d2:
                st.markdown(f"**🔄 Revision Round:** {det.get('revision_round', 0)}")
            with d3:
                st.markdown(f"**📅 Committee:** {_fmt_date(det.get('committee_date'))}")
            with d4:
                st.markdown(f"**📌 Status:** {_status_badge(det.get('status'))}")

            st.markdown(
                f"**📄 Submission Ref:** `{det.get('submission_ref', '-')}` · "
                f"**📅 {_fmt_date(det.get('submission_date'))}**  \n"
                f"**🔍 Acceptance Ref:** `{det.get('acceptance_ref', '-')}`  \n"
                f"**📎 Evidence:** `{det.get('acceptance_evidence', '-')}`"
            )
            st.markdown(
                f"**✅ Completeness:** {det.get('completeness_check', '-')} · "
                f"**📋 TOR:** {det.get('tor_compliance_check', '-')} · "
                f"**🎯 Review Result:** {_result_badge(det.get('deliverable_review_result', '-'))}"
            )

            with st.expander("📝 Comment / Finding", expanded=True):
                st.write(det.get("review_comment", "-"))

            # ---- Soft Delete + Restore ----
            if st.session_state.role in ("admin", "monitoring"):
                st.markdown("---")
                with st.expander("🗑️ ลบ / คืนค่า (Soft Delete)", expanded=False):
                    st.caption("⚠️ Soft Delete = ซ่อนจาก UI, ข้อมูลยังอยู่ใน CSV")

                    colA, colB = st.columns(2)

                    with colA:
                        st.markdown("**🗑️ Soft Delete**")
                        del_id = st.selectbox(
                            "เลือก Acceptance ID",
                            acc_df["acceptance_id"].astype(str).tolist(),
                            key="h_acc_del_sel",
                        )
                        del_reason = st.text_input(
                            "เหตุผลที่ลบ", key="h_acc_del_reason",
                        )
                        if st.button("🗑️ Soft Delete", type="primary", key="h_acc_del_btn"):
                            if not del_reason.strip():
                                st.error("⚠️ กรุณาระบุเหตุผล")
                            else:
                                try:
                                    acc_repo.soft_delete(
                                        del_id, del_reason, st.session_state.user
                                    )
                                    st.success(f"✅ ซ่อน `{del_id}` แล้ว")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ {e}")

                    with colB:
                        st.markdown("**↩️ Restore**")
                        try:
                            from core.void_registry import read_voids
                            vd = read_voids()
                            vd_a = (
                                vd[vd["record_type"] == "acceptance"]
                                if not vd.empty else vd
                            )
                            if vd_a.empty:
                                st.info("ไม่มีรายการที่ถูก Void")
                            else:
                                rid = st.selectbox(
                                    "เลือก Acceptance ID",
                                    vd_a["record_id"].tolist(),
                                    key="h_acc_restore_sel",
                                )
                                if st.button("↩️ คืนค่า", key="h_acc_restore_btn"):
                                    if acc_repo.restore(rid, st.session_state.user):
                                        st.success(f"✅ คืนค่า `{rid}` แล้ว")
                                        st.rerun()
                        except Exception as e:
                            st.error(f"❌ {e}")

    # ============================================================
    # TAB 3 — CHARTS
    # ============================================================
    with t3:
        st.markdown("### 📈 Charts สรุปการตรวจรับ")

        # ---- Milestone status distribution ----
        st.markdown("#### 📊 สถานะ Milestone ทั้งหมด")
        ms_status_counts = ms_df["status"].value_counts()

        status_colors = {
            "Not Started": "#9E9E9E",
            "In Progress": "#0B5ED7",
            "Submitted": "#6A1B9A",
            "Under Review": "#F57C00",
            "Revision Required": "#D32F2F",
            "Ready for Acceptance": "#F9A825",
            "Accepted": "#2E7D32",
            "Payment Processing": "#00838F",
            "Paid": "#1B5E20",
            "Closed": "#4CAF50",
        }

        fig1 = go.Figure(data=[go.Bar(
            x=ms_status_counts.index.tolist(),
            y=ms_status_counts.values.tolist(),
            marker_color=[
                status_colors.get(x, "#0B5ED7") for x in ms_status_counts.index
            ],
            text=ms_status_counts.values.tolist(),
            textposition="outside",
        )])
        fig1.update_layout(
            height=340, plot_bgcolor="#FAFBFC",
            yaxis_title="จำนวน Milestones",
            margin=dict(l=10, r=10, t=20, b=80),
        )
        st.plotly_chart(fig1, use_container_width=True)

        # ---- Acceptance rounds ----
        if not acc_df.empty:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 📊 ผลการตรวจรับตาม Milestone")
                result_counts = (
                    acc_df["deliverable_review_result"].value_counts()
                )
                fig2 = go.Figure(data=[go.Pie(
                    labels=result_counts.index.tolist(),
                    values=result_counts.values.tolist(),
                    hole=0.5,
                )])
                fig2.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(fig2, use_container_width=True)

            with c2:
                st.markdown("#### 🔄 จำนวนรอบการแก้ไข (Revision Rounds)")
                if "revision_round" in acc_df.columns:
                    rr = acc_df["revision_round"].astype(int).value_counts().sort_index()
                    fig3 = go.Figure(data=[go.Bar(
                        x=[f"Round {i}" for i in rr.index],
                        y=rr.values.tolist(),
                        marker_color="#F57C00",
                        text=rr.values.tolist(),
                        textposition="outside",
                    )])
                    fig3.update_layout(
                        height=320, plot_bgcolor="#FAFBFC",
                        yaxis_title="จำนวนครั้ง",
                        margin=dict(l=10, r=10, t=30, b=40),
                    )
                    st.plotly_chart(fig3, use_container_width=True)

            # ---- Timeline ----
            st.markdown("#### 📅 Timeline: Submission vs Committee")
            tdf = acc_df.copy()
            tdf["_sub"] = pd.to_datetime(tdf["submission_date"], errors="coerce")
            tdf["_com"] = pd.to_datetime(tdf["committee_date"], errors="coerce")
            tdf = tdf.dropna(subset=["_sub", "_com"]).sort_values("_sub")

            if not tdf.empty:
                fig4 = go.Figure()
                fig4.add_trace(go.Scatter(
                    x=tdf["_sub"], y=tdf["milestone_id"],
                    mode="markers", name="Submission",
                    marker=dict(size=12, color="#0B5ED7", symbol="circle"),
                ))
                fig4.add_trace(go.Scatter(
                    x=tdf["_com"], y=tdf["milestone_id"],
                    mode="markers", name="Committee",
                    marker=dict(size=12, color="#2E7D32", symbol="diamond"),
                ))
                fig4.update_layout(
                    height=max(300, len(tdf) * 40),
                    plot_bgcolor="#FAFBFC",
                    xaxis_title="Date",
                    margin=dict(l=10, r=10, t=20, b=40),
                )
                st.plotly_chart(fig4, use_container_width=True)

    # ============================================================
    # TAB 4 — CSV
    # ============================================================
    with t4:
        st.markdown("### 📥 ข้อมูล CSV (อ่านเท่านั้น)")
        st.caption("ไฟล์จริง: `data/history/acceptance_history.csv`")

        if acc_df.empty:
            st.info("ยังไม่มีข้อมูล")
        else:
            st.dataframe(acc_df, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ ดาวน์โหลด acceptance_history.csv",
                data=acc_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"acceptance_history_{today_str()}.csv",
                mime="text/csv",
                key="dl_acc",
            )