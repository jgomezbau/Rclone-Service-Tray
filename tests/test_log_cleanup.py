import datetime as dt
from pathlib import Path

from rclonetray.log_manager import LogManager
from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import CommandResult


class FakeSystemd:
    def journal_warnings(self, service: str, lines: int = 50) -> CommandResult:
        return CommandResult(True, "", "", 0)


def test_clear_log_truncates_safe_log_file(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    log_file = logs_dir / "rclone.log"
    log_file.parent.mkdir()
    log_file.write_text("existing log\n", encoding="utf-8")
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=log_file)
    logs = LogManager(FakeSystemd(), logs_dir=logs_dir)  # type: ignore[arg-type]

    result = logs.clear_log_for_service(service)

    assert result.ok
    assert log_file.exists()
    assert log_file.read_text(encoding="utf-8") == ""


def test_clear_log_rejects_path_outside_safe_logs_dir(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    unsafe_log = tmp_path / "other" / "rclone.log"
    unsafe_log.parent.mkdir()
    unsafe_log.write_text("do not touch\n", encoding="utf-8")
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=unsafe_log)
    logs = LogManager(FakeSystemd(), logs_dir=logs_dir)  # type: ignore[arg-type]

    result = logs.clear_log_for_service(service)

    assert not result.ok
    assert unsafe_log.read_text(encoding="utf-8") == "do not touch\n"


def test_clear_log_requires_existing_file(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    missing_log = logs_dir / "missing.log"
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=missing_log)
    logs = LogManager(FakeSystemd(), logs_dir=logs_dir)  # type: ignore[arg-type]

    result = logs.clear_log_for_service(service)

    assert not result.ok
    assert not missing_log.exists()


def test_clear_error_history_for_service_keeps_other_services(tmp_path: Path) -> None:
    history = tmp_path / "config" / "errors.jsonl"
    history.parent.mkdir()
    history.write_text(
        '{"service": "rclone-One.service", "line": "one"}\n'
        '{"service": "rclone-Two.service", "line": "two"}\n',
        encoding="utf-8",
    )
    service = RcloneService(name="rclone-One.service", path=tmp_path / "rclone-One.service")
    logs = LogManager(FakeSystemd(), logs_dir=tmp_path / "logs", error_history_path=history)  # type: ignore[arg-type]

    result = logs.clear_error_history_for_service(service)

    assert result.ok
    assert history.read_text(encoding="utf-8") == '{"service": "rclone-Two.service", "line": "two"}\n'


def test_clear_error_history_for_service_suppresses_old_detected_lines(tmp_path: Path) -> None:
    history = tmp_path / "config" / "errors.jsonl"
    history.parent.mkdir()
    history.write_text('{"service": "rclone-One.service", "line": "old error"}\n', encoding="utf-8")
    service = RcloneService(name="rclone-One.service", path=tmp_path / "rclone-One.service")
    logs = LogManager(FakeSystemd(), logs_dir=tmp_path / "logs", error_history_path=history)  # type: ignore[arg-type]

    result = logs.clear_error_history_for_service(service)
    logs.record_detected_errors(service, ["old error"])

    assert result.ok
    assert history.read_text(encoding="utf-8") == ""


def test_total_logs_size_includes_service_logs_and_error_history(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    log_file = logs_dir / "rclone.log"
    log_file.write_text("12345", encoding="utf-8")
    history = tmp_path / "config" / "errors.jsonl"
    history.parent.mkdir()
    history.write_text("123", encoding="utf-8")
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=log_file)
    logs = LogManager(FakeSystemd(), logs_dir=logs_dir, error_history_path=history)  # type: ignore[arg-type]

    assert logs.total_logs_size([service]) == 8


def test_history_errors_for_service_reads_only_service_entries(tmp_path: Path) -> None:
    history = tmp_path / "config" / "errors.jsonl"
    history.parent.mkdir()
    history.write_text(
        '{"service": "rclone-One.service", "line": "error one"}\n'
        '{"service": "rclone-Two.service", "line": "error two"}\n'
        '{"service": "rclone-One.service", "line": "error three"}\n',
        encoding="utf-8",
    )
    service = RcloneService(name="rclone-One.service", path=tmp_path / "rclone-One.service")
    logs = LogManager(FakeSystemd(), logs_dir=tmp_path / "logs", error_history_path=history)  # type: ignore[arg-type]

    assert logs.history_errors_for_service(service) == ["error one", "error three"]


def test_sync_service_errors_ignores_old_log_errors_after_clear_time(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    log_file = logs_dir / "rclone.log"
    log_file.write_text("2026/04/28 14:00:00 ERROR : old error\n", encoding="utf-8")
    history = tmp_path / "config" / "errors.jsonl"
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=log_file)
    logs = LogManager(FakeSystemd(), logs_dir=logs_dir, error_history_path=history)  # type: ignore[arg-type]

    logs.sync_service_errors(service, cleared_after=dt.datetime(2026, 4, 28, 14, 45, 0))

    assert logs.error_count(service) == 0
    assert logs.history_errors_for_service(service) == []


def test_sync_service_errors_records_new_log_errors_after_clear_time(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    log_file = logs_dir / "rclone.log"
    log_file.write_text("2026/04/28 15:00:00 ERROR : new error\n", encoding="utf-8")
    history = tmp_path / "config" / "errors.jsonl"
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=log_file)
    logs = LogManager(FakeSystemd(), logs_dir=logs_dir, error_history_path=history)  # type: ignore[arg-type]

    logs.sync_service_errors(service, cleared_after=dt.datetime(2026, 4, 28, 14, 45, 0))

    assert logs.error_count(service) == 1
    assert logs.history_errors_for_service(service) == ["2026/04/28 15:00:00 ERROR : new error"]
