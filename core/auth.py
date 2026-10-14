"""Authentication & Authorization — Session-based (Robust Version)

เพิ่มความทนทาน:
- ตรวจสอบไฟล์ users.json ว่าใช้งานได้
- Self-heal: ถ้า users list ว่าง หรือ hash เสียหาย → regenerate
- ฟังก์ชัน force_recreate_users() สำหรับ reset ทั้งหมด
- verify_password() สำหรับ debug
"""
import json
import hashlib
import secrets
import shutil
from pathlib import Path
from datetime import datetime, timedelta

import streamlit as st

from core.time_util import now_str


# ============================================================
# PATHS
# ============================================================
ROOT = Path(__file__).parent.parent
USERS_FILE = ROOT / "config" / "users.json"
USERS_BACKUP_DIR = ROOT / "config" / "backups"

# ============================================================
# DEFAULT USERS
# ============================================================
DEFAULT_USERS_DATA = {
    "users": [
        {
            "username":  "admin",
            "full_name": "ผู้ดูแลระบบ",
            "role":      "admin",
            "email":     "admin@cch.local",
            "active":    True,
            "password":  "admin123",     # จะถูก hash ตอนสร้าง
        },
        {
            "username":  "monitoring01",
            "full_name": "เจ้าหน้าที่ติดตาม 1",
            "role":      "monitoring",
            "email":     "monitoring01@cch.local",
            "active":    True,
            "password":  "monitor123",
        },
        {
            "username":  "reviewer01",
            "full_name": "ผู้ตรวจสอบ 1",
            "role":      "reviewer",
            "email":     "reviewer01@cch.local",
            "active":    True,
            "password":  "review123",
        },
        {
            "username":  "committee01",
            "full_name": "คณะกรรมการตรวจรับ",
            "role":      "committee",
            "email":     "committee01@cch.local",
            "active":    True,
            "password":  "committee123",
        },
        {
            "username":  "supervisor01",
            "full_name": "ผู้บังคับบัญชา",
            "role":      "supervisor",
            "email":     "supervisor01@cch.local",
            "active":    True,
            "password":  "super123",
        },
        {
            "username":  "viewer",
            "full_name": "ผู้ชม (อ่านเท่านั้น)",
            "role":      "readonly",
            "email":     "viewer@cch.local",
            "active":    True,
            "password":  "viewer123",
        },
    ],
    "settings": {
        "session_timeout_minutes":  60,
        "allow_self_register":      False,
        "default_role_on_register": "readonly",
    },
}

# Default passwords — ใช้แสดงในหน้า Login (demo)
DEFAULT_PASSWORDS = {
    "admin":         "admin123",
    "monitoring01":  "monitor123",
    "reviewer01":    "review123",
    "committee01":   "committee123",
    "supervisor01":  "super123",
    "viewer":        "viewer123",
}


# ============================================================
# HASHING
# ============================================================
def _hash_password(password: str, salt: str) -> str:
    """SHA-256(salt::password) — demo; production ควร bcrypt/argon2"""
    data = f"{salt}::{password}".encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _new_salt() -> str:
    return secrets.token_hex(16)


def verify_password(username: str, password: str) -> dict:
    """ตรวจรหัสผ่าน — คืนผลลัพธ์ละเอียด (สำหรับ debug)"""
    data = _load_users_file()
    for u in data.get("users", []):
        if u.get("username", "").lower() == (username or "").strip().lower():
            salt = u.get("salt", "")
            expected = u.get("password_hash", "")
            computed = _hash_password(password, salt)
            return {
                "found":          True,
                "username":       u.get("username"),
                "active":         u.get("active", True),
                "has_salt":       bool(salt),
                "has_hash":       bool(expected),
                "hash_match":     computed == expected,
                "expected_hash":  expected[:12] + "..." if expected else "",
                "computed_hash":  computed[:12] + "...",
            }
    return {"found": False, "username": username}


# ============================================================
# FILE I/O
# ============================================================
def _load_users_file() -> dict:
    if not USERS_FILE.exists():
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_users_file(data: dict) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _backup_users_file() -> Path | None:
    """สำรอง users.json ก่อนแก้"""
    if not USERS_FILE.exists():
        return None
    USERS_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = USERS_BACKUP_DIR / f"users_{stamp}.json"
    try:
        shutil.copy2(USERS_FILE, backup_path)
        return backup_path
    except Exception:
        return None


