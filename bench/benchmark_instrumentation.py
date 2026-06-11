"""Thread-safe latency logger for the scaling benchmark.

When disabled (the default), all calls are no-ops with negligible cost.
The runtime monkey-patches in `bench.instrument` call into this module to
write one CSV row per handled event, with four timestamps:

    mqtt_in       — stamped on the MQTT receive thread in CommunicationAgent._on_message
    inbox_in      — stamped right before _inbox.put() in Agent.receive
    handle_start  — stamped in Agent._run_loop before handle()
    handle_end    — stamped in Agent._run_loop after handle()

End-to-end latency is `handle_end - mqtt_in`. The two intermediate stamps
isolate MQTT-thread overhead, queue wait, and statechart cost.
"""

from __future__ import annotations

import csv
import os
import threading
import time

_ENABLED = False
_FILE = None
_WRITER = None
_LOCK = threading.Lock()
_LOCAL = threading.local()


def start_latency_log(path: str) -> None:
    """Open `path` and start writing latency rows. Idempotent restart."""
    global _ENABLED, _FILE, _WRITER
    with _LOCK:
        if _ENABLED:
            stop_latency_log()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Long-lived handle written-to from the MQTT receive and agent
        # inbox threads; closed in `stop_latency_log()`. Can't use `with`.
        _FILE = open(path, "w", newline="", buffering=8192)  # noqa: SIM115
        _WRITER = csv.writer(_FILE)
        _WRITER.writerow(
            [
                "wallclock",
                "agent",
                "event_type",
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
        _ENABLED = True


def stop_latency_log() -> None:
    """Close the latency log. Safe to call when already stopped."""
    global _ENABLED, _FILE, _WRITER
    with _LOCK:
        if not _ENABLED:
            return
        _ENABLED = False
        try:
            _FILE.flush()
            _FILE.close()
        except Exception:
            pass
        _FILE = None
        _WRITER = None


def is_enabled() -> bool:
    return _ENABLED


def set_mqtt_in() -> float:
    """Stash the MQTT-arrival timestamp on this thread. Returns the timestamp."""
    t = time.perf_counter()
    _LOCAL.mqtt_in = t
    return t


def get_mqtt_in() -> float | None:
    return getattr(_LOCAL, "mqtt_in", None)


def clear_mqtt_in() -> None:
    if hasattr(_LOCAL, "mqtt_in"):
        del _LOCAL.mqtt_in


# Tick / housekeeping events would dominate the CSV without telling us
# anything about agent dispatch cost. Skip them.
_SKIP_EVENT_TYPES = {"internal_tick", "tick"}


def record(
    agent: str,
    event_type: str,
    mqtt_in: float | None,
    inbox_in: float | None,
    handle_start: float,
    handle_end: float,
) -> None:
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
                agent,
                event_type,
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
