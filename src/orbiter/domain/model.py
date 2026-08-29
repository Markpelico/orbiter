"""Job domain model.

A job's state is a pure projection of its event log. The database stores the
events; the current-state column on the jobs table is a cache of
``replay(events)``, never an independent source of truth.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class JobState(enum.StrEnum):
    SUBMITTED = "submitted"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class EventType(enum.StrEnum):
    SUBMITTED = "submitted"
    ENQUEUED = "enqueued"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"  # non-retryable, or retries exhausted at the app layer
    REQUEUED = "requeued"  # retryable failure, or worker lost mid-run
    DEAD_LETTERED = "dead_lettered"  # MaxDeliver exhausted -> quarantined
    REPLAYED = "replayed"  # operator re-injects a dead-lettered job


# States from which no event is ever legal again.
TERMINAL_STATES: frozenset[JobState] = frozenset({JobState.SUCCEEDED, JobState.FAILED})


@dataclass(frozen=True, slots=True)
class JobEvent:
    type: EventType
    attempt: int = 0
    detail: dict[str, object] = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class JobPayload:
    """The one job type ORBITER runs: a simulation stub.

    The workload is a prop; the platform is the product.
    """

    duration_ms: int
    failure_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be >= 0")
        if not 0.0 <= self.failure_rate <= 1.0:
            raise ValueError("failure_rate must be within [0, 1]")
