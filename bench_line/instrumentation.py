"""Thread-safe latency logger for the line-mode benchmark.

Same design as bench/benchmark_instrumentation.py, with three additions:

  - a `kind` column ("car" / "ws" / "agent") so car and workstation rows
    separate without name heuristics,
  - a `ws_num` column recording which workstation the event refers to
    (the event payload's `ws_num` for car events, the agent's own number
    for workstation events). This is what lets the analyzer detect line
    exits (car `done` rows with ws_num == N) and full traversals (cars
    whose first `start` row has ws_num == 1),
  - a `rows_written()` counter so the runner can drain until the engine
    goes quiet instead of sleeping a fixed amount.

Four timestamps per row:

    mqtt_in       — stamped on the MQTT receive thread in CommunicationAgent._on_message
    inbox_in      — stamped right before _inbox.put() in Agent.receive
    handle_start  — stamped before the event is handled in the agent's own thread
    handle_end    — stamped after handling completes

End-to-end latency is `handle_end - mqtt_in`. All stamps are
`time.perf_counter()` values, comparable across threads within the
engine process.
"""

from __future__ import annotations

import csv
import os
import threading
import time

_ENABLED = False
_FILE = None
_WRITER = None
_ROWS = 0
_LOCK = threading.Lock()
_LOCAL = threading.local()


def start_latency_log(path: str) -> None:
    """Open `path` and start writing latency rows. Idempotent restart."""
    global _ENABLED, _FILE, _WRITER, _ROWS
    with _LOCK:
        if _ENABLED:
            _stop_locked()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Long-lived handle written-to from the MQTT receive and agent
        # threads; closed in `stop_latency_log()`. Can't use `with`.
        _FILE = open(path, "w", newline="", buffering=8192)  # noqa: SIM115
        _WRITER = csv.writer(_FILE)
        _WRITER.writerow(
            [
                "wallclock",
                "kind",
                "agent",
                "event_type",
                "ws_num",
                "mqtt_in_perf",
                "inbox_in_perf",
                "handle_start_perf",
                "handle_end_perf",
                "mqtt_to_inbox_s",
                "inbox_wait_s",
                "handle_s",
                "e2e_s",
            ]
        )
        _ROWS = 0
        _ENABLED = True


def _stop_locked() -> None:
    global _ENABLED, _FILE, _WRITER
    _ENABLED = False
    try:
        _FILE.flush()
        _FILE.close()
    except Exception:
        pass
    _FILE = None
    _WRITER = None


def stop_latency_log() -> None:
    """Close the latency log. Safe to call when already stopped."""
    with _LOCK:
        if _ENABLED:
            _stop_locked()


def is_enabled() -> bool:
    return _ENABLED


def rows_written() -> int:
    """Rows recorded so far. Used by the runner's drain-until-quiet loop."""
    with _LOCK:
        return _ROWS


def set_mqtt_in() -> float:
    """Stash the MQTT-arrival timestamp on this thread. Returns the timestamp."""
    t = time.perf_counter()
    _LOCAL.mqtt_in = t
    return t


def get_mqtt_in() -> float | None:
    return getattr(_LOCAL, "mqtt_in", None)


# Tick / housekeeping events would dominate the CSV without telling us
# anything about agent dispatch cost. Skip them.
_SKIP_EVENT_TYPES = {"internal_tick", "tick"}


def record(
    kind: str,
    agent: str,
    event_type: str,
    ws_num: int | None,
    mqtt_in: float | None,
    inbox_in: float | None,
    handle_start: float,
    handle_end: float,
) -> None:
    global _ROWS
    if not _ENABLED:
        return
    if event_type in _SKIP_EVENT_TYPES:
        return
    mqtt_to_inbox = (inbox_in - mqtt_in) if (mqtt_in is not None and inbox_in is not None) else ""
    inbox_wait = (handle_start - inbox_in) if inbox_in is not None else ""
    handle_s = handle_end - handle_start
    e2e = (handle_end - mqtt_in) if mqtt_in is not None else ""
    with _LOCK:
        if _WRITER is None:
            return
        _WRITER.writerow(
            [
                time.time(),
                kind,
                agent,
                event_type,
                ws_num if ws_num is not None else "",
                mqtt_in if mqtt_in is not None else "",
                inbox_in if inbox_in is not None else "",
                handle_start,
                handle_end,
                mqtt_to_inbox,
                inbox_wait,
                handle_s,
                e2e,
            ]
        )
        _ROWS += 1
