"""Role-Based Access Control (RBAC) — Centralized Permissions Matrix

หลักการ:
- Least Privilege: ให้สิทธิ์เท่าที่จำเป็น
- Explicit: ทุกสิทธิ์ต้องประกาศชัดเจน
- Centralized: รวมในที่เดียว ง่ายต่อการตรวจสอบ

Menu Permissions:
- view:    เห็นเมนู + เข้าได้
- edit:    เพิ่ม/แก้ข้อมูลในหน้านั้น
- delete:  soft delete ได้
- approve: อนุมัติได้ (ตรวจรับ, เบิกจ่าย)
"""

# ============================================================
# ROLE DEFINITIONS
# ============================================================
ALL_ROLES = [
    "admin", "monitoring", "reviewer",
    "committee", "supervisor", "readonly",
]

# ============================================================
# PAGE PERMISSIONS MATRIX
# ============================================================
# แต่ละ page มี 4 permission levels
# - view:     ใครเข้าหน้านี้ได้
# - edit:     ใครเพิ่ม/แก้ข้อมูลได้
# - delete:   ใคร soft delete ได้
# - approve:  ใครอนุมัติได้ (ถ้ามี)
# ============================================================

PAGE_PERMISSIONS: dict[str, dict[str, set]] = {
    "p01_dashboard": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor", "readonly"},
        "edit":    set(),
        "delete":  set(),
        "approve": set(),
    },
    "p02_project": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor"},
        "edit":    {"admin", "monitoring"},
        "delete":  {"admin"},
        "approve": set(),
    },
    "p03_deliverable": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor"},
        "edit":    {"admin", "monitoring"},
        "delete":  {"admin", "monitoring"},
        "approve": set(),
    },
    "p04_deliverable_review": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor"},
        "edit":    {"admin", "monitoring", "reviewer"},
        "delete":  {"admin", "monitoring"},
        "approve": {"admin", "monitoring", "reviewer"},
    },
    "p05_progress": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor"},
        "edit":    {"admin", "monitoring"},
        "delete":  {"admin", "monitoring"},
        "approve": set(),
    },
    "p06_meeting": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor"},
        "edit":    {"admin", "monitoring", "committee"},
        "delete":  {"admin", "monitoring"},
        "approve": set(),
    },
    "p07_action": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor"},
        "edit":    {"admin", "monitoring", "reviewer", "committee"},
        "delete":  {"admin", "monitoring"},
        "approve": {"admin", "monitoring", "reviewer"},
    },
    "p08_issue": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor"},
        "edit":    {"admin", "monitoring", "reviewer"},
        "delete":  {"admin", "monitoring"},
        "approve": set(),
    },
    "p09_acceptance": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor"},
        "edit":    {"admin", "monitoring", "committee", "supervisor"},
        "delete":  {"admin", "monitoring"},
        "approve": {"admin", "committee", "supervisor"},
    },
    "p10_payment": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor"},
        "edit":    {"admin", "monitoring", "committee", "supervisor"},
        "delete":  {"admin", "monitoring"},
        "approve": {"admin", "committee", "supervisor"},
    },
    "p11_timeline": {
        "view":    {"admin", "monitoring", "reviewer", "committee", "supervisor", "readonly"},
        "edit":    set(),
        "delete":  set(),
        "approve": set(),
    },
    "p12_audit": {
        "view":    {"admin", "supervisor"},
        "edit":    set(),
        "delete":  set(),
        "approve": set(),
    },
    "p13_settings": {
        "view":    {"admin", "monitoring", "supervisor"},
        "edit":    {"admin"},
        "delete":  {"admin"},
        "approve": set(),
    },
    "p14_void_registry": {
        "view":    {"admin", "monitoring", "supervisor"},   # ← ให้ monitoring ดูได้
        "edit":    {"admin"},
        "delete":  {"admin"},
        "approve": set(),
    },
}


# ============================================================
# CORE FUNCTIONS
# ============================================================
def _get_perms(page_key: str) -> dict:
    return PAGE_PERMISSIONS.get(page_key, {})


def can_view(page_key: str, role: str) -> bool:
    if not page_key or not role:
        return False
    return role in _get_perms(page_key).get("view", set())


def can_edit(page_key: str, role: str) -> bool:
    if not page_key or not role:
        return False
    return role in _get_perms(page_key).get("edit", set())


def can_delete(page_key: str, role: str) -> bool:
    if not page_key or not role:
        return False
    return role in _get_perms(page_key).get("delete", set())


def can_approve(page_key: str, role: str) -> bool:
    if not page_key or not role:
        return False
    return role in _get_perms(page_key).get("approve", set())


def get_accessible_pages(role: str, all_pages: dict) -> dict:
    """
    กรอง pages ตาม role
    all_pages = {"🏠 Dashboard": "p01_dashboard", ...}
    """
    return {k: v for k, v in all_pages.items() if can_view(v, role)}


def get_landing_page(role: str, all_pages: dict) -> str | None:
    """คืนเมนูแรกที่ role เข้าถึงได้ (สำหรับ redirect)"""
    acc = get_accessible_pages(role, all_pages)
    if not acc:
        return None
    return list(acc.keys())[0]


# ============================================================
# INFO HELPERS (สำหรับ UI)
# ============================================================
ROLE_LABELS = {
    "admin":      ("🟥", "admin",      "ผู้ดูแลระบบ — สิทธิ์เต็ม"),
    "monitoring": ("🟦", "monitoring", "ผู้ติดตาม — เพิ่ม/แก้ข้อมูล"),
    "reviewer":   ("🟪", "reviewer",   "ผู้ตรวจ — Review deliverable"),
    "committee":  ("🟩", "committee",  "คณะกรรมการ — อนุมัติตรวจรับ"),
    "supervisor": ("🟨", "supervisor", "ผู้บังคับบัญชา — ดูภาพรวม"),
    "readonly":   ("⬜", "readonly",   "ผู้ชม — อ่านเฉพาะภาพรวม"),
}


def get_role_badge(role: str) -> str:
    """คืน badge สำหรับแสดงใน UI"""
    icon, label, _ = ROLE_LABELS.get(role, ("⚪", role, "-"))
    return f"{icon} {label}"


def get_role_description(role: str) -> str:
    return ROLE_LABELS.get(role, ("", "", "-"))[2]


def get_permission_summary(page_key: str) -> dict:
    """คืน summary ของหน้า — ใช้ใน settings/preview"""
    perms = _get_perms(page_key)
    return {
        "view":    sorted(perms.get("view", set())),
        "edit":    sorted(perms.get("edit", set())),
        "delete":  sorted(perms.get("delete", set())),
        "approve": sorted(perms.get("approve", set())),
    }

# ============================================================
# HARD DELETE PERMISSION
# ============================================================
HARD_DELETE_ROLES = {"admin"}   # ← เฉพาะ admin เท่านั้น


def can_hard_delete(role: str) -> bool:
    """ตรวจสิทธิ์ลบถาวร — admin เท่านั้น"""
    return role in HARD_DELETE_ROLES