"""Distributed leases with fencing tokens.

The failure this prevents: worker A holds a TTL lease on a job, then pauses —
GC, VM freeze, or a skewed clock. The lease expires, worker B legitimately
acquires it and starts writing. A wakes up, still believing it owns the job,
and writes too. Two writers, silent corruption. A TTL alone cannot prevent
this because A cannot know it paused.

The fix (Kleppmann's critique of Redlock): every acquisition gets a token from
a monotonically increasing counter, and the *protected resource* rejects any
write carrying a token older than the newest it has accepted. The stale
holder's writes bounce off the data, not off the lock.

Chaos Mesh TimeChaos reproduces the pause in the live demo; the unit tests
reproduce it here with a fake clock.
"""

from __future__ import annotations

from dataclasses import dataclass

from orbiter.kv.store import KeyValueStore


class StaleLeaseError(Exception):
    def __init__(self, resource: str, token: int, newest_seen: int) -> None:
        self.resource = resource
        self.token = token
        self.newest_seen = newest_seen
        super().__init__(
            f"write to {resource!r} with fencing token {token} rejected: "
            f"a newer holder (token {newest_seen}) has already written"
        )


@dataclass(frozen=True, slots=True)
class Lease:
    resource: str
    holder: str
    token: int


class LeaseManager:
    """Acquire/release leases in a shared KV store.

    The token counter is incremented *before* the SET NX, so a failed acquire
    burns a token. That is fine: fencing only needs monotonicity, not density.
    """

    def __init__(self, kv: KeyValueStore, ttl_s: float) -> None:
        self._kv = kv
        self._ttl_s = ttl_s

    @staticmethod
    def _lease_key(resource: str) -> str:
        return f"orbiter:lease:{resource}"

    @staticmethod
    def _token_key(resource: str) -> str:
        return f"orbiter:lease:{resource}:token"

    async def acquire(self, resource: str, holder: str) -> Lease | None:
        token = await self._kv.incr(self._token_key(resource))
        acquired = await self._kv.set_if_absent(
            self._lease_key(resource), f"{holder}:{token}", self._ttl_s
        )
        if not acquired:
            return None
        return Lease(resource=resource, holder=holder, token=token)

    async def release(self, lease: Lease) -> bool:
        """Release only if we still hold it — a plain DEL could drop a
        successor's lease, which is the same two-writers bug in a party hat."""
        return await self._kv.compare_and_delete(
            self._lease_key(lease.resource), f"{lease.holder}:{lease.token}"
        )


class FencedWriter:
    """Guards a write path with fencing-token checks.

    In production the check lives at the storage layer (a WHERE clause on the
    accepted-token column). This class is that check, factored so both the
    Postgres repo and the tests share one implementation of the rule:
    accept token >= newest accepted, reject older.
    """

    def __init__(self) -> None:
        self._newest_accepted: dict[str, int] = {}

    def check(self, resource: str, token: int) -> None:
        newest = self._newest_accepted.get(resource, 0)
        if token < newest:
            raise StaleLeaseError(resource, token, newest)
        self._newest_accepted[resource] = token

    def newest_accepted(self, resource: str) -> int:
        return self._newest_accepted.get(resource, 0)
