from pathlib import Path

from rclonetray.cache_manager import CacheManager


def test_cache_path_safety(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "vfs")
    safe = tmp_path / "vfs" / "Google-Drive"
    unsafe = tmp_path / "other"

    assert cache.is_safe_cache_path(safe)
    assert not cache.is_safe_cache_path(unsafe)
