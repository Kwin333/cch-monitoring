"""
Sync Timeline 261014 — อัปเดต Supabase ให้ตรงกับ EXAT CCH Timeline v9

ทำ 3 อย่าง:
1. UPDATE status ของ deliverables ที่มีอยู่ (ตาม Excel)
2. UPDATE planned_start/planned_finish ที่เปลี่ยนแปลง
3. ADD deliverables ใหม่ (1.1 sign off, 1.5 Interview, 1.6.x, Monthly Reports)

⚠️ ไม่ลบข้อมูลที่มีอยู่ — เฉพาะ update/add
"""
import os
import sys
from pathlib import Path
from datetime import date

import pandas as pd
from sqlalchemy import create_engine, text


# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
DATABASE_URL = (
    "postgresql+psycopg2://postgres.ttglehyfuwxhoojlkded:"
    "84fey%2FYb_zNUHii@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
)

DRY_RUN = False  # True = แค่แสดงรายการ ไม่แก้อะไร


# ═══════════════════════════════════════════════════════════
# ข้อมูลจาก Excel — UPDATE
# ═══════════════════════════════════════════════════════════
# status_map: deliverable_id → (status, planned_start, planned_finish)
STATUS_UPDATES = {
    # ═══ M1 — เสร็จสิ้นทั้งหมด ═══
    "DLV-M1-01": ("Accepted", "2026-08-18", "2026-08-18"),
    "DLV-M1-02": ("Accepted", "2026-08-18", "2026-08-21"),
    "DLV-M1-03": ("Accepted", "2026-08-18", "2026-08-21"),
    "DLV-M1-04": ("Accepted", "2026-08-18", "2026-08-21"),
    "DLV-M1-05": ("Accepted", "2026-08-18", "2026-10-31"),  # 1.5 Interview → Oct
    "DLV-M1-06": ("Accepted", "2026-08-18", "2026-10-31"),
    "DLV-M1-07": ("Accepted", "2026-08-18", "2026-10-31"),
    "DLV-M1-08": ("Accepted", "2026-08-18", "2026-10-31"),
    "DLV-M1-09": ("Accepted", "2026-08-18", "2026-10-31"),
    "DLV-M1-10": ("Accepted", "2026-08-18", "2026-10-31"),
    "DLV-M1-11": ("Accepted", "2026-08-18", "2026-08-31"),
    "DLV-M1-12": ("Accepted", "2026-08-18", "2026-08-31"),
    "DLV-M1-13": ("Accepted", "2026-08-18", "2026-08-31"),
    "DLV-M1-14": ("Accepted", "2026-08-18", "2026-08-31"),
    "DLV-M1-15": ("Accepted", "2026-08-18", "2026-08-21"),
    "DLV-M1-16": ("Accepted", "2026-08-21", "2026-08-31"),
    "DLV-M1-17": ("Accepted", "2026-08-31", "2026-08-31"),
    "DLV-M1-18": ("Accepted", "2026-09-01", "2026-09-01"),

    # ═══ M2 — ส่วนใหญ่ รอ / 2.3 & 2.12 = In Progress ═══
    "DLV-M2-01": ("Not Started", "2026-10-08", "2026-11-30"),
    "DLV-M2-02": ("Not Started", "2026-10-08", "2026-11-21"),
    "DLV-M2-03": ("In Progress",  "2026-10-08", "2026-11-30"),  # กำลังดำเนินการ
    "DLV-M2-04": ("Not Started", "2026-10-08", "2026-11-30"),
    "DLV-M2-05": ("Not Started", "2026-10-08", "2026-11-30"),
    "DLV-M2-06": ("Not Started", "2026-10-22", "2026-12-04"),
    "DLV-M2-07": ("Not Started", "2026-10-22", "2026-12-04"),
    "DLV-M2-08": ("Not Started", "2026-11-08", "2026-12-04"),
    "DLV-M2-09": ("Not Started", "2026-09-01", "2026-11-30"),
    "DLV-M2-10": ("Not Started", "2026-09-01", "2026-11-30"),
    "DLV-M2-11": ("Not Started", "2026-10-08", "2026-12-14"),
    "DLV-M2-12": ("In Progress",  "2026-08-18", "2026-10-15"),  # กำลังดำเนินการ
    "DLV-M2-13": ("Not Started", "2026-09-30", "2026-10-31"),
    "DLV-M2-14": ("Not Started", "2026-12-06", "2026-12-06"),
    "DLV-M2-15": ("Not Started", "2026-12-08", "2026-12-16"),
    "DLV-M2-16": ("Not Started", "2026-12-16", "2026-12-16"),
    "DLV-M2-17": ("Not Started", "2026-12-17", "2026-12-25"),
}


