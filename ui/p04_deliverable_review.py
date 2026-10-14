"""Deliverable Review — ตรวจทีละชิ้นงานตาม Checklist 8 ข้อ
บทบาท: 'Screen ลำดับแรก' ก่อนส่งคณะกรรมการตรวจรับ (p09)

เวอร์ชันนี้:
- ✅ Next Action (D) อยู่นอก form — เพื่อให้ dynamic แสดง/ซ่อนได้ทันที
- ✅ "นัดตรวจรอบถัดไป" แสดงเฉพาะเมื่อ action ต้องนัดจริง
- ✅ ส่งให้คณะกรรมการ / ปิดการตรวจ → แสดง banner แทนบังคับกรอกวัน
- ✅ Validation: ถ้า action ต้องนัด → ต้องมีวันที่
- ✅ History แสดง next_action + next_review_date
"""
import streamlit as st
import pandas as pd
from datetime import date, timedelta

from repositories.base_repo import AppendOnlyRepo
from repositories.deliverable_repo import DeliverableRepo
from repositories.progress_repo import ProgressRepo
from repositories.issue_repo import IssueRepo
from core.ids import new_id
from core.time_util import now_str, today_str
from core.audit import append_audit
from core.validator import ValidationError


# ============================================================
# CONSTANTS
# ============================================================
CHECKLIST_ITEMS = [
    ("checklist_1_doc",        "มีเอกสารตาม TOR"),
    ("checklist_2_content",    "เนื้อหาครบตาม TOR"),
    ("checklist_3_evidence",   "มีหลักฐานประกอบ"),
    ("checklist_4_plan",       "สอดคล้องกับแผนงาน"),
    ("checklist_5_milestone",  "สอดคล้องกับ Milestone"),
    ("checklist_6_prev",       "สอดคล้องกับงานก่อนหน้า"),
    ("checklist_7_fixed",      "มีการแก้ไขจากข้อสังเกตเดิมแล้ว"),
    ("checklist_8_no_pending", "ไม่มีประเด็นค้างที่กระทบการตรวจรับ"),
]

REVIEW_DIMENSIONS = [
    "Operation",
    "Financial & Accounting",
    "Technical",
    "Law & Regulations",
]

RESULTS = [
    "ผ่าน",
    "ผ่านโดยมีข้อสังเกต",
    "ต้องแก้ไข",
    "ไม่ผ่าน",
]

COMPLIANCE = [
    "Compliant",
    "Partially Compliant",
    "Non-Compliant",
    "Not Applicable",
]

NEXT_ACTIONS = [
    "ส่งกลับให้ที่ปรึกษาแก้ไข",
    "ส่งให้คณะกรรมการตรวจรับ",
    "ปิดการตรวจ",
    "รอหลักฐานเพิ่มเติม",
    "อื่น ๆ",
]

# ── เงื่อนไขการแสดง "นัดตรวจรอบถัดไป" ──
# ต้องระบุวันนัด (บังคับ)
ACTIONS_REQUIRE_DATE = (
    "ส่งกลับให้ที่ปรึกษาแก้ไข",
    "รอหลักฐานเพิ่มเติม",
)
# ตัวเลือก (ไม่บังคับ)
ACTIONS_OPTIONAL_DATE = (
    "อื่น ๆ",
)
# ที่เหลือ (ส่งให้ กก. / ปิดการตรวจ) → ไม่ต้องนัด

REVIEW_FIELDS = [
    "timestamp", "review_id", "deliverable_id", "milestone_id", "tor_clause",
    "version_no", "review_dimension", "reviewer", "review_date",
    "checklist_1_doc", "checklist_2_content", "checklist_3_evidence",
    "checklist_4_plan", "checklist_5_milestone", "checklist_6_prev",
    "checklist_7_fixed", "checklist_8_no_pending",
    "checklist_score",
    "result", "compliance_status", "comment", "evidence_reference",
    "linked_issue_id", "next_action", "next_review_date", "created_by",
]


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


def _safe_float_str(x):
    try:
        return f"{float(x):.1f}%"
    except Exception:
        return "-"


