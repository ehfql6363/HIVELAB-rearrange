from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtGui import (
    QDropEvent, QDragEnterEvent, QKeySequence, QShortcut, QFont, QGuiApplication
)
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QHBoxLayout, QFileDialog, QTextEdit
)

from app.security.fingerprint import compute_fingerprint
from app.security.license import validate_license_text, save_license_to_disk
from app.style.fluent import PrimaryPushButton, PushButton, InfoBar

APP_VERSION = "1.1"  # 앱 버전과 맞춰 주세요


# ---------- 강력 디코더: 파일을 어떤 인코딩으로든 최대한 안전하게 텍스트로 ----------
_HIDDEN_CHARS_RE = re.compile(r"[\ufeff\u200b\u200c\u200d\u2060]+")

def _read_text_robust(path: str) -> str:
    data = Path(path).read_bytes()
    for enc in ("utf-8", "utf-8-sig", "utf-16-le", "utf-16-be"):
        try:
            s = data.decode(enc)
            break
        except Exception:
            continue
    else:
        s = data.decode("latin-1", errors="ignore")

    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _HIDDEN_CHARS_RE.sub("", s)
    return s.strip()


# ---------- 드래그&드롭으로 '파일 내용'을 받아들이는 QTextEdit ----------
class LicenseDropTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setPlaceholderText(
            "여기에 라이선스 파일을 드롭하거나, 라이선스 텍스트를 붙여넣으세요.\n"
            "(JSON 또는 JSON\\n--SIG--\\nbase64sig)"
        )

    def dragEnterEvent(self, e: QDragEnterEvent):
        md = e.mimeData()
        if md.hasUrls() or md.hasText():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e: QDropEvent):
        md = e.mimeData()
        # 1) 파일 드롭 우선
        if md.hasUrls():
            for u in md.urls():
                p = u.toLocalFile()
                if p and Path(p).is_file():
                    try:
                        text = _read_text_robust(p)
                        self.setPlainText(text)
                        InfoBar.success(title="불러오기", content="파일에서 라이선스를 불러왔습니다.", parent=self.window())
                        e.acceptProposedAction()
                        return
                    except Exception as ex:
                        InfoBar.error(title="오류", content=f"파일 읽기 실패: {ex}", parent=self.window())
                        e.acceptProposedAction()
                        return
        # 2) 일반 텍스트 드롭
        if md.hasText():
            self.insertPlainText(md.text())
            e.acceptProposedAction()
            return
        super().dropEvent(e)


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("라이선스 인증")
        self.resize(600, 520)

        root = QVBoxLayout(self)

        head = QLabel("이 PC에서 사용할 라이선스를 입력하세요.")
        head.setWordWrap(True)
        root.addWidget(head)

        # --- PC 지문 표시 + 복사 ---
        fp_row = QHBoxLayout()
        fp_label = QLabel("이 PC 지문:")
        self.fpEdit = QLineEdit(self)
        self.fpEdit.setReadOnly(True)
        self.fpEdit.setText(compute_fingerprint())
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.fpEdit.setFont(mono)

        self.copyFpBtn = PushButton("복사")
        self.copyFpBtn.clicked.connect(self.onCopyFingerprint)

        fp_row.addWidget(fp_label)
        fp_row.addWidget(self.fpEdit, 1)
        fp_row.addWidget(self.copyFpBtn)
        root.addLayout(fp_row)

        # --- 라이선스 입력(드롭/붙여넣기 지원) ---
        self.licEdit = LicenseDropTextEdit(self)
        root.addWidget(self.licEdit, 1)

        # --- PIN(비밀번호) ---
        self.pinEdit = QLineEdit(self)
        self.pinEdit.setEchoMode(QLineEdit.Password)
        self.pinEdit.setPlaceholderText("비밀번호(PIN, 선택)")
        root.addWidget(self.pinEdit)

        # --- 버튼들 ---
        row = QHBoxLayout()
        self.loadBtn = PushButton("파일에서 불러오기")
        self.loadBtn.clicked.connect(self.onLoadFile)
        row.addWidget(self.loadBtn)

        self.okBtn = PrimaryPushButton("확인")
        self.okBtn.clicked.connect(self.onConfirm)
        # 엔터 제출: 기본 버튼 지정
        self.okBtn.setDefault(True)
        self.okBtn.setAutoDefault(True)
        row.addWidget(self.okBtn)

        self.cancelBtn = PushButton("취소")
        self.cancelBtn.clicked.connect(self.reject)
        row.addWidget(self.cancelBtn)

        root.addLayout(row)

        # 단축키
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.onLoadFile)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.onConfirm)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self.onCopyFingerprint)
        # 엔터(일반/넘패드) → 텍스트 상자에 포커스가 없을 때만 확인
        QShortcut(QKeySequence("Return"), self, activated=self._submitIfAllowed)
        QShortcut(QKeySequence("Enter"), self, activated=self._submitIfAllowed)
        # PIN 칸에서 엔터
        self.pinEdit.returnPressed.connect(self.onConfirm)

        self.validated_payload: Optional[dict] = None
        self.saved_path: Optional[Path] = None

    # ---------- 엔터 제출 보호(텍스트 박스에서는 줄바꿈 유지) ----------
    def _submitIfAllowed(self):
        if self.licEdit.hasFocus():
            # 라이선스 텍스트 상자에서는 엔터가 줄바꿈으로 동작해야 하므로 무시
            return
        self.onConfirm()

    # ---------- 지문 복사 ----------
    def onCopyFingerprint(self):
        text = self.fpEdit.text().strip()
        QGuiApplication.clipboard().setText(text)
        InfoBar.success(title="복사", content="지문이 클립보드에 복사되었습니다.", parent=self)

    # ---------- 파일에서 불러오기 ----------
    def onLoadFile(self):
        path, _ = QFileDialog.getOpenFileName(self, "라이선스 파일 선택", "", "All Files (*);;Text (*.txt *.lic)")
        if not path:
            return
        try:
            text = _read_text_robust(path)
            self.licEdit.setPlainText(text)
            InfoBar.success(title="불러오기", content="파일에서 라이선스를 불러왔습니다.", parent=self)
        except Exception as e:
            InfoBar.error(title="오류", content=f"파일 읽기 실패: {e}", parent=self)

    # ---------- 확인(검증 + 저장) ----------
    def onConfirm(self):
        # 사용자가 경로 문자열을 붙여넣었을 수도 있으니, 경로면 파일 내용으로 교체
        raw = (self.licEdit.toPlainText() or "").strip()
        txt = raw
        # file:// 드롭 대비
        p = Path(raw.replace("file:///", "").replace("file://", ""))

        if len(raw) < 260 and p.is_file():  # 경로처럼 보이고 실제 파일이면
            try:
                txt = _read_text_robust(str(p))
                self.licEdit.setPlainText(txt)
            except Exception as e:
                InfoBar.error(title="오류", content=f"파일 읽기 실패: {e}", parent=self)
                return

        pin = (self.pinEdit.text() or "")
        ok, msg, payload = validate_license_text(txt, APP_VERSION, pin if pin != "" else None)
        if not ok:
            InfoBar.error(title="인증 실패", content=msg, parent=self)
            return

        path = save_license_to_disk(txt)
        self.validated_payload = payload
        self.saved_path = path
        InfoBar.success(title="인증 성공", content="라이선스가 저장되었습니다.", parent=self)
        self.accept()
