from repositories.base_repo import AppendOnlyRepo

ACTION_FIELDS = [
    "action_id","timestamp","source_type","source_id","description",
    "owner","priority","due_date","status","completion_date",
    "evidence","verification_status","verifier","verification_date",
    "comment","created_by",
]

class ActionRepo(AppendOnlyRepo):
    def __init__(self):
        super().__init__("action_history.csv", ACTION_FIELDS)