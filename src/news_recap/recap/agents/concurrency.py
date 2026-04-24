"""Thread-safe adaptive concurrency slot manager for the API execution backend."""

from __future__ import annotations

import threading
import time

from news_recap.recap.exceptions import RecapPipelineError


class ConcurrencyController:
    """Adaptive concurrency controller with rate-limit-driven downshift.

    On ``on_rate_limit()``:
      - halves the active cap (floor 1) under a lock
      - sleeps ``downshift_pause`` **outside** the lock

    On ``on_success()``:
      - increments a success counter; when it reaches ``recovery_successes``,
        the cap is incremented by 1 (up to ``initial_cap``) and the counter resets

    Call sequence for a rate-limit event (required ordering):
      1. acquire()         — take a slot
      2. transport call    — raises rate-limit error
      3. release()         — return slot BEFORE any sleep
      4. on_rate_limit()   — halves cap (under lock), then sleeps outside lock
      5. sleep(backoff)    — caller-side exponential backoff
      6. goto 1            — re-acquire

    ``max_backoff`` and ``jitter`` are stored here so callers can read them
    without needing a separate settings reference.
    """

    def __init__(
        self,
        initial_cap: int,
        recovery_successes: int,
        downshift_pause: float,
        max_backoff: float = 60.0,
        jitter: float = 5.0,
    ) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._cap = initial_cap
        self._initial_cap = initial_cap
        self._active = 0
        self._recovery_successes = recovery_successes
        self._downshift_pause = downshift_pause
        self._consecutive_successes = 0
        self.max_backoff = max_backoff
        self.jitter = jitter

    def acquire(self, stop_event: threading.Event | None = None) -> None:
        """Block until a concurrency slot is available, then take it."""
        with self._cond:
            while self._active >= self._cap:
                if stop_event is not None and stop_event.is_set():
                    raise RecapPipelineError("interrupted", "Pipeline interrupted by user")
                self._cond.wait(timeout=0.5)
            self._active += 1

    def release(self) -> None:
        """Return a previously acquired slot."""
        with self._cond:
            self._active -= 1
            self._cond.notify_all()

    def on_rate_limit(self) -> None:
        """Halve the cap (floor 1) and sleep outside the lock."""
        with self._cond:
            self._cap = max(1, self._cap // 2)
            self._consecutive_successes = 0
            self._cond.notify_all()
        # Sleep outside any lock so other threads are not blocked.
        time.sleep(self._downshift_pause)

    def on_success(self) -> None:
        """Record a successful call; increment cap after enough consecutive successes."""
        with self._cond:
            self._consecutive_successes += 1
            if self._consecutive_successes >= self._recovery_successes:
                if self._cap < self._initial_cap:
                    self._cap += 1
                    self._cond.notify_all()
                self._consecutive_successes = 0
