"""Query — abstract request that reads engine state and returns a DTO.

Deployments implement concrete Query subclasses for their domain (e.g.
GetWorkstationStatus, GetActiveCars, GetProductionMetrics). The
SimulationInterface routes calls through a Query object so the read path is
uniform and the lock is held for the duration of the execute() call.

Most simple read APIs can avoid creating a Query subclass and just expose a
method on the deployment's SimulationInterface subclass — Query is the
extension point when a deployment wants caller-supplied parameters or to
plug in additional read paths without modifying the interface base.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class Query(ABC, Generic[T]):
    """Abstract read request executed against the engine's agent populations.

    Returns:
        A DTO, a list of DTOs, or any immutable aggregate appropriate to the
        deployment's interface contract.
    """

    @abstractmethod
    def execute(self, environment: Any) -> T:
        """Read engine state and return a DTO-shaped result.

        Implementations should never mutate engine state and must produce
        an immutable result safe to hand to any caller.
        """
