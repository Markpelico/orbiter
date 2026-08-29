"""Integration fixtures: real Postgres, real NATS JetStream, real Valkey,
each in a container, with the whole platform (API, relay, worker, DLQ
listener) running in-process on top. If Docker is not available these tests
are skipped, not faked — an integration test against a mock is a unit test
with worse ergonomics."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from orbiter.api.app import create_app
from orbiter.config import Settings
from orbiter.dlq import listener as dlq_listener
from orbiter.relay import outbox_relay
from orbiter.worker.main import Worker

_HAS_DOCKER = shutil.which("docker") is not None


@pytest.fixture(scope="session")
def stack() -> Iterator[Settings]:
    if not _HAS_DOCKER:
        pytest.skip("Docker is not available")
    from testcontainers.community.postgres import PostgresContainer
    from testcontainers.community.redis import RedisContainer
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    with (
        PostgresContainer("postgres:17-alpine") as pg,
        RedisContainer("valkey/valkey:8-alpine") as valkey,
        DockerContainer("nats:2.10-alpine").with_command("-js").with_exposed_ports(4222) as nats_c,
    ):
        wait_for_logs(nats_c, "Server is ready", timeout=30)
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        yield Settings(
            database_url=dsn,
            nats_url=f"nats://{nats_c.get_container_host_ip()}:{nats_c.get_exposed_port(4222)}",
            valkey_url=(
                f"redis://{valkey.get_container_host_ip()}:{valkey.get_exposed_port(6379)}/0"
            ),
            ack_wait_s=5,
            max_deliver=3,
            worker_fetch_timeout_s=1,
            relay_poll_interval_s=0.1,
        )


@pytest.fixture
async def running_platform(stack: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """The whole platform in one process: relay, worker, DLQ listener, ASGI app."""
    stop = asyncio.Event()
    relay_task = asyncio.create_task(outbox_relay.run(stack, stop))
    dlq_task = asyncio.create_task(dlq_listener.run(stack, stop))
    worker = Worker(stack)
    worker_task = asyncio.create_task(worker.run())
    app = create_app(stack)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://orbiter") as client:
            yield client
    worker.request_shutdown()
    stop.set()
    await asyncio.wait_for(asyncio.gather(relay_task, dlq_task, worker_task), timeout=30)


WaitForState = Callable[[httpx.AsyncClient, str, str, float], Awaitable[dict[str, Any]]]


@pytest.fixture
def wait_for_state() -> WaitForState:
    async def _wait(
        client: httpx.AsyncClient, job_id: str, target: str, timeout_s: float = 30.0
    ) -> dict[str, Any]:
        job: dict[str, Any] = {"state": "<never fetched>"}
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            response = await client.get(f"/jobs/{job_id}")
            assert response.status_code == 200
            job = response.json()
            if job["state"] == target:
                return job
            await asyncio.sleep(0.2)
        raise AssertionError(f"job {job_id} never reached {target!r}; last seen: {job['state']}")

    return _wait
