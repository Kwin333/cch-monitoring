"""Issue Tracker (ข้อ 1.3 + 1.5) — Comprehensive Version

ครอบคลุม:
- 📊 KPI Dashboard: ทั้งหมด, Open, Critical/High, Overdue, Resolution Rate
- ➕ Add Issue + auto-link Milestone/Deliverable/Meeting + Auto-create Action
- 🔄 Update Issue + lifecycle (Open → In Progress → Escalated → Closed)
- 📜 History + Filter (severity/status/escalation/overdue) + Search + Card-style
- 🗑️ Soft Delete + Restore (admin/monitoring)
- 📈 Charts: Severity, Status, Responsible, Open by Severity
- 📥 CSV Export
- 💾 Form persistence + Reset + Flash message
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

from core.ids import new_id
from core.time_util import now_str, today_str
from core.audit import append_audit
from core.validator import validate_issue_close, ValidationError
from repositories.issue_repo import IssueRepo
from repositories.action_repo import ActionRepo
from repositories.meeting_repo import MeetingRepo
from repositories.milestone_repo import MilestoneRepo
from repositories.deliverable_repo import DeliverableRepo


# ============================================================
# CONSTANTS
# ============================================================
SEVERITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Open", "In Progress", "Escalated", "Closed"]
ESCALATION_LEVELS = ["None", "Level 1", "Level 2", "Level 3"]

SEVERITY_COLORS = {
    "Low": "#9E9E9E",
    "Medium": "#0B5ED7",
    "High": "#F57C00",
    "Critical": "#D32F2F",
}

STATUS_BADGES = {
    "Open": "🔴 เปิด",
    "In Progress": "🟠 กำลังแก้ไข",
    "Escalated": "🚨 ยกระดับ",
    "Closed": "✅ ปิด",
}

SEVERITY_BADGES = {
    "Low": "⚪ Low",
    "Medium": "🔵 Medium",
    "High": "🟠 High",
    "Critical": "🔴 Critical",
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


def _fmt_date(d):
    dd = _to_date(d)
    return dd.strftime("%d/%m/%Y") if dd else "-"


def _today():
    return date.today()


def _is_overdue(due, status):
    if status == "Closed":
        return False
    dd = _to_date(due)
    return dd is not None and dd < _today()


def _days_left(due):
    dd = _to_date(due)
    return (dd - _today()).days if dd else None


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


def _validate_issue(data, prev_status=None):
    """Validation เต็มรูปแบบ"""
    if not (data.get("description") or "").strip():
        raise ValidationError("⚠️ ต้องระบุ Description")
    if not (data.get("impact") or "").strip():
        raise ValidationError("⚠️ ต้องระบุ Impact")

    # BR-06: Closed ต้องมี Resolution
    validate_issue_close(data.get("status"), data.get("resolution"))

    # Critical ต้องมี Escalation + Root Cause
    if data.get("severity") == "Critical":
        if data.get("escalation_level") in ("None", "", None):
            raise ValidationError("⚠️ Severity = Critical ต้องมี Escalation Level")
        if not (data.get("root_cause") or "").strip():
            raise ValidationError("⚠️ Severity = Critical ต้องระบุ Root Cause")

    # In Progress ต้องมี Corrective Action
    if data.get("status") in ("In Progress", "Escalated"):
        if not (data.get("corrective_action") or "").strip():
            raise ValidationError(
                "⚠️ สถานะ In Progress / Escalated ต้องระบุ Corrective Action"
            )

    # Action Due ต้องไม่ก่อน Issue Date
    iss_d = _to_date(data.get("issue_date"))
    act_d = _to_date(data.get("action_due_date"))
    if iss_d and act_d and act_d < iss_d:
        raise ValidationError("⚠️ Action Due Date ต้องไม่ก่อน Issue Date")

    # ห้าม Closed → Open ย้อนหลัง
    if prev_status == "Closed" and data.get("status") != "Closed":
        raise ValidationError(
            "⚠️ ไม่สามารถเปิด Issue ที่ปิดแล้วกลับมาได้ — "
            "หากพบปัญหาใหม่ กรุณาสร้าง Issue ใหม่"
        )


def _build_issue_card(r, border_color, time_txt):
    """สร้าง HTML card สำหรับแสดง Issue"""
    sev_color = SEVERITY_COLORS.get(r.get("severity", "Medium"), "#0B5ED7")
    status_txt = STATUS_BADGES.get(r.get("status", "-"), r.get("status", "-"))
    sev_txt = SEVERITY_BADGES.get(r.get("severity", "-"), r.get("severity", "-"))
    esc = r.get("escalation_level", "None") or "None"
    esc_html = (
        f'<span style="background:#FFEBEE;color:#B71C1C;padding:2px 8px;'
        f'border-radius:10px;font-size:10.5px;margin-left:6px;">'
        f'🚨 {esc}</span>'
        if esc != "None" else ""
    )
    src_html = ""
    if r.get("milestone_id") or r.get("deliverable_id"):
        parts = []
        if r.get("milestone_id"):
            parts.append(f"📌 {r['milestone_id']}")
        if r.get("deliverable_id"):
            parts.append(f"📦 {r['deliverable_id']}")
        src_html = " · ".join(parts)

    return (
        f'<div style="background:#FFFFFF;border-radius:8px;'
        f'padding:10px 14px;border-left:4px solid {border_color};'
        f'box-shadow:0 1px 4px rgba(0,51,102,0.05);margin-bottom:8px;">'
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:center;flex-wrap:wrap;gap:8px;">'
        f'<div style="font-size:13px;font-weight:700;color:#003366;">'
        f'{r["issue_id"]} '
        f'<span style="background:{sev_color};color:#FFF;'
        f'padding:2px 8px;border-radius:10px;font-size:10.5px;'
        f'margin-left:6px;">{r.get("severity","-")}</span>'
        f'<span style="font-weight:400;color:#666;margin-left:6px;">'
        f'({status_txt})</span>{esc_html}'
        f'</div>'
        f'<div style="font-size:11.5px;color:{border_color};font-weight:600;">'
        f'{time_txt}</div></div>'
        f'<div style="font-size:13px;color:#333;margin:6px 0;">'
        f'{str(r["description"])[:200]}</div>'
        f'<div style="font-size:11.5px;color:#666;">'
        f'👤 <b>{r.get("responsible_party","-")}</b> · '
        f'📅 Issue {_fmt_date(r.get("issue_date"))} · '
        f'⏰ Due {_fmt_date(r.get("action_due_date"))}'
        + (f' · {src_html}' if src_html else '')
        + f'</div></div>'
    )


# ============================================================
# MAIN RENDER
# ============================================================
def render():
    st.title("⚠️ Issue Tracker")
    st.caption(
        "ติดตามประเด็นปัญหา · Root Cause · Corrective/Preventive Action · "
        "เชื่อมโยงกับ Milestone, Deliverable และ Action Tracker"
    )

    # ============================================================
    # READ ONCE
    # ============================================================
    iss_repo = IssueRepo()
    iss_df = iss_repo.read()

    try:
        act_repo = ActionRepo()
    except Exception:
        act_repo = None
    try:
        mtg_df = MeetingRepo().read()
    except Exception:
        mtg_df = pd.DataFrame()
    try:
        ms_df = MilestoneRepo().read()
    except Exception:
        ms_df = pd.DataFrame()
    try:
        dl_df = DeliverableRepo().read()
        dl_df = dl_df[dl_df["milestone_id"].astype(str).str.startswith("MLS")].reset_index(drop=True)
    except Exception:
        dl_df = pd.DataFrame()

    # ============================================================
    # KPI TILES
    # ============================================================
    st.markdown("### 📊 ภาพรวม Issues")

    n_total = len(iss_df)
    if n_total:
        n_open = int((iss_df["status"] == "Open").sum())
        n_prog = int((iss_df["status"] == "In Progress").sum())
        n_esc = int((iss_df["status"] == "Escalated").sum())
        n_closed = int((iss_df["status"] == "Closed").sum())
        n_critical = int((iss_df["severity"] == "Critical").sum())
        n_high = int((iss_df["severity"] == "High").sum())
        n_overdue = sum(
            1 for _, r in iss_df.iterrows()
            if _is_overdue(r.get("action_due_date"), r.get("status"))
        )
    else:
        n_open = n_prog = n_esc = n_closed = 0
        n_critical = n_high = n_overdue = 0

    open_total = n_open + n_prog + n_esc
    resolution_rate = (n_closed / n_total * 100) if n_total else 0.0

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(_tile("📋 ทั้งหมด", f"{n_total}",
                          f"ปิดแล้ว {n_closed}", "#0B5ED7"),
                    unsafe_allow_html=True)
    with k2:
        st.markdown(_tile("🔴 เปิดอยู่", f"{open_total}",
                          f"Open {n_open} · Prog {n_prog} · Esc {n_esc}",
                          "#D32F2F"), unsafe_allow_html=True)
    with k3:
        crit_color = "#D32F2F" if n_critical > 0 else "#2E7D32"
        st.markdown(_tile("🚨 Critical", f"{n_critical}",
                          f"🟠 High: {n_high}", crit_color), unsafe_allow_html=True)
    with k4:
        od_color = "#D32F2F" if n_overdue > 0 else "#2E7D32"
        st.markdown(_tile("⏰ เกินกำหนด", f"{n_overdue}",
                          "ต้องติดตามด่วน" if n_overdue else "ไม่มี",
                          od_color), unsafe_allow_html=True)
    with k5:
        st.markdown(_tile("🎯 Resolution", f"{resolution_rate:.0f}%",
                          f"{n_closed}/{n_total} ปิดแล้ว", "#2E7D32"),
                    unsafe_allow_html=True)

    if n_critical > 0 or n_overdue > 0:
        alerts = []
        if n_critical > 0:
            alerts.append(f"🚨 <b>{n_critical} Critical</b>")
        if n_overdue > 0:
            alerts.append(f"⏰ <b>{n_overdue} Overdue</b>")
        st.markdown(
            f'<div style="background:#FFEBEE;border-left:4px solid #D32F2F;'
            f'padding:10px 14px;border-radius:8px;font-size:13px;margin-top:10px;color:#B71C1C;">'
            + " · ".join(alerts)
            + ' — กรุณาตรวจสอบในแท็บ "📜 ประวัติ & ติดตาม"'
            + '</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ============================================================
    # TABS
    # ============================================================
    t1, t2, t3, t4 = st.tabs([
        "➕ เพิ่ม / อัปเดต",
        "📜 ประวัติ & ติดตาม",
        "📈 Charts",
        "📥 CSV",
    ])

    # ============================================================
    # TAB 1 — ADD / UPDATE
    # ============================================================
    with t1:
        # Flash
        if "iss_last_saved" in st.session_state:
            info = st.session_state.pop("iss_last_saved")
            extra = ""
            if info.get("action_id"):
                extra = (
                    f' · สร้าง Action <code>{info["action_id"]}</code> อัตโนมัติ'
                )
            st.markdown(
                f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
                f'padding:10px 14px;border-radius:8px;font-size:13px;">'
                f'✅ <b>{info["mode"]} Issue สำเร็จ</b> — '
                f'Issue ID: <code>{info["id"]}</code>{extra}'
                f'</div>',
                unsafe_allow_html=True,
            )

        mode = st.radio(
            "โหมด",
            ["➕ เพิ่มใหม่", "🔄 อัปเดตสถานะ"],
            horizontal=True,
            key="iss_mode",
        )

        # ---------- ADD ----------
        if mode == "➕ เพิ่มใหม่":
            st.markdown("### ➕ เพิ่ม Issue ใหม่")

            # --- Reference selector นอก form (dependent dropdown) ---
            st.markdown("**A. แหล่งที่มา / ข้ออ้างอิง**")

            cA1, cA2, cA3 = st.columns(3)
            ms_opts = ["-"] + (
                ms_df["milestone_id"].astype(str).tolist() if not ms_df.empty else []
            )
            iss_ms = cA1.selectbox("Milestone ID", ms_opts, key="iss_ms")

            # Deliverable filtered by milestone
            if iss_ms != "-" and not dl_df.empty:
                dl_opts = ["-"] + dl_df[
                    dl_df["milestone_id"] == iss_ms
                ]["deliverable_id"].astype(str).tolist()
            elif not dl_df.empty:
                dl_opts = ["-"] + dl_df["deliverable_id"].astype(str).tolist()
            else:
                dl_opts = ["-"]

            def _fmt_dl(x):
                if x == "-" or dl_df.empty:
                    return x
                sub = dl_df[dl_df["deliverable_id"] == x]
                if sub.empty:
                    return x
                return f"{x} — {str(sub['deliverable_name'].iloc[0])[:40]}"

            iss_dl = cA2.selectbox(
                "Deliverable ID",
                dl_opts,
                format_func=_fmt_dl,
                key="iss_dl",
            )

            # Auto-fill TOR clause
            auto_clause = ""
            if iss_dl != "-" and not dl_df.empty:
                sub = dl_df[dl_df["deliverable_id"] == iss_dl]
                if not sub.empty:
                    auto_clause = str(sub["tor_clause"].iloc[0])

            iss_clause = cA3.text_input(
                "TOR Clause",
                value=st.session_state.get("iss_clause", auto_clause),
                key="iss_clause",
            )

            # --- FORM ---
            with st.form("iss_add_form", clear_on_submit=False):
                st.markdown("**B. รายละเอียดปัญหา**")
                cB1, cB2 = st.columns([1, 2])
                iss_date = cB1.date_input(
                    "Issue Date",
                    value=st.session_state.get("iss_date", _today()),
                    key="iss_date",
                )
                cur_sev = st.session_state.get("iss_sev", "Medium")
                iss_sev = cB2.selectbox(
                    "Severity",
                    SEVERITIES,
                    index=SEVERITIES.index(cur_sev) if cur_sev in SEVERITIES else 1,
                    key="iss_sev",
                )

                iss_desc = st.text_area(
                    "Description",
                    value=st.session_state.get("iss_desc", ""),
                    height=90,
                    key="iss_desc",
                    placeholder="อธิบายปัญหาที่พบอย่างชัดเจน วัดผลได้",
                )
                iss_impact = st.text_area(
                    "Impact (ผลกระทบต่อโครงการ)",
                    value=st.session_state.get("iss_impact", ""),
                    height=80,
                    key="iss_impact",
                    placeholder="เช่น ทำให้ส่งมอบล่าช้า 5 วัน / กระทบงบประมาณ 100,000 บาท",
                )

                st.markdown("**C. การวิเคราะห์**")
                cC1, cC2, cC3 = st.columns(3)
                iss_rc = cC1.text_input(
                    "Root Cause",
                    value=st.session_state.get("iss_rc", ""),
                    key="iss_rc",
                )
                iss_owner = cC2.text_input(
                    "Responsible Party",
                    value=st.session_state.get("iss_owner", ""),
                    key="iss_owner",
                )
                cur_esc = st.session_state.get("iss_esc", "None")
                iss_esc = cC3.selectbox(
                    "Escalation Level",
                    ESCALATION_LEVELS,
                    index=ESCALATION_LEVELS.index(cur_esc) if cur_esc in ESCALATION_LEVELS else 0,
                    key="iss_esc",
                )

                st.markdown("**D. Action Plan**")
                cD1, cD2 = st.columns(2)
                iss_ca = cD1.text_area(
                    "Corrective Action (แก้ไข)",
                    value=st.session_state.get("iss_ca", ""),
                    height=70,
                    key="iss_ca",
                )
                iss_pa = cD2.text_area(
                    "Preventive Action (ป้องกัน)",
                    value=st.session_state.get("iss_pa", ""),
                    height=70,
                    key="iss_pa",
                )

                cD3, cD4 = st.columns(2)
                iss_due = cD3.date_input(
                    "Action Due Date",
                    value=st.session_state.get("iss_due", _today() + timedelta(days=7)),
                    key="iss_due",
                )
                cur_stat = st.session_state.get("iss_stat", "Open")
                iss_stat = cD4.selectbox(
                    "Status",
                    STATUSES,
                    index=STATUSES.index(cur_stat) if cur_stat in STATUSES else 0,
                    key="iss_stat",
                )

                st.markdown("**E. ความเชื่อมโยง & หลักฐาน**")
                cE1, cE2 = st.columns(2)
                mtg_opts = ["-"] + (
                    mtg_df["meeting_id"].astype(str).tolist() if not mtg_df.empty else []
                )
                iss_mtg_ref = cE1.selectbox(
                    "Meeting Reference",
                    mtg_opts,
                    key="iss_mtg_ref",
                )
                iss_evi = cE2.text_input(
                    "Evidence Reference",
                    value=st.session_state.get("iss_evi", ""),
                    key="iss_evi",
                    placeholder="เช่น ภาพถ่าย, รายงาน, หนังสือที่ 1234/2569",
                )

                iss_resolution = st.text_area(
                    "Resolution (บังคับถ้า Status = Closed)",
                    value=st.session_state.get("iss_resolution", ""),
                    height=80,
                    key="iss_resolution",
                )

                st.markdown("**F. Auto-create Action**")
                auto_action = st.checkbox(
                    "สร้าง Action Item อัตโนมัติ (สำหรับ Severity ≥ High)",
                    value=(iss_sev in ("High", "Critical")),
                    key="iss_auto_action",
                )

                cBtn1, cBtn2 = st.columns([1, 1])
                submitted = cBtn1.form_submit_button(
                    "💾 บันทึก Issue", type="primary", use_container_width=True,
                )
                reset_clicked = cBtn2.form_submit_button(
                    "↩️ ล้างฟอร์ม", use_container_width=True,
                )

            if reset_clicked:
                _reset_keys("iss_", preserve=("iss_mode",))
                st.rerun()

            if submitted:
                try:
                    data = {
                        "milestone_id":      "" if iss_ms == "-" else iss_ms,
                        "deliverable_id":    "" if iss_dl == "-" else iss_dl,
                        "tor_clause":        iss_clause,
                        "issue_date":        str(iss_date),
                        "description":       iss_desc,
                        "impact":            iss_impact,
                        "severity":          iss_sev,
                        "root_cause":        iss_rc,
                        "responsible_party": iss_owner,
                        "corrective_action": iss_ca,
                        "preventive_action": iss_pa,
                        "action_due_date":   str(iss_due),
                        "escalation_level":  iss_esc,
                        "meeting_reference": "" if iss_mtg_ref == "-" else iss_mtg_ref,
                        "resolution":        iss_resolution,
                        "status":            iss_stat,
                        "evidence_reference": iss_evi,
                    }
                    _validate_issue(data)

                    iid = new_id("issue")
                    row = {
                        "issue_id":  iid,
                        "timestamp": now_str(),
                        "project_id": "PRJ-2026-0001",
                        **data,
                        "closed_date": str(_today()) if iss_stat == "Closed" else "",
                        "created_by":  st.session_state.user,
                    }
                    iss_repo.append(row)

                    # Auto-create Action
                    action_id_created = ""
                    if auto_action and iss_sev in ("High", "Critical") and act_repo is not None:
                        try:
                            aid = new_id("action")
                            action_row = {
                                "action_id":           aid,
                                "timestamp":           now_str(),
                                "source_type":         "Issue",
                                "source_id":           iid,
                                "description":         f"[{iss_sev}] {iss_desc[:200]}",
                                "owner":               iss_owner,
                                "priority":            "Critical" if iss_sev == "Critical" else "High",
                                "due_date":            str(iss_due),
                                "status":              "Open",
                                "completion_date":     "",
                                "evidence":            "",
                                "verification_status": "Not Verified",
                                "verifier":            "",
                                "verification_date":   "",
                                "comment":             f"สร้างจาก Issue {iid}",
                                "created_by":          st.session_state.user,
                            }
                            act_repo.append(action_row)
                            action_id_created = aid
                        except Exception as e:
                            st.warning(f"⚠️ สร้าง Action ไม่สำเร็จ: {e}")

                    append_audit(
                        st.session_state.user, "CREATE", "ISSUE", iid,
                        old_value="",
                        new_value=f"[{iss_sev}] {iss_desc[:80]}",
                        reason=f"Status: {iss_stat}"
                               + (f" · Auto-Action: {action_id_created}" if action_id_created else ""),
                    )

                    st.session_state["iss_last_saved"] = {
                        "id": iid, "mode": "เพิ่ม",
                        "action_id": action_id_created,
                    }
                    _reset_keys("iss_", preserve=("iss_mode", "iss_last_saved"))
                    st.rerun()

                except ValidationError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"❌ {type(e).__name__}: {e}")

        # ---------- UPDATE ----------
        else:
            st.markdown("### 🔄 อัปเดต Issue ที่มีอยู่")

            if iss_df.empty:
                st.info("ยังไม่มี Issue ให้อัปเดต")
            else:
                iss_sel = st.selectbox(
                    "เลือก Issue ID",
                    iss_df["issue_id"].astype(str).tolist(),
                    format_func=lambda x: (
                        f"{x} — "
                        f"{str(iss_df[iss_df['issue_id']==x]['description'].iloc[0])[:60]}"
                    ),
                    key="iss_upd_sel",
                )
                i_row = iss_df[iss_df["issue_id"] == iss_sel].iloc[-1]

                # Reference info
                info1, info2, info3, info4 = st.columns(4)
                with info1:
                    st.markdown(
                        f"**📌 Source:** `{i_row.get('milestone_id') or '-'}` / "
                        f"`{i_row.get('deliverable_id') or '-'}`"
                    )
                with info2:
                    sev_color = SEVERITY_COLORS.get(i_row.get("severity"), "#0B5ED7")
                    st.markdown(
                        f"**⚡ Severity:** "
                        f"<span style='color:{sev_color};font-weight:700;'>"
                        f"{i_row.get('severity')}</span>",
                        unsafe_allow_html=True,
                    )
                with info3:
                    st.markdown(f"**👤 Owner:** {i_row.get('responsible_party','-')}")
                with info4:
                    overdue = _is_overdue(i_row.get("action_due_date"), i_row.get("status"))
                    st.markdown(
                        f"**📅 Due:** {_fmt_date(i_row.get('action_due_date'))} "
                        f"{'🔴 เกิน' if overdue else ''}"
                    )

                st.markdown(f"**📝 Description:** {i_row.get('description', '-')}")

                with st.form("iss_upd_form", clear_on_submit=False):
                    st.markdown("**อัปเดตสถานะ**")
                    cU1, cU2 = st.columns(2)
                    cur_stat = i_row.get("status", "Open")
                    new_status = cU1.selectbox(
                        "Status",
                        STATUSES,
                        index=STATUSES.index(cur_stat) if cur_stat in STATUSES else 0,
                        key="issu_status",
                    )
                    cur_sev = i_row.get("severity", "Medium")
                    new_sev = cU2.selectbox(
                        "Severity",
                        SEVERITIES,
                        index=SEVERITIES.index(cur_sev) if cur_sev in SEVERITIES else 1,
                        key="issu_sev",
                    )

                    cU3, cU4 = st.columns(2)
                    cur_esc = i_row.get("escalation_level", "None") or "None"
                    new_esc = cU3.selectbox(
                        "Escalation Level",
                        ESCALATION_LEVELS,
                        index=ESCALATION_LEVELS.index(cur_esc)
                            if cur_esc in ESCALATION_LEVELS else 0,
                        key="issu_esc",
                    )
                    new_owner = cU4.text_input(
                        "Responsible Party",
                        value=str(i_row.get("responsible_party", "")),
                        key="issu_owner",
                    )

                    new_rc = st.text_input(
                        "Root Cause",
                        value=str(i_row.get("root_cause", "")),
                        key="issu_rc",
                    )
                    new_ca = st.text_area(
                        "Corrective Action",
                        value=str(i_row.get("corrective_action", "")),
                        height=70,
                        key="issu_ca",
                    )
                    new_pa = st.text_area(
                        "Preventive Action",
                        value=str(i_row.get("preventive_action", "")),
                        height=70,
                        key="issu_pa",
                    )

                    cU5, cU6 = st.columns(2)
                    cur_due = _to_date(i_row.get("action_due_date")) or _today()
                    new_due = cU5.date_input(
                        "Action Due Date", value=cur_due, key="issu_due",
                    )
                    new_evi = cU6.text_input(
                        "Evidence Reference",
                        value=str(i_row.get("evidence_reference", "")),
                        key="issu_evi",
                    )

                    new_resolution = st.text_area(
                        "Resolution (บังคับถ้า Closed)",
                        value=str(i_row.get("resolution", "")),
                        height=80,
                        key="issu_resolution",
                    )

                    cBtn1, cBtn2 = st.columns([1, 1])
                    save_upd = cBtn1.form_submit_button(
                        "💾 บันทึกการอัปเดต", type="primary", use_container_width=True,
                    )
                    reset_upd = cBtn2.form_submit_button(
                        "↩️ ยกเลิกการแก้ไข", use_container_width=True,
                    )

                if reset_upd:
                    _reset_keys("issu_")
                    st.rerun()

                if save_upd:
                    try:
                        data = {
                            "milestone_id":      str(i_row.get("milestone_id", "")),
                            "deliverable_id":    str(i_row.get("deliverable_id", "")),
                            "tor_clause":        str(i_row.get("tor_clause", "")),
                            "issue_date":        str(i_row.get("issue_date", "")),
                            "description":       str(i_row.get("description", "")),
                            "impact":            str(i_row.get("impact", "")),
                            "severity":          new_sev,
                            "root_cause":        new_rc,
                            "responsible_party": new_owner,
                            "corrective_action": new_ca,
                            "preventive_action": new_pa,
                            "action_due_date":   str(new_due),
                            "escalation_level":  new_esc,
                            "meeting_reference": str(i_row.get("meeting_reference", "")),
                            "resolution":        new_resolution,
                            "status":            new_status,
                            "evidence_reference": new_evi,
                        }
                        _validate_issue(data, prev_status=cur_stat)

                        # Determine closed_date
                        if new_status == "Closed":
                            closed_date = (
                                str(i_row.get("closed_date")) if i_row.get("closed_date")
                                else str(_today())
                            )
                        else:
                            closed_date = ""

                        new_row = {
                            "issue_id":  iss_sel,
                            "timestamp": now_str(),
                            "project_id": "PRJ-2026-0001",
                            **data,
                            "closed_date": closed_date,
                            "created_by":  st.session_state.user,
                        }
                        iss_repo.append(new_row)
                        append_audit(
                            st.session_state.user, "UPDATE", "ISSUE", iss_sel,
                            old_value=f"{cur_stat} / {cur_sev}",
                            new_value=f"{new_status} / {new_sev}",
                            reason=f"อัปเดต Issue (owner: {new_owner})",
                        )

                        st.session_state["iss_last_saved"] = {
                            "id": iss_sel, "mode": "อัปเดต", "action_id": "",
                        }
                        _reset_keys("issu_", preserve=("iss_last_saved",))
                        st.rerun()

                    except ValidationError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"❌ {type(e).__name__}: {e}")

    # ============================================================
    # TAB 2 — HISTORY
    # ============================================================
    with t2:
        st.markdown("### 📜 ประวัติ & ติดตาม Issue")

        if iss_df.empty:
            st.info("ยังไม่มี Issue — เริ่มที่แท็บ ➕")
        else:
            # ---- Filters ----
            c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
            with c1:
                f_sev = st.multiselect(
                    "Severity", SEVERITIES,
                    default=SEVERITIES, key="h_sev",
                )
            with c2:
                f_stat = st.multiselect(
                    "Status", STATUSES,
                    default=["Open", "In Progress", "Escalated"], key="h_stat",
                )
            with c3:
                overdue_only = st.checkbox("เฉพาะ Overdue", key="h_od")
            with c4:
                search = st.text_input(
                    "🔍 Search (Description / Owner / Issue ID)",
                    value="", key="h_search",
                )

            # ---- Apply ----
            view = iss_df.copy()
            if f_sev:
                view = view[view["severity"].isin(f_sev)]
            if f_stat:
                view = view[view["status"].isin(f_stat)]
            if overdue_only:
                view = view[
                    view.apply(
                        lambda r: _is_overdue(
                            r.get("action_due_date"), r.get("status")
                        ),
                        axis=1,
                    )
                ]
            if search.strip():
                s = search.strip().lower()
                view = view[
                    view["description"].astype(str).str.lower().str.contains(s, na=False)
                    | view["responsible_party"].astype(str).str.lower().str.contains(s, na=False)
                    | view["issue_id"].astype(str).str.lower().str.contains(s, na=False)
                ]

            # ---- Sort: critical first, then by due date ----
            sev_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
            view = view.copy()
            view["_sev_order"] = view["severity"].map(sev_order).fillna(9)
            view["_due_dt"] = pd.to_datetime(view["action_due_date"], errors="coerce")
            view = view.sort_values(
                ["_sev_order", "_due_dt"],
                ascending=[True, True],
                na_position="last",
            )

            st.caption(f"แสดง {len(view)} / {len(iss_df)} รายการ (เรียงตาม Severity + Due)")

            # ---- Card list ----
            for _, r in view.iterrows():
                overdue = _is_overdue(r.get("action_due_date"), r.get("status"))
                dl = _days_left(r.get("action_due_date"))

                if r["status"] == "Closed":
                    border = "#2E7D32"
                    time_txt = f"✅ ปิดเมื่อ {_fmt_date(r.get('closed_date'))}"
                elif overdue:
                    border = "#D32F2F"
                    time_txt = f"🔴 เกินกำหนด {-dl} วัน"
                elif dl is not None and dl <= 3:
                    border = "#F57C00"
                    time_txt = f"⏰ อีก {dl} วัน"
                elif r["status"] == "Escalated":
                    border = "#D32F2F"
                    time_txt = f"🚨 ยกระดับ — อีก {dl} วัน" if dl is not None else "🚨 ยกระดับ"
                else:
                    border = SEVERITY_COLORS.get(r.get("severity", "Medium"), "#0B5ED7")
                    time_txt = f"📅 อีก {dl} วัน" if dl is not None else "-"

                st.markdown(_build_issue_card(r, border, time_txt), unsafe_allow_html=True)

            # ---- Detail Table ----
            with st.expander("📋 ตารางแบบละเอียด"):
                show_cols = [c for c in [
                    "issue_id", "severity", "status", "escalation_level",
                    "issue_date", "action_due_date", "closed_date",
                    "responsible_party", "milestone_id", "deliverable_id",
                    "tor_clause", "root_cause",
                    "corrective_action", "preventive_action",
                    "resolution", "evidence_reference",
                    "description", "impact",
                ] if c in view.columns]
                st.dataframe(
                    view[show_cols],
                    use_container_width=True,
                    hide_index=True,
                )

            # ---- Soft Delete + Restore ----
            if st.session_state.role in ("admin", "monitoring"):
                st.markdown("---")
                with st.expander("🗑️ ลบ / คืนค่า (Soft Delete)", expanded=False):
                    st.caption("⚠️ Soft Delete = ซ่อนจาก UI, ข้อมูลยังอยู่ใน CSV")

                    colA, colB = st.columns(2)

                    with colA:
                        st.markdown("**🗑️ Soft Delete**")
                        del_id = st.selectbox(
                            "เลือก Issue ID",
                            iss_df["issue_id"].astype(str).tolist(),
                            key="h_del_sel",
                        )
                        del_reason = st.text_input(
                            "เหตุผลที่ลบ", key="h_del_reason",
                        )
                        if st.button("🗑️ Soft Delete", type="primary", key="h_del_btn"):
                            if not del_reason.strip():
                                st.error("⚠️ กรุณาระบุเหตุผล")
                            else:
                                try:
                                    iss_repo.soft_delete(
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
                            vd_i = (
                                vd[vd["record_type"] == "issue"]
                                if not vd.empty else vd
                            )
                            if vd_i.empty:
                                st.info("ไม่มีรายการที่ถูก Void")
                            else:
                                rid = st.selectbox(
                                    "เลือก Issue ID",
                                    vd_i["record_id"].tolist(),
                                    key="h_restore_sel",
                                )
                                if st.button("↩️ คืนค่า", key="h_restore_btn"):
                                    if iss_repo.restore(rid, st.session_state.user):
                                        st.success(f"✅ คืนค่า `{rid}` แล้ว")
                                        st.rerun()
                        except Exception as e:
                            st.error(f"❌ {e}")

    # ============================================================
    # TAB 3 — CHARTS
    # ============================================================
    with t3:
        st.markdown("### 📈 Charts สรุป Issues")

        if iss_df.empty:
            st.info("ยังไม่มีข้อมูลสำหรับสร้างกราฟ")
        else:
            c1, c2 = st.columns(2)

            # --- Severity ---
            with c1:
                st.markdown("#### ตาม Severity")
                sev_counts = iss_df["severity"].value_counts().reindex(SEVERITIES).fillna(0)
                fig1 = go.Figure(data=[go.Pie(
                    labels=sev_counts.index.tolist(),
                    values=sev_counts.values.tolist(),
                    hole=0.5,
                    marker=dict(colors=[
                        SEVERITY_COLORS.get(x, "#0B5ED7") for x in sev_counts.index
                    ]),
                )])
                fig1.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(fig1, use_container_width=True)

            # --- Status ---
            with c2:
                st.markdown("#### ตามสถานะ")
                st_counts = iss_df["status"].value_counts().reindex(STATUSES).fillna(0)
                status_colors = {
                    "Open": "#D32F2F",
                    "In Progress": "#F57C00",
                    "Escalated": "#B71C1C",
                    "Closed": "#2E7D32",
                }
                fig2 = go.Figure(data=[go.Bar(
                    x=st_counts.index.tolist(),
                    y=st_counts.values.tolist(),
                    marker_color=[status_colors.get(x, "#0B5ED7") for x in st_counts.index],
                    text=st_counts.values.astype(int).tolist(),
                    textposition="outside",
                )])
                fig2.update_layout(
                    height=320, plot_bgcolor="#FAFBFC",
                    yaxis_title="จำนวน",
                    margin=dict(l=10, r=10, t=30, b=40),
                )
                st.plotly_chart(fig2, use_container_width=True)

            # --- Responsible (Top 10) ---
            st.markdown("#### ตาม Responsible Party (Top 10 — เฉพาะที่ยังไม่ปิด)")
            open_iss = iss_df[iss_df["status"] != "Closed"]
            owner_counts = (
                open_iss["responsible_party"].value_counts().head(10)
                if not open_iss.empty else pd.Series(dtype=int)
            )
            if owner_counts.empty:
                st.info("ไม่มีข้อมูล Responsible Party (ที่ยังเปิดอยู่)")
            else:
                fig3 = go.Figure(data=[go.Bar(
                    x=owner_counts.values.tolist(),
                    y=owner_counts.index.tolist(),
                    orientation="h",
                    marker_color="#F57C00",
                    text=owner_counts.values.tolist(),
                    textposition="outside",
                )])
                fig3.update_layout(
                    height=max(280, len(owner_counts) * 38),
                    plot_bgcolor="#FAFBFC",
                    xaxis_title="จำนวน Issue",
                    margin=dict(l=10, r=60, t=20, b=40),
                )
                st.plotly_chart(fig3, use_container_width=True)

            # --- Open by Severity ---
            st.markdown("#### 🔴 Open Issues by Severity")
            if open_iss.empty:
                st.success("✅ ไม่มี Issue ที่เปิดอยู่")
            else:
                open_sev = open_iss["severity"].value_counts().reindex(SEVERITIES).fillna(0)
                fig4 = go.Figure(data=[go.Bar(
                    x=open_sev.index.tolist(),
                    y=open_sev.values.tolist(),
                    marker_color=[
                        SEVERITY_COLORS.get(x, "#0B5ED7") for x in open_sev.index
                    ],
                    text=open_sev.values.astype(int).tolist(),
                    textposition="outside",
                )])
                fig4.update_layout(
                    height=300, plot_bgcolor="#FFF5F5",
                    yaxis_title="จำนวน",
                    margin=dict(l=10, r=10, t=20, b=40),
                )
                st.plotly_chart(fig4, use_container_width=True)

    # ============================================================
    # TAB 4 — CSV
    # ============================================================
    with t4:
        st.markdown("### 📥 ข้อมูล CSV (อ่านเท่านั้น)")
        st.caption("ไฟล์จริง: `data/history/issue_history.csv`")

        if iss_df.empty:
            st.info("ยังไม่มีข้อมูล")
        else:
            st.dataframe(iss_df, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ ดาวน์โหลด issue_history.csv",
                data=iss_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"issue_history_{today_str()}.csv",
                mime="text/csv",
                key="dl_iss",
            )