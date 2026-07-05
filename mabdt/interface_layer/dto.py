"""DTO — frozen-dataclass base for read-only records.

Maps to the read-only records of the JIM paper's "Interface Layer" section. All data crossing the interface
boundary is immutable. Deployments define one DTO per kind of DT agent
(plus aggregate records for production metrics and system health) as a
frozen dataclass that inherits from this base — though inheritance is
optional; what matters is that they are frozen dataclasses.

The base is provided for taxonomy and tooling (`isinstance(x, DTO)` lets
consumers distinguish engine records from arbitrary data). It carries no
fields of its own.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DTO:
    """Marker base class for engine DTOs.

    Subclasses must be `@dataclass(frozen=True)` and contain only immutable
    field types (str, int, float, bool, tuple, frozenset, other DTOs, ...).
    """
