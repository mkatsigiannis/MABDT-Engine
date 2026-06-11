"""Agent → DTO conversion for the Tiger Motors interface layer.

Each `convert_*` method takes a live agent and returns the matching
frozen-dataclass DTO. The converter holds a reference to the environment
so it can resolve cross-agent fields (e.g. the VIN of the car parked at
a given workstation).
"""

import time
from typing import TYPE_CHECKING, Any

from mabdt.exceptions import SimulationError
from tiger_motors_dt.simulation.dto import CarStatus, InspectionStationStatus, WorkstationStatus

if TYPE_CHECKING:
    from tiger_motors_dt.simulation.environment import TigerMotorsEnvironment


class DTOConverters:
    """Builds frozen DTOs from live agents, resolving cross-agent fields via the environment."""

    def __init__(self, environment: "TigerMotorsEnvironment"):
        """
        Initialize the converters with environment reference.

        Args:
            environment: The simulation environment for entity lookups.
        """
        self._environment = environment

    def convert_workstation(self, workstation: Any) -> WorkstationStatus:
        """
        Convert internal WorkstationAgent to WorkstationStatus DTO.

        Args:
            workstation: WorkstationAgent instance to convert.

        Returns:
            WorkstationStatus: Immutable DTO representing workstation state.

        Raises:
            SimulationError: If conversion fails.
        """
        try:
            # Extract state information
            state = str(workstation.state) if hasattr(workstation, "state") else "Unknown"

            # Determine simplified state and andon color
            simplified_state, andon_color = self.parse_workstation_state(state)

            # Find current car at this workstation
            current_car = self._find_car_at_workstation(workstation)

            # Get time tracking data. The workstation agent exposes the
            # four utilization durations as wall-clock seconds via
            # StateTimer-backed properties; no tick-rate math here.
            idle_time = float(getattr(workstation, "idle_time", 0.0))
            busy_time = float(getattr(workstation, "busy_time", 0.0))
            yellow_time = float(getattr(workstation, "yellow_time", 0.0))
            red_time = float(getattr(workstation, "red_time", 0.0))

            # Check if workstation is paused
            is_paused = getattr(workstation, "paused", False)

            return WorkstationStatus(
                id=workstation.ws_id,
                state=simplified_state,
                andon_color=andon_color,
                current_car=current_car,
                idle_time=idle_time,
                busy_time=busy_time,
                yellow_time=yellow_time,
                red_time=red_time,
                is_paused=is_paused,
            )

        except Exception as e:
            raise SimulationError(
                f"Failed to convert workstation to DTO: {e}",
                error_code="WORKSTATION_CONVERSION_FAILED",
                context={"workstation_id": getattr(workstation, "ws_id", "Unknown")},
            ) from e

    def _find_car_at_workstation(self, workstation: Any) -> str | None:
        """
        Find the car currently at the given workstation.

        Args:
            workstation: WorkstationAgent to check.

        Returns:
            Car ID if found, None otherwise.
        """
        if self._environment and hasattr(self._environment, "cars"):
            for car in self._environment.cars.values():
                if (
                    hasattr(car, "current_workstation")
                    and car.current_workstation == workstation.ws_num
                ):
                    return car.car_id
        return None

    @staticmethod
    def parse_workstation_state(state: str) -> tuple[str, str]:
        """
        Parse workstation state to extract simplified state and andon color.

        Args:
            state: Raw state string from workstation agent.

        Returns:
            Tuple of (simplified_state, andon_color).
        """
        state_lower = state.lower()

        if "idle" in state_lower:
            return ("idle", "green")
        elif "busy" in state_lower:
            return ("busy", "green")
        elif "yellow" in state_lower:
            return ("caution", "yellow")
        elif "red" in state_lower:
            return ("stopped", "red")
        elif "production" in state_lower and "start" in state_lower:
            return ("starting", "paused")
        elif "initialize" in state_lower:
            return ("initializing", "paused")
        else:
            return ("unknown", "paused")

    def convert_car(self, car: Any) -> CarStatus:
        """
        Convert internal CarAgent to CarStatus DTO.

        Args:
            car: CarAgent instance to convert.

        Returns:
            CarStatus: Immutable DTO representing car state.

        Raises:
            SimulationError: If conversion fails.
        """
        try:
            # Basic car information
            vin = getattr(car, "car_id", "Unknown")
            state = str(getattr(car, "state", "Unknown"))
            current_workstation = getattr(car, "current_workstation", None)

            # Fault information
            production_faults = list(getattr(car, "during_production_faults", []))
            inspection_faults = list(getattr(car, "faults", []))

            # Timing information
            starting_time = getattr(car, "starting_time", 0)
            final_lead_time = getattr(car, "final_lead_time", None)

            # Calculate current lead time if not finished
            if final_lead_time is not None:
                lead_time = final_lead_time
            elif starting_time > 0:
                lead_time = time.time() - starting_time
            else:
                lead_time = None

            # Determine if finished
            is_finished = state == "Finished"

            return CarStatus(
                vin=vin,
                state=state,
                current_workstation=current_workstation,
                production_faults=production_faults,
                inspection_faults=inspection_faults,
                lead_time=lead_time,
                starting_time=starting_time,
                is_finished=is_finished,
            )

        except Exception as e:
            raise SimulationError(
                f"Failed to convert car to DTO: {e}",
                error_code="CAR_CONVERSION_FAILED",
                context={"car_id": getattr(car, "car_id", "Unknown")},
            ) from e

    def convert_inspection_station(self, inspection_station: Any) -> InspectionStationStatus:
        """
        Convert internal InspectionStationAgent to InspectionStationStatus DTO.

        Args:
            inspection_station: InspectionStationAgent instance to convert.

        Returns:
            InspectionStationStatus: Immutable DTO representing inspection station state.

        Raises:
            SimulationError: If conversion fails.
        """
        try:
            # Basic inspection station information
            state = str(getattr(inspection_station, "state", "Unknown"))

            # Current car being inspected
            current_car_vin = None
            current_car = getattr(inspection_station, "current_car", None)
            if current_car and hasattr(current_car, "car_id"):
                current_car_vin = current_car.car_id

            # Latest fault detected
            newest_fault = getattr(inspection_station, "newest_fault", None)

            # Whether station is actively processing
            is_active = (
                "inspecting" in state.lower()
                or "fault" in state.lower()
                or "passed" in state.lower()
            )

            is_paused = getattr(inspection_station, "paused", False)

            return InspectionStationStatus(
                state=state,
                current_car_vin=current_car_vin,
                newest_fault=newest_fault,
                is_active=is_active,
                is_paused=is_paused,
            )

        except Exception as e:
            raise SimulationError(
                f"Failed to convert inspection station to DTO: {e}",
                error_code="INSPECTION_CONVERSION_FAILED",
            ) from e
