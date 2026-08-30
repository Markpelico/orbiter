"""The dead-letter path for poison messages.

A poison message is one that takes its worker down before any application
code can handle it — the worker never acks, naks-with-thought, or terms; the
broker just sees the delivery vanish. Without a backstop, JetStream redelivers
it forever and it kills every worker in the fleet, one AckWait at a time.

MaxDeliver caps that: after N deliveries JetStream stops redelivering and
emits a max-deliveries advisory. Advisories are fire-and-forget, which means
a listener that is down for a deploy would silently lose quarantines — so
ORBITER captures the advisory subject into its own stream and consumes it
with a durable pull consumer. A quarantine can be late; it cannot be lost.

For each advisory, this listener:

1. fetches the poisoned message from the work stream by sequence,
2. copies it to the DLQ stream (durable, inspectable, deduped by msg-id),
3. records DEAD_LETTERED in the audit trail,
4. deletes the original so the work stream stays clean, and only then
5. acks the advisory.

Replay is an operator action through the API: POST /jobs/{id}/replay.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
import uuid
from dataclasses import dataclass
from typing import Any

import nats
from nats.js.api import AckPolicy, ConsumerConfig, StreamConfig

from orbiter.config import Settings
from orbiter.db import repo
from orbiter.domain.model import EventType
from orbiter.domain.state_machine import IllegalTransition
from orbiter.telemetry import context_from, init_telemetry, meter, tracer

log = logging.getLogger("orbiter.dlq")

_ADVISORY_TYPE = "io.nats.jetstream.advisory.v1.max_deliver"


def advisory_subject(stream: str, consumer: str) -> str:
    return f"$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.{stream}.{consumer}"


@dataclass(frozen=True, slots=True)
class MaxDeliveriesAdvisory:
    stream: str
    consumer: str
    stream_seq: int
    deliveries: int


def parse_advisory(raw: bytes) -> MaxDeliveriesAdvisory | None:
    """Parse a max-deliveries advisory; None for anything else on the subject."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    # json.loads(b"0") is a perfectly valid int — found by Hypothesis in CI.
    if not isinstance(data, dict) or data.get("type") != _ADVISORY_TYPE:
        return None
    try:
        return MaxDeliveriesAdvisory(
            stream=str(data["stream"]),
            consumer=str(data["consumer"]),
            stream_seq=int(data["stream_seq"]),
            deliveries=int(data["deliveries"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def ensure_streams(js: Any, settings: Settings) -> None:
    """DLQ stream, plus a stream capturing the advisory subject so that
    max-deliveries events survive listener downtime."""
    with contextlib.suppress(Exception):
        await js.add_stream(
            StreamConfig(name=settings.dlq_stream_name, subjects=[settings.subject_dlq])
        )
    with contextlib.suppress(Exception):
        await js.add_stream(
            StreamConfig(
                name=settings.advisory_stream_name,
                subjects=[advisory_subject(settings.stream_name, settings.consumer_durable)],
            )
        )
    with contextlib.suppress(Exception):
        await js.add_consumer(
            settings.advisory_stream_name,
            ConsumerConfig(
                durable_name=settings.dlq_consumer_durable,
                ack_policy=AckPolicy.EXPLICIT,
                filter_subject=advisory_subject(settings.stream_name, settings.consumer_durable),
            ),
        )


_quarantined = meter().create_counter(
    "orbiter.jobs.quarantined", description="Poison jobs moved to the DLQ"
)


async def quarantine(js: Any, pool: Any, settings: Settings, adv: MaxDeliveriesAdvisory) -> None:
    raw = await js.get_msg(settings.stream_name, adv.stream_seq)
    body = json.loads(raw.data)
    job_id = uuid.UUID(body["job_id"])
    # The poisoned message still carries its submit-time traceparent, so the
    # quarantine appears in the SAME trace as the original HTTP submit.
    with tracer().start_as_current_span(
        "dlq.quarantine",
        context=context_from(body.get("traceparent")),
        attributes={"orbiter.job_id": str(job_id), "orbiter.deliveries": adv.deliveries},
    ):
        await _quarantine_inner(js, pool, settings, adv, raw, job_id)
    _quarantined.add(1)


async def _quarantine_inner(
    js: Any,
    pool: Any,
    settings: Settings,
    adv: MaxDeliveriesAdvisory,
    raw: Any,
    job_id: uuid.UUID,
) -> None:
    # Copy before delete, always: the DLQ publish is deduped by msg-id, so
    # crashing and re-running this block is safe at every point.
    await js.publish(
        settings.subject_dlq,
        raw.data,
        headers={"Nats-Msg-Id": f"dlq-{settings.stream_name}-{adv.stream_seq}"},
    )
    try:
        await repo.record_event(
            pool,
            job_id,
            EventType.DEAD_LETTERED,
            attempt=adv.deliveries,
            detail={"stream_seq": adv.stream_seq, "deliveries": adv.deliveries},
        )
    except IllegalTransition:
        # Duplicate advisory or already-terminal job: the audit trail already
        # tells the true story; just clean the work stream.
        log.warning("job %s: dead-letter event not applicable; cleaning up", job_id)
    await js.delete_msg(settings.stream_name, adv.stream_seq)
    log.error("job %s quarantined after %d deliveries", job_id, adv.deliveries)


async def run(settings: Settings, stop: asyncio.Event) -> None:
    pool = await repo.create_pool(settings.database_url)
    await repo.apply_schema(pool)
    nc = await nats.connect(settings.nats_url)
    js = nc.jetstream()
    await ensure_streams(js, settings)
    sub = await js.pull_subscribe(
        advisory_subject(settings.stream_name, settings.consumer_durable),
        durable=settings.dlq_consumer_durable,
        stream=settings.advisory_stream_name,
    )
    log.info("dlq listener started")
    try:
        while not stop.is_set():
            try:
                msgs = await sub.fetch(1, timeout=1)
            except TimeoutError:
                continue
            except nats.errors.TimeoutError:
                continue
            for msg in msgs:
                adv = parse_advisory(msg.data)
                log.info("advisory received: %s", adv)
                if adv is not None:
                    try:
                        await quarantine(js, pool, settings, adv)
                    except Exception:
                        # An advisory whose quarantine crashes forever would
                        # itself be a poison message. Log loudly, ack anyway;
                        # the job's absence from DLQ is visible in the audit
                        # trail and the work stream.
                        log.exception("quarantine failed for stream_seq=%d", adv.stream_seq)
                await msg.ack()
    finally:
        await nc.close()
        await pool.close()


async def amain() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = Settings()
    init_telemetry("orbiter-dlq", settings.otel_endpoint)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    with contextlib.suppress(NotImplementedError):
        loop.add_signal_handler(signal.SIGTERM, stop.set)
        loop.add_signal_handler(signal.SIGINT, stop.set)
    await run(settings, stop)


if __name__ == "__main__":
    asyncio.run(amain())
