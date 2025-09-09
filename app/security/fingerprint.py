from __future__ import annotations

import hashlib
import os
import subprocess


def _win_machine_guid() -> str:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        val, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(val).strip()
    except Exception:
        return ""

def _win_volume_serial(drive: str = "C:") -> str:
    try:
        # 'vol C:' 출력에서 시리얼 추출
        out = subprocess.check_output(["cmd", "/c", f"vol {drive}"], stderr=subprocess.DEVNULL, text=True)
        # 예: Volume Serial Number is XXXX-XXXX
        for line in out.splitlines():
            if "Serial Number is" in line:
                return line.split("is")[-1].strip().replace("-", "")
    except Exception:
        pass
    return ""

def _mac_addr() -> str:
    try:
        import uuid
        mac = uuid.getnode()
        return f"{mac:012x}"
    except Exception:
        return ""

def compute_fingerprint() -> str:
    """Windows 우선. 다른 OS는 확장 가능."""
    parts = []
    if os.name == "nt":
        parts += [_win_machine_guid(), _win_volume_serial("C:"), _mac_addr()]
    else:
        parts += [_mac_addr()]
    raw = "|".join(x for x in parts if x)
    if not raw:
        raw = "fallback"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
