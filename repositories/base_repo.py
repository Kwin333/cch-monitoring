"""
repositories/base_repo.py — รองรับทั้ง CSV (local) และ PostgreSQL (production)

★ v4 — แก้ไข:
- 🔧 Fix: เพิ่ม `id_col` parameter ใน AppendOnlyRepo/MasterRepo constructor
  (ชัดเจน ไม่ต้องเดา — ป้องกัน bug กับ deliverable_review_history)
- 🔧 Fix: `_get_id_col()` รองรับ `_id_col_override` attribute
- 🔧 Fix: `_hard_delete_db()` เพิ่ม logging + verify rowcount
- 🔧 Fix: ห้าม silent fallback — DB mode แล้ว error → raise
- ✨ เพิ่ม `_safe_int()` helper

★ v3:
- ใช้ _DeleteMixin ร่วมกันระหว่าง AppendOnlyRepo และ MasterRepo
- รองรับ DB mode (Supabase PostgreSQL) ผ่าน core.db
- กรอง field ที่ไม่ตรง schema ออกก่อน save

★ v2:
- เพิ่ม `_clean_row()` — ป้องกัน column ไม่มีใน DB
- Force reseed / rebalance

★ v1:
- Initial: CSV-only repo
"""
import os
import csv
import shutil
from pathlib import Path
from datetime import datetime


# ═══════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════
DATA_DIR = Path(__file__).parent.parent / "data"


# ═══════════════════════════════════════════════════════════
# BACKEND SELECTION
# ═══════════════════════════════════════════════════════════
_USE_DB = os.environ.get("USE_DATABASE", "false").lower() == "true"

try:
    import streamlit as st
    if st.secrets.get("DATABASE_URL"):
        _USE_DB = True
except Exception:
    pass


def is_db_mode() -> bool:
    """สำหรับ debug — บอกว่าใช้ DB หรือ CSV"""
    return _USE_DB


# ═══════════════════════════════════════════════════════════
# BACKUP HELPER (CSV mode)
# ═══════════════════════════════════════════════════════════
def _backup(path: Path) -> Path | None:
    """สำรองไฟล์ก่อนแก้ — ใช้เฉพาะโหมด CSV"""
    if _USE_DB or not path.exists():
        return None
    bdir = DATA_DIR / "backup"
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    dest = bdir / f"{path.stem}_{stamp}{path.suffix}"
    try:
        shutil.copy2(path, dest)
        return dest
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def _safe_int(v, default=0) -> int:
    """★ v4: แปลงเป็น int แบบปลอดภัย"""
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _clean_row(row: dict, fields: list) -> dict:
    """
    ★ v3 — กรอง row ให้เหลือเฉพาะ field ที่อยู่ใน schema
    - เก็บเฉพาะ key ที่อยู่ใน fields
    - เติม field ที่ขาดด้วย "" (empty string)
    - แปลง NaN → ""
    """
    clean = {}
    for f in fields:
        v = row.get(f, "")
        try:
            import pandas as pd
            if pd.isna(v):
                v = ""
        except Exception:
            pass
        clean[f] = v
    return clean


