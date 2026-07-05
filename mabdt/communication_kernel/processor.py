"""TopicProcessor — deployment-specific routing rule.

Each TopicProcessor subclass declares the MQTT topic patterns it cares about
and a `process(topic, payload, context)` method that parses the payload,
looks up the target agent, and emits the appropriate internal event.

A manufacturing deployment, for example, may supply one processor per inbound
topic family (e.g. barcode scanner, PLC bridge, inspection station), each
implementing the JIM paper's "rule-based routing pipeline" for that family. The
CommunicationAgent base iterates over registered processors at subscription
time and dispatch time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TopicProcessor(ABC):
    """Abstract routing rule for one or more inbound MQTT topic patterns.

    Subclasses declare:
      - `subscriptions`: a list of (topic_filter, qos) tuples to subscribe to
      - `process(topic, payload, context)`: how to handle each delivery
    """

    @property
    @abstractmethod
    def subscriptions(self) -> list[tuple[str, int]]:
        """Topic filters + QoS values this processor wants to receive."""

    @abstractmethod
    def process(self, topic: str, payload: bytes, context: Any) -> None:
        """Parse a delivered message and dispatch the appropriate internal event.

        `context` is an opaque object handed to every processor by the
        CommunicationAgent at registration time. Deployments typically pack
        their environment, event bus, and any helper references into it.
        """
