"""Runtime configuration. Everything comes from ORBITER_* environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORBITER_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://orbiter:orbiter@localhost:5432/orbiter"
    nats_url: str = "nats://localhost:4222"
    valkey_url: str = "redis://localhost:6379/0"

    stream_name: str = "ORBITER_JOBS"
    subject_jobs: str = "orbiter.jobs"
    consumer_durable: str = "workers"
    dlq_stream_name: str = "ORBITER_DLQ"
    subject_dlq: str = "orbiter.dlq"
    advisory_stream_name: str = "ORBITER_ADVISORIES"
    dlq_consumer_durable: str = "dlq-listener"
    # At-least-once knobs: how long a delivery stays invisible before redelivery,
    # and how many deliveries before the broker gives up and we dead-letter.
    ack_wait_s: int = 30
    max_deliver: int = 5

    # API admission control: max concurrently processed submissions per replica.
    admission_capacity: int = 64
    admission_retry_after_s: int = 1

    # Worker
    worker_fetch_timeout_s: int = 5
    shutdown_grace_s: int = 25  # must be < the pod terminationGracePeriodSeconds

    # Outbox relay
    relay_poll_interval_s: float = 0.2
    relay_batch_size: int = 100

    # Idempotent execution guard
    exec_guard_ttl_s: int = 3600
    lease_ttl_s: int = 30

    # Observability. Empty endpoint = telemetry entirely off (tests, local
    # scripts). Point at an OTLP/HTTP collector to light it up.
    otel_endpoint: str = ""
