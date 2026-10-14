"""
Migration Script: Import CSV → Supabase
รันครั้งเดียวเพื่อย้ายข้อมูลจาก CSV ไป Supabase
"""
import os
import pandas as pd
from sqlalchemy import create_engine, text
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# ⚠️ แก้ไขตรงนี้ — ใส่ Connection String ของคุณ
# ═══════════════════════════════════════════════════════════
DATABASE_URL = "postgresql://postgres:84fey%2FYb_zNUHii@db.ttglehyfuwxhoojlkded.supabase.co:5432/postgres"

DATA_DIR = Path(__file__).parent / "data"

# Mapping: CSV file → table name
CSV_TO_TABLE = {
    "master/project_master.csv":              "project_master",
    "master/milestone_master.csv":            "milestone_master",
    "master/deliverable_master.csv":          "deliverable_master",
    "master/personnel_master.csv":            "personnel_master",
    "history/progress_history.csv":           "progress_history",
    "history/meeting_history.csv":            "meeting_history",
    "history/resolution_history.csv":         "resolution_history",
    "history/action_history.csv":             "action_history",
    "history/issue_history.csv":              "issue_history",
    "history/acceptance_history.csv":         "acceptance_history",
    "history/payment_history.csv":            "payment_history",
    "history/deliverable_review_history.csv": "deliverable_review_history",
    "audit/audit_log.csv":                    "audit_log",
    "audit/voided_records.csv":               "voided_records",
}


def migrate():
    engine = create_engine(DATABASE_URL)
    print("🔌 Connected to Supabase")

    for csv_rel, table_name in CSV_TO_TABLE.items():
        csv_path = DATA_DIR / csv_rel
        if not csv_path.exists():
            print(f"⏭️  Skip {csv_rel} (not found)")
            continue

        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            if df.empty:
                print(f"⏭️  Skip {table_name} (empty)")
                continue

            # Import with "if_exists='append'"
            df.to_sql(
                table_name,
                engine,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=500,
            )
            print(f"✅ {table_name}: {len(df)} rows imported")

        except Exception as e:
            print(f"❌ {table_name}: {type(e).__name__}: {e}")

    print("\n🎉 Migration complete!")


if __name__ == "__main__":
    migrate()