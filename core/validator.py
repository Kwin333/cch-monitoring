"""Centralized validation rules (BR-01..BR-11)"""
from datetime import date

class ValidationError(Exception):
    pass

def validate_progress(actual, planned):
    if actual is None or not (0 <= actual <= 100):
        raise ValidationError("BR-01: actual_percent ต้องอยู่ระหว่าง 0-100")
    if planned is not None and not (0 <= planned <= 100):
        raise ValidationError("BR-01: planned_percent ต้องอยู่ระหว่าง 0-100")

def validate_dates(start, end, label="Due Date"):
    if start and end and end < start:
        raise ValidationError(f"BR-10: {label} ต้องไม่ก่อนวันเริ่มต้น")

def validate_payment_flow(submission, acceptance, request, approval, payment):
    seq = [("Submission", submission), ("Acceptance", acceptance),
           ("Request", request), ("Approval", approval), ("Payment", payment)]
    last, last_name = None, None
    for name, d in seq:
        if d:
            if last and d < last:
                raise ValidationError(f"BR-11: {name} ต้องไม่ก่อน {last_name}")
            last, last_name = d, name

def validate_issue_close(status, resolution):
    if status == "Closed" and not (resolution or "").strip():
        raise ValidationError("BR-06: ห้ามปิด Issue ถ้าไม่มี Resolution")

def validate_action_complete(status, completion_date, evidence):
    if status == "Completed":
        if not completion_date:
            raise ValidationError("BR-07: Action Completed ต้องมี Completion Date")
        if not (evidence or "").strip():
            raise ValidationError("BR-07: Action Completed ต้องมี Evidence")

def validate_review(review_status, comment):
    if review_status in ("Revision Required", "ไม่ผ่าน") and not (comment or "").strip():
        raise ValidationError("BR-08: เลือก Revision Required ต้องระบุ Comment")