"""Workstation status card: ID, state label, state-time pie chart, LED test button."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from mabdt.utils.logging import get_logger
from tiger_motors_dt.simulation.dto import WorkstationStatus
from tiger_motors_dt.widgets.state_pie_chart import StatePieChart

logger = get_logger(__name__)


class WorkstationCard(QFrame):
    """One card per workstation: shows state, andon color, per-state time, LED test."""

    def __init__(self, ws_id: str, parent=None):
        super().__init__(parent)
        self.ws_id = ws_id
        self.ws_agent = None
        self.setup_ui()

    def setup_ui(self):
        self.setFrameStyle(QFrame.Box)
        self.setFixedSize(180, 200)

        layout = QVBoxLayout()

        self.id_label = QLabel(self.ws_id)
        self.id_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        self.id_label.setFont(font)

        self.state_label = QLabel("OFFLINE")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet(
            "QLabel { background-color: gray; color: white; padding: 3px; }"
        )

        chart_layout = QHBoxLayout()

        self.pie_chart = StatePieChart(self, width=1.5, height=1.5, dpi=80)
        self.pie_chart.setFixedSize(100, 100)

        self.time_tracking_label = QLabel("Time Tracking:\nOffline")
        self.time_tracking_label.setAlignment(Qt.AlignCenter)
        self.time_tracking_label.setStyleSheet(
            "QLabel { font-size: 9px; background-color: #f0f0f0; padding: 3px; }"
        )
        self.time_tracking_label.setWordWrap(True)
        self.time_tracking_label.setFixedWidth(65)

        chart_layout.addWidget(self.pie_chart)
        chart_layout.addWidget(self.time_tracking_label)

        self.led_button = QPushButton("Test LED")
        self.led_button.setMaximumHeight(25)
        self.led_button.clicked.connect(self.test_led)

        layout.addWidget(self.id_label)
        layout.addWidget(self.state_label)
        layout.addLayout(chart_layout)
        layout.addWidget(self.led_button)
        layout.setContentsMargins(5, 5, 5, 5)

        self.setLayout(layout)

    def update_status(self, status: WorkstationStatus | None):
        """Update the visual appearance from a WorkstationStatus DTO."""
        if status is None:
            self.state_label.setText("OFFLINE")
            self.state_label.setStyleSheet(
                "QLabel { background-color: gray; color: white; padding: 3px; font-size: 8px; }"
            )
            self.pie_chart.update_chart(0, 0, 0, 0)
            self.time_tracking_label.setText("Offline")
            return

        display_state = self._format_state(status.state, status.andon_color)

        if status.is_paused:
            self.state_label.setText(f"PAUSED\n{display_state}")
            self.state_label.setStyleSheet(
                "QLabel { background-color: orange; color: black; padding: 3px; font-size: 8px; }"
            )
        else:
            self.state_label.setText(display_state)
            style = self._style_for(status.state, status.andon_color)
            self.state_label.setStyleSheet(f"QLabel {{ {style} padding: 3px; font-size: 8px; }}")

        self.pie_chart.update_chart(
            status.idle_time, status.busy_time, status.yellow_time, status.red_time
        )
        self.time_tracking_label.setText(
            f"Idle: {status.idle_time:.1f}s\n"
            f"Busy: {status.busy_time:.1f}s\n"
            f"Yellow: {status.yellow_time:.1f}s\n"
            f"Red: {status.red_time:.1f}s"
        )

    @staticmethod
    def _format_state(state: str, andon_color: str) -> str:
        if not state or state == "unknown":
            return "UNKNOWN"
        if state in ("starting", "initializing"):
            return state.upper()
        return f"{andon_color.upper()}\n{state.upper()}"

    @staticmethod
    def _style_for(state: str, andon_color: str) -> str:
        if andon_color == "green":
            if state == "busy":
                return "background-color: green; color: white;"
            return "background-color: lightgreen; color: black;"
        if andon_color == "yellow":
            return "background-color: yellow; color: black;"
        if andon_color == "red":
            return "background-color: red; color: white;"
        if andon_color == "paused":
            return "background-color: lightblue; color: black;"
        return "background-color: lightgray; color: black;"

    def test_led(self):
        """Publish a manual LED ON command for this workstation via the main window's env."""
        main_window = self.window()
        if hasattr(main_window, "environment") and main_window.environment:
            led_topic = f"leds/{self.ws_id}"
            try:
                main_window.environment.test_led(led_topic, "ON")
                logger.info(f"LED test sent for {self.ws_id}")
            except Exception as e:
                logger.error(f"Error testing LED for {self.ws_id}: {e}")
