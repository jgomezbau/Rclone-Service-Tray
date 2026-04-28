from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int


class SystemdManager:
    def run(self, args: list[str], timeout: int = 30) -> CommandResult:
        try:
            completed = subprocess.run(
                args,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            return CommandResult(
                completed.returncode == 0,
                completed.stdout,
                completed.stderr,
                completed.returncode,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CommandResult(False, "", str(exc), 1)

    def start(self, service: str) -> CommandResult:
        return self.run(["systemctl", "--user", "start", service])

    def stop(self, service: str) -> CommandResult:
        return self.run(["systemctl", "--user", "stop", service])

    def restart(self, service: str) -> CommandResult:
        return self.run(["systemctl", "--user", "restart", service])

    def daemon_reload(self) -> CommandResult:
        return self.run(["systemctl", "--user", "daemon-reload"])

    def status(self, service: str) -> CommandResult:
        return self.run(["systemctl", "--user", "status", service, "--no-pager", "-l"])

    def show_state(self, service: str) -> tuple[str, str]:
        result = self.run(
            ["systemctl", "--user", "show", service, "--property=ActiveState", "--property=SubState"],
            timeout=10,
        )
        active = "unknown"
        sub = "unknown"
        for line in result.stdout.splitlines():
            if line.startswith("ActiveState="):
                active = line.split("=", 1)[1] or "unknown"
            elif line.startswith("SubState="):
                sub = line.split("=", 1)[1] or "unknown"
        return active, sub

    def journal_warnings(self, service: str, lines: int = 50) -> CommandResult:
        return self.run(
            ["journalctl", "--user", "-u", service, "-p", "warning", "-n", str(lines), "--no-pager"],
            timeout=20,
        )

    def verify(self, path: Path) -> CommandResult:
        return self.run(["systemd-analyze", "--user", "verify", str(path)], timeout=20)
