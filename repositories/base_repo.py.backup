"""Append-only CSV repository + Master snapshot repository

Components:
- AppendOnlyRepo: history CSV (append-only) + soft/hard delete
- MasterRepo: master CSV (Single Source of Truth) + soft/hard delete

Key Features:
- ✅ Backup อัตโนมัติก่อนแก้ไขทุกครั้ง
- ✅ Soft Delete: ซ่อนจาก UI, ข้อมูลยังอยู่ใน CSV
- ✅ Hard Delete: ลบถาวรทั้ง UI และ CSV (พร้อม backup + audit)
- ✅ 3 read modes: read_active / read_voided / read_all
- ✅ Void registry integration (core.void_registry)
- ✅ Both repos มี API เดียวกัน: read/soft_delete/restore/hard_delete
"""
import csv
import shutil
from pathlib import Path
from datetime import datetime


# ============================================================
# PATHS
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data"


# ============================================================
# BACKUP HELPER
# ============================================================
def _backup(path: Path) -> Path | None:
    """สำรองไฟล์ก่อนแก้ — คืน path ที่ backup สำเร็จ"""
    if not path.exists():
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


# ============================================================
# COMMON MIXIN — shared soft/hard delete logic
# ============================================================
class _DeleteMixin:
    """Shared methods สำหรับ soft/hard delete — ใช้ทั้ง 2 repo"""

    def _get_id_col(self) -> str | None:
        """หา ID column — override ใน subclass"""
        raise NotImplementedError

    def read_active(self):
        return self.read(include_voided=False)

    def read_voided(self):
        import pandas as pd
        if not self.path.exists():
            return pd.DataFrame(columns=self.fields)
        df = pd.read_csv(self.path, encoding="utf-8-sig")
        id_col = self._get_id_col()
        if not id_col or id_col not in df.columns:
            return pd.DataFrame(columns=self.fields)
        try:
            from core.void_registry import get_voided_ids
            voided = get_voided_ids()
            if not voided:
                return pd.DataFrame(columns=self.fields)
            return df[
                df[id_col].astype(str).isin(voided)
            ].reset_index(drop=True)
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

    def soft_delete(self, record_id: str, reason: str, user: str):
        """ทำเครื่องหมายว่าถูกลบ — ข้อมูลยังอยู่ใน CSV แต่จะถูกซ่อนใน UI"""
        from core.void_registry import add_void
        from core.audit import append_audit

        df = self.read(include_voided=True)
        id_col = self._get_id_col()
        if id_col is None or id_col not in df.columns:
            raise ValueError(
                f"ไม่พบ ID column ใน {self.path.name} — fields: {self.fields}"
            )

        if str(record_id) not in df[id_col].astype(str).values:
            raise ValueError(f"ไม่พบ record_id: {record_id}")

        rows = df[df[id_col].astype(str) == str(record_id)]
        old_row = rows.iloc[-1].to_dict() if len(rows) > 0 else {}

        # record_type: ตัด "_history" หรือ "_master" ออก
        record_type = (
            self.path.stem
            .replace("_history", "")
            .replace("_master", "")
        )

        add_void(record_type, record_id, reason, user, mode="soft")
        append_audit(
            user, "SOFT_DELETE", self.path.stem, record_id,
            old_value=str(old_row)[:500],
            new_value="voided",
            reason=reason,
        )

    def restore(self, record_id: str, user: str):
        """ยกเลิกการ Void"""
        from core.void_registry import remove_void
        from core.audit import append_audit
        ok = remove_void(record_id)
        if ok:
            append_audit(
                user, "RESTORE", self.path.stem, record_id,
                old_value="voided", new_value="active",
                reason="ยกเลิก Void",
            )
        return ok

    def hard_delete(
        self,
        record_id: str,
        reason: str,
        user: str,
        create_backup: bool = True,
    ) -> dict:
        """
        ลบ record ออกจาก CSV อย่างถาวร
        - ลบออกจาก voided_records ด้วย (ถ้ามี)
        - Backup CSV ก่อนลบ (default = True)
        - Audit log บันทึก HARD_DELETE
        """
        import pandas as pd
        from core.void_registry import remove_void
        from core.audit import append_audit

        if not self.path.exists():
            raise FileNotFoundError(f"ไม่พบไฟล์: {self.path}")

        df = pd.read_csv(self.path, encoding="utf-8-sig")
        id_col = self._get_id_col()

        if id_col is None or id_col not in df.columns:
            raise ValueError(
                f"ไม่พบ ID column ใน {self.path.name} — "
                f"fields: {self.fields}"
            )

        mask = df[id_col].astype(str) == str(record_id)
        n_match = int(mask.sum())

        if n_match == 0:
            raise ValueError(f"ไม่พบ record_id: {record_id}")

        deleted_rows = df[mask].to_dict("records")
        rows_before = len(df)

        backup_path = ""
        if create_backup:
            b = _backup(self.path)
            backup_path = str(b) if b else ""

        df_after = df[~mask].reset_index(drop=True)
        df_after.to_csv(self.path, index=False, encoding="utf-8-sig")

        # ลบออกจาก voided_records ด้วย
        try:
            remove_void(str(record_id))
        except Exception:
            pass

        # Audit log
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
            "deleted":     n_match,
            "backup":      backup_path,
            "rows_before": rows_before,
            "rows_after":  len(df_after),
        }

    def hard_delete_all(
        self,
        record_ids: list,
        reason: str,
        user: str,
    ) -> dict:
        """ลบหลาย record พร้อมกัน"""
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
            return {
                "deleted":     0,
                "backup":      "",
                "rows_before": len(df),
                "rows_after":  len(df),
                "not_found":   not_found,
            }

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
            "deleted":     n_match,
            "backup":      str(b) if b else "",
            "rows_before": len(df),
            "rows_after":  len(df_after),
            "not_found":   not_found,
        }


