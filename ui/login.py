"""Login Page — หน้าเข้าสู่ระบบ"""
import streamlit as st
from core.auth import (
    authenticate, login_session, ensure_users_file,
    DEFAULT_PASSWORDS,
)
from core.audit import append_audit


def render():
    # ตรวจสอบ users.json
    ensure_users_file()

    # Hide sidebar ในหน้า login
    st.markdown(
        """
        <style>
            [data-testid="stSidebar"] { display: none; }
            [data-testid="collapsedControl"] { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Center layout
    _, center, _ = st.columns([1, 2, 1])

    with center:
        st.markdown(
            """
            <div style="text-align:center;padding:30px 0 20px 0;">
                <div style="font-size:56px;line-height:1;">🎯</div>
                <div style="font-size:26px;font-weight:800;color:#003366;margin-top:8px;">
                    CCH Consultant Monitoring
                </div>
                <div style="font-size:13px;color:#666;margin-top:4px;">
                    โครงการจ้างที่ปรึกษากำกับดูแล CCH · การทางพิเศษแห่งประเทศไทย
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("---")

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
                    st.success(f"✅ ยินดีต้อนรับ **{user.get('full_name', user.get('username'))}**")
                    st.rerun()