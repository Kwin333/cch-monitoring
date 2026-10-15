"""คำนวณ Overall Progress + Warning + Payment Amounts

★ v4 — แก้ไข:
- 🔧 Fix: `check_milestone_warning()` คืน GREEN ถ้า milestone status
  = Accepted / Payment Processing / Paid / Closed (ปิดงานแล้วไม่ต้องเตือน)
- 🔧 Fix: `_effective_actual()` ใช้ FINAL_STATUSES tuple กลาง
  รองรับ status เพิ่มเติม (Submitted, Under Review) ในอนาคต

★ v3:
- `compute_overall_progress()`: ถ้า deliverable status = "Accepted"
  → ใช้ actual = 100% เสมอ
- เพิ่ม helper `_effective_actual()` ใช้ร่วมกัน
- เพิ่ม helper `compute_milestone_progress()` สำหรับ reuse
"""
from datetime import date
from config_loader import load_settings
from repositories.progress_repo import ProgressRepo
from repositories.deliverable_repo import DeliverableRepo


# ============================================================
# ★ v4: Constants
# ============================================================
# Deliverable final statuses → นับเป็น 100%
DELIVERABLE_FINAL_STATUSES = ("Accepted", "Closed")

# Milestone final statuses → ไม่ต้องเตือน (GREEN เสมอ)
MILESTONE_FINAL_STATUSES = (
    "Accepted",
    "Payment Processing",
    "Paid",
    "Closed",
)


# ============================================================
# ★ v3: Helper — Effective Actual
# ============================================================
def _effective_actual(deliverable_row, prog_df) -> float:
    """
    คำนวณ actual % ที่แท้จริงของ deliverable
    ★ v3: ถ้า status = "Accepted" หรือ "Closed" → 100% ทันที

    Args:
        deliverable_row: row จาก deliverable_master (มี deliverable_id + status)
        prog_df: DataFrame ของ progress_history

    Returns:
        actual % (0.0 - 100.0)
    """
    # ── 1. ตรวจสอบ status ──
    try:
        status = str(deliverable_row.get("status", "") or "")
    except Exception:
        status = ""

    if status in DELIVERABLE_FINAL_STATUSES:
        return 100.0

    # ── 2. หา latest progress จาก history ──
    if prog_df is None or prog_df.empty:
        return 0.0

    did = deliverable_row.get("deliverable_id", "")
    p = prog_df[prog_df["deliverable_id"] == did]
    if p.empty:
        return 0.0

    try:
        # เรียงตาม timestamp ล่าสุด
        if "timestamp" in p.columns:
            p = p.copy()
            p["_ts"] = pd_to_datetime(p["timestamp"])
            p = p.dropna(subset=["_ts"]).sort_values("_ts")
        return float(p["actual_percent"].iloc[-1])
    except Exception:
        return 0.0


def pd_to_datetime(series):
    """Wrapper สำหรับ pd.to_datetime — ป้องกัน import pandas ไม่ตรง"""
    try:
        import pandas as pd
        return pd.to_datetime(series, errors="coerce")
    except Exception:
        return series


# ============================================================
# MAIN — Overall Progress
# ============================================================
def compute_overall_progress(project_id: str) -> dict:
    """
    Overall = Σ(weight × effective_actual)

    ★ v3: ใช้ _effective_actual() ที่คำนึงถึง status
    - status = "Accepted" / "Closed" → actual = 100%
    - status อื่น → อ่านจาก progress_history

    Returns:
        {
            "overall_progress": float,
            "breakdown": [{
                "deliverable_id", "weight", "latest_actual",
                "status", "contribution"
            }, ...],
            "total_weight": float,
            "has_accepted_override": bool
        }
    """
    deliv = DeliverableRepo().read()
    prog = ProgressRepo().read()

    if deliv.empty:
        return {
            "overall_progress": 0.0,
            "breakdown": [],
            "total_weight": 0.0,
            "has_accepted_override": False,
        }

    # กรองเฉพาะ deliverable ที่ belong กับ milestone จริง
    deliv = deliv[
        deliv["milestone_id"].astype(str).str.startswith("MLS")
    ].copy()

    rows = []
    total_weight = 0.0
    weighted = 0.0
    has_override = False

    for _, d in deliv.iterrows():
        did = d["deliverable_id"]
        w = float(d.get("weight", 0) or 0)
        status = str(d.get("status", "") or "")

        # ★ v3: ใช้ effective actual
        latest = _effective_actual(d, prog)

        if status in DELIVERABLE_FINAL_STATUSES and latest == 100.0:
            has_override = True

        total_weight += w
        weighted += w * latest

        rows.append({
            "deliverable_id": did,
            "weight": w,
            "latest_actual": latest,
            "status": status,
            "contribution": round(w * latest / 100.0, 4),
        })

    overall = (weighted / total_weight) if total_weight else 0.0

    return {
        "overall_progress": round(overall, 2),
        "breakdown": rows,
        "total_weight": round(total_weight, 2),
        "has_accepted_override": has_override,
    }


