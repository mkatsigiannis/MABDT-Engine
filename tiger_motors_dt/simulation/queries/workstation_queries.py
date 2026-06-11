"""Query helpers for workstation status DTOs."""

from typing import TYPE_CHECKING

from mabdt.exceptions import SimulationError
from mabdt.utils.logging import get_logger
from tiger_motors_dt.simulation.converters import DTOConverters
from tiger_motors_dt.simulation.dto import WorkstationStatus

if TYPE_CHECKING:
    from tiger_motors_dt.simulation.environment import TigerMotorsEnvironment

logger = get_logger(__name__)


class WorkstationQueries:
    """
    Handles workstation status retrieval and conversion.

    This class encapsulates all logic for querying workstation data from
    the simulation environment and converting it to DTOs for external use.

    Attributes:
        _env: Reference to the simulation environment.
        _converters: DTO converter instance for transforming agents to DTOs.
    """

    def __init__(self, environment: "TigerMotorsEnvironment", converters: DTOConverters):
        """
        Initialize workstation queries with dependencies.

        Args:
            environment: The simulation environment containing workstation agents.
            converters: DTO converter instance for transforming agents.
        """
        self._env = environment
        self._converters = converters

    def get_status(self, ws_id: str) -> WorkstationStatus:
        """
        Get status for a single workstation.

        Args:
            ws_id: Workstation identifier (e.g., "C1WS1", "C2WS5").

        Returns:
            WorkstationStatus: Current status of the workstation.

        Raises:
            ValueError: If ws_id is invalid.
            SimulationError: If workstation not found or conversion fails.
        """
        if not ws_id or not isinstance(ws_id, str):
            raise ValueError(f"Invalid workstation ID: {ws_id}")

        # Get workstation agent from environment
        workstation = self._env.workstations.get(ws_id)
        if not workstation:
            raise SimulationError(
                f"Workstation not found: {ws_id}",
                error_code="WORKSTATION_NOT_FOUND",
                context={"ws_id": ws_id},
            )

        # Convert internal state to DTO
        return self._converters.convert_workstation(workstation)

    def get_all(self) -> dict[str, WorkstationStatus]:
        """
        Get status for all workstations.

        Returns:
            Dict[str, WorkstationStatus]: Dictionary mapping workstation IDs to their status.

        Note:
            Individual conversion failures are logged but don't stop the batch operation.
            Failed workstations will be omitted from the result.
        """
        workstation_statuses: dict[str, WorkstationStatus] = {}

        for ws_id, workstation in self._env.workstations.items():
            try:
                workstation_statuses[ws_id] = self._converters.convert_workstation(workstation)
            except SimulationError as e:
                logger.warning(f"Failed to convert workstation {ws_id}: {e}")
                # Continue with other workstations

        return workstation_statuses

    def get_by_cell(self, cell_number: int) -> dict[str, WorkstationStatus]:
        """
        Get status for all workstations in a specific cell.

        Args:
            cell_number: Cell number (1-based) to filter by.

        Returns:
            Dict[str, WorkstationStatus]: Dictionary of workstations in the specified cell.
        """
        cell_prefix = f"C{cell_number}"
        cell_workstations: dict[str, WorkstationStatus] = {}

        for ws_id, workstation in self._env.workstations.items():
            if ws_id.startswith(cell_prefix):
                try:
                    cell_workstations[ws_id] = self._converters.convert_workstation(workstation)
                except Exception as e:
                    logger.warning(f"Failed to convert workstation {ws_id}: {e}")

        return cell_workstations

    def get_count(self) -> int:
        """
        Get total number of workstations.

        Returns:
            int: Total workstation count.
        """
        return len(self._env.workstations)
