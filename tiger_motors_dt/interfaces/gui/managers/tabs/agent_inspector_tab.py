"""Agent Inspector tab: hosts the AgentInspectorWidget debug panel."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from tiger_motors_dt.widgets import AgentInspectorWidget

logger = logging.getLogger(__name__)


def build(main_window) -> QWidget:
    """Build the Agent Inspector tab; on failure, return an inline error widget."""
    try:
        main_window.agent_inspector_widget = AgentInspectorWidget()

        # Bind the interface eagerly if the simulation is already up; the
        # display manager covers the late-binding case on its next tick.
        iface = getattr(main_window, "iface", None)
        if iface is not None and iface.is_initialized():
            main_window.agent_inspector_widget.set_interface(iface)

        return main_window.agent_inspector_widget

    except Exception as e:
        logger.error(f"Error creating agent inspector tab: {e}")

        error_widget = QWidget()
        error_layout = QVBoxLayout()
        error_label = QLabel(f"Error loading Agent Inspector: {e}")
        error_label.setStyleSheet("color: red; font-weight: bold; padding: 20px;")
        error_label.setAlignment(Qt.AlignCenter)
        error_layout.addWidget(error_label)
        error_widget.setLayout(error_layout)
        return error_widget
