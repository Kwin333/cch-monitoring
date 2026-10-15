"""CCH Consultant Monitoring System — Focus 1.3 & 1.5

Main Entry Point:
- Bootstrap master data + users
- Authentication gate (login / session timeout)
- Role-Based Access Control (RBAC) via core.permissions
- View-only mode banner สำหรับหน้าที่อ่านได้อย่างเดียว
- Audit logging (login / logout / navigation)

★ v3 — แก้ไข:
- 🕒 ใช้ Bangkok timezone (now_str) แทน datetime.now() (UTC)
- 🕒 Session elapsed คำนวณด้วย Bangkok time
- 🕒 Footer แสดงเวลาไทย
- 🕒 Sidebar footer © year ใช้ Bangkok year

★ v2: เพิ่ม Logo EXAT ใน Sidebar + Footer
"""
import streamlit as st
import base64
from pathlib import Path
from datetime import datetime, timedelta
import importlib
import traceback

# ★ v3: Bangkok timezone helpers
import pytz
from core.time_util import now_str, today_str, BKK

from core.permissions import (
    can_view, can_edit, can_delete, can_approve,
    get_accessible_pages, get_landing_page,
    get_role_badge, get_role_description,
)


# ============================================================
# ★ v3: TIME HELPERS (Bangkok)
# ============================================================
def _now_bkk() -> datetime:
    """คืน datetime ปัจจุบันใน Bangkok timezone (naive)"""
    return datetime.now(BKK).replace(tzinfo=None)


def _now_bkk_str() -> str:
    """คืน string เวลาไทย format DD/MM/YYYY HH:MM:SS"""
    return _now_bkk().strftime("%d/%m/%Y %H:%M:%S")


def _year_bkk() -> int:
    """คืนปี (ค.ศ.) ใน Bangkok timezone"""
    return _now_bkk().year


# ============================================================
# ★ LOGO HELPER
# ============================================================
def _get_logo_base64() -> str:
    """อ่านไฟล์ Logo เป็น base64 string (รองรับหลาย path)"""
    possible_paths = [
        Path(__file__).parent / "assets" / "exat_logo.png",
        Path(__file__).parent.parent / "assets" / "exat_logo.png",
        Path("assets") / "exat_logo.png",
    ]
    for logo_path in possible_paths:
        if logo_path.exists():
            try:
                with open(logo_path, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                continue
    return ""


# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="CCH Consultant Monitoring | กทพ.",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": (
            "**CCH Consultant Monitoring System**\n\n"
            "ระบบติดตามที่ปรึกษากำกับดูแล CCH (ข้อ 1.3 + 1.5)\n\n"
            "การทางพิเศษแห่งประเทศไทย (กทพ.)\n\n"
            "เวอร์ชัน: v1.0 · Evidence-based Monitoring"
        ),
    },
)