# ============================================================
# ★ v3: Milestone Progress (reusable)
# ============================================================
def compute_milestone_progress(milestone_id: str) -> dict:
    """
    คำนวณ progress ของ milestone เดียว
    ใช้ในหน้า p01 (Milestone table) และ p02 (Project)

    Returns:
        {
            "milestone_id": str,
            "progress": float,
            "n_deliverables": int,
            "n_accepted": int,
            "n_in_progress": int,
            "total_weight": float,
        }
    """
    deliv = DeliverableRepo().read()
    prog = ProgressRepo().read()

    if deliv.empty:
        return {
            "milestone_id": milestone_id,
            "progress": 0.0,
            "n_deliverables": 0,
            "n_accepted": 0,
            "n_in_progress": 0,
            "total_weight": 0.0,
        }

    m_dl = deliv[deliv["milestone_id"] == milestone_id].copy()
    if m_dl.empty:
        return {
            "milestone_id": milestone_id,
            "progress": 0.0,
            "n_deliverables": 0,
            "n_accepted": 0,
            "n_in_progress": 0,
            "total_weight": 0.0,
        }

    total_w = 0.0
    weighted = 0.0
    n_accepted = 0
    n_in_progress = 0

    for _, d in m_dl.iterrows():
        w = float(d.get("weight", 0) or 0)
        latest = _effective_actual(d, prog)
        total_w += w
        weighted += w * latest

        status = str(d.get("status", "") or "")
        if status in DELIVERABLE_FINAL_STATUSES:
            n_accepted += 1
        elif status == "In Progress":
            n_in_progress += 1

    progress = (weighted / total_w) if total_w else 0.0

    return {
        "milestone_id": milestone_id,
        "progress": round(progress, 2),
        "n_deliverables": len(m_dl),
        "n_accepted": n_accepted,
        "n_in_progress": n_in_progress,
        "total_weight": round(total_w, 2),
    }


# ============================================================
# WARNING HELPERS
# ============================================================
def warning_level(variance: float, cfg: dict = None) -> str:
    """variance = actual − planned"""
    if cfg is None:
        cfg = load_settings()
    t = cfg["warning_thresholds"]
    if variance >= t["green_variance_pct"]:
        return "GREEN"
    if variance >= t["yellow_variance_pct"]:
        return "YELLOW"
    return "RED"


def check_milestone_warning(m: dict) -> str:
    """
    เช็ค Milestone เทียบ Due Date

    ★ v4: ตรวจสอบ status ก่อน — ถ้า milestone เสร็จแล้ว → GREEN เสมอ
        (ปิดงานแล้ว ไม่ควรขึ้น RED แม้เลย Due Date)

    ลำดับการเช็ค:
    1. status ∈ (Accepted, Payment Processing, Paid, Closed)
       → GREEN (ปิดงานแล้ว)
    2. ไม่มี due_date → GREEN
    3. due_date ผ่านมาแล้ว (days_left < 0) → RED
    4. days_left ≤ due_soon_days → YELLOW
    5. อื่นๆ → GREEN
    """
    cfg = load_settings()
    today = date.today()

    # ══════════════════════════════════════════════════════
    # ★ v4: ถ้า milestone เสร็จสิ้นแล้ว → GREEN ทันที
    # ══════════════════════════════════════════════════════
    status = str(m.get("status", "") or "")
    if status in MILESTONE_FINAL_STATUSES:
        return "GREEN"

    # ══════════════════════════════════════════════════════
    # เช็ค Due Date ตามปกติ
    # ══════════════════════════════════════════════════════
    due = m.get("due_date")
    if not due:
        return "GREEN"

    if isinstance(due, str):
        try:
            due = date.fromisoformat(due)
        except Exception:
            return "GREEN"

    days_left = (due - today).days

    if days_left < 0:
        return "RED"
    if days_left <= cfg["warning_thresholds"]["due_soon_days"]:
        return "YELLOW"
    return "GREEN"


# ============================================================
# PAYMENT
# ============================================================
def compute_payment_amounts(milestone: dict, total_value: float) -> dict:
    """10% หักจาก 'ยอดจ่ายงวดนี้' ไม่ใช่ทั้งสัญญา (BR-12)"""
    cfg = load_settings()
    pct = float(milestone.get("payment_percent", 0))
    gross = total_value * pct / 100.0
    ded = gross * cfg["payment"]["guarantee_deduction_pct"] / 100.0
    return {
        "payment_percent": pct,
        "payment_amount": round(gross, 2),
        "guarantee_deduction": round(ded, 2),
        "net_payable": round(gross - ded, 2),
    }