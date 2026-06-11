"""GUI controls for the Barcode Scanner Service: start/stop, status, and message log."""

from datetime import datetime

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mabdt.utils.logging import get_logger
from tiger_motors_dt.services.barcode_scanner_service import BarcodeServerService

logger = get_logger(__name__)


class ServiceWorker(QThread):
    """
    Worker thread for running the Barcode Scanner Service.

    This follows the same pattern as EnvironmentWorker for background service execution.
    """

    service_started = Signal()
    service_stopped = Signal()
    error_occurred = Signal(str)

    def __init__(self, service: BarcodeServerService):
        super().__init__()
        self.service = service

        # Connect service signals to worker signals
        self.service.service_started.connect(self.service_started.emit)
        self.service.service_stopped.connect(self.service_stopped.emit)
        self.service.error_occurred.connect(self.error_occurred.emit)

    def start_service(self):
        """Start the service."""
        self.service.start_service()

    def stop_service(self):
        """Stop the service."""
        self.service.stop_service()


class BarcodeServiceControlWidget(QGroupBox):
    """
    Control widget for the Barcode Scanner Service.

    Provides start/stop controls and status display similar to ProductionControlWidget.
    """

    # Signals for communication with main GUI
    service_started = Signal()
    service_stopped = Signal()

    def __init__(self, config: dict | None = None, bus=None, parent=None):
        super().__init__("Barcode Scanner Service Control", parent)

        # Initialize service and worker with EventBus
        self.service = BarcodeServerService(config, bus)
        self.service_worker = ServiceWorker(self.service)

        # Connect worker signals
        self.service_worker.service_started.connect(self._on_service_started)
        self.service_worker.service_stopped.connect(self._on_service_stopped)
        self.service_worker.error_occurred.connect(self._on_error)

        # State tracking
        self.is_service_running = False

        self.setup_ui()
        self.update_status_display()

        # Auto-start service after GUI initialization
        QTimer.singleShot(500, self.start_service)  # 500ms delay to ensure full initialization

    def setup_ui(self):
        """Create and arrange the UI elements."""
        layout = QVBoxLayout()

        # Service control buttons
        control_layout = QHBoxLayout()

        self.start_button = QPushButton("Start Service")
        self.start_button.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; }"
        )
        self.start_button.clicked.connect(self.start_service)

        self.stop_button = QPushButton("Stop Service")
        self.stop_button.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; padding: 8px; font-weight: bold; }"
        )
        self.stop_button.clicked.connect(self.stop_service)
        self.stop_button.setEnabled(False)

        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addStretch()

        # Status display
        status_layout = QGridLayout()

        # Service status indicator
        self.status_label = QLabel("OFFLINE")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(
            "QLabel { background-color: #f44336; color: white; padding: 8px; font-weight: bold; border-radius: 4px; }"
        )

        # Configuration display
        self.config_label = QLabel("Host: N/A | Port: N/A")
        self.config_label.setStyleSheet("QLabel { background-color: #f0f0f0; padding: 4px; }")

        # Statistics display
        self.stats_label = QLabel("Messages: 0 | Topics: 0 | Runtime: 00:00:00")
        self.stats_label.setStyleSheet("QLabel { background-color: #e8f5e8; padding: 4px; }")

        # Health status display
        self.health_label = QLabel("Health: Initializing...")
        self.health_label.setStyleSheet("QLabel { background-color: #f0f0f0; padding: 4px; }")

        status_layout.addWidget(QLabel("Status:"), 0, 0)
        status_layout.addWidget(self.status_label, 0, 1)
        status_layout.addWidget(QLabel("Configuration:"), 1, 0)
        status_layout.addWidget(self.config_label, 1, 1)
        status_layout.addWidget(QLabel("Statistics:"), 2, 0)
        status_layout.addWidget(self.stats_label, 2, 1)
        status_layout.addWidget(QLabel("Health:"), 3, 0)
        status_layout.addWidget(self.health_label, 3, 1)

        # Add layouts to main layout
        layout.addLayout(control_layout)
        layout.addLayout(status_layout)

        self.setLayout(layout)

        # Setup update timer for statistics
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status_display)
        self.update_timer.start(2000)  # Update every 2 seconds

    def start_service(self):
        """Start the barcode scanner service."""
        try:
            # Prevent duplicate starts
            if self.is_service_running:
                logger.info("Barcode Scanner Service already running")
                return

            self.start_button.setEnabled(False)
            self.status_label.setText("STARTING...")
            self.status_label.setStyleSheet(
                "QLabel { background-color: #ff9800; color: white; padding: 8px; font-weight: bold; border-radius: 4px; }"
            )

            # Start service in worker thread
            self.service_worker.start_service()

        except Exception as e:
            self._on_error(f"Failed to start service: {e}")

    def stop_service(self):
        """Stop the barcode scanner service."""
        try:
            self.stop_button.setEnabled(False)
            self.status_label.setText("STOPPING...")
            self.status_label.setStyleSheet(
                "QLabel { background-color: #ff9800; color: white; padding: 8px; font-weight: bold; border-radius: 4px; }"
            )

            # Stop service
            self.service_worker.stop_service()

        except Exception as e:
            self._on_error(f"Failed to stop service: {e}")

    def _on_service_started(self):
        """Handle service started signal."""
        self.is_service_running = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        self.status_label.setText("RUNNING")
        self.status_label.setStyleSheet(
            "QLabel { background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; border-radius: 4px; }"
        )

        self.service_started.emit()
        logger.info("Barcode Scanner Service started (auto-start enabled)")

    def _on_service_stopped(self):
        """Handle service stopped signal."""
        self.is_service_running = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        self.status_label.setText("OFFLINE")
        self.status_label.setStyleSheet(
            "QLabel { background-color: #f44336; color: white; padding: 8px; font-weight: bold; border-radius: 4px; }"
        )

        self.service_stopped.emit()
        logger.info("Barcode Scanner Service stopped from GUI")

    def _on_error(self, error_message: str):
        """Handle error signals."""
        logger.error(f"Barcode Scanner Service Error: {error_message}")

        # Reset buttons
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        # Update status to show error
        self.status_label.setText("ERROR")
        self.status_label.setStyleSheet(
            "QLabel { background-color: #f44336; color: white; padding: 8px; font-weight: bold; border-radius: 4px; }"
        )

    def update_status_display(self):
        """Update the status display with current service information."""
        try:
            status = self.service.get_service_status()

            # Update configuration display
            self.config_label.setText(f"Host: {status['host']} | Port: {status['port']}")

            # Update statistics display with filtered message info
            if "total_messages" in status:
                runtime = status.get("runtime", datetime.now() - datetime.now())
                runtime_str = str(runtime).split(".")[0]  # Remove microseconds

                total_msgs = status.get("total_messages", 0)
                logged_msgs = status.get("logged_messages", 0)
                filtered_msgs = status.get("filtered_messages", 0)

                stats_text = f"Total: {total_msgs} | Logged: {logged_msgs} | Filtered: {filtered_msgs} | Runtime: {runtime_str}"
                self.stats_label.setText(stats_text)

            # Update health display (simplified - always healthy)
            if "health_status" in status:
                self.health_label.setText("HEALTHY")
                self.health_label.setStyleSheet(
                    "QLabel { background-color: #4CAF50; color: white; padding: 4px; font-weight: bold; }"
                )

        except Exception as e:
            logger.error(f"Error updating status display: {e}")


