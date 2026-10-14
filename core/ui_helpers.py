"""UI Helpers — Reusable components สำหรับ delete confirmation"""
import streamlit as st
import random
import string


def _gen_challenge_code(length: int = 6) -> str:
    """สร้างรหัสยืนยัน 6 ตัว (A-Z + 0-9)"""
    chars = string.ascii_uppercase + string.digits
    # ตัดอักษรที่สับสน (O/0, I/1)
    chars = (
        chars.replace("O", "").replace("0", "")
             .replace("I", "").replace("1", "")
    )
    return "".join(random.choices(chars, k=length))


def render_hard_delete_form(repo, record_id: str, record_label: str,
                             on_success=None, key_prefix: str = "hd"):
    """
    แสดงฟอร์ม Hard Delete พร้อม 3-layer confirmation:
    1. Checkbox ยืนยัน
    2. พิมพ์รหัส 6 ตัว
    3. พิมพ์เหตุผล
    """
    st.markdown(
        f"""
        <div style="background:#FFEBEE;border:2px solid #D32F2F;
                    border-radius:10px;padding:16px 20px;margin:12px 0;">
            <div style="font-size:15px;font-weight:800;color:#B71C1C;
                        margin-bottom:8px;">
                🚨 คำเตือน — การลบแบบถาวร (Hard Delete)
            </div>
            <div style="font-size:12.5px;color:#333;line-height:1.7;">
                • ข้อมูลจะถูกลบ <b>ออกจากไฟล์ CSV อย่างถาวร</b><br>
                • <b>ไม่สามารถกู้คืนได้</b> จากหน้า UI<br>
                • จะมี <b>backup CSV</b> เก็บไว้ที่ <code>data/backup/</code><br>
                • Audit Log จะบันทึก <code>HARD_DELETE</code> ไว้เป็นหลักฐาน
            </div>
            <div style="font-size:12.5px;color:#333;margin-top:10px;">
                <b>Record:</b> <code>{record_label}</code>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Generate challenge code ใหม่ทุกครั้ง
    code_key = f"{key_prefix}_code"
    input_key = f"{key_prefix}_input"
    reason_key = f"{key_prefix}_reason"
    confirm_key = f"{key_prefix}_confirm"

    if code_key not in st.session_state:
        st.session_state[code_key] = _gen_challenge_code()

    challenge = st.session_state[code_key]

    st.markdown(
        f"""
        <div style="background:#FFF3E0;border-left:4px solid #F57C00;
                    padding:12px 16px;border-radius:8px;margin:10px 0;">
            <div style="font-size:12px;color:#666;">
                พิมพ์รหัสนี้เพื่อยืนยัน:
            </div>
            <div style="font-family:monospace;font-size:32px;
                        font-weight:900;letter-spacing:6px;
                        color:#E65100;margin-top:6px;
                        background:#FFF;padding:10px 16px;
                        border-radius:6px;text-align:center;
                        border:2px dashed #F57C00;">
                {challenge}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form(f"{key_prefix}_form"):
        typed = st.text_input(
            "พิมพ์รหัสยืนยัน",
            value="",
            key=input_key,
            placeholder=f"พิมพ์: {challenge}",
        )
        reason = st.text_area(
            "เหตุผลการลบ (ต้องอธิบายให้ชัดเจน)",
            value="",
            height=80,
            key=reason_key,
            placeholder="เช่น ลบข้อมูลทดสอบที่บันทึกผิดพลาด / ข้อมูลซ้ำซ้อน",
        )
        confirmed = st.checkbox(
            "☑️ ข้าพเจ้ายืนยันว่าต้องการลบข้อมูลนี้อย่างถาวร",
            value=False,
            key=confirm_key,
        )

        submitted = st.form_submit_button(
            "🚨 ลบถาวร (Hard Delete)",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        # Validate
        errors = []
        if typed.strip().upper() != challenge:
            errors.append("❌ รหัสยืนยันไม่ถูกต้อง")
        if not reason.strip():
            errors.append("❌ ต้องระบุเหตุผลการลบ")
        if len(reason.strip()) < 10:
            errors.append("❌ เหตุผลต้องมีอย่างน้อย 10 ตัวอักษร")
        if not confirmed:
            errors.append("❌ ต้องติ๊กยืนยัน")

        if errors:
            for e in errors:
                st.error(e)
        else:
            try:
                result = repo.hard_delete(
                    record_id=record_id,
                    reason=reason.strip(),
                    user=st.session_state.user,
                )
                # Reset challenge
                st.session_state.pop(code_key, None)
                st.session_state.pop(input_key, None)
                st.session_state.pop(reason_key, None)
                st.session_state.pop(confirm_key, None)

                st.success(
                    f"✅ ลบ `{record_id}` สำเร็จ — "
                    f"{result['deleted']} rows · "
                    f"เหลือ {result['rows_after']} rows"
                )
                if result.get("backup"):
                    st.info(f"💾 Backup: `{result['backup']}`")

                if on_success:
                    on_success(result)
                else:
                    st.rerun()
            except Exception as e:
                st.error(f"❌ {type(e).__name__}: {e}")


def render_dual_delete_panel(repo, record_id: str, record_label: str,
                              key_prefix: str = "dual"):
    """
    Panel รวม Soft + Hard Delete — ให้ผู้ใช้เลือก
    """
    st.markdown("### 🗑️ ตัวเลือกการลบ")

    tab_soft, tab_hard = st.tabs([
        "🟡 Soft Delete (แนะนำ)",
        "🔴 Hard Delete (ถาวร)",
    ])

    with tab_soft:
        st.markdown(
            """
            <div style="background:#FFF8E1;border-left:4px solid #F57C00;
                        padding:10px 14px;border-radius:8px;font-size:12.5px;">
                <b>🟡 Soft Delete = ซ่อนจาก UI</b><br>
                • ข้อมูลยังอยู่ใน CSV<br>
                • กู้คืนได้จากหน้า 🗑️ Voided Records<br>
                • Audit trail ครบถ้วน<br>
                • <b>แนะนำสำหรับการใช้งานปกติ</b>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("")
        soft_reason = st.text_area(
            "เหตุผลการซ่อน (บังคับ)",
            value="",
            height=70,
            key=f"{key_prefix}_soft_reason",
        )
        if st.button(
            "🟡 Soft Delete",
            key=f"{key_prefix}_soft_btn",
            type="primary",
            use_container_width=True,
        ):
            if not soft_reason.strip():
                st.error("⚠️ กรุณาระบุเหตุผล")
            else:
                try:
                    repo.soft_delete(
                        record_id, soft_reason.strip(), st.session_state.user
                    )
                    st.success(f"✅ ซ่อน `{record_id}` แล้ว")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ {e}")

    with tab_hard:
        from core.permissions import can_hard_delete
        if not can_hard_delete(st.session_state.get("role", "")):
            st.warning("🔒 Hard Delete ใช้ได้เฉพาะ admin เท่านั้น")
        else:
            render_hard_delete_form(
                repo, record_id, record_label,
                key_prefix=f"{key_prefix}_hd",
            )