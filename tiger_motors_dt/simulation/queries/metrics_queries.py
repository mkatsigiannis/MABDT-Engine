"""Query helpers for production metrics and system status DTOs."""

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from mabdt.exceptions import SimulationError
from mabdt.utils.logging import get_logger
from tiger_motors_dt.simulation.converters import DTOConverters
from tiger_motors_dt.simulation.dto import InspectionStationStatus, ProductionMetrics, SystemStatus

if TYPE_CHECKING:
    from tiger_motors_dt.simulation.environment import TigerMotorsEnvironment

logger = get_logger(__name__)


class MetricsQueries:
    """
    Handles production metrics and system status retrieval.

    This class encapsulates all logic for calculating and aggregating
    production metrics and system status information.

    Attributes:
        _env: Reference to the simulation environment.
        _converters: DTO converter instance for transforming agents to DTOs.
        _init_time: Timestamp when the interface was initialized (for uptime).
        _get_error_count: Callable to get current error count from interface.
    """

    def __init__(
        self,
        environment: "TigerMotorsEnvironment",
        converters: DTOConverters,
        init_time: float,
        error_count_getter: Callable[[], int],
    ):
        """
        Initialize metrics queries with dependencies.

        Args:
            environment: The simulation environment containing all agents.
            converters: DTO converter instance for transforming agents.
            init_time: Timestamp when the simulation interface was initialized.
            error_count_getter: Callable that returns the current error count.
        """
        self._env = environment
        self._converters = converters
        self._init_time = init_time
        self._get_error_count = error_count_getter

    def get_production_metrics(self) -> ProductionMetrics:
        """
        Get comprehensive production metrics.

        Returns:
            ProductionMetrics: Current production metrics including throughput and timing.
        """
        # Get basic metrics from environment
        env_metrics = self._env.get_production_metrics()

        # Calculate workstation state counts
        ws_active = 0
        ws_idle = 0
        ws_caution = 0
        ws_stopped = 0

        for ws in self._env.workstations.values():
            if hasattr(ws, "state"):
                state_str = str(ws.state)
                if "Busy" in state_str:
                    ws_active += 1
                elif "Idle" in state_str:
                    ws_idle += 1
                elif "Yellow" in state_str:
                    ws_caution += 1
                elif "Red" in state_str:
                    ws_stopped += 1

        # Calculate car counts
        active_cars = len(
            [
                car
                for car in self._env.cars.values()
                if hasattr(car, "state") and car.state != "Finished"
            ]
        )
        finished_cars = len(
            [
                car
                for car in self._env.cars.values()
                if hasattr(car, "state") and car.state == "Finished"
            ]
        )
        cars_in_inspection = len(
            [
                car
                for car in self._env.cars.values()
                if hasattr(car, "state") and "Inspection" in str(car.state)
            ]
        )

        # Calculate average lead time for finished cars
        finished_lead_times = [
            car.final_lead_time
            for car in self._env.cars.values()
            if hasattr(car, "final_lead_time") and car.final_lead_time is not None
        ]
        avg_lead_time = (
            sum(finished_lead_times) / len(finished_lead_times) if finished_lead_times else None
        )

        return ProductionMetrics(
            is_tracking=env_metrics["tracking_production"],
            start_time=env_metrics["production_start_time"],
            elapsed_time=env_metrics["elapsed_time"],
            total_workstations=len(self._env.workstations),
            active_cars=active_cars,
            finished_cars=finished_cars,
            cars_in_inspection=cars_in_inspection,
            workstations_active=ws_active,
            workstations_idle=ws_idle,
            workstations_caution=ws_caution,
            workstations_stopped=ws_stopped,
            average_lead_time=avg_lead_time,
        )

    def get_system_status(self) -> SystemStatus:
        """
        Get overall system status and health information.

        Returns:
            SystemStatus: Current system status including initialization and component health.
        """
        is_initialized = self._env.is_initialized()
        is_production_tracking = self._env.tracking_production if is_initialized else False
        component_counts = (
            self._env.get_agent_counts()
            if is_initialized
            else {
                "workstations": 0,
                "cars": 0,
                "inspection_station": 0,
                "communication_agent": 0,
            }
        )

        # Check MQTT connection status. The comm agent exposes the
        # underlying protocol's is_connected; fall back to bare existence
        # check if the attribute isn't there (e.g., during tests).
        mqtt_connected = False
        if is_initialized and self._env.comm_agent is not None:
            proto = getattr(self._env.comm_agent, "_protocol", None)
            if proto is not None and hasattr(proto, "is_connected"):
                mqtt_connected = proto.is_connected()
            else:
                mqtt_connected = True  # comm agent exists; assume connected

        uptime = time.time() - self._init_time

        return SystemStatus(
            is_initialized=is_initialized,
            is_production_tracking=is_production_tracking,
            component_counts=component_counts,
            mqtt_connected=mqtt_connected,
            configuration_valid=True,  # If we got this far, config is valid
            error_count=self._get_error_count(),
            uptime_seconds=uptime,
        )

    def get_inspection_station_status(self) -> InspectionStationStatus:
        """
        Get inspection station status.

        Returns:
            InspectionStationStatus: Current status of the inspection station.

        Raises:
            SimulationError: If inspection station not available.
        """
        if not self._env.inspection_station:
            raise SimulationError(
                "Inspection station not available",
                error_code="INSPECTION_STATION_NOT_FOUND",
            )

        return self._converters.convert_inspection_station(self._env.inspection_station)
