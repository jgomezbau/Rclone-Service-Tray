from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rclonetray.config import AppConfig, save_config
from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import SystemdManager


class SettingsWindow(QDialog):
    config_changed = Signal()
    request_clean_all = Signal()
    request_restart_all = Signal()
    request_reload_services = Signal()

    def __init__(self, config: AppConfig, services: list[RcloneService], systemd: SystemdManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.services = services
        self.systemd = systemd
        self.setWindowTitle("Ajustes - Rclone Service Tray")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._services_tab(), "Servicios")
        tabs.addTab(self._appearance_tab(), "Apariencia")
        tabs.addTab(self._behavior_tab(), "Comportamiento")
        tabs.addTab(self._paths_tab(), "Rutas")
        tabs.addTab(self._maintenance_tab(), "Mantenimiento")
        layout.addWidget(tabs)
        save = QPushButton("Guardar ajustes")
        save.clicked.connect(self.save)
        layout.addWidget(save)

    def _services_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Servicios cargados:"))
        for service in self.services:
            layout.addWidget(QLabel(f"{service.name} - {service.path}"))
        add = QPushButton("Agregar archivo .service manualmente")
        detect = QPushButton("Detectar automáticamente")
        reload_daemon = QPushButton("Recargar daemon systemd user")
        add.clicked.connect(self._add_manual_service)
        detect.clicked.connect(self.request_reload_services.emit)
        reload_daemon.clicked.connect(lambda: QMessageBox.information(self, "daemon-reload", self.systemd.daemon_reload().stderr or "Finalizado."))
        layout.addWidget(add)
        layout.addWidget(detect)
        layout.addWidget(reload_daemon)
        layout.addStretch()
        return tab

    def _appearance_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        self.theme = QComboBox()
        self.theme.addItems(["system", "light", "dark"])
        self.theme.setCurrentText(self.config.theme)
        layout.addRow("Tema", self.theme)
        return tab

    def _behavior_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        self.start_minimized = QCheckBox()
        self.start_minimized.setChecked(self.config.start_minimized)
        self.minimize_to_tray = QCheckBox()
        self.minimize_to_tray.setChecked(self.config.minimize_to_tray)
        self.notifications = QCheckBox()
        self.notifications.setChecked(self.config.show_notifications)
        self.confirm_cache = QCheckBox()
        self.confirm_cache.setChecked(self.config.confirm_cache_clean)
        self.refresh_interval = QSpinBox()
        self.refresh_interval.setRange(3, 3600)
        self.refresh_interval.setValue(self.config.refresh_interval_seconds)
        self.cache_interval = QSpinBox()
        self.cache_interval.setRange(10, 86400)
        self.cache_interval.setValue(self.config.cache_refresh_interval_seconds)
        layout.addRow("Iniciar minimizado", self.start_minimized)
        layout.addRow("Minimizar al cerrar", self.minimize_to_tray)
        layout.addRow("Notificaciones KDE", self.notifications)
        layout.addRow("Confirmar limpieza de cache", self.confirm_cache)
        layout.addRow("Refresco estado (s)", self.refresh_interval)
        layout.addRow("Refresco cache (s)", self.cache_interval)
        return tab

    def _paths_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        self.systemd_dir = self._path_row(self.config.systemd_user_dir, layout, "Servicios systemd user")
        self.mounts_dir = self._path_row(self.config.mounts_base_dir, layout, "Montajes")
        self.cache_dir = self._path_row(self.config.rclone_cache_dir, layout, "Cache rclone")
        self.logs_dir = self._path_row(self.config.logs_dir, layout, "Logs")
        return tab

    def _maintenance_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        clean_all = QPushButton("Limpiar cache de todos los rclone")
        restart_all = QPushButton("Reiniciar todos los servicios")
        daemon_reload = QPushButton("Recargar daemon systemd user")
        clean_all.clicked.connect(self.request_clean_all.emit)
        restart_all.clicked.connect(self.request_restart_all.emit)
        daemon_reload.clicked.connect(lambda: QMessageBox.information(self, "daemon-reload", self.systemd.daemon_reload().stderr or "Finalizado."))
        layout.addWidget(clean_all)
        layout.addWidget(restart_all)
        layout.addWidget(daemon_reload)
        layout.addStretch()
        return tab

    def _path_row(self, value: str, layout: QFormLayout, label: str) -> QLineEdit:
        row = QHBoxLayout()
        edit = QLineEdit(value)
        browse = QPushButton("...")
        browse.setFixedWidth(36)
        browse.clicked.connect(lambda: self._browse_dir(edit))
        row.addWidget(edit)
        row.addWidget(browse)
        wrapper = QWidget()
        wrapper.setLayout(row)
        layout.addRow(label, wrapper)
        return edit

    def _browse_dir(self, edit: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta", edit.text())
        if directory:
            edit.setText(directory)

    def _add_manual_service(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Agregar .service", str(Path.home()), "Systemd service (*.service)")
        if filename and filename not in self.config.services:
            self.config.services.append(filename)
            save_config(self.config)
            self.request_reload_services.emit()

    def save(self) -> None:
        self.config.theme = self.theme.currentText()
        self.config.start_minimized = self.start_minimized.isChecked()
        self.config.minimize_to_tray = self.minimize_to_tray.isChecked()
        self.config.show_notifications = self.notifications.isChecked()
        self.config.confirm_cache_clean = self.confirm_cache.isChecked()
        self.config.refresh_interval_seconds = self.refresh_interval.value()
        self.config.cache_refresh_interval_seconds = self.cache_interval.value()
        self.config.systemd_user_dir = self.systemd_dir.text()
        self.config.mounts_base_dir = self.mounts_dir.text()
        self.config.rclone_cache_dir = self.cache_dir.text()
        self.config.logs_dir = self.logs_dir.text()
        save_config(self.config)
        self.config_changed.emit()
        QMessageBox.information(self, "Ajustes", "Ajustes guardados.")
