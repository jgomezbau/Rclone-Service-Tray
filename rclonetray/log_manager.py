from __future__ import annotations

import re
from pathlib import Path

from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import SystemdManager


ERROR_RE = re.compile(
    r"(ERROR|Failed|failed|warning|pacer|rateLimitExceeded|unauthenticated|permission denied|transport endpoint is not connected)",
    re.IGNORECASE,
)


class LogManager:
    def __init__(self, systemd: SystemdManager):
        self.systemd = systemd

    def recent_journal_errors(self, service: RcloneService, lines: int = 50) -> list[str]:
        result = self.systemd.journal_warnings(service.name, lines)
        return [line for line in result.stdout.splitlines() if line.strip()]

    def recent_file_lines(self, path: Path | None, lines: int = 80) -> list[str]:
        if not path or not path.exists():
            return []
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                block = min(size, 65536)
                handle.seek(-block, 2)
                data = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return []
        return data.splitlines()[-lines:]

    def recent_errors(self, service: RcloneService, lines: int = 80) -> list[str]:
        entries = self.recent_journal_errors(service, 50)
        entries.extend(line for line in self.recent_file_lines(service.log_file, lines) if ERROR_RE.search(line))
        return entries[-lines:]

    def error_count(self, service: RcloneService) -> int:
        return len(self.recent_errors(service, 80))
