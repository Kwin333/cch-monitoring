from repositories.base_repo import AppendOnlyRepo

ACCEPTANCE_FIELDS = [
    "timestamp","acceptance_id","milestone_id","submission_date","submission_ref",
    "completeness_check","tor_compliance_check","deliverable_review_result",
    "revision_round","committee_date","acceptance_ref","acceptance_evidence",
    "status","reviewer","review_comment","created_by",
]

PAYMENT_FIELDS = [
    "timestamp","payment_id","milestone_id","acceptance_ref",
    "payment_percent","payment_amount","guarantee_deduction","guarantee_ref",
    "payment_request_date","approval_date","payment_date",
    "status","notes","created_by",
]

class AcceptanceRepo(AppendOnlyRepo):
    def __init__(self):
        super().__init__("acceptance_history.csv", ACCEPTANCE_FIELDS)

class PaymentRepo(AppendOnlyRepo):
    def __init__(self):
        super().__init__("payment_history.csv", PAYMENT_FIELDS)