"""The walking skeleton, proven: HTTP submit -> outbox -> relay -> JetStream
-> worker -> Postgres -> status endpoint. Everything real except the clock."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from orbiter.api.app import create_app
from orbiter.config import Settings
from orbiter.relay import outbox_relay
from orbiter.worker.main import Worker

pytestmark = pytest.mark.integration


@pytest.fixture
async def running_platform(stack: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """The whole platform in one process: relay task, worker task, ASGI app."""
    stop = asyncio.Event()
    relay_task = asyncio.create_task(outbox_relay.run(stack, stop))
    worker = Worker(stack)
    worker_task = asyncio.create_task(worker.run())
    app = create_app(stack)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://orbiter") as client:
            yield client
    worker.request_shutdown()
    stop.set()
    await asyncio.wait_for(asyncio.gather(relay_task, worker_task), timeout=30)


async def wait_for_state(
    client: httpx.AsyncClient, job_id: str, target: str, timeout_s: float = 30.0
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        job: dict[str, Any] = response.json()
        if job["state"] == target:
            return job
        await asyncio.sleep(0.2)
    raise AssertionError(f"job {job_id} never reached {target!r}; last seen: {job['state']}")


async def test_job_travels_end_to_end(running_platform: httpx.AsyncClient) -> None:
    client = running_platform
    submit = await client.post(
        "/jobs",
        json={"duration_ms": 100, "failure_rate": 0.0},
        headers={"Idempotency-Key": f"e2e-{uuid.uuid4()}"},
    )
    assert submit.status_code == 201
    job_id = submit.json()["id"]

    job = await wait_for_state(client, job_id, "succeeded")
    event_names = [e["event"] for e in job["events"]]
    assert event_names[:2] == ["submitted", "enqueued"]
    assert "started" in event_names
    assert event_names[-1] == "completed"
    assert job["result"]["elapsed_ms"] >= 0


async def test_duplicate_submit_returns_the_same_job(running_platform: httpx.AsyncClient) -> None:
    client = running_platform
    key = f"dup-{uuid.uuid4()}"
    body = {"duration_ms": 50, "failure_rate": 0.0}
    first = await client.post("/jobs", json=body, headers={"Idempotency-Key": key})
    second = await client.post("/jobs", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201 and first.json()["created"] is True
    assert second.status_code == 200 and second.json()["created"] is False
    assert first.json()["id"] == second.json()["id"]


async def test_always_failing_job_exhausts_retries(running_platform: httpx.AsyncClient) -> None:
    client = running_platform
    submit = await client.post(
        "/jobs",
        json={"duration_ms": 10, "failure_rate": 1.0},
        headers={"Idempotency-Key": f"fail-{uuid.uuid4()}"},
    )
    assert submit.status_code == 201
    job = await wait_for_state(client, submit.json()["id"], "failed", timeout_s=60)
    event_names = [e["event"] for e in job["events"]]
    assert event_names.count("requeued") >= 1  # it retried before giving up
    assert event_names[-1] == "failed"


async def test_missing_idempotency_key_is_rejected(running_platform: httpx.AsyncClient) -> None:
    response = await running_platform.post("/jobs", json={"duration_ms": 10})
    assert response.status_code == 422
