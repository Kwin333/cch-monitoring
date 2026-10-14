"""ประชุมกำกับดูแลและติดตามผล (ข้อ 1.3) — Comprehensive Version

ครอบคลุม:
- 📊 KPI Dashboard: ประชุม, มติ, overdue, completion rate
- 📋 Meeting CRUD + link to Milestone / Deliverable / Issue
- ✅ Resolution CRUD + auto-create Action + lifecycle tracking
- 📜 History + Filter + Search + Detail viewer + Soft Delete + Restore
- 📈 Chart ประชุมตามประเภท
- 📥 CSV Export
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

from core.ids import new_id
from core.time_util import now_str, today_str
from core.audit import append_audit
from core.validator import ValidationError
from repositories.meeting_repo import MeetingRepo, ResolutionRepo
from repositories.action_repo import ActionRepo
from repositories.deliverable_repo import DeliverableRepo
from repositories.milestone_repo import MilestoneRepo
from repositories.issue_repo import IssueRepo


# ============================================================
# CONSTANTS
# ============================================================
MEETING_TYPES = ["Kick-off", "Workshop", "Steering", "Monitoring", "Ad-hoc", "Site Visit"]
MEETING_STATUSES = ["Planned", "Held", "Postponed", "Cancelled"]
RESOLUTION_STATUSES = ["Open", "In Progress", "Completed", "Closed", "Cancelled"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]


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


def _meeting_badge(s):
    return {
        "Planned": "🔵 วางแผนไว้",
        "Held": "🟢 จัดแล้ว",
        "Postponed": "🟠 เลื่อน",
        "Cancelled": "⚪ ยกเลิก",
    }.get(s, s or "-")


def _res_badge(s):
    return {
        "Open": "🔴 เปิด",
        "In Progress": "🟠 กำลังดำเนินการ",
        "Completed": "🟢 เสร็จ",
        "Closed": "✅ ปิด",
        "Cancelled": "⚪ ยกเลิก",
    }.get(s, s or "-")


def _is_overdue(due, status):
    if status in ("Closed", "Cancelled", "Completed"):
        return False
    dd = _to_date(due)
    return dd is not None and dd < _today()


def _next_meeting_no(meetings_df):
    """Auto-generate MTG-YYYY-NNN"""
    year = _today().year
    prefix = f"MTG-{year}-"
    if meetings_df is None or meetings_df.empty or "meeting_no" not in meetings_df:
        return f"{prefix}001"
    nums = []
    for v in meetings_df["meeting_no"].astype(str):
        if v.startswith(prefix):
            try:
                nums.append(int(v[len(prefix):]))
            except ValueError:
                pass
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"


def _next_resolution_no(meeting_id, resolutions_df):
    """Auto-generate RES-NNN ต่อการประชุม 1 ครั้ง"""
    if resolutions_df is None or resolutions_df.empty:
        return "RES-001"
    sub = resolutions_df[resolutions_df["meeting_id"] == meeting_id]
    nums = []
    for v in sub["resolution_no"].astype(str):
        if v.startswith("RES-"):
            try:
                nums.append(int(v[4:]))
            except ValueError:
                pass
    return f"RES-{(max(nums) + 1) if nums else 1:03d}"


def _split_ids(s):
    """แยก comma-separated IDs เป็น list"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return []
    return [x.strip() for x in str(s).split(",") if x.strip()]


def _join_ids(ids):
    return ", ".join(ids) if ids else ""


def _reset_keys(prefix, preserve=()):
    for k in list(st.session_state.keys()):
        if k.startswith(prefix) and k not in preserve:
            st.session_state.pop(k, None)


def _validate_meeting(data):
    if not (data.get("meeting_no") or "").strip():
        raise ValidationError("⚠️ ต้องระบุเลขที่ประชุม")
    if not _to_date(data.get("meeting_date")):
        raise ValidationError("⚠️ ต้องระบุวันที่ประชุม")
    if not (data.get("agenda") or "").strip():
        raise ValidationError("⚠️ ต้องระบุระเบียบวาระ")


def _validate_resolution(data):
    if not (data.get("resolution_text") or "").strip():
        raise ValidationError("⚠️ ต้องระบุรายละเอียดมติ")
    if not (data.get("responsible_person") or "").strip():
        raise ValidationError("⚠️ ต้องระบุผู้รับผิดชอบ")
    if not _to_date(data.get("due_date")):
        raise ValidationError("⚠️ ต้องระบุกำหนดแล้วเสร็จ")
    if data.get("status") == "Closed" and not _to_date(data.get("completion_date")):
        raise ValidationError("⚠️ มติที่ปิด ต้องระบุวันแล้วเสร็จ")


