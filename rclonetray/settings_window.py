from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rclonetray.config import AppConfig, save_config
from rclonetray.icons import icon
from rclonetray.rc_client import RcloneRcClient
from rclonetray.service_model import RcloneService
from rclonetray.service_parser import load_services
from rclonetray.systemd_manager import SystemdManager


class SettingsWindow(QDialog):
    config_changed = Signal()
    request_clean_all = Signal()
    request_clean_all_logs = Signal()
    request_clean_error_history = Signal()
    request_show_total_cache = Signal()
    request_show_total_logs = Signal()
    request_restart_all = Signal()
    request_reload_services = Signal()

    def __init__(self, config: AppConfig, services: list[RcloneService], systemd: SystemdManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.services = services
        self.systemd = systemd
        self.setWindowTitle("Ajustes - Rclone Service Tray")
        self.setMinimumSize(840, 560)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._services_tab(), "Servicios")
        tabs.addTab(self._appearance_tab(), "Apariencia")
        tabs.addTab(self._behavior_tab(), "Comportamiento")
        tabs.addTab(self._paths_tab(), "Rutas")
        tabs.addTab(self._maintenance_tab(), "Mantenimiento")
        layout.addWidget(tabs)
        save = QPushButton("Guardar ajustes")
        save.setIcon(icon("document-save"))
        save.clicked.connect(self.save)
        layout.addWidget(save)
        self._resize_initial_window_to_content()

    def _services_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Servicios detectados:"))
        self.service_checks: dict[str, QCheckBox] = {}
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Servicio", "Ruta", "Activo en Rclone Service Tray", "RC/API", "Acción"])
        table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        detected = self._detected_services_for_settings()
        for row, service in enumerate(detected):
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(service.name))
            table.setItem(row, 1, QTableWidgetItem(str(service.path)))
            active = QCheckBox()
            active.setChecked(service.name not in self.config.ignored_services)
            self.service_checks[service.name] = active
            rc_detail = QPushButton("Detalle")
            rc_detail.setIcon(icon("network-server", "dialog-information"))
            rc_detail.clicked.connect(lambda _, s=service, port=self._suggested_rc_port(service, detected): RcServiceDetailDialog(s, port, self).exec())
            ignore = QPushButton("Ignorar")
            ignore.setIcon(icon("list-remove", "edit-delete"))
            ignore.clicked.connect(lambda _, name=service.name, checkbox=active: self._ignore_service(name, checkbox))
            table.setCellWidget(row, 2, active)
            table.setCellWidget(row, 3, rc_detail)
            table.setCellWidget(row, 4, ignore)
        table.resizeColumnsToContents()
        table.setColumnWidth(0, min(max(table.columnWidth(0), 180), 260))
        table.setColumnWidth(2, 190)
        table.setColumnWidth(3, 100)
        table.setColumnWidth(4, 110)
        layout.addWidget(table)
        add = QPushButton("Agregar archivo .service manualmente")
        add.setIcon(icon("list-add"))
        detect = QPushButton("Detectar automáticamente")
        detect.setIcon(icon("system-search", "edit-find"))
        restore_ignored = QPushButton("Restaurar ignorados")
        restore_ignored.setIcon(icon("edit-undo"))
        reload_daemon = QPushButton("Recargar daemon systemd user")
        reload_daemon.setIcon(icon("system-run"))
        add.clicked.connect(self._add_manual_service)
        detect.clicked.connect(self.request_reload_services.emit)
        restore_ignored.clicked.connect(self._restore_ignored)
        reload_daemon.clicked.connect(lambda: QMessageBox.information(self, "daemon-reload", self.systemd.daemon_reload().stderr or "Finalizado."))
        layout.addWidget(add)
        layout.addWidget(detect)
        layout.addWidget(restore_ignored)
        layout.addWidget(reload_daemon)
        layout.addStretch()
        return tab

    def _resize_initial_window_to_content(self) -> None:
        detected_count = len(self._detected_services_for_settings())
        desired_width = 980
        desired_height = 620 if detected_count <= 8 else 700
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            desired_width = min(desired_width, int(available.width() * 0.9))
            desired_height = min(desired_height, int(available.height() * 0.85))
        self.resize(desired_width, desired_height)

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
        self.tray_indicators = QCheckBox()
        self.tray_indicators.setChecked(self.config.show_tray_indicators)
        self.confirm_cache = QCheckBox()
        self.confirm_cache.setChecked(self.config.confirm_cache_clean)
        self.refresh_interval = QSpinBox()
        self.refresh_interval.setRange(3, 3600)
        self.refresh_interval.setValue(self.config.refresh_interval_seconds)
        self.cache_interval = QSpinBox()
        self.cache_interval.setRange(10, 86400)
        self.cache_interval.setValue(self.config.cache_refresh_interval_seconds)
        self.activity_window = QSpinBox()
        self.activity_window.setRange(10, 3600)
        self.activity_window.setValue(self.config.activity_window_seconds)
        layout.addRow("Iniciar minimizado", self.start_minimized)
        layout.addRow("Minimizar al cerrar", self.minimize_to_tray)
        layout.addRow("Notificaciones KDE", self.notifications)
        layout.addRow("Indicadores en icono del tray", self.tray_indicators)
        layout.addRow("Confirmar liberación de espacio", self.confirm_cache)
        layout.addRow("Refresco estado (s)", self.refresh_interval)
        layout.addRow("Refresco archivos locales (s)", self.cache_interval)
        layout.addRow("Ventana actividad (s)", self.activity_window)
        return tab

    def _paths_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        self.systemd_dir = self._path_row(self.config.systemd_user_dir, layout, "Servicios systemd user")
        self.mounts_dir = self._path_row(self.config.mounts_base_dir, layout, "Montajes")
        self.cache_dir = self._path_row(self.config.rclone_cache_dir, layout, "Archivos locales rclone")
        self.logs_dir = self._path_row(self.config.logs_dir, layout, "Logs")
        return tab

    def _maintenance_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        clean_all = QPushButton("Liberar espacio en disco de todos los rclone")
        clean_all.setIcon(icon("user-trash", "edit-delete"))
        cache_size = QPushButton("Ver tamaño total ocupado")
        cache_size.setIcon(icon("drive-harddisk", "folder"))
        logs_size = QPushButton("Ver tamaño total de logs")
        logs_size.setIcon(icon("text-x-log", "text-x-generic"))
        clean_logs = QPushButton("Limpiar logs de todos los servicios")
        clean_logs.setIcon(icon("edit-clear"))
        clean_errors = QPushButton("Limpiar historial de errores general")
        clean_errors.setIcon(icon("dialog-warning"))
        restart_all = QPushButton("Reiniciar todos los servicios activos")
        restart_all.setIcon(icon("view-refresh"))
        daemon_reload = QPushButton("Recargar daemon systemd user")
        daemon_reload.setIcon(icon("system-run"))
        clean_all.clicked.connect(self.request_clean_all.emit)
        cache_size.clicked.connect(self.request_show_total_cache.emit)
        logs_size.clicked.connect(self.request_show_total_logs.emit)
        clean_logs.clicked.connect(self.request_clean_all_logs.emit)
        clean_errors.clicked.connect(self.request_clean_error_history.emit)
        restart_all.clicked.connect(self.request_restart_all.emit)
        daemon_reload.clicked.connect(lambda: QMessageBox.information(self, "daemon-reload", self.systemd.daemon_reload().stderr or "Finalizado."))
        layout.addWidget(cache_size)
        layout.addWidget(logs_size)
        layout.addWidget(clean_all)
        layout.addWidget(clean_logs)
        layout.addWidget(clean_errors)
        layout.addWidget(restart_all)
        layout.addWidget(daemon_reload)
        layout.addStretch()
        return tab

    def _detected_services_for_settings(self) -> list[RcloneService]:
        return load_services(Path(self.config.systemd_user_dir), self.config.services, ignored_services=[])

    def _suggested_rc_port(self, service: RcloneService, services: list[RcloneService]) -> int:
        try:
            return 5573 + services.index(service)
        except ValueError:
            return 5573

    def _ignore_service(self, name: str, checkbox: QCheckBox) -> None:
        checkbox.setChecked(False)
        if name not in self.config.ignored_services:
            self.config.ignored_services.append(name)
            save_config(self.config)
        self.request_reload_services.emit()

    def _restore_ignored(self) -> None:
        self.config.ignored_services.clear()
        for checkbox in self.service_checks.values():
            checkbox.setChecked(True)
        save_config(self.config)
        self.request_reload_services.emit()

    def _path_row(self, value: str, layout: QFormLayout, label: str) -> QLineEdit:
        row = QHBoxLayout()
        edit = QLineEdit(value)
        browse = QPushButton()
        browse.setIcon(icon("folder-open"))
        browse.setToolTip("Seleccionar carpeta")
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
        self.config.show_tray_indicators = self.tray_indicators.isChecked()
        self.config.confirm_cache_clean = self.confirm_cache.isChecked()
        self.config.refresh_interval_seconds = self.refresh_interval.value()
        self.config.cache_refresh_interval_seconds = self.cache_interval.value()
        self.config.activity_window_seconds = self.activity_window.value()
        self.config.ignored_services = sorted(name for name, checkbox in self.service_checks.items() if not checkbox.isChecked())
        self.config.systemd_user_dir = self.systemd_dir.text()
        self.config.mounts_base_dir = self.mounts_dir.text()
        self.config.rclone_cache_dir = self.cache_dir.text()
        self.config.logs_dir = self.logs_dir.text()
        save_config(self.config)
        self.config_changed.emit()
        QMessageBox.information(self, "Ajustes", "Ajustes guardados.")


