from pathlib import Path

from rclonetray.log_manager import ErrorEntry, LogManager, classify_error_entry, classify_error_line, is_error_line, normalize_error_message
from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import CommandResult


class FakeSystemd:
    def journal_warnings(self, service: str, lines: int = 50) -> CommandResult:
        return CommandResult(True, "", "", 0)


class FakeSystemdWithJournal:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout

    def journal_warnings(self, service: str, lines: int = 50) -> CommandResult:
        return CommandResult(True, self.stdout, "", 0)


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


def test_dropbox_local_dns_lookup_is_warning() -> None:
    line = (
        '2026/04/30 10:00:00 ERROR : /: Dir.Stat error: Post "https://api.dropboxapi.com/2/files/list_folder": '
        "dial tcp: lookup api.dropboxapi.com on 127.0.0.53:53: server misbehaving"
    )
    entry = classify_error_entry(line, [line])

    assert is_error_line(line)
    assert entry.severity == "warning"
    assert entry.error_type == "DNS local / conectividad temporal"


def test_nextcloud_local_dns_lookup_is_warning() -> None:
    line = (
        '2026/04/30 10:00:00 ERROR : /: Dir.Stat error: couldn\'t list files: Propfind "https://juanbau.duckdns.org:444/remote.php/dav/files/jgomezbau/": '
        "dial tcp: lookup juanbau.duckdns.org on 127.0.0.53:53: server misbehaving"
    )
    entry = classify_error_entry(line, [line])

    assert entry.severity == "warning"
    assert entry.error_type == "DNS local / conectividad temporal"


def test_dir_stat_io_and_start_cursor_dns_errors_group_within_30_seconds() -> None:
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]
    lines = [
        (
            '2026/04/30 10:00:00 ERROR : /: Dir.Stat error: Post "https://api.dropboxapi.com/2/files/list_folder": '
            "dial tcp: lookup api.dropboxapi.com on 127.0.0.53:53: server misbehaving"
        ),
        (
            '2026/04/30 10:00:12 ERROR : /: IO error: Post "https://api.dropboxapi.com/2/files/list_folder": '
            "dial tcp: lookup api.dropboxapi.com on 127.0.0.53:53: server misbehaving"
        ),
        (
            '2026/04/30 10:00:18 INFO  : Dropbox root \'\': Failed to get StartCursor: Post "https://api.dropboxapi.com/2/files/list_folder/get_latest_cursor": '
            "dial tcp: lookup api.dropboxapi.com on 127.0.0.53:53: server misbehaving"
        ),
    ]
    grouped = logs.grouped_errors([classify_error_entry(line, lines) for line in lines])

    assert len(grouped) == 1
    assert grouped[0].severity == "warning"
    assert grouped[0].error_type == "DNS local / conectividad temporal"
    assert grouped[0].message == "No se pudo resolver api.dropboxapi.com"
    assert grouped[0].file == "remote root"
    assert grouped[0].count == 3


def test_failed_start_cursor_dns_is_warning_even_when_info_line() -> None:
    line = (
        '2026/04/30 10:00:00 INFO  : Dropbox root \'\': Failed to get StartCursor: Post "https://api.dropboxapi.com/2/files/list_folder/get_latest_cursor": '
        "dial tcp: lookup api.dropboxapi.com on 127.0.0.53:53: server misbehaving"
    )
    entry = classify_error_entry(line, [line])

    assert is_error_line(line)
    assert entry.severity == "warning"
    assert entry.error_type == "DNS local / conectividad temporal"


def test_repeated_dns_error_more_than_three_times_in_five_minutes_is_critical() -> None:
    lines = [
        (
            f'2026/04/30 10:00:0{index} ERROR : /: IO error: Post "https://api.dropboxapi.com/2/files/list_folder": '
            "dial tcp: lookup api.dropboxapi.com on 127.0.0.53:53: server misbehaving"
        )
        for index in range(4)
    ]

    assert classify_error_line(lines[0], lines) == "critical"


def test_dns_summary_replaces_long_urls_with_host_summary() -> None:
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]
    line = (
        '2026/04/30 10:00:00 ERROR : /: IO error: Propfind "https://juanbau.duckdns.org:444/remote.php/dav/files/jgomezbau/very/long/path": '
        "dial tcp: lookup juanbau.duckdns.org on 127.0.0.53:53: server misbehaving"
    )

    grouped = logs.grouped_errors([classify_error_entry(line, [line])])

    assert grouped[0].message == "No se pudo resolver juanbau.duckdns.org"
    assert "https://juanbau.duckdns.org" not in grouped[0].message


