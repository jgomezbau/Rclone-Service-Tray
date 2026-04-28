from __future__ import annotations

import base64
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from rclonetray.service_model import RcloneService


@dataclass
class ActivitySummary:
    state: str = "idle"
    transfers_count: int = 0
    checking_count: int = 0
    transferring_count: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    speed: float = 0.0
    active_files: list[dict[str, Any]] = field(default_factory=list)
    raw_stats: dict[str, Any] = field(default_factory=dict)
    source: str = "none"
    error: str | None = None
    error_count: int = 0


class RcloneRcClient:
    def __init__(self, service: RcloneService, timeout: float = 1.0):
        self.service = service
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            self.call("rc/noop")
            return True
        except RcloneRcError:
            return False

    def call(self, endpoint: str, payload: dict | None = None) -> dict:
        if not self.service.rc_enabled or not self.service.rc_url:
            raise RcloneRcError("RC no configurado")
        url = f"{self.service.rc_url}/{endpoint.lstrip('/')}"
        data = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout) as exc:
            raise RcloneRcError(str(exc)) from exc
        if not body.strip():
            return {}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RcloneRcError(f"Respuesta RC no es JSON valido: {exc}") from exc
        return parsed if isinstance(parsed, dict) else {"result": parsed}

    def get_stats(self) -> dict:
        return self.call("core/stats")

    def get_core_version(self) -> dict:
        return self.call("core/version")

    def get_active_transfers(self) -> list:
        stats = self.get_stats()
        transfers = stats.get("transferring", [])
        return transfers if isinstance(transfers, list) else []

    def get_activity_summary(self) -> ActivitySummary:
        try:
            stats = self.get_stats()
        except RcloneRcError as exc:
            return ActivitySummary(state="unavailable", source="rc", error=str(exc))
        return activity_summary_from_stats(stats)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.service.rc_auth_enabled and self.service.rc_user and self.service.rc_pass:
            token = f"{self.service.rc_user}:{self.service.rc_pass}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(token).decode("ascii")
        return headers


class RcloneRcError(RuntimeError):
    pass


def activity_summary_from_stats(stats: dict[str, Any]) -> ActivitySummary:
    transferring = _list_value(stats.get("transferring"))
    checking = _list_value(stats.get("checking"))
    transfers_count = _int_value(stats.get("transfers"))
    checks_count = _int_value(stats.get("checks"))
    error_count = _int_value(stats.get("errors"))
    bytes_done = _int_value(stats.get("bytes"))
    speed = _float_value(stats.get("speed"))
    total_size = sum(_int_value(item.get("size")) for item in transferring if isinstance(item, dict))
    if not total_size:
        total_size = _int_value(stats.get("totalBytes")) or bytes_done
    state = _state_from_stats(transferring, checking, speed, transfers_count, checks_count)
    return ActivitySummary(
        state=state,
        transfers_count=transfers_count,
        checking_count=max(checks_count, len(checking)),
        transferring_count=len(transferring),
        bytes_total=total_size,
        bytes_done=bytes_done,
        speed=speed,
        active_files=[item for item in transferring if isinstance(item, dict)],
        raw_stats=stats,
        source="rc",
        error_count=error_count,
    )


def _state_from_stats(
    transferring: list[Any],
    checking: list[Any],
    speed: float,
    transfers_count: int = 0,
    checks_count: int = 0,
) -> str:
    if not transferring and not checking and transfers_count == 0 and checks_count == 0 and speed == 0:
        return "idle"
    if transferring:
        text = " ".join(str(item) for item in transferring).lower()
        if "download" in text or "downloading" in text:
            return "downloading"
        if "upload" in text or "uploading" in text:
            return "uploading"
        return "syncing" if speed > 0 else "syncing"
    if checking:
        return "syncing"
    if transfers_count > 0 or checks_count > 0 or speed > 0:
        return "syncing"
    return "idle"


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _float_value(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0
