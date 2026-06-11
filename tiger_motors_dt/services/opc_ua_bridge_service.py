"""OPC UA → MQTT bridge.

Subscribes to KepServerEX OPC UA tags for the workstation Andon lights
and republishes value changes as MQTT messages so the rest of the engine
sees them on a single transport. Reconnects with exponential backoff and
emits Qt signals for the GUI's connection-status widget.
"""

import threading
import time
from datetime import datetime
from enum import Enum
from typing import Any

from PySide6.QtCore import QObject, Signal

from mabdt.utils.logging import get_logger
from tiger_motors_dt.config import load_config

logger = get_logger(__name__)

try:
    from opcua import Client
    from opcua.common.subscription import SubHandler

    OPCUA_AVAILABLE = True
except ImportError:
    OPCUA_AVAILABLE = False

    # Create dummy base class when opcua is not available
    class SubHandler:
        """Dummy SubHandler class when opcua is not available."""

        pass

    Client = None
    logger.warning("opcua library not available. OPC UA service will not function.")
    logger.warning("Install with: pip install opcua")

import paho.mqtt.client as mqtt


class ConnectionState(Enum):
    """Connection state enumeration."""

    DISCONNECTED = "Disconnected"
    CONNECTING = "Connecting"
    CONNECTED = "Connected"
    ERROR = "Error"


class OPCUADataChangeHandler(SubHandler):
    """
    Handler for OPC UA data change notifications.

    This handler is called whenever a subscribed OPC UA tag changes value.
    It publishes the change to MQTT for consumption by the Digital Twin.
    """

    def __init__(
        self, tag_to_ws_dict: dict, mqtt_client: mqtt.Client, service: "OPCUABridgeService"
    ):
        """
        Initialize the data change handler.

        Args:
            tag_to_ws_dict: Mapping of OPC UA tags to (workstation, color) tuples
            mqtt_client: MQTT client for publishing changes
            service: Reference to parent service for logging
        """
        super().__init__()
        self.tag_to_ws_dict = tag_to_ws_dict
        self.mqtt_client = mqtt_client
        self.service = service

    def datachange_notification(self, node, val, data):
        """
        Handle data change notifications from OPC UA server.

        Args:
            node: OPC UA node that changed
            val: New value
            data: Additional data about the change
        """
        try:
            node_id = str(node)
            if node_id in self.tag_to_ws_dict:
                ws, color = self.tag_to_ws_dict[node_id]
                topic = f"plc/{ws}/{color}"

                # Publish to MQTT
                self.mqtt_client.publish(topic, str(val), qos=2, retain=False)

                # Log the change
                message = f"PLC Data Change - {ws}/{color}: {val}"
                self.service._log_message(message)

        except Exception as e:
            self.service._log_error(f"Error in datachange_notification: {e}")


