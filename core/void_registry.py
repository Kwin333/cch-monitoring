"""ทะเบียนรายการที่ถูก Void — soft delete registry
รองรับทั้ง CSV และ PostgreSQL

★ v2:
- ใช้ core.db สำหรับ DB mode
- CSV mode ทำงานเหมือนเดิม 100%
"""
import csv
import os
from pathlib import Path

from core.time_util import now_str


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
# PATHS
# ═══════════════════════════════════════════════════════════
DATA_DIR = Path(__file__).parent.parent / "data"
VOID_FILE = DATA_DIR / "audit" / "voided_records.csv"
TABLE_NAME = "voided_records"

FIELDS = [
    "void_id", "record_type", "record_id", "reason",
    "voided_by", "voided_at", "mode",
]


def _ensure_dir():
    VOID_FILE.parent.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════
# WRITE
# ═══════════════════════════════════════════════════════════
def add_void(record_type: str, record_id: str,
             reason: str, user: str, mode: str = "soft"):
    """เพิ่ม void record — รองรับทั้ง CSV และ DB"""
    row = {
        "void_id":     f"VOID-{now_str().replace('-','').replace(':','').replace(' ','')[:15]}-{str(record_id)[-4:]}",
        "record_type": record_type,
        "record_id":   record_id,
        "reason":      reason,
        "voided_by":   user,
        "voided_at":   now_str(),
        "mode":        mode,
    }

    if _USE_DB:
        try:
            from core.db import append_row
            append_row(TABLE_NAME, row)
        except Exception as e:
            print(f"⚠️ DB void failed: {e} — falling back to CSV")
            _add_void_csv(row)
    else:
        _add_void_csv(row)


def _add_void_csv(row):
    _ensure_dir()
    exists = VOID_FILE.exists()
    with open(VOID_FILE, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(row)


# ═══════════════════════════════════════════════════════════
# READ
# ═══════════════════════════════════════════════════════════
def read_voids():
    """อ่าน voided records ทั้งหมด — รองรับทั้ง CSV และ DB"""
    import pandas as pd

    if _USE_DB:
        try:
            from core.db import read_table
            df = read_table(TABLE_NAME)
            if df.empty and VOID_FILE.exists():
                return pd.read_csv(VOID_FILE, encoding="utf-8-sig")
            return df
        except Exception:
            if VOID_FILE.exists():
                return pd.read_csv(VOID_FILE, encoding="utf-8-sig")
            return pd.DataFrame(columns=FIELDS)
    else:
        if not VOID_FILE.exists():
            return pd.DataFrame(columns=FIELDS)
        return pd.read_csv(VOID_FILE, encoding="utf-8-sig")


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def get_voided_ids() -> set:
    """คืน set ของ record_id ที่ถูก void"""
    try:
        df = read_voids()
        if df.empty:
            return set()
        return set(df["record_id"].astype(str).tolist())
    except Exception:
        return set()


def is_voided(record_id: str) -> bool:
    """ตรวจว่า record ถูก void หรือยัง"""
    return str(record_id) in get_voided_ids()


def get_void_info(record_id: str) -> dict | None:
    """คืนข้อมูล void ล่าสุดของ record_id"""
    try:
        df = read_voids()
        if df.empty:
            return None
        sub = df[df["record_id"].astype(str) == str(record_id)]
        if sub.empty:
            return None
        return sub.iloc[-1].to_dict()
    except Exception:
        return None


def count_voids_by_type() -> dict:
    """นับจำนวน voided records แต่ละประเภท"""
    try:
        df = read_voids()
        if df.empty:
            return {}
        return df["record_type"].value_counts().to_dict()
    except Exception:
        return {}


def search_voids(keyword: str) -> list:
    """ค้นหา voided records"""
    if not keyword:
        return []
    try:
        df = read_voids()
        if df.empty:
            return []
        kw = keyword.lower()
        mask = (
            df["record_id"].astype(str).str.lower().str.contains(kw, na=False)
            | df["reason"].astype(str).str.lower().str.contains(kw, na=False)
            | df["voided_by"].astype(str).str.lower().str.contains(kw, na=False)
        )
        return df[mask].to_dict("records")
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════
# DELETE — ยกเลิกการ Void
# ═══════════════════════════════════════════════════════════
def remove_void(record_id: str) -> bool:
    """ยกเลิกการ Void — คืน True ถ้าลบสำเร็จ"""
    if _USE_DB:
        try:
            from core.db import delete_row, get_engine, read_table
            from sqlalchemy import text

            engine = get_engine()

            # ตรวจว่ามี record นี้ไหม
            with engine.begin() as conn:
                exists = conn.execute(
                    text(f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE record_id = :rid"),
                    {"rid": str(record_id)},
                ).scalar()

            if not exists:
                return False

            with engine.begin() as conn:
                conn.execute(
                    text(f"DELETE FROM {TABLE_NAME} WHERE record_id = :rid"),
                    {"rid": str(record_id)},
                )
            return True
        except Exception as e:
            print(f"⚠️ DB remove_void failed: {e} — falling back to CSV")
            return _remove_void_csv(record_id)
    else:
        return _remove_void_csv(record_id)


def _remove_void_csv(record_id: str) -> bool:
    _ensure_dir()
    if not VOID_FILE.exists():
        return False
    import pandas as pd
    df = pd.read_csv(VOID_FILE, encoding="utf-8-sig")
    before = len(df)
    df = df[df["record_id"].astype(str) != str(record_id)]
    if len(df) == before:
        return False
    df.to_csv(VOID_FILE, index=False, encoding="utf-8-sig")
    return True


# ═══════════════════════════════════════════════════════════
# DEBUG
# ═══════════════════════════════════════════════════════════
def is_db_mode() -> bool:
    """คืนค่า True ถ้าใช้ DB"""
    return _USE_DB


def get_void_count() -> int:
    """นับจำนวน voided records"""
    try:
        return len(read_voids())
    except Exception:
        return 0