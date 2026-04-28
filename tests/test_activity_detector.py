import datetime as dt
from pathlib import Path

from rclonetray.activity_detector import ActivityDetector
from rclonetray.log_manager import LogManager
from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import CommandResult


NOW = dt.datetime(2026, 4, 28, 13, 31, 24)


class FakeSystemd:
    def journal_warnings(self, service: str, lines: int = 50) -> CommandResult:
        return CommandResult(True, "", "", 0)


def detect_activity(tmp_path: Path, lines: list[str]) -> str:
    log_file = tmp_path / "rclone.log"
    log_file.write_text("\n".join(lines), encoding="utf-8")
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=log_file)
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]
    detector = ActivityDetector(logs, activity_window_seconds=60, now=lambda: NOW)
    return detector.detect(service)


def test_upload_line_from_two_hours_ago_does_not_mark_activity(tmp_path: Path) -> None:
    assert detect_activity(tmp_path, ["2026/04/28 11:31:24 INFO  : file.txt: upload succeeded"]) == "idle"


def test_upload_line_from_twenty_seconds_ago_marks_uploading(tmp_path: Path) -> None:
    assert detect_activity(tmp_path, ["2026/04/28 13:31:04 INFO  : file.txt: upload succeeded"]) == "uploading"


def test_recent_cleaned_with_zero_uploads_marks_idle(tmp_path: Path) -> None:
    assert (
        detect_activity(
            tmp_path,
            ["2026/04/28 13:31:04 INFO  : vfs cache: cleaned: objects 0 in use 0, to upload 0, uploading 0"],
        )
        == "idle"
    )


def test_old_upload_and_recent_cleaned_zero_uploads_marks_idle(tmp_path: Path) -> None:
    assert (
        detect_activity(
            tmp_path,
            [
                "2026/04/28 11:31:24 INFO  : file.txt: upload succeeded",
                "2026/04/28 13:31:04 INFO  : vfs cache: cleaned: objects 0 in use 0, to upload 0, uploading 0",
            ],
        )
        == "idle"
    )
