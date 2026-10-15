"""
Backfill progress_history — สร้าง progress snapshots ให้ M1 ที่ Accepted แล้ว
รันครั้งเดียวหลัง Reseed
"""
from sqlalchemy import create_engine, text

DATABASE_URL = (
    "postgresql+psycopg2://postgres.ttglehyfuwxhoojlkded:"
    "84fey%2FYb_zNUHii@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
)


def main():
    engine = create_engine(DATABASE_URL)

    # 1. ลบ test progress เก่าของ M1 ทั้งหมด (ถ้ามี)
    with engine.begin() as conn:
        result = conn.execute(text("""
            DELETE FROM "progress_history"
            WHERE deliverable_id LIKE 'DLV-M1-%'
        """))
        print(f"🗑️  Deleted old M1 progress: {result.rowcount} rows")

    # 2. ดึง M1 deliverables ทั้งหมด
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT deliverable_id, milestone_id, tor_clause,
                   planned_start, planned_finish,
                   weight, status
            FROM "deliverable_master"
            WHERE milestone_id = 'MLS-01'
            ORDER BY deliverable_id
        """)).fetchall()

    print(f"📋 Found {len(rows)} M1 deliverables")

    # 3. Insert progress 100% สำหรับ Accepted
    inserted = 0
    for row in rows:
        (did, mid, tor, ps, pf, w, status) = row
        if status != "Accepted":
            continue

        actual = 100.0
        planned = 100.0

        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO "progress_history" (
                    "timestamp", "progress_id", "project_id",
                    "milestone_id", "deliverable_id", "tor_clause",
                    "update_date", "reporting_period",
                    "planned_percent", "actual_percent", "progress_delta",
                    "status", "progress_description",
                    "evidence_reference", "evidence_type",
                    "issue_flag", "risk_level", "action_required",
                    "action_owner", "action_due_date",
                    "meeting_reference", "resolution_reference",
                    "reviewer", "review_date", "review_status", "review_comment",
                    "created_by", "version_no"
                ) VALUES (
                    :ts, :pid, :proj, :mid, :did, :tor,
                    :upd, :period,
                    :planned, :actual, :delta,
                    'Accepted', :desc,
                    :evi, 'Report',
                    'No', 'Low', '', '', '',
                    '', '',
                    'admin', :upd, 'Approved', 'Backfill from Timeline 261014',
                    'admin', 'v1'
                )
            """), {
                "ts": f"{pf} 09:00:00",
                "pid": f"PRG-BACKFILL-{did[-7:]}",
                "proj": "PRJ-2026-0001",
                "mid": mid, "did": did, "tor": tor,
                "upd": pf, "period": str(pf)[:7],
                "planned": planned, "actual": actual, "delta": 0.0,
                "desc": f"ปิดงานตามกำหนด — Backfill จาก Timeline 261014",
                "evi": f"BACKFILL-{did}",
            })
            inserted += 1
            print(f"   ✅ {did}: 100%")

    print(f"\n🎉 Backfilled {inserted} progress records")


if __name__ == "__main__":
    main()