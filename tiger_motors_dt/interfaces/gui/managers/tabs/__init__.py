"""Per-tab builders for the Tiger Motors main window.

Each module exposes a `build(main_window) -> QWidget` function that the
TabManager calls by name. Builders mutate `main_window` attributes
(workstation_cards, production_cars_table, ...) for the display manager
to find later.
"""

from .agent_inspector_tab import build as build_agent_inspector_tab
from .barcode_service_tab import build as build_barcode_service_tab
from .cars_tab import build as build_cars_tab
from .finished_cars_tab import build as build_finished_cars_tab
from .llm_chat_tab import build as build_llm_chat_tab
from .production_tab import build as build_production_tab

__all__ = [
    "build_agent_inspector_tab",
    "build_barcode_service_tab",
    "build_cars_tab",
    "build_finished_cars_tab",
    "build_llm_chat_tab",
    "build_production_tab",
]
