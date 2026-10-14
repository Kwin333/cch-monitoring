"""
core/db.py — Database connection layer for Supabase (PostgreSQL)

★ v2:
- Quote column names ด้วย double quotes
  (แก้ bug: "user", "timestamp" เป็น PostgreSQL reserved words)
- Quote table names ด้วย
- เพิ่ม helper functions สำหรับ quoting
"""
import os
from pathlib import Path
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text


# ═══════════════════════════════════════════════════════════
# CONNECTION
# ═══════════════════════════════════════════════════════════
@st.cache_resource
def get_engine():
    """คืน SQLAlchemy engine — cached ต่อ session"""
    try:
        db_url = st.secrets.get("DATABASE_URL")
    except Exception:
        db_url = None

    if not db_url:
        db_url = os.environ.get("DATABASE_URL")

    if not db_url:
        raise RuntimeError(
            "❌ ไม่พบ DATABASE_URL — กรุณาตั้งค่าใน st.secrets หรือ os.environ"
        )

    return create_engine(db_url, pool_pre_ping=True, pool_recycle=300)


# ═══════════════════════════════════════════════════════════
# ★ HELPER: Quote identifiers (แก้ reserved words)
# ═══════════════════════════════════════════════════════════
def _q(name: str) -> str:
    """
    Quote identifier ด้วย double quotes
    
    PostgreSQL reserved words เช่น "user", "timestamp", "order"
    ต้อง quote เสมอ
    
    ตัวอย่าง:
        _q("user")      → '"user"'
        _q("audit_log") → '"audit_log"'
    """
    return f'"{name}"'


def _quote_cols(cols: list) -> str:
    """Quote list ของ columns → `"col1", "col2", ...`"""
    return ", ".join([_q(c) for c in cols])


# ═══════════════════════════════════════════════════════════
# READ
# ═══════════════════════════════════════════════════════════
def read_table(table_name: str, filters: dict = None) -> pd.DataFrame:
    """อ่าน table → DataFrame"""
    engine = get_engine()
    t = _q(table_name)

    if filters:
        where_clauses = []
        params = {}
        for i, (col, val) in enumerate(filters.items()):
            key = f"p{i}"
            where_clauses.append(f"{_q(col)} = :{key}")
            params[key] = val
        where_sql = " WHERE " + " AND ".join(where_clauses)
        sql = f"SELECT * FROM {t}{where_sql}"
        return pd.read_sql(sql, engine, params=params)
    else:
        return pd.read_sql(f"SELECT * FROM {t}", engine)


def read_sql(query: str, params: dict = None) -> pd.DataFrame:
    """อ่านด้วย raw SQL (ผู้ใช้ต้อง quote เองถ้าจำเป็น)"""
    engine = get_engine()
    return pd.read_sql(query, engine, params=params or {})


# ═══════════════════════════════════════════════════════════
# WRITE — UPSERT (INSERT or UPDATE)
# ═══════════════════════════════════════════════════════════
def upsert_row(table_name: str, row: dict, pk_col: str):
    """
    เพิ่มหรือแก้ไข 1 row
    
    ★ v2: Quote ทุก identifier (table, column, pk) เพื่อรองรับ reserved words
    """
    engine = get_engine()

    cols = list(row.keys())
    col_names = _quote_cols(cols)
    placeholders = ", ".join([f":{c}" for c in cols])
    update_set = ", ".join(
        [f"{_q(c)} = EXCLUDED.{_q(c)}" for c in cols if c != pk_col]
    )

    sql = text(f"""
        INSERT INTO {_q(table_name)} ({col_names})
        VALUES ({placeholders})
        ON CONFLICT ({_q(pk_col)}) DO UPDATE SET {update_set}
    """)

    with engine.begin() as conn:
        conn.execute(sql, row)


def append_row(table_name: str, row: dict):
    """
    Append 1 row (สำหรับ history tables)
    
    ★ v2: Quote ทุก identifier
    แก้ bug: "INSERT INTO audit_log (user, timestamp, ...)" 
             → "user" และ "timestamp" เป็น reserved words → error
    
    ตอนนี้: "INSERT INTO "audit_log" ("audit_id", "user", "timestamp", ...)"
    """
    engine = get_engine()

    cols = list(row.keys())
    col_names = _quote_cols(cols)
    placeholders = ", ".join([f":{c}" for c in cols])

    sql = text(
        f'INSERT INTO {_q(table_name)} ({col_names}) VALUES ({placeholders})'
    )

    with engine.begin() as conn:
        conn.execute(sql, row)


def delete_row(table_name: str, pk_col: str, pk_value: str):
    """ลบ 1 row ตาม PK — ★ v2: quote identifiers"""
    engine = get_engine()
    sql = text(
        f"DELETE FROM {_q(table_name)} WHERE {_q(pk_col)} = :pk"
    )
    with engine.begin() as conn:
        conn.execute(sql, {"pk": pk_value})


# ═══════════════════════════════════════════════════════════
# RAW EXECUTE (สำหรับ complex queries)
# ═══════════════════════════════════════════════════════════
def execute_sql(query: str, params: dict = None):
    """Execute SQL ที่ไม่คืนค่า (INSERT/UPDATE/DELETE)"""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(query), params or {})


# ═══════════════════════════════════════════════════════════
# DEBUG HELPERS
# ═══════════════════════════════════════════════════════════
def test_connection() -> dict:
    """
    ทดสอบ connection — คืนข้อมูลว่าเชื่อมต่อได้หรือไม่
    ใช้ในหน้า Settings เพื่อ debug
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT current_user, current_database(), version()")
            ).fetchone()
            return {
                "ok": True,
                "user": result[0],
                "database": result[1],
                "version": result[2][:80],
            }
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }


def count_rows(table_name: str) -> int:
    """นับจำนวน rows ใน table — ใช้ debug"""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT COUNT(*) FROM {_q(table_name)}")
            ).scalar()
            return int(result)
    except Exception:
        return -1