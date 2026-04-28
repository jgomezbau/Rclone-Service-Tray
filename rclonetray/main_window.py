from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QTimer, Signal, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QApplication,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rclonetray.activity_detector import ActivityDetector
from rclonetray.cache_manager import CacheManager, human_size
from rclonetray.config import AppConfig
from rclonetray.dialogs import CacheDialog, ServiceEditorDialog, TextDialog
from rclonetray.log_manager import LogManager
from rclonetray.notifications import Notifier
from rclonetray.service_model import RcloneService
from rclonetray.service_parser import discover_service_files, parse_service_file
from rclonetray.settings_window import SettingsWindow
from rclonetray.systemd_manager import SystemdManager
from rclonetray.theme_manager import apply_theme


STATUS_LABELS = {
    "active": "🟢 Activo",
    "inactive": "🔴 Detenido",
    "failed": "⚠️ Con errores",
    "activating": "🔵 Montando",
    "deactivating": "🟡 Reiniciando",
}

ACTIVITY_LABELS = {
    "idle": "☁️ Inactivo",
    "syncing": "🔄 Sincronizando",
    "downloading": "⬇️ Descargando",
    "uploading": "⬆️ Subiendo",
    "reading": "📖 Leyendo",
    "writing": "✏️ Escribiendo",
    "cleaning": "🧹 Limpiando cache",
    "error": "⚠️ Error reciente",
}


