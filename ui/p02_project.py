"""Project / Milestone — จัดการข้อมูลโครงการ + งวดงาน + บุคลากร (TOR ข้อ 12)

เวอร์ชันนี้เพิ่ม:
- 👥 แท็บ Personnel (TOR ข้อ 12): 8 ตำแหน่ง + ผู้ช่วย 2 + ผู้ประสาน 1
- ⚠️ ตารางค่าปรับ (TOR ข้อ 10) ในแท็บ Milestone
- 📄 Document submission summary (M1-M4: USB 2 | M5: USB 10)
"""
import streamlit as st
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

from repositories.base_repo import MasterRepo
from repositories.deliverable_repo import DeliverableRepo
from repositories.progress_repo import ProgressRepo
from repositories.acceptance_repo import AcceptanceRepo, PaymentRepo
from core.time_util import now_str, today_str
from core.audit import append_audit
from core.validator import ValidationError
from config_loader import load_settings


# ============================================================
# CONSTANTS
# ============================================================
PROJECT_FIELDS = [
    "project_id", "project_name", "contract_no", "consultant_name",
    "contract_date", "project_start_date", "project_duration_days", "project_end_date",
    "total_contract_value", "project_manager", "status", "created_at", "updated_at",
]

MILESTONE_FIELDS = [
    "milestone_id", "project_id", "milestone_no", "milestone_name",
    "tor_reference", "due_day", "due_date", "payment_percent", "payment_amount",
    "submission_date", "acceptance_date", "payment_date", "status", "updated_at",
]

MILESTONE_STATUSES = [
    "Not Started", "In Progress", "Submitted", "Under Review",
    "Revision Required", "Ready for Acceptance", "Accepted",
    "Payment Processing", "Paid", "Closed",
]

PROJECT_STATUSES = ["Active", "On Hold", "Closed"]

FINAL_MILESTONE_STATUSES = ("Accepted", "Payment Processing", "Paid", "Closed")


# ============================================================
# HELPERS
# ============================================================
def _to_date(s):
    try:
        if pd.isna(s) or s == "":
            return None
        return pd.to_datetime(str(s)).date()
    except Exception:
        return None


def _safe_date_input(label, value, key=None, min_value=None, max_value=None):
    """date_input ที่ไม่ crash ถ้าค่าเดิมเพี้ยน"""
    d = _to_date(value) or date.today()
    return st.date_input(label, value=d, key=key,
                         min_value=min_value, max_value=max_value)


def _days_between(d1, d2):
    a, b = _to_date(d1), _to_date(d2)
    if a is None or b is None:
        return None
    return (b - a).days


def _pct(num, den):
    return 0.0 if not den else (num / den) * 100


def _fmt_date(d):
    dd = _to_date(d)
    return dd.strftime("%d/%m/%Y") if dd else "-"


def _fmt_money(v):
    try:
        return f"{float(v):,.0f}"
    except Exception:
        return "-"


def _status_badge(s):
    m = {
        "Not Started": "⚪ ยังไม่เริ่ม",
        "In Progress": "🔵 กำลังทำ",
        "Submitted": "🟣 ส่งแล้ว",
        "Under Review": "🟠 กำลังตรวจ",
        "Revision Required": "🟠 ต้องแก้ไข",
        "Ready for Acceptance": "🟢 พร้อมตรวจรับ",
        "Accepted": "🟢 ตรวจรับแล้ว",
        "Payment Processing": "🟡 กำลังเบิก",
        "Paid": "✅ จ่ายแล้ว",
        "Closed": "✅ ปิดแล้ว",
    }
    return m.get(s, s or "-")


def _validate_project(p: dict):
    """ตรวจสอบข้อมูลโครงการ"""
    cdate = _to_date(p.get("contract_date"))
    sdate = _to_date(p.get("project_start_date"))
    edate = _to_date(p.get("project_end_date"))

    if cdate and sdate and sdate < cdate:
        raise ValidationError("⚠️ วันเริ่มโครงการต้องไม่ก่อนวันลงนามสัญญา")

    if sdate and edate and edate < sdate:
        raise ValidationError("⚠️ วันสิ้นสุดโครงการต้องไม่ก่อนวันเริ่มโครงการ")

    if int(p.get("project_duration_days", 0)) <= 0:
        raise ValidationError("⚠️ ระยะเวลาโครงการต้องมากกว่า 0 วัน")

    if float(p.get("total_contract_value", 0)) <= 0:
        raise ValidationError("⚠️ มูลค่าสัญญาต้องมากกว่า 0 บาท")


