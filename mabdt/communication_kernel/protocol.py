"""MessagingProtocol — abstraction over the external broker.

The CommunicationAgent does not depend on paho-mqtt directly. It uses a
MessagingProtocol that exposes connect/disconnect/publish/subscribe. MQTT is
the default backend (MqttProtocol); InMemoryProtocol enables tests and the
toy example to run without a broker.
"""

from __future__ import annotations

import re
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable

from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class MessagingProtocol(ABC):
    """Abstract messaging transport used by the communication kernel."""

    @abstractmethod
    def connect(self) -> None:
        """Establish the connection to the broker (or in-memory bus)."""

    @abstractmethod
    def disconnect(self) -> None:
        """Tear the connection down cleanly."""

    @abstractmethod
    def publish(self, topic: str, payload: bytes | str, qos: int = 1) -> None:
        """Publish a message on `topic`."""

    @abstractmethod
    def subscribe(
        self,
        topic_filter: str,
        handler: Callable[[str, bytes], None],
        qos: int = 1,
    ) -> None:
        """Subscribe to `topic_filter`; `handler(topic, payload)` is called per message."""

    @abstractmethod
    def is_connected(self) -> bool: ...


class MqttProtocol(MessagingProtocol):
    """paho-mqtt backed implementation.

    Args:
        host: Broker hostname or IP.
        port: Broker port (default 1883 plaintext, 8883 TLS).
        keepalive: MQTT keepalive interval in seconds.
        client_id: Optional fixed client ID (paho generates one if None).
        username: Optional MQTT auth username.
        password: Optional MQTT auth password.
    """

    def __init__(
        self,
        host: str,
        port: int = 1883,
        keepalive: int = 60,
        client_id: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        import paho.mqtt.client as mqtt  # local import: avoid hard dep at module level

        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._handlers: list[tuple[str, Callable[[str, bytes], None], int]] = []
        self._connected = False

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            client_id=client_id,
        )
        if username is not None:
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def connect(self) -> None:
        self._client.connect(self._host, self._port, self._keepalive)
        self._client.loop_start()

    def disconnect(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        finally:
            self._connected = False

    def publish(self, topic: str, payload: bytes | str, qos: int = 1) -> None:
        self._client.publish(topic, payload, qos=qos)

    def subscribe(
        self,
        topic_filter: str,
        handler: Callable[[str, bytes], None],
        qos: int = 1,
    ) -> None:
        self._handlers.append((topic_filter, handler, qos))
        if self._connected:
            self._client.subscribe(topic_filter, qos=qos)

    def is_connected(self) -> bool:
        return self._connected

    # --- paho callbacks ---

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            logger.info(f"MQTT connected to {self._host}:{self._port}")
            for topic_filter, _handler, qos in self._handlers:
                client.subscribe(topic_filter, qos=qos)
        else:
            logger.error(f"MQTT connection failed: rc={rc}")

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        if rc != 0:
            logger.warning(f"MQTT unexpected disconnect rc={rc}; reconnecting")
            try:
                client.reconnect()
            except Exception as e:
                logger.error(f"MQTT reconnect failed: {e}")

    def _on_message(self, client, userdata, msg) -> None:
        for topic_filter, handler, _qos in self._handlers:
            if _topic_matches(topic_filter, msg.topic):
                try:
                    handler(msg.topic, msg.payload)
                except Exception as e:
                    logger.error(f"MQTT handler error for '{msg.topic}': {e}")


class InMemoryProtocol(MessagingProtocol):
    """In-memory implementation for tests and the toy_line example.

    Subscribers are stored as (topic_filter, handler) tuples; publishes are
    dispatched synchronously to every handler whose filter matches the
    published topic. Supports MQTT-style wildcards (`+` single-level,
    `#` multi-level tail).
    """

    def __init__(self) -> None:
        self._handlers: list[tuple[str, Callable[[str, bytes], None]]] = []
        self._connected = False
        self._lock = threading.Lock()

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def publish(self, topic: str, payload: bytes | str, qos: int = 1) -> None:
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        with self._lock:
            handlers = list(self._handlers)
        for topic_filter, handler in handlers:
            if _topic_matches(topic_filter, topic):
                try:
                    handler(topic, payload)
                except Exception as e:
                    logger.error(f"InMemory handler error for '{topic}': {e}")

    def subscribe(
        self,
        topic_filter: str,
        handler: Callable[[str, bytes], None],
        qos: int = 1,
    ) -> None:
        with self._lock:
            self._handlers.append((topic_filter, handler))

    def is_connected(self) -> bool:
        return self._connected


# --- Topic-filter matching (shared by both backends) ---


def _topic_matches(topic_filter: str, topic: str) -> bool:
    """Return True if `topic` matches the MQTT `topic_filter`.

    Supports the standard MQTT wildcards (MQTT v5 §4.7):
      `+`  matches exactly one level (no slashes).
      `#`  matches the parent and any number of child levels; must be the
            final character of the filter. For example, `sport/#` matches
            `sport`, `sport/tennis`, and `sport/tennis/player1`.
    """
    if topic_filter == topic:
        return True
    parts = topic_filter.split("/")
    regex_parts: list[str] = []
    has_terminal_hash = False
    for i, p in enumerate(parts):
        if p == "+":
            regex_parts.append(r"[^/]+")
        elif p == "#":
            if i != len(parts) - 1:
                return False  # `#` must be terminal
            has_terminal_hash = True
        else:
            regex_parts.append(re.escape(p))
    if has_terminal_hash:
        prefix = "/".join(regex_parts)
        pattern = "^" + prefix + r"(/.*)?$" if prefix else r"^.*$"
    else:
        pattern = "^" + "/".join(regex_parts) + "$"
    return re.match(pattern, topic) is not None
