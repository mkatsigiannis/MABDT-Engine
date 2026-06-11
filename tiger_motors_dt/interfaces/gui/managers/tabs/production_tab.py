"""Production monitor tab: workstation grid, controls, and the side info panel."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tiger_motors_dt.config import load_config
from tiger_motors_dt.widgets import (
    InspectionStationCard,
    ProductionControlWidget,
    WorkstationCard,
)
from tiger_motors_dt.widgets.opc_service_status_widget import OPCServiceStatusWidget

logger = logging.getLogger(__name__)


def build(main_window) -> QWidget:
    """Build the production monitor tab and stash widget refs on `main_window`."""
    main_tab = QWidget()
    main_layout = QHBoxLayout()

    left_splitter = QSplitter(Qt.Vertical)

    control_panel_widget = QWidget()
    control_panel_layout = QVBoxLayout()
    control_panel_layout.setContentsMargins(0, 0, 0, 0)
    control_panel_layout.setSpacing(5)

    main_window.production_control = ProductionControlWidget()
    control_panel_layout.addWidget(main_window.production_control)

    try:
        opc_config = {}
        try:
            opc_config = load_config()
            logger.debug("Loaded OPC UA service configuration from config.json")
        except Exception as config_error:
            logger.warning(f"Failed to load config.json: {config_error}")

        main_window.opc_service_widget = OPCServiceStatusWidget(opc_config)
        control_panel_layout.addWidget(main_window.opc_service_widget)
    except Exception as e:
        logger.error(f"Error creating OPC UA status widget: {e}")

    control_panel_widget.setLayout(control_panel_layout)
    left_splitter.addWidget(control_panel_widget)

    left_splitter.addWidget(_workstation_grid(main_window))
    left_splitter.setSizes([200, 500])

    main_layout.addWidget(left_splitter, 2)
    main_layout.addWidget(_information_panel(main_window), 1)

    main_tab.setLayout(main_layout)
    return main_tab


def _workstation_grid(main_window) -> QWidget:
    """3×5 workstation card grid plus the inspection station card underneath."""
    group_box = QGroupBox("Workstation & Inspection Monitor")
    main_layout = QVBoxLayout()

    workstation_layout = QGridLayout()
    main_window.workstation_cards = {}

    ws_number = 1
    for cell in range(1, 4):
        for ws_in_cell in range(1, 6):
            ws_id = f"C{cell}WS{ws_number}"
            card = WorkstationCard(ws_id, main_window)
            main_window.workstation_cards[ws_id] = card
            workstation_layout.addWidget(card, cell - 1, ws_in_cell - 1)
            ws_number += 1

    workstation_widget = QWidget()
    workstation_widget.setLayout(workstation_layout)

    main_window.inspection_card = InspectionStationCard(main_window)

    inspection_layout = QHBoxLayout()
    inspection_layout.addStretch()
    inspection_layout.addWidget(main_window.inspection_card)
    inspection_layout.addStretch()

    inspection_widget = QWidget()
    inspection_widget.setLayout(inspection_layout)

    main_layout.addWidget(workstation_widget)
    main_layout.addWidget(inspection_widget)

    group_box.setLayout(main_layout)
    return group_box


def _information_panel(main_window) -> QWidget:
    """Right-side panel: production summary on top, system messages below."""
    panel = QWidget()
    layout = QVBoxLayout()

    messages_group = QGroupBox("System Messages")
    messages_layout = QVBoxLayout()
    main_window.messages_text = QTextEdit()
    main_window.messages_text.setReadOnly(True)
    main_window.messages_text.setFont(QFont("Consolas", 9))
    messages_layout.addWidget(main_window.messages_text)
    messages_group.setLayout(messages_layout)

    layout.addWidget(_production_summary(main_window), 1)
    layout.addWidget(messages_group, 4)

    panel.setLayout(layout)
    return panel


def _production_summary(main_window) -> QWidget:
    """Production-time readout group box."""
    summary_group = QGroupBox("Production Summary")
    summary_layout = QVBoxLayout()

    main_window.production_time_label = QLabel("Production Time: 00:00:00")
    main_window.production_time_label.setFont(QFont("Arial", 10, QFont.Bold))

    summary_layout.addWidget(main_window.production_time_label)
    summary_layout.addStretch()

    summary_group.setLayout(summary_layout)
    return summary_group