class OPCUABridgeService(QObject):
    """
    OPC UA to MQTT Bridge Service.

    This service connects to an OPC UA server (KepServerEX) and bridges PLC data
    to MQTT for consumption by the Digital Twin system. It operates independently
    of the main simulation and provides robust reconnection capabilities.
    """

    # Qt Signals for GUI integration
    connection_changed = Signal(str)  # Emits connection state
    error_occurred = Signal(str)  # Emits error messages
    message_logged = Signal(str)  # Emits log messages

    def __init__(self, config: dict | None = None, bus=None):
        """
        Initialize the OPC UA Bridge Service.

        Args:
            config: Configuration dictionary (uses defaults if None)
            bus: EventBus instance (optional, for integration with simulation)
        """
        super().__init__()

        self.bus = bus

        # Load config.json as the authoritative source; passed-in config
        # (next block) overrides any specific values the caller cares about.
        self.config = self._load_config()

        # If a config was passed in, merge it (passed config overrides loaded values)
        if config:
            self._merge_config(config)

        # Extract configuration parameters from opc_ua_service section
        opc_config = self.config.get("opc_ua_service", {})
        self.enabled = opc_config.get("enabled", True)
        self.opc_server_url = opc_config.get("opc_server_url", "opc.tcp://localhost:49320")
        self.mqtt_host = opc_config.get("mqtt_host", "localhost")
        self.mqtt_port = opc_config.get("mqtt_port", 8883)
        self.subscription_interval = opc_config.get("subscription_interval", 150)
        self.reconnect_delay = opc_config.get("reconnect_delay", 5)
        self.max_reconnect_delay = opc_config.get("max_reconnect_delay", 60)

        # Connection state
        self.connection_state = ConnectionState.DISCONNECTED
        self.opc_connected = False
        self.mqtt_connected = False

        # Clients
        self.opc_client: Client | None = None
        self.mqtt_client: mqtt.Client | None = None
        self.subscription = None

        # Reconnection control
        self.reconnect_enabled = True
        self.reconnect_thread: threading.Thread | None = None
        self.stop_reconnect_event = threading.Event()

        # Statistics
        self.start_time: datetime | None = None
        self.message_count = 0
        self.last_error: str | None = None

        # Tag to workstation mapping (from original script)
        self.tag_to_ws_dict = {
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA01_BIT_06": ("C1WS1", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA02_BIT_00": ("C1WS2", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA03_BIT_01": ("C1WS3", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA04_BIT_07": ("C1WS4", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA05_BIT13": ("C1WS5", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA06_BIT_06": ("C2WS6", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA07_BIT_00": ("C2WS7", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA08_BIT_01": ("C2WS8", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA09_BIT_07": ("C2WS9", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA10_BIT_13": ("C2WS10", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA11_Bit_13": ("C3WS11", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA12_Bit_07": ("C3WS12", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA13_Bit_01": ("C3WS13", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA14_Bit_00": ("C3WS14", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA15_Bit_06": ("C3WS15", "GRN"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA01_BIT_08": ("C1WS1", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA02_BIT_02": ("C1WS2", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA03_BIT_03": ("C1WS3", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA04_BIT_09": ("C1WS4", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA05_BIT15": ("C1WS5", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA06_BIT_08": ("C2WS6", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA07_BIT_02": ("C2WS7", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA08_BIT_03": ("C2WS8", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA09_BIT_09": ("C2WS9", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA10_BIT_15": ("C2WS10", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA11_Bit_15": ("C3WS11", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA12_Bit_09": ("C3WS12", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA13_Bit_03": ("C3WS13", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA14_Bit_02": ("C3WS14", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA15_Bit_08": ("C3WS15", "YEL"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA01_BIT_10": ("C1WS1", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA02_BIT_04": ("C1WS2", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA03_BIT_05": ("C1WS3", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA04_BIT_11": ("C1WS4", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA05_BIT14": ("C1WS5", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA06_BIT_10": ("C2WS6", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA07_BIT_04": ("C2WS7", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA08_BIT_05": ("C2WS8", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA09_BIT_11": ("C2WS9", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA10_BIT_14": ("C2WS10", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA11_Bit_14": ("C3WS11", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA12_Bit_11": ("C3WS12", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA13_Bit_05": ("C3WS13", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA14_Bit_04": ("C3WS14", "RED"),
            "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA15_Bit_10": ("C3WS15", "RED"),
        }

        # Workstation to tags mapping (for initialization)
        self.ws_to_tags_dict = {
            "C1WS1": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA01_BIT_06",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA01_BIT_08",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA01_BIT_10",
            ),
            "C1WS2": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA02_BIT_00",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA02_BIT_02",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA02_BIT_04",
            ),
            "C1WS3": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA03_BIT_01",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA03_BIT_03",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA03_BIT_05",
            ),
            "C1WS4": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA04_BIT_07",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA04_BIT_09",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA04_BIT_11",
            ),
            "C1WS5": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA05_BIT13",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA05_BIT15",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA05_BIT14",
            ),
            "C2WS6": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA06_BIT_06",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA06_BIT_08",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA06_BIT_10",
            ),
            "C2WS7": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA07_BIT_00",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA07_BIT_02",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA07_BIT_04",
            ),
            "C2WS8": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA08_BIT_01",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA08_BIT_03",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA08_BIT_05",
            ),
            "C2WS9": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA09_BIT_07",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA09_BIT_09",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA09_BIT_11",
            ),
            "C2WS10": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA10_BIT_13",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA10_BIT_15",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA10_BIT_14",
            ),
            "C3WS11": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA11_Bit_13",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA11_Bit_15",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA11_Bit_14",
            ),
            "C3WS12": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA12_Bit_07",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA12_Bit_09",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA12_Bit_11",
            ),
            "C3WS13": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA13_Bit_01",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA13_Bit_03",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA13_Bit_05",
            ),
            "C3WS14": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA14_Bit_00",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA14_Bit_02",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA14_Bit_04",
            ),
            "C3WS15": (
                "ns=2;s=Omron_PLC.NJ101.LGT_GRN_STA15_Bit_06",
                "ns=2;s=Omron_PLC.NJ101.LGT_YEL_STA15_Bit_08",
                "ns=2;s=Omron_PLC.NJ101.LGT_RED_STA15_Bit_10",
            ),
        }

    def _load_config(self) -> dict:
        """Load configuration from `config.json`. Returns `{}` on failure."""
        try:
            return load_config()
        except Exception as e:
            logger.warning(f"Could not load config.json: {e}")
            return {}

    def _merge_config(self, override_config: dict) -> None:
        """
        Merge override config into the loaded config.
        Only updates values that are explicitly provided in override_config.
        """
        for key, value in override_config.items():
            if (
                isinstance(value, dict)
                and key in self.config
                and isinstance(self.config[key], dict)
            ):
                # Deep merge for nested dicts
                self.config[key].update(value)
            else:
                self.config[key] = value

    def _log_message(self, message: str):
        """Log a message and emit signal."""
        logger.info(message)
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {message}"
        self.message_logged.emit(log_msg)
        self.message_count += 1

    def _log_error(self, error: str):
        """Log an error and emit signal."""
        logger.error(error)
        timestamp = datetime.now().strftime("%H:%M:%S")
        error_msg = f"[{timestamp}] ERROR: {error}"
        self.last_error = error
        self.error_occurred.emit(error_msg)

    def _set_connection_state(self, state: ConnectionState):
        """Update connection state and emit signal."""
        self.connection_state = state
        self.connection_changed.emit(state.value)

    def _mqtt_on_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection."""
        if rc == 0:
            self.mqtt_connected = True
            self._log_message("Connected to MQTT broker")

            # Subscribe to workstation initialization topic
            client.subscribe("ws_init/+", qos=2)
            self._log_message("Subscribed to ws_init/+ topic")

            # Update overall connection state
            if self.opc_connected:
                self._set_connection_state(ConnectionState.CONNECTED)
        else:
            self.mqtt_connected = False
            self._log_error(f"MQTT connection failed with code {rc}")

    def _mqtt_on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection."""
        self.mqtt_connected = False
        self._log_message(f"Disconnected from MQTT broker (rc={rc})")

        if self.connection_state == ConnectionState.CONNECTED:
            self._set_connection_state(ConnectionState.DISCONNECTED)

            # Trigger reconnection if enabled
            if self.reconnect_enabled:
                self._start_reconnect_thread()

    def _mqtt_on_message(self, client, userdata, msg):
        """Handle MQTT messages (workstation initialization requests)."""
        try:
            topic = msg.topic

            # Handle workstation initialization
            if topic.startswith("ws_init/"):
                ws_id = topic.split("/")[1]

                if ws_id in self.ws_to_tags_dict and self.opc_connected:
                    tags = self.ws_to_tags_dict[ws_id]

                    # Read current values and publish the active light
                    for tag_id in tags:
                        try:
                            tag = self.opc_client.get_node(tag_id)
                            value = tag.get_value()

                            if value:
                                ws, color = self.tag_to_ws_dict[tag_id]
                                client.publish(f"plc/{ws}/{color}", "True", qos=2, retain=False)
                                self._log_message(f"Initialized {ws_id}: {color} light active")
                                break
                        except Exception as e:
                            self._log_error(f"Error reading tag {tag_id}: {e}")

        except Exception as e:
            self._log_error(f"Error in MQTT message handler: {e}")

    def start_service(self):
        """Start the OPC UA bridge service."""
        if not self.enabled:
            self._log_message("OPC UA service is disabled in configuration")
            return

        if not OPCUA_AVAILABLE:
            self._log_error("OPC UA library not available. Install with: pip install opcua")
            self._set_connection_state(ConnectionState.ERROR)
            return

        self._log_message("Starting OPC UA Bridge Service...")
        self.start_time = datetime.now()
        self.stop_reconnect_event.clear()

        # Attempt initial connection
        self._connect()

    def _connect(self):
        """Attempt to connect to OPC UA server and MQTT broker."""
        self._set_connection_state(ConnectionState.CONNECTING)

        try:
            # Initialize MQTT client
            if self.mqtt_client is None:
                self.mqtt_client = mqtt.Client()
                self.mqtt_client.on_connect = self._mqtt_on_connect
                self.mqtt_client.on_disconnect = self._mqtt_on_disconnect
                self.mqtt_client.on_message = self._mqtt_on_message

            # Connect to MQTT broker
            if not self.mqtt_connected:
                self._log_message(
                    f"Connecting to MQTT broker at {self.mqtt_host}:{self.mqtt_port}..."
                )
                self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
                self.mqtt_client.loop_start()

            # Initialize OPC UA client
            if self.opc_client is None:
                self._log_message(f"Connecting to OPC UA server at {self.opc_server_url}...")
                self.opc_client = Client(self.opc_server_url)

            # Connect to OPC UA server
            if not self.opc_connected:
                self.opc_client.connect()
                self.opc_connected = True
                self._log_message("Connected to OPC UA server")

                # Create subscription with data change handler
                handler = OPCUADataChangeHandler(self.tag_to_ws_dict, self.mqtt_client, self)
                self.subscription = self.opc_client.create_subscription(
                    self.subscription_interval, handler
                )

                # Subscribe to all workstation light tags
                for tag_id in self.tag_to_ws_dict.keys():
                    self.subscription.subscribe_data_change(self.opc_client.get_node(tag_id))

                self._log_message(f"Subscribed to {len(self.tag_to_ws_dict)} OPC UA tags")

                # Update connection state
                if self.mqtt_connected:
                    self._set_connection_state(ConnectionState.CONNECTED)
                    self._log_message("OPC UA Bridge Service is fully operational")

        except Exception as e:
            self._log_error(f"Connection failed: {e}")
            self._set_connection_state(ConnectionState.ERROR)

            # Start reconnection thread if enabled
            if self.reconnect_enabled:
                self._start_reconnect_thread()

    def _start_reconnect_thread(self):
        """Start the reconnection thread if not already running."""
        if self.reconnect_thread is None or not self.reconnect_thread.is_alive():
            self.reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
            self.reconnect_thread.start()

    def _reconnect_loop(self):
        """Background thread that attempts reconnection with exponential backoff."""
        current_delay = self.reconnect_delay

        while self.reconnect_enabled and not self.stop_reconnect_event.is_set():
            # Check if we need to reconnect
            if self.connection_state != ConnectionState.CONNECTED:
                self._log_message(f"Attempting reconnection in {current_delay} seconds...")

                # Wait with ability to cancel
                if self.stop_reconnect_event.wait(current_delay):
                    break

                # Attempt reconnection
                try:
                    self._connect()

                    # If successful, reset delay
                    if self.connection_state == ConnectionState.CONNECTED:
                        current_delay = self.reconnect_delay
                        break
                    else:
                        # Exponential backoff
                        current_delay = min(current_delay * 2, self.max_reconnect_delay)

                except Exception as e:
                    self._log_error(f"Reconnection attempt failed: {e}")
                    current_delay = min(current_delay * 2, self.max_reconnect_delay)
            else:
                # Already connected, exit loop
                break

    def stop_service(self):
        """Stop the OPC UA bridge service."""
        self._log_message("Stopping OPC UA Bridge Service...")

        # Stop reconnection attempts
        self.reconnect_enabled = False
        self.stop_reconnect_event.set()

        # Disconnect OPC UA
        if self.opc_client and self.opc_connected:
            try:
                self.opc_client.disconnect()
                self._log_message("Disconnected from OPC UA server")
            except Exception as e:
                self._log_error(f"Error disconnecting OPC UA: {e}")
            finally:
                self.opc_connected = False
                self.opc_client = None

        # Disconnect MQTT
        if self.mqtt_client and self.mqtt_connected:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
                self._log_message("Disconnected from MQTT broker")
            except Exception as e:
                self._log_error(f"Error disconnecting MQTT: {e}")
            finally:
                self.mqtt_connected = False

        # Wait for reconnection thread to finish
        if self.reconnect_thread and self.reconnect_thread.is_alive():
            self.reconnect_thread.join(timeout=2)

        self._set_connection_state(ConnectionState.DISCONNECTED)
        self._log_message("OPC UA Bridge Service stopped")

    def enable_reconnection(self, enabled: bool):
        """
        Enable or disable automatic reconnection.

        Args:
            enabled: True to enable reconnection, False to disable
        """
        self.reconnect_enabled = enabled

        if enabled:
            self._log_message("Automatic reconnection enabled")
            if self.connection_state != ConnectionState.CONNECTED:
                self._start_reconnect_thread()
        else:
            self._log_message("Automatic reconnection disabled")
            self.stop_reconnect_event.set()

    def get_service_status(self) -> dict[str, Any]:
        """
        Get current service status.

        Returns:
            Dictionary containing service status information
        """
        uptime = None
        if self.start_time:
            uptime = (datetime.now() - self.start_time).total_seconds()

        return {
            "enabled": self.enabled,
            "connection_state": self.connection_state.value,
            "opc_connected": self.opc_connected,
            "mqtt_connected": self.mqtt_connected,
            "reconnect_enabled": self.reconnect_enabled,
            "opc_server_url": self.opc_server_url,
            "mqtt_host": self.mqtt_host,
            "mqtt_port": self.mqtt_port,
            "uptime": uptime,
            "message_count": self.message_count,
            "last_error": self.last_error,
            "subscribed_tags": len(self.tag_to_ws_dict),
        }

    def set_event_bus(self, bus):
        """
        Set EventBus reference for integration with simulation.

        Args:
            bus: EventBus instance
        """
        self.bus = bus
        self._log_message("Connected to EventBus")


# Standalone execution
if __name__ == "__main__":
    logger.info("OPC UA Bridge Service - Standalone Mode")
    logger.info("=" * 50)

    # Create and start service (config.json is loaded internally).
    service = OPCUABridgeService()
    service.start_service()

    try:
        logger.info("Service running. Press Ctrl+C to stop...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        service.stop_service()
        logger.info("Service stopped.")
