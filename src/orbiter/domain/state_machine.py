"""The job lifecycle state machine.

Every state change in the system funnels through :func:`apply`. There is
exactly one place where a transition can be judged legal, which is what makes
the audit trail trustworthy: if an event is in the log, it was a legal move
when it happened.

Without this, distributed retries produce logs like RUNNING -> RUNNING ->
SUCCEEDED -> RUNNING, and nobody can say which write was the lie.
"""

from __future__ import annotations

from collections.abc import Iterable

from orbiter.domain.model import TERMINAL_STATES, EventType, JobEvent, JobState


class IllegalTransition(Exception):
    def __init__(self, state: JobState | None, event: EventType) -> None:
        self.state = state
        self.event = event
        super().__init__(f"event {event.value!r} is not legal in state {state!r}")


# state -> {event: next_state}. Absence means illegal.
_TRANSITIONS: dict[JobState, dict[EventType, JobState]] = {
    JobState.SUBMITTED: {
        EventType.ENQUEUED: JobState.QUEUED,
    },
    JobState.QUEUED: {
        EventType.STARTED: JobState.RUNNING,
        EventType.DEAD_LETTERED: JobState.DEAD_LETTER,
    },
    JobState.RUNNING: {
        EventType.COMPLETED: JobState.SUCCEEDED,
        EventType.FAILED: JobState.FAILED,
        EventType.REQUEUED: JobState.QUEUED,
        EventType.DEAD_LETTERED: JobState.DEAD_LETTER,
    },
    JobState.DEAD_LETTER: {
        EventType.REPLAYED: JobState.QUEUED,
    },
    JobState.SUCCEEDED: {},
    JobState.FAILED: {},
}


def apply(state: JobState | None, event: EventType) -> JobState:
    """Return the state after ``event``, or raise :class:`IllegalTransition`.

    ``state=None`` means "the job does not exist yet"; the only legal first
    event is SUBMITTED.
    """
    if state is None:
        if event is EventType.SUBMITTED:
            return JobState.SUBMITTED
        raise IllegalTransition(None, event)
    next_state = _TRANSITIONS[state].get(event)
    if next_state is None:
        raise IllegalTransition(state, event)
    return next_state


def replay(events: Iterable[JobEvent]) -> JobState:
    """Fold an event log into the current state.

    Deterministic by construction: the same log always produces the same
    state, which is the property that makes the audit trail an audit trail.
    """
    state: JobState | None = None
    for event in events:
        state = apply(state, event.type)
    if state is None:
        raise ValueError("cannot replay an empty event log")
    return state


def is_terminal(state: JobState) -> bool:
    return state in TERMINAL_STATES


def legal_events(state: JobState | None) -> frozenset[EventType]:
    if state is None:
        return frozenset({EventType.SUBMITTED})
    return frozenset(_TRANSITIONS[state])