class BarcodeServiceMonitorWidget(QWidget):
    """
    Monitor widget for displaying MQTT message activity from the Barcode Scanner Service.

    Shows real-time message log and topic statistics.
    """

    def __init__(self, service: BarcodeServerService, parent=None):
        super().__init__(parent)

        self.service = service
        self.message_history = []
        self.max_history = 1000  # Limit message history to prevent memory issues

        # Connect to service signals
        self.service.message_received.connect(self._on_message_received)

        self.setup_ui()

    def setup_ui(self):
        """Create and arrange the UI elements."""
        layout = QVBoxLayout()

        # Title
        title_label = QLabel("MQTT Message Monitor")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        title_label.setFont(title_font)

        # Message log area
        log_group = QGroupBox("Recent Messages")
        log_layout = QVBoxLayout()

        self.message_log = QTextEdit()
        self.message_log.setMaximumHeight(200)
        self.message_log.setReadOnly(True)
        self.message_log.setStyleSheet("QTextEdit { font-family: monospace; font-size: 9pt; }")

        # Controls
        controls_layout = QHBoxLayout()

        self.clear_log_button = QPushButton("Clear Log")
        self.clear_log_button.clicked.connect(self.clear_message_log)

        self.save_log_button = QPushButton("Save Log")
        self.save_log_button.clicked.connect(self.save_message_log)

        controls_layout.addWidget(self.clear_log_button)
        controls_layout.addWidget(self.save_log_button)
        controls_layout.addStretch()

        log_layout.addWidget(self.message_log)
        log_layout.addLayout(controls_layout)
        log_group.setLayout(log_layout)

        # Topic statistics table
        stats_group = QGroupBox("Topic Statistics")
        stats_layout = QVBoxLayout()

        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(3)
        self.stats_table.setHorizontalHeaderLabels(["Topic", "Message Count", "Last Message"])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.stats_table.setMaximumHeight(200)

        stats_layout.addWidget(self.stats_table)
        stats_group.setLayout(stats_layout)

        # Add everything to main layout
        layout.addWidget(title_label)
        layout.addWidget(log_group)
        layout.addWidget(stats_group)

        self.setLayout(layout)

        # Setup update timer for statistics table
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_statistics_table)
        self.stats_timer.start(5000)  # Update every 5 seconds

    def _on_message_received(self, topic: str, message: str):
        """Handle new MQTT message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {topic}: {message}"

        # Add to message log
        self.message_log.append(log_entry)

        # Maintain message history
        self.message_history.append((timestamp, topic, message))
        if len(self.message_history) > self.max_history:
            self.message_history.pop(0)

        # Auto-scroll to bottom
        scrollbar = self.message_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_message_log(self):
        """Clear the message log display."""
        self.message_log.clear()
        self.message_history.clear()

    def save_message_log(self):
        """Save the current message log to a file."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"barcode_service_log_{timestamp}.txt"

            with open(filename, "w") as f:
                f.write("Tiger Motors Digital Twin - Barcode Scanner Service Log\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")

                for timestamp, topic, message in self.message_history:
                    f.write(f"[{timestamp}] {topic}: {message}\n")

            logger.info(f"Message log saved to {filename}")

        except Exception as e:
            logger.error(f"Error saving message log: {e}")

    def update_statistics_table(self):
        """Update the topic statistics table with split logging data."""
        try:
            status = self.service.get_service_status()
            message_counts = status.get("message_counts", {})

            # Sort topics to show scanner topics first, then others
            scanner_topics = {k: v for k, v in message_counts.items() if k.startswith("scanner/")}
            other_topics = {k: v for k, v in message_counts.items() if not k.startswith("scanner/")}

            # Combine with scanner topics first
            sorted_topics = {**scanner_topics, **other_topics}

            # Update table
            self.stats_table.setRowCount(len(sorted_topics))

            for row, (topic, count) in enumerate(sorted_topics.items()):
                # Topic column with color coding
                topic_item = QTableWidgetItem(topic)
                if topic.startswith("scanner/"):
                    topic_item.setBackground(
                        QColor(200, 255, 200)
                    )  # Light green for scanner topics
                else:
                    topic_item.setBackground(QColor(200, 200, 255))  # Light blue for other topics
                self.stats_table.setItem(row, 0, topic_item)

                # Count column
                count_item = QTableWidgetItem(str(count))
                count_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.stats_table.setItem(row, 1, count_item)

                # Last message column (get from history)
                last_message = self._get_last_message_for_topic(topic)
                last_item = QTableWidgetItem(last_message)
                self.stats_table.setItem(row, 2, last_item)

        except Exception as e:
            logger.error(f"Error updating statistics table: {e}")

    def _get_last_message_for_topic(self, topic: str) -> str:
        """Get the most recent message for a specific topic."""
        for timestamp, msg_topic, message in reversed(self.message_history):
            if msg_topic == topic:
                return (
                    f"[{timestamp}] {message[:30]}..."
                    if len(message) > 30
                    else f"[{timestamp}] {message}"
                )
        return "No messages"


