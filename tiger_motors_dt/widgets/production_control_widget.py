"""Start/stop buttons + elapsed-time display for production runs."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class ProductionControlWidget(QGroupBox):
    """Production start/stop controls and elapsed-time readout.

    Signals:
        production_started: start button was clicked
        production_stopped: stop button was clicked
    """

    production_started = Signal()
    production_stopped = Signal()

    def __init__(self, parent=None):
        super().__init__("Production Control", parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        buttons_layout = QHBoxLayout()

        self.start_button = QPushButton("Start Production")
        self.start_button.setStyleSheet(
            "QPushButton { background-color: lightgreen; font-weight: bold; }"
        )
        self.start_button.clicked.connect(self.start_production)

        self.stop_button = QPushButton("Stop Production")
        self.stop_button.setStyleSheet(
            "QPushButton { background-color: lightcoral; font-weight: bold; }"
        )
        self.stop_button.clicked.connect(self.stop_production)

        buttons_layout.addWidget(self.start_button)
        buttons_layout.addWidget(self.stop_button)

        self.status_label = QLabel("Status: STOPPED")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont("Arial", 12, QFont.Bold))

        self.timer_label = QLabel("Elapsed Time: 00:00:00")
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setFont(QFont("Arial", 10))

        layout.addLayout(buttons_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.timer_label)

        self.setLayout(layout)

    def start_production(self):
        self.status_label.setText("Status: RUNNING")
        self.status_label.setStyleSheet("QLabel { color: green; }")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        self.production_started.emit()

    def stop_production(self):
        self.status_label.setText("Status: STOPPED")
        self.status_label.setStyleSheet("QLabel { color: red; }")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        self.production_stopped.emit()

    def update_timer(self, elapsed_seconds: float):
        hours = int(elapsed_seconds // 3600)
        minutes = int((elapsed_seconds % 3600) // 60)
        seconds = int(elapsed_seconds % 60)
        self.timer_label.setText(f"Elapsed Time: {hours:02d}:{minutes:02d}:{seconds:02d}")
