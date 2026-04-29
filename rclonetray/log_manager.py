from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
import json
import re
from pathlib import Path

from rclonetray.config import APP_CONFIG_DIR
from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import CommandResult, SystemdManager


DEFAULT_RCLONE_STATE_LOG_DIR = Path.home() / ".local" / "state" / "rclone"

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
URL_RE = re.compile(r"(https?://[^\s\"]+)", re.I)
RCLONE_OBJECT_RE = re.compile(r"\b(?:ERROR|CRITICAL|INFO|NOTICE|DEBUG)\s*:?\s+(.+?):\s+(.+)$", re.I)
TEMP_PREFIXES = (".~", "~$")
TEMP_SUFFIXES = (".tmp", ".lock")
VFS_CACHE_ERROR_RE = re.compile(
    r"(vfs cache: failed to open item|create cache file failed|open RW handle failed to open cache file|"
    r"Non-out-of-space error encountered during open|\.cache/rclone/vfs/.*no such file or directory|"
    r"no such file or directory.*\.cache/rclone/vfs/)",
    re.I,
)
VFS_CACHE_PATH_RE = re.compile(r"(/[^\s:]*\.cache/rclone/vfs/[^\s:]+)", re.I)
ONEDRIVE_SLOW_UPLOAD_RE = re.compile(r"upload chunks may be taking too long", re.I)
CANCELLED_OPERATION_RE = re.compile(r"context canceled|operation canceled|cancelled|canceled", re.I)
DIRECTORY_NOT_EMPTY_RE = re.compile(
    r"Dir\.Remove not empty|Dir\.Remove failed to remove directory: directory not empty|"
    r"IO error: directory not empty|directory not empty",
    re.I,
)
CANCELLATION_WINDOW_SECONDS = 30
ONEDRIVE_SLOW_UPLOAD_SUGGESTION = (
    "Puede ocurrir si el equipo se suspendió durante una subida. "
    "Reiniciar el servicio rclone o reintentar la operación."
)


@dataclass
class GroupedError:
    message: str
    severity: str
    error_type: str
    file: str
    source: str
    count: int
    first_seen: str | None
    last_seen: str | None
    detail: str


@dataclass
class ErrorDiagnosis:
    summary: str
    commands: list[str]


@dataclass
class ErrorEntry:
    line: str
    severity: str = "critical"
    source: str = "log"
    error_type: str = "Error crítico"


