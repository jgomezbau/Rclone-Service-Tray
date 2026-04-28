from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


LOCAL_FALLBACK_ICON = Path(__file__).parent / "resources" / "icons" / "rclone-service-tray.svg"


def app_icon() -> QIcon:
    if LOCAL_FALLBACK_ICON.exists():
        local = QIcon(str(LOCAL_FALLBACK_ICON))
        if not local.isNull():
            return local
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#2f7df6"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "R")
    painter.end()
    return QIcon(pixmap)


def icon(name: str, *fallback_names: str) -> QIcon:
    for candidate in (name, *fallback_names):
        themed = QIcon.fromTheme(candidate)
        if not themed.isNull():
            return themed
    return QIcon(str(LOCAL_FALLBACK_ICON))


def colored_dot_icon(color: str, size: int = 16) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    margin = max(2, size // 8)
    painter.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)
    painter.end()
    return QIcon(pixmap)
