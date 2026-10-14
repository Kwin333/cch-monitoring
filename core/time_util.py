from datetime import datetime
import pytz

BKK = pytz.timezone("Asia/Bangkok")

def now_str() -> str:
    return datetime.now(BKK).strftime("%Y-%m-%d %H:%M:%S")

def today_str() -> str:
    return datetime.now(BKK).strftime("%Y-%m-%d")

def parse_date(s):
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None