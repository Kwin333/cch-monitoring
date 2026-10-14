"""เบิกจ่ายตามงวด (ข้อ 1.5) — Comprehensive Version

ครอบคลุม:
- 📊 KPI Dashboard: มูลค่าสัญญา, จ่ายแล้ว, กำลังเบิก, คงเหลือ, ประกันผลงาน
- 🔍 Pre-conditions: Acceptance status, Evidence, Duplicate, Contract value
- ➕ Payment form + Payment flow validation + Document checklist + WHT
- 📜 History + Filter + Search + Detail viewer + Soft Delete + Restore
- 📈 Charts: Distribution, Cumulative, Status, Aging analysis
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
from core.validator import validate_payment_flow, ValidationError
from repositories.acceptance_repo import AcceptanceRepo, PaymentRepo
from repositories.milestone_repo import MilestoneRepo
from services.progress_service import compute_payment_amounts
from config_loader import load_settings


# ============================================================
# CONSTANTS
# ============================================================
PAYMENT_STATUSES = ["Payment Processing", "Paid", "Closed", "Cancelled"]
FINAL_PAYMENT_STATUSES = ("Paid", "Closed")
CANCELLED_STATUSES = ("Cancelled",)

ACCEPTANCE_READY_STATUSES = (
    "Accepted", "Payment Processing", "Paid", "Closed"
)

# Checklist เอกสารที่ต้องมีก่อนเบิก
DOCUMENT_CHECKLIST = [
    ("doc_1_invoice",       "📄 ใบแจ้งหนี้ / ใบส่งของ"),
    ("doc_2_acceptance",    "📋 ใบตรวจรับ / รายงานการประชุมคณะกรรมการ"),
    ("doc_3_guarantee",     "🔒 หนังสือค้ำประกันผลงาน (หรือหนังสือหัก 10%)"),
    ("doc_4_tor_comply",    "✅ เอกสารยืนยันความสอดคล้อง TOR"),
    ("doc_5_tax_invoice",   "🧾 ใบกำกับภาษี / ใบเสร็จรับเงิน"),
    ("doc_6_wht_cert",      "📑 หนังสือรับรองการหักภาษี ณ ที่จ่าย"),
]

STATUS_BADGES = {
    "Payment Processing": "🟡 กำลังเบิก",
    "Paid": "✅ จ่ายแล้ว",
    "Closed": "✅ ปิด",
    "Cancelled": "⚪ ยกเลิก",
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


def _to_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def _fmt_money(v):
    return f"{_to_float(v):,.2f}"


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
        <div style="font-size:20px;font-weight:700;color:#003366;
                    line-height:1.1;margin:4px 0;">{value}</div>
        <div style="font-size:11px;color:{color};">{sub}</div>
    </div>
    """


def _latest_acceptance(milestone_id, acc_df):
    """คืน row ล่าสุดของ milestone (หรือ None)"""
    if acc_df is None or acc_df.empty:
        return None
    sub = acc_df[acc_df["milestone_id"] == milestone_id].copy()
    if sub.empty:
        return None
    sub["_ts"] = pd.to_datetime(sub["timestamp"], errors="coerce")
    sub = sub.dropna(subset=["_ts"]).sort_values("_ts")
    return sub.iloc[-1] if not sub.empty else None


def _has_active_payment(milestone_id, pay_df):
    """ตรวจว่ามี payment ที่ยัง active (ไม่ Cancelled) หรือยัง"""
    if pay_df is None or pay_df.empty:
        return False
    sub = pay_df[
        (pay_df["milestone_id"] == milestone_id)
        & (~pay_df["status"].isin(CANCELLED_STATUSES))
    ]
    return not sub.empty


def _cumulative_paid(pay_df, exclude_milestone=None):
    """ยอดที่จ่ายจริงแล้ว (Paid + Closed)"""
    if pay_df is None or pay_df.empty:
        return 0.0
    df = pay_df[pay_df["status"].isin(FINAL_PAYMENT_STATUSES)]
    if exclude_milestone:
        df = df[df["milestone_id"] != exclude_milestone]
    return float(pd.to_numeric(df["payment_amount"], errors="coerce").fillna(0).sum())


def _days_between(d1, d2):
    a, b = _to_date(d1), _to_date(d2)
    if a is None or b is None:
        return None
    return (b - a).days


def _aging_bucket(days):
    if days is None:
        return "-"
    if days < 0:
        return "N/A"
    if days <= 15:
        return "0–15 วัน"
    if days <= 30:
        return "16–30 วัน"
    if days <= 60:
        return "31–60 วัน"
    return "> 60 วัน"


def _validate_payment(data, prev_status=None):
    """Validation เพิ่มเติม"""
    if data.get("status") == "Paid" and not data.get("payment_date"):
        raise ValidationError("⚠️ สถานะ Paid ต้องระบุวันที่จ่ายเงิน")
    if data.get("status") in ("Paid", "Closed") and not (data.get("guarantee_ref") or "").strip():
        raise ValidationError("⚠️ สถานะ Paid/Closed ต้องระบุอ้างอิงการหักประกันผลงาน")
    if prev_status in FINAL_PAYMENT_STATUSES and data.get("status") not in FINAL_PAYMENT_STATUSES:
        raise ValidationError(
            "⚠️ ไม่สามารถเปลี่ยนจาก Paid/Closed กลับเป็นสถานะอื่นได้"
        )


