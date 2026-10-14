"""Settings — Comprehensive Configuration Manager (v2)

Bug fixes:
- ลบ duplicate import `load_settings` ภายใน render() ที่ทำให้เกิด UnboundLocalError
- ใช้ module-level import อย่างเดียว

★ v2 — เพิ่ม:
- ⚖️ Rebalance Deliverable Weights — ปรับ weights ให้รวม = 100.00%
- 🔄 Force Reseed Master Data — ใช้ force_reseed_master() จาก bootstrap
- แสดง Weight Audit ก่อน Rebalance (ให้เห็นผลกระทบ)
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import shutil
import os
from pathlib import Path
from datetime import datetime

from config_loader import load_settings, save_settings, CFG
from core.audit import append_audit, read_audit
from core.time_util import now_str, today_str


# ============================================================
# CONSTANTS
# ============================================================
SETTINGS_DIR = CFG.parent
BACKUP_DIR = SETTINGS_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path(__file__).parent.parent / "data"
MASTER_DIR = DATA_DIR / "master"

TARGET_WEIGHT_TOTAL = 100.0
WEIGHT_TOLERANCE = 0.01

DEFAULT_SETTINGS = {
    "project_defaults": {
        "duration_days": 360,
        "contract_value": 18971100.00,
    },
    "milestones": [
        {"no": 1, "name": "Inception Report",   "due_day": 30,  "percent": 10},
        {"no": 2, "name": "Progress Report I",  "due_day": 120, "percent": 30},
        {"no": 3, "name": "Interim Report",     "due_day": 180, "percent": 30},
        {"no": 4, "name": "Progress Report II", "due_day": 300, "percent": 20},
        {"no": 5, "name": "Final Report",       "due_day": 360, "percent": 10},
    ],
    "warning_thresholds": {
        "green_variance_pct": -3.0,
        "yellow_variance_pct": -10.0,
        "red_variance_pct": -10.01,
        "due_soon_days": 7,
    },
    "payment": {
        "guarantee_deduction_pct": 10.0,
    },
    "user_roles": ["admin", "monitoring", "reviewer", "committee", "supervisor", "readonly"],
}

ADMIN_ROLES = ("admin",)


# ============================================================
# HELPERS
# ============================================================
def _is_admin():
    return st.session_state.get("role") in ADMIN_ROLES


def _tile(label, value, sub, color):
    return f"""
    <div style="background:#FFFFFF;border-radius:10px;padding:12px 14px;
                border-left:4px solid {color};
                box-shadow:0 2px 6px rgba(0,51,102,0.06);height:100%;">
        <div style="font-size:11.5px;color:#5A5A5A;font-weight:600;">{label}</div>
        <div style="font-size:20px;font-weight:700;color:#003366;
                    line-height:1.1;margin:4px 0;">{value}</div>
        <div style="font-size:11px;color:{color};">{sub}</div>
    </div>
    """


def _file_meta(path):
    if not path.exists():
        return None
    stat = path.stat()
    return {
        "path":   str(path),
        "size":   stat.st_size,
        "mtime":  datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M:%S"),
    }


def _fmt_size(n):
    for unit in ["B", "KB", "MB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _backup_config(cfg, reason="settings_change"):
    if not CFG.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"settings_{stamp}_{reason}.json"
    try:
        shutil.copy2(CFG, backup_path)
        return backup_path
    except Exception:
        return None


def _list_backups():
    if not BACKUP_DIR.exists():
        return []
    files = sorted(
        BACKUP_DIR.glob("settings_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files


def _validate_settings(data):
    errors = []

    pd_cfg = data.get("project_defaults", {})
    dur = pd_cfg.get("duration_days", 0)
    val = pd_cfg.get("contract_value", 0)
    if not (1 <= dur <= 1000):
        errors.append("Duration Days ต้องอยู่ระหว่าง 1–1000")
    if val <= 0:
        errors.append("Contract Value ต้องมากกว่า 0")

    wt = data.get("warning_thresholds", {})
    g = wt.get("green_variance_pct", 0)
    y = wt.get("yellow_variance_pct", 0)
    r = wt.get("red_variance_pct", 0)
    if not (g > y):
        errors.append("Green Variance ต้องมากกว่า Yellow Variance (เช่น -3 > -10)")
    if not (y > r):
        errors.append("Yellow Variance ต้องมากกว่า Red Variance (เช่น -10 > -10.01)")
    if not (0 <= wt.get("due_soon_days", 0) <= 365):
        errors.append("Due Soon Days ต้องอยู่ระหว่าง 0–365")

    p = data.get("payment", {})
    gd = p.get("guarantee_deduction_pct", 0)
    if not (0 <= gd <= 100):
        errors.append("Guarantee Deduction ต้องอยู่ระหว่าง 0–100%")

    ms = data.get("milestones", [])
    if not ms:
        errors.append("ต้องมีอย่างน้อย 1 milestone")
    else:
        total = sum(m.get("percent", 0) for m in ms)
        if abs(total - 100) > 0.01:
            errors.append(f"Payment % รวม = {total:.2f}% (ต้องเท่ากับ 100%)")
        prev = 0
        for m in ms:
            if m.get("due_day", 0) <= prev:
                errors.append(f"Milestone {m.get('no')}: Due Day ต้องเรียงจากน้อยไปมาก")
                break
            prev = m.get("due_day", 0)

    return errors


def _diff_summary(old_cfg, new_cfg):
    diffs = []

    def _walk(o, n, path=""):
        if isinstance(o, dict) and isinstance(n, dict):
            all_keys = set(o.keys()) | set(n.keys())
            for k in all_keys:
                _walk(o.get(k), n.get(k), f"{path}.{k}" if path else k)
        elif isinstance(o, list) and isinstance(n, list):
            if o != n:
                diffs.append((path, str(o), str(n)))
        else:
            if o != n:
                diffs.append((path, str(o), str(n)))

    _walk(old_cfg, new_cfg)
    return diffs


def _save_with_audit(new_cfg, reason, user):
    old_cfg = load_settings()
    diffs = _diff_summary(old_cfg, new_cfg)

    if not diffs:
        return False, "ไม่มีการเปลี่ยนแปลง"

    errors = _validate_settings(new_cfg)
    if errors:
        return False, "Validation: " + "; ".join(errors)

    _backup_config(old_cfg, "before_change")
    save_settings(new_cfg)

    append_audit(
        user, "UPDATE", "SETTINGS", "settings.json",
        old_value=f"{len(diffs)} fields",
        new_value=f"{len(diffs)} fields changed",
        reason=reason,
    )

    return True, f"บันทึกสำเร็จ ({len(diffs)} การเปลี่ยนแปลง)"


# ============================================================
# ★ WEIGHT SUMMARY HELPERS (สำหรับ Rebalance section)
# ============================================================
def _load_deliverable_weights():
    """โหลด weight summary จาก deliverable_master.csv"""
    path = MASTER_DIR / "deliverable_master.csv"
    if not path.exists():
        return None

    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return None

    if "milestone_id" not in df.columns or "weight" not in df.columns:
        return None

    valid = df[df["milestone_id"].astype(str).str.startswith("MLS")].copy()
    if valid.empty:
        return None

    valid["weight"] = pd.to_numeric(valid["weight"], errors="coerce").fillna(0.0)

    by_ms = (
        valid.groupby("milestone_id")
        .agg(Weight=("weight", "sum"), Count=("deliverable_id", "count"))
        .reset_index()
        .sort_values("milestone_id")
    )

    return {
        "df": valid,
        "total": round(float(valid["weight"].sum()), 2),
        "n_items": len(valid),
        "by_milestone": by_ms,
        "path": str(path),
    }


# ============================================================
# MAIN RENDER
# ============================================================
def render():
    st.title("🔧 Settings")
    st.caption("จัดการค่าตั้งต้นของระบบ — การเปลี่ยนแปลงมีผลทันทีกับทุกหน้า")

    is_admin = _is_admin()
    if not is_admin:
        st.warning(
            f"🔒 หน้าตั้งค่าอยู่ในโหมด **อ่านเท่านั้น** "
            f"(Role: `{st.session_state.get('role')}`) — "
            f"เฉพาะ admin เท่านั้นที่แก้ไขได้"
        )

    # LOAD CURRENT
    try:
        cfg = load_settings()
    except Exception as e:
        st.error(f"❌ ไม่สามารถโหลด settings.json: {e}")
        return

    # FLASH MESSAGE
    if "settings_last_saved" in st.session_state:
        info = st.session_state.pop("settings_last_saved")
        st.markdown(
            f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
            f'padding:10px 14px;border-radius:8px;font-size:13px;">'
            f'✅ <b>{info["msg"]}</b> — {info["n"]} การเปลี่ยนแปลง'
            f'</div>',
            unsafe_allow_html=True,
        )

    # KPI TILES
    st.markdown("### 📊 ภาพรวม Configuration")

    dur = cfg.get("project_defaults", {}).get("duration_days", 0)
    val = cfg.get("project_defaults", {}).get("contract_value", 0)
    g = cfg.get("warning_thresholds", {}).get("green_variance_pct", 0)
    y = cfg.get("warning_thresholds", {}).get("yellow_variance_pct", 0)
    due_soon = cfg.get("warning_thresholds", {}).get("due_soon_days", 0)
    gd = cfg.get("payment", {}).get("guarantee_deduction_pct", 0)
    n_ms = len(cfg.get("milestones", []))
    n_users = len(cfg.get("user_roles", []))

    validation_errors = _validate_settings(cfg)
    n_errors = len(validation_errors)

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(_tile("📋 Duration", f"{dur} วัน",
                          "ระยะเวลาโครงการ", "#0B5ED7"), unsafe_allow_html=True)
    with k2:
        st.markdown(_tile("💰 มูลค่าสัญญา", f"{val:,.0f} ฿",
                          "ตามสัญญาจ้าง", "#2E7D32"), unsafe_allow_html=True)
    with k3:
        st.markdown(_tile("⚠️ Warning", f"{g:.1f}%",
                          f"Yellow {y:.1f}% · Due {due_soon} วัน",
                          "#F57C00"), unsafe_allow_html=True)
    with k4:
        st.markdown(_tile("💵 ประกันผลงาน", f"{gd:.1f}%",
                          "หักจากงวด", "#6A1B9A"), unsafe_allow_html=True)
    with k5:
        n_ms_color = "#2E7D32"
        total_pct = sum(m.get("percent", 0) for m in cfg.get("milestones", []))
        if abs(total_pct - 100) > 0.01:
            n_ms_color = "#D32F2F"
        st.markdown(_tile("📅 Milestones", f"{n_ms} งวด",
                          f"Total {total_pct:.0f}% · {n_users} roles",
                          n_ms_color), unsafe_allow_html=True)

    if n_errors > 0:
        st.markdown(
            f'<div style="background:#FFEBEE;border-left:4px solid #D32F2F;'
            f'padding:10px 14px;border-radius:8px;font-size:13px;'
            f'margin-top:10px;color:#B71C1C;">'
            f'🚨 <b>พบ {n_errors} ปัญหาใน settings.json</b> — '
            + " · ".join(validation_errors)
            + '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="background:#E8F5E9;border-left:4px solid #2E7D32;'
            f'padding:8px 14px;border-radius:8px;font-size:12.5px;'
            f'margin-top:10px;color:#2E7D32;">'
            f'✅ <b>Configuration ถูกต้องทุกส่วน</b>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # TABS
    t1, t2, t3, t4, t5, t6, t7 = st.tabs([
        "📋 Project",
        "⚠️ Warning",
        "💵 Payment",
        "📅 Milestones",
        "👥 Roles",
        "💾 Backup / Export",
        "🔐 Users",
    ])

    # ============================================================
    # TAB 1 — PROJECT DEFAULTS
    # ============================================================
    with t1:
        st.markdown("### 📋 Project Defaults")
        st.caption("ค่าตั้งต้นของโครงการ — มีผลต่อ bootstrap และการคำนวณงวดงาน")

        pd_cfg = cfg.get("project_defaults", {})

        with st.form("project_defaults_form"):
            c1, c2 = st.columns(2)
            new_dur = c1.number_input(
                "Duration (days)",
                min_value=1, max_value=1000,
                value=int(pd_cfg.get("duration_days", 360)),
                step=10,
                disabled=not is_admin,
                key="cfg_dur",
            )
            new_val = c2.number_input(
                "Contract Value (THB)",
                min_value=0.0, max_value=1e12,
                value=float(pd_cfg.get("contract_value", 0)),
                step=100000.0,
                disabled=not is_admin,
                key="cfg_val",
            )

            if new_val != pd_cfg.get("contract_value", 0):
                st.warning(
                    f"⚠️ **ผลกระทบ:** การเปลี่ยนมูลค่าสัญญาจะกระทบ "
                    f"**payment_amount** ของทุก milestone"
                )

            cBtn1, cBtn2 = st.columns([1, 1])
            save_1 = cBtn1.form_submit_button(
                "💾 บันทึก", type="primary", use_container_width=True,
                disabled=not is_admin,
            )
            reset_1 = cBtn2.form_submit_button(
                "↩️ ยกเลิก", use_container_width=True,
                disabled=not is_admin,
            )

        if reset_1:
            st.rerun()

        if save_1:
            new_cfg = json.loads(json.dumps(cfg))
            new_cfg["project_defaults"] = {
                "duration_days":   int(new_dur),
                "contract_value":  float(new_val),
            }
            ok, msg = _save_with_audit(
                new_cfg, "แก้ไข Project Defaults", st.session_state.user
            )
            if ok:
                st.session_state["settings_last_saved"] = {"msg": msg, "n": 2}
                st.rerun()
            else:
                st.error(f"❌ {msg}")

    # ============================================================
    # TAB 2 — WARNING THRESHOLDS
    # ============================================================
    with t2:
        st.markdown("### ⚠️ Warning Thresholds")
        st.caption("เกณฑ์เตือนความล่าช้า — variance = actual − planned (ค่าติดลบ = ล่าช้า)")

        wt = cfg.get("warning_thresholds", {})

        st.markdown("#### 📊 Chart Preview")
        fig = go.Figure()
        fig.add_shape(
            type="rect",
            x0=-100, x1=wt.get("green_variance_pct", -3),
            y0=0, y1=1,
            fillcolor="rgba(46,125,50,0.15)", line=dict(width=0),
        )
        fig.add_shape(
            type="rect",
            x0=wt.get("green_variance_pct", -3),
            x1=wt.get("yellow_variance_pct", -10),
            y0=0, y1=1,
            fillcolor="rgba(245,124,0,0.15)", line=dict(width=0),
        )
        fig.add_shape(
            type="rect",
            x0=wt.get("yellow_variance_pct", -10),
            x1=-100,
            y0=0, y1=1,
            fillcolor="rgba(211,47,47,0.15)", line=dict(width=0),
        )
        fig.add_trace(go.Scatter(
            x=[0], y=[0.5], mode="markers",
            marker=dict(size=14, color="#0B5ED7"),
            name="On-track",
        ))
        fig.update_layout(
            height=180,
            xaxis=dict(title="Variance (%)", range=[-50, 5]),
            yaxis=dict(showticklabels=False, range=[0, 1]),
            showlegend=False,
            plot_bgcolor="#FAFBFC",
            margin=dict(l=10, r=10, t=10, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"🟢 variance ≥ {wt.get('green_variance_pct', 0):.1f}% · "
            f"🟠 ≥ {wt.get('yellow_variance_pct', 0):.1f}% · "
            f"🔴 < {wt.get('yellow_variance_pct', 0):.1f}%"
        )

        with st.form("warning_form"):
            c1, c2, c3, c4 = st.columns(4)
            new_g = c1.number_input(
                "Green (%)", min_value=-100.0, max_value=100.0,
                value=float(wt.get("green_variance_pct", -3.0)),
                step=0.5, disabled=not is_admin, key="cfg_g",
            )
            new_y = c2.number_input(
                "Yellow (%)", min_value=-100.0, max_value=100.0,
                value=float(wt.get("yellow_variance_pct", -10.0)),
                step=0.5, disabled=not is_admin, key="cfg_y",
            )
            new_r = c3.number_input(
                "Red (%)", min_value=-100.0, max_value=100.0,
                value=float(wt.get("red_variance_pct", -10.01)),
                step=0.01, disabled=not is_admin, key="cfg_r",
            )
            new_due = c4.number_input(
                "Due Soon (days)", min_value=0, max_value=365,
                value=int(wt.get("due_soon_days", 7)),
                step=1, disabled=not is_admin, key="cfg_due",
            )

            if not (new_g > new_y > new_r):
                st.error("⚠️ ต้องเรียง: Green > Yellow > Red")

            cBtn1, cBtn2 = st.columns([1, 1])
            save_2 = cBtn1.form_submit_button(
                "💾 บันทึก", type="primary", use_container_width=True,
                disabled=not is_admin,
            )
            reset_2 = cBtn2.form_submit_button(
                "↩️ ยกเลิก", use_container_width=True,
                disabled=not is_admin,
            )

        if reset_2:
            st.rerun()

        if save_2:
            new_cfg = json.loads(json.dumps(cfg))
            new_cfg["warning_thresholds"] = {
                "green_variance_pct":  float(new_g),
                "yellow_variance_pct": float(new_y),
                "red_variance_pct":    float(new_r),
                "due_soon_days":       int(new_due),
            }
            ok, msg = _save_with_audit(
                new_cfg, "แก้ไข Warning Thresholds", st.session_state.user
            )
            if ok:
                st.session_state["settings_last_saved"] = {"msg": msg, "n": 4}
                st.rerun()
            else:
                st.error(f"❌ {msg}")

    # ============================================================
    # TAB 3 — PAYMENT
    # ============================================================
    with t3:
        st.markdown("### 💵 Payment Settings")
        st.caption("การหักประกันผลงาน (BR-12: หักจากยอดจ่ายงวดนี้)")

        p_cfg = cfg.get("payment", {})

        with st.form("payment_form"):
            new_gd = st.number_input(
                "Guarantee Deduction (%)",
                min_value=0.0, max_value=100.0,
                value=float(p_cfg.get("guarantee_deduction_pct", 10.0)),
                step=0.5, disabled=not is_admin, key="cfg_gd",
            )

            sample = 1000000.0
            ded = sample * new_gd / 100.0
            net = sample - ded
            st.info(
                f"💡 ตัวอย่าง: ยอดจ่าย 1,000,000 ฿  \n"
                f"หักประกัน {new_gd:.1f}% = {ded:,.2f} ฿  \n"
                f"ยอดสุทธิ = **{net:,.2f} ฿**"
            )

            cBtn1, cBtn2 = st.columns([1, 1])
            save_3 = cBtn1.form_submit_button(
                "💾 บันทึก", type="primary", use_container_width=True,
                disabled=not is_admin,
            )
            reset_3 = cBtn2.form_submit_button(
                "↩️ ยกเลิก", use_container_width=True,
                disabled=not is_admin,
            )

        if reset_3:
            st.rerun()

        if save_3:
            new_cfg = json.loads(json.dumps(cfg))
            new_cfg["payment"] = {"guarantee_deduction_pct": float(new_gd)}
            ok, msg = _save_with_audit(
                new_cfg, "แก้ไข Payment Settings", st.session_state.user
            )
            if ok:
                st.session_state["settings_last_saved"] = {"msg": msg, "n": 1}
                st.rerun()
            else:
                st.error(f"❌ {msg}")

    # ============================================================
    # TAB 4 — MILESTONES
    # ============================================================
    with t4:
        st.markdown("### 📅 Milestones Template")
        st.caption(
            "Template นี้ใช้ตอน bootstrap — แก้จริงที่หน้า ⚙️ Project / Milestone"
        )

        ms_list = cfg.get("milestones", [])

        if ms_list:
            ms_df = pd.DataFrame(ms_list)
            total_pct = ms_df["percent"].sum()
            total_days = ms_df["due_day"].max() if not ms_df.empty else 0

            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(_tile("📊 จำนวนงวด", f"{len(ms_list)}",
                                  "milestones", "#0B5ED7"), unsafe_allow_html=True)
            with c2:
                pct_color = "#2E7D32" if abs(total_pct - 100) < 0.01 else "#D32F2F"
                st.markdown(_tile("💯 Payment รวม", f"{total_pct:.1f}%",
                                  "ต้องเท่ากับ 100%", pct_color), unsafe_allow_html=True)
            with c3:
                st.markdown(_tile("📅 Due Day สูงสุด", f"{total_days}",
                                  "วัน", "#6A1B9A"), unsafe_allow_html=True)

            st.markdown("---")
            st.dataframe(ms_df, use_container_width=True, hide_index=True)

            fig_ms = go.Figure()
            fig_ms.add_trace(go.Bar(
                x=[f"M{m['no']}" for m in ms_list],
                y=[m["due_day"] for m in ms_list],
                name="Due Day",
                marker_color="#0B5ED7",
                yaxis="y",
                text=[f"D{m['due_day']}" for m in ms_list],
                textposition="outside",
            ))
            fig_ms.add_trace(go.Scatter(
                x=[f"M{m['no']}" for m in ms_list],
                y=[m["percent"] for m in ms_list],
                name="Payment %",
                mode="lines+markers+text",
                line=dict(color="#F57C00", width=3),
                marker=dict(size=10),
                yaxis="y2",
                text=[f"{m['percent']}%" for m in ms_list],
                textposition="top center",
            ))
            fig_ms.update_layout(
                height=340, plot_bgcolor="#FAFBFC",
                yaxis=dict(title="Due Day", side="left"),
                yaxis2=dict(
                    title="Payment %", overlaying="y", side="right",
                    range=[0, max([m["percent"] for m in ms_list] + [10]) * 1.5],
                ),
                legend=dict(orientation="h", y=1.1),
                margin=dict(l=10, r=10, t=30, b=40),
            )
            st.plotly_chart(fig_ms, use_container_width=True)

        st.markdown("---")
        st.markdown("#### ✏️ แก้ไข Milestones Template (JSON)")

        with st.form("milestones_form"):
            ms_json = st.text_area(
                "Milestones",
                value=json.dumps(ms_list, ensure_ascii=False, indent=2),
                height=280, disabled=not is_admin, key="cfg_ms_json",
            )

            cBtn1, cBtn2 = st.columns([1, 1])
            save_4 = cBtn1.form_submit_button(
                "💾 บันทึก", type="primary", use_container_width=True,
                disabled=not is_admin,
            )
            reset_4 = cBtn2.form_submit_button(
                "↩️ ยกเลิก", use_container_width=True,
                disabled=not is_admin,
            )

        if reset_4:
            st.rerun()

        if save_4:
            try:
                parsed = json.loads(ms_json)
                if not isinstance(parsed, list):
                    raise ValueError("ต้องเป็น JSON array")
                for m in parsed:
                    if not all(k in m for k in ["no", "name", "due_day", "percent"]):
                        raise ValueError(
                            f"Milestone {m.get('no', '?')} ขาด field"
                        )

                new_cfg = json.loads(json.dumps(cfg))
                new_cfg["milestones"] = parsed
                ok, msg = _save_with_audit(
                    new_cfg, "แก้ไข Milestones Template", st.session_state.user
                )
                if ok:
                    st.session_state["settings_last_saved"] = {
                        "msg": msg, "n": len(parsed),
                    }
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")
            except json.JSONDecodeError as e:
                st.error(f"❌ JSON ไม่ถูกต้อง: {e}")
            except ValueError as e:
                st.error(f"❌ {e}")

    # ============================================================
    # TAB 5 — USER ROLES
    # ============================================================
    with t5:
        st.markdown("### 👥 User Roles")
        st.caption("รายชื่อ role ที่ระบบรองรับ")

        roles = cfg.get("user_roles", [])

        role_descriptions = {
            "admin":      "ผู้ดูแลระบบ — แก้ Settings, ลบข้อมูลได้",
            "monitoring": "ผู้ติดตาม — เพิ่ม/แก้ข้อมูลประจำวัน",
            "reviewer":   "ผู้ตรวจ — Review deliverable",
            "committee":  "คณะกรรมการ — อนุมัติตรวจรับ",
            "supervisor": "ผู้บังคับบัญชา — ดูภาพรวม อนุมัติ",
            "readonly":   "อ่านเท่านั้น",
        }

        role_rows = []
        for r in roles:
            role_rows.append({
                "Role":        r,
                "คำอธิบาย":   role_descriptions.get(r, "-"),
                "สิทธิ์แก้ Settings": "✅" if r == "admin" else "❌",
            })
        st.dataframe(pd.DataFrame(role_rows), use_container_width=True, hide_index=True)

        with st.form("roles_form"):
            new_roles = st.multiselect(
                "Roles ที่ระบบรองรับ",
                options=list(role_descriptions.keys()) + roles,
                default=roles,
                disabled=not is_admin,
                key="cfg_roles",
            )

            cBtn1, cBtn2 = st.columns([1, 1])
            save_5 = cBtn1.form_submit_button(
                "💾 บันทึก", type="primary", use_container_width=True,
                disabled=not is_admin,
            )
            reset_5 = cBtn2.form_submit_button(
                "↩️ ยกเลิก", use_container_width=True,
                disabled=not is_admin,
            )

        if reset_5:
            st.rerun()

        if save_5:
            seen = set()
            uniq = []
            for r in new_roles:
                if r not in seen:
                    seen.add(r)
                    uniq.append(r)

            new_cfg = json.loads(json.dumps(cfg))
            new_cfg["user_roles"] = uniq
            ok, msg = _save_with_audit(
                new_cfg, "แก้ไข User Roles", st.session_state.user
            )
            if ok:
                st.session_state["settings_last_saved"] = {
                    "msg": msg, "n": len(uniq),
                }
                st.rerun()
            else:
                st.error(f"❌ {msg}")

    # ============================================================
    # TAB 6 — BACKUP / EXPORT
    # ============================================================
    with t6:
        st.markdown("### 💾 Backup / Restore / Export")

        meta = _file_meta(CFG)
        if meta:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(_tile("📄 ไฟล์ปัจจุบัน",
                                  f"{_fmt_size(meta['size'])}",
                                  "settings.json", "#0B5ED7"),
                            unsafe_allow_html=True)
            with c2:
                st.markdown(_tile("🕒 แก้ไขล่าสุด",
                                  meta["mtime"].split()[1],
                                  meta["mtime"].split()[0], "#2E7D32"),
                            unsafe_allow_html=True)
            with c3:
                n_backups = len(_list_backups())
                st.markdown(_tile("💾 จำนวน Backup", f"{n_backups}",
                                  "สำรองอัตโนมัติ", "#6A1B9A"),
                            unsafe_allow_html=True)

        st.markdown("---")

        st.markdown("#### 📥 Export ปัจจุบัน")
        cfg_text = json.dumps(cfg, ensure_ascii=False, indent=2)
        st.download_button(
            "⬇️ ดาวน์โหลด settings.json",
            data=cfg_text.encode("utf-8"),
            file_name=f"settings_{today_str()}.json",
            mime="application/json",
            use_container_width=True,
            key="cfg_dl_current",
        )

        st.markdown("---")

        st.markdown("#### 📤 Import จากไฟล์")
        if not is_admin:
            st.info("🔒 เฉพาะ admin")
        else:
            uploaded = st.file_uploader(
                "เลือกไฟล์ settings.json",
                type=["json"],
                key="cfg_upload",
            )
            if uploaded is not None:
                try:
                    content = uploaded.read().decode("utf-8")
                    parsed = json.loads(content)
                    errors = _validate_settings(parsed)
                    if errors:
                        st.error("❌ ไฟล์ไม่ผ่าน validation:")
                        for e in errors:
                            st.markdown(f"- {e}")
                    else:
                        st.success(f"✅ ไฟล์ถูกต้อง — มี {len(parsed)} keys")
                        with st.expander("ดูตัวอย่าง", expanded=False):
                            st.json(parsed)

                        if st.button("📤 Import (ทับ settings ปัจจุบัน)",
                                     type="primary", key="cfg_do_import"):
                            _backup_config(cfg, "before_import")
                            save_settings(parsed)
                            append_audit(
                                st.session_state.user, "UPDATE", "SETTINGS",
                                "settings.json",
                                old_value="from current",
                                new_value=f"imported {len(parsed)} keys",
                                reason="Import settings.json",
                            )
                            st.session_state["settings_last_saved"] = {
                                "msg": "Import สำเร็จ", "n": len(parsed),
                            }
                            st.rerun()
                except json.JSONDecodeError as e:
                    st.error(f"❌ JSON ไม่ถูกต้อง: {e}")
                except Exception as e:
                    st.error(f"❌ {type(e).__name__}: {e}")

        # ═══════════════════════════════════════════════════════════
        # ★ WEIGHT REBALANCE
        # ═══════════════════════════════════════════════════════════
        st.markdown("---")
        st.markdown("#### ⚖️ Rebalance Deliverable Weights")
        st.caption(
            "ปรับ weights ของ deliverables ให้ผลรวม = 100.00% พอดี "
            "โดยรักษาสัดส่วนเดิม (scale factor เดียวกัน) — "
            "ไม่กระทบ history"
        )

        if not is_admin:
            st.info("🔒 เฉพาะ admin เท่านั้น")
        else:
            summary = _load_deliverable_weights()

            if summary is None:
                st.warning(
                    "⚠️ ไม่พบไฟล์ `deliverable_master.csv` หรือไม่มีข้อมูล — "
                    "กรุณา Reseed Master Data ก่อน"
                )
            else:
                total_w = summary["total"]
                n_items = summary["n_items"]
                by_ms = summary["by_milestone"]
                is_valid = abs(total_w - TARGET_WEIGHT_TOTAL) < WEIGHT_TOLERANCE

                # ---- KPI tiles ----
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("📦 จำนวน Deliverables", f"{n_items}")
                with c2:
                    delta = total_w - TARGET_WEIGHT_TOTAL
                    st.metric(
                        "⚖️ Weight รวม",
                        f"{total_w:.2f}%",
                        delta=f"{delta:+.2f}%" if not is_valid else "✅ OK",
                        delta_color="inverse" if not is_valid else "normal",
                    )
                with c3:
                    status = "✅ ครบ 100%" if is_valid else "⚠️ ไม่ครบ"
                    st.metric("📌 สถานะ", status)

                # ---- Breakdown ----
                with st.expander("📊 ดู Breakdown ต่อ Milestone", expanded=False):
                    show = by_ms.copy()
                    show.columns = ["Milestone", "Weight (%)", "จำนวน"]
                    show["Weight (%)"] = show["Weight (%)"].apply(
                        lambda x: f"{float(x):.2f}%"
                    )
                    st.dataframe(show, use_container_width=True, hide_index=True)

                # ---- Action ----
                st.markdown("")
                if is_valid:
                    st.success(
                        f"✅ Weight รวม = {total_w:.2f}% — "
                        f"ถูกต้องแล้ว ไม่ต้อง Rebalance"
                    )
                else:
                    st.warning(
                        f"⚠️ Weight รวม = {total_w:.2f}% — "
                        f"ห่างจากเป้าหมาย {abs(delta):.2f}%"
                    )

                    confirm_reb = st.checkbox(
                        "☑️ ยืนยัน Rebalance weights (จะ backup CSV ก่อนแก้)",
                        value=False,
                        key="cfg_rebalance_confirm",
                    )

                    if st.button(
                        "⚖️ Rebalance เป็น 100%",
                        type="primary",
                        use_container_width=True,
                        disabled=not confirm_reb,
                        key="cfg_rebalance_btn",
                    ):
                        try:
                            from bootstrap import rebalance_existing_weights
                            res = rebalance_existing_weights(
                                target_total=TARGET_WEIGHT_TOTAL
                            )

                            if res["ok"]:
                                append_audit(
                                    st.session_state.user,
                                    "UPDATE", "SETTINGS", "deliverable_weights",
                                    old_value=f"{res['old_total']:.2f}%",
                                    new_value=f"{res['new_total']:.2f}%",
                                    reason=(
                                        f"Rebalance {res['changed']} deliverables · "
                                        f"backup={Path(res['backup']).name if res.get('backup') else '-'}"
                                    ),
                                )
                                st.success(res["message"])
                                if res.get("backup"):
                                    st.info(
                                        f"💾 Backup: `{res['backup']}`"
                                    )
                                st.info(
                                    "💡 กรุณา refresh หน้าเว็บ (F5) "
                                    "เพื่อโหลดข้อมูลใหม่"
                                )
                                st.rerun()
                            else:
                                st.error(res["message"])
                        except Exception as e:
                            st.error(f"❌ {type(e).__name__}: {e}")

        # ═══════════════════════════════════════════════════════════
        # ★ FORCE RESEED MASTER DATA
        # ═══════════════════════════════════════════════════════════
        st.markdown("---")
        st.markdown("#### 🔄 Force Reseed Master Data")
        st.caption(
            "ลบและสร้างใหม่ข้อมูล master ทั้งหมด "
            "(project / milestone / deliverable / personnel) — "
            "ใช้เมื่อ timeline หรือรายการ deliverable มีการอัปเดต"
        )

        if not is_admin:
            st.info("🔒 เฉพาะ admin เท่านั้น")
        else:
            st.warning(
                "⚠️ **คำเตือน:** การ Reseed จะ **เขียนทับ** ข้อมูล master "
                "ทั้งหมดด้วยค่าเริ่มต้นจาก bootstrap.py\n\n"
                "• ประวัติ History (progress, meeting, acceptance ฯลฯ) "
                "**ไม่หาย**\n"
                "• แต่ **การแก้ไข** project/milestone/deliverable ในหน้า UI "
                "จะหายไป\n"
                "• ระบบจะ backup ไฟล์เดิมไว้ที่ `data/backup/` อัตโนมัติ\n"
                "• Deliverables weights จะถูก **normalize ให้รวม = 100.00%** "
                "อัตโนมัติ"
            )

            # แสดงข้อมูลที่จะถูก Reseed
            st.markdown("**📋 ข้อมูลที่จะถูก Reseed:**")
            col_r1, col_r2, col_r3, col_r4 = st.columns(4)
            for col, fname in zip(
                [col_r1, col_r2, col_r3, col_r4],
                ["project_master.csv", "milestone_master.csv",
                 "deliverable_master.csv", "personnel_master.csv"]
            ):
                fp = MASTER_DIR / fname
                if fp.exists():
                    try:
                        n = len(pd.read_csv(fp, encoding="utf-8-sig"))
                        col.metric(fname.replace(".csv", ""), f"{n} แถว")
                    except Exception:
                        col.metric(fname.replace(".csv", ""), "อ่านไม่ได้")
                else:
                    col.metric(fname.replace(".csv", ""), "ไม่มีไฟล์")

            # Checkbox confirm
            confirm_reseed = st.checkbox(
                "☑️ ข้าพเจ้ายืนยันว่าต้องการ Reseed master data",
                value=False,
                key="cfg_reseed_confirm",
            )

            col_btn1, col_btn2 = st.columns([1, 1])
            with col_btn1:
                if st.button(
                    "🔄 Force Reseed Master",
                    type="primary",
                    use_container_width=True,
                    disabled=not confirm_reseed,
                    key="cfg_reseed_btn",
                ):
                    try:
                        from bootstrap import force_reseed_master
                        res = force_reseed_master(backup=True)

                        if res["ok"]:
                            append_audit(
                                st.session_state.user,
                                "UPDATE", "SETTINGS", "master_data",
                                old_value="existing master CSV",
                                new_value="reseeded from bootstrap.py",
                                reason=(
                                    f"Force reseed — "
                                    f"backup {len(res['backed_up'])} files"
                                ),
                            )
                            st.success(res["message"])
                            if res["backed_up"]:
                                with st.expander("💾 ไฟล์ที่ backup ไว้"):
                                    for b in res["backed_up"]:
                                        st.markdown(f"- `data/backup/{b}`")
                            st.info(
                                "💡 กรุณา refresh หน้าเว็บ (F5) "
                                "เพื่อโหลดข้อมูลใหม่"
                            )
                        else:
                            st.error(res["message"])
                    except Exception as e:
                        st.error(f"❌ {type(e).__name__}: {e}")

            with col_btn2:
                if st.button(
                    "📄 ดูตัวอย่างข้อมูลใหม่",
                    use_container_width=True,
                    key="cfg_preview_reseed",
                ):
                    try:
                        from bootstrap import (
                            DELIVERABLES_FULL,
                            normalize_deliverable_weights,
                        )
                        normalized = normalize_deliverable_weights(
                            DELIVERABLES_FULL, target_total=100.0
                        )
                        n = len(normalized)
                        total_w = sum(d["weight"] for d in normalized)

                        st.info(
                            f"📊 bootstrap.py มี **{n}** deliverables "
                            f"พร้อม seed — weight รวม **{total_w:.2f}%**"
                        )
                        with st.expander(f"ดูรายการทั้งหมด ({n})"):
                            preview = pd.DataFrame([
                                {
                                    "ID": d["id"],
                                    "Milestone": d["ms"],
                                    "ชื่อ": d["name"][:70],
                                    "Weight": d["weight"],
                                    "Start": d["start"],
                                    "Finish": d["finish"],
                                }
                                for d in normalized
                            ])
                            st.dataframe(
                                preview,
                                use_container_width=True,
                                hide_index=True,
                            )
                    except Exception as e:
                        st.error(f"❌ {e}")

        # ═══════════════════════════════════════════════════════════
        # RESET TO DEFAULTS
        # ═══════════════════════════════════════════════════════════
        st.markdown("---")
        st.markdown("#### ⚠️ Reset เป็นค่าเริ่มต้น")
        if not is_admin:
            st.info("🔒 เฉพาะ admin")
        else:
            st.warning(
                "🚨 Reset จะ **ทับ settings.json ปัจจุบัน** — "
                "ระบบจะ backup ก่อนดำเนินการ"
            )
            confirm_reset = st.checkbox(
                "ยืนยัน reset", value=False, key="cfg_reset_confirm",
            )
            if st.button(
                "🔄 Reset to Defaults",
                disabled=not confirm_reset,
                key="cfg_reset_btn",
            ):
                _backup_config(cfg, "before_reset")
                save_settings(json.loads(json.dumps(DEFAULT_SETTINGS)))
                append_audit(
                    st.session_state.user, "UPDATE", "SETTINGS",
                    "settings.json",
                    old_value="custom",
                    new_value="defaults",
                    reason="Reset to defaults",
                )
                st.session_state["settings_last_saved"] = {
                    "msg": "Reset เป็นค่าเริ่มต้นสำเร็จ", "n": 5,
                }
                st.rerun()

        st.markdown("---")

        st.markdown("#### 💾 Backup History")
        backups = _list_backups()
        if not backups:
            st.info("ยังไม่มี backup")
        else:
            backup_rows = []
            for i, b in enumerate(backups[:50], 1):
                meta_b = _file_meta(b)
                backup_rows.append({
                    "ลำดับ": i,
                    "ชื่อไฟล์": b.name,
                    "ขนาด": _fmt_size(meta_b["size"]),
                    "วันที่": meta_b["mtime"],
                })
            st.dataframe(
                pd.DataFrame(backup_rows),
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("**↩️ Restore จาก Backup**")
            if not is_admin:
                st.info("🔒 เฉพาะ admin")
            else:
                backup_names = [b.name for b in backups]
                sel_backup = st.selectbox(
                    "เลือก Backup", backup_names, key="cfg_restore_sel",
                )
                if st.button("↩️ Restore", key="cfg_restore_btn"):
                    _backup_config(cfg, "before_restore")
                    src = BACKUP_DIR / sel_backup
                    shutil.copy2(src, CFG)
                    append_audit(
                        st.session_state.user, "RESTORE", "SETTINGS",
                        "settings.json",
                        old_value="current",
                        new_value=f"from {sel_backup}",
                        reason="Restore settings from backup",
                    )
                    st.session_state["settings_last_saved"] = {
                        "msg": f"Restore จาก {sel_backup} สำเร็จ", "n": 1,
                    }
                    st.rerun()

    # ============================================================
    # TAB 7 — USER MANAGEMENT
    # ============================================================
    with t7:
        st.markdown("### 🔐 User Management")
        st.caption("จัดการผู้ใช้ในระบบ — เพิ่ม / แก้ role / reset รหัสผ่าน / ปิดการใช้งาน")

        if not is_admin:
            st.info("🔒 เฉพาะ admin เท่านั้น")
        else:
            from core.auth import (
                list_users, create_user, change_password,
                reset_password, toggle_user_active, update_user_role,
                force_recreate_users,
            )

            users = list_users()

            if users:
                u_df = pd.DataFrame([
                    {
                        "Username": u.get("username"),
                        "ชื่อ":     u.get("full_name"),
                        "Role":     u.get("role"),
                        "Email":    u.get("email", ""),
                        "สถานะ":    "✅ ใช้งาน" if u.get("active") else "🚫 ปิด",
                        "สร้างเมื่อ": u.get("created_at", ""),
                    }
                    for u in users
                ])
                st.dataframe(u_df, use_container_width=True, hide_index=True)

            st.markdown("---")

            # --- Add user ---
            with st.expander("➕ เพิ่มผู้ใช้ใหม่", expanded=False):
                with st.form("add_user_form"):
                    c1, c2 = st.columns(2)
                    new_u = c1.text_input("Username", key="nu_user")
                    new_p = c2.text_input("Password", type="password", key="nu_pwd")
                    c3, c4 = st.columns(2)
                    new_n = c3.text_input("ชื่อ-สกุล", key="nu_name")
                    new_e = c4.text_input("Email", key="nu_email")

                    all_roles = cfg.get("user_roles", [])
                    new_r = st.selectbox("Role", all_roles or ["readonly"], key="nu_role")

                    if st.form_submit_button("💾 สร้างผู้ใช้", type="primary"):
                        ok, msg = create_user(new_u, new_p, new_n, new_r, new_e)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

            # --- Manage users ---
            with st.expander("🔧 จัดการผู้ใช้", expanded=False):
                usernames = [u.get("username") for u in users if u.get("username")]
                if usernames:
                    sel_u = st.selectbox("เลือกผู้ใช้", usernames, key="mg_user")

                    c1, c2 = st.columns(2)
                    with c1:
                        all_roles = cfg.get("user_roles", [])
                        cur_role = next(
                            (u.get("role") for u in users
                             if u.get("username") == sel_u),
                            "readonly",
                        )
                        new_role = st.selectbox(
                            "เปลี่ยน Role",
                            all_roles,
                            index=all_roles.index(cur_role)
                                if cur_role in all_roles else 0,
                            key="mg_role",
                        )
                        if st.button("💾 อัปเดต Role", key="mg_role_btn"):
                            ok, msg = update_user_role(sel_u, new_role)
                            st.success(msg) if ok else st.error(msg)
                            st.rerun()

                    with c2:
                        if st.button("🔄 เปิด/ปิดการใช้งาน", key="mg_toggle_btn"):
                            ok, msg = toggle_user_active(sel_u)
                            st.success(msg) if ok else st.error(msg)
                            st.rerun()

                    st.markdown("---")
                    st.markdown("**🔑 Reset รหัสผ่าน**")
                    with st.form("reset_pwd_form"):
                        new_p2 = st.text_input(
                            f"รหัสผ่านใหม่สำหรับ `{sel_u}`",
                            type="password", key="mg_newpwd",
                        )
                        if st.form_submit_button("🔄 Reset Password"):
                            ok, msg = reset_password(sel_u, new_p2)
                            st.success(msg) if ok else st.error(msg)
                            st.rerun()

            st.markdown("---")

            # --- Force recreate (emergency) ---
            with st.expander("🚨 Emergency — Force Recreate Users", expanded=False):
                st.warning(
                    "⚠️ **ใช้เฉพาะเมื่อ users.json เสียหาย** — "
                    "จะ backup ของเดิม แล้วสร้าง users ทั้งหมดใหม่ "
                    "ด้วยรหัสผ่านเริ่มต้น"
                )
                if st.button("🚨 Force Recreate users.json", key="force_recreate"):
                    ok, msg = force_recreate_users()
                    if ok:
                        st.success(msg)
                        st.info(
                            "ℹ️ กรุณาออกจากระบบแล้วเข้าใหม่ด้วย "
                            "`admin` / `admin123`"
                        )
                    else:
                        st.error(msg)

    # ============================================================
    # CURRENT SETTINGS VIEWER
    # ============================================================
    st.markdown("---")
    with st.expander("📄 ดู settings.json ปัจจุบัน (read-only)", expanded=False):
        st.json(cfg)

    # ============================================================
    # AUDIT LOG ของ SETTINGS
    # ============================================================
    with st.expander("📋 ประวัติการแก้ Settings (จาก Audit Log)", expanded=False):
        try:
            audit_df = read_audit()
            if audit_df.empty:
                st.info("ยังไม่มีประวัติ")
            else:
                settings_audit = audit_df[
                    audit_df["module"] == "SETTINGS"
                ].copy()
                if settings_audit.empty:
                    st.info("ยังไม่มีการแก้ Settings")
                else:
                    settings_audit = settings_audit.sort_values(
                        "timestamp", ascending=False
                    )
                    show_cols = [c for c in [
                        "timestamp", "user", "action", "record_id",
                        "reason", "old_value", "new_value",
                    ] if c in settings_audit.columns]
                    st.dataframe(
                        settings_audit[show_cols].head(50),
                        use_container_width=True,
                        hide_index=True,
                    )
        except Exception as e:
            st.warning(f"⚠️ อ่าน Audit Log ไม่สำเร็จ: {e}")