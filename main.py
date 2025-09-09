from __future__ import annotations
from app.ui import run
from PySide6.QtWidgets import QApplication
from app.security.license_gate import ensure_activated
import sys


APP_VERSION = "2.8"

def _license_gate_or_exit() -> bool:
    from app.security.license_gate import ensure_activated
    return bool(ensure_activated(current_version=APP_VERSION.lstrip("v")))

def main():
    app = QApplication(sys.argv)

    # ★ 여기서 먼저 라이선스 통과 여부 확인
    if not ensure_activated(app, current_version="1.2"):
        # 사용자가 취소했거나, 라이선스가 끝내 유효하지 않음 → 종료
        return 0

    return run()


if __name__ == "__main__":
    sys.exit(main())
