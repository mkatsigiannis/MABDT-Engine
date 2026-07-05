"""IndependentService — structural Protocol for sidecar services.

A service must expose start/stop/is_connected so the deployment's lifecycle
code can manage it uniformly alongside the engine. Using a Protocol (rather
than an ABC) lets services inherit from framework bases like PySide6.QObject
without diamond-MRO problems.

Typical service responsibilities (JIM paper: "Independent Services" subsection):
  - manage its own configuration
  - manage its own connection to the broker
  - manage reconnect logic when the upstream link drops
  - optionally respond bidirectionally to engine requests
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IndependentService(Protocol):
    """Structural Protocol for services running alongside the engine."""

    def start(self) -> None:
        """Connect to upstreams and begin work."""

    def stop(self) -> None:
        """Disconnect and shut down cleanly."""

    def is_connected(self) -> bool:
        """Report whether the service's upstream link is currently healthy."""
