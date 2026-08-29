"""The simulation stub — ORBITER's one and only job type.

Sleeps for the requested duration in small slices (so shutdown stays
responsive) and fails with the requested probability. The workload is a prop;
the platform is the product.
"""

from __future__ import annotations

import asyncio
import random
import time


class SimulatedFailure(Exception):
    """The job's own failure mode — retryable by policy."""


_SLICE_S = 0.1


async def execute(duration_ms: int, failure_rate: float, rng: random.Random) -> dict[str, object]:
    will_fail = rng.random() < failure_rate
    started = time.monotonic()
    remaining = duration_ms / 1000.0
    while remaining > 0:
        step = min(_SLICE_S, remaining)
        await asyncio.sleep(step)
        remaining -= step
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if will_fail:
        raise SimulatedFailure(f"simulated failure after {elapsed_ms}ms")
    return {"elapsed_ms": elapsed_ms}