# ============================================================
# HEALTH CHECK
# ============================================================
def _is_users_file_healthy(data: dict) -> bool:
    """ตรวจว่า users.json ใช้ได้หรือยัง"""
    if not isinstance(data, dict):
        return False

    users = data.get("users", [])
    if not isinstance(users, list) or len(users) == 0:
        return False

    # ต้องมีอย่างน้อย 1 user ที่ hash ครบ
    valid_count = 0
    for u in users:
        if not isinstance(u, dict):
            continue
        if (
            u.get("username")
            and u.get("salt")
            and u.get("password_hash")
            and u.get("password_hash") not in ("", "PLACEHOLDER")
            and len(u.get("salt", "")) >= 16
            and len(u.get("password_hash", "")) == 64  # SHA-256 hex
        ):
            valid_count += 1

    return valid_count > 0


# ============================================================
# BOOTSTRAP / SELF-HEAL
# ============================================================
def _build_default_users_data() -> dict:
    """สร้างข้อมูล users ใหม่จาก DEFAULT_USERS_DATA"""
    users = []
    for u in DEFAULT_USERS_DATA["users"]:
        pwd = u.pop("password", "changeme")
        salt = _new_salt()
        users.append({
            **u,
            "salt":          salt,
            "password_hash": _hash_password(pwd, salt),
            "created_at":    now_str(),
        })
        # คืน password กลับเข้า dict (เพื่อไม่ให้ mutates original)
        u["password"] = pwd
    return {
        "users":    users,
        "settings": DEFAULT_USERS_DATA["settings"],
    }


def ensure_users_file() -> None:
    """
    สร้าง/ซ่อมแซม users.json
    - ถ้าไม่มีไฟล์ → สร้างใหม่
    - ถ้ามีแต่ไม่ healthy → backup + สร้างใหม่
    """
    if not USERS_FILE.exists():
        _save_users_file(_build_default_users_data())
        return

    data = _load_users_file()
    if not _is_users_file_healthy(data):
        # backup ของเดิมไว้ (เผื่ออยากกู้คืน)
        _backup_users_file()
        # regenerate
        _save_users_file(_build_default_users_data())


def force_recreate_users() -> tuple[bool, str]:
    """ลบ users.json และสร้างใหม่ — ใช้เมื่อ login ไม่ได้เลย"""
    try:
        if USERS_FILE.exists():
            _backup_users_file()
            USERS_FILE.unlink()
        _save_users_file(_build_default_users_data())
        return True, "Recrate users.json สำเร็จ — ล็อกอินด้วย admin/admin123"
    except Exception as e:
        return False, f"ล้มเหลว: {type(e).__name__}: {e}"


# ============================================================
# AUTHENTICATION
# ============================================================
def authenticate(username: str, password: str) -> dict | None:
    """คืน user dict ถ้าถูกต้อง, None ถ้าไม่, {'_error': 'inactive'} ถ้าถูกปิด"""
    # Self-heal ก่อนตรวจ
    ensure_users_file()

    data = _load_users_file()
    users = data.get("users", [])
    uname = (username or "").strip().lower()

    for u in users:
        if u.get("username", "").lower() != uname:
            continue
        if not u.get("active", True):
            return {"_error": "inactive"}
        salt = u.get("salt", "")
        expected = u.get("password_hash", "")
        computed = _hash_password(password, salt)
        if computed == expected:
            return u
        return None
    return None


def create_user(username, password, full_name, role, email="") -> tuple[bool, str]:
    uname = (username or "").strip().lower()
    if not uname:
        return False, "ต้องระบุ Username"
    if len(password) < 6:
        return False, "รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร"

    data = _load_users_file()
    users = data.get("users", [])

    if any(u.get("username", "").lower() == uname for u in users):
        return False, f"Username `{uname}` มีอยู่แล้ว"

    salt = _new_salt()
    users.append({
        "username":      uname,
        "full_name":     full_name or uname,
        "role":          role or "readonly",
        "email":         email,
        "active":        True,
        "salt":          salt,
        "password_hash": _hash_password(password, salt),
        "created_at":    now_str(),
    })
    data["users"] = users
    _save_users_file(data)
    return True, f"สร้างผู้ใช้ `{uname}` สำเร็จ"


