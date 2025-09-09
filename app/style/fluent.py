from __future__ import annotations
from PySide6.QtWidgets import QMessageBox, QPushButton, QLineEdit, QComboBox


HAS_QFW = False


try:
    from qfluentwidgets import (
    setTheme, Theme, FluentIcon as FI, PrimaryPushButton, PushButton,
    LineEdit, ComboBox, InfoBar, InfoBarPosition
    )
    HAS_QFW = True
except Exception: # fallback
    class PrimaryPushButton(QPushButton):
        pass


    class PushButton(QPushButton):
        pass


    class LineEdit(QLineEdit):
        pass


    class ComboBox(QComboBox):
        pass


    class InfoBar:
        @staticmethod
        def success(title: str = "", content: str = "", parent=None, position=None):
            QMessageBox.information(parent, title or "Info", content)
        @staticmethod
        def error(title: str = "", content: str = "", parent=None, position=None):
            QMessageBox.critical(parent, title or "Error", content)


    class InfoBarPosition:
        TOP = 0


    class Theme:
        AUTO = 0


    def setTheme(*_a, **_k):
        pass


    class FI:
        pass