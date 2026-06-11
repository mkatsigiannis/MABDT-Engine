"""Factory functions for constructing a `TigerMotorsEnvironment`.

`create_environment()` is the standard entrypoint — loads config,
creates the event bus, and wires the environment. Tests that need
mock dependencies can instantiate `TigerMotorsEnvironment` directly.
"""

from typing import Any

from mabdt.communication_kernel.event_bus import EventBus
from tiger_motors_dt.config import DEFAULT_CONFIG_PATH, load_config

from .environment import TigerMotorsEnvironment


def create_environment(
    config_path: str | None = None,
    config: dict[str, Any] | None = None,
    bus: EventBus | None = None,
) -> TigerMotorsEnvironment:
    """Build a `TigerMotorsEnvironment` with config + event bus + agents wired.

    Args:
        config_path: Path to a config JSON. Ignored if `config` is given.
                     Defaults to `config.json` in the working directory.
        config: Pre-loaded configuration dict. Skips file loading entirely.
        bus: Pre-built EventBus. If None, one is created from `config`.
    """
    if config is None:
        config = load_config(config_path or DEFAULT_CONFIG_PATH)

    if bus is None:
        bus = EventBus(config)

    return TigerMotorsEnvironment(config=config, bus=bus)


def create_environment_for_testing(
    config: dict[str, Any] | None = None, bus: EventBus | None = None
) -> TigerMotorsEnvironment:
    """
    Factory function for creating a TigerMotorsEnvironment for testing purposes.

    Provides minimal default configuration suitable for unit tests.
    All dependencies can be overridden for mocking.

    Args:
        config: Optional configuration dictionary. If None, uses minimal test defaults.
        bus: Optional EventBus instance. If None, creates EventBus with test config.

    Returns:
        TigerMotorsEnvironment: Environment configured for testing.

    Example:
        # Use with default test config
        env = create_environment_for_testing()

        # Use with mock bus
        mock_bus = MockEventBus()
        env = create_environment_for_testing(bus=mock_bus)
    """
    # Minimal test configuration
    test_config = config or {
        "mqtt": {
            "host": "localhost",
            "port": 1883,
            "keepalive": 60,
            "username": None,
            "password": None,
        },
        "production": {"target_takt_time": 75, "target_cycle_time": 60},
        "facility": {
            "total_workstations": 3,  # Reduced for faster tests
            "cells": 1,
            "workstations_per_cell": 3,
        },
        "performance": {
            "eventbus_tick_interval": 0.1,  # Slower for tests
            "gui_update_interval": 0.1,
            "state_stability_delay": 0.01,
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

    # Create EventBus if not provided
    if bus is None:
        bus = EventBus(test_config)

    return TigerMotorsEnvironment(config=test_config, bus=bus)
