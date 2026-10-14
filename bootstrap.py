"""สร้าง Master + History CSV เริ่มต้น

เวอร์ชันนี้ใช้ข้อมูลจริงจาก Timeline ที่วางแผนร่วมกับ
จุฬาลงกรณ์มหาวิทยาลัย — EXAT CCH Full Timeline
Contract Signed: 18 ส.ค. 2569 (2026-08-18)
Payment Schedule: 10/30/30/20/10

★ v2 — แก้ไข:
- เพิ่ม `normalize_deliverable_weights()` — normalize weights ให้รวม = 100.00%
  (เดิม DELIVERABLES_FULL มี weight รวม 95.00% → ทำให้ Overall Progress
  ไม่สามารถเข้าถึง 100% ได้)
- เพิ่ม `rebalance_existing_weights()` — ซ่อมข้อมูลเดิมโดยไม่ต้อง reseed
- เพิ่ม `force_reseed_master()` — ใช้โดยหน้า p13_settings
- `ensure_seed_data()` เรียก normalizer ก่อนเขียน CSV ทุกครั้ง
"""
from pathlib import Path
import pandas as pd
from datetime import date, timedelta
from config_loader import load_settings

DATA = Path(__file__).parent / "data"


# ============================================================
# ★ WEIGHT NORMALIZER
# ============================================================
def normalize_deliverable_weights(
    deliverables: list,
    target_total: float = 100.0,
    round_to: int = 2,
) -> list:
    """
    ปรับ weights ของ deliverables ให้ผลรวม = target_total พอดี

    หลักการ:
    - Scale ทุกตัวด้วย factor เดียวกัน → รักษาสัดส่วนเดิม
    - ปรับ rounding ที่ตัวที่มี weight มากสุด เพื่อให้ sum เป๊ะ
    - Idempotent: ถ้ารันซ้ำด้วย input ที่ normalize แล้ว → ผลเท่าเดิม

    Args:
        deliverables: list ของ dict (แต่ละ dict ต้องมี key "weight")
        target_total: ผลรวมเป้าหมาย (default 100.0)
        round_to: จำนวนทศนิยม (default 2)

    Returns:
        list ใหม่ (copy) ที่มี weight ถูก normalize แล้ว
    """
    if not deliverables:
        return []

    # คำนวณผลรวมปัจจุบัน (จาก valid weights เท่านั้น)
    weights = []
    for d in deliverables:
        try:
            w = float(d.get("weight", 0) or 0)
        except (ValueError, TypeError):
            w = 0.0
        weights.append(w)

    total = sum(weights)
    if total <= 0:
        # fallback: กระจายเท่า ๆ กัน
        n = len(deliverables)
        if n == 0:
            return []
        each = round(target_total / n, round_to)
        result = [dict(d) for d in deliverables]
        for d in result:
            d["weight"] = each
        return result

    # ถ้าอยู่ใกล้เป้าหมายแล้ว → คืนค่าเดิม (idempotent)
    if abs(total - target_total) < 10 ** (-round_to):
        return [dict(d) for d in deliverables]

    # Scale
    factor = target_total / total
    result = [dict(d) for d in deliverables]
    for i, d in enumerate(result):
        result[i]["weight"] = round(weights[i] * factor, round_to)

    # Fix rounding → ปรับที่ตัวที่มี weight มากสุด
    current_sum = sum(d["weight"] for d in result)
    diff = round(target_total - current_sum, round_to)
    if abs(diff) >= 10 ** (-round_to):
        # หา index ที่มี weight มากสุด
        max_idx = max(range(len(result)), key=lambda i: result[i]["weight"])
        result[max_idx]["weight"] = round(
            result[max_idx]["weight"] + diff, round_to
        )

    return result


# ============================================================
# ★ DELIVERABLE MASTER — Full Timeline (จุฬาลงกรณ์มหาวิทยาลัย)
# ============================================================
# ⚠️ หมายเหตุ: ค่า weight ด้านล่างนี้เป็นค่าดิบตาม Timeline
#    ผลรวมทั้งชุด = 95.00% → ระบบจะ normalize ให้เป็น 100.00%
#    อัตโนมัติใน `ensure_seed_data()` ผ่าน normalize_deliverable_weights()
#
#    ถ้าต้องการแก้ weight ด้วยตนเอง ให้แก้ค่าที่นี่ แล้วระบบจะ normalize
#    ตามสัดส่วนให้เอง — ไม่ต้องกังวลเรื่องผลรวม
# ============================================================

