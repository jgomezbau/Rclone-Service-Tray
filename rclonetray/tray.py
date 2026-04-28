from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from rclonetray.icons import app_icon, icon


def compose_tray_icon(base_icon: QIcon, activity_state: str, has_error: bool, animation_frame: int) -> QIcon:
    pixmap = base_icon.pixmap(64, 64)
    composed = QPixmap(pixmap)
    painter = QPainter(composed)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    overlay_rect = QRectF(42, 2, 20, 20)
    if has_error:
        if animation_frame % 2 == 0:
            painter.setBrush(QColor("#d92d20"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(overlay_rect)
            painter.setPen(QPen(QColor("white"), 2))
            painter.drawLine(52, 7, 52, 15)
            painter.drawPoint(52, 19)
    elif activity_state == "uploading":
        _draw_arrow_overlay(painter, overlay_rect, up=True)
    elif activity_state == "downloading":
        _draw_arrow_overlay(painter, overlay_rect, up=False)
    elif activity_state == "syncing":
        _draw_spinner_overlay(painter, overlay_rect, animation_frame)
    painter.end()
    return QIcon(composed)


def _draw_arrow_overlay(painter: QPainter, rect: QRectF, up: bool) -> None:
    painter.setBrush(QColor("#18794e" if up else "#1d4ed8"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(rect)
    painter.setBrush(QColor("white"))
    if up:
        points = [rect.center() + p for p in [QPointF(0, -6), QPointF(-4, 0), QPointF(-1, 0), QPointF(-1, 6), QPointF(1, 6), QPointF(1, 0), QPointF(4, 0)]]
    else:
        points = [rect.center() + p for p in [QPointF(0, 6), QPointF(-4, 0), QPointF(-1, 0), QPointF(-1, -6), QPointF(1, -6), QPointF(1, 0), QPointF(4, 0)]]
    painter.drawPolygon(QPolygonF(points))


def _draw_spinner_overlay(painter: QPainter, rect: QRectF, animation_frame: int) -> None:
    painter.setBrush(QColor("#7c3aed"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(rect)
    painter.setPen(QPen(QColor("white"), 2))
    painter.drawArc(rect.adjusted(3, 3, -3, -3), (animation_frame % 8) * 45 * 16, 180 * 16)


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
        state = self._global_state()
        if self.window.config.show_tray_indicators:
            self.tray.setIcon(compose_tray_icon(self.base_icon, state["activity"], state["has_error"], self.animation_frame))
        else:
            self.tray.setIcon(self.base_icon)
        self.tray.setToolTip(self._tooltip_text(state))

    def _global_state(self) -> dict[str, object]:
        any_recent_error = sum(1 for service in self.services if getattr(service, "recent_error", False))
        if any_recent_error:
            return {"activity": "error", "has_error": True, "error_services": any_recent_error}
        for activity in ["uploading", "downloading", "syncing"]:
            if any(getattr(service, "activity", "") == activity for service in self.services):
                return {"activity": activity, "has_error": False, "error_services": 0}
        if any(getattr(service, "activity", "") == "cleaning" for service in self.services):
            return {"activity": "syncing", "has_error": False, "error_services": 0}
        return {"activity": "idle", "has_error": False, "error_services": 0}

    def _tooltip_text(self, state: dict[str, object]) -> str:
        if state["has_error"]:
            count = state["error_services"]
            suffix = "servicio" if count == 1 else "servicios"
            return f"Rclone Service Tray\nErrores detectados en {count} {suffix}"
        activity = state["activity"]
        if activity == "uploading":
            return "Rclone Service Tray\nActividad: subiendo archivos"
        if activity == "downloading":
            return "Rclone Service Tray\nActividad: descargando archivos"
        if activity == "syncing":
            return "Rclone Service Tray\nActividad: sincronizando archivos"
        return "Rclone Service Tray\nTodos los servicios inactivos"
