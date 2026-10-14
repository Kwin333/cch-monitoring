"""คำนวณ Overall Progress + Warning + Payment Amounts"""
from datetime import date
from config_loader import load_settings
from repositories.progress_repo import ProgressRepo
from repositories.deliverable_repo import DeliverableRepo


def compute_overall_progress(project_id: str) -> dict:
    """Overall = Σ(weight × latest_actual)"""
    deliv = DeliverableRepo().read()
    prog = ProgressRepo().read()

    if deliv.empty:
        return {"overall_progress": 0.0, "breakdown": [], "total_weight": 0.0}

    # กรองเฉพาะ deliverable ที่ belong กับ milestone จริง (ตัดแถว 'รวม')
    deliv = deliv[deliv["milestone_id"].astype(str).str.startswith("MLS")].copy()

    rows = []
    total_weight = 0.0
    weighted = 0.0
    for _, d in deliv.iterrows():
        did = d["deliverable_id"]
        w = float(d.get("weight", 0) or 0)
        p = prog[prog["deliverable_id"] == did] if not prog.empty else prog
        latest = float(p["actual_percent"].iloc[-1]) if len(p) else 0.0
        total_weight += w
        weighted += w * latest
        rows.append({"deliverable_id": did, "weight": w, "latest_actual": latest})

    overall = (weighted / total_weight) if total_weight else 0.0
    return {
        "overall_progress": round(overall, 2),
        "breakdown": rows,
        "total_weight": total_weight,
    }


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
    """เช็ค Milestone เทียบ Due Date"""
    cfg = load_settings()
    today = date.today()
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