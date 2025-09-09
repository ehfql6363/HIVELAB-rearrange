from __future__ import annotations
import sys
from typing import Optional
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog

from app.security.license import (
    load_license_from_disk,
    validate_license_text,
)
from app.security.license_dialog import LicenseDialog

# 앱 버전은 프로젝트의 실제 버전과 맞춰 주세요
APP_VERSION = "1.2"


def _try_auto_validate(current_version: str) -> bool:
    """디스크에 저장된 라이선스가 이미 유효하면 True."""
    lic_text = load_license_from_disk()
    if not lic_text:
        return False
    ok, _msg, _payload = validate_license_text(lic_text, current_version, password=None)
    return ok


def ensure_activated(app: QApplication, current_version: Optional[str] = None) -> bool:
    """
    메인 윈도우 생성 전에 호출하세요.
    - 저장된 라이선스가 유효하면 True 즉시 반환
    - 없거나 무효면 LicenseDialog를 띄워 사용자에게 입력 받음
      (성공 시 True, 취소 시 False → 앱 종료)
    """
    version = current_version or APP_VERSION

    # 1) 자동 검증(이미 저장된 라이선스가 유효한지)
    if _try_auto_validate(version):
        return True

    # 2) 수동 입력(다이얼로그)
    while True:
        dlg = LicenseDialog(parent=None)  # 지문 표시/복사 + 붙여넣기/파일 불러오기 + PIN
        result = dlg.exec()

        Accepted = getattr(QDialog, "DialogCode", QDialog).Accepted
        if result == Accepted:
            # LicenseDialog 내부에서 검증·저장까지 완료되면 Accepted로 닫힘.
            # (안전하게 한 번 더 확인하고 싶으면 아래처럼 재검증)
            lic_text = (dlg.licEdit.toPlainText() or "").strip()
            pin = (dlg.pinEdit.text() or "")
            ok, _msg, _payload = validate_license_text(lic_text, version, pin)
            if ok:
                return True
            QMessageBox.warning(None, "인증 실패", "라이선스 검증에 실패했습니다. 다시 시도하세요.")
            continue
        else:
            # 사용자가 취소/닫기 → 앱 종료
            return False