DELIVERABLES_FULL = [
    # ═══════════════════════════════════════════════════════════
    # M1 — INCEPTION REPORT (31 ส.ค. 69 / 2026-08-31) — Payment 10%
    # ═══════════════════════════════════════════════════════════
    {
        "id": "DLV-M1-01", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.1 Kick-off Meeting (ภายใน 15 วัน)",
        "desc": "ต้องจัดภายใน 15 วันหลังลงนามสัญญา ตาม TOR ข้อ 5",
        "output": "รายงานการประชุม Kick-off",
        "evidence": "MEETING-KICKOFF-001",
        "weight": 0.3, "start": "2026-08-18", "finish": "2026-08-18",
    },
    {
        "id": "DLV-M1-02", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.2 Project Charter (ความเป็นมา + วัตถุประสงค์)",
        "desc": "6.1.1-6.1.2 ความเป็นมา + วัตถุประสงค์โครงการ",
        "output": "Project Charter",
        "evidence": "CHARTER-CCH-M1",
        "weight": 0.5, "start": "2026-08-18", "finish": "2026-08-21",
    },
    {
        "id": "DLV-M1-03", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.3 แผนการดำเนินโครงการโดยละเอียด (Project Timeline)",
        "desc": "6.1.3 รูปแบบ/วิธี/ขั้นตอน/ระยะเวลา + ผลที่คาดว่าจะได้รับ",
        "output": "Project Plan + Timeline",
        "evidence": "PLAN-CCH-M1",
        "weight": 1.0, "start": "2026-08-18", "finish": "2026-08-21",
    },
    {
        "id": "DLV-M1-04", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.4 ผังการบริหารของโครงการ (Org Chart)",
        "desc": "6.1.4 Organization Chart ทีมโครงการ",
        "output": "Organization Chart",
        "evidence": "ORG-CCH-M1",
        "weight": 0.5, "start": "2026-08-18", "finish": "2026-08-21",
    },
    {
        "id": "DLV-M1-05", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.5 สัมภาษณ์กองนิติการ + DPO",
        "desc": "PDPA, Consent, ระเบียบวิธีปฏิบัติ",
        "output": "Interview Notes",
        "evidence": "INT-LEGAL-M1",
        "weight": 0.3, "start": "2026-08-18", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-06", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.6 สัมภาษณ์ฝ่ายดิจิทัล 1 (ธุรกิจดิจิทัล)",
        "desc": "ลงทะเบียน, เติมเงิน, บัตร Easy Pass",
        "output": "Interview Notes",
        "evidence": "INT-DT1-M1",
        "weight": 0.3, "start": "2026-08-18", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-07", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.7 สัมภาษณ์ฝ่ายการเงิน (รายได้+บัญชี)",
        "desc": "Payment Data Flow, กระทบยอด",
        "output": "Interview Notes",
        "evidence": "INT-FIN-M1",
        "weight": 0.3, "start": "2026-08-18", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-08", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.8 สัมภาษณ์ฝ่ายดิจิทัล 2 (IT+Network+Security)",
        "desc": "API, Network, Cyber Security",
        "output": "Interview Notes",
        "evidence": "INT-DT2-M1",
        "weight": 0.3, "start": "2026-08-18", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-09", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.9 สัมภาษณ์ฝ่ายบริหารธุรกิจใหม่",
        "desc": "EXAT Reward, Non-Toll Revenue",
        "output": "Interview Notes",
        "evidence": "INT-BIZ-M1",
        "weight": 0.3, "start": "2026-08-18", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-10", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.10 สัมภาษณ์บริหารความเสี่ยง + สตส + กฏหมาย",
        "desc": "Risk Mgmt, Internal Audit, Legal Framework",
        "output": "Interview Notes",
        "evidence": "INT-RISK-M1",
        "weight": 0.3, "start": "2026-08-18", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-11", "ms": "MLS-01", "tor": "4.1.1",
        "name": "1.11 ผลศึกษาเบื้องต้น 4.1.1 (Compliance Advisory)",
        "desc": "6.1.5 Compliance Baseline + Gap Analysis Initial",
        "output": "Initial Study Report",
        "evidence": "REPORT-M1-COMP",
        "weight": 1.2, "start": "2026-08-18", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-12", "ms": "MLS-01", "tor": "4.2",
        "name": "1.12 Initial Governance Review",
        "desc": "6.1.6 ผลทบทวนโครงสร้างการกำกับดูแลเบื้องต้น",
        "output": "Governance Review Report",
        "evidence": "REPORT-M1-GOV",
        "weight": 0.8, "start": "2026-08-18", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-13", "ms": "MLS-01", "tor": "4.3",
        "name": "1.13 Business Assumptions + Context (Initial)",
        "desc": "6.1.7 การวิเคราะห์สมมติฐานทางธุรกิจเบื้องต้น",
        "output": "Business Assumptions Doc",
        "evidence": "REPORT-M1-BIZ",
        "weight": 0.8, "start": "2026-08-18", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-14", "ms": "MLS-01", "tor": "4.4",
        "name": "1.14 Monitoring Framework + KPIs (Initial)",
        "desc": "6.1.8 กรอบ Monitoring + KPI เบื้องต้น",
        "output": "Monitoring Framework",
        "evidence": "REPORT-M1-MON",
        "weight": 0.6, "start": "2026-08-18", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-15", "ms": "MLS-01", "tor": "7.1",
        "name": "▶ ส่ง(ร่าง) Inception ให้คณะกรรมการ (10 วันก่อน)",
        "desc": "จัดหนังสือส่ง + Slide นำเสนอ",
        "output": "Draft Submission",
        "evidence": "SUB-DRAFT-M1",
        "weight": 0.3, "start": "2026-08-18", "finish": "2026-08-21",
    },
    {
        "id": "DLV-M1-16", "ms": "MLS-01", "tor": "7.1",
        "name": "▶ ปรับปรุง Inception ตามข้อแก้ไข",
        "desc": "แก้ไขตาม Comment ของคณะกรรมการ",
        "output": "Revised Report",
        "evidence": "SUB-REV-M1",
        "weight": 0.3, "start": "2026-08-21", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-17", "ms": "MLS-01", "tor": "7.1",
        "name": "🎯 Submit Inception Report — 31 ส.ค. 69 (Day 30)",
        "desc": "2 ชุด + USB 2 อัน | Payment 10% ของราคาจ้าง",
        "output": "Final Inception Report",
        "evidence": "ACCEPT-M1-REQ",
        "weight": 1.5, "start": "2026-08-31", "finish": "2026-08-31",
    },
    {
        "id": "DLV-M1-18", "ms": "MLS-01", "tor": "7.1",
        "name": "👥 ประชุมตรวจรับ Inception Report",
        "desc": "คณะกรรมการตรวจรับงาน",
        "output": "Acceptance Minutes",
        "evidence": "ACC-MIN-M1",
        "weight": 0.4, "start": "2026-09-01", "finish": "2026-09-01",
    },

    # ═══════════════════════════════════════════════════════════
    # M2 — PROGRESS I REPORT (16 ธ.ค. 69 / 2026-12-16) — Payment 30%
    # 🔥 PF License ยื่นในงวดนี้
    # ═══════════════════════════════════════════════════════════
    {
        "id": "DLV-M2-01", "ms": "MLS-02", "tor": "4.1.2",
        "name": "2.1 CCH Operational Workflow (5 กระบวนการ)",
        "desc": "6.2.1 รับข้อมูล+ตรวจสอบ+ประมวลผล+กระทบยอด+ส่ง สถ.การเงิน — วิเคราะห์ ช่วยเหลือ ดำเนินการ และกำหนดกระบวนการทำงานที่เกี่ยวข้องกับการดำเนินงานของระบบ CCH",
        "output": "Operational Workflow Draft",
        "evidence": "REPORT-M2-WF",
        "weight": 2.5, "start": "2026-09-01", "finish": "2026-11-30",
    },
    {
        "id": "DLV-M2-02", "ms": "MLS-02", "tor": "4.1.3",
        "name": "2.2 Risk Assessment (เบื้องต้น)",
        "desc": "6.2.2 Risk Assessment เบื้องต้น + Risk Matrix",
        "output": "Risk Assessment Report",
        "evidence": "REPORT-M2-RISK",
        "weight": 1.5, "start": "2026-09-15", "finish": "2026-11-21",
    },
    {
        "id": "DLV-M2-03", "ms": "MLS-02", "tor": "4.1.4",
        "name": "2.3 SOPs (เบื้องต้น) + Internal Control",
        "desc": "6.2.3 Draft SOP Manual + Control Procedures — ร่าง SOPs, การควบคุมภายใน, ขั้นตอนตรวจสอบธุรกรรม, AML/CFT, Audit Checklists และ Three Lines of Defense",
        "output": "Draft SOP Manual",
        "evidence": "REPORT-M2-SOP",
        "weight": 2.0, "start": "2026-09-22", "finish": "2026-11-30",
    },
    {
        "id": "DLV-M2-04", "ms": "MLS-02", "tor": "4.1.6",
        "name": "2.4 Data Retention Framework (เบื้องต้น)",
        "desc": "6.2.4 Data Retention Policy + Data Lifecycle",
        "output": "Data Retention Draft",
        "evidence": "REPORT-M2-DR",
        "weight": 1.0, "start": "2026-10-08", "finish": "2026-11-30",
    },
    {
        "id": "DLV-M2-05", "ms": "MLS-02", "tor": "4.1.7",
        "name": "2.5 Draft Compliance Roadmap + Reporting Framework",
        "desc": "6.2.5 Regulatory Reporting Framework + Templates",
        "output": "Compliance Roadmap",
        "evidence": "REPORT-M2-CR",
        "weight": 1.5, "start": "2026-10-08", "finish": "2026-11-30",
    },
    {
        "id": "DLV-M2-06", "ms": "MLS-02", "tor": "4.1.8",
        "name": "2.6 Source of Fund / Channel Code Design",
        "desc": "6.2.6 คู่มือทดสอบเติมเงิน + วิธีตรวจสอบ",
        "output": "Source of Fund Design",
        "evidence": "REPORT-M2-SOF",
        "weight": 1.5, "start": "2026-10-22", "finish": "2026-12-04",
    },
    {
        "id": "DLV-M2-07", "ms": "MLS-02", "tor": "4.1.9",
        "name": "2.7 Electronic Wallet Design (วงเงิน + โครงสร้าง)",
        "desc": "6.2.7 การกำหนดวงเงิน + Fair Media + จำนวน Wallet",
        "output": "E-Wallet Design Doc",
        "evidence": "REPORT-M2-EW",
        "weight": 1.5, "start": "2026-10-22", "finish": "2026-12-04",
    },
    {
        "id": "DLV-M2-08", "ms": "MLS-02", "tor": "4.1",
        "name": "2.8 Workshops ร่วมกับหน่วยงานภายใน",
        "desc": "6.2.8 Workshop ทดสอบและปรับปรุงกระบวนการ",
        "output": "Workshop Report",
        "evidence": "REPORT-M2-WS",
        "weight": 1.0, "start": "2026-11-08", "finish": "2026-12-04",
    },
    {
        "id": "DLV-M2-09", "ms": "MLS-02", "tor": "4.2",
        "name": "2.9 ร่าง Org Structure + Key Roles (เบื้องต้น)",
        "desc": "6.2.9 Organisational Structure + Roles Draft — ร่างโครงสร้างองค์กร บทบาทและความรับผิดชอบ + System Control Board",
        "output": "Draft Org Structure",
        "evidence": "REPORT-M2-ORG",
        "weight": 1.5, "start": "2026-09-01", "finish": "2026-11-30",
    },
    {
        "id": "DLV-M2-10", "ms": "MLS-02", "tor": "4.3",
        "name": "2.10 Business Model Overview + Revenue + Cost (เบื้องต้น)",
        "desc": "6.2.10 BM Overview + Revenue Model + Cost Structure — ร่างการจำลองรายได้-ต้นทุน และการวิเคราะห์ความเสี่ยง",
        "output": "BM Overview Draft",
        "evidence": "REPORT-M2-BM",
        "weight": 2.0, "start": "2026-09-01", "finish": "2026-11-30",
    },
    {
        "id": "DLV-M2-11", "ms": "MLS-02", "tor": "4.4",
        "name": "2.11 Daily Transaction + Monthly Performance Reporting",
        "desc": "6.2.11 Daily TXN Monitoring + Monthly Performance",
        "output": "Performance Report",
        "evidence": "REPORT-M2-PERF",
        "weight": 1.0, "start": "2026-10-08", "finish": "2026-12-14",
    },
    {
        "id": "DLV-M2-12", "ms": "MLS-02", "tor": "4.5.1 (PF)",
        "name": "🔥 2.12 PF License Application Package",
        "desc": "4.5.1 เอกสารครบชุด (Corp+Compliance+Tech+AML)",
        "output": "PF Application Package",
        "evidence": "PKG-PF-REQ",
        "weight": 3.0, "start": "2026-08-18", "finish": "2026-09-30",
    },
    {
        "id": "DLV-M2-13", "ms": "MLS-02", "tor": "4.5.2 (PF)",
        "name": "🔥 2.13 PF License Pre-review + Submit to BOT ⭐",
        "desc": "ยื่นเอกสาร PF ต่อ ธปท.",
        "output": "BOT Submission Receipt",
        "evidence": "BOT-SUB-PF",
        "weight": 2.0, "start": "2026-09-30", "finish": "2026-10-04",
    },
    {
        "id": "DLV-M2-14", "ms": "MLS-02", "tor": "7.2",
        "name": "▶ ส่ง(ร่าง) Progress I ให้คณะกรรมการ (10 วันก่อน)",
        "desc": "จัดหนังสือส่ง + Slide",
        "output": "Draft Submission",
        "evidence": "SUB-DRAFT-M2",
        "weight": 0.5, "start": "2026-12-06", "finish": "2026-12-06",
    },
    {
        "id": "DLV-M2-15", "ms": "MLS-02", "tor": "7.2",
        "name": "▶ ปรับปรุง Progress I ตามข้อแก้ไข",
        "desc": "แก้ไขตาม Comment",
        "output": "Revised Report",
        "evidence": "SUB-REV-M2",
        "weight": 0.5, "start": "2026-12-08", "finish": "2026-12-16",
    },
    {
        "id": "DLV-M2-16", "ms": "MLS-02", "tor": "7.2",
        "name": "🎯 Submit Progress I Report — 16 ธ.ค. 69 (Day 120)",
        "desc": "2 ชุด + USB 2 อัน | Payment 30% ของราคาจ้าง",
        "output": "Final Progress I Report",
        "evidence": "ACCEPT-M2-REQ",
        "weight": 1.5, "start": "2026-12-16", "finish": "2026-12-16",
    },
    {
        "id": "DLV-M2-17", "ms": "MLS-02", "tor": "7.2",
        "name": "👥 ประชุมตรวจรับ Progress I Report",
        "desc": "คณะกรรมการตรวจรับงาน",
        "output": "Acceptance Minutes",
        "evidence": "ACC-MIN-M2",
        "weight": 0.5, "start": "2026-12-17", "finish": "2026-12-25",
    },

    # ═══════════════════════════════════════════════════════════
    # M3 — INTERIM REPORT (14 ก.พ. 70 / 2027-02-14) — Payment 30%
    # WP 4.1-4.3 เสร็จ + EM เริ่ม
    # ═══════════════════════════════════════════════════════════
    {
        "id": "DLV-M3-01", "ms": "MLS-03", "tor": "4.1.2",
        "name": "3.1 CCH Operational Workflow (ฉบับสมบูรณ์)",
        "desc": "6.3.1 Process Flow ระบบ CCH ฉบับสมบูรณ์ — วิเคราะห์ ช่วยเหลือ ดำเนินการ และกำหนดกระบวนการทำงาน",
        "output": "Final Operational Workflow",
        "evidence": "REPORT-M3-WF",
        "weight": 2.5, "start": "2026-12-01", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-02", "ms": "MLS-03", "tor": "4.1.5",
        "name": "3.2 Audit Trail Design (ฉบับสมบูรณ์)",
        "desc": "6.3.2 Audit Trail Design ฉบับสมบูรณ์ — ออกแบบกลไกการบันทึกร่องรอยการตรวจสอบ",
        "output": "Audit Trail Design",
        "evidence": "REPORT-M3-AT",
        "weight": 1.5, "start": "2026-12-01", "finish": "2027-01-31",
    },
    {
        "id": "DLV-M3-03", "ms": "MLS-03", "tor": "4.1.6",
        "name": "3.3 Data Retention Framework (ฉบับสมบูรณ์)",
        "desc": "6.3.3 Data Retention Framework ฉบับสมบูรณ์ — ออกแบบกลไกการจัดเก็บข้อมูล",
        "output": "Data Retention Framework",
        "evidence": "REPORT-M3-DR",
        "weight": 1.0, "start": "2026-12-01", "finish": "2027-01-31",
    },
    {
        "id": "DLV-M3-04", "ms": "MLS-03", "tor": "4.1.7",
        "name": "3.4 Regulatory Reporting Framework (ฉบับสมบูรณ์)",
        "desc": "6.3.4 Regulatory Reporting Framework ฉบับสมบูรณ์ — เครื่องมือการรายงานต่อหน่วยงานกำกับดูแล ให้สอดคล้องกับ ธปท.",
        "output": "Reporting Framework",
        "evidence": "REPORT-M3-RPT",
        "weight": 1.0, "start": "2026-12-01", "finish": "2027-01-31",
    },
    {
        "id": "DLV-M3-05", "ms": "MLS-03", "tor": "4.2",
        "name": "3.5 Org Structure + Governance + Committee (ฉบับสมบูรณ์)",
        "desc": "6.3.5 Org Structure + Governance + System Control Board ครบชุด — ช่วยเหลือ กทพ. ในการจัดตั้งคณะกรรมการกำกับระบบ",
        "output": "Governance Design Package",
        "evidence": "REPORT-M3-GOV",
        "weight": 2.5, "start": "2026-12-01", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-06", "ms": "MLS-03", "tor": "4.3",
        "name": "3.6 Business Model + Operational Model + Risk (ฉบับสมบูรณ์)",
        "desc": "6.3.6 BM Overview + Operational Model + Risk Analysis สมบูรณ์",
        "output": "BM & Op Model",
        "evidence": "REPORT-M3-BM",
        "weight": 2.5, "start": "2026-12-01", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-07", "ms": "MLS-03", "tor": "4.4",
        "name": "3.7 System Health Monitoring",
        "desc": "6.3.7 ติดตามสถานะระบบ",
        "output": "System Health Report",
        "evidence": "REPORT-M3-SH",
        "weight": 1.0, "start": "2026-12-22", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-08", "ms": "MLS-03", "tor": "4.5",
        "name": "3.8 Compliance Gap Assessment + Licensing Roadmap",
        "desc": "6.3.8 Licensing Preparation Roadmap",
        "output": "Licensing Roadmap",
        "evidence": "REPORT-M3-LIC",
        "weight": 1.5, "start": "2026-12-01", "finish": "2027-01-14",
    },
    {
        "id": "DLV-M3-09", "ms": "MLS-03", "tor": "4.3",
        "name": "3.9 Risk Management Strategy Report",
        "desc": "6.3.9 Risk Assessment + Risk Management Strategy — ระบุและประเมินความเสี่ยง + กลยุทธ์บรรเทา",
        "output": "Risk Strategy Report",
        "evidence": "REPORT-M3-RSK",
        "weight": 1.5, "start": "2026-12-15", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-10", "ms": "MLS-03", "tor": "4.3",
        "name": "3.10 Cost-Revenue Framework Report",
        "desc": "6.3.10 โครงสร้างรายได้-ค่าใช้จ่าย",
        "output": "Cost-Revenue Framework",
        "evidence": "REPORT-M3-CR",
        "weight": 1.5, "start": "2026-12-15", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-11", "ms": "MLS-03", "tor": "4.3",
        "name": "3.11 Efficiency Improvement Report",
        "desc": "6.3.11 Process Consolidation + Automation + Cost Reduction",
        "output": "Efficiency Report",
        "evidence": "REPORT-M3-EFF",
        "weight": 1.0, "start": "2026-12-22", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-12", "ms": "MLS-03", "tor": "4.3.4",
        "name": "3.12 Non-Toll Contract Templates + Fee Structure",
        "desc": "6.3.12 สัญญาพันธมิตร + MDR/Fee Structure + ตัวอย่างสัญญา — รีวิวสัญญาที่มีของ EXAT แล้วให้ feedback",
        "output": "Contract Templates",
        "evidence": "REPORT-M3-CT",
        "weight": 1.5, "start": "2026-12-15", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-13", "ms": "MLS-03", "tor": "4.4",
        "name": "3.13 Reporting Templates (Daily/Monthly/Quarterly/Yearly)",
        "desc": "6.3.13 แม่แบบรายงานสำหรับ ธปท. + ภายในองค์กร — Daily/Monthly/Quarterly/Yearly",
        "output": "Reporting Templates",
        "evidence": "REPORT-M3-TPL",
        "weight": 1.5, "start": "2026-12-22", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-14", "ms": "MLS-03", "tor": "4.4",
        "name": "3.14 Initial Year Monitoring (Advisory Support)",
        "desc": "6.3.14 Ongoing Advisory (12 เดือน)",
        "output": "Advisory Log",
        "evidence": "REPORT-M3-ADV",
        "weight": 1.0, "start": "2026-12-22", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-15", "ms": "MLS-03", "tor": "4.5.1 (EM)",
        "name": "🔥 3.17 E-Money License Application (เริ่ม)",
        "desc": "4.5.1 เตรียมเอกสาร E-Money License",
        "output": "EM Application Draft",
        "evidence": "REPORT-M3-EM",
        "weight": 1.5, "start": "2026-12-22", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-16", "ms": "MLS-03", "tor": "7.3",
        "name": "▶ ส่ง(ร่าง) Interim ให้คณะกรรมการ (10 วันก่อน)",
        "desc": "จัดหนังสือส่ง + Slide",
        "output": "Draft Submission",
        "evidence": "SUB-DRAFT-M3",
        "weight": 0.5, "start": "2027-02-02", "finish": "2027-02-02",
    },
    {
        "id": "DLV-M3-17", "ms": "MLS-03", "tor": "7.3",
        "name": "▶ ปรับปรุง Interim ตามข้อแก้ไข",
        "desc": "แก้ไขตาม Comment",
        "output": "Revised Report",
        "evidence": "SUB-REV-M3",
        "weight": 0.5, "start": "2027-02-02", "finish": "2027-02-12",
    },
    {
        "id": "DLV-M3-18", "ms": "MLS-03", "tor": "7.3",
        "name": "🎯 Submit Interim Report — 14 ก.พ. 70 (Day 180)",
        "desc": "2 ชุด + USB 2 อัน | Payment 30% ของราคาจ้าง",
        "output": "Final Interim Report",
        "evidence": "ACCEPT-M3-REQ",
        "weight": 1.5, "start": "2027-02-12", "finish": "2027-02-12",
    },
    {
        "id": "DLV-M3-19", "ms": "MLS-03", "tor": "7.3",
        "name": "👥 ประชุมตรวจรับ Interim Report",
        "desc": "คณะกรรมการตรวจรับงาน",
        "output": "Acceptance Minutes",
        "evidence": "ACC-MIN-M3",
        "weight": 0.5, "start": "2027-02-15", "finish": "2027-02-19",
    },

    # ═══════════════════════════════════════════════════════════
    # M4 — PROGRESS II REPORT (14 มิ.ย. 70 / 2027-06-14) — Payment 20%
    # 🔥 EM Submit + Advisory + Training
    # ═══════════════════════════════════════════════════════════
    {
        "id": "DLV-M4-01", "ms": "MLS-04", "tor": "4.4.1",
        "name": "4.1 Continuous Advisory Support (12 เดือน)",
        "desc": "6.4.1 การติดตามและให้คำปรึกษาต่อเนื่อง",
        "output": "Advisory Report",
        "evidence": "REPORT-M4-ADV",
        "weight": 3.0, "start": "2027-02-15", "finish": "2027-06-14",
    },
    {
        "id": "DLV-M4-02", "ms": "MLS-04", "tor": "4.4",
        "name": "4.2 Performance Monitoring",
        "desc": "6.4.2 การติดตามและประเมินประสิทธิภาพการดำเนินงาน",
        "output": "Performance Report",
        "evidence": "REPORT-M4-PERF",
        "weight": 2.0, "start": "2027-02-15", "finish": "2027-06-14",
    },
    {
        "id": "DLV-M4-03", "ms": "MLS-04", "tor": "4.1.1",
        "name": "4.3 Compliance Advisory Progress",
        "desc": "6.4.3 ความก้าวหน้ารายงาน Compliance Advisory",
        "output": "Compliance Progress",
        "evidence": "REPORT-M4-COMP",
        "weight": 1.5, "start": "2027-02-15", "finish": "2027-05-31",
    },
    {
        "id": "DLV-M4-04", "ms": "MLS-04", "tor": "4.2",
        "name": "4.4 Org Implementation Monitoring",
        "desc": "6.4.4 ผลการติดตามการนำโครงสร้างองค์กรไปใช้",
        "output": "Org Monitoring Report",
        "evidence": "REPORT-M4-ORG",
        "weight": 1.5, "start": "2027-02-15", "finish": "2027-05-31",
    },
    {
        "id": "DLV-M4-05", "ms": "MLS-04", "tor": "4.3",
        "name": "4.5 Business Performance Monitoring + Improvement",
        "desc": "6.4.5 ประสิทธิภาพการดำเนินงาน + ข้อเสนอแนะ",
        "output": "Business Improvement",
        "evidence": "REPORT-M4-BIZ",
        "weight": 1.5, "start": "2027-02-15", "finish": "2027-05-31",
    },
    {
        "id": "DLV-M4-06", "ms": "MLS-04", "tor": "4.4",
        "name": "4.6 Issue Escalation + Continuous Improvement",
        "desc": "6.4.6 กระบวนการยกระดับปัญหา + ปรับปรุงต่อเนื่อง",
        "output": "Escalation Report",
        "evidence": "REPORT-M4-ESC",
        "weight": 1.5, "start": "2027-02-15", "finish": "2027-05-31",
    },
    {
        "id": "DLV-M4-07", "ms": "MLS-04", "tor": "4.5",
        "name": "4.7 License Documentation + Coordination",
        "desc": "6.4.7 จัดเตรียมเอกสาร + ประสานหน่วยกำกับดูแล",
        "output": "License Docs",
        "evidence": "REPORT-M4-LIC",
        "weight": 2.0, "start": "2027-02-15", "finish": "2027-05-14",
    },
    {
        "id": "DLV-M4-08", "ms": "MLS-04", "tor": "4.5.2",
        "name": "4.8 AMLO Assessment + Approval Support",
        "desc": "4.5.2 ขอความเห็นชอบจากสำนักงาน ปปง. — AML Policy + AMLO Monitoring Procedure (SOP) + KYC/CDD Guidelines",
        "output": "AMLO Package",
        "evidence": "REPORT-M4-AMLO",
        "weight": 1.5, "start": "2027-03-08", "finish": "2027-05-14",
    },
    {
        "id": "DLV-M4-09", "ms": "MLS-04", "tor": "4.6",
        "name": "4.9 Training Program + Materials",
        "desc": "4.6 หลักสูตร + เอกสารประกอบ (Compliance/Operational/Governance)",
        "output": "Training Materials",
        "evidence": "TRN-MAT-M4",
        "weight": 1.5, "start": "2027-04-01", "finish": "2027-05-14",
    },
    {
        "id": "DLV-M4-10", "ms": "MLS-04", "tor": "4.6",
        "name": "4.10 การจัดฝึกอบรม (20+ คน, 3+ ชม.)",
        "desc": "4.6 Workshop สำหรับเจ้าหน้าที่ กทพ.",
        "output": "Training Report",
        "evidence": "TRN-RPT-M4",
        "weight": 1.5, "start": "2027-05-15", "finish": "2027-06-07",
    },
    {
        "id": "DLV-M4-11", "ms": "MLS-04", "tor": "4.5.1 (EM)",
        "name": "🔥 4.11 E-Money License — Complete Application",
        "desc": "4.5.1 เอกสาร EM ครบชุด",
        "output": "EM Complete Package",
        "evidence": "PKG-EM-REQ",
        "weight": 2.5, "start": "2027-02-15", "finish": "2027-04-21",
    },
    {
        "id": "DLV-M4-12", "ms": "MLS-04", "tor": "4.5.2 (EM)",
        "name": "🔥 4.12 E-Money License — Submit to BOT ⭐",
        "desc": "ยื่นเอกสาร E-Money ต่อ ธปท.",
        "output": "BOT Submission Receipt",
        "evidence": "BOT-SUB-EM",
        "weight": 1.5, "start": "2027-04-22", "finish": "2027-04-30",
    },
    {
        "id": "DLV-M4-13", "ms": "MLS-04", "tor": "7.4",
        "name": "▶ ส่ง(ร่าง) Progress II ให้คณะกรรมการ (10 วันก่อน)",
        "desc": "จัดหนังสือส่ง + Slide",
        "output": "Draft Submission",
        "evidence": "SUB-DRAFT-M4",
        "weight": 0.5, "start": "2027-06-04", "finish": "2027-06-04",
    },
    {
        "id": "DLV-M4-14", "ms": "MLS-04", "tor": "7.4",
        "name": "▶ ปรับปรุง Progress II ตามข้อแก้ไข",
        "desc": "แก้ไขตาม Comment",
        "output": "Revised Report",
        "evidence": "SUB-REV-M4",
        "weight": 0.5, "start": "2027-06-04", "finish": "2027-06-14",
    },
    {
        "id": "DLV-M4-15", "ms": "MLS-04", "tor": "7.4",
        "name": "🎯 Submit Progress II Report — 14 มิ.ย. 70 (Day 300)",
        "desc": "2 ชุด + USB 2 อัน | Payment 20% ของราคาจ้าง",
        "output": "Final Progress II Report",
        "evidence": "ACCEPT-M4-REQ",
        "weight": 1.5, "start": "2027-06-14", "finish": "2027-06-14",
    },
    {
        "id": "DLV-M4-16", "ms": "MLS-04", "tor": "7.4",
        "name": "👥 ประชุมตรวจรับ Progress II Report",
        "desc": "คณะกรรมการตรวจรับงาน",
        "output": "Acceptance Minutes",
        "evidence": "ACC-MIN-M4",
        "weight": 0.5, "start": "2027-06-15", "finish": "2027-06-18",
    },

    # ═══════════════════════════════════════════════════════════
    # M5 — FINAL REPORT (13 ส.ค. 70 / 2027-08-13) — Payment 10%
    # ═══════════════════════════════════════════════════════════
    {
        "id": "DLV-M5-01", "ms": "MLS-05", "tor": "4.4",
        "name": "5.1 Advisory Support (12 เดือนแล้วเสร็จ)",
        "desc": "6.5.1 การติดตามและให้คำปรึกษาช่วงปีแรก",
        "output": "Advisory Closure",
        "evidence": "REPORT-M5-ADV",
        "weight": 1.0, "start": "2027-06-15", "finish": "2027-08-14",
    },
    {
        "id": "DLV-M5-02", "ms": "MLS-05", "tor": "4.1",
        "name": "5.2 Operational Compliance Framework Package (ฉบับสมบูรณ์)",
        "desc": "6.5.2 ชุดเอกสาร WP 4.1 ครบทุกรายการ",
        "output": "WP 4.1 Package",
        "evidence": "PKG-M5-WP41",
        "weight": 1.5, "start": "2027-06-15", "finish": "2027-07-31",
    },
    {
        "id": "DLV-M5-03", "ms": "MLS-05", "tor": "4.2",
        "name": "5.3 Organizational Governance Design Package (ฉบับสมบูรณ์)",
        "desc": "6.5.3 ชุดเอกสาร WP 4.2 ครบทุกรายการ",
        "output": "WP 4.2 Package",
        "evidence": "PKG-M5-WP42",
        "weight": 1.0, "start": "2027-06-15", "finish": "2027-07-31",
    },
    {
        "id": "DLV-M5-04", "ms": "MLS-05", "tor": "4.3",
        "name": "5.4 CCH Business Model & Financial Framework Package",
        "desc": "6.5.4 ชุดเอกสาร WP 4.3 ครบทุกรายการ",
        "output": "WP 4.3 Package",
        "evidence": "PKG-M5-WP43",
        "weight": 1.0, "start": "2027-06-15", "finish": "2027-07-31",
    },
    {
        "id": "DLV-M5-05", "ms": "MLS-05", "tor": "4.4",
        "name": "5.5 Operational Monitoring Package (ฉบับสมบูรณ์)",
        "desc": "6.5.5 ชุดเอกสาร WP 4.4 ครบทุกรายการ",
        "output": "WP 4.4 Package",
        "evidence": "PKG-M5-WP44",
        "weight": 1.0, "start": "2027-06-15", "finish": "2027-07-31",
    },
    {
        "id": "DLV-M5-06", "ms": "MLS-05", "tor": "4.5",
        "name": "5.6 E-Money License Advisory Package (ฉบับสมบูรณ์)",
        "desc": "6.5.6 ชุดเอกสาร WP 4.5 ครบทุกรายการ",
        "output": "WP 4.5 Package",
        "evidence": "PKG-M5-WP45",
        "weight": 1.0, "start": "2027-06-15", "finish": "2027-07-31",
    },
    {
        "id": "DLV-M5-07", "ms": "MLS-05", "tor": "4.6",
        "name": "5.7 Training Report + Attendance + Evaluation",
        "desc": "4.6 รายงานสรุปฝึกอบรม + บัญชีผู้เข้าร่วม + ผลประเมิน",
        "output": "Training Summary",
        "evidence": "TRN-RPT-M5",
        "weight": 0.5, "start": "2027-07-01", "finish": "2027-07-31",
    },
    {
        "id": "DLV-M5-08", "ms": "MLS-05", "tor": "7.5",
        "name": "5.9 Project Closure Report",
        "desc": "สรุปโครงการ",
        "output": "Closure Report",
        "evidence": "REPORT-M5-CLOSE",
        "weight": 0.5, "start": "2027-07-22", "finish": "2027-08-03",
    },
    {
        "id": "DLV-M5-09", "ms": "MLS-05", "tor": "7.5",
        "name": "▶ ส่ง(ร่าง) Final ให้คณะกรรมการ (10 วันก่อน)",
        "desc": "จัดหนังสือส่ง + Slide",
        "output": "Draft Submission",
        "evidence": "SUB-DRAFT-M5",
        "weight": 0.3, "start": "2027-08-03", "finish": "2027-08-03",
    },
    {
        "id": "DLV-M5-10", "ms": "MLS-05", "tor": "7.5",
        "name": "▶ ปรับปรุง Final ตามข้อแก้ไข",
        "desc": "แก้ไขตาม Comment",
        "output": "Revised Report",
        "evidence": "SUB-REV-M5",
        "weight": 0.2, "start": "2027-08-03", "finish": "2027-08-13",
    },
    {
        "id": "DLV-M5-11", "ms": "MLS-05", "tor": "7.5",
        "name": "🎯 Submit Final Report — 13 ส.ค. 70 (Day 360)",
        "desc": "2 ชุด + USB 10 อัน (Word+PDF) | Payment 10% ของราคาจ้าง",
        "output": "Final Report Package",
        "evidence": "ACCEPT-M5-REQ",
        "weight": 1.0, "start": "2027-08-13", "finish": "2027-08-13",
    },
    {
        "id": "DLV-M5-12", "ms": "MLS-05", "tor": "7.5",
        "name": "👥 ประชุมตรวจรับ Final Report",
        "desc": "คณะกรรมการตรวจรับงาน",
        "output": "Acceptance Minutes",
        "evidence": "ACC-MIN-M5",
        "weight": 0.5, "start": "2027-08-16", "finish": "2027-08-20",
    },
]

