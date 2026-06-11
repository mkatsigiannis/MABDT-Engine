"""LLM chat widget — talks to the LLM service over MQTT with optional RAG context."""

import json
import time
import uuid

import paho.mqtt.client as mqtt
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,  # Added for RAG controls
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Import RAG system for context enhancement
from mabdt.utils.logging import get_logger
from tiger_motors_dt.config import load_config
from tiger_motors_dt.rag_system import DigitalTwinRAGSystem

logger = get_logger(__name__)


class LLMChatWorker(QObject):
    """
    Worker class to handle MQTT communication in a separate thread.
    This prevents the GUI from freezing during network operations.
    """

    # Signals for thread-safe communication with GUI
    connected = Signal(bool)  # Connection status
    message_received = Signal(str, str)  # user_id, answer
    connection_error = Signal(str)  # error message

    def __init__(self, broker_host: str, broker_port: int, question_topic: str, answer_topic: str):
        super().__init__()
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.question_topic = question_topic
        self.answer_topic = answer_topic

        self.client: mqtt.Client | None = None
        self.user_id = f"gui_user_{uuid.uuid4().hex[:8]}"
        self.is_connected = False

    def connect_mqtt(self):
        """Initialize and connect to MQTT broker."""
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                client_id="tiger_motors_gui_llm_chat",
            )
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect

            logger.info(
                f"[LLM Chat] Connecting to MQTT broker {self.broker_host}:{self.broker_port}"
            )
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()

        except Exception as e:
            error_msg = f"Failed to connect to MQTT broker: {str(e)}"
            logger.error(f"[LLM Chat] {error_msg}")
            self.connection_error.emit(error_msg)

    def disconnect_mqtt(self):
        """Disconnect from MQTT broker."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.is_connected = False

    def send_question(self, question: str, rag_context: str = ""):
        """Send a question to the LLM service via MQTT."""
        if not self.is_connected or not self.client:
            self.connection_error.emit("Not connected to MQTT broker")
            return

        try:
            message = {"user_id": self.user_id, "question": question, "rag_context": rag_context}

            self.client.publish(self.question_topic, json.dumps(message), qos=1)
            logger.info(f"[LLM Chat] Question sent: {question[:50]}...")

        except Exception as e:
            error_msg = f"Failed to send question: {str(e)}"
            logger.error(f"[LLM Chat] {error_msg}")
            self.connection_error.emit(error_msg)

    def _on_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection callback (VERSION1 API)."""
        if rc == 0:
            logger.info("[LLM Chat] Connected to MQTT broker")
            client.subscribe(self.answer_topic, qos=1)
            logger.info(f"[LLM Chat] Subscribed to {self.answer_topic}")
            self.is_connected = True
            self.connected.emit(True)
        else:
            error_msg = f"Failed to connect to MQTT broker (code: {rc})"
            logger.error(f"[LLM Chat] {error_msg}")
            self.connection_error.emit(error_msg)

    def _on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection callback (VERSION1 API)."""
        self.is_connected = False
        self.connected.emit(False)
        logger.info("[LLM Chat] Disconnected from MQTT broker")

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages (LLM responses)."""
        try:
            data = json.loads(msg.payload.decode())

            # Only process messages for this user
            if data.get("user_id") == self.user_id:
                answer = data.get("answer", "")
                logger.info(f"[LLM Chat] Received answer: {answer[:50]}...")
                self.message_received.emit(self.user_id, answer)

        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            logger.error(f"[LLM Chat] {error_msg}")
            self.connection_error.emit(error_msg)


