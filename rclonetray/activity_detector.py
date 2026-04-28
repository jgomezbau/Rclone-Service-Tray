from __future__ import annotations

import re

from rclonetray.log_manager import LogManager
from rclonetray.service_model import RcloneService


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("error", re.compile(r"ERROR|failed|transport endpoint is not connected", re.I)),
    ("downloading", re.compile(r"download|Downloaded|Transferred.*\/", re.I)),
    ("uploading", re.compile(r"upload|Copied|copying", re.I)),
    ("reading", re.compile(r"read|reading", re.I)),
    ("writing", re.compile(r"write|writing", re.I)),
    ("syncing", re.compile(r"sync|transferred|checking", re.I)),
]


class ActivityDetector:
    def __init__(self, logs: LogManager):
        self.logs = logs

    def detect(self, service: RcloneService) -> str:
        lines = self.logs.recent_file_lines(service.log_file, 80)
        text = "\n".join(lines[-40:])
        for name, pattern in PATTERNS:
            if pattern.search(text):
                return name
        return "idle"

    def relevant_lines(self, service: RcloneService) -> list[str]:
        lines = self.logs.recent_file_lines(service.log_file, 120)
        return lines[-80:]
