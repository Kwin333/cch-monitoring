"""Centralized validation rules (BR-01..BR-11)

★ v2 — แก้ไข:
- 🔧 Fix: `validate_payment_flow()` รองรับ date / datetime / str ผสมกัน
- 🔧 Fix: เพิ่ม helper `_to_date()` — normalize ทุก type เป็น date
- 🔧 Fix: Error message แสดงวันที่ให้เห็นชัดเจน
- 🔧 Fix: ใช้ `is None` แทน falsy check (ป้องกัน "" และ 0)
- 🔧 Fix: `validate_dates()` normalize ค่าก่อนเปรียบเทียบเช่นกัน
"""
from datetime import date, datetime


class ValidationError(Exception):
    pass


# ============================================================
# ★ v2: HELPER — Normalize ค่าเป็น date
# ============================================================
def _to_date(v):
    """
    ★ v2: แปลงค่าที่หลากหลายให้เป็น `date` หรือ `None`

    รองรับ:
    - date (คืนเลย)
    - datetime (แปลงเป็น .date())
    - str ISO (YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS)
    - str อื่นๆ (ลอง parse)
    - None, "" → None
    - อื่นๆ → None
    """
    if v is None or v == "":
        return None

    # date (ไม่ใช่ datetime)
    if isinstance(v, date) and not isinstance(v, datetime):
        return v

    # datetime → date
    if isinstance(v, datetime):
        return v.date()

    # str → ลอง parse
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None

        # ลอง ISO format (รวม YYYY-MM-DDTHH:MM:SS)
        try:
            return datetime.fromisoformat(s).date()
        except Exception:
            pass

        # ลอง YYYY-MM-DD (กรณีมี time ต่อท้าย)
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except Exception:
            pass

        # ลอง DD/MM/YYYY
        try:
            return datetime.strptime(s[:10], "%d/%m/%Y").date()
        except Exception:
            pass

        return None

    # pandas.Timestamp หรือ type อื่นที่มี .date()
    if hasattr(v, "date") and callable(getattr(v, "date")):
        try:
            return v.date()
        except Exception:
            return None

    return None


# ============================================================
# VALIDATORS (BR-01..BR-11)
# ============================================================
def validate_progress(actual, planned):
    """BR-01: actual/planned ต้องอยู่ 0-100"""
    if actual is None or not (0 <= actual <= 100):
        raise ValidationError("BR-01: actual_percent ต้องอยู่ระหว่าง 0-100")
    if planned is not None and not (0 <= planned <= 100):
        raise ValidationError("BR-01: planned_percent ต้องอยู่ระหว่าง 0-100")


def validate_dates(start, end, label="Due Date"):
    """
    BR-10: start ≤ end
    ★ v2: normalize ทั้ง 2 ค่าก่อนเทียบ
    """
    s = _to_date(start)
    e = _to_date(end)

    if s and e and e < s:
        raise ValidationError(
            f"BR-10: {label} ({e.strftime('%d/%m/%Y')}) "
            f"ต้องไม่ก่อนวันเริ่มต้น ({s.strftime('%d/%m/%Y')})"
        )


def validate_payment_flow(submission, acceptance, request, approval, payment):
    """
    ★ v2: BR-11 — ตรวจลำดับวันที่ในกระบวนการเบิกจ่าย

    ลำดับที่ถูกต้อง:
      Submission ≤ Acceptance ≤ Request ≤ Approval ≤ Payment

    รองรับทั้ง date / datetime / str (ISO, ISO datetime, DD/MM/YYYY)
    - ค่า None หรือ "" → skip (ไม่บังคับว่าต้องมีทุกขั้น)
    - เทียบเฉพาะคู่ที่มีค่าทั้งคู่
    """
    seq = [
        ("Submission",  _to_date(submission)),
        ("Acceptance",  _to_date(acceptance)),
        ("Request",     _to_date(request)),
        ("Approval",    _to_date(approval)),
        ("Payment",     _to_date(payment)),
    ]

    last = None
    last_name = None

    for name, d in seq:
        # ── Skip ค่าที่ normalize ไม่ได้ ──
        if d is None:
            continue

        # ── เปรียบเทียบกับค่าที่ผ่านมาก่อนหน้า ──
        if last is not None and d < last:
            raise ValidationError(
                f"BR-11: ลำดับวันที่ไม่ถูกต้อง — "
                f"'{name}' ({d.strftime('%d/%m/%Y')}) "
                f"ต้องไม่ก่อน "
                f"'{last_name}' ({last.strftime('%d/%m/%Y')})"
            )

        last = d
        last_name = name


def validate_issue_close(status, resolution):
    """BR-06: ห้ามปิด Issue ถ้าไม่มี Resolution"""
    if status == "Closed" and not (resolution or "").strip():
        raise ValidationError("BR-06: ห้ามปิด Issue ถ้าไม่มี Resolution")


def validate_action_complete(status, completion_date, evidence):
    """BR-07: Action Completed ต้องมี Completion Date + Evidence"""
    if status == "Completed":
        if not completion_date:
            raise ValidationError("BR-07: Action Completed ต้องมี Completion Date")
        if not (evidence or "").strip():
            raise ValidationError("BR-07: Action Completed ต้องมี Evidence")


def validate_review(review_status, comment):
    """BR-08: Revision Required / ไม่ผ่าน ต้องมี Comment"""
    if review_status in ("Revision Required", "ไม่ผ่าน") and not (comment or "").strip():
        raise ValidationError("BR-08: เลือก Revision Required ต้องระบุ Comment")