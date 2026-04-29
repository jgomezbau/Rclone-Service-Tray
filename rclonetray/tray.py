from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QAction, QFont, QIcon, QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from rclonetray.icons import app_icon, icon


TRAY_STATES = {"error", "restarting", "uploading", "downloading", "syncing", "idle"}


def _get_global_tray_state(services) -> str:
    if any(getattr(service, "recent_error", False) for service in services):
        return "error"
    if any(getattr(service, "transient_state", None) in {"restarting", "starting", "stopping", "mounting"} for service in services):
        return "restarting"
    if any(getattr(service, "activity", "") == "uploading" for service in services):
        return "uploading"
    if any(getattr(service, "activity", "") == "downloading" for service in services):
        return "downloading"
    if any(getattr(service, "activity", "") in {"syncing", "cleaning"} for service in services):
        return "syncing"
    return "idle"


def _build_tray_icon(state: str, animation_frame: int, base_icon: QIcon | None = None) -> QIcon:
    if state == "idle":
        return base_icon or app_icon()

    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_state_background(painter, state)
    if state == "error":
        _draw_center_text(painter, "!", QColor("white"), point_size=38, y_offset=-1)
        painter.setPen(QPen(QColor("white"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(24, 16, 32, 8)
        painter.drawLine(32, 8, 40, 16)
    elif state == "uploading":
        _draw_center_text(painter, "↑", QColor("white"), point_size=46, y_offset=-4)
    elif state == "downloading":
        _draw_center_text(painter, "↓", QColor("white"), point_size=46, y_offset=-4)
    else:
        _draw_spinner_icon(painter, animation_frame)
    painter.end()
    return QIcon(pixmap)


def _draw_state_background(painter: QPainter, state: str) -> None:
    colors = {
        "error": "#d92d20",
        "restarting": "#7c3aed",
        "uploading": "#18794e",
        "downloading": "#1d4ed8",
        "syncing": "#7c3aed",
    }
    painter.setBrush(QColor(colors.get(state, "#2f7df6")))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(4, 4, 56, 56), 14, 14)


def _draw_center_text(painter: QPainter, text: str, color: QColor, point_size: int, y_offset: int = 0) -> None:
    font = QFont("Noto Sans", point_size)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(color)
    rect = QRectF(4, 4 + y_offset, 56, 56)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


def _draw_spinner_icon(painter: QPainter, animation_frame: int) -> None:
    painter.setPen(QPen(QColor("white"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    rect = QRectF(16, 16, 32, 32)
    painter.drawArc(rect, (animation_frame % 8) * 45 * 16, 250 * 16)
    _draw_center_text(painter, "↻", QColor("white"), point_size=25, y_offset=-1)


class TrayController:
    def __init__(self, window):
        self.window = window
        self.base_icon = app_icon()
        self.tray = QSystemTrayIcon(self.base_icon)
        self.tray.setToolTip("Rclone Service Tray")
        self.animation_frame = 0
        self.services = []
        self.menu = QMenu()
        self.open_action = QAction(icon("window-new"), "Abrir Rclone Service Tray")
        self.restart_all_action = QAction(icon("view-refresh"), "Reiniciar todos los rclone")
        self.errors_action = QAction(icon("dialog-warning"), "Ver errores recientes")
        self.clean_all_action = QAction(icon("user-trash", "edit-delete"), "Liberar espacio en disco de todos los rclone")
        self.settings_action = QAction(icon("settings-configure", "preferences-system"), "Ajustes")
        self.quit_action = QAction(icon("application-exit"), "Salir")
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
        self.timer = QTimer()
        self.timer.timeout.connect(self._animate)
        self.timer.start(500)

    def show(self) -> None:
        self.tray.show()
        self._refresh_visuals()

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

    def update_services(self, services) -> None:
        self.services = list(services)
        self._refresh_visuals()

    def _animate(self) -> None:
        self.animation_frame += 1
        self._refresh_visuals()

    def _refresh_visuals(self) -> None:
        state = _get_global_tray_state(self.services)
        if self.window.config.show_tray_indicators:
            self.tray.setIcon(_build_tray_icon(state, self.animation_frame, self.base_icon))
        else:
            self.tray.setIcon(self.base_icon)
        self.tray.setToolTip(self._tooltip_text(state))

    def _tooltip_text(self, state: str) -> str:
        active = sum(1 for service in self.services if getattr(service, "active_state", "") == "active")
        syncing = sum(1 for service in self.services if getattr(service, "activity", "") in {"uploading", "downloading", "syncing", "cleaning"})
        errors = sum(1 for service in self.services if getattr(service, "recent_error", False))
        restarting = sum(1 for service in self.services if getattr(service, "transient_state", None) in {"restarting", "starting", "stopping", "mounting"})
        labels = {
            "error": "errores detectados",
            "restarting": "servicios cambiando de estado",
            "uploading": "subiendo archivos",
            "downloading": "descargando archivos",
            "syncing": "sincronizando archivos",
            "idle": "sin actividad",
        }
        return "\n".join(
            [
                "Rclone Service Tray",
                f"Estado: {labels.get(state, state)}",
                f"Activos: {active}",
                f"En sincronización: {syncing}",
                f"Con errores: {errors}",
                f"Reiniciando/montando/deteniendo: {restarting}",
            ]
        )