# ═══════════════════════════════════════════════════════════
# COMMON MIXIN — shared methods
# ═══════════════════════════════════════════════════════════
class _DeleteMixin:
    """Shared methods — ทั้ง AppendOnlyRepo และ MasterRepo ใช้ร่วมกัน"""

    def _get_id_col(self) -> str | None:
        """override ใน subclass"""
        raise NotImplementedError

    # --------------------------------------------------------
    # READ VARIANTS
    # --------------------------------------------------------
    def read_active(self):
        return self.read(include_voided=False)

    def read_voided(self):
        import pandas as pd
        df = self.read(include_voided=True)
        id_col = self._get_id_col()
        if not id_col or id_col not in df.columns:
            return pd.DataFrame(columns=self.fields)
        try:
            from core.void_registry import get_voided_ids
            voided = get_voided_ids()
            if not voided:
                return pd.DataFrame(columns=self.fields)
            return df[df[id_col].astype(str).isin(voided)].reset_index(drop=True)
        except Exception:
            return pd.DataFrame(columns=self.fields)

    def read_all(self):
        return self.read(include_voided=True)

    def count_voided(self) -> int:
        try:
            return len(self.read_voided())
        except Exception:
            return 0

    def count_all(self) -> int:
        try:
            return len(self.read_all())
        except Exception:
            return 0

    def count_active(self) -> int:
        try:
            return len(self.read_active())
        except Exception:
            return 0

    # --------------------------------------------------------
    # SOFT DELETE
    # --------------------------------------------------------
    def soft_delete(self, record_id: str, reason: str, user: str):
        """Soft delete — ใช้ได้ทั้ง CSV และ DB"""
        from core.void_registry import add_void
        from core.audit import append_audit

        df = self.read(include_voided=True)
        id_col = self._get_id_col()
        if id_col is None or id_col not in df.columns:
            raise ValueError(f"ไม่พบ ID column — fields: {self.fields}")

        if str(record_id) not in df[id_col].astype(str).values:
            raise ValueError(f"ไม่พบ record_id: {record_id}")

        rows = df[df[id_col].astype(str) == str(record_id)]
        old_row = rows.iloc[-1].to_dict() if len(rows) > 0 else {}

        record_type = (
            self.filename
            .replace("_history.csv", "")
            .replace("_master.csv", "")
        )

        add_void(record_type, record_id, reason, user, mode="soft")
        append_audit(
            user, "SOFT_DELETE", self.filename, record_id,
            old_value=str(old_row)[:500],
            new_value="voided",
            reason=reason,
        )

    # --------------------------------------------------------
    # RESTORE
    # --------------------------------------------------------
    def restore(self, record_id: str, user: str):
        from core.void_registry import remove_void
        from core.audit import append_audit
        ok = remove_void(record_id)
        if ok:
            append_audit(
                user, "RESTORE", self.filename, record_id,
                old_value="voided", new_value="active",
                reason="ยกเลิก Void",
            )
        return ok

    # --------------------------------------------------------
    # HARD DELETE — รองรับทั้ง CSV และ DB
    # --------------------------------------------------------
    def hard_delete(
        self,
        record_id: str,
        reason: str,
        user: str,
        create_backup: bool = True,
    ) -> dict:
        """
        ลบถาวร — รองรับทั้ง CSV และ DB
        ★ v4: ใช้ id_col ที่ชัดเจน — ถ้าไม่มี → raise (ไม่เงียบ)
        """
        id_col = self._get_id_col()

        if id_col is None:
            raise ValueError(
                f"❌ ไม่พบ ID column สำหรับ {self.filename} — "
                f"กรุณาระบุ `id_col` ใน constructor"
            )

        # ★ v4: log ให้เห็นชัด
        try:
            import streamlit as st
            st.caption(
                f"🔧 Repo: `{self.table_name}` · ID col: `{id_col}` · "
                f"Target: `{record_id}`"
            )
        except Exception:
            pass

        if _USE_DB:
            return self._hard_delete_db(record_id, reason, user, id_col)
        else:
            return self._hard_delete_csv(
                record_id, reason, user, id_col, create_backup
            )

    def _hard_delete_db(self, record_id, reason, user, id_col):
        """
        DB mode — ★ v4: verify rowcount + แจ้งชัดเจนถ้าลบไม่เจอ
        """
        from core.db import get_engine, delete_row, _q
        from core.void_registry import remove_void
        from core.audit import append_audit
        from sqlalchemy import text
        import traceback

        rid = str(record_id).strip()
        engine = get_engine()

        # ── 1. Count before ──
        with engine.begin() as conn:
            n_before = _safe_int(
                conn.execute(
                    text(f'SELECT COUNT(*) FROM {_q(self.table_name)}')
                ).scalar(),
                0,
            )

        # ── 2. DELETE ──
        try:
            deleted = delete_row(self.table_name, id_col, rid)
        except Exception as e:
            print(f"❌ _hard_delete_db: delete_row failed: {e}")
            print(traceback.format_exc())
            raise

        # ── 3. Count after ──
        with engine.begin() as conn:
            n_after = _safe_int(
                conn.execute(
                    text(f'SELECT COUNT(*) FROM {_q(self.table_name)}')
                ).scalar(),
                0,
            )

        delta = n_before - n_after

        # ── 4. ถ้าไม่มีการลบ → หา record ใกล้เคียง ──
        if delta == 0:
            similar = []
            try:
                with engine.begin() as conn:
                    rows = conn.execute(
                        text(f'SELECT {_q(id_col)} FROM {_q(self.table_name)} '
                             f'WHERE {_q(id_col)} ILIKE :pat LIMIT 5'),
                        {"pat": f"%{rid[-12:]}%"},
                    ).fetchall()
                    similar = [str(r[0]) for r in rows]
            except Exception as e:
                print(f"⚠️ similar lookup failed: {e}")

            # ★ โยน exception ให้ UI รู้
            raise ValueError(
                f"❌ ไม่พบ record `{rid}` ในตาราง `{self.table_name}` "
                f"(คอลัมน์ `{id_col}`)  \n"
                + (f"ใกล้เคียง: {similar}" if similar else "ไม่พบรายการใกล้เคียง")
            )

        # ── 5. remove_void ──
        try:
            remove_void(rid)
        except Exception as e:
            print(f"⚠️ remove_void failed: {e}")

        # ── 6. Audit ──
        try:
            append_audit(
                user, "HARD_DELETE", self.table_name, rid,
                old_value=f"{delta} row(s) deleted",
                new_value="PERMANENTLY_DELETED",
                reason=reason,
            )
        except Exception as e:
            print(f"⚠️ audit failed: {e}")

        return {
            "deleted": delta,
            "backup": "",
            "rows_before": n_before,
            "rows_after": n_after,
        }

    def _hard_delete_csv(self, record_id, reason, user, id_col, create_backup):
        """CSV mode"""
        import pandas as pd
        from core.void_registry import remove_void
        from core.audit import append_audit

        if not self.path.exists():
            raise FileNotFoundError(f"ไม่พบไฟล์: {self.path}")

        df = pd.read_csv(self.path, encoding="utf-8-sig")
        mask = df[id_col].astype(str) == str(record_id)
        n_match = int(mask.sum())

        if n_match == 0:
            raise ValueError(f"ไม่พบ record_id: {record_id}")

        deleted_rows = df[mask].to_dict("records")
        rows_before = len(df)

        b = _backup(self.path) if create_backup else None

        df_after = df[~mask].reset_index(drop=True)
        df_after.to_csv(self.path, index=False, encoding="utf-8-sig")

        try:
            remove_void(str(record_id))
        except Exception:
            pass

        try:
            first_row_str = str(deleted_rows[0]) if deleted_rows else ""
            append_audit(
                user, "HARD_DELETE", self.path.stem, record_id,
                old_value=f"{n_match} row(s) · {first_row_str[:400]}",
                new_value="PERMANENTLY_DELETED",
                reason=reason,
            )
        except Exception:
            pass

        return {
            "deleted": n_match,
            "backup": str(b) if b else "",
            "rows_before": rows_before,
            "rows_after": len(df_after),
        }

    # --------------------------------------------------------
    # HARD DELETE ALL
    # --------------------------------------------------------
    def hard_delete_all(self, record_ids: list, reason: str, user: str) -> dict:
        """ลบหลาย record — CSV mode เท่านั้น"""
        if _USE_DB:
            total_deleted = 0
            for rid in record_ids:
                try:
                    res = self.hard_delete(rid, reason, user)
                    total_deleted += res["deleted"]
                except Exception:
                    pass
            return {"deleted": total_deleted, "backup": "",
                    "rows_before": 0, "rows_after": 0, "not_found": []}

        import pandas as pd
        from core.void_registry import remove_void
        from core.audit import append_audit

        if not self.path.exists():
            raise FileNotFoundError(f"ไม่พบไฟล์: {self.path}")

        df = pd.read_csv(self.path, encoding="utf-8-sig")
        id_col = self._get_id_col()
        if id_col is None:
            raise ValueError("ไม่พบ ID column")

        ids_str = [str(x) for x in record_ids]
        existing = set(df[id_col].astype(str).tolist())
        not_found = [x for x in ids_str if x not in existing]

        mask = df[id_col].astype(str).isin(ids_str)
        n_match = int(mask.sum())

        if n_match == 0:
            return {"deleted": 0, "backup": "", "rows_before": len(df),
                    "rows_after": len(df), "not_found": not_found}

        b = _backup(self.path)
        df_after = df[~mask].reset_index(drop=True)
        df_after.to_csv(self.path, index=False, encoding="utf-8-sig")

        for rid in ids_str:
            try:
                remove_void(rid)
            except Exception:
                pass

        try:
            append_audit(
                user, "HARD_DELETE_BULK", self.path.stem,
                ",".join(ids_str[:10]) + ("..." if len(ids_str) > 10 else ""),
                old_value=f"{n_match} rows deleted",
                new_value="PERMANENTLY_DELETED",
                reason=reason,
            )
        except Exception:
            pass

        return {
            "deleted": n_match, "backup": str(b) if b else "",
            "rows_before": len(df), "rows_after": len(df_after),
            "not_found": not_found,
        }


