from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from rclonetray.service_model import RcloneService
from rclonetray.systemd_manager import CommandResult, SystemdManager


@dataclass
class CacheInfo:
    path: Path
    size: int
    files: int
    mtime: float | None


def human_size(size: int | None) -> str:
    if size is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


class CacheManager:
    def __init__(self, cache_base: Path):
        self.cache_base = cache_base.expanduser().resolve()

    def cache_path_for(self, service: RcloneService) -> Path:
        candidates = []
        if service.remote:
            candidates.append(service.remote.rstrip(":").replace("/", "_"))
        candidates.append(service.display_name)
        for name in candidates:
            path = self.cache_base / name
            if path.exists():
                return path
        return self.cache_base / candidates[0]

    def inspect(self, path: Path) -> CacheInfo:
        path = path.expanduser()
        if not path.exists():
            return CacheInfo(path, 0, 0, None)
        total = 0
        files = 0
        newest: float | None = None
        for root, _, filenames in os.walk(path):
            for filename in filenames:
                file_path = Path(root) / filename
                try:
                    stat = file_path.stat()
                except OSError:
                    continue
                total += stat.st_size
                files += 1
                newest = max(newest or stat.st_mtime, stat.st_mtime)
        return CacheInfo(path, total, files, newest)

    def list_files(self, path: Path, limit: int = 500) -> list[tuple[Path, int, float]]:
        items: list[tuple[Path, int, float]] = []
        if not path.exists():
            return items
        for root, _, filenames in os.walk(path):
            for filename in filenames:
                file_path = Path(root) / filename
                try:
                    stat = file_path.stat()
                except OSError:
                    continue
                items.append((file_path, stat.st_size, stat.st_mtime))
                if len(items) >= limit:
                    return sorted(items, key=lambda item: item[2], reverse=True)
        return sorted(items, key=lambda item: item[2], reverse=True)

    def is_safe_cache_path(self, path: Path) -> bool:
        try:
            resolved = path.expanduser().resolve()
            return resolved == self.cache_base or resolved.is_relative_to(self.cache_base)
        except OSError:
            return False

    def clear_cache_for_service(self, service: RcloneService, systemd: SystemdManager) -> CommandResult:
        path = service.cache_path or self.cache_path_for(service)
        if not self.is_safe_cache_path(path) or path == self.cache_base:
            return CommandResult(False, "", f"Unsafe cache path: {path}", 1)
        stop = systemd.stop(service.name)
        if not stop.ok:
            return stop
        try:
            if path.exists():
                shutil.rmtree(path)
        except OSError as exc:
            systemd.start(service.name)
            return CommandResult(False, "", str(exc), 1)
        start = systemd.start(service.name)
        if not start.ok:
            return start
        return CommandResult(True, f"Cache cleaned: {path}", "", 0)

    def clear_all(self, services: list[RcloneService], systemd: SystemdManager) -> list[tuple[str, CommandResult]]:
        results: list[tuple[str, CommandResult]] = []
        for service in services:
            results.append((service.name, self.clear_cache_for_service(service, systemd)))
        return results
