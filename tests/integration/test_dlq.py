"""Poison-message quarantine, end to end.

A poison job naks every delivery without acking — from the broker's point of
view its worker just keeps dying. The proof: MaxDeliver exhausts, the
advisory fires, the DLQ listener quarantines the job, the operator can see
it, replay it, and the quarantine holds when it poisons again."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

WaitForState = Callable[[httpx.AsyncClient, str, str, float], Awaitable[dict[str, Any]]]

pytestmark = pytest.mark.integration


async def test_poison_job_is_quarantined_then_replayable(
    running_platform: httpx.AsyncClient, wait_for_state: WaitForState
) -> None:
    client = running_platform
    submit = await client.post(
        "/jobs",
        json={"duration_ms": 10, "poison": True},
        headers={"Idempotency-Key": f"poison-{uuid.uuid4()}"},
    )
    assert submit.status_code == 201
    job_id = submit.json()["id"]

    # The fleet survives: the job lands in quarantine instead of looping.
    job = await wait_for_state(client, job_id, "dead_letter", 60.0)
    dead_letter_events = [e for e in job["events"] if e["event"] == "dead_lettered"]
    assert dead_letter_events, "audit trail must show the quarantine"
    assert dead_letter_events[-1]["detail"]["deliveries"] >= 3  # MaxDeliver in test settings

    # The operator can see it.
    dlq = await client.get("/dlq")
    assert dlq.status_code == 200
    assert job_id in [entry["id"] for entry in dlq.json()]

    # The operator can replay it...
    replay = await client.post(f"/jobs/{job_id}/replay")
    assert replay.status_code == 200
    assert replay.json()["state"] == "queued"

    # ...and since the job is still poison, the quarantine holds again.
    await wait_for_state(client, job_id, "dead_letter", 60.0)


async def test_replay_of_a_healthy_job_is_rejected(
    running_platform: httpx.AsyncClient, wait_for_state: WaitForState
) -> None:
    client = running_platform
    submit = await client.post(
        "/jobs",
        json={"duration_ms": 10, "failure_rate": 0.0},
        headers={"Idempotency-Key": f"healthy-{uuid.uuid4()}"},
    )
    job_id = submit.json()["id"]
    await wait_for_state(client, job_id, "succeeded", 30.0)

    replay = await client.post(f"/jobs/{job_id}/replay")
    assert replay.status_code == 409  # only dead-lettered jobs are replayable


async def test_replay_of_unknown_job_is_404(running_platform: httpx.AsyncClient) -> None:
    response = await running_platform.post(f"/jobs/{uuid.uuid4()}/replay")
    assert response.status_code == 404
