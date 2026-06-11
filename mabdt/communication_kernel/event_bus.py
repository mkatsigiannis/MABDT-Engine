"""EventBus — internal publish/subscribe messaging with tick + shared table.

Maps to JIM §3.2 "Event Bus". Carries broadcast and one-to-many traffic
between DT agents. Also exposes:

  - A periodic `tick` event other agents can subscribe to (utilization
    counters, recurring actions).
  - A small shared lookup table for engine-wide flags.
  - An outbound reserved topic (default "mqtt") that the CommunicationAgent
    listens on to forward messages to the broker.

The bus is deployment-agnostic: no required config keys, no validation. The
constructor accepts an arbitrary config dict; the only key it consults is
`performance.eventbus_tick_interval` (default 0.01 s) for the tick loop.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class EventBus:
    """Centralized publish/subscribe bus for engine-internal events.

    Args:
        config: Optional configuration dict. If None, an empty dict is used.
                The only key consulted is `performance.eventbus_tick_interval`.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._subs: dict[str, list[Callable]] = {}
        self._config: dict[str, Any] = config if config is not None else {}
        self._shared: dict[str, Any] = {}

        self._tick_interval: float = self._config.get("performance", {}).get(
            "eventbus_tick_interval", 0.01
        )

        self._running = True
        self._tick_thread: threading.Thread | None = None
        self._lock = threading.Lock()

        logger.debug(f"EventBus initialized with tick interval: {self._tick_interval}s")

    # --- Pub/sub ---

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        """Subscribe `callback` to receive every message published on `topic`."""
        with self._lock:
            self._subs.setdefault(topic, []).append(callback)
        logger.debug(
            f"Subscribed to topic '{topic}', total subscribers: {len(self._subs.get(topic, []))}"
        )

    def unsubscribe(self, topic: str, callback: Callable[[Any], None]) -> bool:
        """Remove `callback` from `topic`. Returns True if it was present."""
        with self._lock:
            if topic in self._subs and callback in self._subs[topic]:
                self._subs[topic].remove(callback)
                if not self._subs[topic]:
                    del self._subs[topic]
                logger.debug(f"Unsubscribed from topic '{topic}'")
                return True
        logger.debug(f"Callback not found for topic '{topic}'")
        return False

    def publish(self, topic: str, message: Any) -> None:
        """Publish `message` to all subscribers of `topic`."""
        with self._lock:
            subscribers = self._subs.get(topic, []).copy()
        for callback in subscribers:
            try:
                callback(message)
            except Exception as e:
                logger.error(f"Error in subscriber callback for topic '{topic}': {e}")
        if subscribers:
            logger.debug(f"Published message to topic '{topic}' ({len(subscribers)} subscribers)")

    def get_subscriber_count(self, topic: str) -> int:
        with self._lock:
            return len(self._subs.get(topic, []))

    def get_all_topics(self) -> list[str]:
        with self._lock:
            return list(self._subs.keys())

    def clear_topic(self, topic: str) -> int:
        """Remove all subscribers from `topic`. Returns the count removed."""
        with self._lock:
            if topic in self._subs:
                count = len(self._subs[topic])
                del self._subs[topic]
                logger.info(f"Cleared {count} subscribers from topic '{topic}'")
                return count
        return 0

    # --- Shared lookup table (JIM §3.2 C24) ---

    def get(self, key: str) -> Any:
        """Read a shared-table value. Returns None if unset."""
        with self._lock:
            return self._shared.get(key)

    def set(self, key: str, value: Any) -> None:
        """Write a shared-table value."""
        with self._lock:
            self._shared[key] = value
        logger.debug(f"Set shared storage key '{key}'")

    def get_config_value(self, section: str, key: str, default: Any = None) -> Any:
        """Read a value from the config dict passed at construction."""
        try:
            return self._config.get(section, {}).get(key, default)
        except (KeyError, AttributeError):
            return default

    # --- Periodic tick ---

    def start_tick(self) -> None:
        """Begin the periodic tick loop in a daemon thread."""
        if self._tick_thread is not None and self._tick_thread.is_alive():
            logger.warning("Tick system is already running")
            return

        def tick_loop() -> None:
            logger.info(f"Tick system started with interval {self._tick_interval}s")
            while self._running:
                try:
                    t0 = time.monotonic()
                    self.publish("tick", None)
                    # Subtract the publish duration so the effective tick rate
                    # stays at 1/_tick_interval regardless of how long
                    # publishing to all subscribers takes. Otherwise the
                    # interval becomes (publish_time + _tick_interval), which
                    # at 100 Hz with many subscribers under-counts agent
                    # state times by tens of percent.
                    sleep_for = self._tick_interval - (time.monotonic() - t0)
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                except Exception as e:
                    logger.error(f"Error in tick loop: {e}")
                    break
            logger.info("Tick system stopped")

        self._tick_thread = threading.Thread(target=tick_loop, daemon=True, name="EventBus-Tick")
        self._tick_thread.start()

    def stop_tick(self) -> None:
        """Stop the tick loop and join its thread."""
        self._running = False
        if self._tick_thread and self._tick_thread.is_alive():
            self._tick_thread.join(timeout=1.0)
            if self._tick_thread.is_alive():
                logger.warning("Tick thread did not stop within timeout")
            else:
                logger.info("Tick system stopped successfully")

    def set_tick_interval(self, interval: float) -> None:
        """Update the tick interval. Takes effect on the next loop iteration."""
        if interval <= 0:
            raise ValueError("Tick interval must be positive")
        self._tick_interval = interval
        logger.info(f"Tick interval updated to {interval}s")

    # --- Convenience helpers ---

    def publish_mqtt(self, topic: str, payload: Any, qos: int = 1) -> None:
        """Publish a dict on the reserved outbound 'mqtt' topic.

        Used by DT agents to send commands back to physical devices. The
        deployment's CommunicationAgent subscribes to 'mqtt' and forwards
        each message to the broker.
        """
        message = {"topic": topic, "payload": payload, "qos": qos}
        self.publish("mqtt", message)
        logger.debug(f"MQTT publish forwarded: topic='{topic}', qos={qos}")

    # --- Lifecycle ---

    def shutdown(self) -> None:
        """Stop the tick loop and clear all subscriptions."""
        logger.info("Shutting down EventBus")
        self.stop_tick()
        with self._lock:
            self._subs.clear()
        logger.info("EventBus shutdown complete")
