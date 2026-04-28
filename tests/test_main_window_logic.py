import datetime as dt
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QApplication = QtWidgets.QApplication
QMessageBox = QtWidgets.QMessageBox

from rclonetray.activity_detector import ActivityDetector
from rclonetray.config import AppConfig
from rclonetray.log_manager import LogManager
from rclonetray.main_window import MainWindow
from rclonetray.rc_client import ActivitySummary
from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import CommandResult


class FakeSystemd:
    def __init__(self) -> None:
        self.restart_calls: list[str] = []
        self.window = None
        self.restart_seen_text: str | None = None
        self.events: list[str] = []
        self.first_restart_transients: list[str | None] | None = None
        self.states: dict[str, tuple[str, str]] = {}

    def journal_warnings(self, service: str, lines: int = 50) -> CommandResult:
        return CommandResult(True, "", "", 0)

    def show_state(self, service: str) -> tuple[str, str]:
        return self.states.get(service, ("active", "running"))

    def restart(self, service: str) -> CommandResult:
        self.events.append(f"restart:{service}")
        self.restart_calls.append(service)
        if self.window is not None:
            item = self.window.table.item(0, 1)
            self.restart_seen_text = item.text() if item is not None else None
            if self.first_restart_transients is None:
                self.first_restart_transients = [item.transient_state for item in self.window.services]
        return CommandResult(True, "restart ok", "", 0)


class FakeTray:
    def __init__(self) -> None:
        self.calls = 0
        self.snapshots = []

    def update_services(self, services) -> None:
        self.calls += 1
        self.snapshots.append(
            [(service.name, service.active_state, service.transient_state, service.recent_error) for service in services]
        )


def app() -> QApplication:
    instance = QApplication.instance()
    return instance if instance is not None else QApplication([])


def make_window(tmp_path: Path, systemd: FakeSystemd) -> MainWindow:
    app()
    config = AppConfig(
        systemd_user_dir=str(tmp_path / "systemd"),
        rclone_cache_dir=str(tmp_path / "cache"),
        logs_dir=str(tmp_path / "logs"),
        refresh_interval_seconds=60,
    )
    window = MainWindow(config, systemd, notifier=None)  # type: ignore[arg-type]
    window.timer.stop()
    window.activity_timer.stop()
    systemd.window = window
    return window


def make_service(tmp_path: Path, name: str = "rclone-Test.service") -> RcloneService:
    return RcloneService(name=name, path=tmp_path / name)


def test_rc_idle_dominates_recent_upload_logs(tmp_path: Path) -> None:
    log_file = tmp_path / "rclone.log"
    log_file.write_text("2026/04/28 13:31:04 INFO  : file.txt: upload succeeded", encoding="utf-8")
    service = RcloneService(
        name="rclone-Test.service",
        path=tmp_path / "rclone-Test.service",
        log_file=log_file,
        rc_enabled=True,
        rc_status="active",
        activity_summary=ActivitySummary(state="idle", source="rc", transfers_count=0, checking_count=0, speed=0),
    )
    logs = LogManager(FakeSystemd(), logs_dir=tmp_path)  # type: ignore[arg-type]
    window = MainWindow.__new__(MainWindow)
    window.activity = ActivityDetector(logs, activity_window_seconds=60, now=lambda: dt.datetime(2026, 4, 28, 13, 31, 24))
    window._request_rc_summary = lambda _service: None

    window._update_service_activity(service)

    assert service.activity == "idle"
    assert service.activity_source == "rc"


def test_old_error_before_last_clear_time_does_not_mark_visual_error(tmp_path: Path) -> None:
    history = tmp_path / "errors.jsonl"
    history.write_text(
        '{"service": "rclone-Test.service", "line": "2026/04/28 10:00:00 ERROR : old error"}\n',
        encoding="utf-8",
    )
    service = make_service(tmp_path)
    logs = LogManager(FakeSystemd(), logs_dir=tmp_path, error_history_path=history)  # type: ignore[arg-type]
    window = MainWindow.__new__(MainWindow)
    window.logs = logs
    window.config = AppConfig(last_error_clear_time={service.name: "2026-04-28T11:00:00"})

    window._refresh_error_state(service)

    assert service.error_count_history == 0
    assert not service.recent_error


def test_restart_service_sets_transient_and_processes_events_before_systemctl(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    systemd = FakeSystemd()
    service = make_service(tmp_path)
    systemd.states[service.name] = ("active", "running")
    window = make_window(tmp_path, systemd)
    tray = FakeTray()
    window.set_tray_controller(tray)
    window.services = [service]
    window._populate_table()
    original_set_transient = window._set_transient_state

    def record_set_transient(target, state, message):
        systemd.events.append(f"set:{state}")
        original_set_transient(target, state, message)

    monkeypatch.setattr(window, "_set_transient_state", record_set_transient)
    monkeypatch.setattr("rclonetray.main_window.QApplication.processEvents", lambda: systemd.events.append("process"))

    window.restart_service(service)

    assert systemd.restart_seen_text == "🟡 Reiniciando"
    assert systemd.events.index("set:restarting") < systemd.events.index(f"restart:{service.name}")
    assert systemd.events.index("process") < systemd.events.index(f"restart:{service.name}")
    assert window.table.item(0, 1).text() == "🟢 Activo"
    assert tray.calls >= 2


def test_restart_all_marks_all_services_restarting_before_any_restart(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    process_events = []
    monkeypatch.setattr("rclonetray.main_window.QApplication.processEvents", lambda: process_events.append("process"))
    systemd = FakeSystemd()
    one = make_service(tmp_path, "rclone-One.service")
    two = make_service(tmp_path, "rclone-Two.service")
    systemd.states = {one.name: ("active", "running"), two.name: ("active", "running")}
    window = make_window(tmp_path, systemd)
    tray = FakeTray()
    window.set_tray_controller(tray)
    window.services = [one, two]
    window._populate_table()

    window.restart_all()

    assert systemd.restart_calls == [one.name, two.name]
    assert systemd.first_restart_transients == ["restarting", "restarting"]
    assert process_events
    assert [service.active_state for service in window.services] == ["active", "active"]
    assert tray.calls >= 3


def test_restart_updates_tray_before_and_after_restart(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr("rclonetray.main_window.QApplication.processEvents", lambda: None)
    systemd = FakeSystemd()
    service = make_service(tmp_path)
    systemd.states[service.name] = ("active", "running")
    window = make_window(tmp_path, systemd)
    tray = FakeTray()
    window.set_tray_controller(tray)
    window.services = [service]
    window._populate_table()

    window.restart_service(service)

    assert any(snapshot[0][2] == "restarting" for snapshot in tray.snapshots)
    assert tray.snapshots[-1][0][2] is None


def test_clearing_errors_updates_tray(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("rclonetray.main_window.save_config", lambda _config: None)
    service = make_service(tmp_path)
    window = MainWindow.__new__(MainWindow)
    window.services = [service]
    window.tray_controller = FakeTray()
    window.config = AppConfig()
    window.table = None
    service.active_state = "active"
    service.error_count_history = 1
    service.recent_error = True

    window._refresh_error_state = lambda _service: None
    window._update_service_activity = lambda _service: None
    window._update_service_row = lambda _service: window.tray_controller.update_services(window.services)

    window._mark_error_history_cleared(service)

    assert window.tray_controller.calls == 1
