"""StateTimer — wall-clock state-duration tracker.

For agents that need to report how long they have spent in each of a small
set of named states (utilization metrics, time-in-state KPIs), this is the
preferred substitute for the legacy pattern of "increment a counter on
each event-bus tick."

The tick pattern is fragile: a slow tick source, a deduplication window,
or a backlogged agent inbox all under-count time silently. StateTimer
reads the wall clock at every state transition, so it is correct by
construction regardless of how the tick source behaves.

Typical use with the `transitions` library:

    from mabdt import StateTimer

    self._timer = StateTimer(["Idle", "Busy", "Yellow", "Red"])
    self.machine = Machine(
        model=self,
        states=...,
        transitions=...,
        after_state_change="_on_state_change",
        ...
    )

    def _on_state_change(self):
        self._timer.on_state_change(self._classify(self.state))

    def _classify(self, state):
        if state == "Production_GreenAndon_Idle":
            return "Idle"
        # ... etc; return None for untracked states (setup, finished, ...)

Override Agent.pause / Agent.resume to call self._timer.on_state_change(None)
on pause and self._timer.on_state_change(self._classify(self.state)) on
resume, so time spent while the agent is paused is not credited to whichever
tracked state was active at the moment of the pause.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable


class StateTimer:
    """Wall-clock state-duration tracker.

    Thread-safe. The intended use is one StateTimer instance per agent,
    written from the agent's own thread (via the state machine's
    after_state_change hook) and read from any thread (typically the
    interface layer's DTO converter on the GUI refresh path).

    Args:
        states: The names of the states to track. Only these names cause
            time to accumulate; everything else (including None) is
            treated as "untracked" and time spent there is silently
            dropped. This keeps transient setup/teardown states from
            contributing to utilization metrics.
    """

    def __init__(self, states: Iterable[str]) -> None:
        self._durations: dict[str, float] = {s: 0.0 for s in states}
        self._current: str | None = None
        self._entered_at: float | None = None
        self._lock = threading.Lock()

    def on_state_change(self, new_state: str | None) -> None:
        """Record entry into `new_state`.

        Accumulates the duration of the previous tracked state (if any)
        into its bucket, then begins tracking the new one. Pass None for
        untracked states.
        """
        with self._lock:
            now = time.monotonic()
            if self._current is not None and self._entered_at is not None:
                self._durations[self._current] += now - self._entered_at
            if new_state in self._durations:
                self._current = new_state
                self._entered_at = now
            else:
                self._current = None
                self._entered_at = None

    def get(self, state: str) -> float:
        """Return wall-clock seconds spent in `state`.

        Includes the time elapsed since entering it if it is currently
        the active state.
        """
        with self._lock:
            base = self._durations.get(state, 0.0)
            if self._current == state and self._entered_at is not None:
                base += time.monotonic() - self._entered_at
            return base

    def all(self) -> dict[str, float]:
        """Snapshot of all tracked states with their current durations."""
        with self._lock:
            result = dict(self._durations)
            if self._current in result and self._entered_at is not None:
                result[self._current] += time.monotonic() - self._entered_at
            return result

    def reset(self) -> None:
        """Zero all durations; keep tracking the current state from now."""
        with self._lock:
            for s in self._durations:
                self._durations[s] = 0.0
            if self._current is not None:
                self._entered_at = time.monotonic()
            else:
                self._entered_at = None