def _validate_milestone(m: dict):
    """ตรวจสอบข้อมูล Milestone"""
    dd = int(m.get("due_day", 0))
    if dd <= 0 or dd > 365:
        raise ValidationError("⚠️ Due Day ต้องอยู่ระหว่าง 1–365")

    pct = float(m.get("payment_percent", 0))
    if pct <= 0 or pct > 100:
        raise ValidationError("⚠️ Payment % ต้องอยู่ระหว่าง 0–100")


def _milestone_progress(milestone_id: str, dl_df, prog_df) -> float:
    """คำนวณ % ความคืบหน้าของ milestone จาก deliverables"""
    if dl_df.empty or prog_df.empty:
        return 0.0
    m_dl = dl_df[dl_df["milestone_id"] == milestone_id]
    if m_dl.empty:
        return 0.0
    total_w = 0.0
    weighted = 0.0
    for _, d in m_dl.iterrows():
        w = float(d.get("weight", 0) or 0)
        p = prog_df[prog_df["deliverable_id"] == d["deliverable_id"]]
        latest = float(p["actual_percent"].iloc[-1]) if len(p) else 0.0
        weighted += w * latest
        total_w += w
    return weighted / total_w if total_w else 0.0


def _mini_tile(label, value, sub, color):
    return f"""
    <div style="background:#FFFFFF;border-radius:10px;padding:12px 14px;
                border-left:4px solid {color};box-shadow:0 2px 6px rgba(0,51,102,0.06);height:100%;">
        <div style="font-size:11.5px;color:#5A5A5A;font-weight:600;">{label}</div>
        <div style="font-size:20px;font-weight:700;color:#003366;line-height:1.1;margin:4px 0;">{value}</div>
        <div style="font-size:11px;color:{color};">{sub}</div>
    </div>
    """


