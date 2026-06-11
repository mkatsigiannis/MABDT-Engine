"""Query helpers for car status DTOs."""

from typing import TYPE_CHECKING

from mabdt.exceptions import SimulationError
from mabdt.utils.logging import get_logger
from tiger_motors_dt.simulation.converters import DTOConverters
from tiger_motors_dt.simulation.dto import CarStatus

if TYPE_CHECKING:
    from tiger_motors_dt.simulation.environment import TigerMotorsEnvironment

logger = get_logger(__name__)


class CarQueries:
    """
    Handles car status retrieval and conversion.

    This class encapsulates all logic for querying car data from
    the simulation environment and converting it to DTOs for external use.

    Attributes:
        _env: Reference to the simulation environment.
        _converters: DTO converter instance for transforming agents to DTOs.
    """

    def __init__(self, environment: "TigerMotorsEnvironment", converters: DTOConverters):
        """
        Initialize car queries with dependencies.

        Args:
            environment: The simulation environment containing car agents.
            converters: DTO converter instance for transforming agents.
        """
        self._env = environment
        self._converters = converters

    def get_active(self) -> list[CarStatus]:
        """
        Get all active (not finished) cars.

        Returns:
            List[CarStatus]: List of active car statuses.

        Note:
            Individual conversion failures are logged but don't stop the batch operation.
            Failed cars will be omitted from the result.
        """
        active_cars: list[CarStatus] = []

        for car_id, car in self._env.cars.items():
            try:
                # Only include cars that are not finished
                if hasattr(car, "state") and car.state != "Finished":
                    car_status = self._converters.convert_car(car)
                    active_cars.append(car_status)
            except SimulationError as e:
                logger.warning(f"Failed to convert car {car_id}: {e}")
                # Continue with other cars

        return active_cars

    def get_finished(self) -> list[CarStatus]:
        """
        Get all finished cars.

        Returns:
            List[CarStatus]: List of finished car statuses.

        Note:
            Individual conversion failures are logged but don't stop the batch operation.
            Failed cars will be omitted from the result.
        """
        finished_cars: list[CarStatus] = []

        for car_id, car in self._env.cars.items():
            try:
                # Only include cars that are finished
                if hasattr(car, "state") and car.state == "Finished":
                    car_status = self._converters.convert_car(car)
                    finished_cars.append(car_status)
            except SimulationError as e:
                logger.warning(f"Failed to convert finished car {car_id}: {e}")
                # Continue with other cars

        return finished_cars

    def get_all(self) -> list[CarStatus]:
        """
        Get all cars regardless of state.

        Returns:
            List[CarStatus]: List of all car statuses.
        """
        all_cars: list[CarStatus] = []

        for car_id, car in self._env.cars.items():
            try:
                car_status = self._converters.convert_car(car)
                all_cars.append(car_status)
            except SimulationError as e:
                logger.warning(f"Failed to convert car {car_id}: {e}")

        return all_cars

    def get_by_vin(self, vin: str) -> CarStatus | None:
        """
        Get a specific car by VIN.

        Args:
            vin: Vehicle identification number to look up.

        Returns:
            CarStatus if found, None otherwise.
        """
        car = self._env.cars.get(vin)
        if car:
            try:
                return self._converters.convert_car(car)
            except SimulationError as e:
                logger.warning(f"Failed to convert car {vin}: {e}")
        return None

    def get_active_count(self) -> int:
        """
        Get count of active (not finished) cars.

        Returns:
            int: Number of active cars.
        """
        return len(
            [
                car
                for car in self._env.cars.values()
                if hasattr(car, "state") and car.state != "Finished"
            ]
        )

    def get_finished_count(self) -> int:
        """
        Get count of finished cars.

        Returns:
            int: Number of finished cars.
        """
        return len(
            [
                car
                for car in self._env.cars.values()
                if hasattr(car, "state") and car.state == "Finished"
            ]
        )

    def get_in_inspection_count(self) -> int:
        """
        Get count of cars currently at or waiting for inspection.

        Returns:
            int: Number of cars in inspection phase.
        """
        return len(
            [
                car
                for car in self._env.cars.values()
                if hasattr(car, "state") and "Inspection" in str(car.state)
            ]
        )
