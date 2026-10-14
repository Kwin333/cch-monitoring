"""ทะเบียนรายการที่ถูก Void — soft delete registry"""
import csv
from pathlib import Path
from core.time_util import now_str

VOID_FILE = Path(__file__).parent.parent / "data" / "audit" / "voided_records.csv"
FIELDS = ["void_id", "record_type", "record_id", "reason",
          "voided_by", "voided_at", "mode"]


def _ensure():
    VOID_FILE.parent.mkdir(parents=True, exist_ok=True)


def add_void(record_type: str, record_id: str,
             reason: str, user: str, mode: str = "soft"):
    """mode: soft | hard"""
    _ensure()
    exists = VOID_FILE.exists()
    with open(VOID_FILE, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerow({
            "void_id":     f"VOID-{now_str().replace('-','').replace(':','').replace(' ','')[:15]}-{record_id[-4:]}",
            "record_type": record_type,
            "record_id":   record_id,
            "reason":      reason,
            "voided_by":   user,
            "voided_at":   now_str(),
            "mode":        mode,
        })


def remove_void(record_id: str) -> bool:
    """ยกเลิกการ Void — คืน True ถ้าลบสำเร็จ"""
    _ensure()
    if not VOID_FILE.exists():
        return False
    import pandas as pd
    df = pd.read_csv(VOID_FILE, encoding="utf-8-sig")
    before = len(df)
    df = df[df["record_id"] != record_id]
    if len(df) == before:
        return False
    df.to_csv(VOID_FILE, index=False, encoding="utf-8-sig")
    return True


def is_voided(record_id: str) -> bool:
    if not VOID_FILE.exists():
        return False
    import pandas as pd
    df = pd.read_csv(VOID_FILE, encoding="utf-8-sig")
    return record_id in df["record_id"].values


def get_voided_ids() -> set:
    if not VOID_FILE.exists():
        return set()
    import pandas as pd
    df = pd.read_csv(VOID_FILE, encoding="utf-8-sig")
    return set(df["record_id"].astype(str).tolist())


def read_voids():
    import pandas as pd
    if not VOID_FILE.exists():
        return pd.DataFrame(columns=FIELDS)
    return pd.read_csv(VOID_FILE, encoding="utf-8-sig")

def get_void_info(record_id: str) -> dict | None:
    """คืนข้อมูล void ของ record_id (ล่าสุด)"""
    if not VOID_FILE.exists():
        return None
    import pandas as pd
    df = pd.read_csv(VOID_FILE, encoding="utf-8-sig")
    sub = df[df["record_id"].astype(str) == str(record_id)]
    if sub.empty:
        return None
    return sub.iloc[-1].to_dict()


def count_voids_by_type() -> dict:
    """นับจำนวน voided records แต่ละประเภท"""
    if not VOID_FILE.exists():
        return {}
    import pandas as pd
    df = pd.read_csv(VOID_FILE, encoding="utf-8-sig")
    if df.empty:
        return {}
    return df["record_type"].value_counts().to_dict()

def search_voids(keyword: str) -> list:
    """ค้นหา voided records"""
    if not VOID_FILE.exists() or not keyword:
        return []
    import pandas as pd
    df = pd.read_csv(VOID_FILE, encoding="utf-8-sig")
    kw = keyword.lower()
    mask = (
        df["record_id"].astype(str).str.lower().str.contains(kw, na=False)
        | df["reason"].astype(str).str.lower().str.contains(kw, na=False)
        | df["voided_by"].astype(str).str.lower().str.contains(kw, na=False)
    )
    return df[mask].to_dict("records")