# ═══════════════════════════════════════════════════════════
# APPEND-ONLY REPO (History)
# ═══════════════════════════════════════════════════════════
class AppendOnlyRepo(_DeleteMixin):
    """
    History CSV — append-only

    ★ v4: เพิ่ม `id_col` parameter (optional)
        ถ้าระบุ → ใช้เลย (ไม่ต้องเดา)
        ถ้าไม่ระบุ → เดาแบบเดิม (backward compatible)
    """

    def __init__(self, filename: str, fields: list, id_col: str = None):
        self.filename = filename
        self.fields = fields
        self.table_name = filename.replace(".csv", "")
        self.path = DATA_DIR / "history" / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # ★ v4: id_col override
        self._id_col_override = id_col

    def _get_id_col(self) -> str | None:
        """
        ★ v4: หา ID column
        1. ถ้ามี override → ใช้เลย
        2. Fallback: หาตัวแรกที่ลงท้าย _id และไม่ใช่ FK
        """
        # ── Priority 1: Override ──
        if self._id_col_override:
            return self._id_col_override

        # ── Priority 2: Auto-detect ──
        for c in self.fields:
            if c.endswith("_id") and c not in (
                "project_id", "milestone_id", "deliverable_id",
                "linked_issue_id", "meeting_id",  # FK in review
            ):
                return c
        return None

    def append(self, row: dict):
        """
        Append row — รองรับทั้ง CSV และ DB
        ★ v3: กรอง field ที่ไม่ตรง schema ออกก่อน save
        """
        clean_row = _clean_row(row, self.fields)

        if _USE_DB:
            from core.db import append_row
            append_row(self.table_name, clean_row)
        else:
            _backup(self.path)
            exists = self.path.exists()
            with open(self.path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=self.fields)
                if not exists:
                    w.writeheader()
                w.writerow(clean_row)

    def read(self, include_voided: bool = False):
        """อ่านข้อมูล — รองรับทั้ง CSV และ DB"""
        if _USE_DB:
            from core.db import read_table
            df = read_table(self.table_name)
        else:
            import pandas as pd
            if not self.path.exists():
                return pd.DataFrame(columns=self.fields)
            df = pd.read_csv(self.path, encoding="utf-8-sig")

        if include_voided:
            return df

        id_col = self._get_id_col()
        if id_col and id_col in df.columns:
            try:
                from core.void_registry import get_voided_ids
                voided = get_voided_ids()
                if voided:
                    df = df[~df[id_col].astype(str).isin(voided)].reset_index(drop=True)
            except Exception:
                pass

        return df


