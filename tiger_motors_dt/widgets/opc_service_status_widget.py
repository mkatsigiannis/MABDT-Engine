"""Compact OPC UA bridge status indicator for embedding in the production tab."""

from datetime import timedelta

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QPushButton

from tiger_motors_dt.services.opc_ua_bridge_service import OPCUABridgeService


class OPCServiceStatusWidget(QGroupBox):
    """Compact status + start/stop + reconnect-toggle widget for the OPC UA bridge."""

    # Signals
    service_started = Signal()
    service_stopped = Signal()

    def __init__(self, config: dict | None = None, bus=None, parent=None):
        """
        Initialize the OPC UA service status widget.

        Args:
            config: Configuration dictionary
            bus: EventBus instance (optional)
            parent: Parent widget
        """
        super().__init__("OPC UA Bridge", parent)

        # Initialize service
        self.service = OPCUABridgeService(config, bus)
        self.config = config or {}
        self.bus = bus

        # Connect service signals
        self.service.connection_changed.connect(self._on_connection_changed)
        self.service.error_occurred.connect(self._on_error)
        self.service.message_logged.connect(self._on_message)

        # State tracking
        self.is_running = False
        self.last_messages = []  # Keep last 5 messages for tooltip
        self.max_messages = 5

        # Setup UI
        self.setup_ui()

        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(2000)  # Update every 2 seconds

        # Auto-start if configured
        opc_config = self.config.get("opc_ua_service", {})
        if opc_config.get("auto_start", False):
            QTimer.singleShot(500, self.start_service)

    def setup_ui(self):
        """Create and arrange the compact UI elements."""
        # Main horizontal layout for compact design
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Status indicator (color-coded label)
        self.status_label = QLabel("●")
        self.status_label.setAlignment(Qt.AlignCenter)
        status_font = QFont()
        status_font.setPointSize(16)
        status_font.setBold(True)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("QLabel { color: #f44336; }")  # Red by default
        self.status_label.setToolTip("Disconnected")

        # Status text
        self.status_text = QLabel("Disconnected")
        self.status_text.setStyleSheet("QLabel { font-weight: bold; }")

        # Start/Stop button
        self.toggle_button = QPushButton("Start")
        self.toggle_button.setFixedWidth(70)
        self.toggle_button.clicked.connect(self.toggle_service)
        self.toggle_button.setStyleSheet(
            """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 4px;
                font-weight: bold;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """
        )

        # Reconnection checkbox
        self.reconnect_checkbox = QCheckBox("Auto-reconnect")
        self.reconnect_checkbox.setChecked(True)
        self.reconnect_checkbox.stateChanged.connect(self._on_reconnect_toggled)
        self.reconnect_checkbox.setToolTip("Enable automatic reconnection on connection loss")

        # Add widgets to layout
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.status_text)
        main_layout.addStretch()
        main_layout.addWidget(self.reconnect_checkbox)
        main_layout.addWidget(self.toggle_button)

        self.setLayout(main_layout)

        # Set compact size
        self.setMaximumHeight(80)

        # Initial display update
        self.update_display()

    def start_service(self):
        """Start the OPC UA bridge service."""
        try:
            if self.is_running:
                return

            self.toggle_button.setEnabled(False)
            self.status_text.setText("Starting...")

            # Start service in background
            self.service.start_service()

            self.is_running = True
            self.toggle_button.setText("Stop")
            self.toggle_button.setStyleSheet(
                """
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    padding: 4px;
                    font-weight: bold;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #da190b;
                }
            """
            )
            self.toggle_button.setEnabled(True)

            self.service_started.emit()

        except Exception as e:
            self.status_text.setText("Error")
            self._on_error(f"Failed to start service: {e}")
            self.toggle_button.setEnabled(True)

    def stop_service(self):
        """Stop the OPC UA bridge service."""
        try:
            if not self.is_running:
                return

            self.toggle_button.setEnabled(False)
            self.status_text.setText("Stopping...")

            # Stop service
            self.service.stop_service()

            self.is_running = False
            self.toggle_button.setText("Start")
            self.toggle_button.setStyleSheet(
                """
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    padding: 4px;
                    font-weight: bold;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """
            )
            self.toggle_button.setEnabled(True)

            self.service_stopped.emit()

        except Exception as e:
            self._on_error(f"Failed to stop service: {e}")
            self.toggle_button.setEnabled(True)

    def toggle_service(self):
        """Toggle service on/off."""
        if self.is_running:
            self.stop_service()
        else:
            self.start_service()

    def _on_connection_changed(self, state: str):
        """Handle connection state changes."""
        # Update status display based on state
        if state == "Connected":
            self.status_label.setStyleSheet("QLabel { color: #4CAF50; }")  # Green
            self.status_text.setText("Connected")
            self.status_label.setToolTip("Connected to OPC UA server and MQTT broker")
        elif state == "Connecting":
            self.status_label.setStyleSheet("QLabel { color: #ff9800; }")  # Orange
            self.status_text.setText("Connecting...")
            self.status_label.setToolTip("Attempting to connect...")
        elif state == "Error":
            self.status_label.setStyleSheet("QLabel { color: #f44336; }")  # Red
            self.status_text.setText("Error")
            self.status_label.setToolTip("Connection error - check logs")
        else:  # Disconnected
            self.status_label.setStyleSheet("QLabel { color: #9e9e9e; }")  # Gray
            self.status_text.setText("Disconnected")
            self.status_label.setToolTip("Not connected")

        # Update full tooltip
        self.update_tooltip()

    def _on_error(self, error: str):
        """Handle error messages."""
        # Add to message log
        self._add_message(f"ERROR: {error}")
        self.update_tooltip()

    def _on_message(self, message: str):
        """Handle log messages."""
        # Add to message log
        self._add_message(message)

    def _add_message(self, message: str):
        """Add a message to the recent messages list."""
        self.last_messages.append(message)
        if len(self.last_messages) > self.max_messages:
            self.last_messages.pop(0)

    def _on_reconnect_toggled(self, state: int):
        """Handle reconnection checkbox toggle."""
        enabled = state == Qt.CheckState.Checked.value
        self.service.enable_reconnection(enabled)

    def update_display(self):
        """Update the display with current service status."""
        try:
            self.update_tooltip()
        except Exception:
            pass  # Silently ignore update errors

    def update_tooltip(self):
        """Update the detailed tooltip with service information."""
        try:
            status = self.service.get_service_status()

            # Format uptime
            uptime_str = "N/A"
            if status["uptime"] is not None:
                uptime = timedelta(seconds=int(status["uptime"]))
                hours = uptime.seconds // 3600
                minutes = (uptime.seconds % 3600) // 60
                seconds = uptime.seconds % 60
                uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            # Build tooltip text
            tooltip_parts = [
                "<b>OPC UA Bridge Service</b>",
                "<hr>",
                f"<b>Status:</b> {status['connection_state']}",
                f"<b>OPC UA:</b> {'Connected' if status['opc_connected'] else 'Disconnected'}",
                f"<b>MQTT:</b> {'Connected' if status['mqtt_connected'] else 'Disconnected'}",
                "<hr>",
                f"<b>Server:</b> {status['opc_server_url']}",
                f"<b>MQTT:</b> {status['mqtt_host']}:{status['mqtt_port']}",
                "<hr>",
                f"<b>Uptime:</b> {uptime_str}",
                f"<b>Messages:</b> {status['message_count']}",
                f"<b>Tags:</b> {status['subscribed_tags']}",
            ]

            # Add last error if present
            if status["last_error"]:
                tooltip_parts.append("<hr>")
                tooltip_parts.append(f"<b>Last Error:</b><br>{status['last_error']}")

            # Add recent messages
            if self.last_messages:
                tooltip_parts.append("<hr>")
                tooltip_parts.append("<b>Recent Messages:</b>")
                for msg in self.last_messages[-3:]:  # Show last 3 messages
                    tooltip_parts.append(f"• {msg}")

            tooltip_text = "<br>".join(tooltip_parts)

            # Set tooltip on the entire widget
            self.setToolTip(tooltip_text)
            self.status_label.setToolTip(tooltip_text)
            self.status_text.setToolTip(tooltip_text)

        except Exception:
            pass  # Silently ignore tooltip update errors

    def get_service(self) -> OPCUABridgeService:
        """Get the underlying service instance."""
        return self.service

    def set_event_bus(self, bus):
        """
        Set EventBus reference for late binding integration.

        Args:
            bus: EventBus instance from the simulation environment
        """
        self.bus = bus
        if self.service:
            self.service.set_event_bus(bus)

    def cleanup(self):
        """Clean up resources when widget is destroyed."""
        self.update_timer.stop()
        if self.is_running:
            self.stop_service()
