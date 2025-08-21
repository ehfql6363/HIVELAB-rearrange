import json
from pathlib import Path
from typing import Dict

from .settings import load_settings

_LANG_CACHE: Dict[str, Dict[str, str]] = {}

def _(key: str) -> str:
    """Trivial i18n getter. Defaults to key if not found."""
    lang = load_settings().get("language", "ko")
    if lang not in _LANG_CACHE:
        _LANG_CACHE[lang] = _load_lang(lang)
    return _LANG_CACHE.get(lang, {}).get(key, key)

def _load_lang(lang: str) -> Dict[str, str]:
    here = Path(__file__).parent
    f = here / "i18n" / f"{lang}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}
