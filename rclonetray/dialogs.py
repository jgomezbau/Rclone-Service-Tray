from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

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
    QTextEdit,
    QVBoxLayout,
)

from rclonetray.cache_manager import CacheManager, human_size
from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import SystemdManager


class TextDialog(QDialog):
    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 520)
        layout = QVBoxLayout(self)
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(text)
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CacheDialog(QDialog):
    def __init__(self, service: RcloneService, cache: CacheManager, on_clean, parent=None):
        super().__init__(parent)
        self.service = service
        self.cache = cache
        self.on_clean = on_clean
        self.setWindowTitle(f"Cache - {service.display_name}")
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        path = service.cache_path or cache.cache_path_for(service)
        layout.addWidget(QLabel(str(path)))
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Archivo", "Tamaño", "Modificado", "Ruta local"])
        for row, (file_path, size, mtime) in enumerate(cache.list_files(path)):
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(file_path.name))
            table.setItem(row, 1, QTableWidgetItem(human_size(size)))
            table.setItem(row, 2, QTableWidgetItem(dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")))
            table.setItem(row, 3, QTableWidgetItem(str(file_path)))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        actions = QHBoxLayout()
        open_button = QPushButton("Abrir ubicación")
        clean_button = QPushButton("Limpiar cache")
        close_button = QPushButton("Cerrar")
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
        validate = QPushButton("Validar")
        reload_button = QPushButton("daemon-reload")
        restart = QPushButton("Reiniciar servicio")
        close = QPushButton("Cerrar")
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