# ============================================================
# ★ PERSONNEL MASTER (TOR ข้อ 12 — 8 ตำแหน่ง + ผู้ช่วย 2 + ผู้ประสาน 1)
# ============================================================
# หมายเหตุ: ใส่ชื่อจริงทีหลังได้ผ่านหน้า ⚙️ Project / Milestone
# ============================================================
PERSONNEL_FULL = [
    # ── Key Personnel (8 ตำแหน่ง) ──
    {
        "id": "PSN-KP-01", "category": "Key Personnel",
        "position": "หัวหน้าโครงการ (Project Manager)",
        "qty": 1, "qualification": "ปริญญาโท+, ประสบการณ์ ≥ 10 ปี",
        "responsibility": "บริหารโครงการทั้งหมด, ประสานคณะกรรมการ",
        "name": "(รอระบุ)",
    },
    {
        "id": "PSN-KP-02", "category": "Key Personnel",
        "position": "รองหัวหน้าโครงการ (Deputy PM)",
        "qty": 1, "qualification": "ปริญญาโท+, ประสบการณ์ ≥ 7 ปี",
        "responsibility": "สนับสนุน PM, ดูแลคุณภาพ deliverable",
        "name": "(รอระบุ)",
    },
    {
        "id": "PSN-KP-03", "category": "Key Personnel",
        "position": "ผู้เชี่ยวชาญด้านการเงิน (Financial Advisory)",
        "qty": 1, "qualification": "CPA/CFA, ประสบการณ์ ≥ 7 ปี",
        "responsibility": "วิเคราะห์ BM, Cost-Revenue, การเงิน",
        "name": "(รอระบุ)",
    },
    {
        "id": "PSN-KP-04", "category": "Key Personnel",
        "position": "ผู้เชี่ยวชาญ Compliance (Regulatory)",
        "qty": 1, "qualification": "ประสบการณ์ด้านกำกับ ≥ 7 ปี",
        "responsibility": "Compliance Roadmap, Regulatory Reporting",
        "name": "(รอระบุ)",
    },
    {
        "id": "PSN-KP-05", "category": "Key Personnel",
        "position": "ผู้เชี่ยวชาญด้านกฎหมาย (Legal)",
        "qty": 1, "qualification": "นิติศาสตร์, ประสบการณ์ ≥ 7 ปี",
        "responsibility": "สัญญา, PF/EM License, กฎหมายการเงิน",
        "name": "(รอระบุ)",
    },
    {
        "id": "PSN-KP-06", "category": "Key Personnel",
        "position": "ผู้เชี่ยวชาญด้าน IT / Technology",
        "qty": 1, "qualification": "IT, ประสบการณ์ ≥ 7 ปี",
        "responsibility": "CCH System, Audit Trail, Data Retention",
        "name": "(รอระบุ)",
    },
    {
        "id": "PSN-KP-07", "category": "Key Personnel",
        "position": "ผู้เชี่ยวชาญด้านความเสี่ยง (Risk Management)",
        "qty": 1, "qualification": "ประสบการณ์ ≥ 7 ปี",
        "responsibility": "Risk Assessment, Risk Strategy",
        "name": "(รอระบุ)",
    },
    {
        "id": "PSN-KP-08", "category": "Key Personnel",
        "position": "ผู้เชี่ยวชาญ AML/CFT",
        "qty": 1, "qualification": "CAMS หรือเทียบเท่า",
        "responsibility": "AML Policy, KYC/CDD, ปปง.",
        "name": "(รอระบุ)",
    },
    # ── Assistant (2 ตำแหน่ง) ──
    {
        "id": "PSN-AS-01", "category": "Assistant",
        "position": "ผู้ช่วยโครงการ 1",
        "qty": 1, "qualification": "ปริญญาตรี+, ประสบการณ์ ≥ 2 ปี",
        "responsibility": "ประสานงาน, จัดทำเอกสาร",
        "name": "(รอระบุ)",
    },
    {
        "id": "PSN-AS-02", "category": "Assistant",
        "position": "ผู้ช่วยโครงการ 2",
        "qty": 1, "qualification": "ปริญญาตรี+, ประสบการณ์ ≥ 2 ปี",
        "responsibility": "สนับสนุน workshop, จัดการข้อมูล",
        "name": "(รอระบุ)",
    },
    # ── Coordinator (1 ตำแหน่ง) ──
    {
        "id": "PSN-CO-01", "category": "Coordinator",
        "position": "ผู้ประสานงานโครงการ",
        "qty": 1, "qualification": "ประสบการณ์ประสานงาน ≥ 3 ปี",
        "responsibility": "ประสานงานทุกฝ่าย, นัดประชุม, ติดตามกำหนด",
        "name": "(รอระบุ)",
    },
]

