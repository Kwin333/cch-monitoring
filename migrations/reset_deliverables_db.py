"""
Reset deliverable_master + progress_history ใน Supabase
ด้วยข้อมูลใหม่จาก bootstrap.DELIVERABLES_FULL (ID ตาม Excel)

⚠️ ลบข้อมูลเดิมทั้งหมดใน 2 ตารางนี้
   ตารางอื่น (meeting, issue, action, acceptance, payment) ไม่แตะ

Usage:
  python migrations/reset_deliverables_db.py             # Dry-run
  python migrations/reset_deliverables_db.py --execute   # ทำจริง
"""
import sys
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
DATABASE_URL = (
    "postgresql+psycopg2://postgres.ttglehyfuwxhoojlkded:"
    "84fey%2FYb_zNUHii@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
)

BACKUP_DIR = Path(__file__).parent.parent / "data" / "backup" / "reset_db"


def _q(name):
    return f'"{name}"'


def print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def backup_table(engine, table: str) -> Path:
    """Dump table → JSON"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = BACKUP_DIR / f"{table}_{stamp}.json"

    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT * FROM {_q(table)}")).fetchall()
        cols = conn.execute(text(f"SELECT * FROM {_q(table)} LIMIT 0")).keys()

    data = {
        "table": table,
        "timestamp": stamp,
        "columns": list(cols),
        "rows": [list(r) for r in rows],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str, indent=2)

    print(f"  💾 Backup {table}: {len(rows)} rows → {path.name}")
    return path


def main():
    dry_run = "--execute" not in sys.argv

    print_header(f"Reset Deliverable Master — {'DRY RUN' if dry_run else 'EXECUTE'}")

    # ★ Import bootstrap data
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from bootstrap import (
        DELIVERABLES_FULL,
        normalize_deliverable_weights,
    )

    # ★ Normalize weights
    normalized = normalize_deliverable_weights(
        DELIVERABLES_FULL, target_total=100.0, round_to=2
    )
    total_w = sum(d["weight"] for d in normalized)

    print(f"\n📊 ข้อมูลใหม่จาก bootstrap.py:")
    print(f"   • จำนวน deliverables: {len(normalized)}")
    print(f"   • Weight รวม: {total_w:.2f}%")
    print(f"   • M1: {sum(1 for d in normalized if d['ms'] == 'MLS-01')} items")
    print(f"   • M2: {sum(1 for d in normalized if d['ms'] == 'MLS-02')} items")
    print(f"   • M3: {sum(1 for d in normalized if d['ms'] == 'MLS-03')} items")
    print(f"   • M4: {sum(1 for d in normalized if d['ms'] == 'MLS-04')} items")
    print(f"   • M5: {sum(1 for d in normalized if d['ms'] == 'MLS-05')} items")

    # ── Show sample ──
    print(f"\n📋 ตัวอย่าง ID ใหม่ (M1):")
    for d in [x for x in normalized if x["ms"] == "MLS-01"][:5]:
        print(f"   {d['id']:12} · {d['name'][:60]}")

    engine = create_engine(DATABASE_URL)

    # ── Check current state ──
    with engine.connect() as conn:
        old_count = conn.execute(
            text(f'SELECT COUNT(*) FROM {_q("deliverable_master")}')
        ).scalar()
        old_ids = conn.execute(
            text(f'SELECT deliverable_id FROM {_q("deliverable_master")} '
                 f'WHERE milestone_id = \'MLS-01\' ORDER BY deliverable_id')
        ).fetchall()
        old_ids = [r[0] for r in old_ids]

    print(f"\n⚠️  DB ปัจจุบัน: {old_count} deliverables")
    print(f"    M1 IDs: {', '.join(old_ids[:8])}")

    if dry_run:
        print("\n✅ DRY RUN — ไม่มีการเปลี่ยนแปลง")
        print("   รันด้วย --execute เพื่อทำจริง")
        return

    # ═══════════════════════════════════════════════════════
    # BACKUP
    # ═══════════════════════════════════════════════════════
    print_header("BACKUP")
    backup_table(engine, "deliverable_master")
    backup_table(engine, "progress_history")

    # ═══════════════════════════════════════════════════════
    # DELETE old data
    # ═══════════════════════════════════════════════════════
    print_header("DELETE OLD DATA")

    with engine.begin() as conn:
        r1 = conn.execute(
            text(f'DELETE FROM {_q("deliverable_master")}')
        )
        print(f"  🗑️  deliverable_master: {r1.rowcount} rows deleted")

        r2 = conn.execute(
            text(f'DELETE FROM {_q("progress_history")}')
        )
        print(f"  🗑️  progress_history: {r2.rowcount} rows deleted")

    # ═══════════════════════════════════════════════════════
    # INSERT new data
    # ═══════════════════════════════════════════════════════
    print_header("INSERT NEW DATA")

    from collections import defaultdict
    seq_counter = defaultdict(int)

    inserted = 0
    for d in normalized:
        mid = d["ms"]
        seq_counter[mid] += 1
        seq = seq_counter[mid]

        row = {
            "deliverable_id":     d["id"],
            "milestone_id":       mid,
            "tor_clause":         d["tor"],
            "deliverable_name":   d["name"],
            "description":        d["desc"],
            "required_output":    d["output"],
            "required_evidence":  d["evidence"],
            "weight":             d["weight"],
            "planned_start":      d["start"],
            "planned_finish":     d["finish"],
            "actual_start":       d["start"] if d.get("status") == "Accepted" else "",
            "actual_finish":      d["finish"] if d.get("status") == "Accepted" else "",
            "status":             d.get("status", "Not Started"),
            "compliance_status":  "Compliant" if d.get("status") == "Accepted" else "Not Checked",
            "reviewer":           "admin" if d.get("status") == "Accepted" else "",
            "review_date":        "2026-09-01" if d.get("status") == "Accepted" else "",
            "review_comment":     "",
            "updated_at":         "2026-10-14 09:00:00",
            "sequence":           seq,
        }

        cols = list(row.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        col_names = ", ".join(f'"{c}"' for c in cols)

        sql = text(f'INSERT INTO {_q("deliverable_master")} '
                   f'({col_names}) VALUES ({placeholders})')

        try:
            with engine.begin() as conn:
                conn.execute(sql, row)
            inserted += 1
            if inserted % 20 == 0:
                print(f"  ... {inserted}/{len(normalized)}")
        except Exception as e:
            print(f"  ❌ {d['id']}: {type(e).__name__}: {e}")

    print(f"\n  ✅ Inserted: {inserted}/{len(normalized)}")

    # ═══════════════════════════════════════════════════════
    # BACKFILL progress_history for M1 (Accepted)
    # ═══════════════════════════════════════════════════════
    print_header("BACKFILL progress_history (M1)")

    m1_items = [d for d in normalized if d["ms"] == "MLS-01"]
    backfilled = 0

    for d in m1_items:
        if d.get("status") != "Accepted":
            continue

        pf = d["finish"]
        row = {
            "timestamp":            f"{pf} 09:00:00",
            "progress_id":          f"PRG-RESET-{d['id'][-7:]}",
            "project_id":           "PRJ-2026-0001",
            "milestone_id":         d["ms"],
            "deliverable_id":       d["id"],
            "tor_clause":           d["tor"],
            "update_date":          pf,
            "reporting_period":     pf[:7],
            "planned_percent":      100.0,
            "actual_percent":       100.0,
            "progress_delta":       0.0,
            "status":               "Accepted",
            "progress_description": "ปิดงานตามกำหนด — Reset from bootstrap v4",
            "evidence_reference":   f"RESET-{d['id']}",
            "evidence_type":        "Report",
            "issue_flag":           "No",
            "risk_level":           "Low",
            "action_required":      "",
            "action_owner":         "",
            "action_due_date":      "",
            "meeting_reference":    "",
            "resolution_reference": "",
            "reviewer":             "admin",
            "review_date":          pf,
            "review_status":        "Approved",
            "review_comment":       "Reset from bootstrap v4",
            "created_by":           "admin",
            "version_no":           "v1",
        }

        cols = list(row.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        col_names = ", ".join(f'"{c}"' for c in cols)

        sql = text(f'INSERT INTO {_q("progress_history")} '
                   f'({col_names}) VALUES ({placeholders})')

        try:
            with engine.begin() as conn:
                conn.execute(sql, row)
            backfilled += 1
        except Exception as e:
            print(f"  ❌ {d['id']}: {e}")

    print(f"  ✅ Backfilled: {backfilled} progress records")

    # ═══════════════════════════════════════════════════════
    # VERIFY
    # ═══════════════════════════════════════════════════════
    print_header("VERIFY")

    with engine.connect() as conn:
        total = conn.execute(
            text(f'SELECT COUNT(*) FROM {_q("deliverable_master")}')
        ).scalar()
        weight = conn.execute(
            text(f'SELECT ROUND(SUM(weight)::numeric, 2) '
                 f'FROM {_q("deliverable_master")}')
        ).scalar()

        print(f"  📦 Total: {total}")
        print(f"  ⚖️  Weight รวม: {weight}%")

        print(f"\n  📋 M1 (ต้องเริ่มด้วย Contract Sign Off):")
        rows = conn.execute(text(f'''
            SELECT deliverable_id, sequence, deliverable_name
            FROM {_q("deliverable_master")}
            WHERE milestone_id = 'MLS-01'
            ORDER BY sequence
            LIMIT 5
        ''')).fetchall()
        for r in rows:
            print(f"     #{r[1]:>2}  {r[0]}  {r[2][:55]}")

    print("\n🎉 เสร็จสิ้น — รีเฟรชหน้าเว็บ (Ctrl+Shift+R)")


if __name__ == "__main__":
    main()