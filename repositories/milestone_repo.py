from repositories.base_repo import MasterRepo

MILESTONE_FIELDS = [
    "milestone_id", "project_id", "milestone_no", "milestone_name",
    "tor_reference", "due_day", "due_date", "payment_percent", "payment_amount",
    "submission_date", "acceptance_date", "payment_date", "status", "updated_at",
]

class MilestoneRepo(MasterRepo):
    def __init__(self):
        super().__init__("milestone_master.csv", MILESTONE_FIELDS)