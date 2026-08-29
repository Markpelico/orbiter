"""Idempotent execution guard: a duplicate delivery must be a no-op, a
concurrent delivery must be excluded, and a crashed attempt must not wedge
the job forever."""

from __future__ import annotations

from orbiter.kv.store import FakeClock, InMemoryKV
from orbiter.worker.idempotency import ClaimResult, ExecutionGuard

CLAIM_TTL = 30.0
DONE_TTL = 3600.0


def make_guard(clock: FakeClock) -> ExecutionGuard:
    return ExecutionGuard(InMemoryKV(clock), claim_ttl_s=CLAIM_TTL, done_ttl_s=DONE_TTL)


async def test_first_delivery_claims() -> None:
    guard = make_guard(FakeClock())
    assert await guard.try_claim("job-1", "w1:1") is ClaimResult.CLAIMED


async def test_concurrent_delivery_is_excluded() -> None:
    guard = make_guard(FakeClock())
    assert await guard.try_claim("job-1", "w1:1") is ClaimResult.CLAIMED
    assert await guard.try_claim("job-1", "w2:1") is ClaimResult.IN_PROGRESS


async def test_delivery_after_completion_is_a_noop() -> None:
    """The at-least-once classic: worker finishes, dies before acking, the
    broker redelivers. The redelivery must not re-execute."""
    guard = make_guard(FakeClock())
    assert await guard.try_claim("job-1", "w1:1") is ClaimResult.CLAIMED
    await guard.mark_done("job-1", "w1:1")
    assert await guard.try_claim("job-1", "w2:2") is ClaimResult.ALREADY_DONE


async def test_crashed_attempt_expires_and_frees_the_job() -> None:
    """A worker that dies mid-execution never releases its claim. The TTL
    frees the job for the redelivery instead of wedging it forever."""
    clock = FakeClock()
    guard = make_guard(clock)
    assert await guard.try_claim("job-1", "w1:1") is ClaimResult.CLAIMED
    # w1 crashes. No release. Time passes.
    clock.advance(CLAIM_TTL + 1)
    assert await guard.try_claim("job-1", "w2:2") is ClaimResult.CLAIMED


async def test_released_claim_allows_retry() -> None:
    guard = make_guard(FakeClock())
    assert await guard.try_claim("job-1", "w1:1") is ClaimResult.CLAIMED
    await guard.release_claim("job-1", "w1:1")
    assert await guard.try_claim("job-1", "w1:2") is ClaimResult.CLAIMED


async def test_release_by_wrong_delivery_is_a_noop() -> None:
    guard = make_guard(FakeClock())
    assert await guard.try_claim("job-1", "w1:1") is ClaimResult.CLAIMED
    await guard.release_claim("job-1", "w2:9")  # not the owner
    assert await guard.try_claim("job-1", "w2:9") is ClaimResult.IN_PROGRESS