def change_password(username, old_password, new_password) -> tuple[bool, str]:
    user = authenticate(username, old_password)
    if user is None:
        return False, "รหัสผ่านเดิมไม่ถูกต้อง"
    if len(new_password) < 6:
        return False, "รหัสผ่านใหม่ต้องมีอย่างน้อย 6 ตัวอักษร"

    data = _load_users_file()
    for u in data.get("users", []):
        if u.get("username", "").lower() == username.lower():
            salt = _new_salt()
            u["salt"] = salt
            u["password_hash"] = _hash_password(new_password, salt)
            u["updated_at"] = now_str()
            break
    _save_users_file(data)
    return True, "เปลี่ยนรหัสผ่านสำเร็จ"


def reset_password(username, new_password, admin_user="admin") -> tuple[bool, str]:
    if len(new_password) < 6:
        return False, "รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร"

    data = _load_users_file()
    found = False
    for u in data.get("users", []):
        if u.get("username", "").lower() == username.lower():
            salt = _new_salt()
            u["salt"] = salt
            u["password_hash"] = _hash_password(new_password, salt)
            u["updated_at"] = now_str()
            found = True
            break
    if not found:
        return False, f"ไม่พบผู้ใช้ `{username}`"
    _save_users_file(data)
    return True, f"Reset รหัสผ่าน `{username}` สำเร็จ"


def list_users() -> list[dict]:
    data = _load_users_file()
    users = data.get("users", [])
    safe = []
    for u in users:
        safe.append({k: v for k, v in u.items() if k not in ("password_hash", "salt")})
    return safe


def toggle_user_active(username) -> tuple[bool, str]:
    data = _load_users_file()
    for u in data.get("users", []):
        if u.get("username", "").lower() == username.lower():
            u["active"] = not u.get("active", True)
            _save_users_file(data)
            state = "เปิด" if u["active"] else "ปิด"
            return True, f"{state}การใช้งาน `{username}` สำเร็จ"
    return False, f"ไม่พบผู้ใช้ `{username}`"


def update_user_role(username, new_role) -> tuple[bool, str]:
    data = _load_users_file()
    for u in data.get("users", []):
        if u.get("username", "").lower() == username.lower():
            u["role"] = new_role
            u["updated_at"] = now_str()
            _save_users_file(data)
            return True, f"เปลี่ยน Role `{username}` → `{new_role}` สำเร็จ"
    return False, f"ไม่พบผู้ใช้ `{username}`"


# ============================================================
# SESSION
# ============================================================
def is_logged_in() -> bool:
    return bool(st.session_state.get("user"))


def get_current_user() -> dict:
    return {
        "username":  st.session_state.get("user", ""),
        "full_name": st.session_state.get("full_name", ""),
        "role":      st.session_state.get("role", ""),
        "email":     st.session_state.get("email", ""),
    }


def login_session(user: dict) -> None:
    st.session_state.user = user.get("username", "")
    st.session_state.full_name = user.get("full_name", user.get("username", ""))
    st.session_state.role = user.get("role", "readonly")
    st.session_state.email = user.get("email", "")
    st.session_state.login_time = datetime.now().isoformat()
    st.session_state.last_activity = datetime.now().isoformat()


def logout_session() -> None:
    for k in ["user", "full_name", "role", "email", "login_time", "last_activity"]:
        st.session_state.pop(k, None)


def touch_activity() -> None:
    st.session_state.last_activity = datetime.now().isoformat()


def is_session_expired() -> bool:
    data = _load_users_file()
    timeout_min = data.get("settings", {}).get("session_timeout_minutes", 60)
    last = st.session_state.get("last_activity")
    if not last:
        return False
    try:
        dt = datetime.fromisoformat(last)
        if datetime.now() - dt > timedelta(minutes=timeout_min):
            return True
    except Exception:
        pass
    return False


# ============================================================
# ROLES
# ============================================================
def has_role(*roles) -> bool:
    return st.session_state.get("role") in roles


def is_admin() -> bool:
    return has_role("admin")


def is_editor() -> bool:
    return has_role("admin", "monitoring", "reviewer", "committee", "supervisor")


def is_readonly() -> bool:
    return has_role("readonly")