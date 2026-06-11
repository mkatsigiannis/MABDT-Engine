"""TabManager: owns the QTabWidget and dispatches to per-tab builders in `tabs/`."""

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QTabWidget, QWidget

from tiger_motors_dt.interfaces.gui.managers.tabs import (
    build_agent_inspector_tab,
    build_barcode_service_tab,
    build_cars_tab,
    build_finished_cars_tab,
    build_llm_chat_tab,
    build_production_tab,
)
from tiger_motors_dt.widgets import LLM_AVAILABLE

logger = logging.getLogger(__name__)


class TabManager(QObject):
    """Builds and tracks the main window's tabs.

    Emits `tab_created(name, widget)` and `tab_removed(name)` for callers
    that need to react to the tab set changing at runtime.
    """

    tab_created = Signal(str, QWidget)
    tab_removed = Signal(str)

    # name -> builder(main_window) -> QWidget. Order here is the display order.
    _TAB_BUILDERS = {
        "Production Monitor": build_production_tab,
        "Active Cars": build_cars_tab,
        "Finished Cars": build_finished_cars_tab,
        "Agent Inspector": build_agent_inspector_tab,
        "AI Assistant": build_llm_chat_tab,
        "Barcode Service": build_barcode_service_tab,
    }

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.tabs: dict[str, QWidget] = {}
        self.tab_widget: QTabWidget | None = None

        # AI Assistant only shows up if the ollama extra is installed.
        self.tab_order = [
            name for name in self._TAB_BUILDERS if name != "AI Assistant" or LLM_AVAILABLE
        ]

    def create_all_tabs(self) -> QTabWidget:
        """Build every tab in `self.tab_order` and return the QTabWidget."""
        self.tab_widget = QTabWidget()
        for tab_name in self.tab_order:
            try:
                widget = self._TAB_BUILDERS[tab_name](self.main_window)
                if widget is not None:
                    self.add_tab(tab_name, widget)
            except Exception as e:
                logger.error(f"Error creating tab '{tab_name}': {e}")
        logger.info(f"Created {len(self.tabs)} tabs")
        return self.tab_widget

    def add_tab(self, name: str, widget: QWidget, index: int | None = None):
        """Append (or insert at `index`) a tab and emit `tab_created`."""
        if self.tab_widget is None:
            logger.error("Tab widget not initialized. Call create_all_tabs() first.")
            return
        self.tabs[name] = widget
        if index is not None:
            self.tab_widget.insertTab(index, widget, name)
        else:
            self.tab_widget.addTab(widget, name)
        self.tab_created.emit(name, widget)

    def remove_tab(self, name: str) -> bool:
        """Remove a tab by name. Returns True if the tab existed."""
        if name not in self.tabs:
            logger.warning(f"Tab '{name}' not found")
            return False
        widget = self.tabs.pop(name)
        for i in range(self.tab_widget.count()):
            if self.tab_widget.widget(i) is widget:
                self.tab_widget.removeTab(i)
                break
        self.tab_removed.emit(name)
        return True

    def get_tab(self, name: str) -> QWidget | None:
        return self.tabs.get(name)

    def get_tab_names(self) -> list[str]:
        return list(self.tabs.keys())

    def get_tab_count(self) -> int:
        return len(self.tabs)

    def set_current_tab(self, name: str) -> bool:
        """Activate the named tab. Returns True if the tab was found."""
        widget = self.tabs.get(name)
        if widget is None:
            logger.warning(f"Tab '{name}' not found")
            return False
        for i in range(self.tab_widget.count()):
            if self.tab_widget.widget(i) is widget:
                self.tab_widget.setCurrentIndex(i)
                return True
        return False

    def clear_all_tabs(self):
        if self.tab_widget:
            self.tab_widget.clear()
        self.tabs.clear()
