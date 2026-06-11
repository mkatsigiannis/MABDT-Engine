"""Tiger Motors simulation interface.

Subclass of `mabdt.SimulationInterface` that adds the deployment's domain
query methods (workstation status, car status, production metrics, system
status). The mabdt base handles lock-protected lifecycle (initialize,
start/stop production, shutdown); this class only adds the read paths
that return Tiger DTOs.
"""

from __future__ import annotations

import time

from mabdt import SimulationInterface as _MABDTSimulationInterface
from mabdt.utils.logging import get_logger

from .converters import DTOConverters
from .dto import (
    CarStatus,
    InspectionStationStatus,
    ProductionMetrics,
    SystemStatus,
    WorkstationStatus,
)
from .environment import TigerMotorsEnvironment
from .queries import CarQueries, MetricsQueries, WorkstationQueries

logger = get_logger(__name__)


class SimulationInterface(_MABDTSimulationInterface):
    """Lock-protected facade for Tiger Motors deployment queries.

    Args:
        environment: Optional pre-built TigerMotorsEnvironment. If None, one
                     is built during `initialize()` via the Tiger factory.
    """

    def __init__(self, environment: TigerMotorsEnvironment | None = None) -> None:
        super().__init__(environment=environment)
        self._converters: DTOConverters | None = None
        self._workstation_queries: WorkstationQueries | None = None
        self._car_queries: CarQueries | None = None
        self._metrics_queries: MetricsQueries | None = None
        logger.info("Tiger SimulationInterface created")

    # --- Lifecycle ----------------------------------------------------------

    def initialize(self, config_path: str | None = None) -> bool:
        """Build the Tiger environment if absent, then delegate to the base."""
        with self._lock:
            if self._environment is None:
                # Local import avoids a cycle through simulation/__init__.
                from tiger_motors_dt.simulation.factory import create_environment

                self._environment = create_environment(config_path=config_path)
        return super().initialize()

    def _setup_queries(self) -> None:
        """Construct Tiger-specific query helpers. Called from base initialize."""
        self._converters = DTOConverters(self._environment)
        self._workstation_queries = WorkstationQueries(self._environment, self._converters)
        self._car_queries = CarQueries(self._environment, self._converters)
        self._metrics_queries = MetricsQueries(
            self._environment,
            self._converters,
            self._init_time,
            lambda: self._error_count,
        )

    def shutdown(self) -> None:
        """Clear query helpers, then delegate to the base shutdown."""
        with self._lock:
            self._converters = None
            self._workstation_queries = None
            self._car_queries = None
            self._metrics_queries = None
        super().shutdown()

    # --- Workstation queries ------------------------------------------------

    def get_workstation_status(self, ws_id: str) -> WorkstationStatus:
        with self._lock:
            try:
                self._validate_environment()
                return self._workstation_queries.get_status(ws_id)
            except Exception as e:
                self._error_count += 1
                logger.error(f"Failed to get workstation status for {ws_id}: {e}")
                raise

    def get_all_workstations(self) -> dict[str, WorkstationStatus]:
        with self._lock:
            try:
                self._validate_environment()
                return self._workstation_queries.get_all()
            except Exception as e:
                self._error_count += 1
                logger.error(f"Failed to get all workstation statuses: {e}")
                raise

    def get_all_workstation_statuses(self) -> dict[str, WorkstationStatus]:
        """Alias for `get_all_workstations` (legacy callers)."""
        return self.get_all_workstations()

    # --- Car queries --------------------------------------------------------

    def get_active_cars(self) -> list[CarStatus]:
        with self._lock:
            try:
                self._validate_environment()
                return self._car_queries.get_active()
            except Exception as e:
                self._error_count += 1
                logger.error(f"Failed to get active cars: {e}")
                raise

    def get_finished_cars(self) -> list[CarStatus]:
        with self._lock:
            try:
                self._validate_environment()
                return self._car_queries.get_finished()
            except Exception as e:
                self._error_count += 1
                logger.error(f"Failed to get finished cars: {e}")
                raise

    # --- Metrics + system queries ------------------------------------------

    def get_inspection_station_status(self) -> InspectionStationStatus:
        with self._lock:
            try:
                self._validate_environment()
                return self._metrics_queries.get_inspection_station_status()
            except Exception as e:
                self._error_count += 1
                logger.error(f"Failed to get inspection station status: {e}")
                raise

    def get_production_metrics(self) -> ProductionMetrics:
        with self._lock:
            try:
                self._validate_environment()
                return self._metrics_queries.get_production_metrics()
            except Exception as e:
                self._error_count += 1
                logger.error(f"Failed to get production metrics: {e}")
                raise

    def get_system_status(self) -> SystemStatus:
        with self._lock:
            try:
                if self._metrics_queries:
                    return self._metrics_queries.get_system_status()
                # Pre-initialize fallback so the GUI can show "not ready".
                uptime = time.time() - self._init_time
                return SystemStatus(
                    is_initialized=False,
                    is_production_tracking=False,
                    component_counts={
                        "workstations": 0,
                        "cars": 0,
                        "inspection_station": 0,
                        "communication_agent": 0,
                    },
                    mqtt_connected=False,
                    configuration_valid=True,
                    error_count=self._error_count,
                    uptime_seconds=uptime,
                )
            except Exception as e:
                self._error_count += 1
                logger.error(f"Failed to get system status: {e}")
                raise

    # --- Debug-only agent access ------------------------------------------
    #
    # The agent inspector panel needs the live Agent object so it can show
    # raw attribute values and the transitions-library state machine. That
    # is outside the DTO surface by design; these two methods are the
    # narrow, named escape hatch the inspector goes through, so the
    # reach-through is grep-able and the widget never references
    # deployment-specific attribute names on the environment.

    _DEBUG_AGENT_TYPES = ("Workstation Agents", "Car Agents", "Inspection Station")

    def debug_list_agent_ids(self, agent_type: str) -> list[str]:
        """Return sorted agent IDs for the inspector's type-picker combo box."""
        with self._lock:
            self._validate_environment()
            env = self._environment
            if agent_type == "Workstation Agents":
                return sorted(env.workstations.keys(), key=lambda x: int(x.split("WS")[1]))
            if agent_type == "Car Agents":
                return sorted(env.cars.keys())
            if agent_type == "Inspection Station":
                return ["InspectionStation"]
            return []

    def debug_get_agent(self, agent_type: str, agent_id: str):
        """Return the live Agent object the inspector should display, or None."""
        with self._lock:
            self._validate_environment()
            env = self._environment
            if agent_type == "Workstation Agents":
                return env.workstations.get(agent_id)
            if agent_type == "Car Agents":
                return env.cars.get(agent_id)
            if agent_type == "Inspection Station":
                return env.inspection_station
            return None
