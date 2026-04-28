from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RcloneService:
    name: str
    path: Path
    exec_start: str = ""
    remote: str = ""
    mount_point: Path | None = None
    log_file: Path | None = None
    flags: dict[str, str | bool] = field(default_factory=dict)
    active_state: str = "unknown"
    sub_state: str = "unknown"
    transient_state: str | None = None
    transient_message: str | None = None
    transient_until: Any | None = None
    activity: str = "idle"
    cache_path: Path | None = None
    cache_size: int | None = None
    cache_files: int | None = None
    cache_mtime: float | None = None
    recent_errors: int = 0
    last_error: str | None = None
    recent_error: bool = False
    error_count_history: int = 0
    rc_error_count: int = 0
    service_failed: bool = False
    rc_enabled: bool = False
    rc_addr: str | None = None
    rc_url: str | None = None
    rc_auth_enabled: bool = True
    rc_user: str | None = None
    rc_pass: str | None = None
    rc_status: str = "not_configured"
    rc_last_check: str | None = None
    rc_warning: str | None = None
    activity_source: str = "logs"
    activity_summary: Any | None = None

    @property
    def display_name(self) -> str:
        if self.remote:
            return self.remote.rstrip(":")
        base = self.name.removeprefix("rclone-").removesuffix(".service")
        return base

    @property
    def is_active(self) -> bool:
        return self.active_state == "active"

    @property
    def is_webdav_like(self) -> bool:
        text = f"{self.exec_start} {self.remote} {self.display_name}".lower()
        return "webdav" in text or "nextcloud" in text

    @property
    def rc_password_display(self) -> str:
        return "********" if self.rc_pass else ""
