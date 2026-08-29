from __future__ import annotations

import random

import pytest

from orbiter.domain.model import JobPayload
from orbiter.worker.executor import SimulatedFailure, execute


async def test_success_reports_elapsed() -> None:
    result = await execute(duration_ms=10, failure_rate=0.0, rng=random.Random(1))
    elapsed = result["elapsed_ms"]
    assert isinstance(elapsed, int) and elapsed >= 0


async def test_failure_rate_one_always_fails() -> None:
    with pytest.raises(SimulatedFailure):
        await execute(duration_ms=0, failure_rate=1.0, rng=random.Random(1))


async def test_deterministic_under_seed() -> None:
    """Same seed, same verdict — the seed of the deterministic sim harness."""

    async def verdict(seed: int) -> bool:
        try:
            await execute(duration_ms=0, failure_rate=0.5, rng=random.Random(seed))
            return True
        except SimulatedFailure:
            return False

    assert [await verdict(s) for s in range(10)] == [await verdict(s) for s in range(10)]


def test_payload_validation() -> None:
    with pytest.raises(ValueError):
        JobPayload(duration_ms=-1)
    with pytest.raises(ValueError):
        JobPayload(duration_ms=0, failure_rate=1.5)
