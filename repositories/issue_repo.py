from repositories.base_repo import AppendOnlyRepo

ISSUE_FIELDS = [
    "issue_id","timestamp","project_id","milestone_id","deliverable_id",
    "tor_clause","issue_date","description","impact","severity",
    "root_cause","responsible_party","corrective_action",
    "preventive_action","action_due_date","escalation_level",
    "meeting_reference","resolution","status","closed_date",
    "evidence_reference","created_by",
]

class IssueRepo(AppendOnlyRepo):
    def __init__(self):
        super().__init__("issue_history.csv", ISSUE_FIELDS)