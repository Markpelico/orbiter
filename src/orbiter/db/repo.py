"""Postgres repository. All multi-row invariants live inside transactions here.

State changes go through the domain state machine before touching the jobs
table, so an illegal transition can never be recorded — the audit trail stays
an audit trail.
"""

from __future__ import annotations

import json
import uuid
from importlib import resources
from typing import Any

import asyncpg

from orbiter.domain.model import EventType, JobEvent, JobState
from orbiter.domain.state_machine import apply
from orbiter.leases.fencing import StaleLeaseError
from orbiter.telemetry import current_carrier


async def create_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(database_url, min_size=1, max_size=10)


# Every service applies the schema at startup, concurrently. CREATE TABLE IF
# NOT EXISTS is NOT concurrency-safe: two sessions can both see "not exists"
# and collide in the catalog (pg_type_typname_nsp_index). An advisory lock
# serializes the DDL; the xact variant releases itself at commit.
_SCHEMA_LOCK_KEY = 0x0_5B17E5  # arbitrary, must simply be unique to ORBITER


async def apply_schema(pool: asyncpg.Pool) -> None:
    schema = (resources.files("orbiter.db") / "schema.sql").read_text(encoding="utf-8")
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _SCHEMA_LOCK_KEY)
        await conn.execute(schema)


async def submit_job(
    pool: asyncpg.Pool,
    idempotency_key: str,
    payload: dict[str, Any],
    subject: str,
) -> tuple[uuid.UUID, bool]:
    """Insert job + SUBMITTED/ENQUEUED events + outbox row in one transaction.

    Returns (job_id, created). If the idempotency key was seen before, returns
    the existing job with created=False — Stripe semantics.
    """
    job_id = uuid.uuid4()
    payload_json = json.dumps(payload)
    async with pool.acquire() as conn, conn.transaction():
        inserted = await conn.fetchval(
            """
            INSERT INTO jobs (id, idempotency_key, payload, state)
            VALUES ($1, $2, $3::jsonb, $4)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            job_id,
            idempotency_key,
            payload_json,
            JobState.QUEUED.value,
        )
        if inserted is None:
            existing = await conn.fetchval(
                "SELECT id FROM jobs WHERE idempotency_key = $1", idempotency_key
            )
            return existing, False
        await conn.executemany(
            "INSERT INTO job_events (job_id, event) VALUES ($1, $2)",
            [(job_id, EventType.SUBMITTED.value), (job_id, EventType.ENQUEUED.value)],
        )
        # The trace context rides in the message itself: it is the only
        # vehicle that survives the trip through a table and a broker.
        message = json.dumps(
            {"job_id": str(job_id), "payload": payload, "traceparent": current_carrier()}
        )
        await conn.execute(
            "INSERT INTO outbox (job_id, subject, payload) VALUES ($1, $2, $3::jsonb)",
            job_id,
            subject,
            message,
        )
    return job_id, True


async def get_job(pool: asyncpg.Pool, job_id: uuid.UUID) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, idempotency_key, payload, state, attempts, result,
                   created_at, updated_at
            FROM jobs WHERE id = $1
            """,
            job_id,
        )
        if row is None:
            return None
        events = await conn.fetch(
            "SELECT event, attempt, detail, at FROM job_events WHERE job_id = $1 ORDER BY id",
            job_id,
        )
    return {
        "id": str(row["id"]),
        "state": row["state"],
        "payload": json.loads(row["payload"]),
        "attempts": row["attempts"],
        "result": json.loads(row["result"]) if row["result"] else None,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "events": [
            {
                "event": e["event"],
                "attempt": e["attempt"],
                "detail": json.loads(e["detail"]),
                "at": e["at"].isoformat(),
            }
            for e in events
        ],
    }