def test_dns_group_includes_contextual_suggestion() -> None:
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]
    line = "2026/04/30 10:00:00 ERROR : /: IO error: dial tcp: lookup api.dropboxapi.com on 127.0.0.53:53: server misbehaving"

    text = logs.format_grouped_errors([classify_error_entry(line, [line])], "empty")

    assert "Revisar VPN, NetworkManager, systemd-resolved o DNS configurado" in text
    assert "Puede ocurrir al cambiar de red" in text


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
    assert grouped[0].error_type == "Archivo temporal de editor"


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


def test_temporary_editor_error_is_warning_without_success() -> None:
    line = "2026/04/28 10:00:00 ERROR : .~cumento sin título.docx: Failed to copy: couldn't list directory: context canceled"

    assert classify_error_line(line, [line]) == "warning"


def test_temporary_editor_warning_is_not_active_history_error(tmp_path: Path) -> None:
    log_file = tmp_path / "rclone.log"
    log_file.write_text(
        "2026/04/28 10:00:00 ERROR : ~$file.docx: Failed to copy: couldn't list directory: context canceled\n",
        encoding="utf-8",
    )
    service = RcloneService(name="rclone-Test.service", path=tmp_path / "rclone-Test.service", log_file=log_file)
    logs = LogManager(FakeSystemd(), logs_dir=tmp_path, error_history_path=tmp_path / "errors.jsonl")  # type: ignore[arg-type]

    logs.sync_service_errors(service)

    entries = logs.history_error_entries_for_service(service)
    assert entries[0].severity == "warning"
    assert entries[0].error_type == "Archivo temporal de editor"
    assert logs.active_history_error_entries_for_service(service) == []


def test_vfs_cache_errors_are_grouped_as_single_warning() -> None:
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]
    entries = [
        "2026/04/28 10:00:00 ERROR : Codice Fiscale e Cellulare.docx: vfs cache: failed to open item: open /home/user/.cache/rclone/vfs/Mega/Codice Fiscale e Cellulare.docx: no such file or directory",
        "2026/04/28 10:00:01 ERROR : Codice Fiscale e Cellulare.docx: Non-out-of-space error encountered during open",
        "2026/04/28 10:00:02 ERROR : Codice Fiscale e Cellulare.docx: open RW handle failed to open cache file: open /home/user/.cache/rclone/vfs/Mega/Codice Fiscale e Cellulare.docx: no such file or directory",
    ]
    grouped = logs.grouped_errors([classify_error_entry(line, entries) for line in entries])

    assert len(grouped) == 1
    assert grouped[0].severity == "warning"
    assert grouped[0].error_type == "VFS cache local inconsistente"
    assert grouped[0].message == "VFS cache local inconsistente al abrir archivo"
    assert grouped[0].file == "Codice Fiscale e Cellulare.docx"
    assert grouped[0].count == 3
    assert "Non-out-of-space error encountered during open" in grouped[0].detail


def test_repeated_vfs_cache_error_is_critical() -> None:
    lines = [
        f"2026/04/28 10:00:0{index} ERROR : file.docx: vfs cache: failed to open item: open /home/user/.cache/rclone/vfs/Mega/file.docx: no such file or directory"
        for index in range(4)
    ]

    assert classify_error_line(lines[0], lines) == "critical"


def test_onedrive_slow_upload_single_error_is_transient_warning(tmp_path: Path) -> None:
    log_file = tmp_path / "rclone.log"
    line = "2026/04/28 10:00:00 ERROR : big-file.zip: upload chunks may be taking too long"
    log_file.write_text(line + "\n", encoding="utf-8")
    service = RcloneService(name="rclone-OneDrive.service", path=tmp_path / "rclone-OneDrive.service", log_file=log_file)
    logs = LogManager(FakeSystemd(), logs_dir=tmp_path, error_history_path=tmp_path / "errors.jsonl")  # type: ignore[arg-type]

    logs.sync_service_errors(service)

    entries = logs.history_error_entries_for_service(service)
    assert is_error_line(line)
    assert entries[0].severity == "warning"
    assert entries[0].error_type == "Advertencia transitoria: upload interrumpido o demorado"
    assert logs.active_history_error_entries_for_service(service) == []


def test_repeated_onedrive_slow_upload_error_is_critical() -> None:
    lines = [
        f"2026/04/28 10:0{index}:00 ERROR : big-file.zip: upload chunks may be taking too long"
        for index in range(4)
    ]

    assert classify_error_line(lines[0], lines) == "critical"


def test_onedrive_slow_upload_group_includes_suggestion() -> None:
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]
    line = "2026/04/28 10:00:00 ERROR : big-file.zip: upload chunks may be taking too long"

    text = logs.format_grouped_errors([classify_error_entry(line, [line])], "empty")

    assert "Tipo: Advertencia transitoria: upload interrumpido o demorado" in text
    assert "Puede ocurrir si el equipo se suspendió durante una subida" in text


