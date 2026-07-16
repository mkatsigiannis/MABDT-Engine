"""Runtime monkey-patches that add timing hooks to the engine (line mode).

The published `mabdt` and `tiger_motors_dt` packages contain no
benchmarking concerns. This module patches four methods at runtime so the
latency logger can capture timestamps without touching engine source:

  - Agent.receive                    adds inbox_in stamp + lifts mqtt_in from TLS
  - Agent._run_loop                  stamps handle_start/handle_end + record()
                                     (covers CarAgent and any base-loop agent)
  - WorkstationAgent._run_loop       same stamps for the workstation agents,
                                     which override the base loop and were
                                     therefore invisible to bench/'s patches
  - CommunicationAgent._on_message   stamps mqtt_in on the MQTT receive thread

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

from bench_line import instrumentation as _bench
from mabdt.agent.base import Agent
from mabdt.communication_kernel.communication_agent import CommunicationAgent
from mabdt.utils.logging import get_logger
from tiger_motors_dt.agents.ws_agent import WorkstationAgent

_logger = get_logger("bench_line.instrument")

# Originals captured at import time so patches are reversible.
_original_receive = Agent.receive
_original_run_loop = Agent._run_loop
_original_ws_run_loop = WorkstationAgent._run_loop
_original_on_message = CommunicationAgent._on_message

_patched = False


def _kind_of(agent: Any) -> str:
    """Row category. Cars are dynamic agents named 'Car-<id>'."""
    return "car" if agent.name.startswith("Car-") else "agent"


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
    """Agent._run_loop replacement (CarAgent, InspectionStationAgent, ...).

    Functionally identical to the original loop, but wraps both
    `self.handle(evt)` call sites with handle_start / handle_end stamps
    and writes one bench record row per handled event.

    Keep this in sync with mabdt/agent/base.py:_run_loop when that
    method changes.
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
                        kind=_kind_of(self),
                        agent=self.name,
                        event_type=evt.get("type", "?"),
                        ws_num=evt.get("ws_num"),
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
                        kind=_kind_of(self),
                        agent=self.name,
                        event_type=evt.get("type", "?"),
                        ws_num=evt.get("ws_num"),
                        mqtt_in=evt.get("_t_mqtt_in"),
                        inbox_in=evt.get("_t_inbox_in"),
                        handle_start=t_start,
                        handle_end=t_end,
                    )
        except queue.Empty:
            continue
        except Exception as e:
            _logger.error(f"Error in agent {self.name}: {e}", exc_info=True)


def _patched_ws_run_loop(self) -> None:
    """WorkstationAgent._run_loop replacement.

    The workstation agent overrides the base run loop with its own
    inline message validation, so the base-class patch never reaches it
    (this is why bench/'s latency CSVs contain only car rows). This
    replacement reproduces the original loop body from
    tiger_motors_dt/agents/ws_agent.py and brackets the message
    processing with handle_start / handle_end stamps.

    Keep this in sync with ws_agent.py:_run_loop when that method
    changes. Rows are recorded for every delivered non-tick message,
    including messages the loop discards via dedup or state validation —
    matching how the base-loop patch records car events (dedup happens
    inside the timed section there too).
    """
    while self.running:
        try:
            try:
                message = self._inbox.get(timeout=0.1)
            except queue.Empty:
                continue

            msg_type = message.get("type", "")

            # Internal tick bypasses timing and dedup, as in the original.
            if msg_type == "internal_tick":
                self._handle_internal_tick()
                continue

            t_start = time.perf_counter()
            try:
                # --- original ws_agent loop body (dedup + validation) ---
                current_time = time.time()
                message_key = f"{msg_type}_{message.get('data', '')}"
                if self.last_message == message_key and current_time - self.last_message_time < 1.0:
                    continue

                self.last_message = message_key
                self.last_message_time = current_time

                current_state = self.state

                if current_state == "ProductionFinished" and msg_type in [
                    "green",
                    "yellow",
                    "red",
                    "busy",
                    "done",
                ]:
                    msg = f"[{self.ws_id}] Production stopped - ignoring {msg_type} message"
                    _logger.info(msg)
                    self.bus.publish("system_message", msg)
                    continue

                if msg_type == "prod_start":
                    if current_state in ["ProductionStart", "ProductionFinished"]:
                        self.prod_start()

                elif msg_type == "green":
                    if current_state in [
                        "Initialize",
                        "Production_YellowAndon",
                        "Production_RedAndon",
                    ]:
                        self.green()

                elif msg_type == "yellow":
                    if current_state in [
                        "Initialize",
                        "Production_GreenAndon_Idle",
                        "Production_GreenAndon_Busy",
                        "Production_RedAndon",
                    ]:
                        self.yellow()

                elif msg_type == "red":
                    if current_state in [
                        "Initialize",
                        "Production_GreenAndon_Idle",
                        "Production_GreenAndon_Busy",
                        "Production_YellowAndon",
                    ]:
                        self.red()

                elif msg_type == "busy":
                    if current_state == "Production_GreenAndon_Idle":
                        self.busy()

                elif msg_type == "done":
                    if current_state == "Production_GreenAndon_Busy":
                        self.done()

                elif msg_type == "prod_finish":
                    if current_state in [
                        "Production_GreenAndon_Idle",
                        "Production_GreenAndon_Busy",
                        "Production_YellowAndon",
                        "Production_RedAndon",
                    ]:
                        self.prod_finish()
                # --- end original loop body ---
            finally:
                t_end = time.perf_counter()
                if _bench.is_enabled() and isinstance(message, dict):
                    _bench.record(
                        kind="ws",
                        agent=self.name,
                        event_type=msg_type,
                        ws_num=self.ws_num,
                        mqtt_in=message.get("_t_mqtt_in"),
                        inbox_in=message.get("_t_inbox_in"),
                        handle_start=t_start,
                        handle_end=t_end,
                    )

        except Exception as e:
            _logger.error(f"Error in workstation {self.ws_id} run loop: {str(e)}")
            time.sleep(1)


def _patched_on_message(self, topic, payload) -> None:
    """CommunicationAgent._on_message replacement.

    Stamps mqtt_in in thread-local storage BEFORE the gate check, so the
    timestamp travels with the message. The downstream Agent.receive
    picks it up off TLS and copies it into the event dict.
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
        WorkstationAgent._run_loop = _patched_ws_run_loop
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
        WorkstationAgent._run_loop = _original_ws_run_loop
        CommunicationAgent._on_message = _original_on_message
        _patched = False
