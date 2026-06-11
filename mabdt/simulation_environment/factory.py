"""Factory helpers for constructing an Environment.

Convenience wrapper for the common "load config then instantiate" pattern.
Deployments typically expose their own factory that returns the subclass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mabdt.communication_kernel.event_bus import EventBus
from mabdt.simulation_environment.environment import Environment
from mabdt.utils.config import load_config


def create_environment(
    environment_cls: type[Environment],
    config: dict[str, Any] | None = None,
    config_path: str | Path | None = None,
    bus: EventBus | None = None,
) -> Environment:
    """Construct an Environment subclass with the given config.

    Exactly one of `config` or `config_path` must be provided.

    Args:
        environment_cls: A subclass of Environment.
        config: Configuration dict (deployment-defined schema).
        config_path: Path to a JSON file to load instead.
        bus: Optional pre-built EventBus. If None, one is created.

    Returns:
        An uninitialized environment. Caller must call `.initialize()`.
    """
    if (config is None) == (config_path is None):
        raise ValueError("Exactly one of `config` or `config_path` must be provided")
    if config_path is not None:
        config = load_config(config_path)
    assert config is not None  # for type checkers
    return environment_cls(config=config, bus=bus)
