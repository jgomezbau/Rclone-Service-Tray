from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
import json
import re
from pathlib import Path

from rclonetray.config import APP_CONFIG_DIR
from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import CommandResult, SystemdManager


ERROR_RE = re.compile(
    r"((^|\s)(ERROR|CRITICAL)(\s|:)|Failed to|failed to|\bfatal\b|\bpanic\b|permission denied|"
    r"transport endpoint is not connected|rateLimitExceeded|unauthenticated|couldn't|\bcannot\b|corrupt)",
    re.IGNORECASE,
)

NON_ERROR_RE = re.compile(
    r"(\sINFO\s|INFO\s*:|DEBUG|NOTICE|vfs cache: cleaned|Committing uploads - please wait|"
    r"Copied \(new\)|upload succeeded|queuing for upload|renamed in cache|removed cache file|RemoveNotInUse)",
    re.IGNORECASE,
)
RCLONE_TS_RE = re.compile(r"^(?P<timestamp>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})\b")
DNS_WEBDAV_RE = re.compile(r"(lookup|127\.0\.0\.53:53|i/o timeout|server misbehaving|Propfind)", re.I)
LOOKUP_HOST_RE = re.compile(r"lookup\s+([A-Za-z0-9._-]+)", re.I)
URL_RE = re.compile(r"(https?://[^\s/]+(?:/[^\s]*)?)", re.I)


@dataclass
class GroupedError:
    message: str
    count: int
    first_seen: str | None
    last_seen: str | None


@dataclass
class ErrorDiagnosis:
    summary: str
    commands: list[str]


def is_error_line(line: str) -> bool:
    if NON_ERROR_RE.search(line):
        return False
    return bool(ERROR_RE.search(line))


