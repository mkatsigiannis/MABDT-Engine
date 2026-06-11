"""Communication Kernel (JIM §3.2).

Two messaging systems:
  - CommunicationAgent: external boundary, bridges MQTT broker traffic to
    internal events via deployment-specific TopicProcessor instances.
  - EventBus: internal pub/sub, periodic time tick, and shared lookup table.

Plus the MessagingProtocol abstraction (MQTT default, in-memory for tests).
"""

from mabdt.communication_kernel.communication_agent import CommunicationAgent
from mabdt.communication_kernel.event_bus import EventBus
from mabdt.communication_kernel.processor import TopicProcessor
from mabdt.communication_kernel.protocol import (
    InMemoryProtocol,
    MessagingProtocol,
    MqttProtocol,
)

__all__ = [
    "CommunicationAgent",
    "EventBus",
    "InMemoryProtocol",
    "MessagingProtocol",
    "MqttProtocol",
    "TopicProcessor",
]
