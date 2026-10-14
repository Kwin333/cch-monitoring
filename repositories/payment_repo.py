from repositories.base_repo import AppendOnlyRepo

PAYMENT_FIELDS = [
    "timestamp","payment_id","milestone_id","acceptance_ref",
    "payment_percent","payment_amount","guarantee_deduction","guarantee_ref",
    "payment_request_date","approval_date","payment_date",
    "status","notes","created_by",
]

class PaymentRepo(AppendOnlyRepo):
    def __init__(self):
        super().__init__("payment_history.csv", PAYMENT_FIELDS)