"""Bounded admission: the backpressure policy is 'reject loudly', and the
controller is the part that decides when."""

from __future__ import annotations

import pytest

from orbiter.api.admission import AdmissionController


def test_admits_up_to_capacity() -> None:
    ctrl = AdmissionController(capacity=3)
    assert all(ctrl.try_acquire() for _ in range(3))
    assert not ctrl.try_acquire()  # the 4th is rejected, not buffered


def test_release_restores_capacity() -> None:
    ctrl = AdmissionController(capacity=1)
    assert ctrl.try_acquire()
    assert not ctrl.try_acquire()
    ctrl.release()
    assert ctrl.try_acquire()


def test_release_without_acquire_is_a_bug() -> None:
    ctrl = AdmissionController(capacity=1)
    with pytest.raises(RuntimeError):
        ctrl.release()


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        AdmissionController(capacity=0)


def test_bookkeeping() -> None:
    ctrl = AdmissionController(capacity=5, retry_after_s=2)
    ctrl.try_acquire()
    ctrl.try_acquire()
    assert ctrl.in_flight == 2
    assert ctrl.available == 3
    assert ctrl.retry_after_s == 2
