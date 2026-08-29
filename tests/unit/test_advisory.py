"""The DLQ listener's advisory parsing: strict about what it quarantines."""

from __future__ import annotations

import json

from hypothesis import given
from hypothesis import strategies as st

from orbiter.dlq.listener import MaxDeliveriesAdvisory, advisory_subject, parse_advisory


def make_advisory(**overrides: object) -> bytes:
    data: dict[str, object] = {
        "type": "io.nats.jetstream.advisory.v1.max_deliver",
        "id": "abc",
        "timestamp": "2026-08-29T00:00:00Z",
        "stream": "ORBITER_JOBS",
        "consumer": "workers",
        "stream_seq": 42,
        "deliveries": 3,
    }
    data.update(overrides)
    return json.dumps(data).encode()


def test_parses_a_real_advisory() -> None:
    adv = parse_advisory(make_advisory())
    assert adv == MaxDeliveriesAdvisory(
        stream="ORBITER_JOBS", consumer="workers", stream_seq=42, deliveries=3
    )


def test_rejects_other_advisory_types() -> None:
    assert parse_advisory(make_advisory(type="io.nats.jetstream.advisory.v1.terminated")) is None


def test_rejects_missing_fields() -> None:
    raw = json.loads(make_advisory())
    del raw["stream_seq"]
    assert parse_advisory(json.dumps(raw).encode()) is None


def test_rejects_non_numeric_sequence() -> None:
    assert parse_advisory(make_advisory(stream_seq="not-a-number")) is None


def test_rejects_valid_json_that_is_not_an_object() -> None:
    """Regression: Hypothesis found b"0" in CI — valid JSON, not a dict."""
    for raw in (b"0", b'"advisory"', b"[1, 2]", b"null", b"true"):
        assert parse_advisory(raw) is None


@given(st.binary(max_size=200))
def test_arbitrary_bytes_never_crash_the_parser(raw: bytes) -> None:
    """The advisory subject is broker-controlled, but the parser still treats
    input as hostile: garbage in, None out, never an exception."""
    result = parse_advisory(raw)
    assert result is None or isinstance(result, MaxDeliveriesAdvisory)


def test_advisory_subject_shape() -> None:
    assert (
        advisory_subject("ORBITER_JOBS", "workers")
        == "$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.ORBITER_JOBS.workers"
    )
