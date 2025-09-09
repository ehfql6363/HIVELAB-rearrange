from __future__ import annotations
import os, shutil, sys
from pathlib import Path

PROGRAMDATA_DIR = Path(os.environ.get("PROGRAMDATA", "")) / "HIVELAB"
APPDATA_DIR    = Path(os.environ.get("APPDATA", "")) / "HIVELAB"
KEYSET_NAME    = "trusted_keyset.fsqpub"

def _exists_anywhere() -> bool:
    for p in [
        PROGRAMDATA_DIR / KEYSET_NAME,
        APPDATA_DIR / KEYSET_NAME,
        Path.cwd() / KEYSET_NAME
    ]:
        if p.exists():
            return True
    return False

def _bundled_candidates() -> list[Path]:
    c = []
    if hasattr(sys, "_MEIPASS"):  # PyInstaller onefile 임시 폴더
        c.append(Path(sys._MEIPASS) / KEYSET_NAME)
    c.append(Path.cwd() / KEYSET_NAME)                         # 실행 폴더
    c.append(Path(__file__).resolve().parents[3] / KEYSET_NAME)  # 프로젝트 루트 추정
    return [p for p in c if p.exists()]

def ensure_keyset_installed() -> Path|None:
    """키셋이 없으면 EXE 옆/번들에서 찾아 ProgramData→AppData 순으로 복사."""
    if _exists_anywhere():
        return None
    srcs = _bundled_candidates()
    if not srcs:
        return None
    src = srcs[0]
    # 1) ProgramData 시도
    try:
        PROGRAMDATA_DIR.mkdir(parents=True, exist_ok=True)
        dst = PROGRAMDATA_DIR / KEYSET_NAME
        shutil.copyfile(src, dst)
        return dst
    except Exception:
        pass
    # 2) AppData 폴백
    try:
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        dst = APPDATA_DIR / KEYSET_NAME
        shutil.copyfile(src, dst)
        return dst
    except Exception:
        return None
