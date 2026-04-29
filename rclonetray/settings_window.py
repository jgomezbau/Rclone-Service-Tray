from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
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
    QSizePolicy,
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
        self.setMinimumSize(900, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        tabs = QTabWidget()
        tabs.addTab(self._services_tab(), "Servicios")
        tabs.addTab(self._appearance_tab(), "Apariencia")
        tabs.addTab(self._behavior_tab(), "Comportamiento")
        tabs.addTab(self._paths_tab(), "Rutas")
        tabs.addTab(self._maintenance_tab(), "Mantenimiento")
        layout.addWidget(tabs)

        save = QPushButton("Guardar ajustes")
        save.setIcon(icon("document-save"))
        save.setDefault(True)
        save.setMinimumWidth(160)
        save.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        save.setToolTip("Guardar la configuración actual")
        save.clicked.connect(self.save)

        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(save)
        layout.addLayout(footer)
        self._resize_initial_window_to_content()

    def _services_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(
            self._section_title(
                "Servicios detectados",
                "Seleccioná qué servicios rclone querés mostrar y controlar desde la app.",
            )
        )
        self.service_checks: dict[str, QCheckBox] = {}
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Servicio", "Ruta", "Activo", "RC/API"])
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(32)
        table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        detected = self._detected_services_for_settings()
        for row, service in enumerate(detected):
            table.insertRow(row)
            name_item = QTableWidgetItem(service.name)
            path_item = QTableWidgetItem(str(service.path))
            name_item.setToolTip(service.name)
            path_item.setToolTip(str(service.path))
            table.setItem(row, 0, name_item)
            table.setItem(row, 1, path_item)
            active = QCheckBox()
            active.setChecked(service.name not in self.config.ignored_services)
            active.setToolTip("Mostrar y controlar este servicio desde Rclone Service Tray")
            self.service_checks[service.name] = active

            rc_detail = self._make_action_button(
                "Detalle",
                "network-server",
                "Ver detalle de configuración RC/API",
                fallback_icon="dialog-information",
                minimum_width=92,
            )
            rc_detail.clicked.connect(lambda _, s=service, port=self._suggested_rc_port(service, detected): RcServiceDetailDialog(s, port, self).exec())
            table.setCellWidget(row, 2, self._centered_cell(active))
            table.setCellWidget(row, 3, self._centered_cell(rc_detail))
        table.resizeColumnsToContents()
        table.setColumnWidth(0, min(max(table.columnWidth(0), 180), 260))
        table.setColumnWidth(2, 80)
        table.setColumnWidth(3, 110)
        layout.addWidget(table, 1)

        add = self._make_action_button("Agregar .service", "list-add", "Agregar manualmente un archivo .service")
        detect = self._make_action_button("Detectar automáticamente", "system-search", "Buscar servicios rclone nuevamente", fallback_icon="edit-find")
        restore_ignored = self._make_action_button("Restaurar ignorados", "edit-undo", "Volver a mostrar todos los servicios ignorados")
        reload_daemon = self._make_action_button("Recargar daemon", "system-run", "Ejecutar systemctl --user daemon-reload")
        add.clicked.connect(self._add_manual_service)
        detect.clicked.connect(self.request_reload_services.emit)
        restore_ignored.clicked.connect(self._restore_ignored)
        reload_daemon.clicked.connect(lambda: QMessageBox.information(self, "daemon-reload", self.systemd.daemon_reload().stderr or "Finalizado."))
        layout.addLayout(self._make_button_row([add, detect, restore_ignored, reload_daemon]))
        return tab

    def _resize_initial_window_to_content(self) -> None:
        detected_count = len(self._detected_services_for_settings())
        desired_width = 980
        desired_height = 640 if detected_count <= 8 else 700
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            desired_width = min(desired_width, int(available.width() * 0.9))
            desired_height = min(desired_height, int(available.height() * 0.85))
        self.resize(desired_width, desired_height)

    def _appearance_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        group, form = self._make_form_group("Apariencia", "Configurá cómo se adapta la aplicación al tema del sistema.")
        self.theme = QComboBox()
        self.theme.addItems(["system", "light", "dark"])
        self.theme.setCurrentText(self.config.theme)
        form.addRow("Tema", self.theme)
        layout.addWidget(group)
        layout.addStretch()
        return tab

    def _behavior_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        group, form = self._make_form_group("Comportamiento", "Ajustá inicio, bandeja, notificaciones y tiempos de refresco.")
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
        form.addRow("Iniciar minimizado", self.start_minimized)
        form.addRow("Minimizar al cerrar", self.minimize_to_tray)
        form.addRow("Notificaciones KDE", self.notifications)
        form.addRow("Indicadores en icono del tray", self.tray_indicators)
        form.addRow("Confirmar liberación de espacio", self.confirm_cache)
        form.addRow("Refresco estado (s)", self.refresh_interval)
        form.addRow("Refresco archivos locales (s)", self.cache_interval)
        form.addRow("Ventana actividad (s)", self.activity_window)
        layout.addWidget(group)
        layout.addStretch()
        return tab

    def _paths_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        group, form = self._make_form_group("Rutas", "Definí dónde buscar servicios, montajes, cache y logs locales.")
        self.systemd_dir = self._path_row(self.config.systemd_user_dir, form, "Servicios systemd user")
        self.mounts_dir = self._path_row(self.config.mounts_base_dir, form, "Montajes")
        self.cache_dir = self._path_row(self.config.rclone_cache_dir, form, "Archivos locales rclone")
        self.logs_dir = self._path_row(self.config.logs_dir, form, "Logs")
        layout.addWidget(group)
        layout.addStretch()
        return tab

    def _maintenance_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        info_group, info_layout = self._make_group("Información", "Consultá el uso local de cache y logs.")
        clean_group, clean_layout = self._make_group("Limpieza", "Acciones para liberar espacio o limpiar registros locales.")
        services_group, services_layout = self._make_group("Servicios", "Acciones globales sobre los servicios rclone.")

        clean_all = self._make_action_button("Liberar espacio en disco", "user-trash", "Limpiar cache local de todos los servicios rclone", fallback_icon="edit-delete", minimum_width=220)
        cache_size = self._make_action_button("Ver tamaño ocupado", "drive-harddisk", "Calcular el tamaño total usado por archivos locales", fallback_icon="folder", minimum_width=220)
        logs_size = self._make_action_button("Ver tamaño de logs", "text-x-log", "Calcular el tamaño total de logs", fallback_icon="text-x-generic", minimum_width=220)
        clean_logs = self._make_action_button("Limpiar logs", "edit-clear", "Limpiar logs locales de todos los servicios", minimum_width=220)
        clean_errors = self._make_action_button("Limpiar historial de errores", "dialog-warning", "Borrar el historial general de errores", minimum_width=220)
        clean_errors.setProperty("warning", True)
        clean_errors.setStyleSheet("QPushButton[warning=\"true\"] { font-weight: 600; }")
        restart_all = self._make_action_button("Reiniciar servicios activos", "view-refresh", "Reiniciar todos los servicios rclone activos", minimum_width=220)
        daemon_reload = self._make_action_button("Recargar daemon systemd user", "system-run", "Ejecutar systemctl --user daemon-reload", minimum_width=220)
        clean_all.clicked.connect(self.request_clean_all.emit)
        cache_size.clicked.connect(self.request_show_total_cache.emit)
        logs_size.clicked.connect(self.request_show_total_logs.emit)
        clean_logs.clicked.connect(self.request_clean_all_logs.emit)
        clean_errors.clicked.connect(self.request_clean_error_history.emit)
        restart_all.clicked.connect(self.request_restart_all.emit)
        daemon_reload.clicked.connect(lambda: QMessageBox.information(self, "daemon-reload", self.systemd.daemon_reload().stderr or "Finalizado."))

        info_layout.addLayout(self._make_button_row([cache_size, logs_size]))
        clean_layout.addLayout(self._make_button_row([clean_all, clean_logs]))
        clean_layout.addLayout(self._make_button_row([clean_errors]))
        services_layout.addLayout(self._make_button_row([restart_all, daemon_reload]))
        layout.addWidget(info_group)
        layout.addWidget(clean_group)
        layout.addWidget(services_group)
        layout.addStretch()
        return tab

    def _section_title(self, text: str, subtitle: str | None = None) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title = QLabel(text)
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 2)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        if subtitle:
            description = QLabel(subtitle)
            description.setWordWrap(True)
            description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(description)
        return wrapper

    def _make_group(self, title: str, subtitle: str | None = None) -> tuple[QGroupBox, QVBoxLayout]:
        group = QGroupBox(title)
        group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        if subtitle:
            description = QLabel(subtitle)
            description.setWordWrap(True)
            layout.addWidget(description)
        return group, layout

    def _make_form_group(self, title: str, subtitle: str | None = None) -> tuple[QGroupBox, QFormLayout]:
        group, outer = self._make_group(title, subtitle)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(form)
        return group, form

    def _make_action_button(
        self,
        text: str,
        icon_name: str,
        tooltip: str,
        *,
        fallback_icon: str | None = None,
        minimum_width: int = 0,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setIcon(icon(icon_name, fallback_icon) if fallback_icon else icon(icon_name))
        button.setToolTip(tooltip)
        if minimum_width:
            button.setMinimumWidth(minimum_width)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return button

    def _make_button_row(self, buttons: list[QPushButton]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for button in buttons:
            row.addWidget(button)
        row.addStretch()
        return row

    def _centered_cell(self, widget: QWidget) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(widget)
        return wrapper

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
        services_dir = Path(self.config.systemd_user_dir).expanduser()
        initial_dir = services_dir if services_dir.exists() else Path.home()
        filename, _ = QFileDialog.getOpenFileName(self, "Agregar .service", str(initial_dir), "Systemd service (*.service)")
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
