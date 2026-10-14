"""Dashboard — Executive view ครบถ้วน รวมงาน 1.3 (Meeting/Resolution) + 1.5 (Acceptance/Payment)

เวอร์ชันนี้:
- ★ S-Curve: แผนสะสม vs จริงสะสม (ตาม Timeline TOR)
- ★ Milestone markers บน S-Curve (แสดงสถานะตามสี)
- ★ KPI 4 ตัว: แผน ณ วันนี้ / จริง ณ วันนี้ / ส่วนต่าง / แผนรวม
- ★ Section 5: ตาราง Deliverable เรียงตามลำดับงาน (M1 → M5)
  + คอลัมน์ หน่วยงาน / ช่วงเวลา / TOR
- 🐛 Fixed v4: WEEKLY_PLAN_PCT normalize ให้ผลรวม = 100.00% พอดี
  (เดิม hardcode รวมได้ 100.50% ทำให้ "แผนรวม" แสดง 100.5%)
- 🐛 Fixed v3: Planned (ตามเวลา) ใช้ S-Curve แทน Linear → ตัวเลขสอดคล้องกัน
- 🐛 Fixed v2: S-Curve ใช้ `update_date` แทน `timestamp`
- 🐛 Fixed v1: ใช้ add_shape + add_annotation แทน add_vline
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, datetime, timedelta
from pathlib import Path

from repositories.deliverable_repo import DeliverableRepo
from repositories.progress_repo import ProgressRepo
from repositories.acceptance_repo import AcceptanceRepo, PaymentRepo
from repositories.action_repo import ActionRepo
from repositories.issue_repo import IssueRepo
from repositories.meeting_repo import MeetingRepo, ResolutionRepo
from services.progress_service import compute_overall_progress, check_milestone_warning
from config_loader import load_settings

DATA_DIR = Path(__file__).parent.parent / "data"


# ============================================================
# ★ RESPONSIBLE UNITS (จาก Timeline TOR)
# ============================================================
RESPONSIBLE_UNITS = {
    # ═══ M1 — Inception Report ═══
    "DLV-M1-01": "คณะกรรมการ",
    "DLV-M1-02": "คณะกรรมการ",
    "DLV-M1-03": "คณะกรรมการ",
    "DLV-M1-04": "ฝทบ.",
    "DLV-M1-05": "กนก.",
    "DLV-M1-06": "ฝดท.1",
    "DLV-M1-07": "ฝกง.",
    "DLV-M1-08": "ฝดท.2",
    "DLV-M1-09": "กบธ.",
    "DLV-M1-10": "ฝพธ., ฝกม.",
    "DLV-M1-11": "ฝดท.1",
    "DLV-M1-12": "ฝดท.1",
    "DLV-M1-13": "ฝพธ.",
    "DLV-M1-14": "ฝยป.",
    "DLV-M1-15": "คณะกรรมการ",
    "DLV-M1-16": "คณะกรรมการ",
    "DLV-M1-17": "คณะกรรมการ",
    "DLV-M1-18": "คณะกรรมการ",
    # ═══ M2 — Progress Report I ═══
    "DLV-M2-01": "ฝดท.1",
    "DLV-M2-02": "ฝยป.",
    "DLV-M2-03": "ฝดท.1, ฝยป.",
    "DLV-M2-04": "ฝดท.1",
    "DLV-M2-05": "กกด.",
    "DLV-M2-06": "ฝดท.1",
    "DLV-M2-07": "ฝยป.",
    "DLV-M2-08": "คณะกรรมการ",
    "DLV-M2-09": "ฝทบ.",
    "DLV-M2-10": "ฝกง., ฝพธ.",
    "DLV-M2-11": "ฝกง.",
    "DLV-M2-12": "ฝดท.1, ฝกม.",
    "DLV-M2-13": "ฝดท.1",
    "DLV-M2-14": "คณะกรรมการ",
    "DLV-M2-15": "คณะกรรมการ",
    "DLV-M2-16": "คณะกรรมการ",
    "DLV-M2-17": "คณะกรรมการ",
    # ═══ M3 — Interim Report ═══
    "DLV-M3-01": "ฝดท.1",
    "DLV-M3-02": "สตส.",
    "DLV-M3-03": "ฝดท.1",
    "DLV-M3-04": "ฝดท.1",
    "DLV-M3-05": "ฝดท.1, ฝทบ.",
    "DLV-M3-06": "ฝพธ.",
    "DLV-M3-07": "ฝดท.1, ฝดท.2",
    "DLV-M3-08": "ฝดท.1",
    "DLV-M3-09": "ฝยป.",
    "DLV-M3-10": "ฝกง.",
    "DLV-M3-11": "ฝดท.1",
    "DLV-M3-12": "ฝกม.",
    "DLV-M3-13": "ฝกง., ฝดท.1",
    "DLV-M3-14": "คณะกรรมการ",
    "DLV-M3-15": "ฝกม., ฝดท.1",
    "DLV-M3-16": "คณะกรรมการ",
    "DLV-M3-17": "คณะกรรมการ",
    "DLV-M3-18": "คณะกรรมการ",
    "DLV-M3-19": "คณะกรรมการ",
    # ═══ M4 — Progress Report II ═══
    "DLV-M4-01": "คณะกรรมการ",
    "DLV-M4-02": "ฝดท.1",
    "DLV-M4-03": "ฝดท.1",
    "DLV-M4-04": "ฝทบ.",
    "DLV-M4-05": "ฝพธ.",
    "DLV-M4-06": "ฝดท.1, ฝดท.2",
    "DLV-M4-07": "ฝกม., ฝดท.1",
    "DLV-M4-08": "ฝกม., ฝดท.1",
    "DLV-M4-09": "คณะกรรมการ",
    "DLV-M4-10": "คณะกรรมการ",
    "DLV-M4-11": "ฝดท.1",
    "DLV-M4-12": "ฝดท.1",
    "DLV-M4-13": "คณะกรรมการ",
    "DLV-M4-14": "คณะกรรมการ",
    "DLV-M4-15": "คณะกรรมการ",
    "DLV-M4-16": "คณะกรรมการ",
    # ═══ M5 — Final Report ═══
    "DLV-M5-01": "คณะกรรมการ",
    "DLV-M5-02": "ฝดท.1",
    "DLV-M5-03": "ฝทบ.",
    "DLV-M5-04": "ฝกง.",
    "DLV-M5-05": "ฝดท.1, ฝดท.2",
    "DLV-M5-06": "ฝดท.1, ฝกม.",
    "DLV-M5-07": "คณะกรรมการ",
    "DLV-M5-08": "คณะกรรมการ",
    "DLV-M5-09": "คณะกรรมการ",
    "DLV-M5-10": "คณะกรรมการ",
    "DLV-M5-11": "คณะกรรมการ",
    "DLV-M5-12": "คณะกรรมการ",
}

# คำอธิบายตัวย่อหน่วยงาน
UNIT_REFERENCE = {
    "คณะกรรมการ": "คณะกรรมการตรวจรับ / ที่ปรึกษาโครงการ",
    "ฝทบ.":       "ฝ่ายทรัพยากรบุคคล",
    "กนก.":       "กองนิติการ",
    "ฝดท.1":      "ฝ่ายดิจิทัล 1 (ธุรกิจดิจิทัล)",
    "ฝดท.2":      "ฝ่ายดิจิทัล 2 (IT / Network / Security)",
    "ฝกง.":       "ฝ่ายการเงิน",
    "กบธ.":       "ฝ่ายบริหารธุรกิจใหม่",
    "ฝพธ.":       "ฝ่ายพัฒนาธุรกิจ / บริหารความเสี่ยง",
    "ฝกม.":       "ฝ่ายกฎหมาย",
    "ฝยป.":       "ฝ่ายยุทธศาสตร์และแผนงาน",
    "สตส.":       "สำนักตรวจสอบภายใน",
    "กกด.":       "กองกำกับดูแล / Compliance",
}


# ============================================================
# ★ WEIGHT NORMALIZER (ใช้สำหรับ S-Curve Plan)
# ============================================================
def _normalize_to_100(values: list, target: float = 100.0) -> list:
    """
    ปรับค่าใน list ให้ผลรวม = target พอดี (เช่น 100.00)

    หลักการ:
    - Scale ทุกค่าด้วย factor เดียวกัน (รักษาสัดส่วนเดิม)
    - แก้ rounding ที่ตัวสุดท้ายเพื่อให้ผลรวมเป๊ะ
    - Idempotent: ถ้ารันซ้ำด้วยค่าเดิม ผลลัพธ์จะเท่าเดิม

    Args:
        values: list ของตัวเลข (เช่น weekly plan %)
        target: ค่าเป้าหมายของผลรวม (default 100.0)

    Returns:
        list ใหม่ที่ผลรวม = target
    """
    if not values:
        return []

    total = sum(values)
    if total <= 0:
        # fallback: กระจายเท่า ๆ กัน
        n = len(values)
        if n == 0:
            return []
        each = round(target / n, 4)
        result = [each] * n
        # Fix rounding
        diff = round(target - sum(result), 4)
        if abs(diff) > 1e-9:
            result[-1] = round(result[-1] + diff, 4)
        return result

    factor = target / total
    scaled = [round(v * factor, 4) for v in values]

    # Fix rounding ให้ผลรวมเป๊ะ = target
    diff = round(target - sum(scaled), 4)
    if abs(diff) > 1e-9:
        # ปรับที่ตัวสุดท้าย (หรือตัวที่มีค่ามากสุด ถ้าตัวสุดท้ายเป็น 0)
        last_idx = len(scaled) - 1
        scaled[last_idx] = round(scaled[last_idx] + diff, 4)

    return scaled


# ============================================================
# ★ S-CURVE PLAN DATA — Raw + Normalized
# ============================================================
# ข้อมูลดิบรายสัปดาห์ (52 สัปดาห์ ตาม Timeline TOR)
# ⚠️ ค่าดิบเหล่านี้รวมได้ ~100.50% → ต้อง normalize ก่อนใช้
_RAW_WEEKLY_PLAN_PCT = [
    0.98, 2.17, 2.92, 3.53,   # ส.ค. 69 (W1-W4)
    0.90, 0.50, 0.67, 0.89,   # ก.ย. 69
    0.89, 1.69, 1.69, 2.12,   # ต.ค. 69
    2.12, 2.32, 2.32, 2.15,   # พ.ย. 69
    2.59, 3.34, 5.91, 3.91,   # ธ.ค. 69
    3.41, 3.41, 3.16, 3.16,   # ม.ค. 70
    4.48, 1.75, 1.69, 1.19,   # ก.พ. 70
    1.19, 1.35, 1.35, 1.35,   # มี.ค. 70
    1.60, 1.60, 1.60, 3.04,   # เม.ย. 70
    1.54, 1.54, 1.46, 1.46,   # พ.ค. 70
    1.78, 2.28, 1.54, 1.04,   # มิ.ย. 70
    1.17, 1.17, 1.17, 2.83,   # ก.ค. 70
    0.69, 1.39, 0.50, 0.00,   # ส.ค. 70
]

# ✅ Normalize ให้ผลรวม = 100.00% พอดี (แก้ 100.50% → 100.00%)
WEEKLY_PLAN_PCT = _normalize_to_100(_RAW_WEEKLY_PLAN_PCT, target=100.0)

# Sanity check (debug)
assert abs(sum(WEEKLY_PLAN_PCT) - 100.0) < 0.001, (
    f"WEEKLY_PLAN_PCT ต้องรวมได้ 100.00% แต่ได้ {sum(WEEKLY_PLAN_PCT):.4f}%"
)


# ============================================================
# HELPERS
# ============================================================
def _pct(num, den):
    return 0.0 if not den else (num / den) * 100


def _to_date(s):
    try:
        return pd.to_datetime(s).date()
    except Exception:
        return None


def _days_between(d1, d2):
    a, b = _to_date(d1), _to_date(d2)
    if a is None or b is None:
        return None
    return (b - a).days


def _warn_icon(level):
    return {"GREEN": "🟢", "YELLOW": "🟠", "RED": "🔴"}.get(level, "⚪")


def _warn_color(level):
    return {"GREEN": "#2E7D32", "YELLOW": "#F57C00", "RED": "#D32F2F"}.get(level, "#757575")


def _warn_bg(level):
    return {"GREEN": "#E8F5E9", "YELLOW": "#FFF8E1", "RED": "#FFEBEE"}.get(level, "#EEEEEE")


def _status_badge(status):
    mapping = {
        "Not Started": "⚪ ยังไม่เริ่ม",
        "In Progress": "🔵 กำลังทำ",
        "Submitted": "🟣 ส่งแล้ว",
        "Completeness Checked": "🟣 ตรวจครบแล้ว",
        "Under Review": "🟠 กำลังตรวจ",
        "Revision Required": "🟠 ต้องแก้ไข",
        "Ready for Acceptance": "🟢 พร้อมตรวจรับ",
        "Accepted": "🟢 ตรวจรับแล้ว",
        "Payment Processing": "🟡 กำลังเบิก",
        "Paid": "✅ จ่ายแล้ว",
        "Closed": "✅ ปิดแล้ว",
    }
    return mapping.get(status, status or "-")


def _load_csv(path: Path, key_col=None):
    """อ่าน CSV แบบ safe"""
    try:
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


# ============================================================
# ★ S-CURVE DATA (แผนสะสม vs จริงสะสม)
# ============================================================
def _compute_scurve(proj, dl_df, prog_df, ms_df):
    """
    คำนวณ S-Curve: แผนสะสม vs จริงสะสม

    - ใช้ update_date แทน timestamp (รองรับการบันทึกย้อนหลัง)
    - เพิ่มจุด "วันนี้" เพื่อให้ KPI แสดงผลจริง ณ ปัจจุบัน
    - interpolate plan สำหรับวันนี้ (ระหว่างสัปดาห์)
    - ✅ Plan normalized ให้ผลรวม = 100.00%
    """
    start_d = _to_date(proj["project_start_date"]) or date(2026, 8, 18)
    today = date.today()

    # ---- 1. เตรียม weight map ----
    if dl_df is None or dl_df.empty:
        dl_filtered = pd.DataFrame()
    else:
        dl_filtered = dl_df[
            dl_df["milestone_id"].astype(str).str.startswith("MLS")
        ].copy()

    if dl_filtered.empty:
        rows = []
        cum_plan = 0.0
        for i, w_pct in enumerate(WEEKLY_PLAN_PCT, 1):
            cum_plan += w_pct
            week_end = start_d + timedelta(days=7 * i)
            rows.append({
                "week_no": i,
                "date": week_end,
                "plan_cumulative": round(cum_plan, 2),
                "actual_cumulative": None,
            })
        rows.insert(0, {
            "week_no": 0, "date": start_d,
            "plan_cumulative": 0.0, "actual_cumulative": 0.0,
        })
        return pd.DataFrame(rows)

    dl_weight = dict(zip(
        dl_filtered["deliverable_id"].astype(str),
        pd.to_numeric(dl_filtered["weight"], errors="coerce").fillna(0),
    ))
    total_weight = sum(dl_weight.values())

    # ---- 2. Helper: คำนวณ actual สะสม ณ วันที่ ----
    def _actual_at(cutoff_date):
        if prog_df is None or prog_df.empty or total_weight <= 0:
            return None

        prog = prog_df.copy()
        if "update_date" in prog.columns:
            prog["_date"] = pd.to_datetime(prog["update_date"], errors="coerce").dt.date
        else:
            prog["_date"] = pd.to_datetime(prog["timestamp"], errors="coerce").dt.date

        prog = prog.dropna(subset=["_date"])
        sub = prog[prog["_date"] <= cutoff_date]
        if sub.empty:
            return 0.0

        latest = (
            sub.sort_values("_date")
               .groupby("deliverable_id")
               .tail(1)
        )

        weighted = 0.0
        for _, p in latest.iterrows():
            did = str(p["deliverable_id"])
            w = dl_weight.get(did, 0.0)
            try:
                a = float(p.get("actual_percent", 0) or 0)
            except Exception:
                a = 0.0
            weighted += w * a

        return round(weighted / total_weight, 2)

    # ---- 3. สร้างแถวรายสัปดาห์ ----
    rows = []
    cum_plan = 0.0
    for i, w_pct in enumerate(WEEKLY_PLAN_PCT, 1):
        cum_plan += w_pct
        week_end = start_d + timedelta(days=7 * i)
        rows.append({
            "week_no": i,
            "date": week_end,
            "plan_cumulative": round(cum_plan, 2),
            "actual_cumulative": None,
        })

    rows.insert(0, {
        "week_no": 0,
        "date": start_d,
        "plan_cumulative": 0.0,
        "actual_cumulative": 0.0,
    })

    df = pd.DataFrame(rows)

    # ---- 4. คำนวณ actual สำหรับแต่ละสัปดาห์ ----
    for idx, row in df.iterrows():
        actual = _actual_at(row["date"])
        if actual is not None:
            df.at[idx, "actual_cumulative"] = actual

    # ---- 5. แทรกจุด "วันนี้" ----
    last_week_date = df["date"].iloc[-1]

    if start_d < today <= last_week_date:
        before = df[df["date"] <= today]
        after = df[df["date"] > today]

        plan_today_val = None
        if not before.empty and not after.empty:
            d0 = before.iloc[-1]["date"]
            p0 = before.iloc[-1]["plan_cumulative"]
            d1 = after.iloc[0]["date"]
            p1 = after.iloc[0]["plan_cumulative"]
            total_days = (d1 - d0).days
            elapsed = (today - d0).days
            plan_today_val = (
                p0 + (p1 - p0) * (elapsed / total_days)
                if total_days > 0 else p0
            )
        elif not before.empty:
            plan_today_val = before.iloc[-1]["plan_cumulative"]

        existing_dates = set(df["date"].tolist())
        if plan_today_val is not None and today not in existing_dates:
            today_row = pd.DataFrame([{
                "week_no": None,
                "date": today,
                "plan_cumulative": round(plan_today_val, 2),
                "actual_cumulative": _actual_at(today),
            }])
            df = pd.concat([df, today_row], ignore_index=True)
            df = df.sort_values("date").reset_index(drop=True)

    return df


# ============================================================
# MAIN RENDER
# ============================================================
def render():
    st.title("🏠 Dashboard — CCH Consultant Monitoring")
    st.caption("Executive Overview · โครงการจ้างที่ปรึกษากำกับดูแลระบบชำระดุลส่วนกลาง (CCH)")

    cfg = load_settings()
    today = date.today()

    # ============================================================
    # LOAD DATA
    # ============================================================
    proj_df = _load_csv(DATA_DIR / "master" / "project_master.csv")
    if proj_df.empty:
        st.error("⚠️ ไม่พบข้อมูลโครงการ — กรุณาตั้งค่าที่เมนู ⚙️ Project / Milestone")
        return
    proj = proj_df.iloc[0]

    ms_df = _load_csv(DATA_DIR / "master" / "milestone_master.csv")
    dl_df = DeliverableRepo().read()
    prog_df = ProgressRepo().read()
    acc_df = AcceptanceRepo().read()
    pay_df = PaymentRepo().read()
    act_df = ActionRepo().read()
    iss_df = IssueRepo().read()
    mtg_df = MeetingRepo().read()
    res_df = ResolutionRepo().read()

    # ============================================================
    # ★ คำนวณ S-Curve + KPI ก่อน (ใช้ร่วมกันทั้งหน้า)
    # ============================================================
    scurve_df = _compute_scurve(proj, dl_df, prog_df, ms_df)

    today_sc = date.today()

    # ---- แผน ณ วันนี้ (จาก S-Curve — interpolated) ----
    _plan_today_df = scurve_df[scurve_df["date"] <= today_sc]
    planned_pct = (
        float(_plan_today_df["plan_cumulative"].iloc[-1])
        if not _plan_today_df.empty else 0.0
    )

    # ---- จริง ณ วันนี้ (จาก S-Curve) ----
    _actual_today_df = scurve_df[
        (scurve_df["date"] <= today_sc)
        & (scurve_df["actual_cumulative"].notna())
    ]
    actual_today = (
        float(_actual_today_df["actual_cumulative"].iloc[-1])
        if not _actual_today_df.empty else 0.0
    )

    # ---- Overall (ถ่วงน้ำหนัก deliverable) ----
    overall = compute_overall_progress(proj["project_id"])
    actual_pct = overall["overall_progress"]

    # ---- Variance = actual - plan ----
    variance = actual_pct - planned_pct

    # ---- วัน ----
    start_d = _to_date(proj["project_start_date"])
    end_d = _to_date(proj["project_end_date"])
    total_days = max((end_d - start_d).days, 1) if start_d and end_d else 360
    days_elapsed = max((today - start_d).days, 0) if start_d else 0
    days_remaining = (end_d - today).days if end_d else 0

    # ---- Health ----
    t = cfg["warning_thresholds"]
    if variance >= t["green_variance_pct"]:
        health_level = "GREEN"
    elif variance >= t["yellow_variance_pct"]:
        health_level = "YELLOW"
    else:
        health_level = "RED"

    health_icon = _warn_icon(health_level)
    health_text = {
        "GREEN": "เป็นไปตามแผน",
        "YELLOW": "ล่าช้าเล็กน้อย",
        "RED": "ล่าช้าอย่างมีนัยสำคัญ",
    }[health_level]

    # ============================================================
    # SECTION 1 — HERO BANNER
    # ============================================================
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#001233 0%,#003366 60%,#0B5ED7 100%);
                border-radius:14px;padding:22px 28px;color:#FFFFFF;margin-bottom:18px;
                box-shadow:0 8px 28px rgba(0,51,102,0.25);">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:20px;">
            <div style="flex:1;">
                <div style="font-size:13px;opacity:0.9;letter-spacing:0.4px;">
                    👔 Executive Dashboard · การทางพิเศษแห่งประเทศไทย
                </div>
                <div style="font-size:22px;font-weight:800;margin:6px 0 8px 0;">
                    {proj['project_name']}
                </div>
                <div style="font-size:13px;opacity:0.92;">
                    📄 สัญญา <b>{proj['contract_no']}</b>
                    &nbsp;·&nbsp; 👥 <b>{proj['consultant_name']}</b>
                    &nbsp;·&nbsp; 📅 {_to_date(proj['project_start_date'])} → {_to_date(proj['project_end_date'])}
                    &nbsp;·&nbsp; 💰 <b>{proj['total_contract_value']:,.0f} ฿</b>
                </div>
            </div>
            <div style="text-align:center;padding:14px 22px;
                        background:rgba(255,255,255,0.15);border-radius:12px;
                        border:1px solid rgba(255,255,255,0.3);">
                <div style="font-size:11px;opacity:0.85;letter-spacing:0.5px;">OVERALL</div>
                <div style="font-size:34px;font-weight:800;line-height:1;margin:4px 0;">
                    {actual_pct:.1f}%
                </div>
                <div style="font-size:11px;opacity:0.85;">{health_icon} {health_text}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ============================================================
    # SECTION 2 — TOP KPI ROW
    # ============================================================
    st.markdown("### 📊 สถานะโครงการ")
    k1, k2, k3, k4, k5 = st.columns(5)

    def _tile(label, value, sub, color):
        return f"""
        <div style="background:#FFFFFF;border-radius:12px;padding:14px 16px;
                    border-left:5px solid {color};box-shadow:0 2px 8px rgba(0,51,102,0.06);height:100%;">
            <div style="font-size:11.5px;color:#5A5A5A;font-weight:600;">{label}</div>
            <div style="font-size:24px;font-weight:700;color:#003366;line-height:1.1;margin:4px 0;">{value}</div>
            <div style="font-size:11.5px;color:{color};font-weight:600;">{sub}</div>
        </div>
        """

    with k1:
        st.markdown(_tile("🎯 Overall Progress", f"{actual_pct:.1f}%",
                          f"{len(overall['breakdown'])} deliverables",
                          "#0B5ED7"), unsafe_allow_html=True)
    with k2:
        st.markdown(_tile("📅 Planned (S-Curve)", f"{planned_pct:.1f}%",
                          "ตามแผน TOR",
                          "#00838F"), unsafe_allow_html=True)
    with k3:
        var_icon = "🟢" if variance >= 0 else ("🟠" if variance > -10 else "🔴")
        var_color = "#2E7D32" if variance >= 0 else ("#F57C00" if variance > -10 else "#D32F2F")
        st.markdown(_tile("📉 Variance (จริง−แผน)", f"{variance:+.1f}%",
                          f"{var_icon} {'นำแผน' if variance >= 0 else 'ล่าช้า'}",
                          var_color), unsafe_allow_html=True)
    with k4:
        st.markdown(_tile("⏱️ วันที่ผ่านไป", f"{days_elapsed}",
                          f"จาก {total_days} วัน",
                          "#6A1B9A"), unsafe_allow_html=True)
    with k5:
        rem_color = "#2E7D32" if days_remaining > 60 else ("#F57C00" if days_remaining > 0 else "#D32F2F")
        st.markdown(_tile("⏳ วันคงเหลือ", f"{max(days_remaining, 0)}",
                          "ยังไม่หมดสัญญา" if days_remaining > 0 else "⚠️ เกินกำหนด",
                          rem_color), unsafe_allow_html=True)

    # ============================================================
    # SECTION 3 — FINANCIAL OVERVIEW
    # ============================================================
    st.markdown("---")
    st.markdown("### 💰 ภาพรวมการเงิน")
    f1, f2, f3, f4 = st.columns(4)

    total_val = float(proj["total_contract_value"])

    if not pay_df.empty:
        paid_mask = pay_df["status"].isin(["Paid", "Closed"])
        paid_amt = pd.to_numeric(pay_df.loc[paid_mask, "payment_amount"], errors="coerce").fillna(0).sum()
        pending_mask = pay_df["status"].isin(["Payment Processing"])
        pending_amt = pd.to_numeric(pay_df.loc[pending_mask, "payment_amount"], errors="coerce").fillna(0).sum()
    else:
        paid_amt = pending_amt = 0

    acc_ready = 0
    if not acc_df.empty:
        acc_ready_mask = acc_df["status"].isin(["Accepted", "Payment Processing", "Paid", "Closed"])
        acc_ready = int(acc_ready_mask.sum())

    remaining_amt = total_val - paid_amt

    with f1:
        st.markdown(_tile("📋 มูลค่าสัญญารวม", f"{total_val:,.0f} ฿",
                          "ตามสัญญาจ้าง", "#0B5ED7"), unsafe_allow_html=True)
    with f2:
        st.markdown(_tile("✅ จ่ายแล้ว", f"{paid_amt:,.0f} ฿",
                          f"{_pct(paid_amt, total_val):.1f}% ของสัญญา",
                          "#2E7D32"), unsafe_allow_html=True)
    with f3:
        st.markdown(_tile("⏳ กำลังเบิก", f"{pending_amt:,.0f} ฿",
                          f"{_pct(pending_amt, total_val):.1f}% ของสัญญา",
                          "#F57C00"), unsafe_allow_html=True)
    with f4:
        st.markdown(_tile("💵 คงเหลือ", f"{remaining_amt:,.0f} ฿",
                          f"{_pct(remaining_amt, total_val):.1f}% ของสัญญา",
                          "#6A1B9A"), unsafe_allow_html=True)

    # ============================================================
    # SECTION 4 — MILESTONE TABLE
    # ============================================================
    st.markdown("---")
    st.markdown("### 📊 Milestone 1–5")

    if ms_df.empty:
        st.info("ยังไม่มีข้อมูล Milestone")
    else:
        ms_rows = []
        for _, m in ms_df.iterrows():
            mid = m["milestone_id"]

            m_dl = dl_df[dl_df["milestone_id"] == mid] if not dl_df.empty else dl_df
            m_actual = 0
            if not m_dl.empty and not prog_df.empty:
                total_w = 0
                weighted = 0
                for _, d in m_dl.iterrows():
                    w = float(d.get("weight", 0) or 0)
                    p = prog_df[prog_df["deliverable_id"] == d["deliverable_id"]]
                    latest = float(p["actual_percent"].iloc[-1]) if len(p) else 0
                    weighted += w * latest
                    total_w += w
                m_actual = weighted / total_w if total_w else 0

            m_acc = acc_df[acc_df["milestone_id"] == mid] if not acc_df.empty else acc_df
            m_pay = pay_df[pay_df["milestone_id"] == mid] if not pay_df.empty else pay_df
            acc_status = m_acc["status"].iloc[-1] if len(m_acc) else "Not Submitted"
            pay_status = m_pay["status"].iloc[-1] if len(m_pay) else "—"

            m_dict = m.to_dict()
            warn = check_milestone_warning(m_dict)

            dr = _days_between(today, m["due_date"])

            ms_rows.append({
                "Milestone":     f"M{m['milestone_no']} {m['milestone_name']}",
                "Due Date":      str(m["due_date"]),
                "วันคงเหลือ":     f"{dr:+d}" if dr is not None else "-",
                "Actual %":      f"{m_actual:.1f}%",
                "Payment %":     f"{m['payment_percent']}%",
                "Acceptance":    _status_badge(acc_status),
                "Payment":       _status_badge(pay_status),
                "Warning":       f"{_warn_icon(warn)} {warn}",
            })

        ms_view = pd.DataFrame(ms_rows)
        st.dataframe(ms_view, use_container_width=True, hide_index=True)

    # ============================================================
    # SECTION 4.5 — S-CURVE
    # ============================================================
    st.markdown("---")
    st.markdown("### 📈 S-Curve: แผนสะสม vs จริงสะสม")
    st.caption(
        "เปรียบเทียบแผนสะสมตาม TOR กับผลงานจริงสะสม — "
        "คำนวณจาก progress snapshots ถ่วงน้ำหนักตาม deliverable weight"
    )

    plan_today = planned_pct  # ใช้ค่าเดียวกันกับ KPI ด้านบน
    gap_today = actual_today - plan_today
    plan_end = float(scurve_df["plan_cumulative"].iloc[-1])

    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        st.markdown(_tile("📘 แผน ณ วันนี้", f"{plan_today:.1f}%",
                          "ตาม S-Curve TOR", "#0B5ED7"), unsafe_allow_html=True)
    with sc2:
        actual_color = "#2E7D32" if actual_today > 0 else "#9E9E9E"
        st.markdown(_tile("📗 จริง ณ วันนี้", f"{actual_today:.1f}%",
                          "จาก progress snapshots", actual_color),
                    unsafe_allow_html=True)
    with sc3:
        if actual_today == 0:
            gap_color, gap_sub = "#9E9E9E", "ยังไม่มีข้อมูล"
        elif gap_today >= -3:
            gap_color, gap_sub = "#2E7D32", "🟢 ตามแผน"
        elif gap_today >= -10:
            gap_color, gap_sub = "#F57C00", "🟠 ล่าช้าเล็กน้อย"
        else:
            gap_color, gap_sub = "#D32F2F", "🔴 ล่าช้ามาก"
        st.markdown(_tile("📊 ส่วนต่าง", f"{gap_today:+.1f}%",
                          gap_sub, gap_color), unsafe_allow_html=True)
    with sc4:
        st.markdown(_tile("🎯 แผนรวม", f"{plan_end:.1f}%",
                          "ถึงสิ้นสุดสัญญา", "#6A1B9A"), unsafe_allow_html=True)

    st.markdown("")

    fig_s = go.Figure()

    fig_s.add_trace(go.Scatter(
        x=scurve_df["date"],
        y=scurve_df["plan_cumulative"],
        mode="lines+markers",
        name="แผนสะสม (Plan %)",
        line=dict(color="#0B5ED7", width=3, shape="spline", smoothing=0.6),
        marker=dict(size=5, color="#0B5ED7"),
        fill="tozeroy",
        fillcolor="rgba(11,94,215,0.08)",
        hovertemplate=(
            "<b>แผนสะสม</b><br>"
            "วันที่: %{x|%d/%m/%Y}<br>"
            "สะสม: %{y:.1f}%"
            "<extra></extra>"
        ),
    ))

    if scurve_df["actual_cumulative"].notna().any():
        actual_plot = scurve_df[scurve_df["actual_cumulative"].notna()]
        fig_s.add_trace(go.Scatter(
            x=actual_plot["date"],
            y=actual_plot["actual_cumulative"],
            mode="lines+markers",
            name="ผลจริงสะสม (Actual %)",
            line=dict(color="#D32F2F", width=3, shape="spline", smoothing=0.6),
            marker=dict(size=8, color="#D32F2F", symbol="diamond",
                        line=dict(color="#FFF", width=1.5)),
            hovertemplate=(
                "<b>ผลจริงสะสม</b><br>"
                "วันที่: %{x|%d/%m/%Y}<br>"
                "สะสม: %{y:.1f}%"
                "<extra></extra>"
            ),
        ))

    # --- เส้น "วันนี้" ---
    fig_s.add_shape(
        type="line",
        x0=today_sc, x1=today_sc,
        y0=0, y1=1,
        yref="paper",
        line=dict(color="#F57C00", width=2, dash="dash"),
    )
    fig_s.add_annotation(
        x=today_sc,
        y=1.0,
        yref="paper",
        text="📅 วันนี้",
        showarrow=False,
        font=dict(color="#F57C00", size=11),
        xanchor="left",
        yshift=8,
    )

    # --- Milestone markers ---
    if not ms_df.empty:
        for _, m in ms_df.iterrows():
            m_due = _to_date(m["due_date"])
            if not m_due:
                continue
            m_no = int(m["milestone_no"])
            pct = float(m.get("payment_percent", 0) or 0)

            if m.get("status") in ("Accepted", "Payment Processing", "Paid", "Closed"):
                m_color = "#2E7D32"
                m_emoji = "✅"
            elif m_due < today_sc:
                m_color = "#D32F2F"
                m_emoji = "🔴"
            elif (m_due - today_sc).days <= 30:
                m_color = "#F57C00"
                m_emoji = "⏰"
            else:
                m_color = "#9E9E9E"
                m_emoji = "📌"

            fig_s.add_shape(
                type="line",
                x0=m_due, x1=m_due,
                y0=0, y1=1,
                yref="paper",
                line=dict(color=m_color, width=1.2, dash="dot"),
            )
            fig_s.add_annotation(
                x=m_due,
                y=0,
                yref="paper",
                text=f"{m_emoji} M{m_no} ({pct:.0f}%)",
                showarrow=False,
                font=dict(color=m_color, size=10),
                xanchor="left",
                yshift=-18,
            )

    fig_s.update_layout(
        height=520,
        plot_bgcolor="#FAFBFC",
        xaxis=dict(
            title="เดือน",
            tickformat="%b %Y",
            dtick="M1",
            tickangle=-45,
            showgrid=True,
            gridcolor="#EEEEEE",
            range=[
                pd.Timestamp(scurve_df["date"].iloc[0]) - pd.Timedelta(days=10),
                pd.Timestamp(scurve_df["date"].iloc[-1]) + pd.Timedelta(days=10),
            ],
        ),
        yaxis=dict(
            title="% สะสม",
            range=[0, 105],
            ticksuffix="%",
            showgrid=True,
            gridcolor="#EEEEEE",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.06,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(255,255,255,0.9)",
        ),
        hovermode="x unified",
        margin=dict(l=10, r=10, t=60, b=80),
    )

    st.plotly_chart(fig_s, use_container_width=True)

    if actual_today > 0 and gap_today < -10:
        st.markdown(
            f"""
            <div style="background:#FFEBEE;border-left:4px solid #D32F2F;
                        padding:12px 16px;border-radius:8px;font-size:13px;
                        color:#B71C1C;margin-top:8px;">
                🚨 <b>คำเตือน:</b> ผลจริงสะสม ({actual_today:.1f}%)
                ล่าช้ากว่าแผน ({plan_today:.1f}%) อยู่ <b>{abs(gap_today):.1f}%</b>
                — กรุณาตรวจสอบสาเหตุและหาแนวทางแก้ไข
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif actual_today == 0:
        st.markdown(
            """
            <div style="background:#F0F4F8;border-left:4px solid #0B5ED7;
                        padding:12px 16px;border-radius:8px;font-size:12.5px;
                        color:#003366;margin-top:8px;">
                ℹ️ <b>ยังไม่มีข้อมูลผลจริง</b> — กรุณาบันทึกความคืบหน้าที่เมนู
                <b>📈 Progress Update</b> เพื่อให้ S-Curve แสดงเส้นผลจริง
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("📥 ดาวน์โหลดข้อมูล S-Curve", expanded=False):
        export_df = scurve_df.copy()
        export_df["date"] = export_df["date"].astype(str)
        export_df.columns = ["สัปดาห์ที่", "วันที่", "แผนสะสม (%)", "จริงสะสม (%)"]
        st.dataframe(export_df, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ ดาวน์โหลด CSV",
            data=export_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"scurve_{today_sc}.csv",
            mime="text/csv",
            key="dl_scurve",
        )

    # ============================================================
    # SECTION 5 — DELIVERABLE PROGRESS TABLE (เรียงตามลำดับงาน)
    # ============================================================
    st.markdown("---")
    st.markdown("### 📈 ความคืบหน้าแต่ละ Deliverable")
    st.caption(
        "เรียงตามลำดับงาน M1 → M5 · แสดงหน่วยงานที่เกี่ยวข้อง · ช่วงเวลา · TOR"
    )

    if dl_df.empty:
        st.info("ยังไม่มีข้อมูล Deliverable — เพิ่มที่เมนู 📦 Deliverable Master")
    else:
        dl_view = dl_df.copy()
        dl_view = dl_view[
            dl_view["milestone_id"].astype(str).str.startswith("MLS")
        ].copy()
        dl_view = dl_view.sort_values(
            ["milestone_id", "deliverable_id"]
        ).reset_index(drop=True)

        # ---- Filters ----
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            f_ms = st.multiselect(
                "Milestone",
                sorted(dl_view["milestone_id"].unique().tolist()),
                default=sorted(dl_view["milestone_id"].unique().tolist()),
                key="dl_prog_ms",
            )
        with c2:
            all_status = sorted(
                [s for s in dl_view["status"].dropna().unique().tolist() if s]
            )
            f_stat = st.multiselect(
                "Status",
                all_status,
                default=all_status,
                key="dl_prog_stat",
            )
        with c3:
            f_search = st.text_input(
                "🔍 Search (ID / ชื่อ / TOR / หน่วยงาน)",
                value="",
                key="dl_prog_search",
            )

        # ---- Apply filters ----
        if f_ms:
            dl_view = dl_view[dl_view["milestone_id"].isin(f_ms)]
        if f_stat:
            dl_view = dl_view[dl_view["status"].isin(f_stat)]
        if f_search.strip():
            s = f_search.strip().lower()
            dl_view = dl_view[
                dl_view["deliverable_id"].astype(str).str.lower().str.contains(s, na=False)
                | dl_view["deliverable_name"].astype(str).str.lower().str.contains(s, na=False)
                | dl_view["tor_clause"].astype(str).str.lower().str.contains(s, na=False)
                | dl_view["deliverable_id"].astype(str).apply(
                    lambda x: s in RESPONSIBLE_UNITS.get(x, "").lower()
                )
            ]

        # ---- Build rows ----
        rows = []
        for i, (_, d) in enumerate(dl_view.iterrows(), 1):
            did = str(d["deliverable_id"])

            if not prog_df.empty:
                p = prog_df[prog_df["deliverable_id"] == did]
                actual = float(p["actual_percent"].iloc[-1]) if len(p) else 0.0
            else:
                actual = 0.0

            ps = _to_date(d.get("planned_start"))
            pf = _to_date(d.get("planned_finish"))
            if ps and pf:
                period = f"{ps.strftime('%d/%m/%y')} → {pf.strftime('%d/%m/%y')}"
            elif ps:
                period = f"{ps.strftime('%d/%m/%y')} →"
            elif pf:
                period = f"→ {pf.strftime('%d/%m/%y')}"
            else:
                period = "-"

            try:
                w = float(d.get("weight", 0) or 0)
                w_str = f"{w:.2f}"
            except Exception:
                w_str = "-"

            rows.append({
                "#":            i,
                "MS":           str(d["milestone_id"]).replace("MLS-", "M"),
                "ID":           did,
                "ชื่อกิจกรรม":   str(d.get("deliverable_name", ""))[:80],
                "หน่วยงาน":     RESPONSIBLE_UNITS.get(did, "-"),
                "ช่วงเวลา":     period,
                "TOR":          str(d.get("tor_clause", "-")),
                "W%":           w_str,
                "Actual":       f"{actual:.0f}%",
                "Status":       _status_badge(d.get("status")),
            })

        if not rows:
            st.info("ไม่พบรายการที่ตรงกับตัวกรอง")
        else:
            st.caption(f"แสดง **{len(rows)}** รายการ (เรียงตามลำดับงาน)")

            tbl_df = pd.DataFrame(rows)
            st.dataframe(
                tbl_df,
                use_container_width=True,
                hide_index=True,
                height=min(800, 38 * len(rows) + 42),
                column_config={
                    "#":            st.column_config.NumberColumn("#", width="small"),
                    "MS":           st.column_config.TextColumn("MS", width="small"),
                    "ID":           st.column_config.TextColumn("ID", width="small"),
                    "ชื่อกิจกรรม":   st.column_config.TextColumn("ชื่อกิจกรรม", width="large"),
                    "หน่วยงาน":     st.column_config.TextColumn("หน่วยงาน", width="small"),
                    "ช่วงเวลา":     st.column_config.TextColumn("ช่วงเวลา", width="small"),
                    "TOR":          st.column_config.TextColumn("TOR", width="small"),
                    "W%":           st.column_config.TextColumn("W%", width="small"),
                    "Actual":       st.column_config.TextColumn("Actual", width="small"),
                    "Status":       st.column_config.TextColumn("สถานะ", width="small"),
                },
            )

        with st.expander("📖 คำอธิบายตัวย่อหน่วยงาน", expanded=False):
            ref_rows = [
                {"ตัวย่อ": k, "ชื่อเต็ม": v}
                for k, v in UNIT_REFERENCE.items()
            ]
            st.dataframe(
                pd.DataFrame(ref_rows),
                use_container_width=True,
                hide_index=True,
            )

        # ---- Bar Chart ----
        st.markdown("---")
        st.markdown("#### 📊 Weight vs Progress (เรียงตามลำดับงาน)")

        if not dl_view.empty and not prog_df.empty:
            chart_rows = []
            for _, d in dl_view.iterrows():
                did = d["deliverable_id"]
                p = prog_df[prog_df["deliverable_id"] == did]
                actual = float(p["actual_percent"].iloc[-1]) if len(p) else 0.0
                chart_rows.append({
                    "sort_key": f"{d['milestone_id']}|{did}",
                    "label":    f"{did} · {str(d['deliverable_name'])[:40]}",
                    "weight":   float(d.get("weight", 0) or 0),
                    "actual":   actual,
                })

            if chart_rows:
                dv = pd.DataFrame(chart_rows).sort_values("sort_key")
                dv_plot = dv.iloc[::-1].reset_index(drop=True)

                if len(dv_plot) > 60:
                    st.caption(
                        f"⚠️ มี {len(dv_plot)} รายการ — กรอง Milestone "
                        f"เพื่อให้อ่านง่ายขึ้น"
                    )

                fig_dl = go.Figure()
                fig_dl.add_trace(go.Bar(
                    x=dv_plot["weight"],
                    y=dv_plot["label"],
                    orientation="h",
                    name="Weight %",
                    marker_color="#E0E6ED",
                    hovertemplate="Weight: %{x:.2f}%<extra></extra>",
                ))
                fig_dl.add_trace(go.Bar(
                    x=dv_plot["actual"] * dv_plot["weight"] / 100,
                    y=dv_plot["label"],
                    orientation="h",
                    name="Actual (weighted)",
                    marker_color="#0B5ED7",
                    text=dv_plot["actual"].apply(lambda x: f"{x:.0f}%"),
                    textposition="outside",
                    hovertemplate="Actual: %{text} · Contrib: %{x:.2f}%<extra></extra>",
                ))
                fig_dl.update_layout(
                    height=max(400, len(dv_plot) * 22),
                    barmode="overlay",
                    xaxis_title="Weight / Progress %",
                    legend=dict(orientation="h", y=1.03),
                    plot_bgcolor="#FAFBFC",
                    margin=dict(l=10, r=80, t=30, b=40),
                )
                st.plotly_chart(fig_dl, use_container_width=True)
        else:
            if prog_df.empty:
                st.info("ยังไม่มีข้อมูล Progress — บันทึกที่เมนู 📈 Progress Update")

    # ============================================================
    # SECTION 6 — ISSUES & ACTIONS
    # ============================================================
    st.markdown("---")
    st.markdown("### ⚠️ Issues & Actions")

    cA, cB = st.columns(2)

    with cA:
        st.markdown("#### 🐛 Issues")
        if iss_df.empty:
            st.info("ไม่มี Issue")
        else:
            open_iss = iss_df[~iss_df["status"].isin(["Closed"])] if "status" in iss_df else iss_df
            crit = open_iss[open_iss["severity"] == "Critical"] if "severity" in open_iss else open_iss.iloc[0:0]
            high = open_iss[open_iss["severity"] == "High"] if "severity" in open_iss else open_iss.iloc[0:0]
            esc = open_iss[open_iss["escalation_level"].astype(str).str.startswith("Level")] if "escalation_level" in open_iss else open_iss.iloc[0:0]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("เปิดอยู่", len(open_iss))
            m2.metric("🔴 Critical", len(crit))
            m3.metric("🟠 High", len(high))
            m4.metric("🚨 Escalated", len(esc))

            if len(open_iss):
                show_cols = [c for c in ["issue_id", "severity", "description", "action_due_date"] if c in open_iss.columns]
                st.dataframe(open_iss[show_cols].head(5), use_container_width=True, hide_index=True)

    with cB:
        st.markdown("#### ✅ Actions")
        if act_df.empty:
            st.info("ไม่มี Action")
        else:
            open_act = act_df[~act_df["status"].isin(["Completed", "Cancelled"])] if "status" in act_df else act_df
            overdue_mask = open_act["due_date"].apply(
                lambda d: (_to_date(d) is not None and _to_date(d) < today)
            ) if "due_date" in open_act else pd.Series([False] * len(open_act))
            overdue = open_act[overdue_mask]

            a1, a2, a3 = st.columns(3)
            a1.metric("เปิดอยู่", len(open_act))
            a2.metric("⏰ เกินกำหนด", len(overdue))
            a3.metric("🎯 ทั้งหมด", len(act_df))

            if len(open_act):
                show_cols = [c for c in ["action_id", "owner", "due_date", "description"] if c in open_act.columns]
                st.dataframe(open_act[show_cols].head(5), use_container_width=True, hide_index=True)

    # ============================================================
    # SECTION 7 — MEETING & RESOLUTION
    # ============================================================
    st.markdown("---")
    st.markdown("### 📅 งานประชุมกำกับดูแลและติดตามผล (ข้อ 1.3)")

    cM, cR = st.columns([1, 1])

    with cM:
        st.markdown("#### 📋 การประชุม")
        if mtg_df.empty:
            st.info("ยังไม่มีการประชุม — เริ่มที่เมนู 📅 ประชุมกำกับดูแล")
        else:
            mtg_sorted = mtg_df.sort_values("meeting_date", ascending=False)
            m1, m2, m3 = st.columns(3)
            m1.metric("จำนวนทั้งหมด", len(mtg_df))
            m2.metric("ประชุมแล้ว", len(mtg_df[mtg_df["status"] == "Held"]) if "status" in mtg_df else len(mtg_df))
            last_meeting = mtg_sorted.iloc[0]
            m3.metric("ล่าสุด", str(last_meeting.get("meeting_date", "-")))

            st.markdown(
                f"**🗓️ ประชุมล่าสุด:** `{last_meeting.get('meeting_no', '-')}` "
                f"— {last_meeting.get('meeting_type', '-')}  \n"
                f"📄 Minutes: `{last_meeting.get('minutes_reference', '-')}`"
            )

            with st.expander("ดูประวัติการประชุม 5 ครั้งล่าสุด"):
                show_cols = [c for c in ["meeting_no", "meeting_date", "meeting_type", "minutes_reference"]
                             if c in mtg_sorted.columns]
                st.dataframe(mtg_sorted[show_cols].head(5),
                             use_container_width=True, hide_index=True)

    with cR:
        st.markdown("#### ✅ มติที่ประชุม (Resolutions)")
        if res_df.empty:
            st.info("ยังไม่มีมติ — บันทึกที่เมนู 📅 ประชุมกำกับดูแล → แท็บมติ")
        else:
            open_res = res_df[res_df["status"] != "Closed"] if "status" in res_df else res_df
            overdue_res_mask = open_res["due_date"].apply(
                lambda d: (_to_date(d) is not None and _to_date(d) < today)
            ) if "due_date" in open_res else pd.Series([False] * len(open_res))
            overdue_res = open_res[overdue_res_mask]

            r1, r2, r3 = st.columns(3)
            r1.metric("ทั้งหมด", len(res_df))
            r2.metric("📌 เปิดอยู่", len(open_res))
            r3.metric("⏰ เกินกำหนด", len(overdue_res))

            if len(open_res):
                show_cols = [c for c in ["resolution_id", "resolution_text", "responsible_person", "due_date"]
                             if c in open_res.columns]
                tmp = open_res[show_cols].head(5).copy()
                if "resolution_text" in tmp.columns:
                    tmp["resolution_text"] = tmp["resolution_text"].astype(str).str.slice(0, 50)
                st.dataframe(tmp, use_container_width=True, hide_index=True)

    # ============================================================
    # SECTION 8 — ACCEPTANCE & PAYMENT WORKFLOW
    # ============================================================
    st.markdown("---")
    st.markdown("### 🔍 ตรวจรับ & เบิกจ่าย (ข้อ 1.5)")

    if ms_df.empty:
        st.info("ยังไม่มี Milestone")
    else:
        wf_rows = []
        for _, m in ms_df.iterrows():
            mid = m["milestone_id"]
            m_acc = acc_df[acc_df["milestone_id"] == mid] if not acc_df.empty else acc_df
            m_pay = pay_df[pay_df["milestone_id"] == mid] if not pay_df.empty else pay_df

            acc_status = m_acc["status"].iloc[-1] if len(m_acc) else "Not Submitted"
            pay_status = m_pay["status"].iloc[-1] if len(m_pay) else "—"
            pay_amt = float(m_pay["payment_amount"].iloc[-1]) if len(m_pay) and "payment_amount" in m_pay else 0

            steps = []
            steps.append("✅ Submitted" if len(m_acc) else "⚪ Submitted")
            steps.append("✅ Reviewed" if acc_status in ("Under Review", "Revision Required", "Ready for Acceptance",
                                                          "Accepted", "Payment Processing", "Paid", "Closed") else "⚪ Reviewed")
            steps.append("✅ Accepted" if acc_status in ("Accepted", "Payment Processing", "Paid", "Closed") else "⚪ Accepted")
            steps.append("✅ Paid" if pay_status in ("Paid", "Closed") else "⚪ Paid")

            wf_rows.append({
                "Milestone":     f"M{m['milestone_no']}",
                "ชื่อ":          m["milestone_name"],
                "Due Date":      str(m["due_date"]),
                "Workflow":      " → ".join(steps),
                "สถานะปัจจุบัน": _status_badge(acc_status) + " | " + _status_badge(pay_status),
                "ยอดจ่าย (฿)":   f"{pay_amt:,.0f}" if pay_amt else "—",
            })

        st.dataframe(pd.DataFrame(wf_rows), use_container_width=True, hide_index=True)

    # ============================================================
    # SECTION 9 — PROGRESS TIMELINE
    # ============================================================
    st.markdown("---")
    st.markdown("### 📈 Progress Timeline")

    if prog_df.empty:
        st.info("ยังไม่มีข้อมูล Progress")
    else:
        pdf = prog_df.copy()
        pdf["update_date_dt"] = pd.to_datetime(pdf["update_date"], errors="coerce")
        pdf = pdf.dropna(subset=["update_date_dt"]).sort_values("update_date_dt")

        fig_p = go.Figure()
        fig_p.add_trace(go.Scatter(
            x=pdf["update_date_dt"], y=pdf["actual_percent"],
            mode="lines+markers", name="Actual %",
            line=dict(color="#D32F2F", width=3),
            marker=dict(size=8),
        ))
        fig_p.add_trace(go.Scatter(
            x=pdf["update_date_dt"], y=pdf["planned_percent"],
            mode="lines+markers", name="Planned (deliverable)",
            line=dict(color="#0B5ED7", width=2, dash="dash"),
            marker=dict(size=6),
        ))
        fig_p.update_layout(
            height=380, plot_bgcolor="#FAFBFC",
            yaxis_title="%", xaxis_title="วันที่อัปเดต",
            legend=dict(orientation="h", y=1.1),
            hovermode="x unified",
        )
        st.plotly_chart(fig_p, use_container_width=True)

    # ============================================================
    # SECTION 10 — EARLY WARNING SUMMARY
    # ============================================================
    st.markdown("---")
    st.markdown("### 🚨 Early Warning Summary")

    warnings = []
    if not ms_df.empty:
        for _, m in ms_df.iterrows():
            w = check_milestone_warning(m.to_dict())
            if w != "GREEN":
                dr = _days_between(today, m["due_date"])
                warnings.append({
                    "ระดับ":  _warn_icon(w) + " " + w,
                    "ประเภท": "Milestone",
                    "รายการ": f"M{m['milestone_no']} {m['milestone_name']}",
                    "รายละเอียด": f"ครบกำหนดในอีก {dr} วัน" if dr and dr >= 0 else f"เกินกำหนด {-dr} วัน" if dr else "-",
                })

    if not res_df.empty:
        open_res = res_df[res_df["status"] != "Closed"]
        for _, r in open_res.iterrows():
            dr = _days_between(today, r.get("due_date"))
            if dr is not None and dr < 0:
                warnings.append({
                    "ระดับ": "🔴 RED",
                    "ประเภท": "Resolution",
                    "รายการ": r["resolution_id"],
                    "รายละเอียด": f"เกินกำหนด {-dr} วัน — {str(r['resolution_text'])[:50]}",
                })

    if not act_df.empty:
        open_act = act_df[~act_df["status"].isin(["Completed", "Cancelled"])]
        overdue_a = open_act[open_act["due_date"].apply(lambda d: _to_date(d) is not None and _to_date(d) < today)]
        for _, a in overdue_a.head(5).iterrows():
            dr = _days_between(today, a["due_date"])
            warnings.append({
                "ระดับ": "🟠 YELLOW",
                "ประเภท": "Action",
                "รายการ": a["action_id"],
                "รายละเอียด": f"เกินกำหนด {-dr} วัน — {str(a['description'])[:50]}",
            })

    if warnings:
        st.dataframe(pd.DataFrame(warnings), use_container_width=True, hide_index=True)
    else:
        st.markdown("✅ **ไม่มีรายการที่ต้องเฝ้าระวัง** — ทุกอย่างเป็นไปตามแผน")

    # ============================================================
    # FOOTER
    # ============================================================
    st.markdown("---")
    st.caption(f"🕒 ข้อมูล ณ วันที่ {today.strftime('%d/%m/%Y')} · อัปเดตล่าสุด: {datetime.now().strftime('%H:%M:%S')}")