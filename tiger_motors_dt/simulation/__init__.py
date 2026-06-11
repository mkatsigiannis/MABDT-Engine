"""Tiger Motors simulation package — environment, interface, DTOs, and queries."""

from .dto import (
    CarStatus,
    InspectionStationStatus,
    ProductionMetrics,
    SystemStatus,
    WorkstationStatus,
)
from .environment import TigerMotorsEnvironment
from .factory import create_environment, create_environment_for_testing
from .interface import SimulationInterface

__all__ = [
    # Core components
    "TigerMotorsEnvironment",
    "SimulationInterface",
    # Factory functions
    "create_environment",
    "create_environment_for_testing",
    # DTOs
    "WorkstationStatus",
    "CarStatus",
    "InspectionStationStatus",
    "ProductionMetrics",
    "SystemStatus",
]
