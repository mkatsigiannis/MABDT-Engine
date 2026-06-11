"""Unit tests for mabdt.StateTimer.

These tests use small real-time sleeps to verify wall-clock accumulation.
They are deliberately tolerant on timing (single-percent) to stay reliable
on a loaded CI worker, but tight enough to catch the kind of bug
StateTimer exists to eliminate (10x off, 100x off, etc.).
"""

import time

import pytest

from mabdt import StateTimer

# Timing tolerance for sleep-based assertions. CI workers are noisy;
# anything looser than this would defeat the purpose of the assertion.
TOL = 0.05  # 50 ms


def test_initial_state_is_zero():
    timer = StateTimer(["Idle", "Busy"])
    assert timer.all() == {"Idle": 0.0, "Busy": 0.0}
    assert timer.get("Idle") == 0.0
    assert timer.get("Busy") == 0.0


def test_accumulates_time_in_current_state():
    timer = StateTimer(["Idle", "Busy"])
    timer.on_state_change("Idle")
    time.sleep(0.1)
    assert abs(timer.get("Idle") - 0.1) < TOL
    assert timer.get("Busy") == 0.0


def test_state_change_accumulates_previous_then_tracks_new():
    timer = StateTimer(["Idle", "Busy"])
    timer.on_state_change("Idle")
    time.sleep(0.1)
    timer.on_state_change("Busy")
    time.sleep(0.1)
    assert abs(timer.get("Idle") - 0.1) < TOL
    assert abs(timer.get("Busy") - 0.1) < TOL


def test_untracked_state_does_not_accumulate():
    """Passing a state name not in the tracked set drops time silently."""
    timer = StateTimer(["Idle", "Busy"])
    timer.on_state_change("Idle")
    time.sleep(0.05)
    timer.on_state_change("Initialize")  # not tracked
    time.sleep(0.1)
    timer.on_state_change("Busy")
    time.sleep(0.05)
    assert abs(timer.get("Idle") - 0.05) < TOL
    assert abs(timer.get("Busy") - 0.05) < TOL
    # The 0.1 s spent in "Initialize" must NOT show up anywhere.
    assert timer.get("Initialize") == 0.0


def test_none_state_pauses_accumulation():
    """on_state_change(None) is the canonical 'untracked' marker."""
    timer = StateTimer(["Idle"])
    timer.on_state_change("Idle")
    time.sleep(0.1)
    timer.on_state_change(None)
    time.sleep(0.2)  # this 200 ms must not be credited to Idle
    timer.on_state_change("Idle")
    time.sleep(0.1)
    assert abs(timer.get("Idle") - 0.2) < TOL


def test_total_time_in_tracked_states_matches_elapsed():
    """The key invariant: sum over tracked states == wall-clock elapsed
    while the timer was in a tracked state."""
    timer = StateTimer(["Idle", "Busy", "Yellow", "Red"])
    timer.on_state_change("Idle")
    t0 = time.monotonic()
    time.sleep(0.05)
    timer.on_state_change("Busy")
    time.sleep(0.05)
    timer.on_state_change("Yellow")
    time.sleep(0.05)
    timer.on_state_change("Red")
    time.sleep(0.05)
    elapsed = time.monotonic() - t0
    timer.on_state_change(None)  # freeze totals

    totals = timer.all()
    assert abs(sum(totals.values()) - elapsed) < TOL


def test_reset_zeros_durations_but_keeps_current_state():
    timer = StateTimer(["Idle"])
    timer.on_state_change("Idle")
    time.sleep(0.1)
    timer.reset()
    assert timer.get("Idle") < TOL  # near zero, possibly small drift
    time.sleep(0.1)
    assert abs(timer.get("Idle") - 0.1) < TOL


def test_all_returns_snapshot_including_in_progress_state():
    timer = StateTimer(["Idle"])
    timer.on_state_change("Idle")
    time.sleep(0.05)
    snapshot = timer.all()
    assert abs(snapshot["Idle"] - 0.05) < TOL


def test_thread_safe_concurrent_reads():
    """Concurrent reads from another thread don't race with the writer."""
    import threading

    timer = StateTimer(["Idle"])
    timer.on_state_change("Idle")

    stop = threading.Event()
    error: list[BaseException] = []

    def reader():
        try:
            while not stop.is_set():
                _ = timer.all()
                _ = timer.get("Idle")
        except BaseException as e:
            error.append(e)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    # Toggle states from this thread while the reader hammers .all()/.get().
    for _ in range(50):
        timer.on_state_change("Idle")
        time.sleep(0.001)
    stop.set()
    t.join(timeout=1.0)
    assert not error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
