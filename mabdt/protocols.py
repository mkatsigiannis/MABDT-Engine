"""Structural Protocols used across mabdt.

These are typing.Protocol declarations that describe the shape an object must
have to participate in a given role. Using Protocols (rather than abstract
base classes) avoids inheritance constraints — services and agents can satisfy
these contracts without subclassing, which matters when a deployment-specific
class already inherits from another framework base (e.g. Qt's QObject).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Stoppable(Protocol):
    """An object that can be cleanly stopped."""

    def stop(self) -> None: ...


@runtime_checkable
class Pausable(Protocol):
    """An object that can be paused and resumed."""

    def pause(self) -> None: ...

    def resume(self) -> None: ...


@runtime_checkable
class MessageHandler(Protocol):
    """An agent-like object that accepts events into a private inbox."""

    name: str
    running: bool
    paused: bool

    def receive(self, evt: dict) -> None: ...

    def handle(self, msg: dict) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def stop(self) -> None: ...


@runtime_checkable
class Publisher(Protocol):
    """A pub/sub bus that other components can publish to and subscribe from."""

    def publish(self, topic: str, message: Any) -> None: ...

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> None: ...
