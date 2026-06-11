"""Smoke tests for the communication kernel: protocol + CommunicationAgent.

Includes explicit regression coverage for the two Phase 3a bugs that
landed and were fixed in this branch:

  1. InspectionProcessor subscribed to `scanner/InspectionStation` exactly,
     so the lab's `scanner/C3InspectionStation1` topic was silently dropped.
     The fix is in InspectionProcessor (subscribe to `scanner/+`, filter
     by "InspectionStation" in topic); covered here at the protocol level.

  2. Two processors sharing the same topic filter caused the protocol to
     register the filter twice, so paho's single on_message dispatch
     invoked the CommAgent's _on_message TWICE per delivered message.
     The fix de-duplicates (filter, qos) pairs in CommunicationAgent.start
     and register_processor.
"""

from __future__ import annotations

from typing import Any

import pytest

from mabdt import (
    CommunicationAgent,
    EventBus,
    InMemoryProtocol,
    TopicProcessor,
)
from mabdt.communication_kernel.protocol import _topic_matches

# ----- _topic_matches -------------------------------------------------------


@pytest.mark.parametrize(
    "topic_filter,topic,expected",
    [
        ("scanner/+", "scanner/WS1", True),
        ("scanner/+", "scanner/InspectionStation", True),  # + matches one level
        ("scanner/+", "scanner/WS1/extra", False),  # + does NOT span levels
        ("plc/#", "plc/WS1/GRN", True),
        ("plc/#", "plc", True),  # # matches the parent level too (MQTT spec)
        ("plc/#", "plctest", False),  # but not a sibling at root
        ("#", "anything/at/all", True),
        ("scanner/WS1", "scanner/WS1", True),
        ("scanner/WS1", "scanner/WS2", False),
    ],
)
def test_topic_matches_mqtt_wildcards(topic_filter, topic, expected):
    assert _topic_matches(topic_filter, topic) is expected


# ----- InMemoryProtocol -----------------------------------------------------


def test_in_memory_protocol_dispatches_to_matching_subscribers_only():
    p = InMemoryProtocol()
    p.connect()
    received: list[tuple[str, bytes]] = []
    p.subscribe("scanner/+", lambda t, b: received.append((t, b)))
    p.publish("scanner/WS1", "SUV1")
    p.publish("plc/WS1", "GRN")  # different filter — should not deliver
    p.publish("scanner/WS5", b"SPEEDSTER3")
    assert received == [
        ("scanner/WS1", b"SUV1"),
        ("scanner/WS5", b"SPEEDSTER3"),
    ]


# ----- CommunicationAgent: per-processor dispatch ---------------------------


class _Recorder(TopicProcessor):
    """Minimal TopicProcessor that counts process() calls."""

    def __init__(self, name: str, subs: list[tuple[str, int]]):
        self.name = name
        self._subs = subs
        self.calls: list[tuple[str, bytes]] = []

    @property
    def subscriptions(self) -> list[tuple[str, int]]:
        return self._subs

    def process(self, topic: str, payload: bytes, context: Any) -> None:
        self.calls.append((topic, payload))


def _fresh_bus() -> EventBus:
    return EventBus({"performance": {"agent_inbox_timeout": 0.05}})


def test_dispatch_routes_to_only_matching_processors():
    bus = _fresh_bus()
    proto = InMemoryProtocol()
    a = _Recorder("a", [("scanner/+", 1)])
    b = _Recorder("b", [("plc/#", 1)])
    comm = CommunicationAgent(bus, proto, context=None)
    comm.register_processor(a)
    comm.register_processor(b)
    comm.start()

    proto.publish("scanner/WS1", b"SUV1")
    proto.publish("plc/WS1/GRN", b"True")

    assert a.calls == [("scanner/WS1", b"SUV1")]
    assert b.calls == [("plc/WS1/GRN", b"True")]
    comm.stop()
    bus.shutdown()


