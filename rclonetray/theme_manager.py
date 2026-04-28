from __future__ import annotations

from PySide6.QtWidgets import QApplication


LIGHT_STYLE = """
QWidget { font-size: 10pt; }
QMainWindow, QDialog { background: #f7f7f8; color: #202124; }
QTableWidget { background: #ffffff; gridline-color: #dddddf; selection-background-color: #d8e8ff; }
QHeaderView::section { background: #ececef; padding: 6px; border: 0; border-right: 1px solid #d4d4d8; }
QPushButton { padding: 6px 10px; border: 1px solid #c6c6ca; border-radius: 6px; background: #ffffff; }
QPushButton:hover { background: #eef5ff; }
QLineEdit, QSpinBox, QComboBox, QTextEdit { background: #ffffff; color: #202124; border: 1px solid #c6c6ca; border-radius: 6px; padding: 5px; }
"""

DARK_STYLE = """
QWidget { font-size: 10pt; }
QMainWindow, QDialog { background: #202124; color: #f1f3f4; }
QTableWidget { background: #2b2c30; color: #f1f3f4; gridline-color: #3c4043; selection-background-color: #174ea6; }
QHeaderView::section { background: #303134; color: #f1f3f4; padding: 6px; border: 0; border-right: 1px solid #4b4c50; }
QPushButton { padding: 6px 10px; border: 1px solid #5f6368; border-radius: 6px; background: #303134; color: #f1f3f4; }
QPushButton:hover { background: #3c4043; }
QLineEdit, QSpinBox, QComboBox, QTextEdit { background: #303134; color: #f1f3f4; border: 1px solid #5f6368; border-radius: 6px; padding: 5px; }
"""


def apply_theme(app: QApplication, theme: str) -> None:
    if theme == "dark":
        app.setStyleSheet(DARK_STYLE)
    elif theme == "light":
        app.setStyleSheet(LIGHT_STYLE)
    else:
        app.setStyleSheet("")
