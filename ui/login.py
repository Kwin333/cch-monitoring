"""Login Page — หน้าเข้าสู่ระบบ (พร้อม Logo EXAT)"""
import base64
from pathlib import Path
import streamlit as st

from core.auth import (
    authenticate, login_session, ensure_users_file,
    DEFAULT_PASSWORDS,
)
from core.audit import append_audit


# ═══════════════════════════════════════════════════════════
# ★ LOGO HELPER
# ═══════════════════════════════════════════════════════════
def _get_logo_base64() -> str:
    """อ่านไฟล์ Logo เป็น base64 string สำหรับฝังใน HTML"""
    # ลองหาหลาย ๆ path เพื่อรองรับทั้ง local และ Streamlit Cloud
    possible_paths = [
        Path(__file__).parent.parent / "assets" / "exat_logo.png",
        Path(__file__).parent / "assets" / "exat_logo.png",
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


# ═══════════════════════════════════════════════════════════
# MAIN RENDER
# ═══════════════════════════════════════════════════════════
def render():
    # ตรวจสอบ users.json
    ensure_users_file()

    # Hide sidebar ในหน้า login
    st.markdown(
        """
        <style>
            [data-testid="stSidebar"] { display: none; }
            [data-testid="collapsedControl"] { display: none; }

            /* ซ่อน decoration bar */
            div[data-testid="stDecoration"] { display: none !important; }

            /* ปรับ header ให้โปร่งใส */
            header[data-testid="stHeader"] {
                background: transparent !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # โหลด Logo
    logo_b64 = _get_logo_base64()

    # Center layout
    _, center, _ = st.columns([1, 2, 1])

    with center:
        # ═══════════════════════════════════════════════════════════
        # ★ LOGO + TITLE
        # ═══════════════════════════════════════════════════════════
        if logo_b64:
            # แสดง Logo
            st.markdown(
                f"""
                <div style="text-align:center;padding:20px 0 10px 0;">
                    <img src="data:image/png;base64,{logo_b64}"
                         style="width:180px;height:auto;
                                filter:drop-shadow(0 4px 12px rgba(0,51,102,0.12));"
                         alt="EXAT Logo">
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            # Fallback ถ้าไม่พบ Logo
            st.markdown(
                """
                <div style="text-align:center;padding:30px 0 10px 0;">
                    <div style="font-size:56px;line-height:1;">🎯</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Title
        st.markdown(
            """
            <div style="text-align:center;padding:4px 0 20px 0;">
                <div style="font-size:26px;font-weight:800;color:#003366;
                            line-height:1.2;">
                    CCH Consultant Monitoring
                </div>
                <div style="font-size:13px;color:#666;margin-top:6px;">
                    โครงการจ้างที่ปรึกษากำกับดูแลระบบชำระดุลส่วนกลาง (CCH)
                </div>
                <div style="font-size:13px;color:#666;margin-top:2px;">
                    การทางพิเศษแห่งประเทศไทย (กทพ.)
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("---")

        # ═══════════════════════════════════════════════════════════
        # LOGIN FORM
        # ═══════════════════════════════════════════════════════════
        with st.form("login_form", clear_on_submit=False):
            st.markdown("### 🔐 เข้าสู่ระบบ")

            username = st.text_input(
                "Username",
                value="",
                placeholder="admin / monitoring01 / ...",
                key="login_user",
            )
            password = st.text_input(
                "Password",
                value="",
                type="password",
                key="login_pwd",
            )

            submit = st.form_submit_button(
                "🚪 เข้าสู่ระบบ",
                type="primary",
                use_container_width=True,
            )

        if submit:
            if not username.strip() or not password:
                st.error("⚠️ กรุณากรอก Username และ Password")
            else:
                user = authenticate(username, password)
                if user is None:
                    st.error("❌ Username หรือ Password ไม่ถูกต้อง")
                    # Audit: failed login
                    try:
                        append_audit(
                            username.strip() or "unknown",
                            "LOGIN_FAILED",
                            "AUTH", "",
                            old_value="",
                            new_value="invalid credentials",
                            reason=f"IP: unknown · User: {username}",
                        )
                    except Exception:
                        pass
                elif isinstance(user, dict) and user.get("_error") == "inactive":
                    st.error("🚫 บัญชีนี้ถูกปิดการใช้งาน — กรุณาติดต่อผู้ดูแลระบบ")
                else:
                    login_session(user)
                    try:
                        append_audit(
                            user.get("username", ""),
                            "LOGIN",
                            "AUTH", user.get("username", ""),
                            old_value="",
                            new_value=f"role={user.get('role')}",
                            reason="เข้าสู่ระบบสำเร็จ",
                        )
                    except Exception:
                        pass
                    st.success(
                        f"✅ ยินดีต้อนรับ "
                        f"**{user.get('full_name', user.get('username'))}**"
                    )
                    st.rerun()

        # ═══════════════════════════════════════════════════════════
        # FOOTER
        # ═══════════════════════════════════════════════════════════
        st.markdown(
            """
            <div style="text-align:center;padding:10px 0 20px 0;
                        font-size:11.5px;color:#999;line-height:1.7;">
                💡 หากลืมรหัสผ่าน กรุณาติดต่อผู้ดูแลระบบ (admin)<br>
                © 2026 การทางพิเศษแห่งประเทศไทย<br>
                <span style="font-size:11px;color:#bbb;">
                    Evidence-based Monitoring · v1.0
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )