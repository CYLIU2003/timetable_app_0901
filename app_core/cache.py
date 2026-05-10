from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any, Callable


@dataclass(frozen=True)
class FileCacheKey:
    path: str
    mtime_ns: int
    sheet_name: str | None = None
    column: str | None = None


def file_mtime_ns(path: str | Path) -> int:
    return Path(path).stat().st_mtime_ns


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TtlCache:
    def __init__(self) -> None:
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = Lock()

    def get_or_set(self, key: str, ttl_seconds: int, loader: Callable[[], Any]) -> Any:
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > now:
                return entry.value

        try:
            value = loader()
        except Exception:
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None:
                    return entry.value
            raise

        with self._lock:
            self._entries[key] = _CacheEntry(value=value, expires_at=now + ttl_seconds)
        return value