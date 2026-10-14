"""Generate unique IDs. รูปแบบ: PREFIX-YYYYMMDD-NNNN"""
import csv
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent.parent / "data"
PREFIX_MAP = {
    "progress":    "PRG",
    "issue":       "ISS",
    "action":      "ACT",
    "meeting":     "MTG",
    "resolution":  "RES",
    "acceptance":  "ACC",
    "payment":     "PAY",
    "audit":       "AUD",
    "deliverable": "DLV",
    "milestone":   "MLS",
    "project":     "PRJ",
    "correction":  "COR",
    "review":      "RVW",
}

def _scan_existing(prefix: str, datestamp: str) -> int:
    """นับ max sequence ของวันนี้ จากทุก history file"""
    max_n = 0
    for folder in ["history", "master", "audit"]:
        d = BASE / folder
        if not d.exists():
            continue
        for f in d.glob("*.csv"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for row in csv.DictReader(fh):
                        for key in ("progress_id","issue_id","action_id","meeting_id",
                            "resolution_id","acceptance_id","payment_id",
                            "deliverable_id","milestone_id","project_id","audit_id",
                            "review_id"):
                            v = row.get(key, "")
                            if v and v.startswith(f"{prefix}-{datestamp}-"):
                                try:
                                    n = int(v.rsplit("-", 1)[1])
                                    max_n = max(max_n, n)
                                except ValueError:
                                    pass
            except Exception:
                pass
    return max_n

def new_id(kind: str) -> str:
    """kind: progress / issue / action / meeting / resolution / acceptance / payment / ..."""
    prefix = PREFIX_MAP.get(kind, "GEN")
    stamp = datetime.now().strftime("%Y%m%d")
    n = _scan_existing(prefix, stamp) + 1
    return f"{prefix}-{stamp}-{n:04d}"