"""The fencing-token tests. test_paused_holder_is_fenced_out is the kill-shot
chart in miniature: the exact scenario Chaos Mesh TimeChaos will reproduce on
the live cluster, proven here first with a fake clock."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from pytest import raises

from orbiter.kv.store import FakeClock, InMemoryKV
from orbiter.leases.fencing import FencedWriter, LeaseManager, StaleLeaseError

TTL = 10.0


def make_manager(clock: FakeClock) -> LeaseManager:
    return LeaseManager(InMemoryKV(clock), ttl_s=TTL)


async def test_acquire_and_release() -> None:
    clock = FakeClock()
    mgr = make_manager(clock)
    lease = await mgr.acquire("job-1", "worker-a")
    assert lease is not None and lease.token == 1
    assert await mgr.acquire("job-1", "worker-b") is None  # held
    assert await mgr.release(lease)
    successor = await mgr.acquire("job-1", "worker-b")
    assert successor is not None and successor.token > lease.token


async def test_expired_lease_can_be_taken_over() -> None:
    clock = FakeClock()
    mgr = make_manager(clock)
    a = await mgr.acquire("job-1", "worker-a")
    assert a is not None
    clock.advance(TTL + 1)
    b = await mgr.acquire("job-1", "worker-b")
    assert b is not None and b.token > a.token


async def test_paused_holder_is_fenced_out() -> None:
    """THE scenario. Worker A acquires the lease, then pauses (GC, VM freeze,
    clock skew) past expiry. Worker B legitimately takes over and writes.
    A wakes up still believing it owns the job and writes with its stale
    token — and the WRITE is rejected, because the lock alone never could."""
    clock = FakeClock()
    mgr = make_manager(clock)
    writer = FencedWriter()

    a = await mgr.acquire("job-1", "worker-a")
    assert a is not None  # A holds the lease...
    clock.advance(TTL + 5)  # ...and pauses past its expiry.

    b = await mgr.acquire("job-1", "worker-b")
    assert b is not None  # B's acquisition is legitimate,
    writer.check("job-1", b.token)  # and B's write is accepted.

    with raises(StaleLeaseError):  # A wakes and writes: REJECTED.
        writer.check("job-1", a.token)

    writer.check("job-1", b.token)  # B keeps working undisturbed.


async def test_release_of_stale_lease_does_not_drop_successor() -> None:
    """A naive DEL on release would delete worker B's lease when stale worker
    A finally calls release. Compare-and-delete refuses."""
    clock = FakeClock()
    mgr = make_manager(clock)
    a = await mgr.acquire("job-1", "worker-a")
    assert a is not None
    clock.advance(TTL + 1)
    b = await mgr.acquire("job-1", "worker-b")
    assert b is not None
    assert not await mgr.release(a)  # stale release is a no-op
    assert await mgr.acquire("job-1", "worker-c") is None  # B still holds it


@given(pauses=st.lists(st.floats(min_value=0.0, max_value=100.0), min_size=1, max_size=20))
async def test_tokens_are_strictly_monotonic(pauses: list[float]) -> None:
    """However acquisitions and expiries interleave, every successful
    acquisition carries a strictly greater token than the one before it —
    the invariant the whole fencing scheme rests on."""
    clock = FakeClock()
    mgr = make_manager(clock)
    last_token = 0
    for i, pause in enumerate(pauses):
        clock.advance(pause)
        lease = await mgr.acquire("job-1", f"worker-{i}")
        if lease is not None:
            assert lease.token > last_token
            last_token = lease.token
