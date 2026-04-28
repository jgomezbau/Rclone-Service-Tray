from __future__ import annotations

import re
import shlex
from pathlib import Path

from rclonetray.service_model import RcloneService


EXEC_RE = re.compile(r"^ExecStart=(.*)$", re.MULTILINE)

RCLONE_VALUE_FLAGS = {
    "--config",
    "--vfs-cache-mode",
    "--vfs-cache-max-size",
    "--vfs-cache-max-age",
    "--vfs-read-chunk-size",
    "--vfs-read-chunk-size-limit",
    "--multi-thread-streams",
    "--multi-thread-cutoff",
    "--dir-cache-time",
    "--attr-timeout",
    "--poll-interval",
    "--log-level",
    "--log-file",
    "--vfs-cache-poll-interval",
    "--drive-pacer-min-sleep",
    "--drive-pacer-burst",
    "--rc-addr",
}

RCLONE_BOOLEAN_FLAGS = {
    "--allow-other",
    "--rc",
    "--rc-no-auth",
}


def discover_service_files(systemd_user_dir: Path) -> list[Path]:
    if not systemd_user_dir.exists():
        return []
    return sorted(
        path
        for path in systemd_user_dir.glob("rclone-*.service")
        if path.is_file() and not path.name.endswith(".bak")
    )


def load_services(systemd_user_dir: Path, configured_services: list[str], ignored_services: list[str] | None = None) -> list[RcloneService]:
    paths = discover_service_files(systemd_user_dir.expanduser())
    paths.extend(Path(p).expanduser() for p in configured_services)
    ignored = set(ignored_services or [])
    services: list[RcloneService] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen or not path.exists() or path.name in ignored:
            continue
        seen.add(path)
        try:
            services.append(parse_service_file(path))
        except OSError:
            continue
    return services


def parse_service_file(path: Path) -> RcloneService:
    text = path.read_text(encoding="utf-8", errors="replace")
    exec_start = _extract_exec_start(text)
    service = RcloneService(name=path.name, path=path, exec_start=exec_start)
    if exec_start:
        _parse_exec_start(service, exec_start)
    return service


def _extract_exec_start(text: str) -> str:
    logical_lines: list[str] = []
    current = ""
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            current += stripped[:-1] + " "
            continue
        logical_lines.append(current + stripped)
        current = ""
    if current:
        logical_lines.append(current)
    normalized = "\n".join(logical_lines)
    match = EXEC_RE.search(normalized)
    return match.group(1).strip() if match else ""


def _parse_exec_start(service: RcloneService, exec_start: str) -> None:
    try:
        parts = shlex.split(exec_start)
    except ValueError:
        parts = exec_start.split()

    if not parts:
        return

    service.flags = _parse_flags(parts)

    mount_index = _find_mount_index(parts)
    if mount_index is not None:
        remote_index = _find_remote_index(parts, mount_index + 1)
        if remote_index is not None:
            service.remote = parts[remote_index]
            if len(parts) > remote_index + 1:
                service.mount_point = Path(parts[remote_index + 1]).expanduser()

    log_file = service.flags.get("--log-file")
    if isinstance(log_file, str):
        service.log_file = Path(log_file).expanduser()


def _find_mount_index(parts: list[str]) -> int | None:
    for index, part in enumerate(parts):
        if part in {"mount", "cmount"}:
            return index
    return None


def _find_remote_index(parts: list[str], start: int) -> int | None:
    index = start
    while index < len(parts):
        token = parts[index]
        if token.startswith("--"):
            key = token.split("=", 1)[0]
            if "=" not in token and key in RCLONE_VALUE_FLAGS:
                index += 2
            else:
                index += 1
            continue
        if token.endswith(":"):
            return index
        index += 1
    return None


def _parse_flags(parts: list[str]) -> dict[str, str | bool]:
    flags: dict[str, str | bool] = {}
    index = 0
    while index < len(parts):
        token = parts[index]
        if not token.startswith("--"):
            index += 1
            continue
        key = token.split("=", 1)[0]
        if "=" in token:
            key, value = token.split("=", 1)
            flags[key] = value
        elif key in RCLONE_VALUE_FLAGS and index + 1 < len(parts):
            flags[token] = parts[index + 1]
            index += 1
        elif key in RCLONE_BOOLEAN_FLAGS:
            flags[token] = True
        else:
            flags[token] = True
        index += 1
    return flags
