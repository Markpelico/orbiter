"""The chaos handler: one message, one dead worker, no cleanup."""

from __future__ import annotations

from orbiter.config import Settings
from orbiter.worker.main import Worker


async def test_chaos_message_kills_the_worker_hard() -> None:
    worker = Worker(Settings())
    deaths: list[int] = []
    worker._die = deaths.append  # observe instead of dying

    await worker._on_chaos_message(object())

    assert deaths == [1]
    # Crucially: no shutdown request, no drain — the worker did NOT go
    # gracefully. Graceful is the SIGTERM path; chaos is a disappearance.
    assert not worker.shutdown.is_set()
