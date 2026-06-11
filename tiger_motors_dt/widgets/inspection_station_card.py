"""Inspection station status card: label, state, LED test button."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from mabdt.utils.logging import get_logger
from tiger_motors_dt.simulation.dto import InspectionStationStatus

logger = get_logger(__name__)


class InspectionStationCard(QFrame):
    """Status card for the inspection station."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.inspection_agent = None
        self.setup_ui()

    def setup_ui(self):
        self.setFrameStyle(QFrame.Box)
        self.setFixedSize(180, 110)

        layout = QVBoxLayout()

        self.id_label = QLabel("INSPECTION\nSTATION")
        self.id_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        self.id_label.setFont(font)

        self.state_label = QLabel("OFFLINE")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet(
            "QLabel { background-color: gray; color: white; padding: 3px; }"
        )

        self.led_button = QPushButton("Test LED")
        self.led_button.setMaximumHeight(25)
        self.led_button.clicked.connect(self.test_led)

        layout.addWidget(self.id_label)
        layout.addWidget(self.state_label)
        layout.addWidget(self.led_button)
        layout.setContentsMargins(5, 5, 5, 5)

        self.setLayout(layout)

    def update_status(self, status: InspectionStationStatus | None):
        """Update the visual appearance from an InspectionStationStatus DTO."""
        if status is None:
            self.state_label.setText("OFFLINE")
            self.state_label.setStyleSheet(
                "QLabel { background-color: gray; color: white; padding: 3px; font-size: 8px; }"
            )
            return

        display_state = self.format_state_name(status.state)

        if status.is_paused:
            self.state_label.setText(f"PAUSED\n{display_state}")
            self.state_label.setStyleSheet(
                "QLabel { background-color: orange; color: black; padding: 3px; font-size: 8px; }"
            )
        else:
            self.state_label.setText(display_state)
            style = self.get_state_style(status.state)
            self.state_label.setStyleSheet(f"QLabel {{ {style} padding: 3px; font-size: 8px; }}")

    def format_state_name(self, state_name):
        """Map a state machine state name to its operator-facing label."""
        if not state_name or state_name == "Unknown":
            return "UNKNOWN"

        state_display = str(state_name).replace("Inspection", "").replace("_", " ").strip().upper()

        if "INITIALIZE" in state_display:
            return "INIT"
        elif "IDLE" in state_display:
            return "IDLE"
        elif "BUSY" in state_display:
            return "BUSY"
        elif "FINISHED" in state_display:
            return "FINISHED"

        return state_display[:12]

    def get_state_style(self, state_name):
        """Return inline CSS for the state label background."""
        state_str = str(state_name).lower()

        if "waiting_for_car" in state_str or "waiting" in state_str:
            return "background-color: lightgreen; color: black;"
        elif "inspecting_car" in state_str or "inspecting" in state_str:
            return "background-color: orange; color: white;"
        elif "passed_inspection" in state_str or "passed" in state_str:
            return "background-color: green; color: white;"
        elif "add_fault" in state_str or "fault" in state_str:
            return "background-color: red; color: white;"
        else:
            return "background-color: lightgray; color: black;"

    def test_led(self):
        """Publish a manual LED ON command for the inspection station."""
        main_window = self.window()
        if hasattr(main_window, "environment") and main_window.environment:
            try:
                led_topic = "leds/InspectionStation"
                main_window.environment.test_led(led_topic, "ON")
                logger.info("LED test sent for Inspection Station")
            except Exception as e:
                logger.error(f"Error testing LED for Inspection Station: {e}")
