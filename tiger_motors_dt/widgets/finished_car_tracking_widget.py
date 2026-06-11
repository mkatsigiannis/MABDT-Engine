"""Finished-car table with inspection result and per-stage fault breakdown."""

import time
from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from tiger_motors_dt.simulation.dto import CarStatus


class FinishedCarTrackingWidget(QTableWidget):
    """Finished cars table (VIN, Type, Inspection, Production Faults, Inspection Faults, Lead Time)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.setColumnCount(6)
        self.setHorizontalHeaderLabels(
            ["VIN", "Type", "Inspection", "Production Faults", "Inspection Faults", "Lead Time"]
        )

        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)

        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        self.setMinimumHeight(200)

    def update_cars(self, car_statuses: Iterable[CarStatus]):
        """Refresh rows from a sequence of finished CarStatus DTOs."""
        car_statuses = list(car_statuses)
        self.setRowCount(0)

        if not car_statuses:
            return

        for row, car in enumerate(car_statuses):
            self.insertRow(row)

            vin = car.vin
            self.setItem(row, 0, QTableWidgetItem(str(vin)))

            if vin.startswith("SUV"):
                car_type = "SUV"
            elif vin.startswith("SPEEDSTER") or vin.startswith("SPEED"):
                car_type = "SPEEDSTER"
            else:
                car_type = "Unknown"
            self.setItem(row, 1, QTableWidgetItem(car_type))

            if car.inspection_faults:
                inspection_item = QTableWidgetItem("FAIL")
                inspection_item.setBackground(QColor(255, 200, 200))
            else:
                inspection_item = QTableWidgetItem("PASS")
                inspection_item.setBackground(QColor(200, 255, 200))
            inspection_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(row, 2, inspection_item)

            if car.production_faults:
                production_faults_text = ", ".join([f"F{fault}" for fault in car.production_faults])
                production_faults_item = QTableWidgetItem(production_faults_text)
                production_faults_item.setBackground(QColor(255, 240, 200))
            else:
                production_faults_item = QTableWidgetItem("None")
            self.setItem(row, 3, production_faults_item)

            if car.inspection_faults:
                inspection_faults_text = ", ".join([f"F{fault}" for fault in car.inspection_faults])
                inspection_faults_item = QTableWidgetItem(inspection_faults_text)
                inspection_faults_item.setBackground(QColor(255, 200, 200))
            else:
                inspection_faults_item = QTableWidgetItem("None")
            self.setItem(row, 4, inspection_faults_item)

            if car.lead_time is not None:
                lead_time_text = f"{car.lead_time:.1f}s"
            elif car.starting_time:
                # Defensive fallback; finished cars should carry lead_time.
                lead_time_text = f"{time.time() - car.starting_time:.1f}s"
            else:
                lead_time_text = "--"
            lead_time_item = QTableWidgetItem(lead_time_text)
            lead_time_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(row, 5, lead_time_item)