class MainWindow(QMainWindow):
    quit_requested = Signal()

    def __init__(self, config: AppConfig, systemd: SystemdManager, notifier: Notifier, parent=None):
        super().__init__(parent)
        self.config = config
        self.systemd = systemd
        self.notifier = notifier
        self.cache = CacheManager(Path(config.rclone_cache_dir))
        self.logs = LogManager(systemd)
        self.activity = ActivityDetector(self.logs)
        self.services: list[RcloneService] = []
        self.setWindowTitle("Rclone Service Tray")
        self.resize(1180, 620)
        self._build_ui()
        self.reload_services()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.config.refresh_interval_seconds * 1000)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Remoto", "Estado", "Actividad", "Punto de montaje", "Tamaño cache", "Errores", "Acciones"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellClicked.connect(self._cell_clicked)
        layout.addWidget(self.table)
        bottom = QHBoxLayout()
        refresh = QPushButton("Refrescar")
        restart_all = QPushButton("Reiniciar todos")
        errors = QPushButton("Ver errores recientes")
        settings = QToolButton()
        settings.setText("⚙")
        settings.setToolTip("Ajustes")
        refresh.clicked.connect(self.refresh)
        restart_all.clicked.connect(self.restart_all)
        errors.clicked.connect(self.show_all_errors)
        settings.clicked.connect(self.open_settings)
        bottom.addWidget(refresh)
        bottom.addWidget(restart_all)
        bottom.addWidget(errors)
        bottom.addStretch()
        bottom.addWidget(settings)
        layout.addLayout(bottom)
        self.setCentralWidget(root)

    def reload_services(self) -> None:
        paths = discover_service_files(Path(self.config.systemd_user_dir).expanduser())
        paths.extend(Path(p).expanduser() for p in self.config.services)
        unique = []
        seen = set()
        for path in paths:
            if path in seen or not path.exists():
                continue
            seen.add(path)
            unique.append(path)
        services = []
        for path in unique:
            try:
                services.append(parse_service_file(path))
            except OSError:
                continue
        self.services = services
        self.refresh()

    def refresh(self) -> None:
        self.cache = CacheManager(Path(self.config.rclone_cache_dir))
        for service in self.services:
            service.active_state, service.sub_state = self.systemd.show_state(service.name)
            service.cache_path = self.cache.cache_path_for(service)
            info = self.cache.inspect(service.cache_path)
            service.cache_size = info.size
            service.cache_files = info.files
            service.cache_mtime = info.mtime
            service.recent_errors = self.logs.error_count(service)
            service.activity = "error" if service.recent_errors else self.activity.detect(service)
        self._populate_table()

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        for row, service in enumerate(self.services):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(service.display_name))
            status = QTableWidgetItem(STATUS_LABELS.get(service.active_state, service.active_state))
            status.setToolTip("Clic derecho para acciones")
            self.table.setItem(row, 1, status)
            activity = QTableWidgetItem(ACTIVITY_LABELS.get(service.activity, service.activity))
            self.table.setItem(row, 2, activity)
            self.table.setItem(row, 3, QTableWidgetItem(str(service.mount_point or "-")))
            cache_item = QTableWidgetItem(human_size(service.cache_size))
            if service.cache_mtime:
                cache_item.setToolTip(
                    f"{service.cache_files} archivos, modificado {dt.datetime.fromtimestamp(service.cache_mtime):%Y-%m-%d %H:%M}"
                )
            self.table.setItem(row, 4, cache_item)
            self.table.setItem(row, 5, QTableWidgetItem(str(service.recent_errors)))
            actions = QPushButton("Acciones")
            actions.clicked.connect(lambda _, s=service: self.show_service_menu(s, actions))
            self.table.setCellWidget(row, 6, actions)
        self.table.resizeColumnsToContents()

    def _cell_clicked(self, row: int, column: int) -> None:
        if row < 0 or row >= len(self.services):
            return
        service = self.services[row]
        if column == 1:
            self.show_service_menu(service)
        elif column == 2:
            self.show_activity(service)
        elif column == 4:
            self.show_cache(service)
        elif column == 5:
            self.show_errors(service)

    def show_service_menu(self, service: RcloneService, anchor: QWidget | None = None) -> None:
        menu = self._service_menu(service)
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft()) if anchor else self.mapToGlobal(self.rect().center())
        menu.exec(pos)

    def _service_menu(self, service: RcloneService) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Iniciar servicio", lambda: self._run_service_action("Iniciar", self.systemd.start(service.name)))
        menu.addAction("Detener servicio", lambda: self._run_service_action("Detener", self.systemd.stop(service.name)))
        menu.addAction("Reiniciar servicio", lambda: self._run_service_action("Reiniciar", self.systemd.restart(service.name)))
        menu.addAction("Recargar daemon systemd user", lambda: self._run_service_action("daemon-reload", self.systemd.daemon_reload()))
        menu.addSeparator()
        menu.addAction("Ver estado systemd", lambda: self.show_text("Estado systemd", self.systemd.status(service.name).stdout))
        menu.addAction("Ver últimos errores", lambda: self.show_errors(service))
        menu.addAction("Editar archivo .service", lambda: ServiceEditorDialog(service, self.systemd, self).exec())
        menu.addAction("Validar archivo .service", lambda: self.validate_service(service))
        menu.addAction("Abrir carpeta .service", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(service.path.parent))))
        menu.addSeparator()
        menu.addAction("Ver cache", lambda: self.show_cache(service))
        menu.addAction("Limpiar cache", lambda: self.clean_cache(service))
        menu.addAction("Actividad", lambda: self.show_activity(service))
        return menu

    def _run_service_action(self, title: str, result) -> None:
        self.refresh()
        QMessageBox.information(self, title, result.stdout or result.stderr or "Comando finalizado.")

    def show_text(self, title: str, text: str) -> None:
        TextDialog(title, text or "Sin salida.", self).exec()

    def show_errors(self, service: RcloneService) -> None:
        self.show_text(f"Errores recientes - {service.display_name}", "\n".join(self.logs.recent_errors(service)) or "Sin errores recientes.")

    def validate_service(self, service: RcloneService) -> None:
        result = self.systemd.verify(service.path)
        self.show_text("Validación", result.stdout + result.stderr or "Validación completada sin salida.")

    def show_all_errors(self) -> None:
        chunks = []
        for service in self.services:
            errors = self.logs.recent_errors(service)
            if errors:
                chunks.append(f"== {service.name} ==\n" + "\n".join(errors))
        self.show_text("Errores recientes", "\n\n".join(chunks) or "Sin errores recientes.")

    def show_activity(self, service: RcloneService) -> None:
        lines = self.activity.relevant_lines(service)
        self.show_text(f"Actividad - {service.display_name}", "\n".join(lines) or "No hay líneas de log disponibles.")

    def show_cache(self, service: RcloneService) -> None:
        CacheDialog(service, self.cache, self.clean_cache, self).exec()

    def clean_cache(self, service: RcloneService) -> None:
        if self.config.confirm_cache_clean:
            answer = QMessageBox.warning(
                self,
                "Confirmar limpieza",
                f"Se detendrá temporalmente {service.name}, se eliminará su cache local y luego se volverá a iniciar.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            )
            if answer != QMessageBox.StandardButton.Ok:
                return
        service.activity = "cleaning"
        result = self.cache.clear_cache_for_service(service, self.systemd)
        self.refresh()
        self.notifier.notify("Rclone Service Tray", result.stdout or result.stderr, critical=not result.ok)
        QMessageBox.information(self, "Limpiar cache", result.stdout or result.stderr)

    def clean_all_caches(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Limpiar todos los caches",
            "Se detendrán temporalmente todos los montajes rclone, se eliminará el cache local y luego se volverán a iniciar.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        results = self.cache.clear_all(self.services, self.systemd)
        self.refresh()
        text = "\n".join(f"{name}: {'OK' if result.ok else 'ERROR'} {result.stderr or result.stdout}" for name, result in results)
        self.notifier.notify("Rclone Service Tray", "Limpieza de cache finalizada")
        QMessageBox.information(self, "Resultado", text)

    def restart_all(self) -> None:
        output = []
        for service in self.services:
            result = self.systemd.restart(service.name)
            output.append(f"{service.name}: {'OK' if result.ok else 'ERROR'} {result.stderr or result.stdout}")
        self.refresh()
        QMessageBox.information(self, "Reiniciar todos", "\n".join(output))

    def open_settings(self) -> None:
        dialog = SettingsWindow(self.config, self.services, self.systemd, self)
        dialog.config_changed.connect(self._settings_changed)
        dialog.request_clean_all.connect(self.clean_all_caches)
        dialog.request_restart_all.connect(self.restart_all)
        dialog.request_reload_services.connect(self.reload_services)
        dialog.exec()

    def _settings_changed(self) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.config.theme)
        self.timer.start(self.config.refresh_interval_seconds * 1000)
        self.reload_services()

    def closeEvent(self, event) -> None:
        if self.config.minimize_to_tray:
            event.ignore()
            self.hide()
        else:
            self.quit_requested.emit()