def _status_badge(s):
    m = {
        "Not Started": "⚪ ยังไม่เริ่ม",
        "In Progress": "🔵 กำลังทำ",
        "Submitted": "🟣 ส่งแล้ว",
        "Under Review": "🟠 กำลังตรวจ",
        "Revision Required": "🟠 ต้องแก้ไข",
        "Accepted": "🟢 ตรวจรับแล้ว",
        "Closed": "✅ ปิดแล้ว",
    }
    return m.get(s, s or "-")


def _result_badge(r):
    m = {
        "ผ่าน": "🟢 ผ่าน",
        "ผ่านโดยมีข้อสังเกต": "🟡 ผ่าน (มีข้อสังเกต)",
        "ต้องแก้ไข": "🟠 ต้องแก้ไข",
        "ไม่ผ่าน": "🔴 ไม่ผ่าน",
        "รอตรวจ": "⚪ รอตรวจ",
    }
    return m.get(r, r or "-")


def _next_version(did: str, rv_df: pd.DataFrame) -> str:
    """คำนวณเลข version ถัดไปของ deliverable นี้"""
    if rv_df.empty:
        return "V01"
    existing = rv_df[rv_df["deliverable_id"] == did]
    if existing.empty:
        return "V01"
    if (existing["version_no"].astype(str) == "FINAL").any():
        return "FINAL"
    nums = []
    for v in existing["version_no"].astype(str):
        if v.startswith("V") and v[1:].isdigit():
            nums.append(int(v[1:]))
    return f"V{max(nums) + 1:02d}" if nums else "V01"


def _validate_review(data: dict):
    """Validate ข้อมูลการ review"""
    # BR: ต้องแก้ไข / ไม่ผ่าน → ต้องมี Comment
    if data["result"] in ("ต้องแก้ไข", "ไม่ผ่าน") and not (data.get("comment") or "").strip():
        raise ValidationError(
            "⚠️ เลือก 'ต้องแก้ไข' หรือ 'ไม่ผ่าน' ต้องระบุ Comment / Finding"
        )

    # BR: ผ่าน → ต้องติ๊ก checklist ครบ 8
    if data["result"] == "ผ่าน" and int(data.get("checklist_score", 0)) < 8:
        raise ValidationError(
            f"⚠️ เลือก 'ผ่าน' ต้องติ๊ก checklist ครบ 8 ข้อ "
            f"(ปัจจุบัน {data.get('checklist_score', 0)}/8)"
        )

    # BR: Non-Compliant → ต้องมี Finding
    if data["compliance_status"] == "Non-Compliant" and not (data.get("comment") or "").strip():
        raise ValidationError("⚠️ Compliance = Non-Compliant ต้องระบุ Finding")

    # BR: ต้องระบุชื่อผู้ตรวจ
    if not (data.get("reviewer") or "").strip():
        raise ValidationError("⚠️ ต้องระบุชื่อผู้ตรวจ")

    # ★ BR: ถ้า action ต้องนัด → ต้องมีวันที่
    if data.get("next_action") in ACTIONS_REQUIRE_DATE:
        if not (data.get("next_review_date") or "").strip():
            raise ValidationError(
                f"⚠️ Action '{data['next_action']}' ต้องระบุวันนัดตรวจรอบถัดไป"
            )


