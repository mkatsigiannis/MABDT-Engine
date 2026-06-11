"""Barcode Service tab: wraps the BarcodeServiceWidget with config loading."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from tiger_motors_dt.config import load_config
from tiger_motors_dt.widgets import BarcodeServiceWidget

logger = logging.getLogger(__name__)


def build(main_window) -> QWidget:
    """Build the Barcode Service tab; on failure, return an inline error widget."""
    try:
        service_config = {}
        try:
            service_config = load_config().get("barcode_scanner_service", {})
        except Exception as config_error:
            logger.warning(f"Failed to load config.json: {config_error}")

        main_window.barcode_service_widget = BarcodeServiceWidget(service_config)
        return main_window.barcode_service_widget

    except Exception as e:
        logger.error(f"Error creating barcode service tab: {e}")
        return _error_widget(f"Error loading Barcode Scanner Service: {e}")


def _error_widget(message: str) -> QWidget:
    error_widget = QWidget()
    error_layout = QVBoxLayout()

    error_label = QLabel(message)
    error_label.setStyleSheet("color: red; font-weight: bold; padding: 20px;")
    error_label.setAlignment(Qt.AlignCenter)

    error_layout.addWidget(error_label)
    error_widget.setLayout(error_layout)
    return error_widget
