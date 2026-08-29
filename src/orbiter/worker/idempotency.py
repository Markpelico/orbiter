"""Idempotent execution guard.

At-least-once delivery means a job WILL be delivered twice: redelivery after a
missed ack, a worker that died after finishing but before acking, an operator
replay. The guard makes the second execution a no-op instead of a double-write.

Two keys per job:
- a ``done`` marker: set after successful completion; any later delivery
  short-circuits.
- a ``claim``: SET NX taken before executing, so two concurrent deliveries of
  the same job cannot both run. The claim carries the delivery attempt so a
  crashed attempt's claim expires (TTL) rather than wedging the job forever.
"""

from __future__ import annotations

import enum

from orbiter.kv.store import KeyValueStore


class ClaimResult(enum.Enum):
    CLAIMED = "claimed"  # we own this execution; run it
    ALREADY_DONE = "already_done"  # completed previously; ack and move on
    IN_PROGRESS = "in_progress"  # another delivery is executing right now


class ExecutionGuard:
    def __init__(self, kv: KeyValueStore, claim_ttl_s: float, done_ttl_s: float) -> None:
        self._kv = kv
        self._claim_ttl_s = claim_ttl_s
        self._done_ttl_s = done_ttl_s

    @staticmethod
    def _done_key(job_id: str) -> str:
        return f"orbiter:exec:{job_id}:done"

    @staticmethod
    def _claim_key(job_id: str) -> str:
        return f"orbiter:exec:{job_id}:claim"

    async def try_claim(self, job_id: str, delivery: str) -> ClaimResult:
        if await self._kv.get(self._done_key(job_id)) is not None:
            return ClaimResult.ALREADY_DONE
        claimed = await self._kv.set_if_absent(self._claim_key(job_id), delivery, self._claim_ttl_s)
        if not claimed:
            return ClaimResult.IN_PROGRESS
        return ClaimResult.CLAIMED

    async def mark_done(self, job_id: str, delivery: str) -> None:
        await self._kv.set_if_absent(self._done_key(job_id), delivery, self._done_ttl_s)
        await self._kv.compare_and_delete(self._claim_key(job_id), delivery)

    async def release_claim(self, job_id: str, delivery: str) -> None:
        """On a retryable failure, free the claim so the redelivery can run."""
        await self._kv.compare_and_delete(self._claim_key(job_id), delivery)
