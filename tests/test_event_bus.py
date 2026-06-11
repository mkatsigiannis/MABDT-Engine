"""Smoke tests for mabdt.EventBus."""

from __future__ import annotations

import time

from mabdt import EventBus


def test_pub_sub_delivers_to_all_subscribers():
    bus = EventBus({})
    received_a, received_b = [], []
    bus.subscribe("topic", received_a.append)
    bus.subscribe("topic", received_b.append)
    bus.publish("topic", {"x": 1})
    assert received_a == [{"x": 1}]
    assert received_b == [{"x": 1}]


def test_unsubscribe_removes_callback():
    bus = EventBus({})
    msgs = []
    cb = msgs.append
    bus.subscribe("t", cb)
    bus.publish("t", "first")
    assert bus.unsubscribe("t", cb) is True
    bus.publish("t", "second")
    assert msgs == ["first"]


def test_publish_with_no_subscribers_does_not_raise():
    bus = EventBus({})
    bus.publish("nobody-listening", 42)


def test_get_set_shared_lookup_table():
    bus = EventBus({})
    assert bus.get("missing") is None
    bus.set("flag", True)
    assert bus.get("flag") is True


def test_get_config_value_with_defaults():
    bus = EventBus({"performance": {"eventbus_tick_interval": 0.05}})
    assert bus.get_config_value("performance", "eventbus_tick_interval") == 0.05
    assert bus.get_config_value("performance", "missing", default=99) == 99
    assert bus.get_config_value("missing_section", "x", default="d") == "d"


def test_tick_loop_publishes_periodically():
    bus = EventBus({"performance": {"eventbus_tick_interval": 0.01}})
    ticks: list[float] = []
    bus.subscribe("tick", lambda _: ticks.append(time.time()))
    bus.start_tick()
    time.sleep(0.1)
    bus.stop_tick()
    # ~10 ticks expected in 100ms; require ≥3 to tolerate scheduling jitter.
    assert len(ticks) >= 3
    bus.shutdown()


def test_publish_mqtt_forwards_on_reserved_topic():
    bus = EventBus({})
    forwarded: list[dict] = []
    bus.subscribe("mqtt", forwarded.append)
    bus.publish_mqtt("leds/WS1", "ON", qos=2)
    assert forwarded == [{"topic": "leds/WS1", "payload": "ON", "qos": 2}]


def test_callback_exception_does_not_abort_other_subscribers():
    bus = EventBus({})
    received: list[str] = []

    def boom(_):
        raise RuntimeError("subscriber failure")

    bus.subscribe("t", boom)
    bus.subscribe("t", received.append)
    bus.publish("t", "ok")
    # Despite the first subscriber raising, the second still gets the message.
    assert received == ["ok"]


def test_shutdown_stops_tick_and_clears_subscribers():
    bus = EventBus({"performance": {"eventbus_tick_interval": 0.01}})
    bus.subscribe("t", lambda _: None)
    bus.start_tick()
    bus.shutdown()
    assert bus.get_all_topics() == []
