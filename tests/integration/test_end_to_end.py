"""The walking skeleton, proven: HTTP submit -> outbox -> relay -> JetStream
-> worker -> Postgres -> status endpoint. Everything real except the clock."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

WaitForState = Callable[[httpx.AsyncClient, str, str, float], Awaitable[dict[str, Any]]]

pytestmark = pytest.mark.integration


async def test_job_travels_end_to_end(
    running_platform: httpx.AsyncClient, wait_for_state: WaitForState
) -> None:
    client = running_platform
    submit = await client.post(
        "/jobs",
        json={"duration_ms": 100, "failure_rate": 0.0},
        headers={"Idempotency-Key": f"e2e-{uuid.uuid4()}"},
    )
    assert submit.status_code == 201
    job_id = submit.json()["id"]

    job = await wait_for_state(client, job_id, "succeeded", 30.0)
    event_names = [e["event"] for e in job["events"]]
    assert event_names[:2] == ["submitted", "enqueued"]
    assert "started" in event_names
    assert event_names[-1] == "completed"
    assert job["result"]["elapsed_ms"] >= 0


async def test_duplicate_submit_returns_the_same_job(
    running_platform: httpx.AsyncClient,
) -> None:
    client = running_platform
    key = f"dup-{uuid.uuid4()}"
    body = {"duration_ms": 50, "failure_rate": 0.0}
    first = await client.post("/jobs", json=body, headers={"Idempotency-Key": key})
    second = await client.post("/jobs", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201 and first.json()["created"] is True
    assert second.status_code == 200 and second.json()["created"] is False
    assert first.json()["id"] == second.json()["id"]


async def test_always_failing_job_exhausts_retries(
    running_platform: httpx.AsyncClient, wait_for_state: WaitForState
) -> None:
    client = running_platform
    submit = await client.post(
        "/jobs",
        json={"duration_ms": 10, "failure_rate": 1.0},
        headers={"Idempotency-Key": f"fail-{uuid.uuid4()}"},
    )
    assert submit.status_code == 201
    job = await wait_for_state(client, submit.json()["id"], "failed", 60.0)
    event_names = [e["event"] for e in job["events"]]
    assert event_names.count("requeued") >= 1  # it retried before giving up
    assert event_names[-1] == "failed"


async def test_missing_idempotency_key_is_rejected(running_platform: httpx.AsyncClient) -> None:
    response = await running_platform.post("/jobs", json={"duration_ms": 10})
    assert response.status_code == 422
