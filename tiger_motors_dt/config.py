"""Tiger Motors configuration loader.

Pure-function loader that reads `config.json` (or a path you pass),
validates it has the five required sections, and returns a dict. No
global state, no singleton — each caller that needs the config either
calls `load_config()` itself or takes the loaded dict as a parameter.

If the target file does not exist, a default config is written so the
first launch is self-bootstrapping. The default uses `localhost` for
MQTT and the Tiger lab's 15-workstation layout.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mabdt.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = "config.json"

REQUIRED_SECTIONS = ("mqtt", "production", "facility", "performance", "topics")

DEFAULT_CONFIG: dict[str, Any] = {
    "mqtt": {
        "host": "localhost",
        "port": 1883,
        "keepalive": 60,
        "username": None,
        "password": None,
    },
    "production": {"target_takt_time": 75, "target_cycle_time": 60},
    "facility": {
        "total_workstations": 15,
        "cells": 3,
        "workstations_per_cell": 5,
    },
    "performance": {
        "eventbus_tick_interval": 0.01,
        "gui_update_interval": 0.05,
        "state_stability_delay": 0.005,
        "agent_inbox_timeout": 0.1,
    },
    "topics": {
        "scanner_prefix": "scanner/",
        "plc_prefix": "plc/",
        "led_prefix": "leds/",
        "inspection_station": "scanner/InspectionStation",
        "production_start": "production_start",
    },
}


def load_config(path: str | os.PathLike = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Read `path` as JSON, validate, return the dict.

    If the file is missing, write `DEFAULT_CONFIG` to `path` first so a
    fresh checkout is self-bootstrapping.
    """
    path = Path(path)
    if not path.exists():
        logger.warning(f"Configuration file not found: {path}; writing default.")
        write_default_config(path)

    try:
        with open(path) as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Invalid JSON in {path}: {e.msg}", e.doc, e.pos) from e

    validate_config(config)

    logger.info(f"Configuration loaded from {path}")
    if "mqtt" in config:
        logger.info(f"MQTT Broker: {config['mqtt']['host']}:{config['mqtt']['port']}")
    return config


def write_default_config(path: str | os.PathLike = DEFAULT_CONFIG_PATH) -> None:
    """Write `DEFAULT_CONFIG` to `path` (creating parent dirs as needed)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    logger.info(f"Default configuration created: {path}")


def validate_config(config: dict[str, Any]) -> None:
    """Raise ValueError if `config` is missing a required section or has malformed values.

    Validates the five required sections (`mqtt`, `production`, `facility`,
    `performance`, `topics`) and the optional service sections
    (`barcode_scanner_service`, `opc_ua_service`) if present.
    """
    missing = [s for s in REQUIRED_SECTIONS if s not in config]
    if missing:
        raise ValueError(f"Missing required configuration sections: {missing}")

    _validate_mqtt(config["mqtt"])
    _validate_facility(config["facility"])
    _validate_performance(config["performance"])

    if "barcode_scanner_service" in config:
        _validate_barcode_scanner_service(config["barcode_scanner_service"])
    if "opc_ua_service" in config:
        _validate_opc_ua_service(config["opc_ua_service"])


def _validate_mqtt(mqtt: dict[str, Any]) -> None:
    for key in ("host", "port", "keepalive"):
        if key not in mqtt:
            raise ValueError(f"Missing required MQTT configuration: {key}")
    if not isinstance(mqtt["port"], int) or mqtt["port"] <= 0:
        raise ValueError("MQTT port must be a positive integer")
    if not isinstance(mqtt["keepalive"], int) or mqtt["keepalive"] <= 0:
        raise ValueError("MQTT keepalive must be a positive integer")


def _validate_facility(facility: dict[str, Any]) -> None:
    for key in ("total_workstations", "cells", "workstations_per_cell"):
        if key not in facility:
            raise ValueError(f"Missing required facility configuration: {key}")
    total = facility["total_workstations"]
    cells = facility["cells"]
    per_cell = facility["workstations_per_cell"]
    if total != cells * per_cell:
        raise ValueError(f"Facility configuration inconsistent: {total} != {cells} * {per_cell}")


def _validate_performance(perf: dict[str, Any]) -> None:
    required = (
        "eventbus_tick_interval",
        "gui_update_interval",
        "state_stability_delay",
        "agent_inbox_timeout",
    )
    for key in required:
        if key not in perf:
            raise ValueError(f"Missing required performance configuration: {key}")
        value = perf[key]
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"Performance setting '{key}' must be a positive number")


def _validate_barcode_scanner_service(scanner: dict[str, Any]) -> None:
    if "enabled" in scanner and not isinstance(scanner["enabled"], bool):
        raise ValueError("barcode_scanner_service.enabled must be a boolean")
    if "port" in scanner:
        if not isinstance(scanner["port"], int) or scanner["port"] <= 0:
            raise ValueError("barcode_scanner_service.port must be a positive integer")
    if "log_directory" in scanner and not isinstance(scanner["log_directory"], str):
        raise ValueError("barcode_scanner_service.log_directory must be a string")


def _validate_opc_ua_service(opc: dict[str, Any]) -> None:
    if "enabled" in opc and not isinstance(opc["enabled"], bool):
        raise ValueError("opc_ua_service.enabled must be a boolean")
    if "mqtt_port" in opc:
        if not isinstance(opc["mqtt_port"], int) or opc["mqtt_port"] <= 0:
            raise ValueError("opc_ua_service.mqtt_port must be a positive integer")
    for key in ("subscription_interval", "reconnect_delay", "max_reconnect_delay"):
        if key in opc:
            value = opc[key]
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"opc_ua_service.{key} must be a positive number")
