"""Interface Layer (JIM §3.3).

The single boundary through which external consumers read the engine's state.
Provides a stable API that delivers consistent snapshots and shields callers
from the agents' internal implementation.
"""

from mabdt.interface_layer.dto import DTO
from mabdt.interface_layer.query import Query
from mabdt.interface_layer.simulation_interface import SimulationInterface

__all__ = ["DTO", "Query", "SimulationInterface"]
