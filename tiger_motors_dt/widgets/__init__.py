"""PySide6 widgets for the Tiger Motors GUI.

`LLM_AVAILABLE` is True when the optional `ollama` extra is installed
and `LLMChatWidget` is importable; consumers should branch on the flag
rather than guarding the import themselves.
"""

from mabdt.utils.logging import get_logger

logger = get_logger(__name__)

from .car_tracking_widget import CarTrackingWidget
from .finished_car_tracking_widget import FinishedCarTrackingWidget
from .inspection_station_card import InspectionStationCard
from .production_control_widget import ProductionControlWidget
from .worker import EnvironmentWorker
from .workstation_card import WorkstationCard

# Optional LLM integration - gracefully handle missing dependencies
try:
    from .llm_chat_widget import LLMChatWidget

    LLM_AVAILABLE = True
except ImportError as e:
    logger.warning(f"LLM Chat Widget not available: {e}")
    logger.warning("LLM features will be disabled. Install 'ollama' package to enable.")
    LLMChatWidget = None
    LLM_AVAILABLE = False

from .agent_inspector_widget import AgentInspectorWidget
from .barcode_service_widget import (
    BarcodeServiceControlWidget,
    BarcodeServiceMonitorWidget,
    BarcodeServiceWidget,
)

# Define what gets imported with "from widgets import *"
__all__ = [
    "EnvironmentWorker",
    "WorkstationCard",
    "InspectionStationCard",
    "CarTrackingWidget",
    "FinishedCarTrackingWidget",
    "ProductionControlWidget",
    "BarcodeServiceWidget",
    "BarcodeServiceControlWidget",
    "BarcodeServiceMonitorWidget",
    "AgentInspectorWidget",
    "LLM_AVAILABLE",
]

# Only export LLMChatWidget if available
if LLM_AVAILABLE:
    __all__.append("LLMChatWidget")
