"""Action Tracker (ข้อ 1.3) — Comprehensive Version (Clean)

ครอบคลุม:
- 📊 KPI Dashboard: ทั้งหมด, Open, Overdue, Completed, Verified + Overdue alert
- ➕ Add Action + auto-link Source Type/ID จาก Repo จริง
- 🔄 Update Status + Verification workflow
- 📜 History + Filter + Search + Card-style list
- 🗑️ Soft Delete + Restore (admin/monitoring)
- 📈 Charts: Status, Priority, Owner, Overdue by Owner
- 📥 CSV Export
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

from core.ids import new_id
from core.time_util import now_str, today_str
from core.audit import append_audit
from core.validator import validate_action_complete, ValidationError
from repositories.action_repo import ActionRepo
from repositories.meeting_repo import MeetingRepo, ResolutionRepo
from repositories.issue_repo import IssueRepo


# ============================================================
# CONSTANTS
# ============================================================
SOURCE_TYPES = [
    "Meeting", "Resolution", "Issue",
    "TOR Review", "Milestone Review",
    "Supervisor Instruction", "Other",
]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Open", "In Progress", "Completed", "Cancelled"]
VERIFICATION_STATUSES = ["Not Verified", "Pending", "Verified", "Rejected"]

PRIORITY_COLORS = {
    "Low": "#9E9E9E",
    "Medium": "#0B5ED7",
    "High": "#F57C00",
    "Critical": "#D32F2F",
}

STATUS_BADGES = {
    "Open": "🔴 เปิด",
    "In Progress": "🟠 กำลังทำ",
    "Completed": "🟢 เสร็จ",
    "Cancelled": "⚪ ยกเลิก",
}

VERIFY_BADGES = {
    "Not Verified": "⚪ ยังไม่ตรวจสอบ",
    "Pending": "🟡 รอตรวจสอบ",
    "Verified": "🟢 ตรวจสอบแล้ว",
    "Rejected": "🔴 ไม่ผ่าน",
}


# ============================================================
# HELPERS
# ============================================================
def _to_date(s):
    try:
        if pd.isna(s) or s in ("", None):
            return None
        return pd.to_datetime(str(s)).date()
    except Exception:
        return None


def _fmt_date(d):
    dd = _to_date(d)
    return dd.strftime("%d/%m/%Y") if dd else "-"


def _today():
    return date.today()


def _is_overdue(due, status):
    if status in ("Completed", "Cancelled"):
        return False
    dd = _to_date(due)
    return dd is not None and dd < _today()


def _days_left(due):
    dd = _to_date(due)
    return (dd - _today()).days if dd else None


def _priority_badge(p):
    return {
        "Low": "⚪ Low",
        "Medium": "🔵 Medium",
        "High": "🟠 High",
        "Critical": "🔴 Critical",
    }.get(p, p or "-")


def _reset_keys(prefix, preserve=()):
    for k in list(st.session_state.keys()):
        if k.startswith(prefix) and k not in preserve:
            st.session_state.pop(k, None)


def _tile(label, value, sub, color):
    return f"""
    <div style="background:#FFFFFF;border-radius:10px;padding:12px 14px;
                border-left:4px solid {color};
                box-shadow:0 2px 6px rgba(0,51,102,0.06);height:100%;">
        <div style="font-size:11.5px;color:#5A5A5A;font-weight:600;">{label}</div>
        <div style="font-size:22px;font-weight:700;color:#003366;
                    line-height:1.1;margin:4px 0;">{value}</div>
        <div style="font-size:11px;color:{color};">{sub}</div>
    </div>
    """


def _validate_action(data, prev_status=None):
    if not (data.get("description") or "").strip():
        raise ValidationError("⚠️ ต้องระบุ Description")
    if not (data.get("owner") or "").strip():
        raise ValidationError("⚠️ ต้องระบุ Owner")
    if not _to_date(data.get("due_date")):
        raise ValidationError("⚠️ ต้องระบุ Due Date")

    if data.get("status") == "Completed":
        validate_action_complete(
            data["status"],
            data.get("completion_date"),
            data.get("evidence"),
        )

    if data.get("verification_status") == "Verified":
        if not (data.get("verifier") or "").strip():
            raise ValidationError("⚠️ Verified ต้องระบุชื่อผู้ตรวจสอบ")
        if not _to_date(data.get("verification_date")):
            raise ValidationError("⚠️ Verified ต้องระบุวันที่ตรวจสอบ")
        if not (data.get("evidence") or "").strip():
            raise ValidationError("⚠️ Verified ต้องมี Evidence")

    if data.get("verification_status") == "Rejected":
        if not (data.get("comment") or "").strip():
            raise ValidationError("⚠️ Rejected ต้องระบุเหตุผล (Comment)")

    if prev_status == "Completed" and data.get("status") == "Open":
        raise ValidationError("⚠️ ไม่สามารถเปลี่ยนจาก Completed กลับเป็น Open ได้")


# ============================================================
# MAIN RENDER
# ============================================================
def render():
    st.title("✅ Action Tracker (ข้อ 1.3)")
    st.caption(
        "ติดตาม Action / มติ / ข้อสั่งการ — เชื่อมโยงกับ Meeting, Resolution, Issue "
        "และ workflow การตรวจสอบ"
    )

    # READ ONCE
    act_repo = ActionRepo()
    act_df = act_repo.read()

    try:
        mtg_df = MeetingRepo().read()
    except Exception:
        mtg_df = pd.DataFrame()
    try:
        res_df = ResolutionRepo().read()
    except Exception:
        res_df = pd.DataFrame()
    try:
        iss_df = IssueRepo().read()
    except Exception:
        iss_df = pd.DataFrame()

    # ---------- KPI ----------
    st.markdown("### 📊 ภาพรวม Actions")

    n_total = len(act_df)
    if n_total:
        n_open = int((act_df["status"] == "Open").sum())
        n_prog = int((act_df["status"] == "In Progress").sum())
        n_done = int((act_df["status"] == "Completed").sum())
        n_cancel = int((act_df["status"] == "Cancelled").sum())
        n_overdue = sum(
            1 for _, r in act_df.iterrows()
            if _is_overdue(r.get("due_date"), r.get("status"))
        )
        n_verified = int((act_df["verification_status"] == "Verified").sum())
    else:
        n_open = n_prog = n_done = n_cancel = n_overdue = n_verified = 0

    denom = n_total - n_cancel
    completion_rate = (n_done / denom * 100) if denom > 0 else 0.0

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(_tile("📋 ทั้งหมด", f"{n_total}",
                          f"ยกเลิก {n_cancel}", "#0B5ED7"),
                    unsafe_allow_html=True)
    with k2:
        st.markdown(_tile("🔴 Open", f"{n_open}",
                          f"🟠 In Progress {n_prog}", "#D32F2F"),
                    unsafe_allow_html=True)
    with k3:
        od_color = "#D32F2F" if n_overdue > 0 else "#2E7D32"
        st.markdown(_tile("⏰ เกินกำหนด", f"{n_overdue}",
                          "ต้องติดตามด่วน" if n_overdue else "ไม่มี",
                          od_color), unsafe_allow_html=True)
    with k4:
        st.markdown(_tile("🟢 เสร็จ", f"{n_done}",
                          f"Completion {completion_rate:.0f}%", "#2E7D32"),
                    unsafe_allow_html=True)
    with k5:
        st.markdown(_tile("✅ Verified", f"{n_verified}",
                          f"จาก {n_done} ที่เสร็จ", "#6A1B9A"),
                    unsafe_allow_html=True)

    if n_overdue > 0:
        st.markdown(
            f'<div style="background:#FFEBEE;border-left:4px solid #D32F2F;'
            f'padding:10px 14px;border-radius:8px;font-size:13px;margin-top:10px;color:#B71C1C;">'
            f'🚨 <b>มี Action เกินกำหนด {n_overdue} รายการ</b> — '
            f'ตรวจสอบได้ที่แท็บ "📜 ประวัติ & ติดตาม"'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ---------- TABS ----------
    t1, t2, t3, t4 = st.tabs([
        "➕ เพิ่ม / อัปเดต",
        "📜 ประวัติ & ติดตาม",
        "📈 Charts",
        "📥 CSV",
    ])

    # ============================================================
    # TAB 1 — ADD / UPDATE
    # ============================================================
    with t1:
        if "act_last_saved" in st.session_state:
            info = st.session_state.pop("act_last_saved")
            st.markdown(
                f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
                f'padding:10px 14px;border-radius:8px;font-size:13px;">'
                f'✅ <b>{info["mode"]} Action สำเร็จ</b> — '
                f'Action ID: <code>{info["id"]}</code>'
                f'</div>',
                unsafe_allow_html=True,
            )

        mode = st.radio(
            "โหมด",
            ["➕ เพิ่มใหม่", "🔄 อัปเดตสถานะ"],
            horizontal=True,
            key="act_mode",
        )

        # ---------- ADD ----------
        if mode == "➕ เพิ่มใหม่":
            st.markdown("### ➕ เพิ่ม Action ใหม่")

            st.markdown("**A. แหล่งที่มา**")
            cA1, cA2 = st.columns(2)

            src_type = cA1.selectbox(
                "Source Type",
                SOURCE_TYPES,
                key="act_src_type",
            )

            # Build source options ตาม type
            src_opts = ["-"]
            if src_type == "Resolution" and not res_df.empty:
                src_opts = ["-"] + res_df["resolution_id"].astype(str).tolist()
            elif src_type == "Meeting" and not mtg_df.empty:
                src_opts = ["-"] + mtg_df["meeting_id"].astype(str).tolist()
            elif src_type == "Issue" and not iss_df.empty:
                src_opts = ["-"] + iss_df["issue_id"].astype(str).tolist()

            def _fmt_src(x):
                if x == "-":
                    return "-"
                try:
                    if src_type == "Resolution" and not res_df.empty:
                        sub = res_df[res_df["resolution_id"] == x]
                        if not sub.empty:
                            return f"{x} — {str(sub['resolution_text'].iloc[0])[:50]}"
                    elif src_type == "Meeting" and not mtg_df.empty:
                        sub = mtg_df[mtg_df["meeting_id"] == x]
                        if not sub.empty:
                            return f"{x} — {sub['meeting_no'].iloc[0]}"
                    elif src_type == "Issue" and not iss_df.empty:
                        sub = iss_df[iss_df["issue_id"] == x]
                        if not sub.empty:
                            return f"{x} — {str(sub['description'].iloc[0])[:50]}"
                except Exception:
                    pass
                return x

            src_id = cA2.selectbox(
                "Source ID",
                src_opts,
                format_func=_fmt_src,
                key="act_src_id",
            )

            with st.form("act_add_form", clear_on_submit=False):
                st.markdown("**B. รายละเอียด Action**")
                desc = st.text_area(
                    "Description",
                    value=st.session_state.get("act_desc", ""),
                    height=90,
                    key="act_desc",
                    placeholder="ระบุสิ่งที่ต้องทำอย่างชัดเจน วัดผลได้",
                )

                cB1, cB2, cB3 = st.columns(3)
                owner = cB1.text_input(
                    "Owner",
                    value=st.session_state.get("act_owner", ""),
                    key="act_owner",
                )
                cur_pri = st.session_state.get("act_pri", "Medium")
                pri = cB2.selectbox(
                    "Priority",
                    PRIORITIES,
                    index=PRIORITIES.index(cur_pri) if cur_pri in PRIORITIES else 1,
                    key="act_pri",
                )
                due = cB3.date_input(
                    "Due Date",
                    value=st.session_state.get("act_due", _today() + timedelta(days=14)),
                    key="act_due",
                )

                st.markdown("**C. สถานะและหลักฐาน**")
                cC1, cC2 = st.columns(2)
                status = cC1.selectbox(
                    "Status",
                    STATUSES,
                    index=0,
                    key="act_status",
                )
                completion = cC2.date_input(
                    "Completion Date (ถ้าเสร็จ)",
                    value=st.session_state.get("act_comp", _today()),
                    key="act_comp",
                )
                evidence = st.text_input(
                    "Evidence",
                    value=st.session_state.get("act_evidence", ""),
                    key="act_evidence",
                    placeholder="เช่น หนังสือที่ กทพ. 1234/2569",
                )

                st.markdown("**D. การตรวจสอบ (Verification)**")
                cD1, cD2, cD3 = st.columns(3)
                vstatus = cD1.selectbox(
                    "Verification Status",
                    VERIFICATION_STATUSES,
                    index=0,
                    key="act_vstatus",
                )
                verifier = cD2.text_input(
                    "Verifier",
                    value=st.session_state.get("act_verifier", ""),
                    key="act_verifier",
                )
                vdate = cD3.date_input(
                    "Verification Date",
                    value=st.session_state.get("act_vdate", _today()),
                    key="act_vdate",
                )

                comment = st.text_area(
                    "Comment / หมายเหตุ",
                    value=st.session_state.get("act_comment", ""),
                    height=70,
                    key="act_comment",
                )

                cBtn1, cBtn2 = st.columns([1, 1])
                submitted = cBtn1.form_submit_button(
                    "💾 บันทึก Action", type="primary", use_container_width=True,
                )
                reset_clicked = cBtn2.form_submit_button(
                    "↩️ ล้างฟอร์ม", use_container_width=True,
                )

            if reset_clicked:
                _reset_keys("act_", preserve=("act_mode",))
                st.rerun()

            if submitted:
                try:
                    src_id_val = "" if src_id == "-" else src_id

                    data = {
                        "source_type":         src_type,
                        "source_id":           src_id_val,
                        "description":         desc,
                        "owner":               owner.strip(),
                        "priority":            pri,
                        "due_date":            str(due),
                        "status":              status,
                        "completion_date":     str(completion) if status == "Completed" else "",
                        "evidence":            evidence.strip(),
                        "verification_status": vstatus,
                        "verifier":            verifier.strip(),
                        "verification_date":   str(vdate) if vstatus == "Verified" else "",
                        "comment":             comment,
                    }
                    _validate_action(data)

                    aid = new_id("action")
                    row = {
                        "action_id":  aid,
                        "timestamp":  now_str(),
                        **data,
                        "created_by": st.session_state.user,
                    }
                    act_repo.append(row)
                    append_audit(
                        st.session_state.user, "CREATE", "ACTION", aid,
                        old_value="",
                        new_value=f"[{pri}] {desc[:80]} → {owner}",
                        reason=f"Source: {src_type} {src_id_val or '-'}",
                    )

                    st.session_state["act_last_saved"] = {"id": aid, "mode": "เพิ่ม"}
                    _reset_keys("act_", preserve=("act_mode", "act_last_saved"))
                    st.rerun()

                except ValidationError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"❌ {type(e).__name__}: {e}")

        # ---------- UPDATE ----------
        else:
            st.markdown("### 🔄 อัปเดต Action ที่มีอยู่")

            if act_df.empty:
                st.info("ยังไม่มี Action ให้อัปเดต")
            else:
                act_sel = st.selectbox(
                    "เลือก Action ID",
                    act_df["action_id"].astype(str).tolist(),
                    format_func=lambda x: (
                        f"{x} — "
                        f"{str(act_df[act_df['action_id']==x]['description'].iloc[0])[:60]}"
                    ),
                    key="act_upd_sel",
                )
                a_row = act_df[act_df["action_id"] == act_sel].iloc[0]

                info1, info2, info3, info4 = st.columns(4)
                with info1:
                    st.markdown(
                        f"**📌 Source:** `{a_row.get('source_type','-')}`"
                        f" / `{a_row.get('source_id') or '-'}`"
                    )
                with info2:
                    st.markdown(f"**👤 Owner:** {a_row.get('owner','-')}")
                with info3:
                    st.markdown(f"**⚡ Priority:** {_priority_badge(a_row.get('priority'))}")
                with info4:
                    overdue = _is_overdue(a_row.get("due_date"), a_row.get("status"))
                    st.markdown(
                        f"**📅 Due:** {_fmt_date(a_row.get('due_date'))} "
                        f"{'🔴 เกิน' if overdue else ''}"
                    )

                st.markdown(f"**📝 Description:** {a_row.get('description', '-')}")

                with st.form("act_upd_form", clear_on_submit=False):
                    st.markdown("**อัปเดตสถานะ**")
                    cU1, cU2 = st.columns(2)
                    cur_stat = a_row.get("status", "Open")
                    new_status = cU1.selectbox(
                        "Status",
                        STATUSES,
                        index=STATUSES.index(cur_stat) if cur_stat in STATUSES else 0,
                        key="actu_status",
                    )
                    cur_pri = a_row.get("priority", "Medium")
                    new_pri = cU2.selectbox(
                        "Priority",
                        PRIORITIES,
                        index=PRIORITIES.index(cur_pri) if cur_pri in PRIORITIES else 1,
                        key="actu_pri",
                    )

                    cU3, cU4 = st.columns(2)
                    cur_comp = _to_date(a_row.get("completion_date")) or _today()
                    new_comp = cU3.date_input(
                        "Completion Date",
                        value=cur_comp,
                        key="actu_comp",
                    )
                    new_evidence = cU4.text_input(
                        "Evidence",
                        value=str(a_row.get("evidence", "")),
                        key="actu_evidence",
                    )

                    st.markdown("**การตรวจสอบ (Verification)**")
                    cU5, cU6, cU7 = st.columns(3)
                    cur_vs = a_row.get("verification_status", "Not Verified")
                    new_vs = cU5.selectbox(
                        "Verification Status",
                        VERIFICATION_STATUSES,
                        index=VERIFICATION_STATUSES.index(cur_vs)
                            if cur_vs in VERIFICATION_STATUSES else 0,
                        key="actu_vs",
                    )
                    new_verifier = cU6.text_input(
                        "Verifier",
                        value=str(a_row.get("verifier", "")),
                        key="actu_verifier",
                    )
                    cur_vd = _to_date(a_row.get("verification_date")) or _today()
                    new_vdate = cU7.date_input(
                        "Verification Date",
                        value=cur_vd,
                        key="actu_vdate",
                    )

                    new_comment = st.text_area(
                        "Comment",
                        value=str(a_row.get("comment", "")),
                        height=70,
                        key="actu_comment",
                    )

                    cBtn1, cBtn2 = st.columns([1, 1])
                    save_upd = cBtn1.form_submit_button(
                        "💾 บันทึกการอัปเดต", type="primary", use_container_width=True,
                    )
                    reset_upd = cBtn2.form_submit_button(
                        "↩️ ยกเลิกการแก้ไข", use_container_width=True,
                    )

                if reset_upd:
                    _reset_keys("actu_")
                    st.rerun()

                if save_upd:
                    try:
                        data = {
                            "description":         str(a_row.get("description", "")),
                            "owner":               str(a_row.get("owner", "")),
                            "due_date":            str(a_row.get("due_date", "")),
                            "status":              new_status,
                            "completion_date":     str(new_comp) if new_status == "Completed" else "",
                            "evidence":            new_evidence.strip(),
                            "verification_status": new_vs,
                            "verifier":            new_verifier.strip(),
                            "verification_date":   str(new_vdate) if new_vs == "Verified" else "",
                            "comment":             new_comment,
                        }
                        _validate_action(data, prev_status=cur_stat)

                        new_row = {
                            "action_id":   act_sel,
                            "timestamp":   now_str(),
                            "source_type": a_row.get("source_type", ""),
                            "source_id":   a_row.get("source_id", ""),
                            **data,
                            "created_by":  st.session_state.user,
                        }
                        act_repo.append(new_row)
                        append_audit(
                            st.session_state.user, "UPDATE", "ACTION", act_sel,
                            old_value=f"{cur_stat} / {cur_vs}",
                            new_value=f"{new_status} / {new_vs}",
                            reason=f"อัปเดต Action (owner: {a_row.get('owner')})",
                        )

                        st.session_state["act_last_saved"] = {
                            "id": act_sel, "mode": "อัปเดต",
                        }
                        _reset_keys("actu_", preserve=("act_last_saved",))
                        st.rerun()

                    except ValidationError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"❌ {type(e).__name__}: {e}")

    # ============================================================
    # TAB 2 — HISTORY & TRACKING
    # ============================================================
    with t2:
        st.markdown("### 📜 ประวัติ & ติดตาม Action")

        if act_df.empty:
            st.info("ยังไม่มี Action — เริ่มที่แท็บ ➕")
        else:
            c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
            with c1:
                f_status = st.multiselect(
                    "Status", STATUSES,
                    default=["Open", "In Progress"],
                    key="h_status",
                )
            with c2:
                f_priority = st.multiselect(
                    "Priority", PRIORITIES,
                    default=PRIORITIES, key="h_priority",
                )
            with c3:
                overdue_only = st.checkbox("เฉพาะ Overdue", key="h_overdue")
            with c4:
                search = st.text_input(
                    "🔍 Search (Description / Owner / Source ID)",
                    value="", key="h_search",
                )

            view = act_df.copy()
            if f_status:
                view = view[view["status"].isin(f_status)]
            if f_priority:
                view = view[view["priority"].isin(f_priority)]
            if overdue_only:
                view = view[
                    view.apply(
                        lambda r: _is_overdue(r.get("due_date"), r.get("status")),
                        axis=1,
                    )
                ]
            if search.strip():
                s = search.strip().lower()
                view = view[
                    view["description"].astype(str).str.lower().str.contains(s, na=False)
                    | view["owner"].astype(str).str.lower().str.contains(s, na=False)
                    | view["source_id"].astype(str).str.lower().str.contains(s, na=False)
                ]

            view = view.copy()
            view["_due_dt"] = pd.to_datetime(view["due_date"], errors="coerce")
            view = view.sort_values("_due_dt", ascending=True, na_position="last")

            st.caption(f"แสดง {len(view)} / {len(act_df)} รายการ")

            for _, r in view.iterrows():
                overdue = _is_overdue(r.get("due_date"), r.get("status"))
                dl = _days_left(r.get("due_date"))

                if overdue:
                    border = "#D32F2F"
                    time_txt = f"🔴 เกิน {-dl} วัน"
                elif dl is not None and dl <= 3 and r["status"] not in ("Completed", "Cancelled"):
                    border = "#F57C00"
                    time_txt = f"⏰ อีก {dl} วัน"
                elif r["status"] == "Completed":
                    border = "#2E7D32"
                    time_txt = "🟢 เสร็จแล้ว"
                elif r["status"] == "Cancelled":
                    border = "#9E9E9E"
                    time_txt = "⚪ ยกเลิก"
                else:
                    border = PRIORITY_COLORS.get(r.get("priority", "Medium"), "#0B5ED7")
                    time_txt = f"📅 อีก {dl} วัน" if dl is not None else "-"

                pri_color = PRIORITY_COLORS.get(r.get("priority", "Medium"), "#0B5ED7")
                status_txt = STATUS_BADGES.get(r["status"], r["status"] or "-")
                verify_txt = VERIFY_BADGES.get(
                    r.get("verification_status", "-"), r.get("verification_status", "-")
                )
                src_txt = f"{r.get('source_type', '-')} {r.get('source_id') or '-'}"

                st.markdown(
                    f'<div style="background:#FFFFFF;border-radius:8px;'
                    f'padding:10px 14px;border-left:4px solid {border};'
                    f'box-shadow:0 1px 4px rgba(0,51,102,0.05);margin-bottom:8px;">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;flex-wrap:wrap;gap:8px;">'
                    f'<div style="font-size:13px;font-weight:700;color:#003366;">'
                    f'{r["action_id"]} '
                    f'<span style="background:{pri_color};color:#FFF;'
                    f'padding:2px 8px;border-radius:10px;font-size:10.5px;'
                    f'margin-left:6px;">{r.get("priority","-")}</span>'
                    f'<span style="font-weight:400;color:#666;margin-left:6px;">'
                    f'({status_txt})</span>'
                    f'</div>'
                    f'<div style="font-size:11.5px;color:{border};font-weight:600;">'
                    f'{time_txt}</div></div>'
                    f'<div style="font-size:13px;color:#333;margin:6px 0;">'
                    f'{str(r["description"])[:200]}</div>'
                    f'<div style="font-size:11.5px;color:#666;">'
                    f'👤 <b>{r.get("owner","-")}</b> · '
                    f'📅 Due {_fmt_date(r.get("due_date"))} · '
                    f'🔗 {src_txt} · '
                    f'🔍 {verify_txt}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            with st.expander("📋 ตารางแบบละเอียด"):
                show_cols = [c for c in [
                    "action_id", "status", "priority", "owner",
                    "due_date", "completion_date",
                    "verification_status", "verifier", "verification_date",
                    "source_type", "source_id", "evidence",
                    "description",
                ] if c in view.columns]
                st.dataframe(
                    view[show_cols],
                    use_container_width=True,
                    hide_index=True,
                )

            # ---- Soft Delete + Restore ----
            if st.session_state.role in ("admin", "monitoring"):
                st.markdown("---")
                with st.expander("🗑️ ลบ / คืนค่า (Soft Delete)", expanded=False):
                    st.caption("⚠️ Soft Delete = ซ่อนจาก UI, ข้อมูลยังอยู่ใน CSV")

                    colA, colB = st.columns(2)

                    with colA:
                        st.markdown("**🗑️ Soft Delete**")
                        del_id = st.selectbox(
                            "เลือก Action ID",
                            act_df["action_id"].astype(str).tolist(),
                            key="h_del_sel",
                        )
                        del_reason = st.text_input(
                            "เหตุผลที่ลบ", key="h_del_reason",
                        )
                        if st.button("🗑️ Soft Delete", type="primary", key="h_del_btn"):
                            if not del_reason.strip():
                                st.error("⚠️ กรุณาระบุเหตุผล")
                            else:
                                try:
                                    act_repo.soft_delete(
                                        del_id, del_reason, st.session_state.user
                                    )
                                    st.success(f"✅ ซ่อน `{del_id}` แล้ว")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ {e}")

                    with colB:
                        st.markdown("**↩️ Restore**")
                        try:
                            from core.void_registry import read_voids
                            vd = read_voids()
                            vd_a = (
                                vd[vd["record_type"] == "action"]
                                if not vd.empty else vd
                            )
                            if vd_a.empty:
                                st.info("ไม่มีรายการที่ถูก Void")
                            else:
                                rid = st.selectbox(
                                    "เลือก Action ID",
                                    vd_a["record_id"].tolist(),
                                    key="h_restore_sel",
                                )
                                if st.button("↩️ คืนค่า", key="h_restore_btn"):
                                    if act_repo.restore(rid, st.session_state.user):
                                        st.success(f"✅ คืนค่า `{rid}` แล้ว")
                                        st.rerun()
                        except Exception as e:
                            st.error(f"❌ {e}")

    # ============================================================
    # TAB 3 — CHARTS
    # ============================================================
    with t3:
        st.markdown("### 📈 Charts สรุป Actions")

        if act_df.empty:
            st.info("ยังไม่มีข้อมูลสำหรับสร้างกราฟ")
        else:
            c1, c2 = st.columns(2)

            with c1:
                st.markdown("#### ตามสถานะ")
                counts = act_df["status"].value_counts()
                colors = {
                    "Open": "#D32F2F",
                    "In Progress": "#F57C00",
                    "Completed": "#2E7D32",
                    "Cancelled": "#9E9E9E",
                }
                fig1 = go.Figure(data=[go.Pie(
                    labels=counts.index.tolist(),
                    values=counts.values.tolist(),
                    hole=0.5,
                    marker=dict(colors=[colors.get(x, "#0B5ED7") for x in counts.index]),
                )])
                fig1.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(fig1, use_container_width=True)

            with c2:
                st.markdown("#### ตาม Priority")
                pc = act_df["priority"].value_counts().reindex(PRIORITIES).fillna(0)
                fig2 = go.Figure(data=[go.Bar(
                    x=pc.index.tolist(),
                    y=pc.values.tolist(),
                    marker_color=[PRIORITY_COLORS.get(x, "#0B5ED7") for x in pc.index],
                    text=pc.values.astype(int).tolist(),
                    textposition="outside",
                )])
                fig2.update_layout(
                    height=320, plot_bgcolor="#FAFBFC",
                    yaxis_title="จำนวน",
                    margin=dict(l=10, r=10, t=30, b=40),
                )
                st.plotly_chart(fig2, use_container_width=True)

            st.markdown("#### ตาม Owner (Top 10)")
            owner_counts = (
                act_df[act_df["status"] != "Cancelled"]["owner"]
                .value_counts().head(10)
            )
            if owner_counts.empty:
                st.info("ไม่มีข้อมูล Owner")
            else:
                fig3 = go.Figure(data=[go.Bar(
                    x=owner_counts.values.tolist(),
                    y=owner_counts.index.tolist(),
                    orientation="h",
                    marker_color="#0B5ED7",
                    text=owner_counts.values.tolist(),
                    textposition="outside",
                )])
                fig3.update_layout(
                    height=max(280, len(owner_counts) * 38),
                    plot_bgcolor="#FAFBFC",
                    xaxis_title="จำนวน Action",
                    margin=dict(l=10, r=60, t=20, b=40),
                )
                st.plotly_chart(fig3, use_container_width=True)

            st.markdown("#### ⏰ Overdue by Owner")
            od_rows = [
                r["owner"] for _, r in act_df.iterrows()
                if _is_overdue(r.get("due_date"), r.get("status"))
            ]
            if od_rows:
                od_counts = pd.Series(od_rows).value_counts()
                fig4 = go.Figure(data=[go.Bar(
                    x=od_counts.values.tolist(),
                    y=od_counts.index.tolist(),
                    orientation="h",
                    marker_color="#D32F2F",
                    text=od_counts.values.tolist(),
                    textposition="outside",
                )])
                fig4.update_layout(
                    height=max(220, len(od_counts) * 38),
                    plot_bgcolor="#FFF5F5",
                    xaxis_title="จำนวน Overdue",
                    margin=dict(l=10, r=60, t=20, b=40),
                )
                st.plotly_chart(fig4, use_container_width=True)
            else:
                st.success("✅ ไม่มี Action เกินกำหนด")

    # ============================================================
    # TAB 4 — CSV
    # ============================================================
    with t4:
        st.markdown("### 📥 ข้อมูล CSV (อ่านเท่านั้น)")
        st.caption("ไฟล์จริง: `data/history/action_history.csv`")

        if act_df.empty:
            st.info("ยังไม่มีข้อมูล")
        else:
            st.dataframe(act_df, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ ดาวน์โหลด action_history.csv",
                data=act_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"action_history_{today_str()}.csv",
                mime="text/csv",
                key="dl_act",
            )