def is_error_line(line: str) -> bool:
    if DIRECTORY_NOT_EMPTY_RE.search(line):
        return True
    if ONEDRIVE_SLOW_UPLOAD_RE.search(line):
        return True
    if VFS_CACHE_ERROR_RE.search(line):
        return True
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
        errors = [entry.line for entry in self._original_error_entries(service, lines)[-lines:]]
        self.record_detected_errors(service, errors)
        return errors

    def original_errors(self, service: RcloneService, lines: int = 80) -> list[str]:
        return [entry.line for entry in self.original_error_entries(service, lines)]

    def original_error_entries(self, service: RcloneService, lines: int = 80) -> list[ErrorEntry]:
        return self._original_error_entries(service, lines)[-lines:]

    def error_count(self, service: RcloneService) -> int:
        return len(self.history_errors_for_service(service, 80))

    def sync_service_errors(self, service: RcloneService, cleared_after: dt.datetime | None = None, lines: int = 80) -> None:
        entries = self._original_error_entries(service, lines)
        if cleared_after is not None:
            filtered: list[ErrorEntry] = []
            for entry in entries:
                timestamp = parse_error_timestamp(entry.line)
                if timestamp is not None and timestamp <= cleared_after:
                    continue
                filtered.append(entry)
            entries = filtered
        self.record_error_entries(service, entries)

    def _original_error_entries(self, service: RcloneService, lines: int = 80) -> list[ErrorEntry]:
        journal_lines = self.recent_journal_errors(service, 50)
        entries = [classify_error_entry(line, journal_lines, source="journalctl") for line in journal_lines]
        file_lines = self.recent_file_lines(service.log_file, lines)
        entries.extend(
            classify_error_entry(line, file_lines)
            for line in file_lines
            if is_error_line(line)
        )
        return dedupe_error_entries(service.name, entries)[-lines:]

    def record_detected_errors(self, service: RcloneService, errors: list[str]) -> None:
        self.record_error_entries(service, [classify_error_entry(line, errors) for line in errors])

    def record_error_entries(self, service: RcloneService, errors: list[ErrorEntry]) -> None:
        if not errors:
            return
        try:
            self.error_history_path.parent.mkdir(parents=True, exist_ok=True)
            existing_keys = self._history_event_keys()
            with self.error_history_path.open("a", encoding="utf-8") as handle:
                for entry in dedupe_error_entries(service.name, errors):
                    key = stable_error_event_key(service.name, entry)
                    if key in self._recorded_errors or key in self._suppressed_errors:
                        continue
                    if key in existing_keys:
                        continue
                    self._recorded_errors.add(key)
                    handle.write(
                        json.dumps(
                            {
                                "service": service.name,
                                "remote": service.display_name,
                                "line": entry.line,
                                "severity": entry.severity,
                                "source": entry.source,
                                "type": entry.error_type,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        except OSError:
            return

    def history_error_entries_for_service(
        self,
        service: RcloneService,
        lines: int = 200,
        cleared_after: dt.datetime | None = None,
    ) -> list[ErrorEntry]:
        if not self.error_history_path.exists():
            return []
        try:
            entries: list[ErrorEntry] = []
            for line in self.error_history_path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("service") != service.name:
                    continue
                stored_line = entry.get("line")
                if not isinstance(stored_line, str):
                    continue
                timestamp = parse_error_timestamp(stored_line)
                if cleared_after is not None and timestamp is not None and timestamp <= cleared_after:
                    continue
                classified = classify_error_entry(stored_line, [stored_line])
                severity = entry.get("severity")
                source = entry.get("source")
                error_type = entry.get("type")
                if not isinstance(severity, str):
                    severity = classified.severity
                if not isinstance(source, str):
                    source = "log"
                if not isinstance(error_type, str):
                    error_type = classified.error_type
                if is_special_error_line(stored_line) and severity == "critical":
                    severity = classified.severity
                    error_type = classified.error_type
                entries.append(ErrorEntry(stored_line, severity=severity, source=source, error_type=error_type))
            return dedupe_error_entries(service.name, entries)[-lines:]
        except OSError:
            return []

    def _history_event_keys(self) -> set[str]:
        if not self.error_history_path.exists():
            return set()
        keys: set[str] = set()
        try:
            for line in self.error_history_path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                service_name = entry.get("service")
                stored_line = entry.get("line")
                if isinstance(service_name, str) and isinstance(stored_line, str):
                    keys.add(stable_error_event_key(service_name, classify_error_entry(stored_line, [stored_line])))
        except OSError:
            return set()
        return keys

    def history_errors_for_service(
        self,
        service: RcloneService,
        lines: int = 200,
        cleared_after: dt.datetime | None = None,
    ) -> list[str]:
        return [entry.line for entry in self.history_error_entries_for_service(service, lines, cleared_after)]

    def active_history_error_entries_for_service(
        self,
        service: RcloneService,
        lines: int = 200,
        cleared_after: dt.datetime | None = None,
    ) -> list[ErrorEntry]:
        return [
            entry
            for entry in self.history_error_entries_for_service(service, lines, cleared_after)
            if entry.severity not in {"warning", "minor_warning", "warning_resolved", "resolved"}
        ]

    def grouped_errors(self, lines: list[str] | list[ErrorEntry]) -> list[GroupedError]:
        grouped: dict[str, GroupedError] = {}
        order: list[str] = []
        normalized_entries: list[ErrorEntry] = []
        for raw in lines:
            entry = raw if isinstance(raw, ErrorEntry) else ErrorEntry(raw)
            if is_special_error_line(entry.line):
                entry = classify_error_entry(entry.line, [entry.line], source=entry.source)
            normalized_entries.append(entry)
        for entry in dedupe_error_entries("", normalized_entries):
            normalized = summarize_error_message(entry.line)
            file_path = extract_error_file(entry.line)
            if is_vfs_cache_error(entry.line):
                normalized = "VFS cache local inconsistente al abrir archivo"
                file_path = extract_vfs_cache_error_file(entry.line) or file_path
            timestamp = parse_error_timestamp(entry.line)
            grouping_stamp = ""
            if is_cancelled_operation(entry.line) and not is_temporary_file(extract_error_file(entry.line)):
                normalized = "Transferencias canceladas por el usuario"
                file_path = ""
                grouping_stamp = cancellation_window_stamp(timestamp)
            elif is_directory_not_empty_cleanup(entry.line) and entry.severity in {"warning", "minor_warning", "warning_resolved", "resolved"}:
                normalized = "Limpieza de directorio cancelada: directory not empty"
                file_path = ""
                grouping_stamp = cancellation_window_stamp(timestamp)
            stamp = timestamp.isoformat(sep=" ", timespec="seconds") if timestamp is not None else None
            key = f"{entry.severity}\0{entry.error_type}\0{normalized}\0{file_path}\0{entry.source}\0{grouping_stamp}"
            if key not in grouped:
                grouped[key] = GroupedError(
                    normalized,
                    severity=entry.severity,
                    error_type=entry.error_type,
                    file=file_path,
                    source=entry.source,
                    count=0,
                    first_seen=stamp,
                    last_seen=stamp,
                    detail=entry.line,
                )
                order.append(key)
            item = grouped[key]
            item.count += 1
            if entry.line not in item.detail.splitlines():
                item.detail += f"\n{entry.line}"
            if item.first_seen is None:
                item.first_seen = stamp
            item.last_seen = stamp or item.last_seen
        return [grouped[key] for key in order]

    def format_grouped_errors(self, lines: list[str] | list[ErrorEntry], empty_message: str) -> str:
        grouped = self.grouped_errors(lines)
        if not grouped:
            return empty_message
        chunks = []
        for item in grouped:
            meta = [
                f"Severidad: {severity_label(item.severity)}",
                f"Tipo: {item.error_type}",
                f"Mensaje resumido: {item.message}",
                f"Archivo: {item.file or '-'}",
                f"Cantidad: {item.count}",
            ]
            if item.first_seen:
                meta.append(f"Primera vez: {item.first_seen}")
            if item.last_seen:
                meta.append(f"Última vez: {item.last_seen}")
            if item.severity in {"warning_resolved", "resolved"}:
                meta.append(f"Estado: {item.severity}")
            meta.append(f"Fuente: {item.source}")
            suggestion = suggestion_for_error_type(item.error_type)
            detail = item.detail
            if suggestion:
                detail = f"{detail}\nSugerencia: {suggestion}"
            chunks.append("\n".join(meta) + f"\nDetalle: {detail}")
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
                DEFAULT_RCLONE_STATE_LOG_DIR.expanduser().resolve(),
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
        results: list[tuple[str, CommandResult]] = []
        for service in services:
            if service.log_file is None:
                results.append((service.name, CommandResult(True, f"Omitido: {service.name} no tiene log configurado.", "", 0)))
                continue
            path = service.log_file.expanduser()
            if self.is_safe_log_path(path) and not path.exists():
                results.append((service.name, CommandResult(True, f"Omitido: el log no existe: {path}", "", 0)))
                continue
            results.append((service.name, self.clear_log_for_service(service)))
        return results

    def suppress_current_errors_for_services(self, services: list[RcloneService]) -> None:
        for service in services:
            for entry in self._original_error_entries(service):
                self._suppressed_errors.add(stable_error_event_key(service.name, entry))

    def suppress_current_errors_for_service(self, service: RcloneService) -> None:
        self.suppress_current_errors_for_services([service])

    def clear_error_history(self) -> CommandResult:
        if not self.is_safe_log_path(self.error_history_path):
            return CommandResult(False, "", f"Unsafe error history path: {self.error_history_path}", 1)
        try:
            self._suppress_history_entries()
            self.error_history_path.parent.mkdir(parents=True, exist_ok=True)
            self.error_history_path.write_text("", encoding="utf-8")
            self._recorded_errors.clear()
            return CommandResult(True, "Historial de errores limpiado correctamente.", "", 0)
        except OSError as exc:
            return CommandResult(False, "", str(exc), 1)

    def clear_error_history_for_service(self, service: RcloneService) -> CommandResult:
        if not self.is_safe_log_path(self.error_history_path):
            return CommandResult(False, "", f"Unsafe error history path: {self.error_history_path}", 1)
        try:
            if not self.error_history_path.exists():
                return CommandResult(True, f"No hay historial de errores para {service.name}.", "", 0)
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
                        self._suppressed_errors.add(stable_error_event_key(service.name, classify_error_entry(stored_line, [stored_line])))
                else:
                    kept.append(line)
            self.error_history_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            self._recorded_errors = {key for key in self._recorded_errors if not key.startswith(f"{service.name}\0")}
            return CommandResult(True, f"Historial de errores limpiado para {service.name}.", "", 0)
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
                    self._suppressed_errors.add(stable_error_event_key(service, classify_error_entry(stored_line, [stored_line])))
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


def summarize_error_message(line: str) -> str:
    _, message = split_rclone_object_message(line)
    message = URL_RE.sub("<url>", message)
    message = re.sub(r"\s+", " ", message).strip()
    if is_directory_not_empty_cleanup(line):
        return "Limpieza de directorio cancelada: directory not empty"
    cancelled_copy = re.search(
        r'Failed to copy:\s*(Put|Post)\s+"<url>":\s*(context canceled|operation canceled|cancelled|canceled)',
        message,
        re.I,
    )
    if cancelled_copy:
        return f'Failed to copy: {cancelled_copy.group(1)} "<url>": {cancelled_copy.group(2).lower()}'
    failed = re.search(r"Failed to copy:\s*([^:]+(?: canceled|cancelled|denied|failed|timeout)?)", message, re.I)
    if failed:
        return f"Failed to copy: {failed.group(1).strip()}"
    retry = re.search(r"failed to \w+:\s*([^:]+)", message, re.I)
    if retry:
        return retry.group(0).strip()
    return normalize_error_message(message)


def extract_error_file(line: str) -> str:
    file_path, _ = split_rclone_object_message(line)
    return file_path


def split_rclone_object_message(line: str) -> tuple[str, str]:
    normalized = normalize_error_message(line)
    match = RCLONE_OBJECT_RE.search(normalized)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "", normalized


def classify_error_entry(line: str, context: list[str], source: str = "log") -> ErrorEntry:
    severity = classify_error_line(line, context)
    return ErrorEntry(line, severity=severity, source=source, error_type=error_type_for_line(line, severity))


def stable_error_event_key(service_name: str, entry: ErrorEntry) -> str:
    timestamp = parse_error_timestamp(entry.line)
    stamp = timestamp.isoformat(sep=" ", timespec="seconds") if timestamp is not None else ""
    message = summarize_error_message(entry.line)
    file_path = extract_error_file(entry.line)
    if is_vfs_cache_error(entry.line):
        message = "VFS cache local inconsistente al abrir archivo"
        file_path = extract_vfs_cache_error_file(entry.line) or file_path
    return "\0".join([service_name, stamp, message, file_path])


def dedupe_error_entries(service_name: str, entries: list[ErrorEntry]) -> list[ErrorEntry]:
    deduped: dict[str, ErrorEntry] = {}
    order: list[str] = []
    for entry in entries:
        key = stable_error_event_key(service_name, entry)
        if key not in deduped:
            deduped[key] = entry
            order.append(key)
            continue
        if classification_priority(entry) > classification_priority(deduped[key]):
            deduped[key] = entry
    return [deduped[key] for key in order]


def classification_priority(entry: ErrorEntry) -> int:
    if is_special_error_line(entry.line):
        return 30
    if entry.source == "RC":
        return 20
    if entry.source == "journalctl":
        return 10
    return 0


def is_special_error_line(line: str) -> bool:
    return (
        is_temporary_file(extract_error_file(line))
        or is_vfs_cache_error(line)
        or is_onedrive_slow_upload_error(line)
        or is_cancelled_operation(line)
        or is_directory_not_empty_cleanup(line)
    )


def classify_error_line(line: str, following_context: list[str]) -> str:
    file_path = extract_error_file(line)
    if is_temporary_file(file_path) and has_later_real_upload_success(file_path, line, following_context):
        return "warning_resolved"
    if is_temporary_file(file_path):
        return "warning"
    if is_cancelled_operation(line):
        return "warning"
    if is_directory_not_empty_cleanup(line):
        return "warning" if has_nearby_cancelled_operation(line, following_context) else "critical"
    if is_vfs_cache_error(line):
        return "critical" if is_repeated_vfs_cache_error(line, following_context) else "warning"
    if is_onedrive_slow_upload_error(line):
        return "critical" if is_repeated_onedrive_slow_upload_error(line, following_context) else "warning"
    return "critical"


def error_type_for_line(line: str, severity: str) -> str:
    file_path = extract_error_file(line)
    if is_temporary_file(file_path):
        return "Archivo temporal de editor"
    if is_directory_not_empty_cleanup(line):
        if severity in {"warning", "minor_warning", "warning_resolved", "resolved"}:
            return "Limpieza posterior a cancelación"
        return "Error crítico"
    if is_cancelled_operation(line):
        return "Operación cancelada por el usuario / copia interrumpida"
    if is_vfs_cache_error(line):
        return "VFS cache local inconsistente"
    if is_onedrive_slow_upload_error(line):
        return "Advertencia transitoria: upload interrumpido o demorado"
    return error_type_for_severity(severity)


def error_type_for_severity(severity: str) -> str:
    if severity in {"warning", "minor_warning", "warning_resolved", "resolved"}:
        return "Advertencia"
    return "Error crítico"


def is_temporary_file(path: str) -> bool:
    name = Path(path).name
    lower = name.lower()
    return name.startswith(TEMP_PREFIXES) or lower.endswith(TEMP_SUFFIXES)


def real_file_for_temporary(path: str) -> str:
    parent = str(Path(path).parent)
    name = Path(path).name
    for prefix in TEMP_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    lower = name.lower()
    for suffix in TEMP_SUFFIXES:
        if lower.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if parent in {"", "."}:
        return name
    return f"{parent}/{name}"


def has_later_real_upload_success(temp_path: str, error_line: str, lines: list[str]) -> bool:
    real_path = real_file_for_temporary(temp_path)
    try:
        start = lines.index(error_line) + 1
    except ValueError:
        start = 0
    real_name = Path(real_path).name
    for line in lines[start:]:
        if re.search(r"upload succeeded|Copied \(new\)|Copied", line, re.I) and (real_path in line or real_name in line):
            return True
    return False


def is_vfs_cache_error(line: str) -> bool:
    return bool(VFS_CACHE_ERROR_RE.search(line))


def is_onedrive_slow_upload_error(line: str) -> bool:
    return bool(ONEDRIVE_SLOW_UPLOAD_RE.search(line))


def is_cancelled_operation(line: str) -> bool:
    return bool(CANCELLED_OPERATION_RE.search(line))


def is_directory_not_empty_cleanup(line: str) -> bool:
    return bool(DIRECTORY_NOT_EMPTY_RE.search(line))


def has_nearby_cancelled_operation(line: str, lines: list[str]) -> bool:
    target_timestamp = parse_error_timestamp(line)
    if target_timestamp is None:
        return any(is_cancelled_operation(candidate) for candidate in lines)
    for candidate in lines:
        if not is_cancelled_operation(candidate):
            continue
        timestamp = parse_error_timestamp(candidate)
        if timestamp is None:
            continue
        if abs((timestamp - target_timestamp).total_seconds()) <= CANCELLATION_WINDOW_SECONDS:
            return True
    return False


def cancellation_window_stamp(timestamp: dt.datetime | None) -> str:
    if timestamp is None:
        return ""
    window_start_second = int(timestamp.timestamp()) // CANCELLATION_WINDOW_SECONDS * CANCELLATION_WINDOW_SECONDS
    window_start = dt.datetime.fromtimestamp(window_start_second)
    return window_start.isoformat(sep=" ", timespec="seconds")


def extract_vfs_cache_error_file(line: str) -> str:
    object_path = extract_error_file(line)
    if object_path:
        return real_file_for_cache_path(object_path)
    match = VFS_CACHE_PATH_RE.search(line)
    if not match:
        return ""
    return real_file_for_cache_path(match.group(1))


def real_file_for_cache_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if "/.cache/rclone/vfs/" in normalized:
        normalized = normalized.split("/.cache/rclone/vfs/", 1)[1]
        parts = [part for part in normalized.split("/") if part]
        if len(parts) >= 2:
            return "/".join(parts[1:])
        if parts:
            return parts[0]
    return Path(normalized).name


def is_repeated_vfs_cache_error(line: str, lines: list[str]) -> bool:
    target_file = extract_vfs_cache_error_file(line)
    target_timestamp = parse_error_timestamp(line)
    if not target_file or target_timestamp is None:
        return False
    repeats = 0
    for candidate in lines:
        if not is_vfs_cache_error(candidate):
            continue
        if extract_vfs_cache_error_file(candidate) != target_file:
            continue
        timestamp = parse_error_timestamp(candidate)
        if timestamp is None:
            continue
        if abs((timestamp - target_timestamp).total_seconds()) <= 60:
            repeats += 1
    return repeats > 3


def is_repeated_onedrive_slow_upload_error(line: str, lines: list[str]) -> bool:
    target_file = extract_error_file(line)
    target_timestamp = parse_error_timestamp(line)
    if target_timestamp is None:
        return False
    repeats = 0
    for candidate in lines:
        if not is_onedrive_slow_upload_error(candidate):
            continue
        if target_file and extract_error_file(candidate) != target_file:
            continue
        timestamp = parse_error_timestamp(candidate)
        if timestamp is None:
            continue
        if abs((timestamp - target_timestamp).total_seconds()) <= 600:
            repeats += 1
    return repeats > 3


def suggestion_for_error_type(error_type: str) -> str | None:
    if error_type == "Advertencia transitoria: upload interrumpido o demorado":
        return ONEDRIVE_SLOW_UPLOAD_SUGGESTION
    return None


def severity_label(severity: str) -> str:
    if severity == "warning_resolved":
        return "Resuelto"
    if severity in {"warning", "minor_warning"}:
        return "Advertencia"
    return "Crítico"


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
