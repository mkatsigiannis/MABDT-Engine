"""Finished Cars tab: quality statistics, legend, and the FinishedCarTrackingWidget."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from tiger_motors_dt.widgets import FinishedCarTrackingWidget


def build(main_window) -> QWidget:
    """Build the Finished Cars tab and stash widget refs on `main_window`."""
    finished_tab = QWidget()
    layout = QVBoxLayout()

    title_label = QLabel("Finished Cars - Quality Tracking")
    title_label.setFont(QFont("Arial", 16, QFont.Bold))
    title_label.setAlignment(Qt.AlignCenter)

    description_label = QLabel("Comprehensive quality tracking for completed vehicles")
    description_label.setAlignment(Qt.AlignCenter)
    description_label.setStyleSheet("color: gray; font-style: italic;")

    stats_widget = _statistics(main_window)
    legend_widget = _legend()

    finished_group = QGroupBox("Finished Cars - Quality Details")
    finished_group.setStyleSheet("QGroupBox { font-weight: bold; color: green; }")
    finished_layout = QVBoxLayout()
    main_window.finished_cars_table = FinishedCarTrackingWidget()
    finished_layout.addWidget(main_window.finished_cars_table)
    finished_group.setLayout(finished_layout)

    layout.addWidget(title_label)
    layout.addWidget(description_label)
    layout.addSpacing(10)
    layout.addWidget(stats_widget)
    layout.addSpacing(5)
    layout.addWidget(legend_widget)
    layout.addSpacing(10)
    layout.addWidget(finished_group, 1)

    finished_tab.setLayout(layout)
    return finished_tab


def _statistics(main_window) -> QWidget:
    """Total / Passed / Failed / Avg lead time readouts."""
    stats_layout = QHBoxLayout()

    main_window.finished_total_label = QLabel("Total Finished: 0")
    main_window.finished_total_label.setFont(QFont("Arial", 12, QFont.Bold))

    main_window.finished_passed_label = QLabel("Passed: 0")
    main_window.finished_passed_label.setFont(QFont("Arial", 11))
    main_window.finished_passed_label.setStyleSheet("color: green;")

    main_window.finished_failed_label = QLabel("Failed: 0")
    main_window.finished_failed_label.setFont(QFont("Arial", 11))
    main_window.finished_failed_label.setStyleSheet("color: red;")

    main_window.finished_avg_lead_time_label = QLabel("Avg Lead Time: --")
    main_window.finished_avg_lead_time_label.setFont(QFont("Arial", 11))
    main_window.finished_avg_lead_time_label.setStyleSheet("color: blue;")

    stats_layout.addWidget(main_window.finished_total_label)
    stats_layout.addStretch()
    stats_layout.addWidget(main_window.finished_passed_label)
    stats_layout.addStretch()
    stats_layout.addWidget(main_window.finished_failed_label)
    stats_layout.addStretch()
    stats_layout.addWidget(main_window.finished_avg_lead_time_label)

    stats_widget = QWidget()
    stats_widget.setLayout(stats_layout)
    return stats_widget


def _legend() -> QWidget:
    """Color-coding legend strip above the finished-cars table."""
    legend_layout = QHBoxLayout()
    legend_label = QLabel("Color Legend:")
    legend_label.setFont(QFont("Arial", 10, QFont.Bold))

    pass_legend = QLabel("PASS")
    pass_legend.setStyleSheet(
        "background-color: rgb(200, 255, 200); padding: 2px; border-radius: 3px;"
    )

    fail_legend = QLabel("FAIL")
    fail_legend.setStyleSheet(
        "background-color: rgb(255, 200, 200); padding: 2px; border-radius: 3px;"
    )

    production_fault_legend = QLabel("Production Faults")
    production_fault_legend.setStyleSheet(
        "background-color: rgb(255, 240, 200); padding: 2px; border-radius: 3px;"
    )

    legend_layout.addWidget(legend_label)
    legend_layout.addWidget(pass_legend)
    legend_layout.addWidget(fail_legend)
    legend_layout.addWidget(production_fault_legend)
    legend_layout.addStretch()

    legend_widget = QWidget()
    legend_widget.setLayout(legend_layout)
    return legend_widget