class BarcodeServiceWidget(QWidget):
    """
    Complete Barcode Scanner Service widget combining control and monitoring.

    This widget provides a comprehensive interface for the service, similar to how
    the existing GUI is structured with different functional areas.
    """

    def __init__(self, config: dict | None = None, bus=None, parent=None):
        super().__init__(parent)

        # Initialize service and control widget (EventBus may be None initially)
        self.control_widget = BarcodeServiceControlWidget(config, bus, self)
        self.monitor_widget = BarcodeServiceMonitorWidget(self.control_widget.service, self)

        self.setup_ui()

    def setup_ui(self):
        """Create and arrange the UI elements."""
        layout = QVBoxLayout()

        # Add control widget at the top
        layout.addWidget(self.control_widget)

        # Add monitor widget
        layout.addWidget(self.monitor_widget)

        self.setLayout(layout)

    def get_service(self) -> BarcodeServerService:
        """Get the underlying service instance."""
        return self.control_widget.service

    def set_event_bus(self, bus):
        """
        Set EventBus reference for late binding integration.

        This method is called by the main window after the simulation environment
        is initialized and the EventBus is available. The service works independently
        but can publish status updates to EventBus when available.

        Args:
            bus: EventBus instance from the simulation environment
        """
        if self.control_widget and self.control_widget.service:
            self.control_widget.service.set_event_bus(bus)
            logger.info("Barcode Service Widget connected to EventBus")
