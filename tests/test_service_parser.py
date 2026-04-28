from pathlib import Path

from rclonetray.service_parser import load_services, parse_service_file


def test_parse_rclone_mount_service(tmp_path: Path) -> None:
    service = tmp_path / "rclone-Google-Drive.service"
    service.write_text(
        """
[Service]
ExecStart=/usr/bin/rclone mount Google-Drive: /home/user/CloudDrives/Google-Drive --vfs-cache-mode full --log-file /home/user/.cache/rclone/google.log --rc --rc-addr 127.0.0.1:5572
""",
        encoding="utf-8",
    )

    parsed = parse_service_file(service)

    assert parsed.name == "rclone-Google-Drive.service"
    assert parsed.remote == "Google-Drive:"
    assert parsed.mount_point == Path("/home/user/CloudDrives/Google-Drive")
    assert parsed.log_file == Path("/home/user/.cache/rclone/google.log")
    assert parsed.flags["--vfs-cache-mode"] == "full"
    assert parsed.flags["--rc"] is True


def test_parse_multiline_exec_start_with_flags_before_remote(tmp_path: Path) -> None:
    service = tmp_path / "rclone-Google-Drive.service"
    service.write_text(
        """
[Service]
ExecStart=/usr/bin/rclone mount \\
    --config=/home/juanbau/.config/rclone/rclone.conf \\
    --vfs-cache-mode full \\
    --vfs-cache-max-size 10G \\
    --vfs-cache-max-age 168h \\
    --dir-cache-time 168h \\
    --poll-interval 15m \\
    --log-file=/home/juanbau/.local/state/rclone/rclone-google-drive.log \\
    --allow-other \\
    Google-Drive: /home/juanbau/CloudDrives/Google-Drive
""",
        encoding="utf-8",
    )

    parsed = parse_service_file(service)

    assert parsed.remote == "Google-Drive:"
    assert parsed.display_name == "Google-Drive"
    assert parsed.mount_point == Path("/home/juanbau/CloudDrives/Google-Drive")
    assert parsed.log_file == Path("/home/juanbau/.local/state/rclone/rclone-google-drive.log")
    assert parsed.flags["--config"] == "/home/juanbau/.config/rclone/rclone.conf"
    assert parsed.flags["--vfs-cache-mode"] == "full"
    assert parsed.flags["--allow-other"] is True


def test_parse_space_separated_log_file_and_boolean_flags(tmp_path: Path) -> None:
    service = tmp_path / "rclone-OneDrive-Personal.service"
    service.write_text(
        """
[Service]
ExecStart=/usr/bin/rclone mount --config /home/user/.config/rclone/rclone.conf --rc --rc-no-auth --rc-addr 127.0.0.1:5572 --log-file /home/user/.cache/rclone/onedrive.log OneDrive-Personal: /home/user/CloudDrives/OneDrive-Personal
""",
        encoding="utf-8",
    )

    parsed = parse_service_file(service)

    assert parsed.remote == "OneDrive-Personal:"
    assert parsed.mount_point == Path("/home/user/CloudDrives/OneDrive-Personal")
    assert parsed.log_file == Path("/home/user/.cache/rclone/onedrive.log")
    assert parsed.flags["--config"] == "/home/user/.config/rclone/rclone.conf"
    assert parsed.flags["--rc"] is True
    assert parsed.flags["--rc-no-auth"] is True
    assert parsed.flags["--rc-addr"] == "127.0.0.1:5572"


def test_load_services_excludes_ignored_services(tmp_path: Path) -> None:
    systemd_dir = tmp_path / "systemd"
    systemd_dir.mkdir()
    active = systemd_dir / "rclone-Active.service"
    ignored = systemd_dir / "rclone-Test.service"
    active.write_text("[Service]\nExecStart=/usr/bin/rclone mount Active: /mnt/active\n", encoding="utf-8")
    ignored.write_text("[Service]\nExecStart=/usr/bin/rclone mount Test: /mnt/test\n", encoding="utf-8")

    services = load_services(systemd_dir, [], ["rclone-Test.service"])

    assert [service.name for service in services] == ["rclone-Active.service"]
