"""The outbox relay: the second half of the transactional outbox.

Polls unpublished outbox rows and publishes them to JetStream. Crash-safety
is layered:

1. The row and the job were committed atomically, so nothing can be published
   that does not exist, and nothing can exist that will not be published.
2. If the relay crashes between publish and mark-published, the row is
   re-published — with the same Nats-Msg-Id header, which JetStream dedupes
   inside its duplicate window.
3. Beyond the dedupe window, the worker's idempotent execution guard makes
   the duplicate a no-op anyway.

At-least-once transport, effectively-once processing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

import nats

from orbiter.config import Settings
from orbiter.db import repo
from orbiter.worker.main import ensure_stream

log = logging.getLogger("orbiter.relay")


async def relay_once(pool: object, js: object, settings: Settings) -> int:
    """Publish one batch. Returns the number of rows published."""
    import asyncpg  # local import keeps module importable without driver at type-check time

    assert isinstance(pool, asyncpg.Pool)
    async with pool.acquire() as conn, conn.transaction():
        rows = await conn.fetch(
            """
            SELECT id, subject, payload::text AS payload
            FROM outbox
            WHERE published_at IS NULL
            ORDER BY id
            LIMIT $1
            FOR UPDATE SKIP LOCKED
            """,
            settings.relay_batch_size,
        )
        for row in rows:
            await js.publish(  # type: ignore[attr-defined]
                row["subject"],
                row["payload"].encode(),
                headers={"Nats-Msg-Id": f"outbox-{row['id']}"},
            )
        if rows:
            await conn.execute(
                "UPDATE outbox SET published_at = now() WHERE id = ANY($1::bigint[])",
                [r["id"] for r in rows],
            )
    return len(rows)


async def run(settings: Settings, stop: asyncio.Event) -> None:
    pool = await repo.create_pool(settings.database_url)
    await repo.apply_schema(pool)
    nc = await nats.connect(settings.nats_url)
    js = nc.jetstream()
    await ensure_stream(js, settings)
    log.info("outbox relay started")
    try:
        while not stop.is_set():
            published = await relay_once(pool, js, settings)
            if published:
                log.info("published %d outbox rows", published)
            else:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=settings.relay_poll_interval_s)
    finally:
        await nc.drain()
        await pool.close()


async def amain() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    with contextlib.suppress(NotImplementedError):
        loop.add_signal_handler(signal.SIGTERM, stop.set)
        loop.add_signal_handler(signal.SIGINT, stop.set)
    await run(Settings(), stop)


if __name__ == "__main__":
    asyncio.run(amain())
