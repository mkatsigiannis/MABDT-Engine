"""Smoke tests for mabdt.Agent.

Covers the lifecycle (start/pause/resume/stop), inbox behavior under
pause (the regression vs. JIM §3.1 that Phase 1 fixed), and the
peer-discovery helpers.
"""

from __future__ import annotations

import time
from typing import Any

from mabdt import Agent, EventBus


class _Echo(Agent):
    """Test agent that records every message it processes."""

    def __init__(self, name: str, bus: EventBus) -> None:
        super().__init__(name, bus)
        self.received: list[Any] = []

    def handle(self, msg: Any) -> None:
        self.received.append(msg)


def _short_bus() -> EventBus:
    """EventBus with a short inbox timeout so pause/resume tests are fast."""
    return EventBus({"performance": {"agent_inbox_timeout": 0.05}})


def test_agent_processes_incoming_messages():
    bus = _short_bus()
    a = _Echo("a", bus)
    a.receive({"type": "hello"})
    time.sleep(0.15)
    assert a.received == [{"type": "hello"}]
    a.stop()


def test_pause_queues_messages_without_processing():
    """JIM §3.1 says paused agents should accumulate messages, not drop."""
    bus = _short_bus()
    a = _Echo("a", bus)
    a.pause()
    a.receive({"type": "p1"})
    a.receive({"type": "p2"})
    time.sleep(0.2)
    assert a.received == []
    a.resume()
    time.sleep(0.2)
    assert a.received == [{"type": "p1"}, {"type": "p2"}]
    a.stop()


def test_pause_called_while_get_is_blocked_does_not_lose_message():
    """Race regression: pause() while the run-loop is blocked in get(timeout=...)
    must not drop the message that arrives during the blocked window."""
    bus = _short_bus()
    a = _Echo("a", bus)
    # The run loop will already be in get(timeout=0.05) by now.
    a.pause()
    a.receive({"type": "raced"})
    time.sleep(0.2)
    # Paused, so we should NOT have processed yet.
    assert a.received == []
    a.resume()
    time.sleep(0.2)
    assert a.received == [{"type": "raced"}]
    a.stop()


def test_stop_terminates_the_run_thread():
    bus = _short_bus()
    a = _Echo("a", bus)
    assert a.running is True
    a.stop()
    assert a.running is False


def test_handle_exception_does_not_crash_the_loop():
    bus = _short_bus()

    class _Boom(Agent):
        def __init__(self, name, bus):
            super().__init__(name, bus)
            self.count = 0

        def handle(self, msg):
            self.count += 1
            raise RuntimeError("crash in handle")

    b = _Boom("b", bus)
    b.receive({"type": "first"})
    b.receive({"type": "second"})
    time.sleep(0.2)
    # Both messages should have been seen even though each raised.
    assert b.count == 2
    b.stop()


def test_set_population_and_find_agent_returns_first_match():
    bus = _short_bus()
    a = _Echo("a", bus)
    b = _Echo("b", bus)
    c = _Echo("c", bus)
    population = [a, b, c]
    for agent in population:
        agent.set_population(population)
    assert a.find_agent(lambda x: x.name == "b") is b
    assert a.find_agent(lambda x: False) is None
    for agent in population:
        agent.stop()


def test_send_publishes_on_the_bus():
    bus = _short_bus()
    received: list[Any] = []
    bus.subscribe("alarm", received.append)
    a = _Echo("a", bus)
    a.send("alarm", {"code": 7})
    # send is synchronous through the bus's publish().
    assert received == [{"code": 7}]
    a.stop()
