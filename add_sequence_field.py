"""
เพิ่ม column 'sequence' ให้ deliverable_master + อัปเดตค่าตาม Excel
รันครั้งเดียว — ปลอดภัย ไม่ลบข้อมูลเดิม
"""
from sqlalchemy import create_engine, text

DATABASE_URL = (
    "postgresql+psycopg2://postgres.ttglehyfuwxhoojlkded:"
    "84fey%2FYb_zNUHii@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
)

# ═══════════════════════════════════════════════════════════
# SEQUENCE ตาม Excel (เลข row ที่ผู้ใช้อัปเดต)
# ═══════════════════════════════════════════════════════════
SEQUENCE_MAP = {
    # ── M1 (#1–14) ──
    "DLV-M1-19": 1,   # 1.1 Contract sign off (17 ส.ค.69)  ← ต้องเป็น "แรก" ของ M1
    "DLV-M1-01": 2,   # 1.1 Kick-off Meeting
    "DLV-M1-02": 3,   # 1.2 Project Charter
    "DLV-M1-03": 4,   # 1.3 Project Timeline
    "DLV-M1-04": 5,   # 1.4 Org Chart
    "DLV-M1-05": 6,   # 1.5 Interview Overview 10 Depts
    "DLV-M1-11": 7,   # 1.11 Compliance Advisory
    "DLV-M1-12": 8,   # 1.12 Initial Governance Review
    "DLV-M1-13": 9,   # 1.13 Business Assumptions
    "DLV-M1-14": 10,  # 1.14 Monitoring Framework
    "DLV-M1-15": 11,  # ▶ ส่ง(ร่าง) Inception
    "DLV-M1-16": 12,  # ▶ ปรับปรุง Inception
    "DLV-M1-17": 13,  # 🎯 Submit Inception Report
    "DLV-M1-18": 14,  # 👥 ประชุมตรวจรับ Inception

    # ── M2 (#15–43) ──
    "DLV-M2-18": 15,  # 1.6 Interview 10 Depts (Overall)
    "DLV-M2-19": 16,  # 1.6.1
    "DLV-M2-20": 17,  # 1.6.2
    "DLV-M2-21": 18,  # 1.6.3
    "DLV-M2-22": 19,  # 1.6.4
    "DLV-M2-23": 20,  # 1.6.5
    "DLV-M2-24": 21,  # 1.6.6
    "DLV-M2-25": 22,  # 1.6.7
    "DLV-M2-26": 23,  # 1.6.8
    "DLV-M2-27": 24,  # 1.6.9
    "DLV-M2-28": 25,  # 1.6.10
    "DLV-M2-29": 26,  # Monthly Report ต.ค.
    "DLV-M2-01": 27,  # 2.1 CCH Workflow
    "DLV-M2-02": 28,  # 2.2 Risk Assessment
    "DLV-M2-03": 29,  # 2.3 SOPs
    "DLV-M2-04": 30,  # 2.4 Data Retention
    "DLV-M2-05": 31,  # 2.5 Compliance Roadmap
    "DLV-M2-30": 32,  # Monthly Report พ.ย.
    "DLV-M2-06": 33,  # 2.6 Source of Fund
    "DLV-M2-07": 34,  # 2.7 E-Wallet Design
    "DLV-M2-08": 35,  # 2.8 Workshops
    "DLV-M2-09": 36,  # 2.9 Org Structure Draft
    "DLV-M2-10": 37,  # 2.10 Business Model
    "DLV-M2-11": 38,  # 2.11 Daily Transaction
    "DLV-M2-12": 39,  # 2.12 PF License Package
    "DLV-M2-13": 40,  # 2.13 PF License Submit
    "DLV-M2-14": 41,  # ▶ ส่ง(ร่าง) Progress I
    "DLV-M2-15": 42,  # ▶ ปรับปรุง
    "DLV-M2-16": 43,  # 🎯 Submit
    "DLV-M2-17": 44,  # 👥 ประชุมตรวจรับ

    # ── M3 (#44–63) ──
    "DLV-M3-01": 45,
    "DLV-M3-02": 46,
    "DLV-M3-03": 47,
    "DLV-M3-04": 48,
    "DLV-M3-20": 49,  # Monthly Report ม.ค.
    "DLV-M3-05": 50,
    "DLV-M3-06": 51,
    "DLV-M3-07": 52,
    "DLV-M3-08": 53,
    "DLV-M3-09": 54,
    "DLV-M3-10": 55,
    "DLV-M3-11": 56,
    "DLV-M3-12": 57,
    "DLV-M3-13": 58,
    "DLV-M3-14": 59,
    "DLV-M3-15": 60,
    "DLV-M3-16": 61,
    "DLV-M3-17": 62,
    "DLV-M3-18": 63,
    "DLV-M3-19": 64,

    # ── M4 (#64–82) ──
    "DLV-M4-01": 65,
    "DLV-M4-02": 66,
    "DLV-M4-03": 67,
    "DLV-M4-17": 68,  # Monthly Report มี.ค.
    "DLV-M4-04": 69,
    "DLV-M4-05": 70,
    "DLV-M4-06": 71,
    "DLV-M4-07": 72,
    "DLV-M4-18": 73,  # Monthly Report เม.ย.
    "DLV-M4-08": 74,
    "DLV-M4-09": 75,
    "DLV-M4-10": 76,
    "DLV-M4-19": 77,  # Monthly Report พ.ค.
    "DLV-M4-11": 78,
    "DLV-M4-12": 79,
    "DLV-M4-13": 80,
    "DLV-M4-14": 81,
    "DLV-M4-15": 82,
    "DLV-M4-16": 83,

    # ── M5 (#83–94) ──
    "DLV-M5-01": 84,
    "DLV-M5-02": 85,
    "DLV-M5-03": 86,
    "DLV-M5-04": 87,
    "DLV-M5-05": 88,
    "DLV-M5-06": 89,
    "DLV-M5-07": 90,
    "DLV-M5-08": 91,
    "DLV-M5-09": 92,
    "DLV-M5-10": 93,
    "DLV-M5-11": 94,
    "DLV-M5-12": 95,
}

# ═══════════════════════════════════════════════════════════
# WEIGHT CORRECTIONS (ตาม Excel)
# ═══════════════════════════════════════════════════════════
WEIGHT_FIX = {
    "DLV-M2-18": 0.0,   # Excel ระบุ "-" → ใช้ 0
    "DLV-M2-19": 0.5,
    "DLV-M2-20": 0.5,
    "DLV-M2-21": 0.5,
    "DLV-M2-22": 0.5,
    "DLV-M2-23": 0.5,
    "DLV-M2-24": 0.5,
    "DLV-M2-25": 0.5,
    "DLV-M2-26": 0.5,
    "DLV-M2-27": 0.5,
    "DLV-M2-28": 0.5,
}

# ═══════════════════════════════════════════════════════════
# MISSING DELIVERABLES ที่ต้องเพิ่ม (ถ้ายังไม่มี)
# ═══════════════════════════════════════════════════════════
MISSING = [
    # ── M1 ──
    {
        "deliverable_id": "DLV-M1-19",
        "milestone_id": "MLS-01",
        "tor_clause": "-",
        "deliverable_name": "1.1 Contract Sign Off (ลงนามสัญญา)",
        "description": "ลงนามสัญญาของโปรเจค",
        "required_output": "Signed Contract",
        "required_evidence": "CONTRACT-SIGN",
        "weight": 0.0,
        "planned_start": "2026-08-17",
        "planned_finish": "2026-08-17",
        "status": "Accepted",
    },
    {
        "deliverable_id": "DLV-M1-20",
        "milestone_id": "MLS-01",
        "tor_clause": "4.1.1",
        "deliverable_name": "1.5 Interview Overview 10 Departments",
        "description": "Overall interview 10 departments",
        "required_output": "Overview Notes",
        "required_evidence": "INT-OVERVIEW-M1",
        "weight": 0.3,
        "planned_start": "2026-08-18",
        "planned_finish": "2026-10-31",
        "status": "Accepted",
    },
    # ── M2 interviews ──
    *[
        {
            "deliverable_id": f"DLV-M2-{n}",
            "milestone_id": "MLS-02",
            "tor_clause": "4.1.1",
            "deliverable_name": name,
            "description": "สัมภาษณ์แยกแต่ละหน่วยงาน",
            "required_output": "Interview Notes",
            "required_evidence": f"INT-{evi}",
            "weight": 0.5,
            "planned_start": "2026-10-19",
            "planned_finish": "2026-10-31",
            "status": "Not Started",
        }
        for n, name, evi in [
            (19, "1.6.1 สัมภาษณ์ฝ่ายพัฒนาธุรกิจ (ฝพธ.)", "DEV-M2"),
            (20, "1.6.2 สำนักตรวจสอบภายใน (สตส.)", "IA-M2"),
            (21, "1.6.3 ฝ่ายเจ้าหน้าที่ DPO", "DPO-M2"),
            (22, "1.6.4 ฝ่ายบำรุงรักษา (ฝบร./กบร.)", "MTN-M2"),
            (23, "1.6.5 ฝ่ายกฎหมาย (ฝกม.)", "LEGAL-M2"),
            (24, "1.6.6 ฝ่ายการเงิน (ฝกง.)", "FIN-M2"),
            (25, "1.6.7 ฝ่ายทรัพยากรบุคคล (ฝทบ.)", "HR-M2"),
            (26, "1.6.8 ฝ่ายยุทธศาสตร์ (ฝยป./กบค.)", "STR-M2"),
            (27, "1.6.9 ฝ่ายดิจิทัล 1 (ฝดท.1)", "DT1-M2"),
            (28, "1.6.10 ฝ่ายดิจิทัล 2 (ฝดท.2)", "DT2-M2"),
        ]
    ],
    {
        "deliverable_id": "DLV-M2-18",
        "milestone_id": "MLS-02",
        "tor_clause": "4.1.1",
        "deliverable_name": "1.6 Interview 10 Departments (Overall)",
        "description": "นัดสัมภาษณ์แยกแต่ละหน่วยงาน รวม 10 แห่ง",
        "required_output": "Interview Plan",
        "required_evidence": "INT-PLAN-M2",
        "weight": 0.0,
        "planned_start": "2026-10-19",
        "planned_finish": "2026-10-31",
        "status": "Not Started",
    },
    {
        "deliverable_id": "DLV-M2-29",
        "milestone_id": "MLS-02",
        "tor_clause": "-",
        "deliverable_name": "📅 Monthly Report — ตุลาคม 69",
        "description": "รายงานอัพเดตความคืบหน้ารายเดือนตุลาคม",
        "required_output": "Monthly Report",
        "required_evidence": "MR-OCT-69",
        "weight": 0.25,
        "planned_start": "2026-11-02",
        "planned_finish": "2026-11-02",
        "status": "Not Started",
    },
    {
        "deliverable_id": "DLV-M2-30",
        "milestone_id": "MLS-02",
        "tor_clause": "-",
        "deliverable_name": "📅 Monthly Report — พฤศจิกายน 69",
        "description": "รายงานอัพเดตความคืบหน้ารายเดือนพฤศจิกายน",
        "required_output": "Monthly Report",
        "required_evidence": "MR-NOV-69",
        "weight": 0.25,
        "planned_start": "2026-11-30",
        "planned_finish": "2026-11-30",
        "status": "Not Started",
    },
    {
        "deliverable_id": "DLV-M3-20",
        "milestone_id": "MLS-03",
        "tor_clause": "-",
        "deliverable_name": "📅 Monthly Report — มกราคม 70",
        "description": "รายงานอัพเดตความคืบหน้ารายเดือนมกราคม",
        "required_output": "Monthly Report",
        "required_evidence": "MR-JAN-70",
        "weight": 0.25,
        "planned_start": "2027-01-29",
        "planned_finish": "2027-01-29",
        "status": "Not Started",
    },
    {
        "deliverable_id": "DLV-M4-17",
        "milestone_id": "MLS-04",
        "tor_clause": "-",
        "deliverable_name": "📅 Monthly Report — มีนาคม 70",
        "description": "รายงานอัพเดตความคืบหน้ารายเดือนมีนาคม",
        "required_output": "Monthly Report",
        "required_evidence": "MR-MAR-70",
        "weight": 0.25,
        "planned_start": "2027-03-31",
        "planned_finish": "2027-03-31",
        "status": "Not Started",
    },
    {
        "deliverable_id": "DLV-M4-18",
        "milestone_id": "MLS-04",
        "tor_clause": "-",
        "deliverable_name": "📅 Monthly Report — เมษายน 70",
        "description": "รายงานอัพเดตความคืบหน้ารายเดือนเมษายน",
        "required_output": "Monthly Report",
        "required_evidence": "MR-APR-70",
        "weight": 0.25,
        "planned_start": "2027-04-30",
        "planned_finish": "2027-04-30",
        "status": "Not Started",
    },
    {
        "deliverable_id": "DLV-M4-19",
        "milestone_id": "MLS-04",
        "tor_clause": "-",
        "deliverable_name": "📅 Monthly Report — พฤษภาคม 70",
        "description": "รายงานอัพเดตความคืบหน้ารายเดือนพฤษภาคม",
        "required_output": "Monthly Report",
        "required_evidence": "MR-MAY-70",
        "weight": 0.25,
        "planned_start": "2027-05-31",
        "planned_finish": "2027-05-31",
        "status": "Not Started",
    },
]


def main():
    engine = create_engine(DATABASE_URL)

    # ── 1. เพิ่ม column sequence (ถ้ายังไม่มี) ──
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE "deliverable_master"
            ADD COLUMN IF NOT EXISTS "sequence" INTEGER DEFAULT 0
        """))
        print("✅ เพิ่ม column `sequence` (ถ้ามีอยู่แล้ว skip)")

    # ── 2. INSERT missing deliverables ──
    inserted = 0
    for d in MISSING:
        try:
            row = {
                **d,
                "actual_start": d["planned_start"] if d["status"] == "Accepted" else "",
                "actual_finish": d["planned_finish"] if d["status"] == "Accepted" else "",
                "compliance_status": "Compliant" if d["status"] == "Accepted" else "Not Checked",
                "reviewer": "admin" if d["status"] == "Accepted" else "",
                "review_date": "2026-09-01" if d["status"] == "Accepted" else "",
                "review_comment": "",
                "updated_at": "2026-10-14 09:00:00",
                "sequence": SEQUENCE_MAP.get(d["deliverable_id"], 0),
            }
            cols = list(row.keys())
            placeholders = ", ".join(f":{c}" for c in cols)
            col_names = ", ".join(f'"{c}"' for c in cols)
            update_set = ", ".join(
                f'"{c}" = EXCLUDED."{c}"' for c in cols
                if c != "deliverable_id"
            )
            sql = text(f"""
                INSERT INTO "deliverable_master" ({col_names})
                VALUES ({placeholders})
                ON CONFLICT ("deliverable_id") DO UPDATE SET {update_set}
            """)
            with engine.begin() as conn:
                conn.execute(sql, row)
            inserted += 1
        except Exception as e:
            print(f"❌ {d['deliverable_id']}: {e}")

    print(f"✅ Upsert missing deliverables: {inserted}/{len(MISSING)}")

    # ── 3. UPDATE sequence + weight ──
    updated_seq = 0
    for did, seq in SEQUENCE_MAP.items():
        with engine.begin() as conn:
            res = conn.execute(
                text("""
                    UPDATE "deliverable_master"
                    SET sequence = :seq, updated_at = NOW()::text
                    WHERE deliverable_id = :did
                """),
                {"seq": seq, "did": did},
            )
            updated_seq += res.rowcount

    print(f"✅ Update sequence: {updated_seq} rows")

    updated_w = 0
    for did, w in WEIGHT_FIX.items():
        with engine.begin() as conn:
            res = conn.execute(
                text("""
                    UPDATE "deliverable_master"
                    SET weight = :w, updated_at = NOW()::text
                    WHERE deliverable_id = :did
                """),
                {"w": w, "did": did},
            )
            updated_w += res.rowcount

    print(f"✅ Update weight: {updated_w} rows")

    # ── 4. Verify ──
    with engine.connect() as conn:
        total = conn.execute(text('SELECT COUNT(*) FROM "deliverable_master"')).scalar()
        no_seq = conn.execute(
            text('SELECT COUNT(*) FROM "deliverable_master" WHERE sequence = 0 OR sequence IS NULL')
        ).scalar()
        print(f"\n📊 Total: {total} · Missing sequence: {no_seq}")

    print("\n🎉 เสร็จสิ้น — กรุณา refresh หน้าเว็บ")


if __name__ == "__main__":
    main()