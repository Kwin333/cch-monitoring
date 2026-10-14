import json
from pathlib import Path
CFG = Path(__file__).parent / "config" / "settings.json"

def load_settings() -> dict:
    with open(CFG, "r", encoding="utf-8") as f:
        return json.load(f)

def save_settings(data: dict):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)