# ============================================================
# GLOBAL CSS
# ============================================================
st.markdown(
    """
    <style>
        /* ═══════════════════════════════════════════════════
           Sidebar primary button (logout)
           ═══════════════════════════════════════════════════ */
        div[data-testid="stSidebar"] button[kind="primary"] {
            background: linear-gradient(90deg, #D32F2F 0%, #B71C1C 100%);
            border: none;
        }
        div[data-testid="stSidebar"] button[kind="primary"]:hover {
            background: linear-gradient(90deg, #B71C1C 0%, #8B0000 100%);
        }

        /* ═══════════════════════════════════════════════════
           Page layout — ให้ header ไม่ถูกตัด
           ═══════════════════════════════════════════════════ */
        .block-container {
            padding-top: 3.5rem !important;
            padding-bottom: 2rem !important;
            max-width: 100% !important;
        }

        .block-container h1 {
            padding-top: 0 !important;
            margin-top: 0 !important;
            line-height: 1.3 !important;
            overflow: visible !important;
        }

        header[data-testid="stHeader"] {
            background: transparent !important;
            height: 3rem !important;
        }

        div[data-testid="stToolbar"] {
            top: 0.5rem !important;
        }

        div[data-testid="stDecoration"] {
            display: none !important;
        }

        /* ═══════════════════════════════════════════════════
           ★ Logo styling
           ═══════════════════════════════════════════════════ */
        .exat-logo-sidebar {
            text-align: center;
            padding: 8px 0 4px 0;
            margin-bottom: 8px;
            border-bottom: 1px solid #E0E6ED;
        }
        .exat-logo-sidebar img {
            width: 100px;
            height: auto;
            opacity: 0.95;
        }
        .exat-logo-footer {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            justify-content: center;
            width: 100%;
            padding: 10px 0 6px 0;
            border-top: 1px solid #E0E6ED;
            margin-top: 20px;
        }
        .exat-logo-footer img {
            height: 28px;
            width: auto;
            opacity: 0.7;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# BOOTSTRAP — Master Data
# ============================================================
try:
    from bootstrap import ensure_seed_data
    ensure_seed_data()
except Exception as e:
    st.error(f"❌ Bootstrap master data ล้มเหลว: {e}")
    st.code(traceback.format_exc())
    st.stop()


# ============================================================
# BOOTSTRAP — Auth
# ============================================================
try:
    from core.auth import (
        ensure_users_file, is_logged_in, is_session_expired,
        logout_session, touch_activity, get_current_user, change_password,
    )
    ensure_users_file()
except Exception as e:
    st.error(f"❌ Bootstrap auth ล้มเหลว: {e}")
    st.code(traceback.format_exc())
    st.stop()


# ============================================================
# BOOTSTRAP — Permissions
# ============================================================
try:
    from core.permissions import (
        can_view, can_edit, can_delete, can_approve,
        get_accessible_pages, get_landing_page,
        get_role_badge, get_role_description,
    )
except Exception as e:
    st.error(f"❌ Bootstrap permissions ล้มเหลว: {e}")
    st.code(traceback.format_exc())
    st.stop()


# ============================================================
# AUTH GATE
# ============================================================
def _render_login_and_stop(reason: str | None = None):
    if reason:
        st.warning(reason)
    try:
        from ui import login as login_ui
        login_ui.render()
    except Exception as e:
        st.error(f"❌ โหลดหน้า Login ล้มเหลว: {e}")
        st.code(traceback.format_exc())
    st.stop()


if not is_logged_in():
    _render_login_and_stop()

if is_session_expired():
    logout_session()
    _render_login_and_stop("⏰ Session หมดอายุ — กรุณาเข้าสู่ระบบใหม่")

touch_activity()


# ============================================================
# USER INFO
# ============================================================
current_user = get_current_user()
user = current_user.get("username", "")
role = current_user.get("role", "readonly")
full_name = current_user.get("full_name") or user
email = current_user.get("email", "")

if not user:
    logout_session()
    _render_login_and_stop("⚠️ ไม่พบข้อมูลผู้ใช้ใน session — กรุณาเข้าสู่ระบบใหม่")


# ============================================================
# PAGES REGISTRY
# ============================================================
ALL_PAGES = {
    "🏠 Dashboard":              "p01_dashboard",
    "⚙️ Project / Milestone":     "p02_project",
    "📦 Deliverable Master":     "p03_deliverable",
    "🔎 Deliverable Review":      "p04_deliverable_review",
    "📈 Progress Update":         "p05_progress",
    "📅 ประชุมกำกับดูแล (1.3)":   "p06_meeting",
    "✅ Action Tracker (1.3)":    "p07_action",
    "⚠️ Issue Tracker":           "p08_issue",
    "🔍 ตรวจรับ (1.5)":           "p09_acceptance",
    "💵 เบิกจ่าย (1.5)":          "p10_payment",
    "🕓 Timeline":                "p11_timeline",
    "📋 Audit Log":              "p12_audit",
    "🗑️ Voided Records":          "p14_void_registry",
    "🔧 Settings":                "p13_settings",
}

# ============================================================
# ROLE-BASED MENU FILTERING
# ============================================================
ACCESSIBLE_PAGES = get_accessible_pages(role, ALL_PAGES)

if not ACCESSIBLE_PAGES:
    st.error(
        f"🚫 Role `{role}` ไม่มีสิทธิ์เข้าถึงเมนูใดเลย — "
        f"กรุณาติดต่อผู้ดูแลระบบ"
    )
    if st.button("🚪 ออกจากระบบ"):
        logout_session()
        st.rerun()
    st.stop()


# ============================================================
# ★ SIDEBAR — Header (with Logo)
# ============================================================
logo_b64 = _get_logo_base64()

if logo_b64:
    st.sidebar.markdown(
        f"""
        <div class="exat-logo-sidebar">
            <img src="data:image/png;base64,{logo_b64}"
                 alt="EXAT Logo">
        </div>
        """,
        unsafe_allow_html=True,
    )

st.sidebar.title("🎯 CCH Monitoring")
st.sidebar.caption("โครงการจ้างที่ปรึกษากำกับดูแล CCH")


# ============================================================
# SIDEBAR — User Card
# ============================================================
role_badge = get_role_badge(role)
role_desc = get_role_description(role)

st.sidebar.markdown(
    f"""
    <div style="background:linear-gradient(135deg,#F0F4F8 0%,#E1E9F0 100%);
                border-radius:10px;padding:12px 14px;margin:6px 0 12px 0;
                border-left:4px solid #003366;">
        <div style="font-size:13px;font-weight:700;color:#003366;
                    display:flex;align-items:center;gap:6px;">
            👤 {full_name}
        </div>
        <div style="font-size:11px;color:#555;margin-top:4px;">
            <code style="font-size:10.5px;">{user}</code>
            &nbsp;·&nbsp; {role_badge}
        </div>
        <div style="font-size:10.5px;color:#888;margin-top:2px;">
            {role_desc}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# ★ v3: SIDEBAR — Session Info (Bangkok time)
# ============================================================
login_time_str = st.session_state.get("login_time", "")
if login_time_str:
    try:
        login_dt = datetime.fromisoformat(login_time_str)

        # ★ v3: ใช้ Bangkok time
        now_bkk = _now_bkk()

        # จัดการกรณี login_dt มี tzinfo หรือไม่มี
        if login_dt.tzinfo is not None:
            # ถ้ามี tzinfo → แปลงเป็น Bangkok แล้วตัด tzinfo
            login_dt_bkk = login_dt.astimezone(BKK).replace(tzinfo=None)
        else:
            # ถ้าไม่มี tzinfo → สมมติว่าเป็น Bangkok time แล้ว
            login_dt_bkk = login_dt

        elapsed = now_bkk - login_dt_bkk
        mins = int(elapsed.total_seconds() // 60)

        if mins < 0:
            # กรณี login_time เป็น UTC → elapsed จะติดลบ → fallback
            st.sidebar.caption("🕒 เข้าใช้ระบบ: เมื่อสักครู่")
        elif mins < 60:
            elapsed_txt = f"{mins} นาที"
            st.sidebar.caption(f"🕒 เข้าใช้ระบบ: {elapsed_txt}")
        else:
            elapsed_txt = f"{mins // 60} ชม. {mins % 60} นาที"
            st.sidebar.caption(f"🕒 เข้าใช้ระบบ: {elapsed_txt}")
    except Exception:
        pass


# ============================================================
# SIDEBAR — Menu
# ============================================================
st.sidebar.markdown("---")

nav_key = "nav_choice"
if nav_key in st.session_state and st.session_state[nav_key] not in ACCESSIBLE_PAGES:
    st.session_state.pop(nav_key, None)

choice = st.sidebar.radio(
    "📚 เมนู",
    list(ACCESSIBLE_PAGES.keys()),
    key=nav_key,
)

current_page_key = ACCESSIBLE_PAGES[choice]


# ============================================================
# GUARD — Double check
# ============================================================
if not can_view(current_page_key, role):
    st.error(f"🔒 คุณไม่มีสิทธิ์เข้าถึงหน้านี้ (`{current_page_key}`)")
    st.stop()


# ============================================================
# SIDEBAR — Change Password
# ============================================================
with st.sidebar.expander("🔑 เปลี่ยนรหัสผ่าน", expanded=False):
    with st.form("sidebar_change_pwd", clear_on_submit=True):
        old_pwd = st.text_input("รหัสเดิม", type="password", key="sb_old_pwd")
        new_pwd = st.text_input("รหัสใหม่", type="password", key="sb_new_pwd")
        confirm_pwd = st.text_input("ยืนยันรหัสใหม่", type="password", key="sb_confirm_pwd")

        if st.form_submit_button("💾 เปลี่ยน", use_container_width=True):
            if not old_pwd or not new_pwd:
                st.error("⚠️ กรอกให้ครบ")
            elif new_pwd != confirm_pwd:
                st.error("⚠️ รหัสใหม่ไม่ตรงกัน")
            elif len(new_pwd) < 6:
                st.error("⚠️ รหัสใหม่ต้อง ≥ 6 ตัวอักษร")
            else:
                ok, msg = change_password(user, old_pwd, new_pwd)
                if ok:
                    st.success(f"✅ {msg}")
                    try:
                        from core.audit import append_audit
                        append_audit(
                            user, "UPDATE", "AUTH", user,
                            old_value="", new_value="password changed",
                            reason="เปลี่ยนรหัสผ่านด้วยตนเอง",
                        )
                    except Exception:
                        pass
                else:
                    st.error(f"❌ {msg}")


# ============================================================
# SIDEBAR — Permission Info
# ============================================================
with st.sidebar.expander("🔐 สิทธิ์ของฉัน", expanded=False):
    st.markdown(f"**Role:** {role_badge}")
    st.markdown(f"**คำอธิบาย:** {role_desc}")
    st.markdown("---")
    st.markdown("**เมนูที่เข้าถึงได้:**")
    for menu_name, page_key in ACCESSIBLE_PAGES.items():
        edit_ok = can_edit(page_key, role)
        delete_ok = can_delete(page_key, role)
        approve_ok = can_approve(page_key, role)

        badges = []
        if edit_ok:
            badges.append("✏️")
        if delete_ok:
            badges.append("🗑️")
        if approve_ok:
            badges.append("✅")

        badge_str = " ".join(badges) if badges else "👁️"
        st.markdown(f"- {menu_name} `{badge_str}`")

    st.caption("✏️ แก้ · 🗑️ ลบ · ✅ อนุมัติ · 👁️ อ่าน")


# ============================================================
# SIDEBAR — Logout
# ============================================================
st.sidebar.markdown("---")

if st.sidebar.button(
    "🚪 ออกจากระบบ",
    use_container_width=True,
    type="primary",
    key="btn_logout",
):
    try:
        from core.audit import append_audit
        append_audit(
            user, "LOGOUT", "AUTH", user,
            old_value="", new_value="",
            reason="ผู้ใช้ออกจากระบบ",
        )
    except Exception:
        pass
    logout_session()
    st.rerun()


# ============================================================
# ★ SIDEBAR — Footer (with Logo) — Bangkok year
# ============================================================
st.sidebar.markdown("---")

if logo_b64:
    st.sidebar.markdown(
        f"""
        <div style="text-align:center;padding:6px 0 4px 0;">
            <img src="data:image/png;base64,{logo_b64}"
                 style="width:70px;height:auto;opacity:0.6;"
                 alt="EXAT">
        </div>
        """,
        unsafe_allow_html=True,
    )

st.sidebar.caption("v1.0 · Evidence-based Monitoring")
st.sidebar.caption(f"© 2026 กทพ. · {_year_bkk()}")   # ★ v3: Bangkok year


# ============================================================
# VIEW-ONLY BANNER
# ============================================================
READ_ONLY_PAGES = {"p01_dashboard", "p11_timeline", "p12_audit"}

if current_page_key not in READ_ONLY_PAGES and not can_edit(current_page_key, role):
    st.markdown(
        f"""
        <div style="background:#FFF8E1;border-left:5px solid #F57C00;
                    padding:12px 18px;border-radius:8px;margin-bottom:14px;">
            <div style="font-size:13px;color:#E65100;font-weight:700;">
                👁️ โหมดอ่านเท่านั้น (View-only)
            </div>
            <div style="font-size:12px;color:#555;margin-top:4px;">
                Role <code>{role}</code> ไม่มีสิทธิ์แก้ไขในหน้านี้ —
                สามารถดูข้อมูลได้อย่างเดียว
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# RENDER — Selected Page
# ============================================================
try:
    mod = importlib.import_module(f"ui.{current_page_key}")
    importlib.reload(mod)
    mod.render()
except ModuleNotFoundError as e:
    st.error(
        f"❌ ไม่พบโมดูล `ui.{current_page_key}` — กรุณาตรวจสอบไฟล์\n\n"
        f"**รายละเอียด:** `{e}`"
    )
    with st.expander("🔧 Debug"):
        st.code(traceback.format_exc())
except AttributeError as e:
    st.error(
        f"❌ โมดูล `ui.{current_page_key}` ไม่มีฟังก์ชัน `render()`\n\n"
        f"**รายละเอียด:** `{e}`"
    )
    with st.expander("🔧 Debug"):
        st.code(traceback.format_exc())
except Exception as e:
    st.error(f"❌ เกิดข้อผิดพลาดขณะแสดงหน้า `{choice}`")
    st.markdown(f"**Error:** `{type(e).__name__}: {e}`")
    with st.expander("🔧 Debug — Full Traceback", expanded=True):
        st.code(traceback.format_exc())


# ============================================================
# ★ v3: FOOTER (with Logo) — Bangkok time
# ============================================================
_bkk_time_str = _now_bkk_str()   # ★ v3: DD/MM/YYYY HH:MM:SS (Bangkok)

if logo_b64:
    st.markdown(
        f"""
        <div class="exat-logo-footer">
            <img src="data:image/png;base64,{logo_b64}" alt="EXAT">
            <div style="font-size:11.5px;color:#888;">
                🕒 {_bkk_time_str} · 
                👤 {full_name} ({role_badge}) · 
                📄 {choice}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown("---")
    st.caption(
        f"🕒 {_bkk_time_str} · "
        f"👤 {full_name} ({role_badge}) · "
        f"📄 {choice}"
    )