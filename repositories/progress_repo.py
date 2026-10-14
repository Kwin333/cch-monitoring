from repositories.base_repo import AppendOnlyRepo

FIELDS = [
    "timestamp","progress_id","project_id","milestone_id","deliverable_id",
    "tor_clause","update_date","reporting_period",
    "planned_percent","actual_percent","progress_delta","status",
    "progress_description","evidence_reference","evidence_type",
    "issue_flag","risk_level","action_required","action_owner","action_due_date",
    "meeting_reference","resolution_reference",
    "reviewer","review_date","review_status","review_comment",
    "created_by","version_no",
]

class ProgressRepo(AppendOnlyRepo):
    def __init__(self):
        super().__init__("progress_history.csv", FIELDS)