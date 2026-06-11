"""Exception hierarchy for mabdt.

All engine-raised exceptions derive from MABDTException, giving deployments a
single base to catch when they want to handle engine failures uniformly.
"""

from __future__ import annotations

from typing import Any


class MABDTException(Exception):
    """Base class for all mabdt engine errors.

    Carries an optional error code and a context dict for structured logging
    or upstream telemetry. Use subclasses for specific failure categories;
    raise MABDTException directly only for engine errors that don't fit a
    more specific subclass.
    """

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": type(self).__name__,
            "message": self.message,
            "error_code": self.error_code,
            "context": self.context,
        }


class ConfigurationError(MABDTException):
    """Configuration loading, validation, or access failed."""


class SimulationError(MABDTException):
    """Simulation environment lifecycle or population error."""


class CommunicationError(MABDTException):
    """Communication kernel error: MQTT, event bus, or processor dispatch."""


class AgentError(MABDTException):
    """Agent lifecycle or message-handling error."""
