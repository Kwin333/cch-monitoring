"""Generate unique IDs. รูปแบบ: PREFIX-YYYYMMDD-NNNN

★ v2:
- รองรับทั้ง CSV และ DB mode
- DB mode: query MAX(id) จาก DB table (แก้ bug duplicate key)
- เพิ่ม verify + retry เพื่อป้องกัน race condition
"""
import csv
import os
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

# ★ v2: Mapping prefix → (table_name, id_col) สำหรับ DB mode
PREFIX_TO_TABLE = {
    "PRG": ("progress_history",            "progress_id"),
    "ISS": ("issue_history",               "issue_id"),
    "ACT": ("action_history",              "action_id"),
    "MTG": ("meeting_history",             "meeting_id"),
    "RES": ("resolution_history",          "resolution_id"),
    "ACC": ("acceptance_history",          "acceptance_id"),
    "PAY": ("payment_history",             "payment_id"),
    "AUD": ("audit_log",                   "audit_id"),
    "RVW": ("deliverable_review_history",  "review_id"),
    "DLV": ("deliverable_master",          "deliverable_id"),
    "MLS": ("milestone_master",            "milestone_id"),
    "PRJ": ("project_master",              "project_id"),
    "COR": ("correction_history",          "correction_id"),
}

# All ID column names (ใช้ตอนสแกน CSV)
ALL_ID_COLS = (
    "progress_id", "issue_id", "action_id", "meeting_id",
    "resolution_id", "acceptance_id", "payment_id",
    "deliverable_id", "milestone_id", "project_id",
    "audit_id", "review_id",
)


# ═══════════════════════════════════════════════════════════
# BACKEND SELECTION
# ═══════════════════════════════════════════════════════════
_USE_DB = os.environ.get("USE_DATABASE", "false").lower() == "true"

try:
    import streamlit as st
    if st.secrets.get("DATABASE_URL"):
        _USE_DB = True
except Exception:
    pass


# ═══════════════════════════════════════════════════════════
# CSV SCAN (เดิม)
# ═══════════════════════════════════════════════════════════
def _scan_existing_csv(prefix: str, datestamp: str) -> int:
    """นับ max sequence ของวันนี้ จากทุก CSV file"""
    max_n = 0
    for folder in ["history", "master", "audit"]:
        d = BASE / folder
        if not d.exists():
            continue
        for f in d.glob("*.csv"):
            try:
                with open(f, "r", encoding="utf-8-sig") as fh:
                    for row in csv.DictReader(fh):
                        for key in ALL_ID_COLS:
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


# ═══════════════════════════════════════════════════════════
# ★ v2: DB SCAN
# ═══════════════════════════════════════════════════════════
def _scan_existing_db(prefix: str, datestamp: str) -> int:
    """
    ★ v2: นับ max sequence จาก DB

    ใช้ PostgreSQL regex: SUBSTRING(id FROM '\\d+$') เพื่อดึงตัวเลขท้าย
    """
    if prefix not in PREFIX_TO_TABLE:
        return 0

    table_name, id_col = PREFIX_TO_TABLE[prefix]

    try:
        from core.db import get_engine, _q
        from sqlalchemy import text

        engine = get_engine()
        pattern = f"{prefix}-{datestamp}-%"

        sql = text(f'''
            SELECT MAX(
                CAST(SUBSTRING({_q(id_col)} FROM '\\d+$') AS INTEGER)
            )
            FROM {_q(table_name)}
            WHERE {_q(id_col)} LIKE :pattern
        ''')

        with engine.connect() as conn:
            result = conn.execute(sql, {"pattern": pattern}).scalar()
            return int(result) if result else 0

    except Exception as e:
        print(f"⚠️ _scan_existing_db error: {type(e).__name__}: {e}")
        # Fallback: ลอง CSV ด้วย (เผื่อ DB error)
        try:
            return _scan_existing_csv(prefix, datestamp)
        except Exception:
            return 0


# ═══════════════════════════════════════════════════════════
# ★ v2: Check ID exists (สำหรับ verify)
# ═══════════════════════════════════════════════════════════
def _id_exists_db(candidate_id: str, prefix: str) -> bool:
    """ตรวจว่า ID มีอยู่ใน DB แล้วหรือยัง"""
    if prefix not in PREFIX_TO_TABLE:
        return False

    table_name, id_col = PREFIX_TO_TABLE[prefix]

    try:
        from core.db import get_engine, _q
        from sqlalchemy import text

        engine = get_engine()
        sql = text(
            f'SELECT 1 FROM {_q(table_name)} '
            f'WHERE {_q(id_col)} = :id LIMIT 1'
        )
        with engine.connect() as conn:
            result = conn.execute(sql, {"id": candidate_id}).scalar()
            return result is not None

    except Exception:
        return False


def _id_exists_csv(candidate_id: str) -> bool:
    """ตรวจว่า ID มีอยู่ใน CSV แล้วหรือยัง"""
    for folder in ["history", "master", "audit"]:
        d = BASE / folder
        if not d.exists():
            continue
        for f in d.glob("*.csv"):
            try:
                with open(f, "r", encoding="utf-8-sig") as fh:
                    for row in csv.DictReader(fh):
                        for key in ALL_ID_COLS:
                            if row.get(key, "") == candidate_id:
                                return True
            except Exception:
                pass
    return False


# ═══════════════════════════════════════════════════════════
# MAIN — Generate new ID
# ═══════════════════════════════════════════════════════════
def new_id(kind: str) -> str:
    """
    สร้าง ID ใหม่ รูปแบบ PREFIX-YYYYMMDD-NNNN

    Args:
        kind: progress / issue / action / meeting / resolution /
              acceptance / payment / audit / review / deliverable /
              milestone / project

    Returns:
        ID string เช่น "RVW-20261014-0003"
    """
    prefix = PREFIX_MAP.get(kind, "GEN")
    stamp = datetime.now().strftime("%Y%m%d")

    # ---- หา max_n ----
    if _USE_DB:
        max_n = _scan_existing_db(prefix, stamp)
    else:
        max_n = _scan_existing_csv(prefix, stamp)

    # ---- ★ Safety: verify + retry (ป้องกัน race condition) ----
    for i in range(50):  # max 50 retries
        candidate_n = max_n + 1 + i
        candidate_id = f"{prefix}-{stamp}-{candidate_n:04d}"

        if _USE_DB:
            exists = _id_exists_db(candidate_id, prefix)
        else:
            exists = _id_exists_csv(candidate_id)

        if not exists:
            return candidate_id

    # ถ้าถึงตรงนี้ = มีปัญหาจริง ๆ
    raise RuntimeError(
        f"ไม่สามารถสร้าง unique ID สำหรับ {prefix}-{stamp} "
        f"ได้ใน 50 retries (max_n={max_n})"
    )


# ═══════════════════════════════════════════════════════════
# DEBUG
# ═══════════════════════════════════════════════════════════
def debug_id_mode() -> str:
    """สำหรับ debug — บอกว่าใช้ DB หรือ CSV"""
    return "DB" if _USE_DB else "CSV"