from __future__ import annotations
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QDialogButtonBox

class PinDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PIN 입력")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("라이선스 PIN을 입력하세요:"))
        self.pin = QLineEdit(self); self.pin.setEchoMode(QLineEdit.Password)
        lay.addWidget(self.pin)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def value(self) -> str:
        return self.pin.text() or ""