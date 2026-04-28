from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon


class Notifier:
    def __init__(self, tray: QSystemTrayIcon | None, enabled: bool = True):
        self.tray = tray
        self.enabled = enabled

    def notify(self, title: str, message: str, critical: bool = False) -> None:
        if not self.enabled or self.tray is None:
            return
        icon = QSystemTrayIcon.MessageIcon.Critical if critical else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(title, message, icon, 6000)
