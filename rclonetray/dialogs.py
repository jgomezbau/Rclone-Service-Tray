from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rclonetray.cache_manager import CacheManager, human_size
from rclonetray.icons import icon
from rclonetray.log_manager import ErrorDiagnosis
from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import SystemdManager


class TextDialog(QDialog):
    def __init__(self, title: str, text: str, parent=None, actions: list[tuple[str, str, Callable[[], None]]] | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 520)
        layout = QVBoxLayout(self)
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(text)
        layout.addWidget(editor)
        if actions:
            action_row = QHBoxLayout()
            for label, icon_name, callback in actions:
                button = QPushButton(label)
                button.setIcon(icon(icon_name))
                button.clicked.connect(lambda _checked=False, cb=callback: cb())
                action_row.addWidget(button)
            action_row.addStretch()
            layout.addLayout(action_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ErrorDialog(QDialog):
    def __init__(
        self,
        title: str,
        history_text: str,
        original_text: str,
        on_clear_history: Callable[[], None],
        diagnosis: ErrorDiagnosis | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.on_clear_history = on_clear_history
        self.setWindowTitle(title)
        self.resize(860, 560)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        self.history_editor = self._make_editor(history_text)
        self.original_editor = self._make_editor(original_text)
        tabs.addTab(self._wrap_editor(self.history_editor), "Historial detectado")
        tabs.addTab(self._wrap_editor(self.original_editor), "Logs originales")
        layout.addWidget(tabs)

        if diagnosis is not None:
            diagnosis_label = QLabel(
                diagnosis.summary + "\n\n" + "\n".join(diagnosis.commands)
            )
            diagnosis_label.setWordWrap(True)
            layout.addWidget(diagnosis_label)

        note = QLabel(
            "Los logs originales de rclone no se modifican desde esta acción. "
            "Para vaciar el log original, use Ver logs -> Limpiar log de este servicio."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        actions = QHBoxLayout()
        clear_button = QPushButton("Limpiar errores de este servicio")
        clear_button.setIcon(icon("edit-clear"))
        clear_button.clicked.connect(self._clear_history)
        actions.addWidget(clear_button)
        actions.addStretch()
        layout.addLayout(actions)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_history_text(self, text: str) -> None:
        self.history_editor.setPlainText(text)

    def set_original_text(self, text: str) -> None:
        self.original_editor.setPlainText(text)

    def _clear_history(self) -> None:
        self.on_clear_history()

    @staticmethod
    def _make_editor(text: str) -> QTextEdit:
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(text)
        return editor

    @staticmethod
    def _wrap_editor(editor: QTextEdit) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(editor)
        return widget


class CacheDialog(QDialog):
    def __init__(self, service: RcloneService, cache: CacheManager, on_clean, parent=None):
        super().__init__(parent)
        self.service = service
        self.cache = cache
        self.on_clean = on_clean
        self.setWindowTitle(f"Archivos locales - {service.display_name}")
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        path = service.cache_path or cache.cache_path_for(service)
        layout.addWidget(QLabel(str(path)))
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Archivo", "Tamaño", "Última modificación", "Ruta local", "Acción"])
        for row, (file_path, size, mtime) in enumerate(cache.list_files(path)):
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(file_path.name))
            table.setItem(row, 1, QTableWidgetItem(human_size(size)))
            table.setItem(row, 2, QTableWidgetItem(dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")))
            table.setItem(row, 3, QTableWidgetItem(str(file_path)))
            open_file = QPushButton()
            open_file.setIcon(icon("document-open", "text-x-generic"))
            open_file.setToolTip("Abrir archivo")
            open_file.setFixedSize(28, 28)
            open_file.clicked.connect(lambda _, p=file_path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
            table.setCellWidget(row, 4, open_file)
        table.resizeColumnsToContents()
        layout.addWidget(table)
        actions = QHBoxLayout()
        open_button = QPushButton("Abrir ubicación")
        open_button.setIcon(icon("folder-open"))
        clean_button = QPushButton("Liberar espacio en disco")
        clean_button.setIcon(icon("edit-delete", "user-trash"))
        clean_button.setToolTip("Eliminar archivos locales de este remoto")
        close_button = QPushButton("Cerrar")
        close_button.setIcon(icon("window-close", "dialog-close"))
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))) if path.exists() else None)
        clean_button.clicked.connect(lambda: self.on_clean(service))
        close_button.clicked.connect(self.reject)
        actions.addWidget(open_button)
        actions.addWidget(clean_button)
        actions.addStretch()
        actions.addWidget(close_button)
        layout.addLayout(actions)


class ServiceEditorDialog(QDialog):
    def __init__(self, service: RcloneService, systemd: SystemdManager, parent=None):
        super().__init__(parent)
        self.service = service
        self.systemd = systemd
        self.setWindowTitle(f"Editar {service.name}")
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(str(service.path)))
        self.editor = QTextEdit()
        self.editor.setPlainText(service.path.read_text(encoding="utf-8", errors="replace"))
        layout.addWidget(self.editor)
        actions = QHBoxLayout()
        save = QPushButton("Guardar")
        save.setIcon(icon("document-save"))
        validate = QPushButton("Validar")
        validate.setIcon(icon("dialog-ok", "emblem-default"))
        reload_button = QPushButton("daemon-reload")
        reload_button.setIcon(icon("system-run"))
        restart = QPushButton("Reiniciar servicio")
        restart.setIcon(icon("view-refresh"))
        close = QPushButton("Cerrar")
        close.setIcon(icon("window-close", "dialog-close"))
        save.clicked.connect(self.save)
        validate.clicked.connect(self.validate)
        reload_button.clicked.connect(self.daemon_reload)
        restart.clicked.connect(self.restart)
        close.clicked.connect(self.reject)
        for button in [save, validate, reload_button, restart]:
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)

    def save(self) -> None:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.service.path.with_name(f"{self.service.path.name}.bak.{stamp}")
        shutil.copy2(self.service.path, backup)
        self.service.path.write_text(self.editor.toPlainText(), encoding="utf-8")
        result = self.systemd.verify(self.service.path)
        message = result.stdout or result.stderr or "Validación completada sin salida."
        QMessageBox.information(self, "Guardado", f"Backup: {backup}\n\n{message}")

    def validate(self) -> None:
        result = self.systemd.verify(self.service.path)
        TextDialog("Validación systemd", result.stdout + result.stderr, self).exec()

    def daemon_reload(self) -> None:
        result = self.systemd.daemon_reload()
        QMessageBox.information(self, "daemon-reload", result.stdout or result.stderr or "Comando finalizado.")

    def restart(self) -> None:
        result = self.systemd.restart(self.service.name)
        QMessageBox.information(self, "Reiniciar servicio", result.stdout or result.stderr or "Comando finalizado.")


def pick_service_file(parent=None) -> Path | None:
    filename, _ = QFileDialog.getOpenFileName(parent, "Seleccionar .service", str(Path.home()), "Systemd service (*.service)")
    return Path(filename) if filename else None