# ============================================================
# PRE-CONDITIONS
# ============================================================
def _run_prechecks(milestone_id, ms_row, acc_df, pay_df, dl_df,
                   total_value, cumulative_excluding_this):
    """ตรวจ pre-conditions ของ milestone → dict"""
    checks = {}

    # 1) Acceptance status
    latest_acc = _latest_acceptance(milestone_id, acc_df)
    if latest_acc is None:
        checks["acceptance"] = {
            "status": "fail",
            "msg": "ยังไม่มีบันทึกการตรวจรับสำหรับงวดนี้",
        }
    elif latest_acc.get("status") not in ACCEPTANCE_READY_STATUSES:
        checks["acceptance"] = {
            "status": "fail",
            "msg": f"สถานะการตรวจรับเป็น '{latest_acc.get('status')}' "
                   f"— ต้องเป็น Accepted ขึ้นไป",
        }
    else:
        checks["acceptance"] = {
            "status": "ok",
            "msg": f"ตรวจรับแล้ว ({latest_acc.get('acceptance_ref', '-')}) "
                   f"สถานะ: {latest_acc.get('status')}",
        }

    # 2) Acceptance evidence
    if latest_acc is not None and not (latest_acc.get("acceptance_evidence") or "").strip():
        checks["evidence"] = {
            "status": "fail",
            "msg": "ไม่มี Acceptance Evidence — ห้ามเบิกจ่าย (BR-05)",
        }
    else:
        checks["evidence"] = {
            "status": "ok",
            "msg": "มีหลักฐานการตรวจรับ",
        }

    # 3) Duplicate check
    if _has_active_payment(milestone_id, pay_df):
        checks["duplicate"] = {
            "status": "fail",
            "msg": "มีรายการเบิกจ่ายของงวดนี้แล้ว (ยังไม่ถูกยกเลิก)",
        }
    else:
        checks["duplicate"] = {
            "status": "ok",
            "msg": "ยังไม่มีการเบิกจ่ายงวดนี้",
        }

    # 4) Cumulative contract value
    pct = _to_float(ms_row.get("payment_percent", 0))
    gross_this = total_value * pct / 100.0
    projected_total = cumulative_excluding_this + gross_this
    if projected_total > total_value + 0.01:
        checks["budget"] = {
            "status": "fail",
            "msg": f"ยอดสะสมจะเกินสัญญา "
                   f"({projected_total:,.0f} > {total_value:,.0f} ฿)",
        }
    else:
        remaining_after = total_value - projected_total
        checks["budget"] = {
            "status": "ok",
            "msg": f"ยอดสะสมหลังจ่าย {projected_total:,.0f} ฿ "
                   f"(คงเหลือ {remaining_after:,.0f} ฿)",
        }

    return checks, latest_acc, gross_this


