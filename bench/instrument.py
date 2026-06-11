"""Runtime monkey-patches that add timing hooks to the engine.

The published `mabdt` and `tiger_motors_dt` packages contain no
benchmarking concerns. This module instead patches three methods at
runtime so the latency logger can capture timestamps without touching
engine source:

  - Agent.receive               adds inbox_in stamp + lifts mqtt_in from TLS
  - Agent._run_loop             adds handle_start / handle_end stamps + record()
  - CommunicationAgent._on_message  stamps mqtt_in on the MQTT receive thread

Patches are applied by `enable(path)` and reversed by `disable()`. Apply
BEFORE constructing the environment — agents capture their bound
`_run_loop` when their thread starts in `Agent.__init__`, so a patch
applied later won't reach already-running threads.

The patched methods fall back to the original behavior when the latency
logger is disabled, so leaving the patches in place between runs has
negligible cost (one boolean check per message handled).
"""

from __future__ import annotations

import queue
import time
from typing import Any

from bench import benchmark_instrumentation as _bench
from mabdt.agent.base import Agent
from mabdt.communication_kernel.communication_agent import CommunicationAgent
from mabdt.utils.logging import get_logger

_logger = get_logger("bench.instrument")

# Originals captured at import time so patches are reversible.
_original_receive = Agent.receive
_original_run_loop = Agent._run_loop
_original_on_message = CommunicationAgent._on_message

_patched = False


def _patched_receive(self, evt) -> None:
    """Agent.receive replacement.

    Lifts the mqtt_in timestamp out of thread-local storage (set by the
    MQTT receive thread in _patched_on_message) and into the event dict
    itself, so it survives the queue handoff into the agent's own thread.
    Then stamps inbox_in and delegates to the original receive.
    """
    if _bench.is_enabled() and isinstance(evt, dict):
        if "_t_mqtt_in" not in evt:
            mqtt_in = _bench.get_mqtt_in()
            if mqtt_in is not None:
                evt["_t_mqtt_in"] = mqtt_in
        evt["_t_inbox_in"] = time.perf_counter()
    return _original_receive(self, evt)


def _patched_run_loop(self) -> None:
    """Agent._run_loop replacement.

    Functionally identical to the original loop, but wraps both
    `self.handle(evt)` call sites with handle_start / handle_end stamps
    and writes one bench.record() row per handled event.

    Keep this in sync with mabdt/agent/base.py:_run_loop when that
    method changes. If the original loop is refactored, this patch
    must follow.
    """
    stashed: Any = None
    while self.running:
        if self.paused:
            time.sleep(self._inbox_timeout)
            continue
        if stashed is not None:
            evt, stashed = stashed, None
            t_start = time.perf_counter()
            try:
                self.handle(evt)
            except Exception as e:
                _logger.error(f"Error in agent {self.name}: {e}", exc_info=True)
            finally:
                t_end = time.perf_counter()
                if _bench.is_enabled() and isinstance(evt, dict):
                    _bench.record(
                        agent=self.name,
                        event_type=evt.get("type", "?"),
                        mqtt_in=evt.get("_t_mqtt_in"),
                        inbox_in=evt.get("_t_inbox_in"),
                        handle_start=t_start,
                        handle_end=t_end,
                    )
            continue
        try:
            evt = self._inbox.get(timeout=self._inbox_timeout)
            if self.paused:
                stashed = evt
                continue
            t_start = time.perf_counter()
            try:
                self.handle(evt)
            finally:
                t_end = time.perf_counter()
                if _bench.is_enabled() and isinstance(evt, dict):
                    _bench.record(
                        agent=self.name,
                        event_type=evt.get("type", "?"),
                        mqtt_in=evt.get("_t_mqtt_in"),
                        inbox_in=evt.get("_t_inbox_in"),
                        handle_start=t_start,
                        handle_end=t_end,
                    )
        except queue.Empty:
            continue
        except Exception as e:
            _logger.error(f"Error in agent {self.name}: {e}", exc_info=True)


def _patched_on_message(self, topic, payload) -> None:
    """CommunicationAgent._on_message replacement.

    Stamps mqtt_in in thread-local storage BEFORE the gate check, so the
    timestamp travels with the message even if dispatch happens. The
    downstream Agent.receive picks it up off TLS and copies it into the
    event dict (see _patched_receive).
    """
    if _bench.is_enabled():
        _bench.set_mqtt_in()
    return _original_on_message(self, topic, payload)


def enable(latency_csv_path: str) -> None:
    """Apply patches and start writing latency rows to `latency_csv_path`.

    Idempotent: calling enable twice is safe; the second call rotates the
    log file but does not double-patch.
    """
    global _patched
    if not _patched:
        Agent.receive = _patched_receive
        Agent._run_loop = _patched_run_loop
        CommunicationAgent._on_message = _patched_on_message
        _patched = True
    _bench.start_latency_log(latency_csv_path)


def disable() -> None:
    """Stop the latency log and restore the original methods."""
    global _patched
    _bench.stop_latency_log()
    if _patched:
        Agent.receive = _original_receive
        Agent._run_loop = _original_run_loop
        CommunicationAgent._on_message = _original_on_message
        _patched = False