class RcServiceDetailDialog(QDialog):
    def __init__(self, service: RcloneService, suggested_port: int, parent=None):
        super().__init__(parent)
        self.service = service
        self.suggested_port = suggested_port
        self.setWindowTitle(f"Rclone RC/API - {service.display_name}")
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("RC detectado", QLabel("Sí" if service.rc_enabled else "No"))
        form.addRow("Dirección", QLabel(service.rc_addr or "-"))
        form.addRow("URL", QLabel(service.rc_url or "-"))
        form.addRow("Estado", QLabel(service.rc_status))
        form.addRow("Usuario", QLabel(service.rc_user or "-"))
        form.addRow("Contraseña", QLabel(service.rc_password_display or "-"))
        auth = "desactivada (--rc-no-auth)" if not service.rc_auth_enabled else "activada"
        form.addRow("Autenticación", QLabel(auth))
        if service.rc_warning:
            warning = QLabel(service.rc_warning)
            warning.setWordWrap(True)
            form.addRow("Advertencia", warning)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        test = QPushButton("Probar conexión RC")
        test.setIcon(icon("network-connect", "dialog-ok"))
        suggest = QPushButton("Sugerir configuración RC")
        suggest.setIcon(icon("document-edit"))
        test.clicked.connect(self._test_connection)
        suggest.clicked.connect(self._show_suggestion)
        buttons.addWidget(test)
        buttons.addWidget(suggest)
        buttons.addStretch()
        layout.addLayout(buttons)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def _test_connection(self) -> None:
        if not self.service.rc_enabled:
            QMessageBox.information(self, "RC/API", "Este servicio no tiene --rc configurado.")
            return
        client = RcloneRcClient(self.service, timeout=1.0)
        if client.is_available():
            QMessageBox.information(self, "RC/API", "Conexión RC disponible.")
        else:
            QMessageBox.warning(self, "RC/API", "RC no responde o no está disponible.")

    def _show_suggestion(self) -> None:
        text = (
            "Para habilitar actividad en tiempo real, agregue a ExecStart:\n\n"
            "--rc \\\n"
            f"--rc-addr 127.0.0.1:{self.suggested_port} \\\n"
            "--rc-no-auth \\\n\n"
            "Use un puerto distinto por servicio. Se recomienda 127.0.0.1; no use 0.0.0.0 salvo que entienda el riesgo de exponer la API RC a la red."
        )
        QMessageBox.information(self, "Sugerir configuración RC", text)
