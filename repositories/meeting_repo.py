from repositories.base_repo import AppendOnlyRepo

MEETING_FIELDS = [
    "timestamp","meeting_id","meeting_no","meeting_date","meeting_type",
    "agenda","attendees","consultant_attendees","minutes_reference","status",
    "linked_milestone_ids","linked_deliverable_ids","linked_issue_ids",
    "minutes_text","created_by",
]

RESOLUTION_FIELDS = [
    "timestamp","resolution_id","meeting_id","resolution_no","resolution_text",
    "responsible_person","due_date","evidence_required","status",
    "completion_date","linked_action_id","comment","created_by",
]

class MeetingRepo(AppendOnlyRepo):
    def __init__(self):
        super().__init__("meeting_history.csv", MEETING_FIELDS)

class ResolutionRepo(AppendOnlyRepo):
    def __init__(self):
        super().__init__("resolution_history.csv", RESOLUTION_FIELDS)