# ═══════════════════════════════════════════════════════════
# ข้อมูลจาก Excel — ADD NEW
# ═══════════════════════════════════════════════════════════
# ใช้ ID ใหม่: DLV-M1-19, DLV-M2-18..27 เพื่อไม่ทับ
NEW_DELIVERABLES = [
    # ═══ 1.1 Contract sign off (M1) ═══
    {
        "deliverable_id": "DLV-M1-19",
        "milestone_id": "MLS-01",
        "tor_clause": "-",
        "deliverable_name": "1.1 Contract Sign Off (ลงนามสัญญา)",
        "description": "ลงนามสัญญาของโปรเจค",
        "required_output": "Signed Contract",
        "required_evidence": "CONTRACT-SIGN",
        "weight": 0.3,
        "planned_start": "2026-08-17",
        "planned_finish": "2026-08-17",
        "status": "Accepted",
    },
    # ═══ 1.5 Interview Overview (M1) — refactored ═══
    {
        "deliverable_id": "DLV-M1-20",
        "milestone_id": "MLS-01",
        "tor_clause": "4.1.1",
        "deliverable_name": "1.5 Interview Overview 10 Departments",
        "description": "Overall interview 10 departments before individual interview",
        "required_output": "Overview Notes",
        "required_evidence": "INT-OVERVIEW-M1",
        "weight": 0.3,
        "planned_start": "2026-08-18",
        "planned_finish": "2026-10-31",
        "status": "Accepted",
    },
    # ═══ 1.6.x Interview 10 Depts (M2) ═══
    {"deliverable_id": "DLV-M2-18", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6 Interview 10 Departments (Overall)",
     "description": "นัดสัมภาษณ์แยกแต่ละหน่วยงาน รวม 10 แห่ง",
     "required_output": "Interview Plan", "required_evidence": "INT-PLAN",
     "weight": 0.3, "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-19", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6.1 สัมภาษณ์ฝ่ายพัฒนาธุรกิจ (ฝพธ.)",
     "description": "สัมภาษณ์แยกแต่ละหน่วยงาน", "required_output": "Interview Notes",
     "required_evidence": "INT-DEV-M2", "weight": 0.5,
     "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-20", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6.2 สำนักตรวจสอบภายใน (สตส.)",
     "description": "สัมภาษณ์แยกแต่ละหน่วยงาน", "required_output": "Interview Notes",
     "required_evidence": "INT-IA-M2", "weight": 0.5,
     "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-21", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6.3 ฝ่ายเจ้าหน้าที่ DPO",
     "description": "สัมภาษณ์แยกแต่ละหน่วยงาน", "required_output": "Interview Notes",
     "required_evidence": "INT-DPO-M2", "weight": 0.5,
     "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-22", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6.4 ฝ่ายบำรุงรักษา (ฝบร./กบร.)",
     "description": "สัมภาษณ์แยกแต่ละหน่วยงาน", "required_output": "Interview Notes",
     "required_evidence": "INT-MTN-M2", "weight": 0.5,
     "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-23", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6.5 ฝ่ายกฎหมาย (ฝกม.)",
     "description": "สัมภาษณ์แยกแต่ละหน่วยงาน", "required_output": "Interview Notes",
     "required_evidence": "INT-LEGAL-M2", "weight": 0.5,
     "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-24", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6.6 ฝ่ายการเงิน (ฝกง.)",
     "description": "สัมภาษณ์แยกแต่ละหน่วยงาน (รายได้+บัญชี)",
     "required_output": "Interview Notes", "required_evidence": "INT-FIN-M2",
     "weight": 0.5, "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-25", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6.7 ฝ่ายทรัพยากรบุคคล (ฝทบ.)",
     "description": "สัมภาษณ์แยกแต่ละหน่วยงาน", "required_output": "Interview Notes",
     "required_evidence": "INT-HR-M2", "weight": 0.5,
     "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-26", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6.8 ฝ่ายยุทธศาสตร์ (ฝยป./กบค.)",
     "description": "สัมภาษณ์แยกแต่ละหน่วยงาน", "required_output": "Interview Notes",
     "required_evidence": "INT-STR-M2", "weight": 0.5,
     "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-27", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6.9 ฝ่ายดิจิทัล 1 (ฝดท.1)",
     "description": "สัมภาษณ์แยกแต่ละหน่วยงาน", "required_output": "Interview Notes",
     "required_evidence": "INT-DT1-M2", "weight": 0.5,
     "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-28", "milestone_id": "MLS-02",
     "tor_clause": "4.1.1",
     "deliverable_name": "1.6.10 ฝ่ายดิจิทัล 2 (ฝดท.2)",
     "description": "สัมภาษณ์แยกแต่ละหน่วยงาน (IT+Network+Security)",
     "required_output": "Interview Notes", "required_evidence": "INT-DT2-M2",
     "weight": 0.5, "planned_start": "2026-10-19", "planned_finish": "2026-10-31",
     "status": "Not Started"},
    # ═══ Monthly Reports ═══
    {"deliverable_id": "DLV-M2-29", "milestone_id": "MLS-02",
     "tor_clause": "-",
     "deliverable_name": "📅 Monthly Report — ตุลาคม 69",
     "description": "รายงานอัพเดตความคืบหน้ารายเดือนตุลาคม",
     "required_output": "Monthly Report", "required_evidence": "MR-OCT-69",
     "weight": 0.25, "planned_start": "2026-11-02", "planned_finish": "2026-11-02",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M2-30", "milestone_id": "MLS-02",
     "tor_clause": "-",
     "deliverable_name": "📅 Monthly Report — พฤศจิกายน 69",
     "description": "รายงานอัพเดตความคืบหน้ารายเดือนพฤศจิกายน",
     "required_output": "Monthly Report", "required_evidence": "MR-NOV-69",
     "weight": 0.25, "planned_start": "2026-11-30", "planned_finish": "2026-11-30",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M3-20", "milestone_id": "MLS-03",
     "tor_clause": "-",
     "deliverable_name": "📅 Monthly Report — มกราคม 70",
     "description": "รายงานอัพเดตความคืบหน้ารายเดือนมกราคม",
     "required_output": "Monthly Report", "required_evidence": "MR-JAN-70",
     "weight": 0.25, "planned_start": "2027-01-29", "planned_finish": "2027-01-29",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M4-17", "milestone_id": "MLS-04",
     "tor_clause": "-",
     "deliverable_name": "📅 Monthly Report — มีนาคม 70",
     "description": "รายงานอัพเดตความคืบหน้ารายเดือนมีนาคม",
     "required_output": "Monthly Report", "required_evidence": "MR-MAR-70",
     "weight": 0.25, "planned_start": "2027-03-31", "planned_finish": "2027-03-31",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M4-18", "milestone_id": "MLS-04",
     "tor_clause": "-",
     "deliverable_name": "📅 Monthly Report — เมษายน 70",
     "description": "รายงานอัพเดตความคืบหน้ารายเดือนเมษายน",
     "required_output": "Monthly Report", "required_evidence": "MR-APR-70",
     "weight": 0.25, "planned_start": "2027-04-30", "planned_finish": "2027-04-30",
     "status": "Not Started"},
    {"deliverable_id": "DLV-M4-19", "milestone_id": "MLS-04",
     "tor_clause": "-",
     "deliverable_name": "📅 Monthly Report — พฤษภาคม 70",
     "description": "รายงานอัพเดตความคืบหน้ารายเดือนพฤษภาคม",
     "required_output": "Monthly Report", "required_evidence": "MR-MAY-70",
     "weight": 0.25, "planned_start": "2027-05-31", "planned_finish": "2027-05-31",
     "status": "Not Started"},
]


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    print(f"🔌 Connecting to Supabase...")
    engine = create_engine(DATABASE_URL)

    # ---- 1. UPDATE existing ----
    print(f"\n📝 Updating {len(STATUS_UPDATES)} deliverables...")
    updated = 0
    for did, (status, ps, pf) in STATUS_UPDATES.items():
        sql = text("""
            UPDATE "deliverable_master"
            SET status = :status,
                planned_start = :ps,
                planned_finish = :pf,
                updated_at = NOW()::text
            WHERE deliverable_id = :did
        """)
        try:
            with engine.begin() as conn:
                res = conn.execute(sql, {
                    "status": status, "ps": ps, "pf": pf, "did": did,
                })
                if res.rowcount > 0:
                    updated += 1
                    print(f"   ✅ {did} → {status}")
                else:
                    print(f"   ⚠️ {did} not found")
        except Exception as e:
            print(f"   ❌ {did}: {type(e).__name__}: {e}")

    # ---- 2. INSERT new ----
    print(f"\n➕ Adding {len(NEW_DELIVERABLES)} new deliverables...")
    added = 0
    for d in NEW_DELIVERABLES:
        row = {
            "deliverable_id": d["deliverable_id"],
            "milestone_id":   d["milestone_id"],
            "tor_clause":     d["tor_clause"],
            "deliverable_name": d["deliverable_name"],
            "description":    d["description"],
            "required_output": d["required_output"],
            "required_evidence": d["required_evidence"],
            "weight":         d["weight"],
            "planned_start":  d["planned_start"],
            "planned_finish": d["planned_finish"],
            "actual_start":   "",
            "actual_finish":  "",
            "status":         d["status"],
            "compliance_status": "Not Checked",
            "reviewer":       "",
            "review_date":    "",
            "review_comment": "",
            "updated_at":     "",
        }
        # ใช้ ON CONFLICT เพื่อความปลอดภัย
        cols = list(row.keys())
        placeholders = ", ".join([f":{c}" for c in cols])
        col_names = ", ".join([f'"{c}"' for c in cols])
        update_set = ", ".join(
            [f'"{c}" = EXCLUDED."{c}"' for c in cols
             if c != "deliverable_id"]
        )
        sql = text(f"""
            INSERT INTO "deliverable_master" ({col_names})
            VALUES ({placeholders})
            ON CONFLICT ("deliverable_id") DO UPDATE SET {update_set}
        """)
        try:
            with engine.begin() as conn:
                conn.execute(sql, row)
                added += 1
                print(f"   ✅ {d['deliverable_id']}: {d['deliverable_name'][:50]}")
        except Exception as e:
            print(f"   ❌ {d['deliverable_id']}: {type(e).__name__}: {e}")

    # ---- 3. Summary ----
    print(f"\n{'='*60}")
    print(f"🎉 Sync complete!")
    print(f"   Updated: {updated} / {len(STATUS_UPDATES)}")
    print(f"   Added:   {added} / {len(NEW_DELIVERABLES)}")

    # ---- 4. Verify ----
    print(f"\n📊 Verify counts:")
    with engine.connect() as conn:
        total = conn.execute(
            text('SELECT COUNT(*) FROM "deliverable_master"')
        ).scalar()
        accepted = conn.execute(
            text('SELECT COUNT(*) FROM "deliverable_master" WHERE status = \'Accepted\'')
        ).scalar()
        in_prog = conn.execute(
            text('SELECT COUNT(*) FROM "deliverable_master" WHERE status = \'In Progress\'')
        ).scalar()
        print(f"   Total:       {total}")
        print(f"   Accepted:    {accepted}")
        print(f"   In Progress: {in_prog}")


if __name__ == "__main__":
    main()