# app/i18n_loader.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict

# 내부 상태
_STATE = {"lang": "en", "messages": {}}  # 기본: 영문 폴백

def _bundle_dir() -> Path:
    # i18n 폴더: app/i18n/
    here = Path(__file__).resolve().parent
    return here / "i18n"

def _load_messages(lang: str) -> Dict[str, str]:
    # ko.json 같은 번들 읽기 (없으면 빈 dict)
    f = _bundle_dir() / f"{lang}.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}

def set_locale(lang: str) -> None:
    """로케일 설정: ko / en 등. 없으면 en으로 폴백."""
    lang = (lang or "en").lower()
    msgs = _load_messages(lang)
    if not msgs:
        # 폴백: en 시도
        msgs = _load_messages("en")
        lang = "en"
    _STATE["lang"] = lang
    _STATE["messages"] = msgs

def get_locale() -> str:
    return _STATE["lang"]

def _(text: str) -> str:
    """번역 함수. 키가 없으면 원문 그대로 반환."""
    return _STATE["messages"].get(text, text)
