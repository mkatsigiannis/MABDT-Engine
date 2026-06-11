"""Tiger Motors Digital Twin - Display Update Manager

Periodically pulls DTO snapshots from the SimulationInterface and pushes
them into the GUI's widgets. After Phase 4 the manager no longer reads
raw agent attributes — every value crossing this boundary is a frozen
DTO from `tiger_motors_dt.simulation.dto`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMainWindow

from tiger_motors_dt.simulation.dto import (
    CarStatus,
    InspectionStationStatus,
    ProductionMetrics,
    WorkstationStatus,
)

logger = logging.getLogger(__name__)


class DisplayUpdateManager(QObject):
    """Manager class for handling all GUI display updates.

    Holds a timer that periodically asks the main window's
    `SimulationInterface` for DTO snapshots of the engine state, then
    forwards them into the widgets that render the operator-facing view.

    Signals:
        status_updated: Emitted when the status bar should be updated.
        error_occurred: Emitted when an update error occurs.
    """

    status_updated = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, main_window: QMainWindow):
        super().__init__()
        self.main_window = main_window

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_all_displays)
        self.update_interval = 50  # ms (20 FPS)

        # Throttle for error toasts.
        self._last_error_time = 0.0
        self._error_threshold = 5  # seconds between error messages

        # System message scrollback.
        self._system_messages: list[str] = []
        self._max_messages = 100

        logger.info("DisplayUpdateManager initialized")

    # --- Lifecycle ---------------------------------------------------------

    def start_updates(self):
        if not self.update_timer.isActive():
            self.update_timer.start(self.update_interval)
            logger.info(f"Display updates started with {self.update_interval}ms interval")
        else:
            logger.warning("Display updates already running")

    def stop_updates(self):
        if self.update_timer.isActive():
            self.update_timer.stop()
            logger.info("Display updates stopped")
        else:
            logger.warning("Display updates already stopped")

    def set_update_interval(self, interval_ms: int):
        if interval_ms <= 0:
            logger.warning(f"Invalid update interval: {interval_ms}ms, must be > 0")
            return
        old = self.update_interval
        self.update_interval = interval_ms
        if self.update_timer.isActive():
            self.update_timer.stop()
            self.update_timer.start(interval_ms)
        logger.info(f"Display update interval changed: {old}ms -> {interval_ms}ms")

    def is_active(self) -> bool:
        return self.update_timer.isActive()

    def get_update_interval(self) -> int:
        return self.update_interval

    # --- Main refresh ------------------------------------------------------

    def update_all_displays(self):
        """Fetch one snapshot of DTOs from the interface and push to widgets."""
        try:
            iface = getattr(self.main_window, "iface", None)
            if iface is None or not iface.is_initialized():
                return

            # One snapshot per refresh tick. Each call holds the interface
            # lock briefly so the GUI sees a consistent picture.
            ws_statuses = iface.get_all_workstations()
            active_cars = iface.get_active_cars()
            finished_cars = iface.get_finished_cars()
            is_status = iface.get_inspection_station_status()
            metrics = iface.get_production_metrics()

            self.update_workstations(ws_statuses)
            self.update_inspection_station(is_status)
            self.update_car_displays(active_cars, finished_cars)
            self.update_production_timer(metrics)
            self.update_system_messages()
            self.update_agent_inspector()
            self.update_status_bar(ws_statuses, active_cars, finished_cars, is_status, metrics)
        except Exception as e:
            self._handle_update_error(e)

    # --- Widget updates ----------------------------------------------------

    def update_workstations(self, ws_statuses: dict[str, WorkstationStatus]):
        """Push a WorkstationStatus DTO to each WorkstationCard."""
        if not hasattr(self.main_window, "workstation_cards"):
            return
        for ws_id, card in self.main_window.workstation_cards.items():
            card.update_status(ws_statuses.get(ws_id))

    def update_inspection_station(self, status: InspectionStationStatus):
        if hasattr(self.main_window, "inspection_card") and self.main_window.inspection_card:
            self.main_window.inspection_card.update_status(status)

    def update_car_displays(
        self,
        active_cars: Iterable[CarStatus],
        finished_cars: Iterable[CarStatus],
    ):
        """Update the three car tables and the active-car statistic labels."""
        active = list(active_cars)
        finished = list(finished_cars)

        if not active and not finished:
            self._clear_car_tables()
            self._clear_car_statistics()
            return

        production, inspection = self._split_active(active)

        if hasattr(self.main_window, "production_cars_table"):
            self.main_window.production_cars_table.update_cars(production)
        if hasattr(self.main_window, "inspection_cars_table"):
            self.main_window.inspection_cars_table.update_cars(inspection)
        if hasattr(self.main_window, "finished_cars_table"):
            self.main_window.finished_cars_table.update_cars(finished)

        self._update_finished_cars_statistics(finished)
        self._update_car_statistics_labels(
            total_active=len(active),
            production=len(production),
            inspection=len(inspection),
            finished=len(finished),
        )

    def update_production_timer(self, metrics: ProductionMetrics):
        if not hasattr(self.main_window, "production_control"):
            return

        if metrics.is_tracking and metrics.elapsed_time is not None:
            elapsed = metrics.elapsed_time
            self.main_window.production_control.update_timer(elapsed)
            if hasattr(self.main_window, "production_time_label"):
                hours = int(elapsed // 3600)
                minutes = int((elapsed % 3600) // 60)
                seconds = int(elapsed % 60)
                self.main_window.production_time_label.setText(
                    f"Production Time: {hours:02d}:{minutes:02d}:{seconds:02d}"
                )
        else:
            if hasattr(self.main_window, "production_time_label"):
                self.main_window.production_time_label.setText("Production Time: 00:00:00")

    def update_status_bar(
        self,
        ws_statuses: dict[str, WorkstationStatus],
        active_cars: list[CarStatus],
        finished_cars: list[CarStatus],
        is_status: InspectionStationStatus,
        metrics: ProductionMetrics,
    ):
        try:
            car_count = len(active_cars) + len(finished_cars)
            ws_active = sum(1 for ws in ws_statuses.values() if not ws.is_paused)
            ws_total = len(ws_statuses)
            inspection_status = "PAUSED" if is_status.is_paused else "ACTIVE"
            production_text = "RUNNING" if metrics.is_tracking else "STOPPED"

            self.status_updated.emit(
                f"Cars: {car_count} | Workstations: {ws_active}/{ws_total} active | "
                f"Inspection: {inspection_status} | Production: {production_text}"
            )
        except Exception as e:
            logger.error(f"Error updating status bar: {e}")

    # --- System message scrollback ----------------------------------------

    def add_system_message(self, message: str, timestamp: str | None = None):
        if timestamp is None:
            timestamp = datetime.now().strftime("%H:%M:%S")
        self._system_messages.append(f"[{timestamp}] {message}")
        if len(self._system_messages) > self._max_messages:
            self._system_messages.pop(0)

    def update_system_messages(self):
        if not hasattr(self.main_window, "messages_text") or not self.main_window.messages_text:
            return
        try:
            self.main_window.messages_text.setText("\n".join(self._system_messages))
            cursor = self.main_window.messages_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.main_window.messages_text.setTextCursor(cursor)
        except Exception as e:
            logger.error(f"Error updating system messages display: {e}")

    def clear_system_messages(self):
        self._system_messages.clear()
        self.update_system_messages()

    # --- Agent inspector (debug escape hatch) ------------------------------

    def update_agent_inspector(self):
        """Refresh the optional agent-inspector debug widget.

        The inspector is the one widget allowed to introspect raw agent
        state; it goes through the interface's `debug_*` methods so the
        reach-through is named and grep-able, never through env attributes
        directly.
        """
        if not hasattr(self.main_window, "agent_inspector_widget"):
            return
        widget = self.main_window.agent_inspector_widget
        iface = getattr(self.main_window, "iface", None)
        if iface is None or not iface.is_initialized():
            return
        try:
            if widget.iface is None:
                widget.set_interface(iface)
            if widget.current_agent is not None:
                widget.refresh()
        except Exception as e:
            logger.debug(f"Error updating agent inspector: {e}")

    # --- Internal helpers --------------------------------------------------

    @staticmethod
    def _split_active(
        active_cars: list[CarStatus],
    ) -> tuple[list[CarStatus], list[CarStatus]]:
        """Partition active cars into (production, inspection) lists.

        A car is at inspection when current_workstation == 16 or its state
        contains 'WaitingInspection'. Everything else is in production.
        """
        production: list[CarStatus] = []
        inspection: list[CarStatus] = []
        for car in active_cars:
            ws = car.current_workstation
            state = car.state
            if ws == 16 or "WaitingInspection" in state:
                inspection.append(car)
            else:
                production.append(car)
        return production, inspection

    def _update_finished_cars_statistics(self, finished_cars: list[CarStatus]):
        if not hasattr(self.main_window, "finished_total_label"):
            return

        if not finished_cars:
            self.main_window.finished_total_label.setText("Total Finished: 0")
            if hasattr(self.main_window, "finished_passed_label"):
                self.main_window.finished_passed_label.setText("Passed: 0")
            if hasattr(self.main_window, "finished_failed_label"):
                self.main_window.finished_failed_label.setText("Failed: 0")
            if hasattr(self.main_window, "finished_avg_lead_time_label"):
                self.main_window.finished_avg_lead_time_label.setText("Avg Lead Time: --")
            return

        passed = sum(1 for c in finished_cars if not c.inspection_faults)
        failed = sum(1 for c in finished_cars if c.inspection_faults)
        lead_times = [c.lead_time for c in finished_cars if c.lead_time is not None]
        # Fallback: derive from starting_time if lead_time wasn't recorded.
        if not lead_times:
            lead_times = [time.time() - c.starting_time for c in finished_cars if c.starting_time]
        avg_lead_time_text = (
            f"Avg Lead Time: {sum(lead_times) / len(lead_times):.1f}s"
            if lead_times
            else "Avg Lead Time: --"
        )

        self.main_window.finished_total_label.setText(f"Total Finished: {len(finished_cars)}")
        if hasattr(self.main_window, "finished_passed_label"):
            self.main_window.finished_passed_label.setText(f"Passed: {passed}")
        if hasattr(self.main_window, "finished_failed_label"):
            self.main_window.finished_failed_label.setText(f"Failed: {failed}")
        if hasattr(self.main_window, "finished_avg_lead_time_label"):
            self.main_window.finished_avg_lead_time_label.setText(avg_lead_time_text)

    def _update_car_statistics_labels(
        self,
        total_active: int,
        production: int,
        inspection: int,
        finished: int,
    ):
        if hasattr(self.main_window, "total_cars_label"):
            self.main_window.total_cars_label.setText(f"Total Active Cars: {total_active}")
        if hasattr(self.main_window, "cars_in_production_label"):
            self.main_window.cars_in_production_label.setText(f"In Production: {production}")
        if hasattr(self.main_window, "cars_in_inspection_label"):
            self.main_window.cars_in_inspection_label.setText(f"Awaiting Inspection: {inspection}")
        if hasattr(self.main_window, "finished_cars_label"):
            self.main_window.finished_cars_label.setText(f"Finished: {finished}")

    def _clear_car_tables(self):
        if hasattr(self.main_window, "production_cars_table"):
            self.main_window.production_cars_table.update_cars([])
        if hasattr(self.main_window, "inspection_cars_table"):
            self.main_window.inspection_cars_table.update_cars([])
        if hasattr(self.main_window, "finished_cars_table"):
            self.main_window.finished_cars_table.update_cars([])

    def _clear_car_statistics(self):
        if hasattr(self.main_window, "total_cars_label"):
            self.main_window.total_cars_label.setText("Total Active Cars: 0")
        if hasattr(self.main_window, "cars_in_production_label"):
            self.main_window.cars_in_production_label.setText("In Production: 0")
        if hasattr(self.main_window, "cars_in_inspection_label"):
            self.main_window.cars_in_inspection_label.setText("Awaiting Inspection: 0")
        if hasattr(self.main_window, "finished_cars_label"):
            self.main_window.finished_cars_label.setText("Finished: 0")

    def _handle_update_error(self, error: Exception):
        current_time = time.time()
        if (current_time - self._last_error_time) > self._error_threshold:
            error_msg = f"Error updating display: {error}"
            logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            self._last_error_time = current_time
