from __future__ import annotations

import re
import shlex
from pathlib import Path

from rclonetray.service_model import RcloneService


EXEC_RE = re.compile(r"^ExecStart=(.*)$", re.MULTILINE)


def discover_service_files(systemd_user_dir: Path) -> list[Path]:
    if not systemd_user_dir.exists():
        return []
    return sorted(
        path
        for path in systemd_user_dir.glob("rclone-*.service")
        if path.is_file() and not path.name.endswith(".bak")
    )


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

    mount_index = _find_mount_index(parts)
    if mount_index is not None and len(parts) > mount_index + 2:
        service.remote = parts[mount_index + 1]
        service.mount_point = Path(parts[mount_index + 2]).expanduser()

    service.flags = _parse_flags(parts)
    log_file = service.flags.get("--log-file")
    if isinstance(log_file, str):
        service.log_file = Path(log_file).expanduser()


def _find_mount_index(parts: list[str]) -> int | None:
    for index, part in enumerate(parts):
        if part in {"mount", "cmount"}:
            return index
    return None


def _parse_flags(parts: list[str]) -> dict[str, str | bool]:
    flags: dict[str, str | bool] = {}
    index = 0
    while index < len(parts):
        token = parts[index]
        if not token.startswith("--"):
            index += 1
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            flags[key] = value
        elif index + 1 < len(parts) and not parts[index + 1].startswith("-"):
            flags[token] = parts[index + 1]
            index += 1
        else:
            flags[token] = True
        index += 1
    return flags
