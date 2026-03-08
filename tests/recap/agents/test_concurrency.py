"""Tests for ConcurrencyController."""

from __future__ import annotations

import threading
import time

import pytest

from news_recap.recap.agents.concurrency import ConcurrencyController


def test_slot_cap_enforced():
    """At most initial_cap threads can hold a slot simultaneously."""
    cc = ConcurrencyController(
        initial_cap=2,
        recovery_successes=100,
        downshift_pause=0.0,
    )
    acquired: list[int] = []
    lock = threading.Lock()

    def worker(idx: int) -> None:
        cc.acquire()
        with lock:
            acquired.append(idx)
        time.sleep(0.05)
        cc.release()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(acquired) == 4  # all eventually acquired


def test_on_rate_limit_halves_cap():
    cc = ConcurrencyController(
        initial_cap=4,
        recovery_successes=100,
        downshift_pause=0.0,
    )
    assert cc._cap == 4
    cc.on_rate_limit()
    assert cc._cap == 2
    cc.on_rate_limit()
    assert cc._cap == 1
    cc.on_rate_limit()
    assert cc._cap == 1  # floor at 1


def test_on_rate_limit_resets_success_counter():
    cc = ConcurrencyController(
        initial_cap=4,
        recovery_successes=3,
        downshift_pause=0.0,
    )
    cc.on_success()
    cc.on_success()
    cc.on_rate_limit()
    assert cc._consecutive_successes == 0


def test_on_success_increments_cap_after_recovery_successes():
    cc = ConcurrencyController(
        initial_cap=4,
        recovery_successes=3,
        downshift_pause=0.0,
    )
    cc.on_rate_limit()  # cap: 4 -> 2
    assert cc._cap == 2

    cc.on_success()
    cc.on_success()
    assert cc._cap == 2  # not yet
    cc.on_success()
    assert cc._cap == 3  # incremented after 3 successes


def test_on_success_does_not_exceed_initial_cap():
    cc = ConcurrencyController(
        initial_cap=2,
        recovery_successes=1,
        downshift_pause=0.0,
    )
    # Already at cap
    cc.on_success()
    assert cc._cap == 2  # no increase beyond initial_cap


def test_on_rate_limit_sleeps_outside_lock(monkeypatch):
    """on_rate_limit() must sleep outside its internal lock."""
    cc = ConcurrencyController(
        initial_cap=2,
        recovery_successes=100,
        downshift_pause=0.05,
    )
    sleep_calls: list[float] = []
    original_sleep = time.sleep

    def recording_sleep(t: float) -> None:
        sleep_calls.append(t)
        original_sleep(min(t, 0.001))  # don't actually wait long in tests

    monkeypatch.setattr(time, "sleep", recording_sleep)
    cc.on_rate_limit()
    assert sleep_calls == [0.05]


def test_acquire_respects_stop_event():
    cc = ConcurrencyController(
        initial_cap=1,
        recovery_successes=100,
        downshift_pause=0.0,
    )
    cc.acquire()  # consume the one slot

    stop_event = threading.Event()
    stop_event.set()  # already set

    from news_recap.recap.tasks.base import RecapPipelineError

    with pytest.raises(RecapPipelineError, match="interrupted"):
        cc.acquire(stop_event=stop_event)

    cc.release()


def test_release_after_rate_limit_does_not_block_others():
    """Threads that released before on_rate_limit() don't block on the sleep."""
    cc = ConcurrencyController(
        initial_cap=2,
        recovery_successes=100,
        downshift_pause=0.05,
    )

    results: list[str] = []

    def rate_limited_thread() -> None:
        cc.acquire()
        cc.release()  # release FIRST
        cc.on_rate_limit()  # then sleep outside lock
        results.append("rate_limited_done")

    def normal_thread() -> None:
        cc.acquire()
        results.append("normal_acquired")
        cc.release()

    t1 = threading.Thread(target=rate_limited_thread)
    t2 = threading.Thread(target=normal_thread)
    t1.start()
    t2.start()
    t1.join(timeout=1.0)
    t2.join(timeout=1.0)

    assert "normal_acquired" in results
    assert "rate_limited_done" in results
