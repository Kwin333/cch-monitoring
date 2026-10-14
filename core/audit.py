"""Append-only audit log"""
import csv
from pathlib import Path
from core.ids import new_id
from core.time_util import now_str

AUDIT_FILE = Path(__file__).parent.parent / "data" / "audit" / "audit_log.csv"
FIELDS = ["audit_id","timestamp","user","action","module","record_id",
          "old_value","new_value","reason","session_id","version"]

def append_audit(user, action, module, record_id,
                 old_value="", new_value="", reason="", session_id=""):
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    exists = AUDIT_FILE.exists()
    with open(AUDIT_FILE, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerow({
            "audit_id":   new_id("audit"),
            "timestamp":  now_str(),
            "user":       user,
            "action":     action,
            "module":     module,
            "record_id":  record_id,
            "old_value":  str(old_value)[:500],
            "new_value":  str(new_value)[:500],
            "reason":     reason,
            "session_id": session_id,
            "version":    "v1",
        })

def read_audit():
    import pandas as pd
    if not AUDIT_FILE.exists():
        return pd.DataFrame(columns=FIELDS)
    return pd.read_csv(AUDIT_FILE, encoding="utf-8-sig")