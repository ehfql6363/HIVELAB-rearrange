from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

# "루트 공개키"로 trusted_keyset.fsqpub 파일의 서명을 검증
# 검증이 통과하면 키셋에 포함된 "발급용 공개키"들을 반환

ROOT_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAlUtdOCgw+wHZ3+dAGYYXfMMd5anFPew/CqCcnDds200=
-----END PUBLIC KEY-----"""

KEYSET_FILENAME = "trusted_keyset.fsqpub"


@dataclass
class Keyset:
    issued_at: str
    valid_from: Optional[str]
    valid_to: Optional[str]
    keys_pem: List[bytes]  # PEM bytes list


def _iso_now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso8601_z(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _normalize_keyset_text(text: str) -> tuple[dict, bytes]:
    """
    trusted_keyset.fsqpub 포맷:
        {canonical JSON}
        --SIG--
        base64(signature by ROOT private key)
    """
    text = text.strip()
    if "\n--SIG--\n" not in text:
        # _sig 필드 내장 방식도 허용하려면 아래처럼 처리 가능
        payload = json.loads(text)
        sig_b64 = payload.pop("_sig", "")
        return payload, (base64.b64decode(sig_b64) if sig_b64 else b"")
    js, sig = text.split("\n--SIG--\n", 1)
    payload = json.loads(js)
    return payload, base64.b64decode(sig.strip())


def _canonical_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _root_pubkey_obj() -> Ed25519PublicKey:
    pub = serialization.load_pem_public_key(ROOT_PUBLIC_KEY_PEM)
    raw = pub.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return Ed25519PublicKey.from_public_bytes(raw)


def _verify_keyset_signature(payload: dict, signature: bytes) -> bool:
    try:
        msg = _canonical_json_bytes(payload)
        _root_pubkey_obj().verify(signature, msg)
        return True
    except Exception:
        return False


def _extract_keys_pem(payload: dict) -> List[bytes]:
    keys = []
    arr = payload.get("keys", [])
    for item in arr:
        pem = item.get("pem", "")
        if isinstance(pem, str) and pem.strip().startswith("-----BEGIN PUBLIC KEY-----"):
            keys.append(pem.encode("utf-8"))
    return keys


def _is_within_range(valid_from: Optional[str], valid_to: Optional[str]) -> bool:
    now = _iso_now_utc()
    vf = _parse_iso8601_z(valid_from)
    vt = _parse_iso8601_z(valid_to)
    if vf and now < vf:
        return False
    if vt and now > vt:
        return False
    return True


def default_keyset_search_paths() -> list[Path]:
    paths: list[Path] = []
    # ProgramData 우선(모든 사용자 공용)
    progdata = os.environ.get("PROGRAMDATA") or ""
    if progdata:
        paths.append(Path(progdata) / "HIVELAB" / KEYSET_FILENAME)
    # 사용자별 APPDATA
    appdata = os.environ.get("APPDATA") or ""
    if appdata:
        paths.append(Path(appdata) / "HIVELAB" / KEYSET_FILENAME)
    # 실행 디렉토리
    paths.append(Path.cwd() / KEYSET_FILENAME)
    return paths


def load_trusted_pubkeys() -> List[Ed25519PublicKey]:
    """서명 검증에 통과한 키셋의 '발급용 공개키'들을 반환(없으면 빈 리스트)."""
    for p in default_keyset_search_paths():
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
            payload, sig = _normalize_keyset_text(text)
            if not sig:
                continue
            if not _verify_keyset_signature(payload, sig):
                continue
            # 날짜 유효성(옵션)
            valid_from = payload.get("valid_from")
            valid_to = payload.get("valid_to")
            if not _is_within_range(valid_from, valid_to):
                continue
            pem_list = _extract_keys_pem(payload)
            objs: List[Ed25519PublicKey] = []
            for pem in pem_list:
                try:
                    pub = serialization.load_pem_public_key(pem)
                    raw = pub.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
                    objs.append(Ed25519PublicKey.from_public_bytes(raw))
                except Exception:
                    continue
            if objs:
                return objs
        except Exception:
            continue
    return []
