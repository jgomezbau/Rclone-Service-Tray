from pathlib import Path

from rclonetray.service_parser import parse_service_file


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