class LogManager:
    def __init__(self, systemd: SystemdManager, logs_dir: Path | None = None, error_history_path: Path | None = None):
        self.systemd = systemd
        self.logs_dir = (logs_dir or Path.home() / ".cache" / "rclone").expanduser()
        self.error_history_path = error_history_path or APP_CONFIG_DIR / "errors.jsonl"
        self._recorded_errors: set[str] = set()
        self._suppressed_errors: set[str] = set()

    def recent_journal_errors(self, service: RcloneService, lines: int = 50) -> list[str]:
        result = self.systemd.journal_warnings(service.name, lines)
        return [line for line in result.stdout.splitlines() if line.strip() and is_error_line(line)]

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
        entries.extend(line for line in self.recent_file_lines(service.log_file, lines) if is_error_line(line))
        errors = entries[-lines:]
        self.record_detected_errors(service, errors)
        return errors

    def original_errors(self, service: RcloneService, lines: int = 80) -> list[str]:
        entries = self.recent_journal_errors(service, 50)
        entries.extend(line for line in self.recent_file_lines(service.log_file, lines) if is_error_line(line))
        return entries[-lines:]

    def error_count(self, service: RcloneService) -> int:
        return len(self.history_errors_for_service(service, 80))

    def sync_service_errors(self, service: RcloneService, cleared_after: dt.datetime | None = None, lines: int = 80) -> None:
        errors = self.original_errors(service, lines)
        if cleared_after is not None:
            filtered: list[str] = []
            for line in errors:
                timestamp = parse_error_timestamp(line)
                if timestamp is not None and timestamp <= cleared_after:
                    continue
                filtered.append(line)
            errors = filtered
        self.record_detected_errors(service, errors)

    def record_detected_errors(self, service: RcloneService, errors: list[str]) -> None:
        if not errors:
            return
        try:
            self.error_history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.error_history_path.open("a", encoding="utf-8") as handle:
                for line in errors:
                    key = f"{service.name}\0{line}"
                    if key in self._recorded_errors or key in self._suppressed_errors:
                        continue
                    self._recorded_errors.add(key)
                    handle.write(json.dumps({"service": service.name, "remote": service.display_name, "line": line}, ensure_ascii=False) + "\n")
        except OSError:
            return

    def history_errors_for_service(self, service: RcloneService, lines: int = 200) -> list[str]:
        if not self.error_history_path.exists():
            return []
        try:
            entries: list[str] = []
            for line in self.error_history_path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("service") != service.name:
                    continue
                stored_line = entry.get("line")
                if isinstance(stored_line, str):
                    entries.append(stored_line)
            return entries[-lines:]
        except OSError:
            return []

    def grouped_errors(self, lines: list[str]) -> list[GroupedError]:
        grouped: dict[str, GroupedError] = {}
        order: list[str] = []
        for line in lines:
            normalized = normalize_error_message(line)
            timestamp = parse_error_timestamp(line)
            stamp = timestamp.isoformat(sep=" ", timespec="seconds") if timestamp is not None else None
            if normalized not in grouped:
                grouped[normalized] = GroupedError(normalized, 0, stamp, stamp)
                order.append(normalized)
            item = grouped[normalized]
            item.count += 1
            if item.first_seen is None:
                item.first_seen = stamp
            item.last_seen = stamp or item.last_seen
        return [grouped[key] for key in order]

    def format_grouped_errors(self, lines: list[str], empty_message: str) -> str:
        grouped = self.grouped_errors(lines)
        if not grouped:
            return empty_message
        chunks = []
        for item in grouped:
            meta = [f"cantidad: {item.count}"]
            if item.first_seen:
                meta.append(f"primera vez: {item.first_seen}")
            if item.last_seen:
                meta.append(f"ultima vez: {item.last_seen}")
            chunks.append(f"{item.message}\n" + " | ".join(meta))
        return "\n\n".join(chunks)

    def diagnose_service_errors(self, service: RcloneService, lines: list[str]) -> ErrorDiagnosis | None:
        if not service.is_webdav_like:
            return None
        text = "\n".join(lines)
        if not DNS_WEBDAV_RE.search(text):
            return None
        domain = extract_domain(text) or "DOMINIO"
        url_base = extract_url_base(text) or "URL_BASE"
        remote = service.remote or f"{service.display_name}:"
        return ErrorDiagnosis(
            summary=(
                "El error parece relacionado con resolucion DNS local o conectividad hacia el servidor "
                "WebDAV/Nextcloud. Verifique resolvectl, conectividad con el dominio y disponibilidad del servidor."
            ),
            commands=[
                f"resolvectl query {domain}",
                f"curl -I {url_base}",
                f"rclone lsf {remote} --max-depth 1 -vv",
            ],
        )

    def is_safe_log_path(self, path: Path | None) -> bool:
        if path is None:
            return False
        try:
            resolved = path.expanduser().resolve()
            safe_roots = [
                self.logs_dir.expanduser().resolve(),
                APP_CONFIG_DIR.expanduser().resolve(),
                self.error_history_path.expanduser().resolve().parent,
            ]
            return any(resolved == root or resolved.is_relative_to(root) for root in safe_roots)
        except OSError:
            return False

    def clear_log_for_service(self, service: RcloneService) -> CommandResult:
        path = service.log_file
        if path is None:
            return CommandResult(False, "", f"No log file configured for {service.name}", 1)
        if not self.is_safe_log_path(path):
            return CommandResult(False, "", f"Unsafe log path: {path}", 1)
        path = path.expanduser()
        if not path.exists():
            return CommandResult(False, "", f"Log file does not exist: {path}", 1)
        try:
            with path.open("w", encoding="utf-8"):
                pass
            return CommandResult(True, f"Log cleaned: {path}", "", 0)
        except OSError as exc:
            return CommandResult(False, "", str(exc), 1)

    def clear_logs_for_services(self, services: list[RcloneService]) -> list[tuple[str, CommandResult]]:
        return [(service.name, self.clear_log_for_service(service)) for service in services]

    def clear_error_history(self) -> CommandResult:
        if not self.is_safe_log_path(self.error_history_path):
            return CommandResult(False, "", f"Unsafe error history path: {self.error_history_path}", 1)
        try:
            self._suppress_history_entries()
            self.error_history_path.parent.mkdir(parents=True, exist_ok=True)
            self.error_history_path.write_text("", encoding="utf-8")
            self._recorded_errors.clear()
            return CommandResult(True, f"Error history cleaned: {self.error_history_path}", "", 0)
        except OSError as exc:
            return CommandResult(False, "", str(exc), 1)

    def clear_error_history_for_service(self, service: RcloneService) -> CommandResult:
        if not self.is_safe_log_path(self.error_history_path):
            return CommandResult(False, "", f"Unsafe error history path: {self.error_history_path}", 1)
        try:
            if not self.error_history_path.exists():
                return CommandResult(True, f"No error history for {service.name}", "", 0)
            kept: list[str] = []
            for line in self.error_history_path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    kept.append(line)
                    continue
                if entry.get("service") == service.name:
                    stored_line = entry.get("line")
                    if isinstance(stored_line, str):
                        self._suppressed_errors.add(f"{service.name}\0{stored_line}")
                else:
                    kept.append(line)
            self.error_history_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            self._recorded_errors = {key for key in self._recorded_errors if not key.startswith(f"{service.name}\0")}
            return CommandResult(True, f"Error history cleaned for {service.name}", "", 0)
        except OSError as exc:
            return CommandResult(False, "", str(exc), 1)

    def _suppress_history_entries(self) -> None:
        if not self.error_history_path.exists():
            return
        try:
            for line in self.error_history_path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                service = entry.get("service")
                stored_line = entry.get("line")
                if isinstance(service, str) and isinstance(stored_line, str):
                    self._suppressed_errors.add(f"{service}\0{stored_line}")
        except OSError:
            return

    def total_logs_size(self, services: list[RcloneService]) -> int:
        total = 0
        seen: set[Path] = set()
        for service in services:
            if service.log_file is None:
                continue
            path = service.log_file.expanduser()
            if path in seen or not self.is_safe_log_path(path):
                continue
            seen.add(path)
            try:
                total += path.stat().st_size
            except OSError:
                continue
        try:
            if self.error_history_path.exists() and self.error_history_path not in seen:
                total += self.error_history_path.stat().st_size
        except OSError:
            pass
        return total


def parse_error_timestamp(line: str) -> dt.datetime | None:
    match = RCLONE_TS_RE.match(line)
    if not match:
        return None
    try:
        return dt.datetime.strptime(match.group("timestamp"), "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None


def normalize_error_message(line: str) -> str:
    normalized = RCLONE_TS_RE.sub("", line, count=1).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def extract_domain(text: str) -> str | None:
    match = LOOKUP_HOST_RE.search(text)
    if match:
        return match.group(1)
    match = URL_RE.search(text)
    if match:
        url = match.group(1)
        return re.sub(r"^https?://", "", url).split("/", 1)[0]
    return None


def extract_url_base(text: str) -> str | None:
    match = URL_RE.search(text)
    if not match:
        return None
    url = match.group(1)
    no_scheme = re.sub(r"^https?://", "", url)
    host, _, rest = no_scheme.partition("/")
    if not rest:
        return url
    first_segment = rest.split("/", 1)[0]
    return f"{url.split(host, 1)[0]}{host}/{first_segment}".rstrip("/")
