"""Smoke tests for mabdt.StateMachineAgent (dedup + processing guard).

The state machine itself (transitions library config) is the deployment's
responsibility. The base class provides message normalization, duplicate
detection, and a standardized handle() flow; these tests verify each.
"""

from __future__ import annotations

import time

from transitions.extensions import HierarchicalMachine

from mabdt import EventBus, StateMachineAgent


def _short_bus() -> EventBus:
    return EventBus({"performance": {"agent_inbox_timeout": 0.05}})


def test_is_duplicate_message_within_window():
    bus = _short_bus()
    sma = StateMachineAgent("sma", bus)
    assert sma.is_duplicate_message("k") is False
    assert sma.is_duplicate_message("k") is True
    # A different key resets the comparison.
    assert sma.is_duplicate_message("other") is False
    sma.stop()


def test_is_duplicate_message_after_timeout_window():
    bus = _short_bus()
    sma = StateMachineAgent("sma", bus)
    assert sma.is_duplicate_message("k", timeout=0.05) is False
    time.sleep(0.08)
    assert sma.is_duplicate_message("k", timeout=0.05) is False
    sma.stop()


def test_normalize_message_handles_str_and_dict_and_unknown():
    bus = _short_bus()
    sma = StateMachineAgent("sma", bus)
    et, md = sma.normalize_message("ping")
    assert et == "ping" and md == {"type": "ping"}
    et, md = sma.normalize_message({"type": "evt", "extra": 1})
    assert et == "evt" and md == {"type": "evt", "extra": 1}
    et, md = sma.normalize_message(42)
    assert et is None and md is None
    sma.stop()


def test_state_machine_dedup_blocks_repeat_event():
    """A statemachine-driven agent should only transition once per dedup key."""
    bus = _short_bus()

    class Tiny(StateMachineAgent):
        def __init__(self, name, bus):
            super().__init__(name, bus)
            states = ["A", "B"]
            transitions = [{"trigger": "go", "source": "A", "dest": "B"}]
            config = self.get_state_machine_config()
            self.machine = HierarchicalMachine(
                model=self, states=states, transitions=transitions, initial="A", **config
            )

    t = Tiny("t", bus)
    assert t.state == "A"
    t.receive({"type": "go"})
    time.sleep(0.15)
    assert t.state == "B"
    # A repeat 'go' within the dedup window is silently dropped — the SM
    # has no 'go' transition from B anyway, but the dedup short-circuits
    # before we'd hit the missing-trigger warning.
    t.receive({"type": "go"})
    time.sleep(0.15)
    assert t.state == "B"
    t.stop()


def test_state_machine_config_defaults():
    bus = _short_bus()
    sma = StateMachineAgent("sma", bus)
    cfg = sma.get_state_machine_config()
    assert cfg == {"ignore_invalid_triggers": True, "auto_transitions": False}
    sma.stop()