async def _apply_event(
    conn: asyncpg.Connection,
    job_id: uuid.UUID,
    event: EventType,
    attempt: int,
    detail: dict[str, Any] | None,
    fence_token: int | None,
    result: dict[str, Any] | None,
) -> JobState:
    row = await conn.fetchrow(
        "SELECT state, attempts, fence_token FROM jobs WHERE id = $1 FOR UPDATE", job_id
    )
    if row is None:
        raise LookupError(f"job {job_id} not found")
    current = JobState(row["state"])
    next_state = apply(current, event)  # raises IllegalTransition
    token = fence_token if fence_token is not None else row["fence_token"]
    updated = await conn.fetchval(
        """
        UPDATE jobs
        SET state = $2,
            attempts = GREATEST(attempts, $3),
            fence_token = $4,
            result = COALESCE($5::jsonb, result),
            updated_at = now()
        WHERE id = $1 AND fence_token <= $4
        RETURNING id
        """,
        job_id,
        next_state.value,
        attempt,
        token,
        json.dumps(result) if result is not None else None,
    )
    if updated is None:
        raise StaleLeaseError(str(job_id), token, row["fence_token"])
    await conn.execute(
        "INSERT INTO job_events (job_id, event, attempt, detail) VALUES ($1, $2, $3, $4::jsonb)",
        job_id,
        event.value,
        attempt,
        json.dumps(detail or {}),
    )
    return next_state


async def record_event(
    pool: asyncpg.Pool,
    job_id: uuid.UUID,
    event: EventType,
    attempt: int = 0,
    detail: dict[str, Any] | None = None,
    fence_token: int | None = None,
    result: dict[str, Any] | None = None,
) -> JobState:
    """Validate the transition, append the event, refresh the projection.

    When ``fence_token`` is given, the jobs-table UPDATE carries the fencing
    check in its WHERE clause: an older token matches zero rows and the whole
    transaction rolls back with StaleLeaseError. This is the write-site half
    of the fenced lease.
    """
    async with pool.acquire() as conn, conn.transaction():
        return await _apply_event(conn, job_id, event, attempt, detail, fence_token, result)


async def replay_job(pool: asyncpg.Pool, job_id: uuid.UUID, subject: str) -> JobState | None:
    """Operator replay of a dead-lettered job: REPLAYED event + a fresh outbox
    row, in one transaction. Returns None if the job does not exist; raises
    IllegalTransition if it is not in DEAD_LETTER."""
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow("SELECT payload::text AS payload FROM jobs WHERE id = $1", job_id)
        if row is None:
            return None
        state = await _apply_event(conn, job_id, EventType.REPLAYED, 0, None, None, None)
        message = json.dumps({"job_id": str(job_id), "payload": json.loads(row["payload"])})
        await conn.execute(
            "INSERT INTO outbox (job_id, subject, payload) VALUES ($1, $2, $3::jsonb)",
            job_id,
            subject,
            message,
        )
    return state


async def list_jobs_by_state(pool: asyncpg.Pool, state: JobState) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, payload::text AS payload, attempts, updated_at
            FROM jobs WHERE state = $1 ORDER BY updated_at DESC LIMIT 200
            """,
            state.value,
        )
    return [
        {
            "id": str(r["id"]),
            "payload": json.loads(r["payload"]),
            "attempts": r["attempts"],
            "updated_at": r["updated_at"].isoformat(),
        }
        for r in rows
    ]


async def list_recent_jobs(pool: asyncpg.Pool, limit: int = 25) -> list[dict[str, Any]]:
    """The chaos page's window: the newest jobs and where they stand."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, state, attempts, created_at, updated_at
            FROM jobs ORDER BY created_at DESC LIMIT $1
            """,
            limit,
        )
    return [
        {
            "id": str(r["id"]),
            "state": r["state"],
            "attempts": r["attempts"],
            "created_at": r["created_at"].isoformat(),
            "updated_at": r["updated_at"].isoformat(),
        }
        for r in rows
    ]


async def replay_events(pool: asyncpg.Pool, job_id: uuid.UUID) -> list[JobEvent]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT event, attempt, detail, at FROM job_events WHERE job_id = $1 ORDER BY id",
            job_id,
        )
    return [
        JobEvent(
            type=EventType(r["event"]),
            attempt=r["attempt"],
            detail=json.loads(r["detail"]),
            at=r["at"],
        )
        for r in rows
    ]
