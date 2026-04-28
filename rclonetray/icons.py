from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon


LOCAL_FALLBACK_ICON = Path(__file__).parent / "resources" / "icons" / "rclone-service-tray.svg"


def icon(name: str, *fallback_names: str) -> QIcon:
    for candidate in (name, *fallback_names):
        themed = QIcon.fromTheme(candidate)
        if not themed.isNull():
            return themed
    return QIcon(str(LOCAL_FALLBACK_ICON))