# ============================================================
# APPEND-ONLY REPO
# ============================================================
class AppendOnlyRepo(_DeleteMixin):
    """
    History CSV — append เท่านั้น ห้าม overwrite
    - Soft Delete: ซ่อนใน UI (ข้อมูลยังอยู่)
    - Hard Delete: ลบถาวรทั้ง UI และ CSV
    """

    def __init__(self, filename: str, fields: list):
        self.path = DATA_DIR / "history" / filename
        self.fields = fields
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # WRITE
    # --------------------------------------------------------
    def append(self, row: dict):
        """เพิ่ม record ใหม่ (append-only)"""
        assert set(row.keys()) <= set(self.fields), \
            f"unknown fields: {set(row.keys()) - set(self.fields)}"
        _backup(self.path)
        exists = self.path.exists()
        with open(self.path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=self.fields)
            if not exists:
                w.writeheader()
            w.writerow(row)

    # --------------------------------------------------------
    # ID COLUMN DETECTION — history ใช้ field ที่ลงท้าย _id
    # --------------------------------------------------------
    def _get_id_col(self) -> str | None:
        """หา ID column (ตัวแรกที่ลงท้าย _id และไม่ใช่ FK)"""
        for c in self.fields:
            if c.endswith("_id") and c not in (
                "project_id", "milestone_id", "deliverable_id"
            ):
                return c
        return None

    # --------------------------------------------------------
    # READ
    # --------------------------------------------------------
    def read(self, include_voided: bool = False):
        """อ่านข้อมูลจาก history CSV"""
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
                    df = df[
                        ~df[id_col].astype(str).isin(voided)
                    ].reset_index(drop=True)
            except Exception:
                pass

        return df


# ============================================================
# MASTER REPO (Single Source of Truth)
# ============================================================
class MasterRepo(_DeleteMixin):
    """
    Master CSV — overwrite ได้ (Single Source of Truth)
    - Soft Delete: ซ่อนใน UI (ข้อมูลยังอยู่)
    - Hard Delete: ลบถาวรทั้ง UI และ CSV
    """

    def __init__(self, filename: str, fields: list):
        self.path = DATA_DIR / "master" / filename
        self.fields = fields
        # PK = field แรกเสมอ (สำหรับ master files)
        self.pk_field = fields[0] if fields else None
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # ID COLUMN — master ใช้ field แรกเป็น PK
    # --------------------------------------------------------
    def _get_id_col(self) -> str | None:
        return self.pk_field

    # --------------------------------------------------------
    # READ
    # --------------------------------------------------------
    def read(self, include_voided: bool = False):
        """อ่าน master CSV (กรอง voided ตาม default)"""
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
                    df = df[
                        ~df[id_col].astype(str).isin(voided)
                    ].reset_index(drop=True)
            except Exception:
                pass

        return df

    # --------------------------------------------------------
    # UPSERT
    # --------------------------------------------------------
    def upsert(self, row: dict, key: str):
        """เพิ่มหรือแก้ไข record"""
        import pandas as pd
        df = self.read(include_voided=True)   # ใช้ทั้งหมดเพื่อ replace
        df = df[df[key].astype(str) != str(row[key])] if not df.empty else df
        new = pd.DataFrame([row], columns=self.fields)
        df = pd.concat([df, new], ignore_index=True)
        _backup(self.path)
        df.to_csv(self.path, index=False, encoding="utf-8-sig")

    # --------------------------------------------------------
    # DELETE (legacy — เรียก hard_delete แบบง่าย)
    # --------------------------------------------------------
    def delete(self, key_value: str, key: str) -> int:
        """ลบ record ออกจาก master CSV — คืนจำนวนที่ลบ (ไม่มี audit)"""
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

    # --------------------------------------------------------
    # UTILITIES
    # --------------------------------------------------------
    def count(self) -> int:
        """นับจำนวน records (active)"""
        try:
            return len(self.read())
        except Exception:
            return 0

    def exists(self, key_value: str, key: str = None) -> bool:
        """ตรวจว่า record มีอยู่"""
        try:
            key = key or self._get_id_col()
            df = self.read(include_voided=True)
            return str(key_value) in df[key].astype(str).values
        except Exception:
            return False