def test_onedrive_slow_upload_duplicate_sources_generate_one_warning_event(tmp_path: Path) -> None:
    line = (
        "2026/04/28 10:00:00 ERROR : big-file.zip: upload chunks may be taking too long - "
        "try reducing --onedrive-chunk-size or decreasing --transfers"
    )
    log_file = tmp_path / "rclone.log"
    log_file.write_text(line + "\n", encoding="utf-8")
    service = RcloneService(name="rclone-OneDrive.service", path=tmp_path / "rclone-OneDrive.service", log_file=log_file)
    logs = LogManager(FakeSystemdWithJournal(line), logs_dir=tmp_path, error_history_path=tmp_path / "errors.jsonl")  # type: ignore[arg-type]

    logs.sync_service_errors(service)
    entries = logs.history_error_entries_for_service(service)
    grouped = logs.grouped_errors(entries)

    assert len(entries) == 1
    assert len(grouped) == 1
    assert entries[0].severity == "warning"
    assert entries[0].error_type == "Advertencia transitoria: upload interrumpido o demorado"
    assert not any(entry.severity == "critical" and entry.line == line for entry in entries)


def test_onedrive_slow_upload_group_dedupes_legacy_critical_entry() -> None:
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]
    line = "2026/04/28 10:00:00 ERROR : big-file.zip: upload chunks may be taking too long"

    grouped = logs.grouped_errors([ErrorEntry(line, severity="critical"), classify_error_entry(line, [line])])

    assert len(grouped) == 1
    assert grouped[0].severity == "warning"
    assert grouped[0].error_type == "Advertencia transitoria: upload interrumpido o demorado"


def test_failed_to_copy_put_context_canceled_is_warning_with_normalized_url() -> None:
    line = '2026/04/28 10:00:00 ERROR : file.txt: Failed to copy: Put "https://graph.microsoft.com/v1.0/long/path": context canceled'

    entry = classify_error_entry(line, [line])

    assert entry.severity == "warning"
    assert entry.error_type == "Operación cancelada por el usuario / copia interrumpida"
    assert summarize_for_test(line) == 'Failed to copy: Put "<url>": context canceled'


def test_failed_to_copy_post_context_canceled_is_warning_with_normalized_url() -> None:
    line = '2026/04/28 10:00:00 ERROR : file.txt: Failed to copy: Post "https://graph.microsoft.com/v1.0/long/path": context canceled'

    entry = classify_error_entry(line, [line])

    assert entry.severity == "warning"
    assert entry.error_type == "Operación cancelada por el usuario / copia interrumpida"
    assert summarize_for_test(line) == 'Failed to copy: Post "<url>": context canceled'


def test_dir_remove_not_empty_near_context_canceled_is_warning() -> None:
    lines = [
        '2026/04/28 10:00:00 ERROR : file.txt: Failed to copy: Put "https://example.com/path": context canceled',
        "2026/04/28 10:00:20 ERROR : folder: Dir.Remove not empty",
    ]

    entry = classify_error_entry(lines[1], lines)

    assert entry.severity == "warning"
    assert entry.error_type == "Limpieza posterior a cancelación"


def test_io_error_directory_not_empty_near_context_canceled_is_warning() -> None:
    lines = [
        '2026/04/28 10:00:00 ERROR : file.txt: Failed to copy: Post "https://example.com/path": context canceled',
        "2026/04/28 10:00:30 ERROR : folder: IO error: directory not empty",
    ]

    entry = classify_error_entry(lines[1], lines)

    assert entry.severity == "warning"
    assert entry.error_type == "Limpieza posterior a cancelación"


def test_multiple_context_canceled_entries_are_grouped_in_same_window() -> None:
    logs = LogManager(FakeSystemd())  # type: ignore[arg-type]
    lines = [
        f'2026/04/28 10:00:0{index} ERROR : file{index}.txt: Failed to copy: Put "https://example.com/{index}": context canceled'
        for index in range(3)
    ]

    grouped = logs.grouped_errors([classify_error_entry(line, lines) for line in lines])

    assert len(grouped) == 1
    assert grouped[0].severity == "warning"
    assert grouped[0].error_type == "Operación cancelada por el usuario / copia interrumpida"
    assert grouped[0].message == "Transferencias canceladas por el usuario"
    assert grouped[0].count == 3
    assert "file0.txt" in grouped[0].detail
    assert "file2.txt" in grouped[0].detail


def test_dir_remove_not_empty_without_nearby_cancelation_is_critical() -> None:
    line = "2026/04/28 10:00:00 ERROR : folder: Dir.Remove not empty"

    entry = classify_error_entry(line, [line])

    assert entry.severity == "critical"
    assert entry.error_type == "Error crítico"


def summarize_for_test(line: str) -> str:
    from rclonetray.log_manager import summarize_error_message

    return summarize_error_message(line)
