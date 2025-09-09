# fsq/style/cupertino.py
from __future__ import annotations
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor, QFont

ACCENT = QColor("#0A84FF")   # macOS 블루
BG     = QColor("#F5F5F7")   # macOS 배경
CARD   = QColor("#FFFFFF")
BORDER = QColor("#E5E5EA")
TEXT   = QColor("#1C1C1E")

def apply_cupertino(app: QApplication) -> None:
    app.setStyle("Fusion")  # 플랫폼 간 일관성

    pal = QPalette()
    pal.setColor(QPalette.Window, BG)
    pal.setColor(QPalette.Base, QColor("#FAFAFC"))
    pal.setColor(QPalette.Button, CARD)
    pal.setColor(QPalette.ButtonText, TEXT)
    pal.setColor(QPalette.Text, TEXT)
    pal.setColor(QPalette.ToolTipBase, CARD)
    pal.setColor(QPalette.WindowText, TEXT)
    pal.setColor(QPalette.Highlight, ACCENT)
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    app.setPalette(pal)

    # 폰트: macOS면 SF, 그 외는 유사 계열로 폴백
    font_candidates = ["SF Pro Display", "Apple SD Gothic Neo", "Segoe UI Variable", "Segoe UI", "Noto Sans KR", "Malgun Gothic"]
    f = QFont()
    for name in font_candidates:
        f = QFont(name)
        if f.exactMatch():
            break
    f.setPointSizeF(11.0)
    app.setFont(f)

    # 전역 스타일시트(QSS)
    app.setStyleSheet("""
    QWidget { background: #F5F5F7; color: #1C1C1E; font-size: 13px; }
    QLabel { font-weight: 500; }
    QFrame#Card, QFrame[card="true"] {
        background: #FFFFFF; border:1px solid #E5E5EA; border-radius:14px;
    }
    QLineEdit, QComboBox, QTextEdit {
        background: #FFFFFF; border:1px solid #E5E5EA; border-radius:10px; padding:8px 10px;
    }
    QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: #0A84FF; }

    QPushButton {
        border-radius:10px; padding:8px 14px; border:1px solid #E5E5EA; background:#FFFFFF;
    }
    QPushButton:hover { background:#F2F2F7; }
    QPushButton:pressed { background:#E5E5EA; }

    /* primary 버튼은 동적 프로퍼티로 지정: setProperty("primary", True) */
    QPushButton[primary="true"] {
        background:#0A84FF; color:white; border:none;
    }
    QPushButton[primary="true"]:hover  { background:#0C7DFF; }
    QPushButton[primary="true"]:pressed{ background:#0969DA; }

    QListWidget, QTableWidget, QProgressBar, QTextEdit {
        background:#FFFFFF; border:1px solid #E5E5EA; border-radius:12px;
    }
    QHeaderView::section {
        background:#FBFBFD; border:none; border-bottom:1px solid #E5E5EA; padding:6px 8px; font-weight:600;
    }
    QProgressBar { background:#E5E5EA; border-radius:6px; height:12px; }
    QProgressBar::chunk { background:#0A84FF; border-radius:6px; }

    QToolTip { background:#FFFFFF; color:#1C1C1E; border:1px solid #E5E5EA; padding:6px 8px; border-radius:8px;}
    """)
