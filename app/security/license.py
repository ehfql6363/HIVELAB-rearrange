# fsq/security/license.py
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
import re
import hashlib, hmac

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

from app.security.fingerprint import compute_fingerprint
from app.security.keyset import load_trusted_pubkeys  # 서명된 키셋 로더

# (선택) 임베디드 발급 공개키(들) — 없으면 빈 리스트로 둬도 됩니다.
EMBEDDED_ISSUER_KEYS_PEM: List[bytes] = [
    b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAPQLKPPXyv8973UdMIyD7DeVeMu3ZZdileGeH580lb40=
-----END PUBLIC KEY-----"""
]

LICENSE_FILENAME = "license.fsqlic"

@dataclass
class LicensePayload:
    license_id: str
    holder: str
    fingerprint: str
    expires: str
    max_version: str
    pin_salt: str
    pin_hash: str

def _iso_now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _parse_iso8601(s: str) -> datetime:
    s = (s or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)

def _normalize_license_text(text: str) -> tuple[dict, bytes]:
    text = text.strip()
    if "\n--SIG--\n" in text:
        j, sig = text.split("\n--SIG--\n", 1)
        payload = json.loads(j)
        sig_bytes = base64.b64decode(sig.strip())
        return payload, sig_bytes
    else:
        payload = json.loads(text)
        sig_b64 = payload.pop("_sig", "")
        sig_bytes = base64.b64decode(sig_b64) if sig_b64 else b""
        return payload, sig_bytes

def _canonical_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _pub_from_pem(pem: bytes) -> Optional[Ed25519PublicKey]:
    try:
        pub = serialization.load_pem_public_key(pem)
        raw = pub.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        return Ed25519PublicKey.from_public_bytes(raw)
    except Exception:
        return None

def _allowed_pubkeys() -> List[Ed25519PublicKey]:
    pubs: List[Ed25519PublicKey] = []
    for pem in EMBEDDED_ISSUER_KEYS_PEM:
        obj = _pub_from_pem(pem)
        if obj:
            pubs.append(obj)
    pubs.extend(load_trusted_pubkeys())  # 키셋에서 로드(없으면 빈 리스트)
    return pubs

def verify_signature(payload: dict, signature: bytes) -> bool:
    msg = _canonical_json_bytes(payload)
    for pub in _allowed_pubkeys():
        try:
            pub.verify(signature, msg)
            return True
        except Exception:
            continue
    return False

def check_password(payload: dict, password: str) -> bool:
    try:
        salt_hex = payload.get("pin_salt", "")
        want_hex = payload.get("pin_hash", "")
        if not salt_hex or not want_hex:
            # PIN 미사용 라이선스일 수 있음
            return (password or "") == ""
        salt = bytes.fromhex(salt_hex)
        mac = hmac.new(salt, (password or "").encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, want_hex)
    except Exception:
        return False

# ---------------- Version compare (정확 + 폴백) ----------------
def _parse_ver_tuple(v: str) -> tuple:
    # 간단 폴백: 숫자만 추출하여 튜플화 (1.10 vs 1.2 올바르게 비교)
    nums = [int(x) for x in re.findall(r"\d+", v or "0")]
    # 길이 맞춤(주로 major.minor.patch 기준)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])

def _version_leq(cur: str, maxv: str) -> bool:
    try:
        from packaging.version import Version
        return Version(cur) <= Version(maxv)
    except Exception:
        # packaging 없으면 폴백
        return _parse_ver_tuple(cur) <= _parse_ver_tuple(maxv)
# -------------------------------------------------------------

def validate_license_text(license_text: str, current_version: str, password: Optional[str]) -> tuple[bool, str, dict]:
    """검증 성공 여부, 메시지, payload 반환(성공 시)."""
    try:
        payload, sig = _normalize_license_text(license_text)
    except Exception as e:
        return False, f"라이선스 파싱 실패: {e}", {}
    if not sig:
        return False, "서명 누락", {}

    if not verify_signature(payload, sig):
        return False, "서명 검증 실패", {}

    if payload.get("fingerprint") != compute_fingerprint():
        return False, "이 PC에 발급된 라이선스가 아닙니다.", {}

    try:
        dt = _parse_iso8601(payload.get("expires", "1970-01-01T00:00:00Z"))
        if _iso_now_utc() > dt:
            return False, "라이선스가 만료되었습니다.", {}
    except Exception:
        return False, "만료일 형식 오류", {}

    maxv = str(payload.get("max_version", "9999.0.0"))
    if not _version_leq(str(current_version), maxv):
        return False, "현재 버전에서 사용할 수 없는 라이선스입니다.", {}

    if password is not None:
        if not check_password(payload, password):
            return False, "비밀번호가 올바르지 않습니다.", {}

    return True, "OK", payload

def default_license_search_paths() -> list[Path]:
    paths: list[Path] = []
    appdata = os.environ.get("APPDATA") or ""
    if appdata:
        paths.append(Path(appdata) / "HIVELAB" / LICENSE_FILENAME)
    progdata = os.environ.get("PROGRAMDATA") or ""
    if progdata:
        paths.append(Path(progdata) / "HIVELAB" / LICENSE_FILENAME)
    paths.append(Path.cwd() / LICENSE_FILENAME)
    return paths

def load_license_from_disk() -> Optional[str]:
    for p in default_license_search_paths():
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                pass
    return None

def save_license_to_disk(text: str) -> Optional[Path]:
    appdata = os.environ.get("APPDATA")
    targets = []
    if appdata:
        targets.append(Path(appdata) / "HIVELAB")
    progdata = os.environ.get("PROGRAMDATA")
    if progdata:
        targets.append(Path(progdata) / "HIVELAB")
    for d in targets:
        try:
            d.mkdir(parents=True, exist_ok=True)
            p = d / LICENSE_FILENAME
            p.write_text(text, encoding="utf-8")
            return p
        except Exception:
            continue
    return None
