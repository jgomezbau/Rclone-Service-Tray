from types import SimpleNamespace

from rclonetray.tray import _get_global_tray_state


def service(activity: str = "idle", recent_error: bool = False, transient_state: str | None = None):
    return SimpleNamespace(activity=activity, recent_error=recent_error, transient_state=transient_state, active_state="active")


def test_global_tray_state_prioritizes_error_over_syncing() -> None:
    assert _get_global_tray_state([service(activity="syncing"), service(recent_error=True)]) == "error"


def test_global_tray_state_prioritizes_restarting_over_uploading_without_error() -> None:
    assert _get_global_tray_state([service(activity="uploading"), service(transient_state="restarting")]) == "restarting"


def test_global_tray_state_detects_uploading() -> None:
    assert _get_global_tray_state([service(activity="uploading")]) == "uploading"


def test_global_tray_state_is_idle_without_activity() -> None:
    assert _get_global_tray_state([service(), service()]) == "idle"
