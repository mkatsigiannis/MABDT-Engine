"""Active-car table: one row per car in production or inspection."""

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from tiger_motors_dt.simulation.dto import CarStatus


class CarTrackingWidget(QTableWidget):
    """Active cars table (VIN, Type, Location, Status)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["VIN", "Type", "Location", "Status"])

        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        self.setMinimumHeight(200)

    def update_cars(self, car_statuses: Iterable[CarStatus]):
        """Refresh rows from a sequence of CarStatus DTOs."""
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

            workstation = car.current_workstation
            state = car.state
            if workstation is not None:
                if workstation == 16:
                    location = "Inspection"
                elif 1 <= workstation <= 15:
                    cell = ((workstation - 1) // 5) + 1
                    if "WaitInQueue" in state:
                        location = f"C{cell}WS{workstation} (Queue)"
                    else:
                        location = f"C{cell}WS{workstation}"
                else:
                    location = f"WS{workstation}"
            else:
                if "WaitingInspection" in state:
                    location = "Inspection Queue"
                elif state == "Finished":
                    location = "Completed"
                else:
                    location = "Unknown"
            self.setItem(row, 2, QTableWidgetItem(location))

            if state and state != "Unknown":
                if "_" in state:
                    display_status = state.split("_")[-1]
                else:
                    display_status = state
                display_status = display_status.replace("AtStation", " at Station").replace(
                    "InQueue", " in Queue"
                )
            else:
                display_status = "Unknown"
            self.setItem(row, 3, QTableWidgetItem(display_status))
