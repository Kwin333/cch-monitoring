"""Audit Log — Comprehensive Read-only Viewer (Append-only)

คุณสมบัติ:
- 📊 KPI Dashboard: ทั้งหมด, วันนี้, users, modules, actions
- 🔍 Filter: Date range, User, Module, Action, Session, Search
- 📜 Timeline view + Card-style + Detail viewer
- 🔎 Diff viewer: old_value → new_value comparison
- 📈 Charts: Actions per day, by module, by user, action type
- 🕵️ Compliance Summary สำหรับผู้ตรวจสอบ
- 📥 CSV Export + JSON Export
- 🔒 Read-only — ห้ามลบ/แก้ (append-only)

หมายเหตุ: หน้านี้เป็น read-only ตามหลักการ audit trail
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta
from pathlib import Path

from core.audit import read_audit, FIELDS
from core.time_util import today_str


# ============================================================
# CONSTANTS
# ============================================================
ACTION_COLORS = {
    "CREATE":       "#2E7D32",
    "UPDATE":       "#0B5ED7",
    "REVIEW":       "#9C27B0",
    "SOFT_DELETE":  "#F57C00",
    "RESTORE":      "#00838F",
    "VOID":         "#D32F2F",
}

ACTION_LABELS = {
    "CREATE":       "🟢 CREATE",
    "UPDATE":       "🔵 UPDATE",
    "REVIEW":       "🟣 REVIEW",
    "SOFT_DELETE":  "🟠 SOFT_DELETE",
    "RESTORE":      "🔷 RESTORE",
    "VOID":         "🔴 VOID",
}

MODULE_LABELS = {
    "PROJECT":      "⚙️ PROJECT",
    "MILESTONE":    "📅 MILESTONE",
    "DELIVERABLE":  "📦 DELIVERABLE",
    "PROGRESS":     "📈 PROGRESS",
    "MEETING":      "📅 MEETING",
    "RESOLUTION":   "✅ RESOLUTION",
    "ACTION":       "⚡ ACTION",
    "ISSUE":        "⚠️ ISSUE",
    "ACCEPTANCE":   "🔍 ACCEPTANCE",
    "PAYMENT":      "💵 PAYMENT",
    "SETTINGS":     "🔧 SETTINGS",
}

QUICK_RANGES = {
    "วันนี้":          1,
    "7 วันล่าสุด":     7,
    "30 วันล่าสุด":    30,
    "90 วันล่าสุด":    90,
    "365 วันล่าสุด":   365,
}

PAGE_SIZE_OPTIONS = [25, 50, 100, 250, 500, 1000]


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


def _fmt_dt(s):
    try:
        dt = pd.to_datetime(str(s), errors="coerce")
        if pd.isna(dt):
            return str(s) if s else "-"
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(s) if s else "-"


def _shorten(s, n=120):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s)
    return s[:n] + "…" if len(s) > n else s


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


def _action_badge(action):
    return ACTION_LABELS.get(action, f"• {action}")


def _module_badge(module):
    return MODULE_LABELS.get(module, module or "-")


def _action_color(action):
    return ACTION_COLORS.get(action, "#757575")


def _safe_get(row, key, default=""):
    try:
        val = row.get(key, default)
        if pd.isna(val) if not isinstance(val, (list, dict)) else False:
            return default
        return val if val not in (None, "") else default
    except Exception:
        return default


# ============================================================
# INTEGRITY CHECK
# ============================================================
def _integrity_summary(df):
    """ตรวจความสมบูรณ์ของ audit log"""
    issues = []

    if df.empty:
        return {"status": "empty", "issues": [], "n": 0}

    # 1) Missing audit_id
    if "audit_id" in df.columns:
        n_missing = int(df["audit_id"].isna().sum() + (df["audit_id"] == "").sum())
        if n_missing > 0:
            issues.append(f"⚠️ {n_missing} แถวไม่มี audit_id")

    # 2) Timestamp ordering
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce")
        n_bad = int(ts.isna().sum())
        if n_bad > 0:
            issues.append(f"⚠️ {n_bad} แถว timestamp ไม่ถูกต้อง")

    # 3) Required fields
    required = ["user", "action", "module", "record_id"]
    for col in required:
        if col in df.columns:
            n_empty = int((df[col].astype(str).str.strip() == "").sum())
            if n_empty > 0:
                issues.append(f"⚠️ {n_empty} แถว {col} ว่าง")

    status = "ok" if not issues else "warning"
    return {"status": status, "issues": issues, "n": len(df)}


# ============================================================
# MAIN RENDER
# ============================================================
def render():
    st.title("📋 Audit Log (Read-only)")
    st.caption(
        "🔒 Append-only audit trail — ตรวจสอบย้อนหลังสำหรับผู้ตรวจสอบ / ผู้บริหาร"
    )

    # ============================================================
    # LOAD ONCE
    # ============================================================
    try:
        df = read_audit()
    except Exception as e:
        st.error(f"❌ ไม่สามารถอ่าน Audit Log ได้: {e}")
        return

    if df.empty:
        st.info("ℹ️ ยังไม่มี Audit Log — เริ่มทำรายการต่าง ๆ ในระบบ")
        return

    # ============================================================
    # NORMALIZE
    # ============================================================
    df = df.copy()
    df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp_dt"])
    df = df.sort_values("timestamp_dt", ascending=False).reset_index(drop=True)

    # Ensure string columns
    for col in ["audit_id", "user", "action", "module", "record_id",
                "old_value", "new_value", "reason", "session_id", "version"]:
        if col in df.columns:
            df[col] = df[col].astype(str).fillna("")
        else:
            df[col] = ""

    n_total = len(df)
    min_ts = df["timestamp_dt"].min()
    max_ts = df["timestamp_dt"].max()
    active_days = df["timestamp_dt"].dt.date.nunique()

    # Today count
    today = date.today()
    n_today = int((df["timestamp_dt"].dt.date == today).sum())

    # ============================================================
    # KPI TILES
    # ============================================================
    st.markdown("### 📊 ภาพรวม Audit Log")

    n_users = df["user"].nunique()
    n_modules = df["module"].nunique()
    n_actions = df["action"].nunique()

    # Most active user
    top_user = (
        df[df["user"] != ""]["user"].value_counts().index[0]
        if (df["user"] != "").any() else "-"
    )

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(_tile("📋 ทั้งหมด", f"{n_total:,}",
                          f"{active_days} วันที่ active", "#0B5ED7"),
                    unsafe_allow_html=True)
    with k2:
        today_color = "#2E7D32" if n_today > 0 else "#9E9E9E"
        st.markdown(_tile("📅 วันนี้", f"{n_today}",
                          "events", today_color), unsafe_allow_html=True)
    with k3:
        st.markdown(_tile("👥 Users", f"{n_users}",
                          f"Top: {_shorten(top_user, 20)}", "#6A1B9A"),
                    unsafe_allow_html=True)
    with k4:
        st.markdown(_tile("📦 Modules", f"{n_modules}",
                          "โมดูลที่บันทึก", "#00838F"),
                    unsafe_allow_html=True)
    with k5:
        st.markdown(_tile("⚡ Action Types", f"{n_actions}",
                          f"ตั้งแต่ {min_ts.strftime('%d/%m/%Y')}",
                          "#F57C00"), unsafe_allow_html=True)

    # ---- Integrity check ----
    integ = _integrity_summary(df)
    if integ["status"] == "warning":
        with st.expander(f"⚠️ พบ {len(integ['issues'])} ความผิดปกติใน Audit Log", expanded=False):
            for issue in integ["issues"]:
                st.markdown(f"- {issue}")
    else:
        st.markdown(
            f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
            f'padding:8px 14px;border-radius:8px;font-size:12.5px;'
            f'margin-top:8px;color:#2E7D32;">'
            f'✅ <b>Audit Log Integrity OK</b> — '
            f'{integ["n"]:,} records ตรวจสอบแล้ว'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ============================================================
    # TABS
    # ============================================================
    t1, t2, t3, t4 = st.tabs([
        "📜 Audit Trail",
        "🔍 Diff Viewer",
        "📈 Charts",
        "📥 Export",
    ])

    # ============================================================
    # TAB 1 — AUDIT TRAIL
    # ============================================================
    with t1:
        st.markdown("### 🔎 Filter")

        # ---- Quick range + Date range ----
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            quick_range = st.selectbox(
                "ช่วงเวลา",
                ["ทั้งหมด"] + list(QUICK_RANGES.keys()) + ["กำหนดเอง"],
                index=0,
                key="al_quick_range",
            )

        if quick_range == "ทั้งหมด":
            default_from = min_ts.date()
            default_to = today
            disabled = True
        elif quick_range == "กำหนดเอง":
            default_from = min_ts.date()
            default_to = today
            disabled = False
        else:
            days = QUICK_RANGES[quick_range]
            default_from = today - timedelta(days=days)
            default_to = today
            disabled = True

        with c2:
            date_from = st.date_input(
                "จากวันที่",
                value=st.session_state.get("al_date_from", default_from),
                disabled=disabled,
                key="al_date_from",
            )
        with c3:
            date_to = st.date_input(
                "ถึงวันที่",
                value=st.session_state.get("al_date_to", default_to),
                disabled=disabled,
                key="al_date_to",
            )

        # ---- Multi-filters ----
        c4, c5, c6 = st.columns([1, 1, 1])
        with c4:
            all_users = sorted([u for u in df["user"].unique().tolist() if u])
            f_users = st.multiselect(
                "User",
                all_users,
                default=all_users,
                key="al_users",
            )
        with c5:
            all_modules = sorted([m for m in df["module"].unique().tolist() if m])
            f_modules = st.multiselect(
                "Module",
                all_modules,
                default=all_modules,
                format_func=_module_badge,
                key="al_modules",
            )
        with c6:
            all_actions = sorted([a for a in df["action"].unique().tolist() if a])
            f_actions = st.multiselect(
                "Action",
                all_actions,
                default=all_actions,
                format_func=_action_badge,
                key="al_actions",
            )

        # ---- Search + Sort ----
        c7, c8 = st.columns([3, 1])
        with c7:
            search = st.text_input(
                "🔍 Search (Audit ID / Record ID / Reason / Value)",
                value="",
                key="al_search",
            )
        with c8:
            sort_order = st.selectbox(
                "เรียงลำดับ",
                ["ใหม่ → เก่า", "เก่า → ใหม่"],
                key="al_sort",
            )

        # ---- Apply filters ----
        view = df.copy()

        # Date
        if not disabled:
            view = view[
                (view["timestamp_dt"].dt.date >= date_from)
                & (view["timestamp_dt"].dt.date <= date_to)
            ]
        else:
            view = view[
                (view["timestamp_dt"].dt.date >= default_from)
                & (view["timestamp_dt"].dt.date <= default_to)
            ]

        # Users
        if f_users:
            view = view[view["user"].isin(f_users)]
        else:
            view = view.iloc[0:0]

        # Modules
        if f_modules:
            view = view[view["module"].isin(f_modules)]
        else:
            view = view.iloc[0:0]

        # Actions
        if f_actions:
            view = view[view["action"].isin(f_actions)]
        else:
            view = view.iloc[0:0]

        # Search
        if search.strip():
            s = search.strip().lower()
            view = view[
                view["audit_id"].astype(str).str.lower().str.contains(s, na=False)
                | view["record_id"].astype(str).str.lower().str.contains(s, na=False)
                | view["reason"].astype(str).str.lower().str.contains(s, na=False)
                | view["old_value"].astype(str).str.lower().str.contains(s, na=False)
                | view["new_value"].astype(str).str.lower().str.contains(s, na=False)
            ]

        # Sort
        view = view.sort_values(
            "timestamp_dt", ascending=(sort_order == "เก่า → ใหม่")
        ).reset_index(drop=True)

        # ---- Pagination ----
        st.markdown("---")
        cA, cB, cC = st.columns([1, 1, 2])
        with cA:
            page_size = st.selectbox(
                "แสดงหน้าละ",
                PAGE_SIZE_OPTIONS,
                index=1,
                key="al_page_size",
            )
        with cB:
            total_pages = max(1, (len(view) + page_size - 1) // page_size)
            page = st.number_input(
                f"หน้า (1–{total_pages})",
                min_value=1,
                max_value=total_pages,
                value=1,
                step=1,
                key="al_page_num",
            )
        with cC:
            st.markdown(
                f"<div style='padding-top:24px;font-size:13px;color:#666;'>"
                f"<b>ผลลัพธ์:</b> {len(view):,} / {n_total:,} records</div>",
                unsafe_allow_html=True,
            )

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_view = view.iloc[start_idx:end_idx]

        st.markdown("---")

        # ---- Render events ----
        if page_view.empty:
            st.info("ไม่พบรายการที่ตรงกับตัวกรอง")
        else:
            current_date = None
            for _, e in page_view.iterrows():
                ev_date = e["timestamp_dt"].date()

                # Date separator
                if ev_date != current_date:
                    current_date = ev_date
                    d_label = ev_date.strftime("%A %d/%m/%Y")
                    st.markdown(
                        f'<div style="margin:14px 0 8px 0;padding:6px 12px;'
                        f'background:#F0F4F8;border-radius:6px;'
                        f'font-size:12px;font-weight:700;color:#003366;">'
                        f'📅 {d_label}</div>',
                        unsafe_allow_html=True,
                    )

                action = e["action"]
                color = _action_color(action)
                action_lbl = _action_badge(action)
                module_lbl = _module_badge(e["module"])

                time_str = e["timestamp_dt"].strftime("%H:%M:%S")
                user_txt = f'👤 {e["user"]}' if e["user"] else "👤 -"
                reason_txt = _shorten(e["reason"], 100)
                old_txt = _shorten(e["old_value"], 60)
                new_txt = _shorten(e["new_value"], 60)

                # Diff display
                diff_html = ""
                if old_txt or new_txt:
                    diff_html = (
                        f'<div style="font-size:11px;color:#666;margin-top:4px;">'
                        f'<b>Old:</b> <code style="color:#D32F2F;">{old_txt or "-"}</code> '
                        f'→ <b>New:</b> <code style="color:#2E7D32;">{new_txt or "-"}</code>'
                        f'</div>'
                    )

                reason_html = (
                    f'<div style="font-size:11px;color:#555;margin-top:3px;'
                    f'font-style:italic;">💬 {reason_txt}</div>'
                    if reason_txt else ""
                )

                st.markdown(
                    f'<div style="background:#FFFFFF;border-radius:8px;'
                    f'padding:10px 14px;border-left:4px solid {color};'
                    f'box-shadow:0 1px 4px rgba(0,51,102,0.05);'
                    f'margin-bottom:6px;">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;flex-wrap:wrap;gap:8px;">'
                    f'<div style="font-size:12.5px;font-weight:700;color:#003366;">'
                    f'<span style="background:{color};color:#FFF;'
                    f'padding:2px 8px;border-radius:10px;font-size:10.5px;'
                    f'margin-right:6px;">{action_lbl}</span>'
                    f'{module_lbl} · <code>{e["record_id"] or "-"}</code>'
                    f'</div>'
                    f'<div style="font-size:11.5px;color:#666;font-weight:600;">'
                    f'🕒 {time_str}</div></div>'
                    f'<div style="font-size:11.5px;color:#666;margin-top:4px;">'
                    f'{user_txt} · 🔑 <code>{e["audit_id"] or "-"}</code>'
                    f'</div>'
                    f'{reason_html}{diff_html}</div>',
                    unsafe_allow_html=True,
                )

            # ---- Table view ----
            with st.expander("📋 ตารางแบบละเอียด"):
                tbl = page_view[[
                    "timestamp", "audit_id", "user", "action", "module",
                    "record_id", "reason", "session_id", "version",
                ]].copy()
                tbl["timestamp"] = tbl["timestamp"].apply(_fmt_dt)
                st.dataframe(tbl, use_container_width=True, hide_index=True)

    # ============================================================
    # TAB 2 — DIFF VIEWER
    # ============================================================
    with t2:
        st.markdown("### 🔍 เปรียบเทียบ Old → New")

        # Only show records with old/new values
        diff_df = df[
            (df["old_value"].astype(str).str.strip() != "")
            | (df["new_value"].astype(str).str.strip() != "")
        ].copy()

        if diff_df.empty:
            st.info("ไม่มีรายการที่มี old_value หรือ new_value")
        else:
            # Filter by UPDATE / SOFT_DELETE / RESTORE / VOID
            c1, c2 = st.columns([1, 3])
            with c1:
                diff_actions = st.multiselect(
                    "Action Type",
                    sorted(diff_df["action"].unique().tolist()),
                    default=sorted(diff_df["action"].unique().tolist()),
                    format_func=_action_badge,
                    key="al_diff_actions",
                )
            with c2:
                diff_search = st.text_input(
                    "🔍 Search (Record ID / Reason / Value)",
                    value="", key="al_diff_search",
                )

            diff_view = diff_df.copy()
            if diff_actions:
                diff_view = diff_view[diff_view["action"].isin(diff_actions)]
            if diff_search.strip():
                s = diff_search.strip().lower()
                diff_view = diff_view[
                    diff_view["record_id"].astype(str).str.lower().str.contains(s, na=False)
                    | diff_view["reason"].astype(str).str.lower().str.contains(s, na=False)
                    | diff_view["old_value"].astype(str).str.lower().str.contains(s, na=False)
                    | diff_view["new_value"].astype(str).str.lower().str.contains(s, na=False)
                ]

            diff_view = diff_view.sort_values(
                "timestamp_dt", ascending=False
            ).reset_index(drop=True)

            st.caption(f"แสดง {len(diff_view):,} รายการ (จาก {len(diff_df):,})")

            # ---- Select one ----
            if not diff_view.empty:
                sel_audit = st.selectbox(
                    "เลือกรายการที่ต้องการดู",
                    diff_view["audit_id"].astype(str).tolist(),
                    format_func=lambda x: (
                        f"{x} · "
                        f"{diff_view[diff_view['audit_id']==x]['module'].iloc[0]} · "
                        f"{diff_view[diff_view['audit_id']==x]['record_id'].iloc[0]}"
                    ),
                    key="al_diff_sel",
                )
                row = diff_view[diff_view["audit_id"] == sel_audit].iloc[0]

                # ---- Header ----
                color = _action_color(row["action"])
                st.markdown(
                    f'<div style="background:{color};color:#FFF;'
                    f'padding:12px 18px;border-radius:10px;font-size:14px;'
                    f'font-weight:700;margin:8px 0;">'
                    f'{_action_badge(row["action"])} · '
                    f'{_module_badge(row["module"])} · '
                    f'<code>{row["record_id"]}</code>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # ---- Meta ----
                m1, m2, m3, m4 = st.columns(4)
                with m1:
                    st.markdown(f"**🕒 {_fmt_dt(row['timestamp'])}**")
                with m2:
                    st.markdown(f"**👤 {row['user'] or '-'}**")
                with m3:
                    st.markdown(f"**🔑 Session:** `{row['session_id'] or '-'}`")
                with m4:
                    st.markdown(f"**📌 Version:** `{row['version'] or '-'}`")

                # ---- Reason ----
                if row["reason"]:
                    st.markdown(
                        f'<div style="background:#F0F4F8;border-left:4px solid #0B5ED7;'
                        f'padding:10px 14px;border-radius:8px;font-size:13px;'
                        f'margin:10px 0;">💬 <b>Reason:</b> {row["reason"]}</div>',
                        unsafe_allow_html=True,
                    )

                # ---- Side-by-side diff ----
                st.markdown("---")
                st.markdown("#### 🔍 Diff")
                dc1, dc2 = st.columns(2)
                with dc1:
                    st.markdown(
                        f'<div style="background:#FFEBEE;padding:12px 14px;'
                        f'border-radius:8px;border-left:4px solid #D32F2F;">'
                        f'<div style="font-size:11px;font-weight:700;color:#B71C1C;'
                        f'margin-bottom:6px;">🔴 OLD VALUE</div>'
                        f'<div style="font-size:12px;color:#333;'
                        f'word-break:break-word;white-space:pre-wrap;">'
                        f'{row["old_value"] or "(empty)"}</div></div>',
                        unsafe_allow_html=True,
                    )
                with dc2:
                    st.markdown(
                        f'<div style="background:#E8F5E9;padding:12px 14px;'
                        f'border-radius:8px;border-left:4px solid #2E7D32;">'
                        f'<div style="font-size:11px;font-weight:700;color:#1B5E20;'
                        f'margin-bottom:6px;">🟢 NEW VALUE</div>'
                        f'<div style="font-size:12px;color:#333;'
                        f'word-break:break-word;white-space:pre-wrap;">'
                        f'{row["new_value"] or "(empty)"}</div></div>',
                        unsafe_allow_html=True,
                    )

            # ---- Summary table ----
            st.markdown("---")
            st.markdown("#### 📋 ตารางสรุป")
            sum_cols = [c for c in [
                "timestamp", "audit_id", "user", "action", "module",
                "record_id", "reason",
            ] if c in diff_view.columns]
            sum_show = diff_view[sum_cols].head(100).copy()
            if "timestamp" in sum_show.columns:
                sum_show["timestamp"] = sum_show["timestamp"].apply(_fmt_dt)
            st.dataframe(sum_show, use_container_width=True, hide_index=True)

    # ============================================================
    # TAB 3 — CHARTS
    # ============================================================
    with t3:
        st.markdown("### 📈 Charts วิเคราะห์ Audit Log")

        # ---- Events per day ----
        st.markdown("#### 📊 จำนวน Audit Events ต่อวัน")
        daily = (
            df.assign(day=df["timestamp_dt"].dt.date)
            .groupby("day").size().reset_index(name="count")
            .sort_values("day")
        )
        if len(daily) > 90:
            daily_view = daily.tail(90)
            st.caption(f"แสดง 90 วันล่าสุด (จาก {len(daily)} วัน)")
        else:
            daily_view = daily

        fig1 = go.Figure()
        fig1.add_trace(go.Bar(
            x=daily_view["day"],
            y=daily_view["count"],
            marker_color="#0B5ED7",
            hovertemplate="%{x}<br>%{y} events<extra></extra>",
        ))
        fig1.update_layout(
            height=320, plot_bgcolor="#FAFBFC",
            xaxis_title="วันที่", yaxis_title="จำนวน",
            margin=dict(l=10, r=10, t=20, b=40),
        )
        st.plotly_chart(fig1, use_container_width=True)

        # ---- By Action ----
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### ⚡ สัดส่วนตาม Action")
            action_counts = df["action"].value_counts()
            labels = [_action_badge(a) for a in action_counts.index]
            colors = [_action_color(a) for a in action_counts.index]
            fig2 = go.Figure(data=[go.Pie(
                labels=labels,
                values=action_counts.values.tolist(),
                hole=0.5,
                marker=dict(colors=colors),
            )])
            fig2.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig2, use_container_width=True)

        with c2:
            st.markdown("#### 📦 จำนวนตาม Module")
            module_counts = df["module"].value_counts()
            mod_labels = [_module_badge(m) for m in module_counts.index]
            fig3 = go.Figure(data=[go.Bar(
                x=module_counts.values.tolist(),
                y=mod_labels,
                orientation="h",
                marker_color="#00838F",
                text=module_counts.values.tolist(),
                textposition="outside",
            )])
            fig3.update_layout(
                height=340, plot_bgcolor="#FAFBFC",
                xaxis_title="จำนวน",
                margin=dict(l=10, r=60, t=20, b=40),
            )
            st.plotly_chart(fig3, use_container_width=True)

        # ---- By User ----
        st.markdown("#### 👥 Audit Events by User (Top 10)")
        user_counts = (
            df[df["user"] != ""]["user"]
            .value_counts().head(10)
        )
        if user_counts.empty:
            st.info("ไม่มีข้อมูล User")
        else:
            fig4 = go.Figure(data=[go.Bar(
                x=user_counts.values.tolist(),
                y=user_counts.index.tolist(),
                orientation="h",
                marker_color="#6A1B9A",
                text=user_counts.values.tolist(),
                textposition="outside",
            )])
            fig4.update_layout(
                height=max(280, len(user_counts) * 38),
                plot_bgcolor="#FAFBFC",
                xaxis_title="จำนวน",
                margin=dict(l=10, r=60, t=20, b=40),
            )
            st.plotly_chart(fig4, use_container_width=True)

        # ---- Heatmap ----
        st.markdown("#### 🔥 Heatmap: Module × Action Type")
        heat_pivot = (
            df.groupby(["module", "action"]).size()
            .unstack(fill_value=0)
        )
        if not heat_pivot.empty:
            heat_pivot.index = [_module_badge(m) for m in heat_pivot.index]
            heat_pivot.columns = [_action_badge(a) for a in heat_pivot.columns]

            fig5 = go.Figure(data=go.Heatmap(
                z=heat_pivot.values,
                x=heat_pivot.columns.tolist(),
                y=heat_pivot.index.tolist(),
                colorscale="Blues",
                hovertemplate="%{y}<br>%{x}<br>%{z}<extra></extra>",
            ))
            fig5.update_layout(
                height=max(320, len(heat_pivot) * 38),
                margin=dict(l=10, r=10, t=20, b=80),
            )
            st.plotly_chart(fig5, use_container_width=True)

    # ============================================================
    # TAB 4 — EXPORT
    # ============================================================
    with t4:
        st.markdown("### 📥 Export Audit Log")
        st.caption("ℹ️ Export ตาม filter ที่เลือก หรือทั้งชุด")

        c1, c2 = st.columns(2)
        with c1:
            exp_from = st.date_input(
                "จากวันที่",
                value=min_ts.date(),
                key="al_exp_from",
            )
        with c2:
            exp_to = st.date_input(
                "ถึงวันที่",
                value=max_ts.date(),
                key="al_exp_to",
            )

        c3, c4, c5 = st.columns(3)
        with c3:
            exp_users = st.multiselect(
                "User",
                sorted([u for u in df["user"].unique().tolist() if u]),
                default=sorted([u for u in df["user"].unique().tolist() if u]),
                key="al_exp_users",
            )
        with c4:
            exp_modules = st.multiselect(
                "Module",
                sorted([m for m in df["module"].unique().tolist() if m]),
                default=sorted([m for m in df["module"].unique().tolist() if m]),
                format_func=_module_badge,
                key="al_exp_modules",
            )
        with c5:
            exp_actions = st.multiselect(
                "Action",
                sorted([a for a in df["action"].unique().tolist() if a]),
                default=sorted([a for a in df["action"].unique().tolist() if a]),
                format_func=_action_badge,
                key="al_exp_actions",
            )

        # ---- Build export ----
        exp_df = df.copy()
        exp_df = exp_df[
            (exp_df["timestamp_dt"].dt.date >= exp_from)
            & (exp_df["timestamp_dt"].dt.date <= exp_to)
        ]
        if exp_users:
            exp_df = exp_df[exp_df["user"].isin(exp_users)]
        if exp_modules:
            exp_df = exp_df[exp_df["module"].isin(exp_modules)]
        if exp_actions:
            exp_df = exp_df[exp_df["action"].isin(exp_actions)]

        exp_view = exp_df[[c for c in FIELDS if c in exp_df.columns]].copy()

        st.markdown(f"**จะ export:** {len(exp_view):,} records")
        st.dataframe(exp_view.head(50), use_container_width=True, hide_index=True)
        if len(exp_view) > 50:
            st.caption(f"แสดงตัวอย่าง 50 แถวแรก (จาก {len(exp_view):,})")

        st.markdown("---")
        cD1, cD2 = st.columns(2)

        with cD1:
            st.download_button(
                "⬇️ ดาวน์โหลด CSV",
                data=exp_view.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"audit_log_{today_str()}.csv",
                mime="text/csv",
                use_container_width=True,
                key="al_dl_csv",
            )

        with cD2:
            try:
                json_bytes = exp_view.to_json(
                    orient="records", force_ascii=False, indent=2,
                ).encode("utf-8")
                st.download_button(
                    "⬇️ ดาวน์โหลด JSON",
                    data=json_bytes,
                    file_name=f"audit_log_{today_str()}.json",
                    mime="application/json",
                    use_container_width=True,
                    key="al_dl_json",
                )
            except Exception as e:
                st.warning(f"⚠️ สร้าง JSON ไม่สำเร็จ: {e}")

        # ---- Summary ----
        st.markdown("---")
        st.markdown("#### 📊 สรุปตาม Action")
        if not exp_view.empty and "action" in exp_view.columns:
            sum_a = (
                exp_view.groupby("action").size()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
            )
            sum_a["action"] = sum_a["action"].apply(_action_badge)
            st.dataframe(sum_a, use_container_width=True, hide_index=True)

        # ---- Compliance note ----
        st.markdown("---")
        st.markdown("#### 🕵️ Compliance Summary (สำหรับผู้ตรวจสอบ)")
        st.markdown(
            f"""
            - 📋 **Total audit records:** {n_total:,}
            - 📅 **Date range:** {min_ts.strftime('%d/%m/%Y')} → {max_ts.strftime('%d/%m/%Y')}
            - 📆 **Active days:** {active_days}
            - 👥 **Distinct users:** {n_users}
            - 📦 **Modules tracked:** {n_modules}
            - ⚡ **Action types:** {n_actions}
            - 🔒 **Integrity:** {integ['status'].upper()}
            """
        )

        if integ["status"] == "warning":
            st.warning("⚠️ พบความผิดปกติ — ดูรายละเอียดด้านบน")
        else:
            st.success("✅ Audit log ครบถ้วน สมบูรณ์ พร้อมใช้สำหรับการตรวจสอบ")