"""
Tiger Motors Digital Twin - GUI Managers Package

This package contains specialized manager classes that handle specific aspects
of the GUI application:

- DisplayUpdateManager: Handles all GUI display updates and refresh cycles
- TabManager: Handles tab creation and management with modular factory system
"""

from .display_manager import DisplayUpdateManager
from .tab_manager import TabManager

__all__ = ["DisplayUpdateManager", "TabManager"]
