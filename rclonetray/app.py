from __future__ import annotations

import logging

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from rclonetray.config import load_config, setup_logging
from rclonetray.icons import app_icon
from rclonetray.main_window import MainWindow
from rclonetray.notifications import Notifier
from rclonetray.systemd_manager import SystemdManager
from rclonetray.theme_manager import apply_theme
from rclonetray.tray import TrayController


def run(argv: list[str]) -> int:
    setup_logging()
    app = QApplication(argv)
    app.setApplicationName("Rclone Service Tray")
    app.setDesktopFileName("rclone-service-tray")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setFont(QFont("Noto Sans", 10))
    app.setWindowIcon(app_icon())
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.warning(None, "Rclone Service Tray", "No se detectó system tray disponible.")
    config = load_config()
    apply_theme(app, config.theme)
    systemd = SystemdManager()
    window = MainWindow(config, systemd, Notifier(None, config.show_notifications))
    tray = TrayController(window)
    window.set_tray_controller(tray)
    tray.show()
    window.notifier.tray = tray.tray
    window.quit_requested.connect(app.quit)
    if not config.start_minimized:
        window.show()
    logging.info("Rclone Service Tray started")
    return app.exec()
