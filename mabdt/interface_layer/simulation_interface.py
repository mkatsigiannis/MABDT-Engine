"""SimulationInterface — thread-safe facade for external consumers.

Maps to JIM §3.3 "Interface Layer". Exposes lifecycle methods (initialize,
start production, stop production, shutdown) and serves as the base class
for deployment-specific facades that add domain query methods.

Holds an internal RLock so only one request runs at a time; this prevents a
data query from running while a lifecycle call is in progress and lets
multiple consumers (GUI refresh timer, CLI command, RAG context build) read
the engine state without races.
"""

from __future__ import annotations

import threading
import time

from mabdt.exceptions import SimulationError
from mabdt.simulation_environment.environment import Environment
from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class SimulationInterface:
    """Lock-protected facade over an Environment.

    Subclasses add domain-specific query methods (e.g. `get_workstation_status`)
    that delegate to deployment-specific Query/converter helpers, always
    while holding `self._lock`.

    Args:
        environment: Optional pre-built Environment for dependency injection
                     and testing. If None, subclasses override `initialize()`
                     to build one (typically via `mabdt.create_environment`).
    """

    def __init__(self, environment: Environment | None = None) -> None:
        self._environment = environment
        self._init_time = time.time()
        self._error_count = 0
        self._lock = threading.RLock()

    # --- Lifecycle ---

    def initialize(self, config_path: str | None = None) -> bool:
        """Initialize the environment and any query helpers.

        Subclasses typically override to construct an Environment from a
        config path before calling this base implementation (or replace
        the base with their own logic).
        """
        with self._lock:
            if self._environment is None:
                raise SimulationError(
                    "No environment provided; subclasses must build one before "
                    "calling SimulationInterface.initialize()",
                    error_code="INTERFACE_NO_ENVIRONMENT",
                )
            self._environment.initialize()
            self._setup_queries()
            return True

    def shutdown(self) -> None:
        """Tear down the environment and clear cached query helpers."""
        with self._lock:
            if self._environment is not None:
                self._environment.shutdown()

    def is_initialized(self) -> bool:
        with self._lock:
            return self._environment is not None and self._environment.is_initialized()

    def start_production(self) -> bool:
        with self._lock:
            self._validate_environment()
            return self._environment.start_production()

    def stop_production(self) -> bool:
        with self._lock:
            self._validate_environment()
            return self._environment.stop_production()

    def is_production_running(self) -> bool:
        with self._lock:
            self._validate_environment()
            return self._environment.tracking_production

    # --- Direct environment access (escape hatch) ---

    def get_environment(self) -> Environment:
        """Return the underlying Environment.

        Prefer query methods exposed by deployment subclasses. This method
        exists as an escape hatch for debugging panels (e.g. an agent
        inspector) and must not be used by widgets in the normal display
        path.
        """
        with self._lock:
            self._validate_environment()
            return self._environment

    # --- Helpers for subclasses ---

    def _validate_environment(self) -> None:
        """Raise SimulationError if the environment is not ready."""
        if self._environment is None:
            raise SimulationError(
                "Environment not initialized",
                error_code="INTERFACE_NOT_INITIALIZED",
            )
        if not self._environment.is_initialized():
            raise SimulationError(
                "Environment not fully initialized",
                error_code="INTERFACE_NOT_READY",
            )

    def _setup_queries(self) -> None:
        """Override point: construct deployment-specific query helpers.

        Called from `initialize()` after the environment is ready. Default
        is a no-op.
        """
        ...

    # --- Telemetry ---

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._init_time

    @property
    def error_count(self) -> int:
        return self._error_count