PERSONNEL_FIELDS = [
    "personnel_id", "category", "position", "quantity",
    "qualification", "responsibility", "name", "updated_at",
]


# ============================================================
# ★ REBALANCE — ซ่อม weights ใน CSV ที่มีอยู่แล้ว
# ============================================================
def rebalance_existing_weights(target_total: float = 100.0) -> dict:
    """
    ปรับ weights ของ deliverables ใน CSV ที่มีอยู่แล้วให้ผลรวม = target_total
    - ไม่ต้อง reseed ทั้งหมด → history ไม่หาย
    - Backup CSV ก่อนแก้
    - Idempotent: ถ้า weights รวม = target แล้ว → no-op

    Returns:
        dict = {
            "ok": bool,
            "message": str,
            "changed": int,
            "old_total": float,
            "new_total": float,
            "backup": str,
        }
    """
    path = DATA / "master" / "deliverable_master.csv"
    if not path.exists():
        return {
            "ok": False,
            "message": "ไม่พบไฟล์ deliverable_master.csv",
            "changed": 0,
            "old_total": 0.0,
            "new_total": 0.0,
            "backup": "",
        }

    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as e:
        return {
            "ok": False,
            "message": f"อ่าน CSV ไม่ได้: {e}",
            "changed": 0,
            "old_total": 0.0,
            "new_total": 0.0,
            "backup": "",
        }

    # Filter เฉพาะ valid rows (milestone_id ขึ้นต้น MLS)
    if "milestone_id" not in df.columns or "weight" not in df.columns:
        return {
            "ok": False,
            "message": "CSV ไม่มีคอลัมน์ milestone_id หรือ weight",
            "changed": 0,
            "old_total": 0.0,
            "new_total": 0.0,
            "backup": "",
        }

    valid_mask = df["milestone_id"].astype(str).str.startswith("MLS")
    if not valid_mask.any():
        return {
            "ok": False,
            "message": "ไม่พบ valid deliverables (milestone_id ขึ้นต้น MLS)",
            "changed": 0,
            "old_total": 0.0,
            "new_total": 0.0,
            "backup": "",
        }

    valid_weights = pd.to_numeric(
        df.loc[valid_mask, "weight"], errors="coerce"
    ).fillna(0.0)

    old_total = float(valid_weights.sum())

    # ถ้าอยู่ใกล้เป้าแล้ว → no-op
    if abs(old_total - target_total) < 0.01:
        return {
            "ok": True,
            "message": f"Weights ถูกต้องแล้ว (รวม = {old_total:.2f}%)",
            "changed": 0,
            "old_total": old_total,
            "new_total": old_total,
            "backup": "",
        }

    if old_total <= 0:
        return {
            "ok": False,
            "message": "ผลรวม weights = 0 ไม่สามารถ normalize ได้",
            "changed": 0,
            "old_total": old_total,
            "new_total": 0.0,
            "backup": "",
        }

    # Normalize
    factor = target_total / old_total
    new_weights = (valid_weights * factor).round(2)

    # Fix rounding → ปรับที่ตัวที่มีค่ามากสุด
    diff = round(target_total - new_weights.sum(), 2)
    if abs(diff) >= 0.01:
        max_idx = new_weights.idxmax()
        new_weights.loc[max_idx] = round(new_weights.loc[max_idx] + diff, 2)

    new_total = float(new_weights.sum())

    # Backup
    backup_path = ""
    try:
        from repositories.base_repo import _backup
        b = _backup(path)
        backup_path = str(b) if b else ""
    except Exception:
        pass

    # Apply + Save
    df.loc[valid_mask, "weight"] = new_weights
    try:
        df.to_csv(path, index=False, encoding="utf-8-sig")
    except Exception as e:
        return {
            "ok": False,
            "message": f"เขียน CSV ไม่ได้: {e}",
            "changed": 0,
            "old_total": old_total,
            "new_total": new_total,
            "backup": backup_path,
        }

    return {
        "ok": True,
        "message": (
            f"ปรับ weights สำเร็จ: {old_total:.2f}% → {new_total:.2f}% "
            f"({len(new_weights)} รายการ)"
        ),
        "changed": int(len(new_weights)),
        "old_total": old_total,
        "new_total": new_total,
        "backup": backup_path,
    }


