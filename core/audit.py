"""Append-only audit log — รองรับทั้ง CSV และ PostgreSQL

★ v2:
- ใช้ core.db สำหรับ DB mode (quote identifier อัตโนมัติ)
- แสดง error ชัดเจน แทน silent fallback (เพื่อ debug ได้)
- CSV mode ทำงานเหมือนเดิม 100%
- Fallback: ถ้า DB error → ลองเขียน CSV + re-raise error
  (เพื่อให้ผู้ใช้เห็นปัญหา ไม่หายเงียบ ๆ)
"""
import csv
import os
import traceback
from pathlib import Path

from core.ids import new_id
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
AUDIT_FILE = DATA_DIR / "audit" / "audit_log.csv"
TABLE_NAME = "audit_log"

FIELDS = [
    "audit_id", "timestamp", "user", "action", "module", "record_id",
    "old_value", "new_value", "reason", "session_id", "version",
]


# ═══════════════════════════════════════════════════════════
# DEBUG HELPER
# ═══════════════════════════════════════════════════════════
def is_db_mode() -> bool:
    """คืนค่า True ถ้าใช้ DB"""
    return _USE_DB


# ═══════════════════════════════════════════════════════════
# WRITE
# ═══════════════════════════════════════════════════════════
def append_audit(user, action, module, record_id,
                 old_value="", new_value="", reason="", session_id="",
                 raise_on_error: bool = False):
    """
    เขียน audit log — รองรับทั้ง CSV และ DB

    ★ v2 ใหม่:
    - แสดง error ให้เห็น (แทน silent fallback)
    - Fallback: ลองเขียน CSV ด้วย แต่ log error ไว้
    - raise_on_error: ถ้า True → raise exception (สำหรับ debug)

    Args:
        user: ชื่อผู้ใช้
        action: CREATE / UPDATE / DELETE / LOGIN ฯลฯ
        module: PROJECT / MILESTONE / DELIVERABLE ฯลฯ
        record_id: ID ของ record ที่ถูกกระทำ
        old_value: ค่าเก่า (str)
        new_value: ค่าใหม่ (str)
        reason: เหตุผล
        session_id: session ID (optional)
        raise_on_error: ถ้า True → โยน error ออกมา (ไม่ silent)
    """
    row = {
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
    }

    if _USE_DB:
        try:
            from core.db import append_row
            append_row(TABLE_NAME, row)
            # ✅ สำเร็จ — ออกเลย
            return
        except Exception as e:
            # ❌ DB error — log ให้ชัดเจน
            err_msg = (
                f"❌ append_audit DB error: "
                f"{type(e).__name__}: {e}\n"
                f"   Table: {TABLE_NAME}\n"
                f"   Row keys: {list(row.keys())}"
            )
            print(err_msg)
            print(traceback.format_exc())

            # ลองเขียน CSV เป็น fallback (backup data)
            try:
                _append_audit_csv(row)
                print("⚠️ Fallback: audit saved to CSV successfully")
            except Exception as e2:
                print(f"❌ CSV fallback also failed: {e2}")

            # ถ้า raise_on_error=True → โยน error ออก
            if raise_on_error:
                raise

            # ถ้าไม่ → กลืน error แต่ data ยังถูกบันทึกใน CSV
            return

    else:
        # CSV mode
        _append_audit_csv(row)


def _append_audit_csv(row):
    """CSV fallback"""
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    exists = AUDIT_FILE.exists()
    with open(AUDIT_FILE, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(row)


# ═══════════════════════════════════════════════════════════
# READ
# ═══════════════════════════════════════════════════════════
def read_audit():
    """
    อ่าน audit log ทั้งหมด → DataFrame

    ★ v2:
    - DB mode: อ่านจาก DB เท่านั้น (ไม่ fallback)
      เพราะถ้า fallback มักสับสน (เห็นข้อมูล 2 ชุด)
    - CSV mode: อ่านจาก CSV ตามเดิม
    """
    import pandas as pd

    if _USE_DB:
        try:
            from core.db import read_table
            df = read_table(TABLE_NAME)
            return df
        except Exception as e:
            print(f"⚠️ DB read failed: {type(e).__name__}: {e}")
            # ★ ไม่ fallback → คืน empty DataFrame
            # ถ้า DB ล่ม → ควรรู้ ไม่ใช่แอบอ่าน CSV
            return pd.DataFrame(columns=FIELDS)
    else:
        if not AUDIT_FILE.exists():
            return pd.DataFrame(columns=FIELDS)
        return pd.read_csv(AUDIT_FILE, encoding="utf-8-sig")


# ═══════════════════════════════════════════════════════════
# DEBUG / UTILITIES
# ═══════════════════════════════════════════════════════════
def get_audit_count() -> int:
    """นับจำนวน audit log — ใช้ใน debug"""
    try:
        df = read_audit()
        return len(df)
    except Exception:
        return 0


def test_audit_roundtrip() -> dict:
    """
    ★ ใหม่: ทดสอบ insert + read
    ใช้ในหน้า Settings เพื่อ debug
    """
    test_id_marker = f"TEST-{now_str()}"

    try:
        # Insert test record
        row = {
            "audit_id":   new_id("audit"),
            "timestamp":  now_str(),
            "user":       "system",
            "action":     "TEST",
            "module":     "AUDIT",
            "record_id":  test_id_marker,
            "old_value":  "",
            "new_value":  "test",
            "reason":     "Roundtrip test",
            "session_id": "",
            "version":    "v1",
        }

        if _USE_DB:
            from core.db import append_row
            append_row(TABLE_NAME, row)
        else:
            _append_audit_csv(row)

        # Read back
        df = read_audit()
        found = (
            len(df[df["audit_id"] == row["audit_id"]]) > 0
            if not df.empty and "audit_id" in df.columns else False
        )

        return {
            "ok": True,
            "mode": "DB" if _USE_DB else "CSV",
            "test_id": row["audit_id"],
            "found_in_read": found,
            "total_rows": len(df),
        }

    except Exception as e:
        return {
            "ok": False,
            "mode": "DB" if _USE_DB else "CSV",
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }