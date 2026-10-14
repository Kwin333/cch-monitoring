from repositories.base_repo import MasterRepo
FIELDS = ["deliverable_id","milestone_id","tor_clause","deliverable_name",
          "description","required_output","required_evidence","weight",
          "planned_start","planned_finish","actual_start","actual_finish",
          "status","compliance_status","reviewer","review_date",
          "review_comment","updated_at"]
class DeliverableRepo(MasterRepo):
    def __init__(self):
        super().__init__("deliverable_master.csv", FIELDS)