# ============================================================
# ★ FORCE RESEED — เขียนทับ master ทั้งหมดด้วยค่าเริ่มต้น
# ============================================================
def force_reseed_master(backup: bool = True) -> dict:
    """
    Force reseed master CSV files ทั้งหมด
    (project, milestone, deliverable, personnel)

    - Backup ไฟล์เดิมก่อน (ถ้า backup=True)
    - ลบไฟล์เดิม + เรียก ensure_seed_data() เพื่อสร้างใหม่
    - History files ไม่ถูกลบ → ข้อมูล progress/meeting ฯลฯ ยังอยู่

    Returns:
        dict = {"ok": bool, "message": str, "backed_up": [...], "reseeded": [...]}
    """
    result = {
        "ok": True,
        "message": "",
        "backed_up": [],
        "reseeded": [],
        "errors": [],
    }

    master_dir = DATA / "master"
    master_dir.mkdir(parents=True, exist_ok=True)

    files_to_reseed = [
        "project_master.csv",
        "milestone_master.csv",
        "deliverable_master.csv",
        "personnel_master.csv",
    ]

    # ---- Backup + Delete ----
    for fname in files_to_reseed:
        fp = master_dir / fname
        if not fp.exists():
            continue

        if backup:
            try:
                from repositories.base_repo import _backup
                b = _backup(fp)
                if b:
                    result["backed_up"].append(Path(b).name)
            except Exception as e:
                result["errors"].append(f"backup {fname}: {e}")

        try:
            fp.unlink()
        except Exception as e:
            result["errors"].append(f"delete {fname}: {e}")

    # ---- Reseed ----
    try:
        ensure_seed_data()
        result["reseeded"] = files_to_reseed
        result["message"] = (
            f"Reseed master data สำเร็จ — {len(result['reseeded'])} ไฟล์ "
            f"(backup {len(result['backed_up'])} ไฟล์)"
        )
    except Exception as e:
        result["ok"] = False
        result["message"] = f"Reseed ล้มเหลว: {type(e).__name__}: {e}"

    return result