# ═══════════════════════════════════════════════════════════
# MASTER REPO (Single Source of Truth)
# ═══════════════════════════════════════════════════════════
class MasterRepo(_DeleteMixin):
    """
    Master CSV — overwrite ได้ (Single Source of Truth)
    ★ ใช้ DATA_DIR / "master" — ต่างจาก AppendOnlyRepo ที่ใช้ /history

    ★ v4: เพิ่ม `id_col` parameter
    """

    def __init__(self, filename: str, fields: list, id_col: str = None):
        self.filename = filename
        self.fields = fields
        self.table_name = filename.replace(".csv", "")
        self.path = DATA_DIR / "master" / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # PK = field แรก (default) หรือ id_col ที่ระบุ
        self.pk_field = id_col or (fields[0] if fields else None)
        self._id_col_override = id_col

    def _get_id_col(self) -> str | None:
        """Master ใช้ field แรกเป็น PK (หรือ override)"""
        if self._id_col_override:
            return self._id_col_override
        return self.pk_field

    def read(self, include_voided: bool = False):
        """อ่าน master data — รองรับทั้ง CSV และ DB"""
        if _USE_DB:
            from core.db import read_table
            df = read_table(self.table_name)
        else:
            import pandas as pd
            if not self.path.exists():
                return pd.DataFrame(columns=self.fields)
            df = pd.read_csv(self.path, encoding="utf-8-sig")

        if include_voided:
            return df

        id_col = self._get_id_col()
        if id_col and id_col in df.columns:
            try:
                from core.void_registry import get_voided_ids
                voided = get_voided_ids()
                if voided:
                    df = df[~df[id_col].astype(str).isin(voided)].reset_index(drop=True)
            except Exception:
                pass

        return df

    def upsert(self, row: dict, key: str):
        """
        Upsert — รองรับทั้ง CSV และ DB
        ★ v3: กรอง field ที่ไม่ตรง schema ออกก่อน save
        """
        clean_row = _clean_row(row, self.fields)

        if _USE_DB:
            from core.db import upsert_row
            upsert_row(self.table_name, clean_row, key)
        else:
            import pandas as pd
            df = self.read(include_voided=True)
            if not df.empty:
                df = df[df[key].astype(str) != str(clean_row[key])]
            new = pd.DataFrame([clean_row], columns=self.fields)
            df = pd.concat([df, new], ignore_index=True)
            _backup(self.path)
            df.to_csv(self.path, index=False, encoding="utf-8-sig")

    def delete(self, key_value: str, key: str) -> int:
        """ลบ record (ไม่มี audit) — รองรับทั้ง CSV และ DB"""
        if _USE_DB:
            from core.db import delete_row
            delete_row(self.table_name, key, str(key_value))
            return 1
        else:
            import pandas as pd
            if not self.path.exists():
                return 0
            df = self.read(include_voided=True)
            before = len(df)
            df = df[df[key].astype(str) != str(key_value)].reset_index(drop=True)
            if len(df) == before:
                return 0
            _backup(self.path)
            df.to_csv(self.path, index=False, encoding="utf-8-sig")
            return before - len(df)

    def count(self) -> int:
        try:
            return len(self.read())
        except Exception:
            return 0

    def exists(self, key_value: str, key: str = None) -> bool:
        try:
            key = key or self._get_id_col()
            df = self.read(include_voided=True)
            return str(key_value) in df[key].astype(str).values
        except Exception:
            return False