"""CommunicationAgent — boundary between the physical layer and DT agents.

Maps to the JIM paper's "Communication Agent" subsection. Manages the MessagingProtocol
connection lifecycle, subscribes to the topics declared by registered
TopicProcessor instances, and dispatches inbound messages through them.

Outbound: a DT agent publishes to a reserved internal topic on the event
bus; this agent forwards the payload to the messaging protocol. The rest
of the engine never talks to the broker directly.

A `gate` callable lets deployments block inbound dispatch when production is
not active (e.g. wire it to `environment.tracking_production`). Default is
always-open. Outbound forwarding always runs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mabdt.agent.base import Agent
from mabdt.communication_kernel.event_bus import EventBus
from mabdt.communication_kernel.processor import TopicProcessor
from mabdt.communication_kernel.protocol import MessagingProtocol
from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class CommunicationAgent(Agent):
    """MQTT boundary + processor dispatch.

    Args:
        bus: The internal EventBus.
        protocol: MessagingProtocol implementation (MQTT or in-memory).
        context: Object passed to every TopicProcessor.process call.
                 Deployments typically pack environment + helpers here.
        gate: Callable returning True if inbound messages should be dispatched.
              Default: always True.
        outbound_topic: Internal bus topic to listen on for outbound forwards.
                        Default: "mqtt".
        name: Agent name. Default: "CommunicationAgent".
    """

    def __init__(
        self,
        bus: EventBus,
        protocol: MessagingProtocol,
        context: Any,
        gate: Callable[[], bool] = lambda: True,
        outbound_topic: str = "mqtt",
        name: str = "CommunicationAgent",
    ) -> None:
        super().__init__(name, bus)
        self._protocol = protocol
        self._context = context
        self._gate = gate
        self._outbound_topic = outbound_topic
        self._processors: list[TopicProcessor] = []
        self._started = False

        # Track (topic_filter, qos) pairs already registered on the protocol.
        # The dispatcher in _on_message ALREADY routes one delivered message
        # to every processor whose declared filter matches — so the protocol
        # only needs ONE subscription per unique filter. Subscribing the same
        # filter twice (e.g. BarcodeProcessor and InspectionProcessor both
        # wanting `scanner/+`) makes the protocol invoke our _on_message
        # twice per delivered message, doubling every downstream effect.
        self._subscribed: set[tuple[str, int]] = set()

        # Outbound: bus -> broker
        self.bus.subscribe(outbound_topic, self._outbound_forward)

    # --- Processor registration ---

    def register_processor(self, processor: TopicProcessor) -> None:
        """Register a TopicProcessor.

        Its declared subscriptions are applied on the next connect (or
        immediately if the protocol is already connected). Filters are
        de-duplicated across processors at the protocol layer.
        """
        self._processors.append(processor)
        if self._started and self._protocol.is_connected():
            self._apply_subscriptions(processor)

    def processors(self) -> list[TopicProcessor]:
        """Return the registered processors in registration order."""
        return list(self._processors)

    def _apply_subscriptions(self, processor: TopicProcessor) -> None:
        """Subscribe each of `processor`'s filters on the protocol, skipping
        (filter, qos) pairs already registered by another processor.
        """
        for topic_filter, qos in processor.subscriptions:
            key = (topic_filter, qos)
            if key in self._subscribed:
                continue
            self._subscribed.add(key)
            self._protocol.subscribe(topic_filter, self._on_message, qos=qos)

    # --- Lifecycle ---

    def start(self) -> None:
        """Connect to the protocol and subscribe to all processor topics."""
        self._protocol.connect()
        for processor in self._processors:
            self._apply_subscriptions(processor)
        self._started = True
        logger.info(
            f"CommunicationAgent started with "
            f"{len(self._processors)} processor(s), "
            f"{len(self._subscribed)} unique filter(s)"
        )

    def stop(self) -> None:
        """Disconnect from the protocol and shut down the agent thread."""
        try:
            self._protocol.disconnect()
        finally:
            self._started = False
            super().stop()
            logger.info("CommunicationAgent stopped")

    # --- Inbound / outbound ---

    def _on_message(self, topic: str, payload: bytes) -> None:
        """Receive a message from the protocol; dispatch to processors.

        Applies the gate first. If the gate is closed, the message is
        silently dropped — the contract is "no DT agent state changes while
        production is not active." Each processor that claims `topic`
        gets a chance to handle it; multiple matches are allowed.
        """
        if not self._gate():
            return
        for processor in self._processors:
            for topic_filter, _qos in processor.subscriptions:
                from mabdt.communication_kernel.protocol import _topic_matches

                if _topic_matches(topic_filter, topic):
                    try:
                        processor.process(topic, payload, self._context)
                    except Exception as e:
                        logger.error(
                            f"Processor {type(processor).__name__} failed on '{topic}': {e}"
                        )
                    break  # this processor handles the message once even if several of its filters match

    def _outbound_forward(self, message: dict) -> None:
        """Forward a bus message to the messaging protocol.

        Expects a dict of shape {"topic": str, "payload": bytes|str, "qos": int}.
        Other shapes are logged and discarded.
        """
        if not isinstance(message, dict) or "topic" not in message:
            logger.warning(f"Outbound forward received non-conforming message: {message!r}")
            return
        topic = message["topic"]
        payload = message.get("payload", b"")
        qos = message.get("qos", 1)
        try:
            self._protocol.publish(topic, payload, qos=qos)
        except Exception as e:
            logger.error(f"Outbound publish to '{topic}' failed: {e}")