class LLMChatWidget(QWidget):
    """
    GUI widget for chatting with the LLM service via MQTT.

    This widget provides:
    - Chat history display
    - Question input field
    - Send button
    - Connection status indicator
    - Real-time response handling
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Read MQTT broker from config.json with localhost fallback.
        try:
            mqtt_config = load_config().get("mqtt", {})
        except Exception as e:
            logger.error(f"Error loading config.json: {e}")
            mqtt_config = {}

        self.broker_host = mqtt_config.get("host", "localhost")
        self.broker_port = mqtt_config.get("port", 8883)
        self.question_topic = "llm/question"
        self.answer_topic = "llm/answer"

        logger.info(f"[LLM Chat] Using MQTT broker: {self.broker_host}:{self.broker_port}")

        # Worker thread for MQTT communication
        self.worker_thread: QThread | None = None
        self.worker: LLMChatWorker | None = None

        # RAG system for context enhancement
        self.rag_system = DigitalTwinRAGSystem()
        self.environment = None  # Will be set by parent GUI

        # UI state
        self.is_connected = False
        self.waiting_for_response = False
        self.rag_enabled = True  # RAG enabled by default

        self.setup_ui()
        self.setup_mqtt()

    def setup_ui(self):
        """Create and arrange the user interface elements."""
        main_layout = QVBoxLayout()

        # Connection status and info
        status_group = QGroupBox("LLM Service Connection")
        status_layout = QVBoxLayout()

        self.status_label = QLabel("Disconnected")
        self.status_label.setFont(QFont("Arial", 10, QFont.Bold))
        status_layout.addWidget(self.status_label)

        info_label = QLabel(f"MQTT Broker: {self.broker_host}:{self.broker_port}")
        info_label.setStyleSheet("color: gray; font-size: 9pt;")
        status_layout.addWidget(info_label)

        # Connect/Disconnect button
        self.connect_button = QPushButton("Connect to LLM Service")
        self.connect_button.clicked.connect(self.toggle_connection)
        status_layout.addWidget(self.connect_button)

        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)

        # RAG (Context Enhancement) Controls
        rag_group = QGroupBox("Digital Twin Context Enhancement (RAG)")
        rag_layout = QVBoxLayout()

        # RAG enable/disable
        self.rag_checkbox = QCheckBox("Enable context enhancement from Digital Twin data")
        self.rag_checkbox.setChecked(True)
        self.rag_checkbox.toggled.connect(self.on_rag_toggled)
        rag_layout.addWidget(self.rag_checkbox)

        # RAG status and focus area
        rag_controls_layout = QHBoxLayout()

        # RAG status label
        self.rag_status_label = QLabel("Ready - No data available")
        self.rag_status_label.setStyleSheet("color: gray; font-size: 9pt;")
        rag_controls_layout.addWidget(self.rag_status_label)

        rag_controls_layout.addStretch()

        # Focus area selection
        focus_label = QLabel("Focus:")
        self.focus_combo = QComboBox()
        self.focus_combo.addItems(
            ["Auto-detect", "Overview", "Workstations", "Vehicles", "Quality", "Performance"]
        )
        self.focus_combo.setCurrentText("Auto-detect")
        self.focus_combo.setEnabled(True)

        rag_controls_layout.addWidget(focus_label)
        rag_controls_layout.addWidget(self.focus_combo)

        rag_layout.addLayout(rag_controls_layout)
        rag_group.setLayout(rag_layout)
        main_layout.addWidget(rag_group)

        # Chat area
        chat_group = QGroupBox("Digital Twin Assistant")
        chat_layout = QVBoxLayout()

        # Chat history display
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setFont(QFont("Consolas", 10))
        self.chat_display.setMinimumHeight(400)

        # Add welcome message
        welcome_msg = (
            "<b>Welcome to the Tiger Motors Digital Twin Assistant!</b><br><br>"
            "I am the intelligent digital replica of the Tiger Motors assembly line. "
            "I can provide insights about production performance, workstation status, "
            "quality metrics, and lean manufacturing principles.<br><br>"
            "Connect to the LLM service above and ask me anything about the facility!<br>"
            "<hr>"
        )
        self.chat_display.setHtml(welcome_msg)

        chat_layout.addWidget(self.chat_display)

        # Input area
        input_layout = QHBoxLayout()

        self.question_input = QLineEdit()
        self.question_input.setPlaceholderText(
            "Ask me about production status, workstation performance, quality metrics..."
        )
        self.question_input.returnPressed.connect(self.send_question)
        self.question_input.setEnabled(False)  # Disabled until connected

        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_question)
        self.send_button.setEnabled(False)  # Disabled until connected

        input_layout.addWidget(self.question_input)
        input_layout.addWidget(self.send_button)

        chat_layout.addLayout(input_layout)
        chat_group.setLayout(chat_layout)
        main_layout.addWidget(chat_group)

        self.setLayout(main_layout)

    def setup_mqtt(self):
        """Initialize MQTT worker in separate thread."""
        self.worker_thread = QThread()
        self.worker = LLMChatWorker(
            self.broker_host, self.broker_port, self.question_topic, self.answer_topic
        )

        # Move worker to separate thread
        self.worker.moveToThread(self.worker_thread)

        # Connect signals for thread-safe communication
        self.worker.connected.connect(self.on_connection_changed)
        self.worker.message_received.connect(self.on_message_received)
        self.worker.connection_error.connect(self.on_connection_error)

        # Start the worker thread
        self.worker_thread.start()

    def toggle_connection(self):
        """Connect or disconnect from MQTT broker."""
        if not self.is_connected:
            self.connect_button.setText("Connecting...")
            self.connect_button.setEnabled(False)
            self.worker.connect_mqtt()
        else:
            self.worker.disconnect_mqtt()

    def send_question(self):
        """Send the current question to the LLM service with optional RAG enhancement."""
        question = self.question_input.text().strip()
        if not question or not self.is_connected or self.waiting_for_response:
            return

        # Add original question to chat display
        self.add_to_chat("You", question, is_user=True)

        # Prepare question for LLM (with or without RAG enhancement)
        rag_context = ""
        rag_used = False

        if self.rag_enabled:
            try:
                # Get focus area from combo box
                focus_selection = self.focus_combo.currentText().lower()
                focus_area = "overview" if focus_selection == "auto-detect" else focus_selection

                # Use RAG system to get context
                if focus_selection == "auto-detect":
                    # Auto-detect context need and focus area
                    should_include, detected_focus = self.rag_system.should_include_context(
                        question
                    )
                    if should_include and self.rag_system.is_data_available():
                        if detected_focus == "overview":
                            rag_context = self.rag_system.get_current_context()
                        else:
                            rag_context = self.rag_system.get_focused_context(detected_focus)
                        rag_used = bool(rag_context and rag_context.strip())
                        if rag_used:
                            self.add_to_chat(
                                "System",
                                f"Enhanced question with {detected_focus} context",
                                is_user=False,
                            )
                    else:
                        rag_context = ""
                        rag_used = False
                else:
                    # Use specified focus area
                    rag_context = self.rag_system.get_focused_context(focus_area)
                    rag_used = bool(rag_context and rag_context.strip())

                    if rag_used:
                        self.add_to_chat(
                            "System", f"Enhanced question with {focus_area} context", is_user=False
                        )

            except Exception as e:
                logger.error(f"[LLM Chat] RAG enhancement failed: {e}")
                self.add_to_chat("System", f"Context enhancement failed: {e}", is_user=False)

        if not rag_used:
            self.add_to_chat(
                "System", "Sending question without context enhancement", is_user=False
            )

        # Clear input and disable while waiting
        self.question_input.clear()
        self.question_input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.waiting_for_response = True

        # Add "thinking" indicator
        self.add_to_chat("Assistant", "Thinking...", is_user=False, is_thinking=True)

        # Send question with RAG context via MQTT
        self.worker.send_question(question, rag_context)

    def add_to_chat(
        self, sender: str, message: str, is_user: bool = False, is_thinking: bool = False
    ):
        """Add a message to the chat display."""
        # Move cursor to end
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.chat_display.setTextCursor(cursor)

        # Format message
        timestamp = time.strftime("%H:%M:%S")

        if is_thinking:
            html = f'<div style="color: #888; font-style: italic; margin: 5px 0;">[{timestamp}] {message}</div>'
        elif is_user:
            html = f'<div style="margin: 10px 0;"><b style="color: #2196F3;">[{timestamp}] {sender}:</b><br/>{message}</div>'
        else:
            html = f'<div style="margin: 10px 0;"><b style="color: #4CAF50;">[{timestamp}] {sender}:</b><br/>{message}</div>'

        self.chat_display.insertHtml(html)

        # Auto-scroll to bottom
        cursor.movePosition(QTextCursor.End)
        self.chat_display.setTextCursor(cursor)

    def on_connection_changed(self, connected: bool):
        """Handle connection status changes."""
        self.is_connected = connected

        if connected:
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.connect_button.setText("Disconnect")
            self.question_input.setEnabled(True)
            self.send_button.setEnabled(True)
            self.add_to_chat(
                "System", "Connected to LLM service. You can now ask questions!", is_user=False
            )
        else:
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.connect_button.setText("Connect to LLM Service")
            self.question_input.setEnabled(False)
            self.send_button.setEnabled(False)
            self.waiting_for_response = False

        self.connect_button.setEnabled(True)

    def on_message_received(self, user_id: str, answer: str):
        """Handle received LLM responses."""
        # Remove "thinking" indicator by clearing and re-adding all messages would be complex
        # Instead, just add the response
        self.add_to_chat("Digital Twin Assistant", answer, is_user=False)

        # Re-enable input
        self.question_input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.waiting_for_response = False
        self.question_input.setFocus()

    def on_connection_error(self, error_message: str):
        """Handle connection errors."""
        self.add_to_chat("System", f"Error: {error_message}", is_user=False)
        self.on_connection_changed(False)

    def closeEvent(self, event):
        """Clean up when widget is closed."""
        if self.worker:
            self.worker.disconnect_mqtt()
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
        event.accept()

    def set_environment(self, environment):
        """Set the Digital Twin environment for RAG context."""
        self.environment = environment
        self.rag_system.set_environment(environment)
        self.update_rag_status()

    def on_rag_toggled(self, checked: bool):
        """Handle RAG enable/disable toggling."""
        self.rag_enabled = checked
        self.update_rag_status()

    def update_rag_status(self):
        """Update RAG status based on current state."""
        if not self.rag_enabled:
            self.rag_status_label.setText("Disabled")
            self.rag_status_label.setStyleSheet("color: gray; font-size: 9pt;")
            return

        try:
            # Check if data is available
            if self.rag_system.is_data_available():
                status_summary = self.rag_system.get_status_summary()
                self.rag_status_label.setText(f"Active - {status_summary}")
                self.rag_status_label.setStyleSheet(
                    "color: green; font-size: 9pt; font-weight: bold;"
                )
            else:
                self.rag_status_label.setText("Ready - No Digital Twin data available")
                self.rag_status_label.setStyleSheet("color: orange; font-size: 9pt;")

        except Exception as e:
            self.rag_status_label.setText(f"Error - {str(e)}")
            self.rag_status_label.setStyleSheet("color: red; font-size: 9pt;")