# ============================================================
# MAIN RENDER
# ============================================================
def render():
    st.title("🔎 Deliverable Review")
    st.caption(
        "ตรวจทีละชิ้นงานตาม Checklist 8 ข้อ — 'Screen ลำดับแรก' "
        "ก่อนส่งคณะกรรมการตรวจรับพัสดุ (Milestone Acceptance)"
    )

    dl_repo = DeliverableRepo()
    rv_repo = AppendOnlyRepo("deliverable_review_history.csv", REVIEW_FIELDS)

    dl_df = dl_repo.read()
    dl_df = dl_df[
        dl_df["milestone_id"].astype(str).str.startswith("MLS")
    ].reset_index(drop=True)

    rv_df = rv_repo.read()

    if dl_df.empty:
        st.info("ℹ️ ยังไม่มี Deliverable — เพิ่มที่เมนู **📦 Deliverable Master** ก่อน")
        return

    # ============================================================
    # KPI TILES
    # ============================================================
    st.markdown("### 📊 สถานะการตรวจชิ้นงาน")

    reviewed_ids = set(rv_df["deliverable_id"].unique()) if not rv_df.empty else set()
    all_dl_ids = set(dl_df["deliverable_id"].astype(str).unique())
    n_total = len(dl_df)
    n_reviewed = len(reviewed_ids & all_dl_ids)
    n_pending = n_total - n_reviewed

    n_passed = 0
    n_need_fix = 0
    if not rv_df.empty:
        latest_per_dl = rv_df.copy()
        latest_per_dl["_ts"] = pd.to_datetime(latest_per_dl["timestamp"], errors="coerce")
        latest_per_dl = (
            latest_per_dl.sort_values("_ts")
            .groupby("deliverable_id")
            .tail(1)
        )
        n_passed = int((latest_per_dl["result"] == "ผ่าน").sum())
        n_need_fix = int((latest_per_dl["result"] == "ต้องแก้ไข").sum())

    k1, k2, k3, k4, k5 = st.columns(5)

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

    with k1:
        st.markdown(_tile("📦 ชิ้นงานทั้งหมด", f"{n_total}",
                          "Deliverables", "#0B5ED7"), unsafe_allow_html=True)
    with k2:
        st.markdown(_tile("⏳ รอตรวจ", f"{n_pending}",
                          "ยังไม่มีผลการตรวจ", "#F57C00"), unsafe_allow_html=True)
    with k3:
        st.markdown(_tile("🔍 ตรวจแล้ว", f"{n_reviewed}",
                          "มีผลการตรวจแล้ว", "#00838F"), unsafe_allow_html=True)
    with k4:
        st.markdown(_tile("🟢 ผ่าน", f"{n_passed}",
                          "ผลล่าสุด = ผ่าน", "#2E7D32"), unsafe_allow_html=True)
    with k5:
        st.markdown(_tile("🟠 ต้องแก้ไข", f"{n_need_fix}",
                          "ผลล่าสุด = ต้องแก้ไข", "#D32F2F"), unsafe_allow_html=True)

    st.markdown("---")

    # ============================================================
    # TABS
    # ============================================================
    t1, t2, t3, t4 = st.tabs([
        "📋 ภาพรวมการตรวจ",
        "🔍 ตรวจชิ้นงาน",
        "📜 ประวัติการตรวจ",
        "📥 CSV",
    ])

    # ============================================================
    # TAB 1 — OVERVIEW
    # ============================================================
    with t1:
        st.markdown("### 📋 ภาพรวมการตรวจแต่ละชิ้นงาน")

        ms_filter = st.multiselect(
            "กรองตาม Milestone",
            sorted(dl_df["milestone_id"].unique().tolist()),
            default=sorted(dl_df["milestone_id"].unique().tolist()),
            key="rv_ms_filter",
        )
        view = dl_df[dl_df["milestone_id"].isin(ms_filter)].copy()

        def _get_latest(did, col, default="-"):
            if rv_df.empty or did not in rv_df["deliverable_id"].values:
                return default
            sub = rv_df[rv_df["deliverable_id"] == did].sort_values("timestamp")
            if sub.empty:
                return default
            return sub.iloc[-1].get(col, default)

        view["_latest_result"] = view["deliverable_id"].apply(
            lambda x: _get_latest(x, "result", "รอตรวจ")
        )
        view["_latest_version"] = view["deliverable_id"].apply(
            lambda x: _get_latest(x, "version_no")
        )
        view["_n_reviews"] = view["deliverable_id"].apply(
            lambda x: len(rv_df[rv_df["deliverable_id"] == x]) if not rv_df.empty else 0
        )

        tbl = pd.DataFrame({
            "Deliverable":  view["deliverable_id"] + " · "
                            + view["deliverable_name"].astype(str).str.slice(0, 40),
            "Milestone":    view["milestone_id"],
            "TOR":          view["tor_clause"],
            "Weight":       view["weight"].apply(_safe_float_str),
            "Version":      view["_latest_version"],
            "จำนวนครั้ง":    view["_n_reviews"].astype(str) + " ครั้ง",
            "ผลล่าสุด":     view["_latest_result"].apply(_result_badge),
            "Status":       view["status"].apply(_status_badge),
        })
        st.dataframe(tbl, use_container_width=True, hide_index=True)
        st.caption(f"แสดง {len(view)} / {len(dl_df)} รายการ")

    # ============================================================
    # TAB 2 — REVIEW FORM
    # ============================================================
    with t2:
        st.markdown("### 🔍 ตรวจชิ้นงานใหม่")

        dl_sel = st.selectbox(
            "เลือก Deliverable ที่จะตรวจ",
            dl_df["deliverable_id"].tolist(),
            format_func=lambda x: (
                f"{x} · "
                f"{dl_df[dl_df['deliverable_id'] == x]['deliverable_name'].iloc[0][:60]}"
            ),
            key="rv_dl_sel",
        )
        dl_row = dl_df[dl_df["deliverable_id"] == dl_sel].iloc[0]

        # --- ข้อมูลอ้างอิง ---
        info1, info2, info3, info4 = st.columns(4)
        with info1:
            st.markdown(f"**📌 Milestone:** `{dl_row['milestone_id']}`")
        with info2:
            st.markdown(f"**🔗 TOR:** {dl_row.get('tor_clause', '-')}")
        with info3:
            st.markdown(f"**⚖️ Weight:** {_safe_float_str(dl_row.get('weight', 0))}")
        with info4:
            st.markdown(f"**📊 Status:** {_status_badge(dl_row['status'])}")

        # --- ประวัติการตรวจเดิม ---
        prev_reviews = rv_df[rv_df["deliverable_id"] == dl_sel] if not rv_df.empty else rv_df
        if not prev_reviews.empty:
            st.markdown("---")
            st.markdown("#### 📜 ประวัติการตรวจเดิม")
            prev_disp = prev_reviews.sort_values("timestamp", ascending=False).head(5)
            show_cols = [c for c in [
                "review_id", "version_no", "review_dimension",
                "reviewer", "review_date", "checklist_score",
                "result", "comment"
            ] if c in prev_disp.columns]
            prev_disp_show = prev_disp[show_cols].copy()
            if "result" in prev_disp_show.columns:
                prev_disp_show["result"] = prev_disp_show["result"].apply(_result_badge)
            prev_disp_show.columns = [
                "ID", "Version", "ด้าน", "ผู้ตรวจ", "วันที่", "Score", "ผล", "Comment"
            ][:len(show_cols)]
            st.dataframe(prev_disp_show, use_container_width=True, hide_index=True)
        else:
            st.info("ℹ️ ยังไม่มีการตรวจ Deliverable นี้ — ครั้งนี้จะเป็น V01")

        st.markdown("---")
        st.markdown("#### 📝 บันทึกผลการตรวจ")

        auto_version = _next_version(dl_sel, rv_df)

        # ═══════════════════════════════════════════════════════════
        # ★ D. NEXT ACTION (นอก form — เพื่อให้ dynamic ได้)
        # ═══════════════════════════════════════════════════════════
        st.markdown("**D. การดำเนินการต่อ**")

        next_action = st.selectbox(
            "ขั้นตอนถัดไป",
            NEXT_ACTIONS,
            key="rv_next_action",
        )

        # ---- ตรวจเงื่อนไข & แสดง field "นัดตรวจรอบถัดไป" แบบ dynamic ----
        next_review_date_str = ""

        if next_action in ACTIONS_REQUIRE_DATE:
            st.markdown(
                f"""
                <div style="background:#FFF8E1;border-left:4px solid #F57C00;
                            padding:8px 14px;border-radius:8px;font-size:12px;
                            color:#E65100;margin:6px 0;">
                    ⚠️ <b>ต้องระบุวันนัดตรวจรอบถัดไป</b> —
                    Action: <code>{next_action}</code>
                </div>
                """,
                unsafe_allow_html=True,
            )
            next_review_date = st.date_input(
                "📅 นัดตรวจรอบถัดไป (ต้องระบุ)",
                value=date.today() + timedelta(days=7),
                key="rv_next_date",
            )
            next_review_date_str = str(next_review_date)

        elif next_action in ACTIONS_OPTIONAL_DATE:
            st.caption("ℹ️ ตัวเลือกนี้สามารถเว้นวันได้ (ไม่บังคับ)")
            next_review_date = st.date_input(
                "📅 นัดตรวจรอบถัดไป (ถ้ามี)",
                value=date.today() + timedelta(days=7),
                key="rv_next_date",
            )
            next_review_date_str = str(next_review_date)

        else:
            # ส่งให้ กก. / ปิดการตรวจ → ไม่ต้องนัด
            st.markdown(
                f"""
                <div style="background:#E8F5E9;border-left:4px solid #2E7D32;
                            padding:8px 14px;border-radius:8px;font-size:12.5px;
                            color:#2E7D32;margin:6px 0;">
                    ✅ <b>ไม่ต้องนัดตรวจรอบถัดไป</b> —
                    Action: <code>{next_action}</code><br>
                    <span style="font-size:11.5px;color:#666;">
                        งานนี้จะถูกส่งต่อ/ปิดการตรวจ ไม่ต้องกรอกวันนัด
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            next_review_date_str = ""

        st.markdown("---")

        # ═══════════════════════════════════════════════════════════
        # FORM: A, B, C
        # ═══════════════════════════════════════════════════════════
        with st.form("rv_form", clear_on_submit=False):
            # ---- A. Reference ----
            st.markdown("**A. ข้อมูลอ้างอิง**")
            cA1, cA2, cA3 = st.columns(3)
            version = cA1.text_input("เวอร์ชัน", value=auto_version, key="rv_version")
            dimension = cA2.selectbox("ด้านที่ตรวจ", REVIEW_DIMENSIONS, key="rv_dimension")
            reviewer = cA3.text_input("ชื่อผู้ตรวจ",
                                       value=st.session_state.user,
                                       key="rv_reviewer")

            # ---- B. Checklist 8 ข้อ ----
            st.markdown("**B. Checklist 8 ข้อ**")
            checks = {}
            cc1, cc2 = st.columns(2)
            for i, (col_name, label) in enumerate(CHECKLIST_ITEMS):
                col = cc1 if i % 2 == 0 else cc2
                checks[col_name] = col.checkbox(
                    f"{i+1}. {label}",
                    value=False,
                    key=f"rv_chk_{dl_sel}_{i}",
                )

            # ---- C. Result ----
            st.markdown("**C. ผลการตรวจ**")
            cC1, cC2 = st.columns(2)
            result = cC1.radio("ผลรวม", RESULTS, horizontal=False, key="rv_result")
            compliance = cC2.selectbox("Compliance", COMPLIANCE, key="rv_compliance")

            comment = st.text_area("Comment / Finding", height=100, key="rv_comment")
            cC3, cC4 = st.columns(2)
            evidence_ref = cC3.text_input("Evidence Reference", value="",
                                           key="rv_evidence")
            linked_issue = cC4.text_input("Linked Issue ID (ถ้ามี)", value="",
                                           key="rv_linked_issue")

            submitted = st.form_submit_button(
                "💾 บันทึกผลการตรวจ",
                type="primary",
                use_container_width=True,
            )

        # ---- SAVE LOGIC (นอก form) ----
        if submitted:
            try:
                checklist_score = sum(1 for v in checks.values() if v)

                data = {
                    "deliverable_id":     dl_sel,
                    "milestone_id":       dl_row["milestone_id"],
                    "tor_clause":         str(dl_row.get("tor_clause", "")),
                    "version_no":         version.strip() or auto_version,
                    "review_dimension":   dimension,
                    "reviewer":           reviewer.strip(),
                    "review_date":        today_str(),
                    **{k: ("Yes" if v else "No") for k, v in checks.items()},
                    "checklist_score":    checklist_score,
                    "result":             result,
                    "compliance_status":  compliance,
                    "comment":            comment,
                    "evidence_reference": evidence_ref,
                    "linked_issue_id":    linked_issue,
                    "next_action":        next_action,
                    "next_review_date":   next_review_date_str,
                }
                _validate_review(data)

                rid = new_id("review")
                row = {
                    "timestamp":  now_str(),
                    "review_id":  rid,
                    "created_by": st.session_state.user,
                    **data,
                }
                rv_repo.append(row)

                # --- Update Deliverable Master ---
                new_status = dl_row["status"]
                if result == "ผ่าน":
                    new_status = "Accepted"
                elif result == "ต้องแก้ไข":
                    new_status = "Revision Required"
                elif result == "ไม่ผ่าน":
                    new_status = "Under Review"

                new_dl = dl_row.to_dict()
                new_dl.update({
                    "status":             new_status,
                    "compliance_status":  compliance,
                    "reviewer":           reviewer.strip(),
                    "review_date":        today_str(),
                    "review_comment":     comment,
                    "updated_at":         now_str(),
                })
                dl_repo.upsert(new_dl, key="deliverable_id")

                # --- Audit Log ---
                append_audit(
                    st.session_state.user,
                    "REVIEW",
                    "DELIVERABLE",
                    dl_sel,
                    old_value="",
                    new_value=str(row)[:500],
                    reason=(
                        f"Review {version}: {result} ({checklist_score}/8) · "
                        f"Next: {next_action}"
                        + (f" @ {next_review_date_str}" if next_review_date_str else "")
                    ),
                )

                st.success(
                    f"✅ บันทึกผลการตรวจ `{rid}` สำเร็จ — {result} "
                    f"({checklist_score}/8 checklist)"
                )

                # ---- Flash: แสดง next action ที่บันทึก ----
                if next_review_date_str:
                    st.info(
                        f"📅 **นัดตรวจรอบถัดไป:** {next_review_date_str} "
                        f"({next_action})"
                    )
                else:
                    st.info(f"✅ **Next Action:** {next_action} (ไม่ต้องนัดตรวจ)")

                st.rerun()

            except ValidationError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"❌ {type(e).__name__}: {e}")

    # ============================================================
    # TAB 3 — HISTORY
    # ============================================================
    with t3:
        st.markdown("### 📜 ประวัติการตรวจทั้งหมด")

        if rv_df.empty:
            st.info("ยังไม่มีการบันทึกผลการตรวจ")
        else:
            h1, h2 = st.columns(2)
            ms_h_filter = h1.multiselect(
                "Milestone",
                sorted(rv_df["milestone_id"].unique().tolist()),
                default=sorted(rv_df["milestone_id"].unique().tolist()),
                key="rv_hist_ms",
            )
            dim_h_filter = h2.multiselect(
                "ด้านที่ตรวจ",
                REVIEW_DIMENSIONS,
                default=REVIEW_DIMENSIONS,
                key="rv_hist_dim",
            )

            h_view = rv_df.copy()
            if ms_h_filter:
                h_view = h_view[h_view["milestone_id"].isin(ms_h_filter)]
            if dim_h_filter:
                h_view = h_view[h_view["review_dimension"].isin(dim_h_filter)]

            h_view = h_view.sort_values("timestamp", ascending=False)

            show_cols = [c for c in [
                "timestamp", "review_id", "deliverable_id", "milestone_id",
                "version_no", "review_dimension", "reviewer", "review_date",
                "checklist_score", "result", "compliance_status",
                "next_action", "next_review_date", "comment",
            ] if c in h_view.columns]

            h_show = h_view[show_cols].copy()
            if "result" in h_show.columns:
                h_show["result"] = h_show["result"].apply(_result_badge)

            # ★ แสดง next_review_date ว่างเป็น "—"
            if "next_review_date" in h_show.columns:
                h_show["next_review_date"] = h_show["next_review_date"].apply(
                    lambda x: x if (x and str(x).strip() not in ("", "None", "nan")) else "—"
                )

            st.caption(f"แสดง {len(h_view)} รายการทั้งหมด (เรียงจากใหม่สุด)")
            st.dataframe(h_show, use_container_width=True, hide_index=True)

            # --- สรุป Version ---
            st.markdown("---")
            st.markdown("#### 📊 สรุป Version แต่ละ Deliverable")

            version_summary = (
                h_view.sort_values("timestamp")
                .groupby("deliverable_id")
                .agg(
                    n_reviews=("review_id", "count"),
                    latest_version=("version_no", "last"),
                    latest_result=("result", "last"),
                )
                .reset_index()
            )
            version_summary["latest_result"] = version_summary["latest_result"].apply(_result_badge)
            version_summary.columns = ["Deliverable", "จำนวนครั้ง", "Version ล่าสุด", "ผลล่าสุด"]
            st.dataframe(version_summary, use_container_width=True, hide_index=True)

    # ============================================================
    # TAB 4 — CSV
    # ============================================================
    with t4:
        st.markdown("### 📥 ข้อมูล CSV (อ่านเท่านั้น)")
        st.caption("ไฟล์จริง: `data/history/deliverable_review_history.csv`")

        if rv_df.empty:
            st.info("ยังไม่มีข้อมูล")
        else:
            st.dataframe(rv_df, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ ดาวน์โหลด deliverable_review_history.csv",
                data=rv_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"deliverable_review_history_{today_str()}.csv",
                mime="text/csv",
            )