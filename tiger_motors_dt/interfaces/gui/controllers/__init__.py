"""
Tiger Motors Digital Twin - GUI Controllers Package

This package contains controller classes that manage simulation lifecycle
and coordination between the GUI and simulation system.

Controllers provide clean separation between GUI interface concerns and
simulation management logic, following MVC architectural patterns.
"""

from .simulation_controller import SimulationController

__all__ = ["SimulationController"]
