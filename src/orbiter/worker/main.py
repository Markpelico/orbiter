"""The worker: pulls jobs from JetStream, executes them idempotently under a
fenced lease, and shuts down gracefully on SIGTERM.

On a spot-instance fleet SIGTERM is not an edge case — it is Tuesday. The
contract: stop fetching, finish (or fail over) the in-flight job, release the
lease, and exit inside the grace period.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import signal
import socket
import uuid
from typing import Any

import nats
from nats.js.api import AckPolicy, ConsumerConfig, RetentionPolicy, StreamConfig

from orbiter.config import Settings
from orbiter.db import repo
from orbiter.domain.model import EventType
from orbiter.kv.valkey import ValkeyKV
from orbiter.leases.fencing import LeaseManager, StaleLeaseError
from orbiter.worker.executor import SimulatedFailure, execute
from orbiter.worker.idempotency import ClaimResult, ExecutionGuard

log = logging.getLogger("orbiter.worker")


async def ensure_stream(js: Any, settings: Settings) -> None:
    """Create the work-queue stream + durable pull consumer if absent."""
    with contextlib.suppress(Exception):
        await js.add_stream(
            StreamConfig(
                name=settings.stream_name,
                subjects=[settings.subject_jobs],
                retention=RetentionPolicy.WORK_QUEUE,
            )
        )
    with contextlib.suppress(Exception):
        await js.add_consumer(
            settings.stream_name,
            ConsumerConfig(
                durable_name=settings.consumer_durable,
                ack_policy=AckPolicy.EXPLICIT,
                ack_wait=settings.ack_wait_s,
                max_deliver=settings.max_deliver,
            ),
        )


class Worker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.shutdown = asyncio.Event()
        self.rng = random.Random()

    async def run(self) -> None:
        settings = self.settings
        pool = await repo.create_pool(settings.database_url)
        await repo.apply_schema(pool)
        kv = ValkeyKV(settings.valkey_url)
        guard = ExecutionGuard(
            kv, claim_ttl_s=settings.ack_wait_s, done_ttl_s=settings.exec_guard_ttl_s
        )
        leases = LeaseManager(kv, ttl_s=settings.lease_ttl_s)
        nc = await nats.connect(settings.nats_url)
        js = nc.jetstream()
        await ensure_stream(js, settings)
        sub = await js.pull_subscribe(
            settings.subject_jobs, durable=settings.consumer_durable, stream=settings.stream_name
        )
        log.info("worker %s started", self.worker_id)
        try:
            while not self.shutdown.is_set():
                try:
                    msgs = await sub.fetch(1, timeout=settings.worker_fetch_timeout_s)
                except TimeoutError:
                    continue
                except nats.errors.TimeoutError:
                    continue
                for msg in msgs:
                    await self.process(msg, pool, guard, leases)
        finally:
            log.info("worker %s draining", self.worker_id)
            await nc.drain()
            await kv.aclose()
            await pool.close()

    async def process(
        self, msg: Any, pool: Any, guard: ExecutionGuard, leases: LeaseManager
    ) -> None:
        settings = self.settings
        data = json.loads(msg.data)
        job_id = uuid.UUID(data["job_id"])
        payload = data["payload"]
        attempt = int(msg.metadata.num_delivered)
        delivery = f"{self.worker_id}:{attempt}"

        claim = await guard.try_claim(str(job_id), delivery)
        if claim is ClaimResult.ALREADY_DONE:
            log.info("job %s already done; acking duplicate delivery", job_id)
            await msg.ack()
            return
        if claim is ClaimResult.IN_PROGRESS:
            log.info("job %s already executing elsewhere; delaying redelivery", job_id)
            await msg.nak(delay=settings.ack_wait_s)
            return

        lease = await leases.acquire(str(job_id), self.worker_id)
        if lease is None:
            await guard.release_claim(str(job_id), delivery)
            await msg.nak(delay=settings.lease_ttl_s)
            return

        try:
            await repo.record_event(
                pool, job_id, EventType.STARTED, attempt=attempt, fence_token=lease.token
            )
            result = await execute(
                int(payload["duration_ms"]), float(payload.get("failure_rate", 0.0)), self.rng
            )
            await repo.record_event(
                pool,
                job_id,
                EventType.COMPLETED,
                attempt=attempt,
                fence_token=lease.token,
                result=result,
            )
            await guard.mark_done(str(job_id), delivery)
            await msg.ack()
            log.info("job %s succeeded on attempt %d", job_id, attempt)
        except SimulatedFailure as exc:
            if attempt < settings.max_deliver:
                await repo.record_event(
                    pool,
                    job_id,
                    EventType.REQUEUED,
                    attempt=attempt,
                    fence_token=lease.token,
                    detail={"error": str(exc)},
                )
                await guard.release_claim(str(job_id), delivery)
                await msg.nak(delay=min(2**attempt, 30))
                log.warning("job %s failed attempt %d; requeued", job_id, attempt)
            else:
                await repo.record_event(
                    pool,
                    job_id,
                    EventType.FAILED,
                    attempt=attempt,
                    fence_token=lease.token,
                    detail={"error": str(exc), "reason": "retries exhausted"},
                )
                await guard.release_claim(str(job_id), delivery)
                await msg.term()
                log.error("job %s failed permanently after %d attempts", job_id, attempt)
        except StaleLeaseError:
            # A newer holder owns this job now; our writes were rejected at the
            # data. Drop the message without acking — their delivery wins.
            log.warning("job %s: stale lease detected, standing down", job_id)
        finally:
            await leases.release(lease)

    def request_shutdown(self) -> None:
        log.info("SIGTERM received: finishing in-flight work, taking no more")
        self.shutdown.set()


async def amain() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    worker = Worker(Settings())
    loop = asyncio.get_running_loop()
    with contextlib.suppress(NotImplementedError):  # signals unavailable on Windows
        loop.add_signal_handler(signal.SIGTERM, worker.request_shutdown)
        loop.add_signal_handler(signal.SIGINT, worker.request_shutdown)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(amain())
