"""Unit tests for `tiger_motors_dt.config.load_config` and its validators."""

import json
from pathlib import Path

import pytest

from tiger_motors_dt.config import (
    DEFAULT_CONFIG,
    load_config,
    validate_config,
    write_default_config,
)


def _good_config():
    """A minimal config that passes every validator."""
    return {
        "mqtt": {"host": "localhost", "port": 1883, "keepalive": 60},
        "production": {"target_takt_time": 75, "target_cycle_time": 60},
        "facility": {"total_workstations": 15, "cells": 3, "workstations_per_cell": 5},
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


def test_validate_default_config_passes():
    validate_config(DEFAULT_CONFIG)


def test_validate_missing_section_raises():
    cfg = _good_config()
    del cfg["mqtt"]
    with pytest.raises(ValueError, match="mqtt"):
        validate_config(cfg)


def test_validate_mqtt_negative_port_raises():
    cfg = _good_config()
    cfg["mqtt"]["port"] = -1
    with pytest.raises(ValueError, match="positive integer"):
        validate_config(cfg)


def test_validate_facility_inconsistent_raises():
    cfg = _good_config()
    cfg["facility"]["workstations_per_cell"] = 4
    with pytest.raises(ValueError, match="inconsistent"):
        validate_config(cfg)


def test_validate_performance_zero_tick_raises():
    cfg = _good_config()
    cfg["performance"]["eventbus_tick_interval"] = 0
    with pytest.raises(ValueError, match="positive number"):
        validate_config(cfg)


def test_validate_optional_opc_section_accepts_floats():
    cfg = _good_config()
    cfg["opc_ua_service"] = {
        "enabled": True,
        "subscription_interval": 0.5,
        "reconnect_delay": 1.0,
        "max_reconnect_delay": 60.0,
    }
    validate_config(cfg)


def test_validate_optional_opc_section_rejects_negative_delay():
    cfg = _good_config()
    cfg["opc_ua_service"] = {"reconnect_delay": -1}
    with pytest.raises(ValueError, match="reconnect_delay"):
        validate_config(cfg)


def test_load_config_missing_file_writes_default(tmp_path: Path):
    config_path = tmp_path / "config.json"
    assert not config_path.exists()

    config = load_config(config_path)

    assert config_path.exists()
    assert config == DEFAULT_CONFIG


def test_load_config_reads_existing_file(tmp_path: Path):
    config_path = tmp_path / "config.json"
    cfg = _good_config()
    cfg["mqtt"]["host"] = "broker.example.com"
    with open(config_path, "w") as f:
        json.dump(cfg, f)

    loaded = load_config(config_path)

    assert loaded["mqtt"]["host"] == "broker.example.com"


def test_load_config_invalid_json_raises(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{ not valid json")

    with pytest.raises(json.JSONDecodeError):
        load_config(config_path)


def test_load_config_invalid_schema_raises(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"mqtt": {}}))  # missing other required sections

    with pytest.raises(ValueError):
        load_config(config_path)


def test_write_default_config_creates_parent_dirs(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "config.json"
    write_default_config(nested)
    assert nested.exists()
    assert json.loads(nested.read_text()) == DEFAULT_CONFIG
