"""Active Cars tab: statistics bar + two CarTrackingWidget tables side-by-side."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from tiger_motors_dt.widgets import CarTrackingWidget


def build(main_window) -> QWidget:
    """Build the Active Cars tab and stash widget refs on `main_window`."""
    cars_tab = QWidget()
    layout = QVBoxLayout()

    title_label = QLabel("Active Cars Tracking")
    title_label.setFont(QFont("Arial", 16, QFont.Bold))
    title_label.setAlignment(Qt.AlignCenter)

    description_label = QLabel("Real-time tracking of vehicles currently in production")
    description_label.setAlignment(Qt.AlignCenter)
    description_label.setStyleSheet("color: gray; font-style: italic;")

    stats_widget = _statistics(main_window)
    tables_widget = _tables(main_window)

    layout.addWidget(title_label)
    layout.addWidget(description_label)
    layout.addSpacing(10)
    layout.addWidget(stats_widget)
    layout.addSpacing(10)
    layout.addWidget(tables_widget, 1)

    cars_tab.setLayout(layout)
    return cars_tab


def _statistics(main_window) -> QWidget:
    """Top-of-tab statistics bar: total / in production / awaiting inspection / finished."""
    stats_layout = QHBoxLayout()

    main_window.total_cars_label = QLabel("Total Active Cars: 0")
    main_window.total_cars_label.setFont(QFont("Arial", 14, QFont.Bold))

    main_window.cars_in_production_label = QLabel("In Production: 0")
    main_window.cars_in_production_label.setFont(QFont("Arial", 12))
    main_window.cars_in_production_label.setStyleSheet("color: blue;")

    main_window.cars_in_inspection_label = QLabel("Awaiting Inspection: 0")
    main_window.cars_in_inspection_label.setFont(QFont("Arial", 12))
    main_window.cars_in_inspection_label.setStyleSheet("color: orange;")

    main_window.finished_cars_label = QLabel("Finished: 0")
    main_window.finished_cars_label.setFont(QFont("Arial", 12))
    main_window.finished_cars_label.setStyleSheet("color: green;")

    stats_layout.addWidget(main_window.total_cars_label)
    stats_layout.addStretch()
    stats_layout.addWidget(main_window.cars_in_production_label)
    stats_layout.addStretch()
    stats_layout.addWidget(main_window.cars_in_inspection_label)
    stats_layout.addStretch()
    stats_layout.addWidget(main_window.finished_cars_label)

    stats_widget = QWidget()
    stats_widget.setLayout(stats_layout)
    return stats_widget


def _tables(main_window) -> QWidget:
    """Side-by-side production/inspection car tables."""
    tables_layout = QHBoxLayout()

    production_group = QGroupBox("Cars in Production (Assembly Line)")
    production_group.setStyleSheet("QGroupBox { font-weight: bold; color: blue; }")
    production_layout = QVBoxLayout()
    main_window.production_cars_table = CarTrackingWidget()
    production_layout.addWidget(main_window.production_cars_table)
    production_group.setLayout(production_layout)

    inspection_group = QGroupBox("Cars Awaiting Inspection")
    inspection_group.setStyleSheet("QGroupBox { font-weight: bold; color: orange; }")
    inspection_layout = QVBoxLayout()
    main_window.inspection_cars_table = CarTrackingWidget()
    inspection_layout.addWidget(main_window.inspection_cars_table)
    inspection_group.setLayout(inspection_layout)

    tables_layout.addWidget(production_group, 3)
    tables_layout.addWidget(inspection_group, 2)

    tables_widget = QWidget()
    tables_widget.setLayout(tables_layout)
    return tables_widget