def _tile(label, value, sub, color):
    return f"""
    <div style="background:#FFFFFF;border-radius:10px;padding:12px 14px;
                border-left:4px solid {color};box-shadow:0 2px 6px rgba(0,51,102,0.06);height:100%;">
        <div style="font-size:11.5px;color:#5A5A5A;font-weight:600;">{label}</div>
        <div style="font-size:22px;font-weight:700;color:#003366;line-height:1.1;margin:4px 0;">{value}</div>
        <div style="font-size:11px;color:{color};">{sub}</div>
    </div>
    """


# ============================================================
# MAIN
# ============================================================
def render():
    st.title("📅 ประชุมกำกับดูแลและติดตามผล (ข้อ 1.3)")
    st.caption(
        "บันทึกการประชุม · จัดการมติ · เชื่อมโยง Milestone/Deliverable/Issue · "
        "Auto-create Action Item"
    )

    # ============================================================
    # READ ONCE
    # ============================================================
    meeting_repo = MeetingRepo()
    res_repo = ResolutionRepo()

    mtg_df = meeting_repo.read()
    res_df = res_repo.read()

    try:
        act_df = ActionRepo().read()
    except Exception:
        act_df = pd.DataFrame()

    try:
        dl_df = DeliverableRepo().read()
        dl_df = dl_df[dl_df["milestone_id"].astype(str).str.startswith("MLS")].reset_index(drop=True)
    except Exception:
        dl_df = pd.DataFrame()

    try:
        ms_df = MilestoneRepo().read()
    except Exception:
        ms_df = pd.DataFrame()

    try:
        iss_df = IssueRepo().read()
    except Exception:
        iss_df = pd.DataFrame()

    # ============================================================
    # KPI TILES
    # ============================================================
    st.markdown("### 📊 ภาพรวมการประชุมและมติ")

    n_mtg_total = len(mtg_df)
    n_mtg_held = int((mtg_df["status"] == "Held").sum()) if not mtg_df.empty else 0
    n_mtg_planned = int((mtg_df["status"] == "Planned").sum()) if not mtg_df.empty else 0

    n_res_total = len(res_df)
    n_res_open = int(res_df["status"].isin(["Open", "In Progress"]).sum()) if not res_df.empty else 0
    n_res_closed = int((res_df["status"] == "Closed").sum()) if not res_df.empty else 0

    n_res_overdue = 0
    if not res_df.empty:
        n_res_overdue = sum(
            1 for _, r in res_df.iterrows()
            if _is_overdue(r.get("due_date"), r.get("status"))
        )

    completion_rate = (n_res_closed / n_res_total * 100) if n_res_total else 0.0

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(_tile("📅 ประชุมทั้งหมด", f"{n_mtg_total}",
                          f"จัดแล้ว {n_mtg_held} · วางแผน {n_mtg_planned}", "#0B5ED7"),
                    unsafe_allow_html=True)
    with k2:
        st.markdown(_tile("✅ มติทั้งหมด", f"{n_res_total}",
                          f"ปิดแล้ว {n_res_closed}", "#00838F"),
                    unsafe_allow_html=True)
    with k3:
        st.markdown(_tile("📌 มติที่เปิด", f"{n_res_open}",
                          "Open + In Progress", "#F57C00"),
                    unsafe_allow_html=True)
    with k4:
        od_color = "#D32F2F" if n_res_overdue > 0 else "#2E7D32"
        st.markdown(_tile("⏰ เกินกำหนด", f"{n_res_overdue}",
                          "ต้องติดตามด่วน" if n_res_overdue else "ไม่มี", od_color),
                    unsafe_allow_html=True)
    with k5:
        st.markdown(_tile("🎯 Completion", f"{completion_rate:.1f}%",
                          f"{n_res_closed}/{n_res_total} มติ", "#2E7D32"),
                    unsafe_allow_html=True)

    st.markdown("---")

    # ============================================================
    # TABS
    # ============================================================
    t1, t2, t3, t4 = st.tabs([
        "📋 บันทึกการประชุม",
        "✅ มติที่ประชุม",
        "📜 ประวัติ",
        "📥 CSV",
    ])

    # ============================================================
    # TAB 1 — MEETING FORM
    # ============================================================
    with t1:
        # Flash message
        if "mtg_last_saved" in st.session_state:
            info = st.session_state.pop("mtg_last_saved")
            st.markdown(
                f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
                f'padding:10px 14px;border-radius:8px;font-size:13px;">'
                f'✅ <b>บันทึกการประชุมสำเร็จ</b> — '
                f'Meeting ID: <code>{info["id"]}</code> · '
                f'Meeting No: <code>{info["no"]}</code>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown("### ➕ บันทึกการประชุมใหม่")
        auto_no = _next_meeting_no(mtg_df)

        with st.form("mtg_form", clear_on_submit=False):
            # ---- A. Basic ----
            st.markdown("**A. ข้อมูลพื้นฐาน**")
            cA1, cA2, cA3 = st.columns(3)
            m_no = cA1.text_input(
                "เลขที่ประชุม",
                value=st.session_state.get("mtg_no", auto_no),
                key="mtg_no",
            )
            m_date = cA2.date_input(
                "วันที่ประชุม",
                value=st.session_state.get("mtg_date", _today()),
                key="mtg_date",
            )
            cur_type = st.session_state.get("mtg_type", "Monitoring")
            m_type = cA3.selectbox(
                "ประเภทการประชุม",
                MEETING_TYPES,
                index=MEETING_TYPES.index(cur_type) if cur_type in MEETING_TYPES else 3,
                key="mtg_type",
            )

            # ---- B. Attendees ----
            st.markdown("**B. ผู้เข้าร่วม**")
            cB1, cB2 = st.columns(2)
            attendees = cB1.text_area(
                "ผู้เข้าร่วม (กทพ.)",
                value=st.session_state.get("mtg_att", ""),
                height=90,
                key="mtg_att",
                placeholder="เช่น คุณสมชาย (ผจก.โครงการ), คุณสมหญิง (ฝ่ายการเงิน)",
            )
            consultant_att = cB2.text_area(
                "ผู้เข้าร่วม (ที่ปรึกษา)",
                value=st.session_state.get("mtg_consult_att", ""),
                height=90,
                key="mtg_consult_att",
                placeholder="เช่น ทีมที่ปรึกษา CCH, ที่ปรึกษากฎหมาย",
            )

            # ---- C. Agenda & Minutes ----
            st.markdown("**C. วาระและรายงานการประชุม**")
            agenda = st.text_area(
                "ระเบียบวาระ",
                value=st.session_state.get("mtg_agenda", ""),
                height=100,
                key="mtg_agenda",
                placeholder="1. ติดตามความก้าวหน้า\n2. พิจารณาเอกสาร\n3. อื่น ๆ",
            )
            minutes_text = st.text_area(
                "บันทึกสรุปการประชุม",
                value=st.session_state.get("mtg_minutes", ""),
                height=120,
                key="mtg_minutes",
            )
            cC1, cC2 = st.columns(2)
            minutes_ref = cC1.text_input(
                "อ้างอิงรายงานการประชุม",
                value=st.session_state.get("mtg_min_ref", ""),
                key="mtg_min_ref",
                placeholder="เช่น MIN-2026-001",
            )
            cur_status = st.session_state.get("mtg_status", "Held")
            m_status = cC2.selectbox(
                "สถานะการประชุม",
                MEETING_STATUSES,
                index=MEETING_STATUSES.index(cur_status) if cur_status in MEETING_STATUSES else 1,
                key="mtg_status",
            )

            # ---- D. Links ----
            st.markdown("**D. เชื่อมโยง (optional)**")
            cD1, cD2, cD3 = st.columns(3)
            ms_options = ms_df["milestone_id"].astype(str).tolist() if not ms_df.empty else []
            dl_options = dl_df["deliverable_id"].astype(str).tolist() if not dl_df.empty else []
            iss_options = iss_df["issue_id"].astype(str).tolist() if not iss_df.empty else []

            linked_ms = cD1.multiselect("Milestone ที่เกี่ยวข้อง", ms_options, key="mtg_linked_ms")
            linked_dl = cD2.multiselect("Deliverable ที่เกี่ยวข้อง", dl_options, key="mtg_linked_dl")
            linked_iss = cD3.multiselect("Issue ที่เกี่ยวข้อง", iss_options, key="mtg_linked_iss")

            # ---- Buttons ----
            cBtn1, cBtn2 = st.columns([1, 1])
            submitted = cBtn1.form_submit_button(
                "💾 บันทึกการประชุม",
                type="primary",
                use_container_width=True,
            )
            reset_clicked = cBtn2.form_submit_button(
                "↩️ ล้างฟอร์ม",
                use_container_width=True,
            )

        # ---- Reset ----
        if reset_clicked:
            _reset_keys("mtg_")
            st.rerun()

        # ---- Save (OUTSIDE form block) ----
        if submitted:
            try:
                _validate_meeting({
                    "meeting_no": m_no,
                    "meeting_date": str(m_date),
                    "agenda": agenda,
                })

                mid = new_id("meeting")
                row = {
                    "timestamp":              now_str(),
                    "meeting_id":             mid,
                    "meeting_no":             m_no.strip(),
                    "meeting_date":           str(m_date),
                    "meeting_type":           m_type,
                    "agenda":                 agenda,
                    "attendees":              attendees,
                    "consultant_attendees":   consultant_att,
                    "minutes_reference":      minutes_ref.strip(),
                    "status":                 m_status,
                    "linked_milestone_ids":   _join_ids(linked_ms),
                    "linked_deliverable_ids": _join_ids(linked_dl),
                    "linked_issue_ids":       _join_ids(linked_iss),
                    "minutes_text":           minutes_text,
                    "created_by":             st.session_state.user,
                }
                meeting_repo.append(row)
                append_audit(
                    st.session_state.user, "CREATE", "MEETING", mid,
                    old_value="",
                    new_value=f"{m_no} ({m_type}, {m_date})",
                    reason="บันทึกการประชุมใหม่",
                )

                st.session_state["mtg_last_saved"] = {"id": mid, "no": m_no}
                _reset_keys("mtg_", preserve=("mtg_last_saved",))
                st.rerun()

            except ValidationError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"❌ {type(e).__name__}: {e}")

        # ---- Recent 5 ----
        if not mtg_df.empty:
            st.markdown("---")
            st.markdown("#### 🕒 ประชุมล่าสุด 5 ครั้ง")
            recent = mtg_df.copy()
            recent["_ts"] = pd.to_datetime(recent["timestamp"], errors="coerce")
            recent = recent.sort_values("_ts", ascending=False).head(5)
            show = pd.DataFrame({
                "Meeting No": recent["meeting_no"],
                "วันที่":      recent["meeting_date"].apply(_fmt_date),
                "ประเภท":     recent["meeting_type"],
                "สถานะ":      recent["status"].apply(_meeting_badge),
                "Minutes":    recent["minutes_reference"].fillna("-"),
                "บันทึกโดย":  recent["created_by"],
            })
            st.dataframe(show, use_container_width=True, hide_index=True)
        else:
            st.info("ℹ️ ยังไม่มีการประชุม — ฟอร์มด้านบนคือการประชุมครั้งแรก")

    # ============================================================
    # TAB 2 — RESOLUTIONS
    # ============================================================
    with t2:
        if mtg_df.empty:
            st.warning("⚠️ ยังไม่มีการประชุม — กรุณาบันทึกที่แท็บ **📋 บันทึกการประชุม** ก่อน")
        else:
            st.markdown("### ➕ เพิ่มมติที่ประชุม")

            # ---- Select meeting ----
            default_ms = st.session_state.get("res_meeting_sel", mtg_df["meeting_id"].iloc[0])
            if default_ms not in mtg_df["meeting_id"].values:
                default_ms = mtg_df["meeting_id"].iloc[0]

            ms_meeting_sel = st.selectbox(
                "เลือกการประชุม",
                mtg_df["meeting_id"].astype(str).tolist(),
                index=mtg_df["meeting_id"].astype(str).tolist().index(str(default_ms)),
                format_func=lambda x: (
                    f"{mtg_df[mtg_df['meeting_id']==x]['meeting_no'].iloc[0]} — "
                    f"{_fmt_date(mtg_df[mtg_df['meeting_id']==x]['meeting_date'].iloc[0])} "
                    f"({mtg_df[mtg_df['meeting_id']==x]['meeting_type'].iloc[0]})"
                ),
                key="res_meeting_sel",
            )

            auto_res_no = _next_resolution_no(ms_meeting_sel, res_df)

            with st.form("res_form", clear_on_submit=False):
                cA1, cA2 = st.columns([1, 3])
                r_no = cA1.text_input(
                    "เลขที่มติ",
                    value=st.session_state.get("res_no", auto_res_no),
                    key="res_no",
                )
                r_text = cA2.text_area(
                    "รายละเอียดมติ",
                    value=st.session_state.get("res_text", ""),
                    height=100,
                    key="res_text",
                    placeholder="ระบุมติอย่างชัดเจน วัดผลได้",
                )

                cB1, cB2, cB3 = st.columns(3)
                r_owner = cB1.text_input(
                    "ผู้รับผิดชอบ",
                    value=st.session_state.get("res_owner", ""),
                    key="res_owner",
                )
                r_due = cB2.date_input(
                    "กำหนดแล้วเสร็จ",
                    value=st.session_state.get("res_due", _today() + timedelta(days=14)),
                    key="res_due",
                )
                r_evi = cB3.text_input(
                    "หลักฐานที่ต้องส่ง",
                    value=st.session_state.get("res_evi", ""),
                    key="res_evi",
                )

                cC1, cC2 = st.columns(2)
                cur_r_status = st.session_state.get("res_status", "Open")
                r_status = cC1.selectbox(
                    "สถานะมติ",
                    RESOLUTION_STATUSES,
                    index=RESOLUTION_STATUSES.index(cur_r_status)
                        if cur_r_status in RESOLUTION_STATUSES else 0,
                    key="res_status",
                )
                r_pri = cC2.selectbox("Priority (สำหรับ Action)",
                                      PRIORITIES, index=1, key="res_pri")

                st.markdown("**การดำเนินการต่อ**")
                cD1, cD2 = st.columns(2)
                create_action = cD1.checkbox(
                    "สร้าง Action Item อัตโนมัติ",
                    value=True,
                    key="res_create_action",
                )
                r_comment = cD2.text_input("หมายเหตุ", value="", key="res_comment")

                cBtn1, cBtn2 = st.columns([1, 1])
                submitted_res = cBtn1.form_submit_button(
                    "💾 บันทึกมติ", type="primary", use_container_width=True,
                )
                reset_res = cBtn2.form_submit_button(
                    "↩️ ล้างฟอร์ม", use_container_width=True,
                )

            if reset_res:
                _reset_keys("res_", preserve=("res_meeting_sel",))
                st.rerun()

            if submitted_res:
                try:
                    _validate_resolution({
                        "resolution_text":    r_text,
                        "responsible_person": r_owner,
                        "due_date":           str(r_due),
                        "status":             r_status,
                        "completion_date":    "",
                    })

                    rid = new_id("resolution")
                    row = {
                        "timestamp":          now_str(),
                        "resolution_id":      rid,
                        "meeting_id":         ms_meeting_sel,
                        "resolution_no":      r_no.strip(),
                        "resolution_text":    r_text,
                        "responsible_person": r_owner.strip(),
                        "due_date":           str(r_due),
                        "evidence_required":  r_evi.strip(),
                        "status":             r_status,
                        "completion_date":    "",
                        "linked_action_id":   "",
                        "comment":            r_comment,
                        "created_by":         st.session_state.user,
                    }

                    linked_action_id = ""

                    if create_action:
                        aid = new_id("action")
                        action_row = {
                            "action_id":           aid,
                            "timestamp":           now_str(),
                            "source_type":         "Resolution",
                            "source_id":           rid,
                            "description":         r_text,
                            "owner":               r_owner.strip(),
                            "priority":            r_pri,
                            "due_date":            str(r_due),
                            "status":              "Open",
                            "completion_date":     "",
                            "evidence":            "",
                            "verification_status": "Not Verified",
                            "verifier":            "",
                            "verification_date":   "",
                            "comment":             f"สร้างจากมติ {r_no}",
                            "created_by":          st.session_state.user,
                        }
                        ActionRepo().append(action_row)
                        linked_action_id = aid
                        row["linked_action_id"] = aid

                    res_repo.append(row)
                    append_audit(
                        st.session_state.user, "CREATE", "RESOLUTION", rid,
                        old_value="",
                        new_value=f"{r_no} → {r_text[:80]}",
                        reason=f"มติจากประชุม {ms_meeting_sel}",
                    )

                    if linked_action_id:
                        st.success(
                            f"✅ บันทึกมติ `{rid}` สำเร็จ — "
                            f"สร้าง Action `{linked_action_id}` อัตโนมัติ"
                        )
                    else:
                        st.success(f"✅ บันทึกมติ `{rid}` สำเร็จ")

                    _reset_keys("res_", preserve=("res_meeting_sel",))
                    st.rerun()

                except ValidationError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"❌ {type(e).__name__}: {e}")

            # ---- Resolutions list ----
            st.markdown("---")
            st.markdown("#### 📋 มติทั้งหมด")

            if res_df.empty:
                st.info("ยังไม่มีมติ — ใช้ฟอร์มด้านบนเพื่อเพิ่มมติแรก")
            else:
                f1, f2, f3 = st.columns([1, 1, 2])
                with f1:
                    res_ms_filter = st.multiselect(
                        "ประชุม",
                        mtg_df["meeting_id"].astype(str).tolist(),
                        default=mtg_df["meeting_id"].astype(str).tolist(),
                        format_func=lambda x: (
                            mtg_df[mtg_df["meeting_id"] == x]["meeting_no"].iloc[0]
                            if x in mtg_df["meeting_id"].values else x
                        ),
                        key="res_filter_ms",
                    )
                with f2:
                    res_st_filter = st.multiselect(
                        "สถานะ", RESOLUTION_STATUSES,
                        default=RESOLUTION_STATUSES,
                        key="res_filter_st",
                    )
                with f3:
                    res_search = st.text_input(
                        "🔍 Search (มติ / ผู้รับผิดชอบ)", value="", key="res_search",
                    )

                rview = res_df.copy()
                if res_ms_filter:
                    rview = rview[rview["meeting_id"].isin(res_ms_filter)]
                if res_st_filter:
                    rview = rview[rview["status"].isin(res_st_filter)]
                if res_search.strip():
                    s = res_search.strip().lower()
                    rview = rview[
                        rview["resolution_text"].astype(str).str.lower().str.contains(s, na=False)
                        | rview["responsible_person"].astype(str).str.lower().str.contains(s, na=False)
                        | rview["resolution_no"].astype(str).str.lower().str.contains(s, na=False)
                    ]

                rview = rview.sort_values("timestamp", ascending=False)
                st.caption(f"แสดง {len(rview)} / {len(res_df)} มติ")

                for _, r in rview.iterrows():
                    overdue = _is_overdue(r.get("due_date"), r.get("status"))
                    due_d = _to_date(r.get("due_date"))
                    days_left = (due_d - _today()).days if due_d else None

                    if overdue:
                        border_color = "#D32F2F"
                        time_txt = f' · 🔴 เกิน {abs(days_left)} วัน'
                    elif days_left is not None and days_left <= 3:
                        border_color = "#F57C00"
                        time_txt = f' · ⏰ อีก {days_left} วัน'
                    elif days_left is not None and days_left <= 7:
                        border_color = "#F57C00"
                        time_txt = f' · ⏰ อีก {days_left} วัน'
                    else:
                        border_color = "#0B5ED7"
                        time_txt = ""

                    st.markdown(
                        f'<div style="background:#FFFFFF;border-radius:8px;'
                        f'padding:10px 14px;border-left:4px solid {border_color};'
                        f'box-shadow:0 1px 4px rgba(0,51,102,0.05);margin-bottom:8px;">'
                        f'<div style="font-size:13px;font-weight:700;color:#003366;">'
                        f'{r["resolution_no"]} · {r["resolution_id"]} '
                        f'<span style="font-weight:400;color:#666;">'
                        f'({_res_badge(r["status"])})</span></div>'
                        f'<div style="font-size:13px;color:#333;margin:6px 0;">'
                        f'{str(r["resolution_text"])[:220]}</div>'
                        f'<div style="font-size:11.5px;color:#666;">'
                        f'👤 {r["responsible_person"]} · '
                        f'📅 Due {_fmt_date(r.get("due_date"))}{time_txt}'
                        f' · 🎯 Action: {r.get("linked_action_id") or "-"}'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )

    # ============================================================
    # TAB 3 — HISTORY
    # ============================================================
    with t3:
        st.markdown("### 📜 ประวัติการประชุมทั้งหมด")

        if mtg_df.empty:
            st.info("ยังไม่มีการประชุม")
        else:
            # ---- Filters ----
            h1, h2, h3 = st.columns([1, 1, 2])
            with h1:
                type_h = st.multiselect("ประเภท", MEETING_TYPES,
                                        default=MEETING_TYPES, key="mh_type")
            with h2:
                status_h = st.multiselect("สถานะ", MEETING_STATUSES,
                                          default=MEETING_STATUSES, key="mh_status")
            with h3:
                search_h = st.text_input(
                    "🔍 Search (Meeting No / Agenda / Minutes)",
                    value="", key="mh_search",
                )

            hview = mtg_df.copy()
            if type_h:
                hview = hview[hview["meeting_type"].isin(type_h)]
            if status_h:
                hview = hview[hview["status"].isin(status_h)]
            if search_h.strip():
                s = search_h.strip().lower()
                hview = hview[
                    hview["meeting_no"].astype(str).str.lower().str.contains(s, na=False)
                    | hview["agenda"].astype(str).str.lower().str.contains(s, na=False)
                    | hview["minutes_reference"].astype(str).str.lower().str.contains(s, na=False)
                ]

            hview = hview.sort_values("timestamp", ascending=False)

            # Enrich: resolution count
            res_count = res_df.groupby("meeting_id").size().to_dict() if not res_df.empty else {}
            res_open = (
                res_df[res_df["status"].isin(["Open", "In Progress"])]
                .groupby("meeting_id").size().to_dict()
            ) if not res_df.empty else {}

            hview_display = pd.DataFrame({
                "Meeting No":    hview["meeting_no"],
                "วันที่":         hview["meeting_date"].apply(_fmt_date),
                "ประเภท":        hview["meeting_type"],
                "สถานะ":         hview["status"].apply(_meeting_badge),
                "Minutes":       hview["minutes_reference"].fillna("-"),
                "มติ (ทั้งหมด)":  hview["meeting_id"].map(res_count).fillna(0).astype(int),
                "มติ (เปิด)":     hview["meeting_id"].map(res_open).fillna(0).astype(int),
                "บันทึกโดย":      hview["created_by"],
                "ID":            hview["meeting_id"],
            })

            st.caption(f"แสดง {len(hview_display)} / {len(mtg_df)} รายการ")
            st.dataframe(hview_display, use_container_width=True, hide_index=True)

            # ---- Detail viewer ----
            st.markdown("---")
            st.markdown("#### 🔎 ดูรายละเอียดการประชุม")

            detail_id = st.selectbox(
                "เลือกการประชุม",
                hview["meeting_id"].astype(str).tolist(),
                format_func=lambda x: (
                    f"{hview[hview['meeting_id']==x]['meeting_no'].iloc[0]} — "
                    f"{_fmt_date(hview[hview['meeting_id']==x]['meeting_date'].iloc[0])}"
                ),
                key="mh_detail_sel",
            )
            m = mtg_df[mtg_df["meeting_id"] == detail_id].iloc[0]

            c1, c2 = st.columns([2, 1])
            with c1:
                st.markdown(f"##### 📋 {m['meeting_no']} — {m['meeting_type']}")
                st.markdown(
                    f"**📅 วันที่:** {_fmt_date(m['meeting_date'])}  \n"
                    f"**📌 สถานะ:** {_meeting_badge(m['status'])}  \n"
                    f"**📄 Minutes Ref:** `{m.get('minutes_reference', '-')}`"
                )
            with c2:
                st.markdown(f"**👥 ผู้เข้าร่วม (กทพ.):**  \n{m.get('attendees', '-')}")
                st.markdown(f"**👥 ผู้เข้าร่วม (ที่ปรึกษา):**  \n{m.get('consultant_attendees', '-')}")

            with st.expander("📝 ระเบียบวาระ", expanded=True):
                st.write(m.get("agenda", "-"))

            with st.expander("📝 บันทึกสรุป", expanded=False):
                st.write(m.get("minutes_text", "-"))

            linked_ms = _split_ids(m.get("linked_milestone_ids", ""))
            linked_dl = _split_ids(m.get("linked_deliverable_ids", ""))
            linked_iss = _split_ids(m.get("linked_issue_ids", ""))
            if linked_ms or linked_dl or linked_iss:
                st.markdown("**🔗 เชื่อมโยง:**")
                if linked_ms:
                    st.markdown(f"- 📌 Milestones: `{', '.join(linked_ms)}`")
                if linked_dl:
                    st.markdown(f"- 📦 Deliverables: `{', '.join(linked_dl)}`")
                if linked_iss:
                    st.markdown(f"- ⚠️ Issues: `{', '.join(linked_iss)}`")

            m_res = res_df[res_df["meeting_id"] == detail_id] if not res_df.empty else res_df
            if not m_res.empty:
                st.markdown("**✅ มติในการประชุมนี้:**")
                m_res_view = pd.DataFrame({
                    "เลขที่":      m_res["resolution_no"],
                    "มติ":         m_res["resolution_text"].astype(str).str.slice(0, 80),
                    "ผู้รับผิดชอบ": m_res["responsible_person"],
                    "Due":         m_res["due_date"].apply(_fmt_date),
                    "สถานะ":       m_res["status"].apply(_res_badge),
                })
                st.dataframe(m_res_view, use_container_width=True, hide_index=True)

            # ---- Soft Delete + Restore ----
            if st.session_state.role in ("admin", "monitoring"):
                st.markdown("---")
                with st.expander("🗑️ ลบการประชุม (Soft Delete)", expanded=False):
                    st.caption("⚠️ ซ่อนจาก UI — ข้อมูลยังอยู่ใน CSV, Audit ยังคงครบ")
                    del_id = st.selectbox(
                        "เลือก Meeting ID ที่จะลบ",
                        mtg_df["meeting_id"].astype(str).tolist(),
                        key="mh_del_sel",
                    )
                    del_reason = st.text_input("เหตุผลที่ลบ (บังคับ)", key="mh_del_reason")
                    if st.button("🗑️ Soft Delete", type="primary", key="mh_del_btn"):
                        if not del_reason.strip():
                            st.error("⚠️ กรุณาระบุเหตุผล")
                        else:
                            try:
                                meeting_repo.soft_delete(
                                    del_id, del_reason, st.session_state.user
                                )
                                st.success(f"✅ ซ่อน `{del_id}` แล้ว")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ {e}")

                with st.expander("↩️ คืนค่า (Restore)", expanded=False):
                    try:
                        from core.void_registry import read_voids
                        vd = read_voids()
                        vd_mtg = vd[vd["record_type"] == "meeting"] if not vd.empty else vd
                        if vd_mtg.empty:
                            st.info("ไม่มีรายการที่ถูก Void")
                        else:
                            rid = st.selectbox(
                                "เลือก Meeting ID",
                                vd_mtg["record_id"].tolist(),
                                key="mh_restore_sel",
                            )
                            if st.button("↩️ คืนค่า", key="mh_restore_btn"):
                                if meeting_repo.restore(rid, st.session_state.user):
                                    st.success(f"✅ คืนค่า `{rid}` แล้ว")
                                    st.rerun()
                    except Exception as e:
                        st.error(f"❌ {e}")

            # ---- Chart ----
            st.markdown("---")
            st.markdown("#### 📊 จำนวนประชุมตามประเภท")
            type_counts = mtg_df["meeting_type"].value_counts()
            fig = go.Figure(data=[go.Bar(
                x=type_counts.index.tolist(),
                y=type_counts.values.tolist(),
                marker_color="#0B5ED7",
                text=type_counts.values.tolist(),
                textposition="outside",
            )])
            fig.update_layout(
                height=300, plot_bgcolor="#FAFBFC",
                xaxis_title="ประเภทการประชุม", yaxis_title="จำนวนครั้ง",
                margin=dict(l=10, r=10, t=20, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)

    # ============================================================
    # TAB 4 — CSV
    # ============================================================
    with t4:
        st.markdown("### 📥 ข้อมูล CSV (อ่านเท่านั้น)")

        cA, cB = st.columns(2)
        with cA:
            st.markdown("#### 📄 `meeting_history.csv`")
            if mtg_df.empty:
                st.info("ยังไม่มีข้อมูล")
            else:
                st.dataframe(mtg_df, use_container_width=True, hide_index=True, height=280)
                st.download_button(
                    "⬇️ ดาวน์โหลด meeting_history.csv",
                    data=mtg_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"meeting_history_{today_str()}.csv",
                    mime="text/csv",
                    key="dl_mtg",
                )

        with cB:
            st.markdown("#### 📄 `resolution_history.csv`")
            if res_df.empty:
                st.info("ยังไม่มีข้อมูล")
            else:
                st.dataframe(res_df, use_container_width=True, hide_index=True, height=280)
                st.download_button(
                    "⬇️ ดาวน์โหลด resolution_history.csv",
                    data=res_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"resolution_history_{today_str()}.csv",
                    mime="text/csv",
                    key="dl_res",
                )