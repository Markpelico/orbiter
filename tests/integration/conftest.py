"""Integration fixtures: real Postgres, real NATS JetStream, real Valkey,
each in a container. If Docker is not available these tests are skipped, not
faked — an integration test against a mock is a unit test with worse ergonomics."""

from __future__ import annotations

import shutil
from collections.abc import Iterator

import pytest

from orbiter.config import Settings

_HAS_DOCKER = shutil.which("docker") is not None

requires_docker = pytest.mark.skipif(not _HAS_DOCKER, reason="Docker is not available")


@pytest.fixture(scope="session")
def stack() -> Iterator[Settings]:
    if not _HAS_DOCKER:
        pytest.skip("Docker is not available")
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer

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