def _render_precheck_panel(checks):
    icon_map = {"ok": "✅", "warn": "⚠️", "fail": "🔴"}
    color_map = {"ok": "#2E7D32", "warn": "#F57C00", "fail": "#D32F2F"}
    bg_map = {"ok": "#E8F5E9", "warn": "#FFF8E1", "fail": "#FFEBEE"}

    labels = {
        "acceptance": "🔍 สถานะการตรวจรับ",
        "evidence":   "📋 หลักฐานการตรวจรับ",
        "duplicate":  "🔁 การเบิกซ้ำ",
        "budget":     "💰 วงเงินคงเหลือ",
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


def _check_all_ok(checks):
    return all(c["status"] == "ok" for c in checks.values())


# ============================================================
# MAIN RENDER
# ============================================================
def render():
    st.title("💵 เบิกจ่ายตามงวด (ข้อ 1.5)")
    st.caption(
        "บริหารการเบิกจ่ายตามงวดงาน — เชื่อมโยงการตรวจรับ (p09) "
        "และติดตามวงเงินคงเหลือของสัญญา"
    )

    # ============================================================
    # READ ONCE
    # ============================================================
    cfg = load_settings()

    ms_repo = MilestoneRepo()
    acc_repo = AcceptanceRepo()
    pay_repo = PaymentRepo()

    ms_df = ms_repo.read()
    acc_df = acc_repo.read()
    pay_df = pay_repo.read()

    try:
        from repositories.deliverable_repo import DeliverableRepo
        dl_df = DeliverableRepo().read()
        dl_df = dl_df[dl_df["milestone_id"].astype(str).str.startswith("MLS")].reset_index(drop=True)
    except Exception:
        dl_df = pd.DataFrame()

    # Project info
    try:
        from repositories.base_repo import MasterRepo
        proj_repo = MasterRepo("project_master.csv", [
            "project_id", "project_name", "contract_no", "consultant_name",
            "contract_date", "project_start_date", "project_duration_days",
            "project_end_date", "total_contract_value", "project_manager",
            "status", "created_at", "updated_at",
        ])
        proj_df = proj_repo.read()
    except Exception:
        proj_df = pd.DataFrame()

    if ms_df.empty or proj_df.empty:
        st.warning(
            "⚠️ ยังไม่มีข้อมูล Milestone หรือ Project — "
            "กรุณาตั้งค่าที่เมนู ⚙️ Project / Milestone"
        )
        return

    proj = proj_df.iloc[0]
    total_value = _to_float(proj["total_contract_value"])

    # ============================================================
    # KPI TILES
    # ============================================================
    st.markdown("### 📊 ภาพรวมการเบิกจ่าย")

    if not pay_df.empty:
        paid_mask = pay_df["status"].isin(FINAL_PAYMENT_STATUSES)
        pending_mask = pay_df["status"] == "Payment Processing"
        paid_amt = _to_float(
            pd.to_numeric(pay_df.loc[paid_mask, "payment_amount"], errors="coerce").fillna(0).sum()
        )
        pending_amt = _to_float(
            pd.to_numeric(pay_df.loc[pending_mask, "payment_amount"], errors="coerce").fillna(0).sum()
        )
        guarantee_amt = _to_float(
            pd.to_numeric(
                pay_df.loc[paid_mask, "guarantee_deduction"], errors="coerce"
            ).fillna(0).sum()
        )
        n_paid = int(paid_mask.sum())
        n_pending = int(pending_mask.sum())
    else:
        paid_amt = pending_amt = guarantee_amt = 0.0
        n_paid = n_pending = 0

    remaining = total_value - paid_amt - pending_amt
    pct_paid = (paid_amt / total_value * 100) if total_value else 0.0

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(_tile("📋 มูลค่าสัญญา", f"{_fmt_money(total_value)} ฿",
                          "ตามสัญญาจ้าง", "#0B5ED7"), unsafe_allow_html=True)
    with k2:
        st.markdown(_tile("✅ จ่ายแล้ว", f"{_fmt_money(paid_amt)} ฿",
                          f"{pct_paid:.1f}% · {n_paid} งวด",
                          "#2E7D32"), unsafe_allow_html=True)
    with k3:
        st.markdown(_tile("⏳ กำลังเบิก", f"{_fmt_money(pending_amt)} ฿",
                          f"{n_pending} งวดรอดำเนินการ",
                          "#F57C00"), unsafe_allow_html=True)
    with k4:
        st.markdown(_tile("💵 คงเหลือ", f"{_fmt_money(remaining)} ฿",
                          f"{(remaining/total_value*100 if total_value else 0):.1f}% ของสัญญา",
                          "#6A1B9A"), unsafe_allow_html=True)
    with k5:
        st.markdown(_tile("🔒 ประกันผลงาน", f"{_fmt_money(guarantee_amt)} ฿",
                          f"หัก {cfg['payment']['guarantee_deduction_pct']}%",
                          "#00838F"), unsafe_allow_html=True)

    # Progress bar ของการจ่าย
    st.markdown(_progress_bar_html(pct_paid, "#0B5ED7"), unsafe_allow_html=True)

    st.markdown("---")

    # ============================================================
    # TABS
    # ============================================================
    t1, t2, t3, t4 = st.tabs([
        "➕ สร้างรายการเบิกจ่าย",
        "📜 ประวัติ & ติดตาม",
        "📈 Charts",
        "📥 CSV",
    ])

    # ============================================================
    # TAB 1 — CREATE PAYMENT
    # ============================================================
    with t1:
        if "pay_last_saved" in st.session_state:
            info = st.session_state.pop("pay_last_saved")
            st.markdown(
                f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
                f'padding:10px 14px;border-radius:8px;font-size:13px;">'
                f'✅ <b>บันทึกการเบิกจ่ายสำเร็จ</b> — '
                f'Payment ID: <code>{info["id"]}</code> · '
                f'Milestone: <code>{info["ms"]}</code> · '
                f'Status: <b>{info["status"]}</b>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown("### 📝 เลือก Milestone ที่จะเบิกจ่าย")

        ms_options = ms_df["milestone_id"].astype(str).tolist()
        default_idx = 0
        ms_sel = st.selectbox(
            "Milestone",
            ms_options,
            index=default_idx,
            format_func=lambda x: (
                f"{x} — "
                f"{ms_df[ms_df['milestone_id']==x]['milestone_name'].iloc[0]} "
                f"(Due {_fmt_date(ms_df[ms_df['milestone_id']==x]['due_date'].iloc[0])})"
            ),
            key="pay_ms_sel",
        )
        m_row = ms_df[ms_df["milestone_id"] == ms_sel].iloc[0]

        # ---- Milestone info ----
        info1, info2, info3, info4 = st.columns(4)
        with info1:
            st.markdown(f"**📅 Due:** {_fmt_date(m_row['due_date'])}")
        with info2:
            pct = _to_float(m_row.get("payment_percent", 0))
            st.markdown(f"**💰 สัดส่วนงวด:** {pct:.1f}%")
        with info3:
            st.markdown(f"**📌 Milestone Status:** `{m_row.get('status', '-')}`")
        with info4:
            dr = _days_between(_today(), m_row.get("due_date"))
            if dr is not None:
                if dr < 0:
                    st.markdown(f"**⏰ เกินกำหนด:** {-dr} วัน")
                else:
                    st.markdown(f"**⏰ อีก:** {dr} วัน")

        # ---- Pre-conditions ----
        cumulative_excluding_this = _cumulative_paid(pay_df, exclude_milestone=None)
        # ถ้ามี payment ของ milestone นี้อยู่แล้ว ให้ exclude ออกจากการคำนวณ budget
        if _has_active_payment(ms_sel, pay_df):
            # ถ้ามีอยู่แล้ว จะ block อยู่ดี
            cumulative_excluding_this = _cumulative_paid(pay_df, exclude_milestone=ms_sel)

        checks, latest_acc, gross_this = _run_prechecks(
            ms_sel, m_row, acc_df, pay_df, dl_df,
            total_value, cumulative_excluding_this,
        )

        st.markdown("---")
        st.markdown("#### 🧪 Pre-conditions")
        _render_precheck_panel(checks)

        all_ok = _check_all_ok(checks)

        if latest_acc is None:
            st.error(
                "🚫 **ไม่สามารถเบิกจ่ายได้** — ยังไม่มีบันทึกการตรวจรับ "
                "(ไปที่เมนู **🔍 ตรวจรับ (1.5)** ก่อน)"
            )
            return
        elif not all_ok:
            st.warning(
                "⚠️ บาง pre-condition ไม่ผ่าน — ตรวจสอบรายละเอียดด้านบน "
                "ก่อนดำเนินการ"
            )

        # ---- Acceptance reference ----
        st.markdown("---")
        st.markdown("#### 📎 อ้างอิงการตรวจรับ")

        acc_m = acc_df[acc_df["milestone_id"] == ms_sel].copy() if not acc_df.empty else pd.DataFrame()
        acc_m = acc_m[acc_m["status"].isin(ACCEPTANCE_READY_STATUSES)] if not acc_m.empty else acc_m

        if acc_m.empty:
            st.error("❌ ไม่พบการตรวจรับที่ผ่านการอนุมัติ — ไม่สามารถเบิกจ่ายได้")
            return

        acc_m["_ts"] = pd.to_datetime(acc_m["timestamp"], errors="coerce")
        acc_m = acc_m.sort_values("_ts", ascending=False)

        acc_ref = st.selectbox(
            "เลขอ้างอิงการตรวจรับ",
            acc_m["acceptance_ref"].astype(str).tolist(),
            key="pay_acc_ref",
        )
        acc_row = acc_m[acc_m["acceptance_ref"] == acc_ref].iloc[0]

        # แสดงข้อมูล acceptance
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            st.markdown(f"**📅 วันที่ส่งมอบ:** {_fmt_date(acc_row.get('submission_date'))}")
        with a2:
            st.markdown(f"**🏛️ วันที่ กก.ตรวจรับ:** {_fmt_date(acc_row.get('committee_date'))}")
        with a3:
            st.markdown(f"**📎 หลักฐาน:** `{acc_row.get('acceptance_evidence', '-')}`")
        with a4:
            st.markdown(f"**🔄 Revision:** {acc_row.get('revision_round', 0)}")

        # ---- Calculation breakdown ----
        st.markdown("---")
        st.markdown("#### 💰 การคำนวณยอดเบิกจ่าย")

        calc = compute_payment_amounts(m_row.to_dict(), total_value)

        cA, cB, cC, cD = st.columns(4)
        with cA:
            st.markdown(_tile("สัดส่วนงวด",
                              f"{calc['payment_percent']:.1f}%",
                              "ของมูลค่าสัญญา", "#0B5ED7"),
                        unsafe_allow_html=True)
        with cB:
            st.markdown(_tile("ยอดจ่ายรวม",
                              f"{_fmt_money(calc['payment_amount'])} ฿",
                              "ก่อนหัก", "#00838F"),
                        unsafe_allow_html=True)
        with cC:
            st.markdown(_tile(
                f"หักประกัน ({cfg['payment']['guarantee_deduction_pct']:.0f}%)",
                f"{_fmt_money(calc['guarantee_deduction'])} ฿",
                "หักจากงวดนี้", "#F57C00"),
                unsafe_allow_html=True)
        with cD:
            st.markdown(_tile("ยอดสุทธิ",
                              f"{_fmt_money(calc['net_payable'])} ฿",
                              "ที่ต้องจ่ายจริง", "#2E7D32"),
                        unsafe_allow_html=True)

        # ---- FORM ----
        st.markdown("---")
        st.markdown("#### 📝 บันทึกการเบิกจ่าย")

        with st.form("pay_form", clear_on_submit=False):
            # A. Dates
            st.markdown("**A. ลำดับวันที่ในกระบวนการ**")
            st.caption(
                "ต้องเรียง: ส่งมอบ → ตรวจรับ → ยื่นเรื่องเบิก → อนุมัติ → จ่าย"
            )

            cA1, cA2, cA3 = st.columns(3)
            req_date = cA1.date_input(
                "วันที่ยื่นเรื่องเบิก",
                value=st.session_state.get("pay_req_date",
                                           _today()),
                key="pay_req_date",
            )
            app_date = cA2.date_input(
                "วันที่อนุมัติ",
                value=st.session_state.get("pay_app_date",
                                           _today()),
                key="pay_app_date",
            )
            pay_date = cA3.date_input(
                "วันที่จ่ายเงิน",
                value=st.session_state.get("pay_pay_date",
                                           _today()),
                key="pay_pay_date",
            )

            # B. Guarantee
            st.markdown("**B. ประกันผลงาน**")
            cB1, cB2 = st.columns([1, 2])
            guarantee_ref = cB1.text_input(
                "เลขอ้างอิงหนังสือค้ำประกัน / หัก 10%",
                value=st.session_state.get("pay_guarantee_ref", ""),
                key="pay_guarantee_ref",
                placeholder="เช่น GUAR-M1-001",
            )
            bank_account = cB2.text_input(
                "บัญชีที่รับเงิน / เลขที่ใบสำคัญ",
                value=st.session_state.get("pay_bank_acc", ""),
                key="pay_bank_acc",
                placeholder="เช่น KBank 123-4-56789-0 / ใบสำคัญ 1234/2569",
            )

            # C. Document checklist
            st.markdown("**C. เอกสารประกอบ**")
            st.caption("ติ๊กเพื่อยืนยันว่าครบถ้วน (บันทึกใน Notes)")
            doc_checks = {}
            cc1, cc2 = st.columns(2)
            for i, (key, label) in enumerate(DOCUMENT_CHECKLIST):
                col = cc1 if i % 2 == 0 else cc2
                doc_checks[key] = col.checkbox(
                    label,
                    value=st.session_state.get(f"pay_{key}", False),
                    key=f"pay_{key}",
                )
            n_docs = sum(1 for v in doc_checks.values() if v)

            # D. WHT
            st.markdown("**D. ภาษีหัก ณ ที่จ่าย (ถ้ามี)**")
            cD1, cD2 = st.columns([1, 2])
            wht_rate = cD1.number_input(
                "อัตรา WHT (%)",
                min_value=0.0, max_value=15.0,
                value=float(st.session_state.get("pay_wht_rate", 0.0)),
                step=0.5,
                key="pay_wht_rate",
            )
            wht_note = cD2.text_input(
                "หมายเหตุภาษี",
                value=st.session_state.get("pay_wht_note", ""),
                key="pay_wht_note",
                placeholder="เช่น หัก ณ ที่จ่าย 1% ตามมาตรา 3 เตรส",
            )
            wht_amount = calc["payment_amount"] * wht_rate / 100.0
            net_after_wht = calc["net_payable"] - wht_amount

            if wht_rate > 0:
                st.info(
                    f"💵 WHT {wht_rate:.1f}% = **{_fmt_money(wht_amount)} ฿** · "
                    f"ยอดโอนสุทธิหลัง WHT = **{_fmt_money(net_after_wht)} ฿**"
                )

            # E. Status
            st.markdown("**E. สถานะ**")
            cE1, cE2 = st.columns([1, 3])
            status = cE1.selectbox(
                "สถานะการเบิกจ่าย",
                PAYMENT_STATUSES,
                index=0,
                key="pay_status",
            )
            notes = cE2.text_area(
                "หมายเหตุ",
                value=st.session_state.get("pay_notes", ""),
                height=68,
                key="pay_notes",
                placeholder="รายละเอียดเพิ่มเติม เช่น เลขที่ใบสำคัญ, ผู้รับเงิน",
            )

            # Buttons
            cBtn1, cBtn2 = st.columns([1, 1])
            submitted = cBtn1.form_submit_button(
                "💾 บันทึกการเบิกจ่าย",
                type="primary",
                use_container_width=True,
            )
            reset_clicked = cBtn2.form_submit_button(
                "↩️ ล้างฟอร์ม",
                use_container_width=True,
            )

        if reset_clicked:
            _reset_keys("pay_", preserve=("pay_ms_sel",))
            st.rerun()

        # ---- SAVE ----
        if submitted:
            try:
                # Business validations
                if not all_ok and status in FINAL_PAYMENT_STATUSES:
                    raise ValidationError(
                        "⚠️ Pre-conditions ไม่ผ่าน — ไม่สามารถบันทึกเป็น "
                        "Paid/Closed ได้"
                    )
                if status in FINAL_PAYMENT_STATUSES and not guarantee_ref.strip():
                    raise ValidationError(
                        "⚠️ สถานะ Paid/Closed ต้องระบุอ้างอิงการหักประกันผลงาน"
                    )

                # BR-11: date flow
                validate_payment_flow(
                    submission=acc_row.get("submission_date"),
                    acceptance=acc_row.get("committee_date"),
                    request=req_date,
                    approval=app_date,
                    payment=pay_date,
                )

                # Extra validation
                _validate_payment({
                    "status":       status,
                    "payment_date": str(pay_date) if status in FINAL_PAYMENT_STATUSES else "",
                    "guarantee_ref": guarantee_ref,
                })

                # Compose notes with doc checklist + WHT
                docs_summary = ", ".join(
                    [label for key, label in DOCUMENT_CHECKLIST if doc_checks.get(key)]
                )
                full_notes = notes or ""
                if docs_summary:
                    full_notes += f"\n[เอกสาร] {docs_summary}"
                if wht_rate > 0:
                    full_notes += (
                        f"\n[WHT] {wht_rate:.1f}% = {_fmt_money(wht_amount)} ฿ · "
                        f"โอนสุทธิ {_fmt_money(net_after_wht)} ฿"
                    )
                if bank_account.strip():
                    full_notes += f"\n[บัญชี] {bank_account.strip()}"

                pid = new_id("payment")
                row = {
                    "timestamp":             now_str(),
                    "payment_id":            pid,
                    "milestone_id":          ms_sel,
                    "acceptance_ref":        acc_ref,
                    "payment_percent":       calc["payment_percent"],
                    "payment_amount":        calc["payment_amount"],
                    "guarantee_deduction":   calc["guarantee_deduction"],
                    "guarantee_ref":         guarantee_ref.strip(),
                    "payment_request_date":  str(req_date),
                    "approval_date":         str(app_date),
                    "payment_date":          str(pay_date) if status in FINAL_PAYMENT_STATUSES else "",
                    "status":                status,
                    "notes":                 full_notes.strip(),
                    "created_by":            st.session_state.user,
                }
                pay_repo.append(row)

                # ---- Sync milestone via MilestoneRepo (มี backup) ----
                new_ms = m_row.to_dict()
                if status in FINAL_PAYMENT_STATUSES:
                    new_ms["payment_date"] = str(pay_date)
                    new_ms["status"] = "Paid" if status == "Paid" else "Closed"
                elif status == "Payment Processing":
                    new_ms["status"] = "Payment Processing"
                new_ms["updated_at"] = now_str()
                ms_repo.upsert(new_ms, key="milestone_id")

                # ---- Audit ----
                append_audit(
                    st.session_state.user, "CREATE", "PAYMENT", pid,
                    old_value=f"MS {ms_sel}: {m_row.get('status')}",
                    new_value=f"Payment {status} · {_fmt_money(calc['payment_amount'])} ฿",
                    reason=f"Ref: {acc_ref} · Docs: {n_docs}/6 · WHT: {wht_rate}%",
                )

                # ---- Flash ----
                st.session_state["pay_last_saved"] = {
                    "id": pid, "ms": ms_sel, "status": status,
                }
                _reset_keys("pay_", preserve=("pay_ms_sel", "pay_last_saved"))
                st.rerun()

            except ValidationError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"❌ {type(e).__name__}: {e}")

    # ============================================================
    # TAB 2 — HISTORY
    # ============================================================
    with t2:
        st.markdown("### 📜 ประวัติ & ติดตามการเบิกจ่าย")

        if pay_df.empty:
            st.info("ยังไม่มีการเบิกจ่าย — เริ่มที่แท็บ ➕")
        else:
            # ---- Filters ----
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                f_ms = st.multiselect(
                    "Milestone",
                    sorted(pay_df["milestone_id"].astype(str).unique().tolist()),
                    default=sorted(pay_df["milestone_id"].astype(str).unique().tolist()),
                    key="h_pay_ms",
                )
            with c2:
                f_stat = st.multiselect(
                    "Status",
                    PAYMENT_STATUSES,
                    default=PAYMENT_STATUSES,
                    key="h_pay_stat",
                )
            with c3:
                search = st.text_input(
                    "🔍 Search (Payment ID / Ref / Notes)",
                    value="", key="h_pay_search",
                )

            view = pay_df.copy()
            if f_ms:
                view = view[view["milestone_id"].isin(f_ms)]
            if f_stat:
                view = view[view["status"].isin(f_stat)]
            if search.strip():
                s = search.strip().lower()
                view = view[
                    view["payment_id"].astype(str).str.lower().str.contains(s, na=False)
                    | view["acceptance_ref"].astype(str).str.lower().str.contains(s, na=False)
                    | view["guarantee_ref"].astype(str).str.lower().str.contains(s, na=False)
                    | view["notes"].astype(str).str.lower().str.contains(s, na=False)
                ]

            view = view.copy()
            view["_ts"] = pd.to_datetime(view["timestamp"], errors="coerce")
            view = view.sort_values("_ts", ascending=False)

            st.caption(f"แสดง {len(view)} / {len(pay_df)} รายการ (เรียงจากใหม่)")

            # ---- Card list ----
            for _, r in view.iterrows():
                status_txt = STATUS_BADGES.get(r.get("status", "-"), r.get("status", "-"))
                amt = _to_float(r.get("payment_amount"))
                ded = _to_float(r.get("guarantee_deduction"))
                net = amt - ded

                if r["status"] in FINAL_PAYMENT_STATUSES:
                    border = "#2E7D32"
                elif r["status"] == "Payment Processing":
                    border = "#F57C00"
                elif r["status"] == "Cancelled":
                    border = "#9E9E9E"
                else:
                    border = "#0B5ED7"

                st.markdown(
                    f'<div style="background:#FFFFFF;border-radius:8px;'
                    f'padding:10px 14px;border-left:4px solid {border};'
                    f'box-shadow:0 1px 4px rgba(0,51,102,0.05);margin-bottom:8px;">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;flex-wrap:wrap;gap:8px;">'
                    f'<div style="font-size:13px;font-weight:700;color:#003366;">'
                    f'{r["payment_id"]} '
                    f'<span style="background:{border};color:#FFF;'
                    f'padding:2px 8px;border-radius:10px;font-size:10.5px;'
                    f'margin-left:6px;">{r.get("milestone_id","-")}</span>'
                    f'<span style="font-weight:400;color:#666;margin-left:6px;">'
                    f'({status_txt})</span>'
                    f'</div>'
                    f'<div style="font-size:13px;font-weight:700;color:#2E7D32;">'
                    f'{_fmt_money(amt)} ฿</div></div>'
                    f'<div style="font-size:11.5px;color:#666;margin-top:6px;">'
                    f'📎 Ref <code>{r.get("acceptance_ref","-")}</code> · '
                    f'🔒 ประกัน <code>{r.get("guarantee_ref","-")}</code> · '
                    f'💵 สุทธิ <b>{_fmt_money(net)}</b> ฿</div>'
                    f'<div style="font-size:11.5px;color:#666;margin-top:4px;">'
                    f'📅 ยื่น {_fmt_date(r.get("payment_request_date"))} · '
                    f'อนุมัติ {_fmt_date(r.get("approval_date"))} · '
                    f'จ่าย {_fmt_date(r.get("payment_date"))}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            # ---- Detail Table ----
            with st.expander("📋 ตารางแบบละเอียด"):
                show_cols = [c for c in [
                    "timestamp", "payment_id", "milestone_id", "acceptance_ref",
                    "payment_percent", "payment_amount", "guarantee_deduction",
                    "guarantee_ref",
                    "payment_request_date", "approval_date", "payment_date",
                    "status", "notes", "created_by",
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
                "เลือก Payment ID",
                view["payment_id"].astype(str).tolist(),
                key="h_pay_det",
            )
            det = pay_df[pay_df["payment_id"] == det_id].iloc[-1]

            d1, d2, d3, d4 = st.columns(4)
            with d1:
                st.markdown(f"**📌 Milestone:** `{det['milestone_id']}`")
            with d2:
                st.markdown(f"**💰 ยอดจ่าย:** {_fmt_money(det.get('payment_amount'))} ฿")
            with d3:
                st.markdown(
                    f"**🔒 หักประกัน:** {_fmt_money(det.get('guarantee_deduction'))} ฿"
                )
            with d4:
                st.markdown(f"**📌 Status:** {STATUS_BADGES.get(det.get('status'), det.get('status'))}")

            st.markdown(
                f"**📎 Acceptance Ref:** `{det.get('acceptance_ref', '-')}` · "
                f"**🔒 Guarantee Ref:** `{det.get('guarantee_ref', '-')}`"
            )
            st.markdown(
                f"**📅 ยื่น:** {_fmt_date(det.get('payment_request_date'))} · "
                f"**อนุมัติ:** {_fmt_date(det.get('approval_date'))} · "
                f"**จ่าย:** {_fmt_date(det.get('payment_date'))}"
            )

            with st.expander("📝 Notes", expanded=True):
                st.text(det.get("notes", "-") or "-")

            # ---- Soft Delete + Restore ----
            if st.session_state.role in ("admin", "monitoring"):
                st.markdown("---")
                with st.expander("🗑️ ลบ / คืนค่า (Soft Delete)", expanded=False):
                    st.caption("⚠️ Soft Delete = ซ่อนจาก UI, ข้อมูลยังอยู่ใน CSV")

                    colA, colB = st.columns(2)

                    with colA:
                        st.markdown("**🗑️ Soft Delete**")
                        del_id = st.selectbox(
                            "เลือก Payment ID",
                            pay_df["payment_id"].astype(str).tolist(),
                            key="h_pay_del_sel",
                        )
                        del_reason = st.text_input(
                            "เหตุผลที่ลบ", key="h_pay_del_reason",
                        )
                        if st.button("🗑️ Soft Delete", type="primary", key="h_pay_del_btn"):
                            if not del_reason.strip():
                                st.error("⚠️ กรุณาระบุเหตุผล")
                            else:
                                try:
                                    pay_repo.soft_delete(
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
                            vd_p = (
                                vd[vd["record_type"] == "payment"]
                                if not vd.empty else vd
                            )
                            if vd_p.empty:
                                st.info("ไม่มีรายการที่ถูก Void")
                            else:
                                rid = st.selectbox(
                                    "เลือก Payment ID",
                                    vd_p["record_id"].tolist(),
                                    key="h_pay_restore_sel",
                                )
                                if st.button("↩️ คืนค่า", key="h_pay_restore_btn"):
                                    if pay_repo.restore(rid, st.session_state.user):
                                        st.success(f"✅ คืนค่า `{rid}` แล้ว")
                                        st.rerun()
                        except Exception as e:
                            st.error(f"❌ {e}")

    # ============================================================
    # TAB 3 — CHARTS
    # ============================================================
    with t3:
        st.markdown("### 📈 Charts สรุปการเบิกจ่าย")

        if pay_df.empty:
            st.info("ยังไม่มีข้อมูลสำหรับสร้างกราฟ")
        else:
            c1, c2 = st.columns(2)

            # ---- Status pie ----
            with c1:
                st.markdown("#### สถานะรายการเบิกจ่าย")
                st_counts = pay_df["status"].value_counts()
                status_colors_map = {
                    "Payment Processing": "#F57C00",
                    "Paid": "#2E7D32",
                    "Closed": "#1B5E20",
                    "Cancelled": "#9E9E9E",
                }
                fig1 = go.Figure(data=[go.Pie(
                    labels=st_counts.index.tolist(),
                    values=st_counts.values.tolist(),
                    hole=0.5,
                    marker=dict(colors=[
                        status_colors_map.get(x, "#0B5ED7") for x in st_counts.index
                    ]),
                )])
                fig1.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(fig1, use_container_width=True)

            # ---- Per-milestone amounts ----
            with c2:
                st.markdown("#### ยอดเบิกจ่ายตาม Milestone")
                per_ms = (
                    pay_df[pay_df["status"].isin(FINAL_PAYMENT_STATUSES)]
                    .groupby("milestone_id")["payment_amount"]
                    .sum()
                    .reset_index()
                    .sort_values("milestone_id")
                )
                if per_ms.empty:
                    st.info("ยังไม่มีการจ่ายจริง")
                else:
                    fig2 = go.Figure(data=[go.Bar(
                        x=per_ms["milestone_id"].tolist(),
                        y=per_ms["payment_amount"].tolist(),
                        marker_color="#2E7D32",
                        text=[_fmt_money(v) for v in per_ms["payment_amount"]],
                        textposition="outside",
                    )])
                    fig2.update_layout(
                        height=320, plot_bgcolor="#FAFBFC",
                        yaxis_title="ยอดจ่าย (฿)",
                        margin=dict(l=10, r=10, t=30, b=40),
                    )
                    st.plotly_chart(fig2, use_container_width=True)

            # ---- Cumulative payment vs contract ----
            st.markdown("#### 📊 ยอดสะสมเทียบมูลค่าสัญญา")
            paid_df = pay_df[pay_df["status"].isin(FINAL_PAYMENT_STATUSES)].copy()
            if not paid_df.empty:
                paid_df["_pay_date"] = pd.to_datetime(
                    paid_df["payment_date"], errors="coerce"
                )
                paid_df = paid_df.dropna(subset=["_pay_date"]).sort_values("_pay_date")
                paid_df["cumulative"] = pd.to_numeric(
                    paid_df["payment_amount"], errors="coerce"
                ).fillna(0).cumsum()

                fig3 = go.Figure()
                fig3.add_trace(go.Scatter(
                    x=paid_df["_pay_date"],
                    y=paid_df["cumulative"],
                    mode="lines+markers",
                    name="ยอดจ่ายสะสม",
                    line=dict(color="#2E7D32", width=3),
                    marker=dict(size=10),
                    hovertemplate="%{y:,.0f} ฿<extra></extra>",
                ))
                fig3.add_trace(go.Scatter(
                    x=[paid_df["_pay_date"].min(), paid_df["_pay_date"].max()],
                    y=[total_value, total_value],
                    mode="lines",
                    name=f"มูลค่าสัญญา ({_fmt_money(total_value)} ฿)",
                    line=dict(color="#D32F2F", width=2, dash="dash"),
                ))
                fig3.update_layout(
                    height=360, plot_bgcolor="#FAFBFC",
                    yaxis_title="ยอดสะสม (฿)",
                    xaxis_title="วันที่จ่าย",
                    legend=dict(orientation="h", y=1.1),
                    margin=dict(l=10, r=10, t=30, b=40),
                )
                st.plotly_chart(fig3, use_container_width=True)
            else:
                st.info("ยังไม่มีการจ่ายจริง — ไม่สามารถสร้างกราฟสะสมได้")

            # ---- Aging analysis ----
            st.markdown("#### ⏱️ Aging: ระยะเวลาจากส่งมอบ → จ่ายจริง")
            aging_rows = []
            for _, p in pay_df.iterrows():
                if p["status"] not in FINAL_PAYMENT_STATUSES:
                    continue
                ms_id = p["milestone_id"]
                # หา acceptance ที่ตรง
                accs = acc_df[
                    (acc_df["milestone_id"] == ms_id)
                    & (acc_df["acceptance_ref"].astype(str) == str(p.get("acceptance_ref", "")))
                ] if not acc_df.empty else pd.DataFrame()
                if accs.empty:
                    continue
                a = accs.iloc[-1]
                days = _days_between(a.get("submission_date"), p.get("payment_date"))
                if days is None:
                    continue
                aging_rows.append({
                    "Milestone":      ms_id,
                    "ส่งมอบ":          str(a.get("submission_date")),
                    "จ่าย":            str(p.get("payment_date")),
                    "ระยะเวลา (วัน)": days,
                    "กลุ่ม":          _aging_bucket(days),
                })

            if not aging_rows:
                st.info("ยังไม่มีข้อมูลเพียงพอสำหรับ Aging analysis")
            else:
                ag_df = pd.DataFrame(aging_rows)
                bucket_counts = ag_df["กลุ่ม"].value_counts().reindex(
                    ["0–15 วัน", "16–30 วัน", "31–60 วัน", "> 60 วัน"]
                ).fillna(0)
                fig4 = go.Figure(data=[go.Bar(
                    x=bucket_counts.index.tolist(),
                    y=bucket_counts.values.tolist(),
                    marker_color=["#2E7D32", "#8BC34A", "#F57C00", "#D32F2F"],
                    text=bucket_counts.values.astype(int).tolist(),
                    textposition="outside",
                )])
                fig4.update_layout(
                    height=320, plot_bgcolor="#FAFBFC",
                    yaxis_title="จำนวนรายการ",
                    margin=dict(l=10, r=10, t=20, b=40),
                )
                st.plotly_chart(fig4, use_container_width=True)

                with st.expander("ดูรายละเอียด"):
                    st.dataframe(ag_df, use_container_width=True, hide_index=True)

    # ============================================================
    # TAB 4 — CSV
    # ============================================================
    with t4:
        st.markdown("### 📥 ข้อมูล CSV (อ่านเท่านั้น)")
        st.caption("ไฟล์จริง: `data/history/payment_history.csv`")

        if pay_df.empty:
            st.info("ยังไม่มีข้อมูล")
        else:
            st.dataframe(pay_df, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ ดาวน์โหลด payment_history.csv",
                data=pay_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"payment_history_{today_str()}.csv",
                mime="text/csv",
                key="dl_pay",
            )


# ============================================================
# HTML PROGRESS BAR HELPER
# ============================================================
def _progress_bar_html(pct, color="#0B5ED7", height=10):
    pct = max(0.0, min(100.0, _to_float(pct)))
    return (
        f'<div style="background:#E0E6ED;border-radius:20px;'
        f'height:{height}px;overflow:hidden;margin-top:10px;">'
        f'<div style="width:{pct}%;background:{color};'
        f'height:100%;border-radius:20px;"></div>'
        f'</div>'
    )