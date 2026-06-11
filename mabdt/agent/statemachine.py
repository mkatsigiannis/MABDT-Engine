"""StateMachineAgent — Agent with hierarchical statechart and message dedup.

Maps to JIM §3.1 "Agent Base Class" extensions: duplicate-message detection
(debouncing) and a standardized handle() flow that normalizes inbound
messages and triggers the matching state-machine event.

The §3.1 "processing guard" semantic (only one state transition at a time
within an agent) is provided by the single-threaded inbox loop on the
Agent base class: messages are pulled and dispatched serially in the
agent's own thread, so two messages arriving in quick succession cannot
race against each other. No additional lock is needed.

The state machine itself (`states`, `transitions`, history markers) is
declared by subclasses using the `transitions` library. This base provides
the machinery around it. Subclasses typically override `create_message_key`
(if dedup must include context such as the current workstation) or
`process_event` (if extra logic is needed before the transition).
"""

from __future__ import annotations

import time
from typing import Any

from mabdt.agent.base import Agent
from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class StateMachineAgent(Agent):
    """Agent with hierarchical statechart + message dedup.

    Args:
        name: Unique identifier for the agent.
        bus: EventBus (or Publisher-compatible) used for outbound messages.
    """

    def __init__(self, name: str, bus: Any) -> None:
        super().__init__(name, bus)

        # Duplicate-message detection
        self.last_message: str = ""
        self.last_message_time: float = 0.0

        # State machine is initialized by subclasses
        self.machine: Any | None = None
        self.state: str | None = None

    # --- Duplicate-message detection ---

    def is_duplicate_message(self, message_key: str, timeout: float = 1.0) -> bool:
        """Return True if `message_key` was seen within the timeout window."""
        current_time = time.time()
        if self.last_message == message_key and current_time - self.last_message_time < timeout:
            return True
        self.last_message = message_key
        self.last_message_time = current_time
        return False

    def create_message_key(self, event_type: str, message_dict: dict) -> str:
        """Build the dedup key from an inbound event. Override for context."""
        return event_type

    # --- Message normalization ---

    def normalize_message(self, msg: Any) -> tuple[str | None, dict | None]:
        """Convert any inbound shape into a (event_type, dict) tuple."""
        if isinstance(msg, str):
            return msg, {"type": msg}
        elif isinstance(msg, dict) and "type" in msg:
            return msg["type"], msg
        else:
            logger.warning(f"[{self.name}] Unknown message format: {msg}")
            return None, None

    # --- State transitions ---

    def trigger_state_event(self, event_type: str) -> bool:
        """Safely trigger a state machine event by name.

        Looks up the trigger method on `self` (the `transitions` library
        attaches them at machine construction time) and calls it. Returns
        True on success, False if the trigger doesn't exist or raises.
        """
        try:
            if hasattr(self, event_type):
                trigger_method = getattr(self, event_type)
                if callable(trigger_method):
                    trigger_method()
                    logger.debug(f"[{self.name}] Triggered {event_type} -> {self.state}")
                    return True
            logger.warning(f"[{self.name}] No trigger for event: {event_type}")
            return False
        except Exception as e:
            logger.error(f"[{self.name}] Error triggering {event_type}: {e}")
            return False

    def process_event(self, event_type: str, message_dict: dict) -> None:
        """Override point: pre-transition logic, then trigger_state_event."""
        self.trigger_state_event(event_type)

    # --- Standard handle() flow ---

    def handle(self, msg: Any) -> None:
        """Normalize, dedup, then dispatch to process_event."""
        try:
            event_type, message_dict = self.normalize_message(msg)
            if event_type is None:
                return
            message_key = self.create_message_key(event_type, message_dict)
            if self.is_duplicate_message(message_key):
                return
            self.process_event(event_type, message_dict)
        except Exception as e:
            logger.error(f"[{self.name}] Error handling message {msg}: {e}")

    # --- State-machine config ---

    def get_state_machine_config(self) -> dict:
        """Return the transitions-library config dict for the SM constructor."""
        return {
            "ignore_invalid_triggers": True,
            "auto_transitions": False,
        }
