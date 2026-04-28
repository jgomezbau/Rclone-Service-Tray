from pathlib import Path

from rclonetray.log_manager import LogManager, is_error_line, normalize_error_message
from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import CommandResult


class FakeSystemd:
    def journal_warnings(self, service: str, lines: int = 50) -> CommandResult:
        return CommandResult(True, "", "", 0)


def test_info_vfs_cache_cleaned_is_not_error() -> None:
    assert not is_error_line("2026/04/28 10:00:00 INFO : vfs cache: cleaned: objects 0")


def test_info_upload_succeeded_is_not_error() -> None:
    assert not is_error_line("2026/04/28 10:00:00 INFO : file.txt: upload succeeded")


def test_error_failed_to_upload_is_error() -> None:
    assert is_error_line("2026/04/28 10:00:00 ERROR : file.txt: failed to upload: retry failed")


def test_transport_endpoint_is_not_connected_is_error() -> None:
    assert is_error_line("mount helper error: transport endpoint is not connected")


def test_permission_denied_is_error() -> None:
    assert is_error_line("open /remote/file.txt: permission denied")


def test_recent_errors_ignores_info_activity_lines(tmp_path: Path) -> None:
    log_file = tmp_path / "rclone.log"
    log_file.write_text(
        "\n".join(
            [
                "2026/04/28 10:00:00 INFO : vfs cache: cleaned: objects 0",
                "2026/04/28 10:00:01 INFO : Committing uploads - please wait",
                "2026/04/28 10:00:02 INFO : file.txt: Copied (new)",
                "2026/04/28 10:00:03 INFO : file.txt: upload succeeded",
            ]
        ),
        encoding="utf-8",
    )
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=log_file)
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]

    assert logs.recent_errors(service) == []
    assert logs.error_count(service) == 0


def test_grouped_errors_aggregates_repeated_lines(tmp_path: Path) -> None:
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]
    grouped = logs.grouped_errors(
        [
            "2026/04/28 10:00:00 ERROR : Propfind failed",
            "2026/04/28 10:05:00 ERROR : Propfind failed",
        ]
    )

    assert len(grouped) == 1
    assert grouped[0].message == normalize_error_message("2026/04/28 10:00:00 ERROR : Propfind failed")
    assert grouped[0].count == 2
    assert grouped[0].first_seen == "2026-04-28 10:00:00"
    assert grouped[0].last_seen == "2026-04-28 10:05:00"


def test_webdav_dns_diagnosis_is_suggested() -> None:
    service = RcloneService(
        name="rclone-Nextcloud.service",
        path=Path("/tmp/rclone-Nextcloud.service"),
        exec_start="/usr/bin/rclone mount Nextcloud: /mnt/nextcloud --log-file /tmp/nc.log",
        remote="Nextcloud:",
    )
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]
    diagnosis = logs.diagnose_service_errors(
        service,
        [
            "2026/04/28 10:00:00 ERROR : Propfind https://cloud.example.com/remote.php/dav/files/user: lookup cloud.example.com on 127.0.0.53:53: server misbehaving"
        ],
    )

    assert diagnosis is not None
    assert "WebDAV/Nextcloud" in diagnosis.summary
    assert diagnosis.commands[0] == "resolvectl query cloud.example.com"
    assert diagnosis.commands[1] == "curl -I https://cloud.example.com/remote.php"
    assert diagnosis.commands[2] == "rclone lsf Nextcloud: --max-depth 1 -vv"


def test_temporary_lock_error_followed_by_real_upload_is_resolved_warning(tmp_path: Path) -> None:
    log_file = tmp_path / "rclone.log"
    log_file.write_text(
        "\n".join(
            [
                "2026/04/28 10:00:00 ERROR : CV JJGB/Cartas/.~archivo.docx: Failed to copy: context canceled: Put \"https://cloud.example.com/very/long/url\": context canceled",
                "2026/04/28 10:00:05 INFO  : CV JJGB/Cartas/archivo.docx: upload succeeded",
            ]
        ),
        encoding="utf-8",
    )
    history = tmp_path / "errors.jsonl"
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=log_file)
    logs = LogManager(FakeSystemd(), logs_dir=tmp_path, error_history_path=history)  # type: ignore[arg-type]

    logs.sync_service_errors(service)
    entries = logs.history_error_entries_for_service(service)
    grouped = logs.grouped_errors(entries)

    assert entries[0].severity == "warning_resolved"
    assert grouped[0].message == "Failed to copy: context canceled"
    assert grouped[0].file == "CV JJGB/Cartas/.~archivo.docx"


def test_resolved_temporary_error_is_not_active_history_error(tmp_path: Path) -> None:
    log_file = tmp_path / "rclone.log"
    log_file.write_text(
        "\n".join(
            [
                "2026/04/28 10:00:00 ERROR : folder/.~file.docx: Failed to copy: context canceled",
                "2026/04/28 10:00:01 INFO  : folder/file.docx: upload succeeded",
            ]
        ),
        encoding="utf-8",
    )
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=log_file)
    logs = LogManager(FakeSystemd(), logs_dir=tmp_path, error_history_path=tmp_path / "errors.jsonl")  # type: ignore[arg-type]

    logs.sync_service_errors(service)

    assert logs.history_error_entries_for_service(service)
    assert logs.active_history_error_entries_for_service(service) == []