def test_gate_blocks_inbound_when_closed():
    bus = _fresh_bus()
    proto = InMemoryProtocol()
    a = _Recorder("a", [("scanner/+", 1)])
    gate_open = [False]
    comm = CommunicationAgent(bus, proto, context=None, gate=lambda: gate_open[0])
    comm.register_processor(a)
    comm.start()

    proto.publish("scanner/WS1", b"SUV1")
    assert a.calls == []  # gate closed → message dropped

    gate_open[0] = True
    proto.publish("scanner/WS1", b"SUV1")
    assert a.calls == [("scanner/WS1", b"SUV1")]
    comm.stop()
    bus.shutdown()


def test_outbound_forward_publishes_via_protocol():
    bus = _fresh_bus()
    inbound_proto = InMemoryProtocol()
    comm = CommunicationAgent(bus, inbound_proto, context=None)
    comm.start()

    # Swap in a fresh in-memory protocol to observe the outbound publish.
    observe = InMemoryProtocol()
    observe.connect()
    seen: list[tuple[str, bytes]] = []
    observe.subscribe("leds/+", lambda t, b: seen.append((t, b)))
    comm._protocol = observe  # type: ignore[attr-defined]

    bus.publish_mqtt("leds/WS1", "ON", qos=1)
    # publish_mqtt is synchronous through the bus subscriber chain.
    assert seen == [("leds/WS1", b"ON")]
    comm.stop()
    bus.shutdown()


# ----- Regression: duplicate (filter, qos) dedup ----------------------------


def test_shared_topic_filter_does_not_cause_double_dispatch():
    """Two processors with the same `scanner/+` filter should NOT cause
    each processor's process() to be called twice per message.

    Bug: in Phase 3a, BarcodeProcessor and InspectionProcessor both
    subscribed to scanner/+. The protocol registered scanner/+ twice,
    so MqttProtocol._on_message walked the handler list and called the
    CommAgent dispatcher twice per delivered message, doubling every
    downstream effect (Starting + Completing from a single scan, no
    Moving messages, inspection station stuck).
    """
    bus = _fresh_bus()
    proto = InMemoryProtocol()
    a = _Recorder("a", [("scanner/+", 1)])
    b = _Recorder("b", [("scanner/+", 1)])
    comm = CommunicationAgent(bus, proto, context=None)
    comm.register_processor(a)
    comm.register_processor(b)
    comm.start()

    # Only one unique (filter, qos) registered on the protocol despite two
    # processors declaring the same subscription.
    assert len(comm._subscribed) == 1  # type: ignore[attr-defined]

    proto.publish("scanner/WS1", b"SUV1")
    assert a.calls == [("scanner/WS1", b"SUV1")]
    assert b.calls == [("scanner/WS1", b"SUV1")]

    proto.publish("scanner/WS1", b"SUV2")
    assert len(a.calls) == 2
    assert len(b.calls) == 2

    comm.stop()
    bus.shutdown()


def test_late_register_processor_still_deduplicates():
    bus = _fresh_bus()
    proto = InMemoryProtocol()
    a = _Recorder("a", [("scanner/+", 1)])
    comm = CommunicationAgent(bus, proto, context=None)
    comm.register_processor(a)
    comm.start()
    # Register a second processor on the same filter AFTER start.
    b = _Recorder("b", [("scanner/+", 1)])
    comm.register_processor(b)
    assert len(comm._subscribed) == 1  # type: ignore[attr-defined]

    proto.publish("scanner/WS1", b"SUV1")
    assert a.calls == [("scanner/WS1", b"SUV1")]
    assert b.calls == [("scanner/WS1", b"SUV1")]
    comm.stop()
    bus.shutdown()


def test_distinct_processors_distinct_filters_both_subscribed():
    bus = _fresh_bus()
    proto = InMemoryProtocol()
    a = _Recorder("a", [("scanner/+", 1)])
    b = _Recorder("b", [("plc/#", 1)])
    comm = CommunicationAgent(bus, proto, context=None)
    comm.register_processor(a)
    comm.register_processor(b)
    comm.start()
    assert len(comm._subscribed) == 2  # type: ignore[attr-defined]
    comm.stop()
    bus.shutdown()
