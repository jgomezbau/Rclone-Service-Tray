from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable

from rclonetray.log_manager import LogManager
from rclonetray.service_model import RcloneService


RCLONE_TS_RE = re.compile(r"^(?P<timestamp>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})\b")
CLEANED_IDLE_RE = re.compile(r"vfs cache: cleaned:.*to upload 0,\s*uploading 0", re.I)
UPLOADING_COUNT_RE = re.compile(r"\buploading\s+([1-9]\d*)\b", re.I)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("downloading", re.compile(r"download|Downloaded|Transferred.*\/", re.I)),
    ("uploading", re.compile(r"upload|Copied|copying", re.I)),
    ("reading", re.compile(r"read|reading", re.I)),
    ("writing", re.compile(r"write|writing", re.I)),
    ("syncing", re.compile(r"sync|transferred|checking", re.I)),
]


class ActivityDetector:
    def __init__(
        self,
        logs: LogManager,
        activity_window_seconds: int = 60,
        now: Callable[[], dt.datetime] | None = None,
    ):
        self.logs = logs
        self.activity_window_seconds = activity_window_seconds
        self._now = now or dt.datetime.now

    def detect(self, service: RcloneService) -> str:
        lines = self.logs.recent_file_lines(service.log_file, 80)
        recent_lines = [line for line in lines[-40:] if self._is_recent(line)]

        activity = "idle"
        has_explicit_activity_signal = False
        for line in recent_lines:
            line_activity = self._activity_for_line(line)
            if line_activity is not None:
                has_explicit_activity_signal = True
                activity = line_activity
        if has_explicit_activity_signal:
            return activity

        text = "\n".join(recent_lines)
        for name, pattern in PATTERNS:
            if pattern.search(text):
                return name
        return "idle"

    def relevant_lines(self, service: RcloneService) -> list[str]:
        lines = self.logs.recent_file_lines(service.log_file, 120)
        return lines[-80:]

    def _is_recent(self, line: str) -> bool:
        timestamp = parse_rclone_timestamp(line)
        if timestamp is None:
            return False
        age = self._now() - timestamp
        return dt.timedelta(seconds=0) <= age <= dt.timedelta(seconds=self.activity_window_seconds)

    def _activity_for_line(self, line: str) -> str | None:
        if CLEANED_IDLE_RE.search(line):
            return "idle"
        if re.search(r"queuing for upload|upload succeeded", line, re.I):
            return "uploading"
        if re.search(r"Committing uploads", line, re.I):
            return "syncing"
        if UPLOADING_COUNT_RE.search(line):
            return "uploading"
        return None


def parse_rclone_timestamp(line: str) -> dt.datetime | None:
    match = RCLONE_TS_RE.match(line)
    if not match:
        return None
    try:
        return dt.datetime.strptime(match.group("timestamp"), "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None
