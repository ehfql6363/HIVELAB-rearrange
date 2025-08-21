import json
from pathlib import Path
from typing import Any, Dict

APP_DIR = Path.home() / ".yourapp"
APP_DIR.mkdir(exist_ok=True)

SETTINGS_FILE = APP_DIR / "settings.json"

DEFAULTS: Dict[str, Any] = {
    "language": "ko",
    "last_input_dir": "",
    "window": {"width": 1000, "height": 720}
}

def load_settings() -> Dict[str, Any]:
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = DEFAULTS.copy()
                merged.update(data)
                return merged
    except Exception:
        pass
    return DEFAULTS.copy()

def save_settings(s: Dict[str, Any]) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
