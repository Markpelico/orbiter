"""Bounded admission control.

The backpressure decision (ADR-0004): when submissions outrun capacity we
REJECT loudly — 429 with Retry-After — rather than buffer quietly. An
unbounded buffer converts overload into latency and then into an outage,
after having hidden the problem exactly as long as it was cheap to fix.
Rejection keeps the failure at the edge, visible, and retryable by the
client, which (unlike the server) knows whether the work still matters.

Per-replica and in-process on purpose: global admission needs shared state
and becomes its own availability problem. Each replica defending its own
capacity composes with horizontal scaling.
"""

from __future__ import annotations


class AdmissionController:
    def __init__(self, capacity: int, retry_after_s: int = 1) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self.retry_after_s = retry_after_s
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def available(self) -> int:
        return self.capacity - self._in_flight

    def try_acquire(self) -> bool:
        if self._in_flight >= self.capacity:
            return False
        self._in_flight += 1
        return True

    def release(self) -> None:
        if self._in_flight <= 0:
            raise RuntimeError("release() without a matching try_acquire()")
        self._in_flight -= 1
