from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


def app_icon() -> QIcon:
    themed = QIcon.fromTheme("folder-cloud")
    if not themed.isNull():
        return themed
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#2f7df6"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "R")
    painter.end()
    return QIcon(pixmap)


class TrayController:
    def __init__(self, window):
        self.window = window
        self.tray = QSystemTrayIcon(app_icon())
        self.tray.setToolTip("Rclone Service Tray")
        self.menu = QMenu()
        self.open_action = QAction("Abrir Rclone Service Tray")
        self.restart_all_action = QAction("Reiniciar todos los rclone")
        self.errors_action = QAction("Ver errores recientes")
        self.clean_all_action = QAction("Limpiar cache de todos los rclone")
        self.settings_action = QAction("Ajustes")
        self.quit_action = QAction("Salir")
        for action in [
            self.open_action,
            self.restart_all_action,
            self.errors_action,
            self.clean_all_action,
            self.settings_action,
            self.quit_action,
        ]:
            self.menu.addAction(action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.open_action.triggered.connect(self.toggle_window)
        self.restart_all_action.triggered.connect(window.restart_all)
        self.errors_action.triggered.connect(window.show_all_errors)
        self.clean_all_action.triggered.connect(window.clean_all_caches)
        self.settings_action.triggered.connect(window.open_settings)
        self.quit_action.triggered.connect(QApplication.instance().quit)

    def show(self) -> None:
        self.tray.show()

    def toggle_window(self) -> None:
        if self.window.isVisible():
            self.window.hide()
        else:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            self.toggle_window()
