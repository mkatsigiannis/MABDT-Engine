"""Digital Twin Data Collector for the RAG system.

After Phase 4 this module no longer reads agent attributes directly. It
holds a `SimulationInterface` (built from the env passed in via
`set_environment`) and pulls DTO snapshots from it. The output dict
shape preserved here matches what the downstream
`DigitalTwinContextBuilder` and `DigitalTwinContextFormatter` expect, so
no formatter changes were needed.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class DigitalTwinDataCollector:
    """Collects DTO-based snapshots from the Digital Twin for RAG prompts."""

    def __init__(self, environment=None):
        """Initialize the data collector.

        Args:
            environment: TigerMotorsEnvironment (optional; can be set later).
        """
        self.environment = environment
        self._iface = None
        self.last_collection_time: float | None = None
        if environment is not None:
            self._build_iface()

    # --- Wiring ----------------------------------------------------------

    def set_environment(self, environment):
        """Set or update the environment reference; rebuild the iface."""
        self.environment = environment
        self._build_iface()

    def set_iface(self, iface):
        """Set the SimulationInterface directly.

        Preferred over `set_environment` when the caller already has an
        initialized interface (e.g. the GUI's main_window.iface). Avoids
        building a redundant interface on top of the same environment.
        """
        self._iface = iface
        if iface is not None:
            self.environment = iface.get_environment()

    def _build_iface(self):
        """Construct a SimulationInterface over `self.environment`."""
        if self.environment is None:
            self._iface = None
            return
        # Local import to avoid a cycle through simulation/__init__.py.
        from tiger_motors_dt.simulation.interface import SimulationInterface

        iface = SimulationInterface(environment=self.environment)
        # The env is already initialized by the time the collector sees
        # it (the GUI sets the env after on_simulation_initialized fires).
        # SimulationInterface.initialize() short-circuits in that case
        # without wiring up query helpers, so we set them up directly.
        iface._setup_queries()
        self._iface = iface

    def is_environment_available(self) -> bool:
        """True if the collector can issue queries."""
        return self._iface is not None and self._iface.is_initialized()

    # --- Collection methods (DTO-sourced, legacy dict shape) -------------

    def collect_workstation_states(self) -> dict[str, dict[str, Any]]:
        """Per-workstation state + per-state time tracking dictionary.

        State times are wall-clock seconds (from StateTimer in the
        workstation agent). Percentages are derived from them directly.
        """
        if not self.is_environment_available():
            return {}

        result: dict[str, dict[str, Any]] = {}
        try:
            ws_statuses = self._iface.get_all_workstations()
            for ws_id, status in ws_statuses.items():
                idle_s = float(status.idle_time)
                busy_s = float(status.busy_time)
                yellow_s = float(status.yellow_time)
                red_s = float(status.red_time)
                total_s = idle_s + busy_s + yellow_s + red_s
                result[ws_id] = {
                    "id": ws_id,
                    "current_state": status.state,
                    "idle_seconds": idle_s,
                    "busy_seconds": busy_s,
                    "yellow_seconds": yellow_s,
                    "red_seconds": red_s,
                    "total_seconds": total_s,
                    "idle_percentage": (idle_s / total_s * 100) if total_s else 0,
                    "busy_percentage": (busy_s / total_s * 100) if total_s else 0,
                    "yellow_percentage": (yellow_s / total_s * 100) if total_s else 0,
                    "red_percentage": (red_s / total_s * 100) if total_s else 0,
                }
        except Exception as e:
            logger.error(f"Error collecting workstation states: {e}")
        return result

    def collect_active_cars(self) -> dict[str, dict[str, Any]]:
        """Per-car dictionary keyed by VIN, with a `category` field.

        Includes both active and finished cars (the formatter walks them
        all and uses `category` to bucket).
        """
        if not self.is_environment_available():
            return {}

        result: dict[str, dict[str, Any]] = {}
        try:
            active = self._iface.get_active_cars()
            finished = self._iface.get_finished_cars()
            for car in [*active, *finished]:
                category = self._categorize(car)
                time_in_system = (
                    car.lead_time
                    if car.lead_time is not None
                    else (time.time() - car.starting_time if car.starting_time else None)
                )
                result[car.vin] = {
                    "id": car.vin,
                    "current_workstation": car.current_workstation,
                    "current_state": car.state,
                    "category": category,
                    "time_in_system": time_in_system,
                    "production_faults": list(car.production_faults),
                    "inspection_faults": list(car.inspection_faults),
                    "total_faults": len(car.production_faults) + len(car.inspection_faults),
                }
        except Exception as e:
            logger.error(f"Error collecting car data: {e}")
        return result

    @staticmethod
    def _categorize(car) -> str:
        """Bucket a CarStatus DTO into 'finished'/'inspection'/'active'/'unknown'."""
        if car.is_finished:
            return "finished"
        state_str = car.state.lower()
        if (
            car.current_workstation == 16
            or "inspection" in state_str
            or "waitinginspection" in state_str
        ):
            return "inspection"
        if car.current_workstation and 1 <= car.current_workstation <= 15:
            return "active"
        return "unknown"

    def collect_production_metrics(self) -> dict[str, Any]:
        """System-level metrics dictionary matching the legacy shape."""
        metrics: dict[str, Any] = {
            "collection_time": datetime.now().isoformat(),
            "tracking_production": False,
            "production_start_time": None,
            "total_workstations": 0,
            "total_cars_in_system": 0,
            "active_cars": 0,
            "inspection_cars": 0,
            "finished_cars": 0,
            "unknown_cars": 0,
        }
        if not self.is_environment_available():
            return metrics

        try:
            ws_statuses = self._iface.get_all_workstations()
            active_cars = self._iface.get_active_cars()
            finished_cars = self._iface.get_finished_cars()
            prod = self._iface.get_production_metrics()

            metrics["tracking_production"] = prod.is_tracking
            metrics["production_start_time"] = prod.start_time
            metrics["total_workstations"] = len(ws_statuses)
            metrics["total_cars_in_system"] = len(active_cars) + len(finished_cars)
            metrics["finished_cars"] = len(finished_cars)

            active_count = inspection_count = unknown_count = 0
            for car in active_cars:
                category = self._categorize(car)
                if category == "active":
                    active_count += 1
                elif category == "inspection":
                    inspection_count += 1
                elif category == "unknown":
                    unknown_count += 1
            metrics["active_cars"] = active_count
            metrics["inspection_cars"] = inspection_count
            metrics["unknown_cars"] = unknown_count

            # Configuration snapshot. This is one of the deliberate
            # escape hatches: the interface's DTO surface doesn't carry
            # the config dict, and the RAG context wants takt time and
            # broker info verbatim, so we read through the env directly.
            env = self._iface.get_environment()
            config = getattr(env, "config", {}) or {}
            metrics["target_takt_time"] = config.get("production", {}).get("target_takt_time", 75)
            metrics["target_cycle_time"] = config.get("production", {}).get("target_cycle_time", 60)
            mqtt = config.get("mqtt", {})
            metrics["mqtt_broker"] = f"{mqtt.get('host', 'Unknown')}:{mqtt.get('port', 'Unknown')}"
        except Exception as e:
            logger.error(f"Error collecting production metrics: {e}")
        return metrics

    def collect_all_data(self) -> dict[str, Any]:
        """Single-shot snapshot of workstations, cars, and metrics."""
        logger.info("[Data Collector] Collecting Digital Twin data...")
        collected = {
            "timestamp": datetime.now().isoformat(),
            "workstations": self.collect_workstation_states(),
            "cars": self.collect_active_cars(),
            "metrics": self.collect_production_metrics(),
        }
        self.last_collection_time = time.time()
        ws_count = len(collected["workstations"])
        car_count = len(collected["cars"])
        logger.info(f"[Data Collector] Collected data: {ws_count} workstations, {car_count} cars")
        return collected

    def get_summary_stats(self) -> str:
        """Short string for debug printouts."""
        if not self.is_environment_available():
            return "Environment not available"
        try:
            ws = self._iface.get_all_workstations()
            active = self._iface.get_active_cars()
            finished = self._iface.get_finished_cars()
            prod = self._iface.get_production_metrics()
            return (
                f"WS: {len(ws)}, "
                f"Cars: {len(active) + len(finished)}, "
                f"Tracking: {prod.is_tracking}"
            )
        except Exception as e:
            return f"Error: {e}"
