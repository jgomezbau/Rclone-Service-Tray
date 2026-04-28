import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from rclonetray.rc_client import RcloneRcClient, activity_summary_from_stats
from rclonetray.service_model import RcloneService


class RcHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/rc/noop":
            self._write({})
        elif self.path == "/core/version":
            self._write({"version": "v1.66.0"})
        elif self.path == "/core/stats":
            self._write(
                {
                    "bytes": 512,
                    "speed": 128,
                    "transfers": 1,
                    "checks": 0,
                    "transferring": [{"name": "file.txt", "size": 1024, "bytes": 512, "operation": "upload"}],
                    "checking": [],
                }
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _write(self, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_service(url: str) -> RcloneService:
    return RcloneService(
        name="rclone-Test.service",
        path=Path("/tmp/rclone-Test.service"),
        rc_enabled=True,
        rc_url=url,
        rc_addr=url.removeprefix("http://"),
        rc_auth_enabled=False,
    )


def test_rc_noop_available() -> None:
    server = HTTPServer(("127.0.0.1", 0), RcHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        service = make_service(f"http://127.0.0.1:{server.server_port}")
        assert RcloneRcClient(service).is_available()
    finally:
        server.shutdown()


def test_core_stats_parse_activity() -> None:
    summary = activity_summary_from_stats(
        {
            "bytes": 512,
            "speed": 128,
            "transfers": 1,
            "transferring": [{"name": "file.txt", "size": 1024, "bytes": 512, "operation": "upload"}],
            "checking": [],
        }
    )

    assert summary.state == "uploading"
    assert summary.transferring_count == 1
    assert summary.bytes_done == 512
    assert summary.bytes_total == 1024
    assert summary.speed == 128


def test_core_stats_parse_downloading_activity() -> None:
    summary = activity_summary_from_stats(
        {
            "bytes": 256,
            "speed": 64,
            "transferring": [{"name": "file.txt", "size": 1024, "bytes": 256, "direction": "download"}],
            "checking": [],
        }
    )

    assert summary.state == "downloading"


def test_core_stats_parse_checking_as_syncing() -> None:
    summary = activity_summary_from_stats({"speed": 0, "transferring": [], "checking": [{"name": "file.txt"}]})

    assert summary.state == "syncing"


def test_connection_failure_returns_unavailable() -> None:
    service = make_service("http://127.0.0.1:1")

    summary = RcloneRcClient(service, timeout=0.1).get_activity_summary()

    assert summary.state == "unavailable"
    assert summary.source == "rc"
    assert summary.error


def test_idle_stats_return_idle() -> None:
    summary = activity_summary_from_stats({"bytes": 0, "speed": 0, "transferring": [], "checking": []})

    assert summary.state == "idle"


def test_completed_transfer_counters_do_not_force_syncing() -> None:
    summary = activity_summary_from_stats(
        {
            "bytes": 1044480,
            "speed": 0,
            "transfers": 1,
            "totalTransfers": 1,
            "transferring": [],
            "checking": [],
        }
    )

    assert summary.state == "idle"
    assert summary.transfers_count == 1


def test_core_stats_error_count_is_preserved() -> None:
    summary = activity_summary_from_stats({"bytes": 0, "speed": 0, "transfers": 0, "checks": 0, "errors": 3})

    assert summary.state == "idle"
    assert summary.error_count == 3
