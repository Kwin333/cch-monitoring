"""
core/db.py — Database connection layer for Supabase (PostgreSQL)
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
# READ
# ═══════════════════════════════════════════════════════════
def read_table(table_name: str, filters: dict = None) -> pd.DataFrame:
    """อ่าน table → DataFrame"""
    engine = get_engine()

    if filters:
        where_clauses = []
        params = {}
        for i, (col, val) in enumerate(filters.items()):
            key = f"p{i}"
            where_clauses.append(f"{col} = :{key}")
            params[key] = val
        where_sql = " WHERE " + " AND ".join(where_clauses)
        sql = f"SELECT * FROM {table_name}{where_sql}"
        return pd.read_sql(sql, engine, params=params)
    else:
        return pd.read_sql(f"SELECT * FROM {table_name}", engine)


def read_sql(query: str, params: dict = None) -> pd.DataFrame:
    """อ่านด้วย raw SQL"""
    engine = get_engine()
    return pd.read_sql(query, engine, params=params or {})


# ═══════════════════════════════════════════════════════════
# WRITE — UPSERT
# ═══════════════════════════════════════════════════════════
def upsert_row(table_name: str, row: dict, pk_col: str):
    """เพิ่มหรือแก้ไข 1 row"""
    engine = get_engine()

    cols = list(row.keys())
    placeholders = ", ".join([f":{c}" for c in cols])
    col_names = ", ".join(cols)
    update_set = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols if c != pk_col])

    sql = text(f"""
        INSERT INTO {table_name} ({col_names})
        VALUES ({placeholders})
        ON CONFLICT ({pk_col}) DO UPDATE SET {update_set}
    """)

    with engine.begin() as conn:
        conn.execute(sql, row)


def append_row(table_name: str, row: dict):
    """Append 1 row (สำหรับ history tables)"""
    engine = get_engine()

    cols = list(row.keys())
    placeholders = ", ".join([f":{c}" for c in cols])
    col_names = ", ".join(cols)

    sql = text(f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})")

    with engine.begin() as conn:
        conn.execute(sql, row)


def delete_row(table_name: str, pk_col: str, pk_value: str):
    """ลบ 1 row ตาม PK"""
    engine = get_engine()
    sql = text(f"DELETE FROM {table_name} WHERE {pk_col} = :pk")
    with engine.begin() as conn:
        conn.execute(sql, {"pk": pk_value})


# ═══════════════════════════════════════════════════════════
# RAW EXECUTE
# ═══════════════════════════════════════════════════════════
def execute_sql(query: str, params: dict = None):
    """Execute SQL ที่ไม่คืนค่า"""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(query), params or {})