from types import SimpleNamespace

from rclonetray.rc_client import ActivitySummary
from rclonetray.tray import _get_global_tray_state


def service(activity: str = "idle", recent_error: bool = False, transient_state: str | None = None):
    active_count = 1 if activity in {"uploading", "downloading", "syncing", "cleaning"} else 0
    return SimpleNamespace(
        activity=activity,
        recent_error=recent_error,
        transient_state=transient_state,
        transient_until=None,
        active_state="active",
        activity_summary=ActivitySummary(
            state=activity,
            active_transferring_count=active_count if activity != "syncing" else 0,
            active_checking_count=active_count if activity == "syncing" else 0,
        ),
        rc_error_count=0,
        service_failed=False,
    )


def test_global_tray_state_prioritizes_error_over_syncing() -> None:
    assert _get_global_tray_state([service(activity="syncing"), service(recent_error=True)]) == "error"


def test_global_tray_state_prioritizes_restarting_over_uploading_without_error() -> None:
    assert _get_global_tray_state([service(activity="uploading"), service(transient_state="restarting")]) == "restarting"


def test_global_tray_state_detects_uploading() -> None:
    assert _get_global_tray_state([service(activity="uploading")]) == "uploading"


def test_global_tray_state_detects_bidirectional_nextcloud_to_onedrive() -> None:
    assert _get_global_tray_state([service(activity="downloading"), service(activity="uploading")]) == "bidirectional"


def test_global_tray_state_detects_bidirectional_onedrive_to_nextcloud() -> None:
    assert _get_global_tray_state([service(activity="uploading"), service(activity="downloading")]) == "bidirectional"


def test_global_tray_state_is_idle_without_activity() -> None:
    assert _get_global_tray_state([service(), service()]) == "idle"


def test_global_tray_state_returns_idle_after_small_copy_cancellation_cleared() -> None:
    services = [service(activity="idle"), service(activity="idle")]

    assert _get_global_tray_state(services) == "idle"


def test_global_tray_state_is_idle_after_rc_clears_counter_only_activity() -> None:
    services = [service(activity="idle"), service(activity="idle")]
    services[0].transfers_count = 3
    services[0].checks_count = 2

    assert _get_global_tray_state(services) == "idle"


def test_global_tray_state_ignores_stale_activity_without_real_rc_activity() -> None:
    stale = service(activity="uploading")
    stale.activity_summary = ActivitySummary(state="idle", active_transferring_count=0, active_checking_count=0, speed=42)

    assert _get_global_tray_state([stale]) == "idle"
