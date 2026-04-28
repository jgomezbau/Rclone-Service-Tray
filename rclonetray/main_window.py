from __future__ import annotations

import datetime as dt
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QApplication,
    QHeaderView,
    QLabel,
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

from rclonetray.activity_detector import ActivityDetector, select_activity_summary
from rclonetray.cache_manager import CacheManager, human_size
from rclonetray.config import AppConfig, save_config
from rclonetray.dialogs import CacheDialog, ErrorDialog, ServiceEditorDialog, TextDialog
from rclonetray.icons import icon
from rclonetray.log_manager import LogManager
from rclonetray.notifications import Notifier
from rclonetray.rc_client import ActivitySummary, RcloneRcClient
from rclonetray.service_model import RcloneService
from rclonetray.service_parser import load_services
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
    "cleaning": "🧹 Liberando espacio",
    "error": "⚠️ Error reciente",
}


class MainWindow(QMainWindow):
    quit_requested = Signal()
    rc_summary_ready = Signal(str, object)

    def __init__(self, config: AppConfig, systemd: SystemdManager, notifier: Notifier, parent=None):
        super().__init__(parent)
        self.config = config
        self.systemd = systemd
        self.notifier = notifier
        self.cache = CacheManager(Path(config.rclone_cache_dir))
        self.logs = LogManager(systemd, Path(config.logs_dir))
        self.activity = ActivityDetector(self.logs, self.config.activity_window_seconds)
        self.services: list[RcloneService] = []
        self._activity_frame = 0
        self._initial_size_applied = False
        self._rc_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rclone-rc")
        self._rc_pending: set[str] = set()
        self.tray_controller = None
        self.setWindowTitle("Rclone Service Tray")
        self._build_ui()
        self.rc_summary_ready.connect(self._apply_rc_summary)
        self.reload_services()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.config.refresh_interval_seconds * 1000)
        self.activity_timer = QTimer(self)
        self.activity_timer.timeout.connect(self._advance_activity_animation)
        self.activity_timer.start(500)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Remoto", "Estado", "Actividad", "API", "Punto de montaje", "Espacio en disco", "Errores", ""]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        self.table.cellClicked.connect(self._cell_clicked)
        layout.addWidget(self.table)
        bottom = QHBoxLayout()
        refresh = QPushButton("Refrescar")
        refresh.setIcon(icon("view-refresh"))
        restart_all = QPushButton("Reiniciar todos")
        restart_all.setIcon(icon("view-refresh"))
        errors = QPushButton("Ver errores recientes")
        errors.setIcon(icon("dialog-warning"))
        settings = QToolButton()
        settings.setIcon(icon("settings-configure", "preferences-system"))
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
        self.services = load_services(
            Path(self.config.systemd_user_dir),
            self.config.services,
            self.config.ignored_services,
        )
        self.refresh()

    def refresh(self) -> None:
        self.cache = CacheManager(Path(self.config.rclone_cache_dir))
        self.logs.logs_dir = Path(self.config.logs_dir).expanduser()
        self.activity.activity_window_seconds = self.config.activity_window_seconds
        for service in self.services:
            service.active_state, service.sub_state = self.systemd.show_state(service.name)
            service.cache_path = self.cache.cache_path_for(service)
            info = self.cache.inspect(service.cache_path)
            service.cache_size = info.size
            service.cache_files = info.files
            service.cache_mtime = info.mtime
            self.logs.sync_service_errors(service, self._last_error_clear_time(service))
            history_errors = self.logs.history_errors_for_service(service)
            service.recent_errors = len(history_errors)
            service.last_error = history_errors[-1] if history_errors else None
            service.recent_error = bool(history_errors)
            if service.recent_error:
                service.activity = "error"
                service.activity_source = "logs"
            else:
                self._update_service_activity(service)
        self._populate_table()
        if self.tray_controller is not None:
            self.tray_controller.update_services(self.services)

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        for row, service in enumerate(self.services):
            self.table.insertRow(row)
            remote = QTableWidgetItem(service.display_name)
            if service.remote:
                remote.setToolTip(service.remote)
            self.table.setItem(row, 0, remote)
            status = QTableWidgetItem(STATUS_LABELS.get(service.active_state, service.active_state))
            status.setToolTip("Clic para acciones de estado")
            self.table.setItem(row, 1, status)
            activity = QLabel(self._activity_label(service.activity))
            activity.setToolTip(ACTIVITY_LABELS.get(service.activity, service.activity))
            self.table.setCellWidget(row, 2, activity)
            api = QTableWidgetItem(self._rc_status_label(service))
            api.setToolTip(self._rc_status_tooltip(service))
            self.table.setItem(row, 3, api)
            mount = QTableWidgetItem(str(service.mount_point or "-"))
            if service.mount_point:
                mount.setToolTip(str(service.mount_point))
            self.table.setItem(row, 4, mount)
            cache_item = QTableWidgetItem(human_size(service.cache_size))
            if service.cache_mtime:
                cache_item.setToolTip(
                    f"{service.cache_files} archivos, modificado {dt.datetime.fromtimestamp(service.cache_mtime):%Y-%m-%d %H:%M}"
                )
            self.table.setItem(row, 5, cache_item)
            self.table.setItem(row, 6, QTableWidgetItem(str(service.recent_errors)))
            actions = QPushButton()
            actions.setIcon(icon("view-more-vertical", "open-menu-symbolic", "application-menu"))
            actions.setToolTip("Más opciones")
            actions.setFixedSize(28, 28)
            actions.clicked.connect(lambda _, s=service, a=actions: self.show_service_menu(s, a))
            self.table.setCellWidget(row, 7, actions)
        self._resize_table_columns()
        if not self._initial_size_applied:
            self._resize_initial_window_to_content()
            self._initial_size_applied = True

    def _resize_table_columns(self) -> None:
        self.table.resizeColumnsToContents()
        caps = [190, 130, 170, 140, 360, 140, 90, 46]
        minimums = [120, 100, 120, 110, 220, 120, 70, 42]
        for column, cap in enumerate(caps):
            width = max(minimums[column], min(self.table.columnWidth(column), cap))
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

    def _resize_initial_window_to_content(self) -> None:
        table_width = sum(self.table.columnWidth(column) for column in range(self.table.columnCount()))
        desired_width = max(860, min(table_width + 80, 1080))
        desired_height = 560 if len(self.services) <= 8 else 640
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            desired_width = min(desired_width, int(available.width() * 0.9))
            desired_height = min(desired_height, int(available.height() * 0.85))
        self.resize(desired_width, desired_height)

    def _cell_clicked(self, row: int, column: int) -> None:
        if row < 0 or row >= len(self.services):
            return
        service = self.services[row]
        if column == 1:
            self.show_status_menu(service)
        elif column == 2:
            self.show_activity(service)
        elif column == 5:
            self.show_cache(service)
        elif column == 6:
            self.show_errors(service)

    def show_service_menu(self, service: RcloneService, anchor: QWidget | None = None) -> None:
        menu = self._service_menu(service)
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft()) if anchor else QCursor.pos()
        menu.exec(pos)

    def show_status_menu(self, service: RcloneService, anchor: QWidget | None = None) -> None:
        menu = self._status_menu(service)
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft()) if anchor else QCursor.pos()
        menu.exec(pos)

    def _status_menu(self, service: RcloneService) -> QMenu:
        menu = QMenu(self)
        menu.addAction(icon("media-playback-start"), "Iniciar", lambda: self._run_service_action("Iniciar", self.systemd.start(service.name)))
        menu.addAction(icon("media-playback-stop"), "Detener", lambda: self._run_service_action("Detener", self.systemd.stop(service.name)))
        menu.addAction(icon("view-refresh"), "Reiniciar", lambda: self._run_service_action("Reiniciar", self.systemd.restart(service.name)))
        menu.addAction(icon("dialog-information"), "Ver estado systemd", lambda: self.show_text("Estado systemd", self.systemd.status(service.name).stdout))
        return menu

    def _service_menu(self, service: RcloneService) -> QMenu:
        menu = QMenu(self)
        menu.addAction(icon("media-playback-start"), "Iniciar", lambda: self._run_service_action("Iniciar", self.systemd.start(service.name)))
        menu.addAction(icon("media-playback-stop"), "Detener", lambda: self._run_service_action("Detener", self.systemd.stop(service.name)))
        menu.addAction(icon("view-refresh"), "Reiniciar", lambda: self._run_service_action("Reiniciar", self.systemd.restart(service.name)))
        menu.addAction(icon("dialog-information"), "Ver estado", lambda: self.show_text("Estado systemd", self.systemd.status(service.name).stdout))
        menu.addSeparator()
        menu.addAction(icon("folder-open"), "Abrir ubicación", lambda: self.open_mountpoint(service))
        menu.addAction(icon("dialog-information"), "Ver actividad", lambda: self.show_activity(service))
        menu.addAction(icon("folder-download", "folder"), "Ver archivos locales", lambda: self.show_cache(service))
        menu.addAction(icon("text-x-log", "text-x-generic"), "Ver logs", lambda: self.show_logs(service))
        menu.addAction(icon("dialog-warning"), "Ver errores", lambda: self.show_errors(service))
        menu.addAction(icon("document-edit"), "Editar .service", lambda: ServiceEditorDialog(service, self.systemd, self).exec())
        menu.addAction(icon("dialog-ok", "emblem-default"), "Validar .service", lambda: self.validate_service(service))
        menu.addAction(icon("edit-delete", "user-trash"), "Liberar espacio en disco", lambda: self.clean_cache(service))
        menu.addAction(icon("system-run"), "Recargar daemon", lambda: self._run_service_action("daemon-reload", self.systemd.daemon_reload()))
        return menu

    def _activity_label(self, activity: str) -> str:
        frames = {
            "uploading": ["⬆", "⇧", "⬆", "⇧"],
            "downloading": ["⬇", "⇩", "⬇", "⇩"],
            "syncing": ["◐", "◓", "◑", "◒"],
            "cleaning": ["◐", "◓", "◑", "◒"],
        }
        if activity in frames:
            icon = frames[activity][self._activity_frame % len(frames[activity])]
            text = ACTIVITY_LABELS.get(activity, activity).split(" ", 1)[-1]
            return f"{icon} {text}"
        return ACTIVITY_LABELS.get(activity, activity)

    def _advance_activity_animation(self) -> None:
        if not self.services:
            return
        self._activity_frame += 1
        for row, service in enumerate(self.services):
            widget = self.table.cellWidget(row, 2)
            if isinstance(widget, QLabel):
                widget.setText(self._activity_label(service.activity))

    def _update_service_activity(self, service: RcloneService) -> None:
        if service.rc_enabled:
            cached = service.activity_summary
            rc_summary = cached if isinstance(cached, ActivitySummary) and cached.source == "rc" else None
            fallback = self.activity.get_activity_summary(service)
            selected = select_activity_summary(service, rc_summary, fallback)
            service.activity = selected.state
            service.activity_source = selected.source
            service.activity_summary = selected
            self._request_rc_summary(service)
            return
        service.rc_status = "not_configured"
        summary = self.activity.get_activity_summary(service)
        service.activity = summary.state
        service.activity_source = "logs"
        service.activity_summary = summary

    def _request_rc_summary(self, service: RcloneService) -> None:
        if service.name in self._rc_pending:
            return
        self._rc_pending.add(service.name)
        service.rc_status = "checking" if service.rc_status in {"unknown", "not_configured"} else service.rc_status

        def worker() -> tuple[str, ActivitySummary]:
            return service.name, RcloneRcClient(service, timeout=1.0).get_activity_summary()

        future = self._rc_executor.submit(worker)
        future.add_done_callback(self._rc_future_done)

    def _rc_future_done(self, future) -> None:
        try:
            service_name, summary = future.result()
        except Exception as exc:
            service_name = ""
            summary = ActivitySummary(state="unavailable", source="rc", error=str(exc))
        self.rc_summary_ready.emit(service_name, summary)

    def _apply_rc_summary(self, service_name: str, summary: ActivitySummary) -> None:
        self._rc_pending.discard(service_name)
        service = next((item for item in self.services if item.name == service_name), None)
        if service is None or not service.rc_enabled:
            return
        service.rc_last_check = dt.datetime.now().replace(microsecond=0).isoformat()
        if summary.state == "unavailable":
            service.rc_status = "unavailable"
            fallback = self.activity.get_activity_summary(service)
            service.activity = fallback.state
            service.activity_source = "logs"
            service.activity_summary = fallback
        else:
            service.rc_status = "active"
            service.activity = summary.state
            service.activity_source = "rc"
            service.activity_summary = summary
        self._populate_table()
        if self.tray_controller is not None:
            self.tray_controller.update_services(self.services)

    def _rc_status_label(self, service: RcloneService) -> str:
        if service.rc_warning:
            return "⚠️ Inseguro"
        if not service.rc_enabled:
            return "⚪ No configurado"
        if service.rc_status == "active":
            return "🟢 RC activo"
        if service.rc_status in {"checking", "unknown"}:
            return "🟡 Comprobando"
        if service.rc_status == "unavailable":
            return "🟡 No responde"
        return "⚪ No configurado"

    def _rc_status_tooltip(self, service: RcloneService) -> str:
        if not service.rc_enabled:
            return "RC/API no configurado. Se usa actividad estimada desde logs."
        parts = [
            f"URL RC: {service.rc_url or '-'}",
            f"Último chequeo: {service.rc_last_check or '-'}",
            f"Estado: {service.rc_status}",
            f"Fuente actividad: {service.activity_source}",
        ]
        if service.rc_warning:
            parts.append(service.rc_warning)
        if service.rc_auth_enabled:
            parts.append(f"Autenticación: {'configurada' if service.rc_user and service.rc_pass else 'requerida/no detectada'}")
        else:
            parts.append("Autenticación: desactivada por --rc-no-auth")
        return "\n".join(parts)

    def _run_service_action(self, title: str, result) -> None:
        self.refresh()
        QMessageBox.information(self, title, result.stdout or result.stderr or "Comando finalizado.")

    def show_text(self, title: str, text: str, actions=None) -> None:
        TextDialog(title, text or "Sin salida.", self, actions=actions).exec()

    def show_errors(self, service: RcloneService) -> None:
        dialog = ErrorDialog(
            f"Errores - {service.display_name}",
            self._history_errors_text(service),
            self._original_errors_text(service),
            on_clear_history=lambda s=service: self._clear_error_history_from_dialog(s, dialog),
            diagnosis=self.logs.diagnose_service_errors(service, self.logs.original_errors(service)),
            parent=self,
        )
        dialog.exec()

    def validate_service(self, service: RcloneService) -> None:
        result = self.systemd.verify(service.path)
        self.show_text("Validación", result.stdout + result.stderr or "Validación completada sin salida.")

    def show_all_errors(self) -> None:
        chunks = []
        for service in self.services:
            errors = self.logs.original_errors(service)
            if errors:
                chunks.append(
                    f"== {service.name} ==\n" +
                    self.logs.format_grouped_errors(errors, "Sin errores actuales en los logs originales.")
                )
        self.show_text("Errores recientes", "\n\n".join(chunks) or "Sin errores recientes.")

    def show_activity(self, service: RcloneService) -> None:
        if service.rc_enabled and service.activity_source == "rc" and isinstance(service.activity_summary, ActivitySummary):
            self.show_text(f"Actividad - {service.display_name}", self._rc_activity_text(service, service.activity_summary))
            return
        lines = self.activity.relevant_lines(service)
        self.show_text(
            f"Actividad - {service.display_name}",
            "Fuente: logs\nActividad estimada desde logs recientes.\n\n" + ("\n".join(lines) or "No hay líneas de log disponibles."),
        )

    def _rc_activity_text(self, service: RcloneService, summary: ActivitySummary) -> str:
        lines = [
            "Fuente: RC/API",
            f"URL: {service.rc_url or '-'}",
            f"Estado: {summary.state}",
            f"Transferencias activas: {summary.transferring_count}",
            f"Checks activos: {summary.checking_count}",
            f"Velocidad: {human_size(int(summary.speed))}/s",
            f"Bytes transferidos: {human_size(summary.bytes_done)}",
            f"Total: {human_size(summary.bytes_total)}",
            "",
            "Archivos activos:",
        ]
        if not summary.active_files:
            lines.append("Sin transferencias activas.")
            return "\n".join(lines)
        for item in summary.active_files:
            name = item.get("name") or item.get("src") or item.get("dst") or "-"
            operation = item.get("operation") or item.get("direction") or summary.state
            done = item.get("bytes") or item.get("transferred") or 0
            total = item.get("size") or item.get("total") or 0
            speed = item.get("speed") or 0
            percentage = item.get("percentage")
            progress = f"{percentage}%" if percentage is not None else f"{human_size(int(done))} / {human_size(int(total))}"
            lines.append(f"- {name} | {operation} | {progress} | {human_size(int(speed))}/s")
        return "\n".join(lines)

    def show_logs(self, service: RcloneService) -> None:
        lines = self.logs.recent_file_lines(service.log_file, 200)
        self.show_text(
            f"Logs - {service.display_name}",
            "\n".join(lines) or "No hay líneas de log disponibles.",
            actions=[
                ("Abrir archivo de log", "text-x-log", lambda s=service: self.open_log(s)),
                ("Abrir carpeta de logs", "folder", lambda s=service: self.open_logs_folder(s)),
                ("Limpiar log de este servicio", "edit-clear", lambda s=service: self.clean_log_for_service(s)),
            ],
        )

    def open_log(self, service: RcloneService) -> None:
        if service.log_file is None or not service.log_file.exists():
            QMessageBox.warning(self, "Abrir log", f"No existe archivo de log para {service.display_name}.")
            return
        try:
            subprocess.run(["xdg-open", str(service.log_file)], check=False)
        except OSError as exc:
            QMessageBox.warning(self, "Abrir log", f"No se pudo abrir el log:\n{exc}")

    def open_logs_folder(self, service: RcloneService) -> None:
        if service.log_file is None:
            folder = Path(self.config.logs_dir).expanduser()
        else:
            folder = service.log_file.expanduser().parent
        if not folder.exists():
            QMessageBox.warning(self, "Abrir carpeta de logs", f"La carpeta de logs no existe:\n{folder}")
            return
        try:
            subprocess.run(["xdg-open", str(folder)], check=False)
        except OSError as exc:
            QMessageBox.warning(self, "Abrir carpeta de logs", f"No se pudo abrir la carpeta:\n{exc}")

    def open_mountpoint(self, service: RcloneService) -> None:
        if service.mount_point is None:
            QMessageBox.warning(self, "Abrir ubicación", f"No se detectó punto de montaje para {service.display_name}.")
            return
        mountpoint = service.mount_point.expanduser()
        if not mountpoint.exists():
            QMessageBox.warning(self, "Abrir ubicación", f"El punto de montaje no existe:\n{mountpoint}")
            return
        try:
            subprocess.run(["xdg-open", str(mountpoint)], check=False)
        except OSError as exc:
            QMessageBox.warning(self, "Abrir ubicación", f"No se pudo abrir la ubicación:\n{exc}")

    def show_cache(self, service: RcloneService) -> None:
        CacheDialog(service, self.cache, self.clean_cache, self).exec()

    def show_total_cache_size(self) -> None:
        total = sum(service.cache_size or 0 for service in self.services)
        files = sum(service.cache_files or 0 for service in self.services)
        QMessageBox.information(self, "Tamaño total ocupado", f"{human_size(total)} en {files} archivos.")

    def show_total_logs_size(self) -> None:
        total = self.logs.total_logs_size(self.services)
        QMessageBox.information(self, "Tamaño total de logs", human_size(total))

    def clean_cache(self, service: RcloneService) -> None:
        if self.config.confirm_cache_clean:
            answer = QMessageBox.warning(
                self,
                "Confirmar liberación de espacio",
                f"Se detendrá temporalmente {service.name}, se eliminarán sus archivos locales y luego se volverá a iniciar.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            )
            if answer != QMessageBox.StandardButton.Ok:
                return
        service.activity = "cleaning"
        result = self.cache.clear_cache_for_service(service, self.systemd)
        self.refresh()
        self.notifier.notify("Rclone Service Tray", result.stdout or result.stderr, critical=not result.ok)
        QMessageBox.information(self, "Liberar espacio en disco", result.stdout or result.stderr)

    def clean_all_caches(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Liberar espacio en disco",
            "Se detendrán temporalmente todos los montajes rclone, se eliminarán sus archivos locales y luego se volverán a iniciar.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        results = self.cache.clear_all(self.services, self.systemd)
        self.refresh()
        text = "\n".join(f"{name}: {'OK' if result.ok else 'ERROR'} {result.stderr or result.stdout}" for name, result in results)
        self.notifier.notify("Rclone Service Tray", "Liberación de espacio finalizada")
        QMessageBox.information(self, "Resultado", text)

    def clean_all_logs(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Limpiar logs de todos los servicios",
            "Se truncarán los archivos de log configurados para los remotos activos. No se borrarán los archivos.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        results = self.logs.clear_logs_for_services(self.services)
        self.refresh()
        text = "\n".join(f"{name}: {'OK' if result.ok else 'ERROR'} {result.stderr or result.stdout}" for name, result in results)
        QMessageBox.information(self, "Limpiar logs", text or "No hay logs configurados.")

    def clean_log_for_service(self, service: RcloneService) -> None:
        answer = QMessageBox.warning(
            self,
            "Limpiar log",
            "Se vaciará el log local de este servicio. No se afectarán archivos del cloud ni la configuración del montaje.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        result = self.logs.clear_log_for_service(service)
        self.refresh()
        QMessageBox.information(self, "Limpiar log", result.stdout or result.stderr)

    def clean_error_history_for_service(self, service: RcloneService) -> None:
        if not self._confirm_service_error_history_clear():
            return
        self._mark_error_history_cleared(service)
        result = self.logs.clear_error_history_for_service(service)
        self.refresh()
        QMessageBox.information(self, "Limpiar errores", result.stdout or result.stderr)

    def clean_error_history(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Limpiar historial de errores",
            "Se limpiará solo el historial de errores detectados por la app. Los logs originales de rclone no se modificarán.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        self._mark_all_error_history_cleared()
        result = self.logs.clear_error_history()
        self.refresh()
        QMessageBox.information(self, "Limpiar historial de errores", result.stdout or result.stderr)

    def _history_errors_text(self, service: RcloneService) -> str:
        history = self.logs.history_errors_for_service(service)
        return self.logs.format_grouped_errors(history, "No hay errores registrados por la app para este servicio.")

    def _original_errors_text(self, service: RcloneService) -> str:
        errors = self.logs.original_errors(service)
        return self.logs.format_grouped_errors(errors, "No hay errores actuales en los logs originales.")

    def _clear_error_history_from_dialog(self, service: RcloneService, dialog: ErrorDialog) -> None:
        if not self._confirm_service_error_history_clear():
            return
        self._mark_error_history_cleared(service)
        result = self.logs.clear_error_history_for_service(service)
        self.refresh()
        dialog.set_history_text(self._history_errors_text(service))
        dialog.set_original_text(self._original_errors_text(service))
        QMessageBox.information(dialog, "Limpiar errores", result.stdout or result.stderr)

    def _confirm_service_error_history_clear(self) -> bool:
        answer = QMessageBox.warning(
            self,
            "Limpiar errores de este servicio",
            "Se limpiará solo el historial de errores detectados por la app para este servicio. No se modificará el log original de rclone.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
        )
        return answer == QMessageBox.StandardButton.Ok

    def _last_error_clear_time(self, service: RcloneService) -> dt.datetime | None:
        raw = self.config.last_error_clear_time.get(service.name)
        if not raw:
            return None
        try:
            return dt.datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _mark_error_history_cleared(self, service: RcloneService) -> None:
        self.config.last_error_clear_time[service.name] = dt.datetime.now().replace(microsecond=0).isoformat()
        save_config(self.config)
        service.recent_errors = 0
        service.last_error = None
        service.recent_error = False
        if service.active_state != "failed":
            service.activity = self.activity.detect(service)

    def _mark_all_error_history_cleared(self) -> None:
        now = dt.datetime.now().replace(microsecond=0).isoformat()
        for service in self.services:
            self.config.last_error_clear_time[service.name] = now
            service.recent_errors = 0
            service.last_error = None
            service.recent_error = False
            if service.active_state != "failed":
                service.activity = self.activity.detect(service)
        save_config(self.config)

    def set_tray_controller(self, tray_controller) -> None:
        self.tray_controller = tray_controller
        self.tray_controller.update_services(self.services)

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
        dialog.request_clean_all_logs.connect(self.clean_all_logs)
        dialog.request_clean_error_history.connect(self.clean_error_history)
        dialog.request_show_total_cache.connect(self.show_total_cache_size)
        dialog.request_show_total_logs.connect(self.show_total_logs_size)
        dialog.request_restart_all.connect(self.restart_all)
        dialog.request_reload_services.connect(self.reload_services)
        dialog.exec()

    def _settings_changed(self) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.config.theme)
        self.timer.start(self.config.refresh_interval_seconds * 1000)
        self.activity.activity_window_seconds = self.config.activity_window_seconds
        self.reload_services()

    def closeEvent(self, event) -> None:
        if self.config.minimize_to_tray:
            event.ignore()
            self.hide()
        else:
            self._rc_executor.shutdown(wait=False, cancel_futures=True)
            self.quit_requested.emit()
