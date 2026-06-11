"""TigerCommAgent — the Tiger Motors deployment's communication agent.

Subclass of mabdt.CommunicationAgent that wires up the three Tiger-specific
TopicProcessors (BarcodeProcessor, PLCProcessor, InspectionProcessor) and
constructs the MQTT protocol from a host/port pair.

The MQTT lifecycle, processor dispatch, gate handling, and outbound
forwarding all live in the mabdt base class. This file only declares
the deployment-specific routing rules and the broker wiring.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mabdt import CommunicationAgent as _MABDTCommunicationAgent
from mabdt import MqttProtocol
from tiger_motors_dt.agents.processors import (
    BarcodeProcessor,
    InspectionProcessor,
    PLCProcessor,
)


class CommunicationAgent(_MABDTCommunicationAgent):
    """Tiger Motors communication agent.

    Args:
        bus: The internal EventBus.
        mqtt_host: Broker hostname or IP.
        mqtt_port: Broker port (default 8883 for TLS, 1883 plaintext).
        context: TigerMotorsEnvironment that owns this agent.
        gate: Callable returning True if inbound messages should be
              dispatched. If None and `context` is provided, defaults to
              `lambda: context.tracking_production`.
        keepalive: MQTT keepalive interval in seconds.
        client_id: Optional fixed MQTT client ID. Defaults to
                   `"tiger_motors_dt"`.
    """

    def __init__(
        self,
        bus,
        mqtt_host: str = "localhost",
        mqtt_port: int = 8883,
        context: Any | None = None,
        gate: Callable[[], bool] | None = None,
        keepalive: int = 60,
        client_id: str = "tiger_motors_dt",
    ) -> None:
        protocol = MqttProtocol(
            host=mqtt_host,
            port=mqtt_port,
            keepalive=keepalive,
            client_id=client_id,
        )
        if gate is None and context is not None:
            gate = lambda: getattr(context, "tracking_production", True)
        elif gate is None:
            gate = lambda: True

        super().__init__(
            bus=bus,
            protocol=protocol,
            context=context,
            gate=gate,
            outbound_topic="mqtt",
            name="CommunicationAgent",
        )

        # Register the three Tiger-specific routing processors.
        self.register_processor(BarcodeProcessor())
        self.register_processor(PLCProcessor())
        self.register_processor(InspectionProcessor())

        # Public attributes for code that reads mqtt_host / mqtt_port / broker
        # off the agent (status displays, version banners).
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.broker = f"tcp://{mqtt_host}:{mqtt_port}"
