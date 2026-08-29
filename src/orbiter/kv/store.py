"""Key-value store abstraction over Valkey.

The protocol exists so the correctness-critical logic (leases, idempotency)
can be tested against an in-memory implementation with a controllable clock.
Clock skew and GC pauses are then just numbers in a test instead of a 3 a.m.
production incident.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...


class WallClock:
    def now(self) -> float:
        return time.monotonic()


class FakeClock:
    """Test clock. ``advance`` is how a test says 'the process paused here'."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class KeyValueStore(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set_if_absent(self, key: str, value: str, ttl_s: float) -> bool:
        """SET NX EX. Returns True only if the key did not exist (or had expired)."""
        ...

    async def incr(self, key: str) -> int:
        """Atomically increment a counter. Counters never expire."""
        ...

    async def compare_and_delete(self, key: str, expected: str) -> bool:
        """Delete the key only if it currently holds ``expected``."""
        ...


@dataclass
class _Entry:
    value: str
    expires_at: float | None


class InMemoryKV:
    """Single-process KeyValueStore with expiry driven by an injectable clock."""

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or WallClock()
        self._data: dict[str, _Entry] = {}
        self._counters: dict[str, int] = {}

    def _live(self, key: str) -> _Entry | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.expires_at is not None and self._clock.now() >= entry.expires_at:
            del self._data[key]
            return None
        return entry

    async def get(self, key: str) -> str | None:
        entry = self._live(key)
        return entry.value if entry else None

    async def set_if_absent(self, key: str, value: str, ttl_s: float) -> bool:
        if self._live(key) is not None:
            return False
        self._data[key] = _Entry(value=value, expires_at=self._clock.now() + ttl_s)
        return True

    async def incr(self, key: str) -> int:
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    async def compare_and_delete(self, key: str, expected: str) -> bool:
        entry = self._live(key)
        if entry is None or entry.value != expected:
            return False
        del self._data[key]
        return True