# ============================================================
# MAIN BOOTSTRAP
# ============================================================
def ensure_seed_data():
    """
    สร้าง master + history CSV เริ่มต้น (ถ้ายังไม่มี)

    ★ สำคัญ: จะ normalize weights ของ deliverables ให้รวม = 100.00% เสมอ
      (DELIVERABLES_FULL มี weight รวม 95.00% → ระบบ scale ให้เป็น 100.00%)
    """
    for d in ["master", "history", "audit", "backup"]:
        (DATA / d).mkdir(parents=True, exist_ok=True)

    cfg = load_settings()

    # ────────────────────────────────────────────────────────────
    # PROJECT MASTER
    # ────────────────────────────────────────────────────────────
    proj = DATA / "master" / "project_master.csv"
    if not proj.exists():
        df = pd.DataFrame([{
            "project_id":           "PRJ-2026-0001",
            "project_name":         "จ้างที่ปรึกษากำกับดูแลระบบชำระดุลส่วนกลาง (CCH)",
            "contract_no":          cfg.get("project_defaults", {}).get("contract_no", "TOR-CCH-2569"),
            "consultant_name":      cfg.get("project_defaults", {}).get("consultant_name", "จุฬาลงกรณ์มหาวิทยาลัย"),
            "contract_date":        cfg.get("project_defaults", {}).get("contract_date", "2026-08-18"),
            "project_start_date":   cfg.get("project_defaults", {}).get("project_start_date", "2026-08-18"),
            "project_duration_days": cfg["project_defaults"]["duration_days"],
            "project_end_date":     cfg.get("project_defaults", {}).get("project_end_date", "2027-08-13"),
            "total_contract_value": cfg["project_defaults"]["contract_value"],
            "project_manager":      cfg.get("project_defaults", {}).get("project_manager", "ผู้จัดการโครงการ กทพ."),
            "status":               "Active",
            "created_at":           "2026-08-18 09:00:00",
            "updated_at":           "2026-08-18 09:00:00",
        }])
        df.to_csv(proj, index=False, encoding="utf-8-sig")

    # ────────────────────────────────────────────────────────────
    # MILESTONE MASTER
    # ────────────────────────────────────────────────────────────
    ms = DATA / "master" / "milestone_master.csv"
    if not ms.exists():
        start = date(2026, 8, 18)
        rows = []
        for m in cfg["milestones"]:
            # ใช้ due_date จาก config ถ้ามี ไม่งั้นคำนวณจาก due_day
            due_iso = m.get("due_date") or (start + timedelta(days=m["due_day"])).isoformat()
            rows.append({
                "milestone_id":    f"MLS-{m['no']:02d}",
                "project_id":      "PRJ-2026-0001",
                "milestone_no":    m["no"],
                "milestone_name":  m["name"],
                "tor_reference":   f"ข้อ 7.{m['no']}",
                "due_day":         m["due_day"],
                "due_date":        due_iso,
                "payment_percent": m["percent"],
                "payment_amount":  cfg["project_defaults"]["contract_value"] * m["percent"] / 100,
                "submission_date": "",
                "acceptance_date": "",
                "payment_date":    "",
                "status":          "Not Started",
                "updated_at":      "2026-08-18 09:00:00",
            })
        pd.DataFrame(rows).to_csv(ms, index=False, encoding="utf-8-sig")

    # ────────────────────────────────────────────────────────────
    # DELIVERABLE MASTER — ★ Full Timeline (Normalized Weights)
    # ────────────────────────────────────────────────────────────
    dl = DATA / "master" / "deliverable_master.csv"
    if not dl.exists():
        # ★★ Normalize weights ให้รวม = 100.00% พอดี ★★
        normalized = normalize_deliverable_weights(
            DELIVERABLES_FULL, target_total=100.0, round_to=2
        )

        # Sanity check
        total_w = sum(d["weight"] for d in normalized)
        assert abs(total_w - 100.0) < 0.01, (
            f"Normalization ผิดพลาด: ผลรวม = {total_w}% (ต้องเป็น 100.0%)"
        )

        rows = []
        for d in normalized:
            rows.append({
                "deliverable_id":     d["id"],
                "milestone_id":       d["ms"],
                "tor_clause":         d["tor"],
                "deliverable_name":   d["name"],
                "description":        d["desc"],
                "required_output":    d["output"],
                "required_evidence":  d["evidence"],
                "weight":             d["weight"],
                "planned_start":      d["start"],
                "planned_finish":     d["finish"],
                "actual_start":       "",
                "actual_finish":      "",
                "status":             "Not Started",
                "compliance_status":  "Not Checked",
                "reviewer":           "",
                "review_date":        "",
                "review_comment":     "",
                "updated_at":         "2026-08-18 09:00:00",
            })
        pd.DataFrame(rows).to_csv(dl, index=False, encoding="utf-8-sig")

    # ────────────────────────────────────────────────────────────
    # ★ PERSONNEL MASTER (TOR ข้อ 12)
    # ────────────────────────────────────────────────────────────
    psn = DATA / "master" / "personnel_master.csv"
    if not psn.exists():
        rows = []
        for p in PERSONNEL_FULL:
            rows.append({
                "personnel_id":   p["id"],
                "category":       p["category"],
                "position":       p["position"],
                "quantity":       p["qty"],
                "qualification":  p["qualification"],
                "responsibility": p["responsibility"],
                "name":           p["name"],
                "updated_at":     "2026-08-18 09:00:00",
            })
        pd.DataFrame(rows).to_csv(psn, index=False, encoding="utf-8-sig")

    # ────────────────────────────────────────────────────────────
    # HISTORY FILES (bootstrap empty)
    # ────────────────────────────────────────────────────────────
    from repositories.progress_repo import ProgressRepo
    from repositories.meeting_repo import MeetingRepo, ResolutionRepo
    from repositories.acceptance_repo import AcceptanceRepo, PaymentRepo
    from repositories.issue_repo import IssueRepo
    from repositories.action_repo import ActionRepo

    ProgressRepo()
    MeetingRepo()
    ResolutionRepo()
    AcceptanceRepo()
    PaymentRepo()
    IssueRepo()
    ActionRepo()