# ============================================================
# MAIN
# ============================================================
def render():
    st.title("⚙️ Project / Milestone")
    st.caption("จัดการข้อมูลโครงการ · งวดงานส่งมอบ · บุคลากร (Source of Truth)")

    proj_repo = MasterRepo("project_master.csv", PROJECT_FIELDS)
    ms_repo = MasterRepo("milestone_master.csv", MILESTONE_FIELDS)

    cfg = load_settings()

    # ----- โหลดข้อมูล -----
    proj_df = proj_repo.read()
    ms_df = ms_repo.read()

    if proj_df.empty:
        st.error("⚠️ ไม่พบข้อมูลโครงการ — กรุณารัน bootstrap ก่อน")
        return

    proj = proj_df.iloc[0]

    dl_df = DeliverableRepo().read()
    prog_df = ProgressRepo().read()
    acc_df = AcceptanceRepo().read()
    pay_df = PaymentRepo().read()

    # ============================================================
    # KPI TILES
    # ============================================================
    st.markdown("### 📊 ข้อมูลสรุปโครงการ")

    today = date.today()
    start_d = _to_date(proj["project_start_date"])
    end_d = _to_date(proj["project_end_date"])
    total_days = int(proj.get("project_duration_days", 360) or 360)
    days_elapsed = max((today - start_d).days, 0) if start_d else 0
    days_remaining = (end_d - today).days if end_d else 0

    k1, k2, k3, k4 = st.columns(4)

    with k1:
        st.markdown(_mini_tile("💰 มูลค่าสัญญา", f"{_fmt_money(proj['total_contract_value'])} ฿",
                               proj["contract_no"], "#0B5ED7"), unsafe_allow_html=True)
    with k2:
        st.markdown(_mini_tile("👥 ที่ปรึกษา", proj["consultant_name"],
                               proj.get("project_manager", "-"), "#6A1B9A"), unsafe_allow_html=True)
    with k3:
        st.markdown(_mini_tile("⏱️ วันที่ผ่านไป", f"{days_elapsed} วัน",
                               f"จาก {total_days} วัน", "#00838F"), unsafe_allow_html=True)
    with k4:
        rem_color = "#2E7D32" if days_remaining > 60 else ("#F57C00" if days_remaining > 0 else "#D32F2F")
        st.markdown(_mini_tile("⏳ วันคงเหลือ", f"{max(days_remaining, 0)} วัน",
                               _fmt_date(proj["project_end_date"]), rem_color), unsafe_allow_html=True)

    st.markdown("---")

    # ============================================================
    # TABS — เพิ่มแท็บ Personnel เป็นแท็บที่ 3
    # ============================================================
    t1, t2, t3, t4 = st.tabs([
        "📋 ข้อมูลโครงการ",
        "📊 Milestone 1–5",
        "👥 Personnel (TOR ข้อ 12)",
        "📥 CSV",
    ])

    # ============================================================
    # TAB 1 — PROJECT INFO
    # ============================================================
    with t1:
        st.markdown("### 📋 ข้อมูลโครงการปัจจุบัน")
        st.dataframe(proj_df, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("### ✏️ แก้ไขข้อมูลโครงการ")
        st.caption("💡 เมื่อแก้ 'วันเริ่มโครงการ' หรือ 'ระยะเวลา' ระบบจะคำนวณ 'วันสิ้นสุด' ใหม่ให้อัตโนมัติ")

        with st.form("project_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            name = c1.text_input("ชื่อโครงการ", value=str(proj["project_name"]), key="pj_name")
            contract = c2.text_input("เลขที่สัญญา", value=str(proj["contract_no"]), key="pj_contract")
            consultant = c1.text_input("ชื่อที่ปรึกษา", value=str(proj["consultant_name"]), key="pj_consultant")
            pm = c2.text_input("ผู้จัดการโครงการ", value=str(proj.get("project_manager", "")), key="pj_pm")

            c3, c4 = st.columns(2)
            cdate = _safe_date_input("วันลงนามสัญญา", proj["contract_date"], key="pj_cdate")
            sdate = _safe_date_input("วันเริ่มโครงการ", proj["project_start_date"], key="pj_sdate")

            c5, c6 = st.columns(2)
            dur = c5.number_input("ระยะเวลา (วัน)", value=int(proj.get("project_duration_days", 360) or 360),
                                   min_value=1, max_value=1000, step=10, key="pj_dur")
            val = c6.number_input("มูลค่าสัญญา (บาท)", value=float(proj.get("total_contract_value", 0) or 0),
                                   min_value=0.0, step=100000.0, key="pj_val")

            # Auto-calc end date preview
            auto_end = sdate + timedelta(days=int(dur)) if sdate and dur else None
            if auto_end:
                st.info(f"📅 **วันสิ้นสุดสัญญา (คำนวณอัตโนมัติ):** `{auto_end.strftime('%d/%m/%Y')}`")

            pstat = st.selectbox(
                "สถานะโครงการ",
                PROJECT_STATUSES,
                index=PROJECT_STATUSES.index(proj["status"]) if proj["status"] in PROJECT_STATUSES else 0,
                key="pj_status",
            )

            st.caption(f"🗓️ สร้างเมื่อ: `{proj.get('created_at', '-')}`  ·  "
                       f"🔄 แก้ไขล่าสุด: `{proj.get('updated_at', '-')}`")

            c_btn1, c_btn2 = st.columns([1, 1])
            submitted = c_btn1.form_submit_button("💾 บันทึก", type="primary", use_container_width=True)
            reset_clicked = c_btn2.form_submit_button("↩️ ยกเลิกการแก้ไข", use_container_width=True)

        if reset_clicked:
            for k in ["pj_name", "pj_contract", "pj_consultant", "pj_pm",
                      "pj_cdate", "pj_sdate", "pj_dur", "pj_val", "pj_status"]:
                st.session_state.pop(k, None)
            st.rerun()

        if submitted:
            try:
                new_data = proj.to_dict()
                new_data.update({
                    "project_name": name,
                    "contract_no": contract,
                    "consultant_name": consultant,
                    "project_manager": pm,
                    "contract_date": str(cdate),
                    "project_start_date": str(sdate),
                    "project_duration_days": int(dur),
                    "project_end_date": str(auto_end) if auto_end else proj.get("project_end_date", ""),
                    "total_contract_value": float(val),
                    "status": pstat,
                    "updated_at": now_str(),
                })
                _validate_project(new_data)

                old_data = proj.to_dict()
                proj_repo.upsert(new_data, key="project_id")

                append_audit(
                    st.session_state.user, "UPDATE", "PROJECT",
                    new_data["project_id"],
                    old_value=str(old_data)[:500],
                    new_value=str(new_data)[:500],
                    reason="แก้ไขข้อมูลโครงการ",
                )

                st.success(f"✅ บันทึกแล้ว — Updated: {new_data['updated_at']}")
                st.rerun()
            except ValidationError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"❌ {type(e).__name__}: {e}")

    # ============================================================
    # TAB 2 — MILESTONE (+ Penalty Section)
    # ============================================================
    with t2:
        if ms_df.empty:
            st.warning("ไม่พบข้อมูล Milestone")
        else:
            # --- Timeline summary ---
            st.markdown("### 📊 สรุปงวดงาน (Milestone Timeline)")
            summary_rows = []
            for _, m in ms_df.iterrows():
                mid = m["milestone_id"]
                m_actual = _milestone_progress(mid, dl_df, prog_df)

                m_acc = acc_df[acc_df["milestone_id"] == mid] if not acc_df.empty else acc_df
                m_pay = pay_df[pay_df["milestone_id"] == mid] if not pay_df.empty else pay_df
                acc_status = m_acc["status"].iloc[-1] if len(m_acc) else "Not Submitted"
                pay_status = m_pay["status"].iloc[-1] if len(m_pay) else "—"

                dr = _days_between(today, m["due_date"])
                if dr is None:
                    dr_txt = "-"
                elif dr > 0:
                    dr_txt = f"อีก {dr} วัน"
                elif dr == 0:
                    dr_txt = "⚠️ ครบกำหนดวันนี้"
                else:
                    dr_txt = f"🔴 เกิน {-dr} วัน"

                summary_rows.append({
                    "Milestone": f"M{m['milestone_no']} {m['milestone_name']}",
                    "Due Date":  _fmt_date(m["due_date"]),
                    "วันคงเหลือ": dr_txt,
                    "Progress":  f"{m_actual:.0f}%",
                    "Payment %": f"{float(m['payment_percent']):.1f}%",
                    "ยอดจ่าย (฿)": _fmt_money(m["payment_amount"]),
                    "Acceptance": _status_badge(acc_status),
                    "Payment":    _status_badge(pay_status),
                })

            st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

            # ═══════════════════════════════════════════════════════════
            # ⚠️ PENALTY SUMMARY (TOR ข้อ 10)
            # ═══════════════════════════════════════════════════════════
            st.markdown("---")
            st.markdown("### ⚠️ ค่าปรับล่าช้า (TOR ข้อ 10)")

            penalty_cfg = cfg.get("penalty", {})
            penalty_pct = float(penalty_cfg.get("late_delivery_pct_per_day", 0.10))
            total_val = float(proj["total_contract_value"])
            daily_penalty = total_val * penalty_pct / 100.0

            st.markdown(
                f'<div style="background:#F0F4F8;border-left:4px solid #0B5ED7;'
                f'padding:10px 14px;border-radius:8px;font-size:12.5px;'
                f'color:#003366;margin-bottom:10px;">'
                f'💰 อัตราค่าปรับ: <b>{penalty_pct:.2f}% ของราคาจ้างต่อวัน</b> '
                f'= <b>{daily_penalty:,.2f} ฿/วัน</b> '
                f'<span style="color:#666;">(จากราคาจ้าง {total_val:,.0f} ฿)</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # ---- หา milestone ที่เกินกำหนด ----
            overdue_rows = []
            total_penalty = 0.0
            for _, m in ms_df.iterrows():
                due = _to_date(m["due_date"])
                if due is None:
                    continue
                # ถ้าปิดงานแล้ว หรือ อยู่ในสถานะ final → ไม่คิดค่าปรับ
                acc_status = "Not Submitted"
                m_acc = acc_df[acc_df["milestone_id"] == m["milestone_id"]] if not acc_df.empty else acc_df
                if len(m_acc):
                    acc_status = m_acc["status"].iloc[-1]

                if m["status"] in FINAL_MILESTONE_STATUSES or acc_status in FINAL_MILESTONE_STATUSES:
                    continue

                days_late = (today - due).days
                if days_late <= 0:
                    continue

                penalty = days_late * daily_penalty
                total_penalty += penalty
                overdue_rows.append({
                    "Milestone":       f"M{m['milestone_no']} {m['milestone_name']}",
                    "Due Date":        _fmt_date(m["due_date"]),
                    "เกินกำหนด (วัน)":  days_late,
                    "ค่าปรับสะสม (฿)":  f"{penalty:,.2f}",
                    "สถานะ":           _status_badge(m["status"]),
                })

            if overdue_rows:
                st.dataframe(pd.DataFrame(overdue_rows),
                             use_container_width=True, hide_index=True)
                st.markdown(
                    f'<div style="background:#FFEBEE;border-left:4px solid #D32F2F;'
                    f'padding:12px 16px;border-radius:8px;font-size:13px;'
                    f'color:#B71C1C;margin-top:10px;">'
                    f'🚨 <b>ค่าปรับสะสมทั้งหมด: {total_penalty:,.2f} ฿</b> '
                    f'({len(overdue_rows)} งวดที่เกินกำหนด)'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
                    f'padding:10px 14px;border-radius:8px;font-size:12.5px;'
                    f'color:#2E7D32;">'
                    f'✅ <b>ไม่มีค่าปรับ</b> — ทุกงวดงานเป็นไปตามกำหนด'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # ═══════════════════════════════════════════════════════════
            # 📄 DOCUMENT SUBMISSION (TOR ข้อ 7)
            # ═══════════════════════════════════════════════════════════
            st.markdown("---")
            st.markdown("### 📄 จำนวนเอกสารที่ต้องส่งมอบ (TOR ข้อ 7)")

            doc_cfg = cfg.get("document_submission", {})
            m14 = doc_cfg.get("M1-M4", {"hard_copies": 2, "usb_copies": 2, "format": "Word+PDF"})
            m5 = doc_cfg.get("M5", {"hard_copies": 2, "usb_copies": 10, "format": "Word+PDF"})

            doc_rows = []
            for _, m in ms_df.iterrows():
                is_final = int(m["milestone_no"]) == 5
                d = m5 if is_final else m14
                doc_rows.append({
                    "Milestone":  f"M{m['milestone_no']} {m['milestone_name']}",
                    "ชุด (Hard)":  f"{d['hard_copies']} ชุด",
                    "USB":        f"{d['usb_copies']} อัน",
                    "Format":     d["format"],
                })
            st.dataframe(pd.DataFrame(doc_rows), use_container_width=True, hide_index=True)

            # --- Select & Edit ---
            st.markdown("---")
            st.markdown("### ✏️ แก้ไข Milestone")

            ms_options = ms_df["milestone_id"].tolist()
            ms_sel = st.selectbox(
                "เลือก Milestone ที่จะแก้ไข",
                ms_options,
                format_func=lambda x: f"{x} — {ms_df[ms_df['milestone_id']==x]['milestone_name'].iloc[0]}",
                key="ms_select_main",
            )
            m = ms_df[ms_df["milestone_id"] == ms_sel].iloc[0]

            # แสดงรายละเอียดก่อนแก้
            info_col1, info_col2, info_col3 = st.columns(3)
            with info_col1:
                st.markdown(f"**📅 Due Date ปัจจุบัน:** {_fmt_date(m['due_date'])}  \n"
                            f"**🔢 Due Day:** {int(m['due_day'])} วัน")
            with info_col2:
                st.markdown(f"**💰 Payment:** {float(m['payment_percent']):.1f}%  \n"
                            f"**💵 ยอดจ่าย:** {_fmt_money(m['payment_amount'])} ฿")
            with info_col3:
                st.markdown(f"**📌 สถานะปัจจุบัน:** {_status_badge(m['status'])}  \n"
                            f"**🔄 Updated:** `{m.get('updated_at', '-')}`")

            with st.form("ms_form", clear_on_submit=False):
                c1, c2, c3 = st.columns(3)
                nm = c1.text_input("ชื่อ Milestone", value=str(m["milestone_name"]), key="ms_name")
                dd = c2.number_input("Due Day (วันที่นับจากวันเริ่ม)", value=int(m["due_day"]),
                                      min_value=1, max_value=365, step=10, key="ms_dd")
                pct = c3.number_input("Payment %", value=float(m["payment_percent"]),
                                       min_value=0.0, max_value=100.0, step=1.0, key="ms_pct")

                # Auto-calc due date
                auto_ms_end = start_d + timedelta(days=int(dd)) if start_d else None

                c4, c5 = st.columns(2)
                tor_ref = c4.text_input("TOR Reference", value=str(m.get("tor_reference", "")), key="ms_tor")
                default_due = _to_date(m["due_date"]) or auto_ms_end or date.today()
                due = c5.date_input("Due Date (แก้เองได้)", value=default_due, key="ms_due")

                if auto_ms_end:
                    st.info(f"📅 **Due Date ตาม Due Day:** `{auto_ms_end.strftime('%d/%m/%Y')}` "
                            f"(ถ้าไม่ต้องการ override ให้นำมาใส่ในช่อง Due Date)")

                cur_stat_idx = MILESTONE_STATUSES.index(m["status"]) if m["status"] in MILESTONE_STATUSES else 0
                stat = st.selectbox("สถานะ", MILESTONE_STATUSES, index=cur_stat_idx, key="ms_status")

                c6, c7, c8 = st.columns(3)
                sub_date_val = _to_date(m.get("submission_date"))
                acc_date_val = _to_date(m.get("acceptance_date"))
                pay_date_val = _to_date(m.get("payment_date"))

                sub_date = c6.date_input("Submission Date", value=sub_date_val or date.today(), key="ms_sub")
                acc_date = c7.date_input("Acceptance Date", value=acc_date_val or date.today(), key="ms_acc")
                pay_date = c8.date_input("Payment Date", value=pay_date_val or date.today(), key="ms_pay")

                c_btn1, c_btn2 = st.columns([1, 1])
                submitted_ms = c_btn1.form_submit_button("💾 บันทึก Milestone",
                                                          type="primary", use_container_width=True)
                reset_ms = c_btn2.form_submit_button("↩️ ยกเลิกการแก้ไข", use_container_width=True)

            if reset_ms:
                for k in ["ms_name", "ms_dd", "ms_pct", "ms_tor", "ms_due",
                          "ms_status", "ms_sub", "ms_acc", "ms_pay"]:
                    st.session_state.pop(k, None)
                st.rerun()

            if submitted_ms:
                try:
                    new_ms = m.to_dict()
                    new_ms.update({
                        "milestone_name": nm,
                        "tor_reference": tor_ref,
                        "due_day": int(dd),
                        "due_date": str(due),
                        "payment_percent": float(pct),
                        "payment_amount": float(proj["total_contract_value"]) * float(pct) / 100,
                        "status": stat,
                        "submission_date": str(sub_date) if sub_date_val else "",
                        "acceptance_date": str(acc_date) if acc_date_val else "",
                        "payment_date": str(pay_date) if pay_date_val else "",
                        "updated_at": now_str(),
                    })
                    _validate_milestone(new_ms)

                    old_ms = m.to_dict()
                    ms_repo.upsert(new_ms, key="milestone_id")

                    append_audit(
                        st.session_state.user, "UPDATE", "MILESTONE",
                        new_ms["milestone_id"],
                        old_value=str(old_ms)[:500],
                        new_value=str(new_ms)[:500],
                        reason="แก้ไขข้อมูล Milestone",
                    )

                    st.success(f"✅ บันทึก Milestone `{m['milestone_id']}` แล้ว")
                    st.rerun()
                except ValidationError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"❌ {type(e).__name__}: {e}")

            # --- Validation ของทั้งชุด ---
            st.markdown("---")
            st.markdown("### 🧪 ตรวจสอบความสอดคล้องของ Milestone ทั้งชุด")
            total_pct = ms_df["payment_percent"].astype(float).sum()
            if abs(total_pct - 100) < 0.01:
                st.markdown(f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
                            f'padding:10px 14px;border-radius:8px;">'
                            f'✅ <b>Payment % รวม = {total_pct:.2f}%</b> — ถูกต้อง (ครบ 100%)'
                            f'</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="background:#FFEBEE;border-left:4px solid #D32F2F;'
                            f'padding:10px 14px;border-radius:8px;">'
                            f'❌ <b>Payment % รวม = {total_pct:.2f}%</b> — ไม่ครบ 100% '
                            f'(ต้องแก้ให้รวม = 100.00%)'
                            f'</div>', unsafe_allow_html=True)

            # ตรวจ due date sequence
            sorted_ms = ms_df.sort_values("due_day")
            prev_day = 0
            seq_ok = True
            for _, r in sorted_ms.iterrows():
                if int(r["due_day"]) <= prev_day:
                    seq_ok = False
                    break
                prev_day = int(r["due_day"])

            if seq_ok:
                st.markdown(f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
                            f'padding:10px 14px;border-radius:8px;margin-top:8px;">'
                            f'✅ <b>Due Day เรียงจากน้อยไปมาก</b> — ถูกต้อง'
                            f'</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="background:#FFF8E1;border-left:4px solid #F57C00;'
                            f'padding:10px 14px;border-radius:8px;margin-top:8px;">'
                            f'⚠️ <b>Due Day ไม่เรียงจากน้อยไปมาก</b> — ควรตรวจสอบ'
                            f'</div>', unsafe_allow_html=True)

    # ============================================================
    # ★ TAB 3 — PERSONNEL (TOR ข้อ 12)
    # ============================================================
    with t3:
        st.markdown("### 👥 บุคลากรโครงการ (TOR ข้อ 12)")
        st.caption(
            "บุคลากรหลัก 8 ตำแหน่ง + ผู้ช่วย 2 ตำแหน่ง + ผู้ประสานงาน 1 ตำแหน่ง "
            "รวม 11 คน — ตามข้อกำหนด TOR"
        )

        psn_path = Path(__file__).parent.parent / "data" / "master" / "personnel_master.csv"

        if not psn_path.exists():
            st.info(
                "ℹ️ ยังไม่มีไฟล์ `personnel_master.csv`\n\n"
                "**วิธีสร้าง:** ไปที่เมนู **🔧 Settings → 💾 Backup/Export → "
                "🔄 Force Reseed Master Data** เพื่อสร้างไฟล์บุคลากร"
            )
        else:
            psn_df = pd.read_csv(psn_path, encoding="utf-8-sig")

            # ---- KPI Tiles ----
            kp = psn_df[psn_df["category"] == "Key Personnel"]
            ast = psn_df[psn_df["category"] == "Assistant"]
            coord = psn_df[psn_df["category"] == "Coordinator"]
            total_qty = int(pd.to_numeric(psn_df["quantity"], errors="coerce").fillna(0).sum())

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown(_mini_tile("👔 Key Personnel",
                                       f"{int(pd.to_numeric(kp['quantity'], errors='coerce').fillna(0).sum())}",
                                       "ตำแหน่งหลัก", "#0B5ED7"),
                            unsafe_allow_html=True)
            with c2:
                st.markdown(_mini_tile("🧑‍💼 ผู้ช่วย",
                                       f"{int(pd.to_numeric(ast['quantity'], errors='coerce').fillna(0).sum())}",
                                       "Assistant", "#00838F"),
                            unsafe_allow_html=True)
            with c3:
                st.markdown(_mini_tile("🤝 ผู้ประสานงาน",
                                       f"{int(pd.to_numeric(coord['quantity'], errors='coerce').fillna(0).sum())}",
                                       "Coordinator", "#6A1B9A"),
                            unsafe_allow_html=True)
            with c4:
                total_color = "#2E7D32" if total_qty == 11 else "#F57C00"
                st.markdown(_mini_tile("👥 รวมทั้งหมด", f"{total_qty}",
                                       "คน (ตาม TOR ข้อ 12)", total_color),
                            unsafe_allow_html=True)

            st.markdown("---")

            # ---- Categories ----
            category_meta = [
                ("Key Personnel", "👔", "#0B5ED7",
                 "บุคลากรหลัก — ต้องมีคุณสมบัติตาม TOR"),
                ("Assistant", "🧑‍💼", "#00838F",
                 "ผู้ช่วยโครงการ — สนับสนุนการดำเนินงาน"),
                ("Coordinator", "🤝", "#6A1B9A",
                 "ผู้ประสานงาน — ติดต่อประสานทุกฝ่าย"),
            ]

            for cat, emoji, color, desc in category_meta:
                sub = psn_df[psn_df["category"] == cat].copy()
                if sub.empty:
                    continue

                st.markdown(
                    f'<div style="background:{color};color:#FFF;'
                    f'padding:8px 14px;border-radius:8px;font-size:13px;'
                    f'font-weight:700;margin:10px 0 8px 0;">'
                    f'{emoji} {cat} <span style="font-weight:400;opacity:0.9;">'
                    f'— {desc}</span></div>',
                    unsafe_allow_html=True,
                )

                # Card-style display
                for _, p in sub.iterrows():
                    qty_badge = (
                        f'<span style="background:#FFF3E0;color:#E65100;'
                        f'padding:2px 8px;border-radius:10px;font-size:11px;'
                        f'margin-left:6px;">× {int(p["quantity"])} คน</span>'
                    )
                    name_display = str(p.get("name", "")).strip()
                    if name_display in ("", "(รอระบุ)", "nan"):
                        name_display = '<span style="color:#9E9E9E;font-style:italic;">(รอระบุชื่อ)</span>'

                    st.markdown(
                        f'<div style="background:#FFFFFF;border-radius:8px;'
                        f'padding:12px 16px;border-left:4px solid {color};'
                        f'box-shadow:0 1px 4px rgba(0,51,102,0.05);'
                        f'margin-bottom:8px;">'
                        f'<div style="display:flex;justify-content:space-between;'
                        f'align-items:flex-start;flex-wrap:wrap;gap:8px;">'
                        f'<div style="flex:1;min-width:250px;">'
                        f'<div style="font-size:13.5px;font-weight:700;color:#003366;">'
                        f'<code>{p["personnel_id"]}</code> · {p["position"]}'
                        f'{qty_badge}</div>'
                        f'<div style="font-size:12px;color:#555;margin-top:6px;">'
                        f'<b>🎓 คุณสมบัติ:</b> {p.get("qualification", "-")}</div>'
                        f'<div style="font-size:12px;color:#555;margin-top:4px;">'
                        f'<b>📋 หน้าที่:</b> {p.get("responsibility", "-")}</div>'
                        f'<div style="font-size:12.5px;color:#003366;margin-top:6px;">'
                        f'<b>👤 ชื่อ-สกุล:</b> {name_display}</div>'
                        f'</div></div></div>',
                        unsafe_allow_html=True,
                    )

            # ---- Warning ถ้ายังไม่มีชื่อ ----
            if len(psn_df) > 0:
                no_name_count = int(
                    psn_df["name"].astype(str).isin(
                        ["", "(รอระบุ)", "nan"]
                    ).sum()
                )
                if no_name_count == len(psn_df):
                    st.warning(
                        "⚠️ **ยังไม่ได้ระบุชื่อบุคลากรจริง** — "
                        "กรุณาแก้ไขไฟล์ `data/master/personnel_master.csv` "
                        "หรือติดต่อผู้ดูแลระบบเพื่ออัปเดตข้อมูล"
                    )
                elif no_name_count > 0:
                    st.info(
                        f"ℹ️ ยังมี {no_name_count}/{len(psn_df)} ตำแหน่งที่ยังไม่ได้ระบุชื่อ"
                    )

            # ---- ตารางสรุปแบบเต็ม ----
            st.markdown("---")
            with st.expander("📋 ดูตารางแบบละเอียด", expanded=False):
                show = psn_df[[
                    "personnel_id", "category", "position", "quantity",
                    "qualification", "responsibility", "name",
                ]].copy()
                show.columns = [
                    "ID", "หมวด", "ตำแหน่ง", "จำนวน",
                    "คุณสมบัติ", "หน้าที่", "ชื่อ-สกุล",
                ]
                st.dataframe(show, use_container_width=True, hide_index=True)

            # ---- CSV Download ----
            st.markdown("---")
            st.download_button(
                "⬇️ ดาวน์โหลด personnel_master.csv",
                data=psn_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"personnel_master_{today_str()}.csv",
                mime="text/csv",
                use_container_width=True,
                key="dl_psn",
            )

    # ============================================================
    # TAB 4 — CSV (เดิม t3)
    # ============================================================
    with t4:
        st.markdown("### 📥 ข้อมูล CSV (อ่านเท่านั้น)")
        st.caption("ข้อมูลจริงอยู่ในไฟล์ `data/master/*.csv` — Tab นี้แสดงเพื่อตรวจสอบ")

        cA, cB = st.columns(2)
        with cA:
            st.markdown("#### 📄 `project_master.csv`")
            st.dataframe(proj_df, use_container_width=True, hide_index=True, height=200)
            st.download_button(
                "⬇️ ดาวน์โหลด project_master.csv",
                data=proj_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"project_master_{today_str()}.csv",
                mime="text/csv",
                key="dl_proj",
            )

        with cB:
            st.markdown("#### 📄 `milestone_master.csv`")
            st.dataframe(ms_df, use_container_width=True, hide_index=True, height=200)
            st.download_button(
                "⬇️ ดาวน์โหลด milestone_master.csv",
                data=ms_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"milestone_master_{today_str()}.csv",
                mime="text/csv",
                key="dl_ms",
            )

        st.markdown("---")
        st.markdown("#### 📄 `deliverable_master.csv`")
        if dl_df.empty:
            st.info("ยังไม่มี Deliverable")
        else:
            st.dataframe(dl_df, use_container_width=True, hide_index=True, height=200)
            st.download_button(
                "⬇️ ดาวน์โหลด deliverable_master.csv",
                data=dl_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"deliverable_master_{today_str()}.csv",
                mime="text/csv",
                key="dl_dlv",
            )