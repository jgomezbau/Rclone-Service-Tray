from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_CONFIG_DIR = Path.home() / ".config" / "rclone-service-tray"
APP_CONFIG_FILE = APP_CONFIG_DIR / "config.json"
APP_LOG_FILE = APP_CONFIG_DIR / "rclone-service-tray.log"


@dataclass
class AppConfig:
    theme: str = "system"
    services: list[str] = field(default_factory=list)
    ignored_services: list[str] = field(default_factory=list)
    last_error_clear_time: dict[str, str] = field(default_factory=dict)
    confirm_cache_clean: bool = True
    start_minimized: bool = True
    minimize_to_tray: bool = True
    show_notifications: bool = True
    show_tray_indicators: bool = True
    refresh_interval_seconds: int = 10
    cache_refresh_interval_seconds: int = 60
    activity_window_seconds: int = 60
    systemd_user_dir: str = str(Path.home() / ".config" / "systemd" / "user")
    mounts_base_dir: str = str(Path.home() / "CloudDrives")
    rclone_cache_dir: str = str(Path.home() / ".cache" / "rclone" / "vfs")
    logs_dir: str = str(Path.home() / ".cache" / "rclone")


def setup_logging() -> None:
    APP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=APP_LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def load_config(path: Path = APP_CONFIG_FILE) -> AppConfig:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        config = AppConfig()
        save_config(config, path)
        return config

    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logging.exception("Could not load config, using defaults")
        return AppConfig()

    defaults = asdict(AppConfig())
    defaults.update({k: v for k, v in raw.items() if k in defaults})
    return AppConfig(**defaults)


def save_config(config: AppConfig, path: Path = APP_CONFIG_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")
