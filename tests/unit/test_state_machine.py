"""The state machine is the constitution of the system: these tests are the
proof that no sequence of distributed mishaps can record an impossible
history."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from orbiter.domain.model import TERMINAL_STATES, EventType, JobEvent, JobState
from orbiter.domain.state_machine import (
    IllegalTransition,
    apply,
    is_terminal,
    legal_events,
    replay,
)

E = EventType
S = JobState


class TestLegalPaths:
    def test_happy_path(self) -> None:
        state = apply(None, E.SUBMITTED)
        for event, expected in [
            (E.ENQUEUED, S.QUEUED),
            (E.STARTED, S.RUNNING),
            (E.COMPLETED, S.SUCCEEDED),
        ]:
            state = apply(state, event)
            assert state is expected

    def test_retry_loop(self) -> None:
        """A job can fail and requeue many times before succeeding."""
        state = apply(apply(None, E.SUBMITTED), E.ENQUEUED)
        for _ in range(5):
            state = apply(state, E.STARTED)
            state = apply(state, E.REQUEUED)
            assert state is S.QUEUED
        assert apply(apply(state, E.STARTED), E.COMPLETED) is S.SUCCEEDED

    def test_lost_worker_restart_is_legal(self) -> None:
        """A worker dies mid-job leaving the state RUNNING; the redelivery's
        STARTED is the recovery, not corruption. The CHAOS button found the
        version of this machine that disagreed."""
        state = apply(apply(apply(None, E.SUBMITTED), E.ENQUEUED), E.STARTED)
        assert state is S.RUNNING
        assert apply(state, E.STARTED) is S.RUNNING  # restart after loss
        assert apply(apply(state, E.STARTED), E.COMPLETED) is S.SUCCEEDED

    def test_dead_letter_and_replay(self) -> None:
        state = apply(apply(apply(None, E.SUBMITTED), E.ENQUEUED), E.STARTED)
        state = apply(state, E.DEAD_LETTERED)
        assert state is S.DEAD_LETTER
        assert apply(state, E.REPLAYED) is S.QUEUED

    def test_permanent_failure(self) -> None:
        state = apply(apply(apply(None, E.SUBMITTED), E.ENQUEUED), E.STARTED)
        assert apply(state, E.FAILED) is S.FAILED


class TestIllegalPaths:
    def test_cannot_complete_before_starting(self) -> None:
        with pytest.raises(IllegalTransition):
            apply(S.QUEUED, E.COMPLETED)

    def test_only_submitted_creates_a_job(self) -> None:
        for event in set(E) - {E.SUBMITTED}:
            with pytest.raises(IllegalTransition):
                apply(None, event)

    def test_terminal_states_absorb_nothing(self) -> None:
        """SUCCEEDED and FAILED accept no event — a duplicate delivery of a
        finished job must be rejected at the transition, not papered over."""
        for state in TERMINAL_STATES:
            assert legal_events(state) == frozenset()
            for event in E:
                with pytest.raises(IllegalTransition):
                    apply(state, event)


class TestReplay:
    def test_replay_reconstructs_state(self) -> None:
        events = [JobEvent(type=t) for t in [E.SUBMITTED, E.ENQUEUED, E.STARTED, E.REQUEUED]]
        assert replay(events) is S.QUEUED

    def test_replay_empty_log_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            replay([])


# --- Property tests -------------------------------------------------------

event_sequences = st.lists(st.sampled_from(list(E)), min_size=0, max_size=30)


@given(events=event_sequences)
def test_no_sequence_produces_an_invalid_state(events: list[EventType]) -> None:
    """Any event sequence either raises IllegalTransition or lands in a real
    JobState. There is no third outcome — no None-state, no corruption."""
    state: JobState | None = None
    try:
        for event in events:
            state = apply(state, event)
    except IllegalTransition:
        return
    assert state is None or isinstance(state, JobState)


@given(events=event_sequences)
def test_replay_is_deterministic(events: list[EventType]) -> None:
    """The same log always folds to the same state — the property that makes
    the audit trail trustworthy."""
    log = [JobEvent(type=t) for t in events]
    try:
        first = replay(log)
    except (IllegalTransition, ValueError):
        return
    assert replay(log) is first


@given(events=event_sequences)
def test_terminal_is_forever(events: list[EventType]) -> None:
    """Once a legal sequence reaches a terminal state, no suffix can move it."""
    state: JobState | None = None
    try:
        for event in events:
            if state is not None and is_terminal(state):
                with pytest.raises(IllegalTransition):
                    apply(state, event)
                return
            state = apply(state, event)
    except IllegalTransition:
        return
