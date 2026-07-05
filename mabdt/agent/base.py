"""Agent base class — autonomous threaded agent with private inbox.

Maps to the JIM paper's "Simulation Environment" section. Each agent runs in its own daemon thread
with a queue.Queue inbox. Other components deposit messages without blocking,
and the agent processes them at its own pace. Pause/resume/stop control the
lifecycle; messages accumulate in the inbox while paused.

The constructor reads `performance.agent_inbox_timeout` from the bus's
config (via the optional `get_config_value` duck-typed method), falling
back to 0.1 s. This keeps the agent decoupled from any particular bus
implementation while letting deployments tune inbox latency.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mabdt.utils.logging import get_logger

if TYPE_CHECKING:
    from mabdt.protocols import MessageHandler, Publisher

logger = get_logger(__name__)


class Agent:
    """Autonomous, threaded agent with a private inbox.

    Subclasses override `handle(msg)` to react to incoming events. The base
    class provides the inbox, the run loop, and lifecycle control.

    Args:
        name: Unique identifier for the agent.
        bus: Publisher (event bus) used for outbound messages.
    """

    name: str
    running: bool
    paused: bool

    def __init__(self, name: str, bus: Publisher) -> None:
        self.name: str = name
        self.bus: Publisher = bus

        # Configurable inbox timeout via the bus's optional get_config_value.
        if hasattr(bus, "get_config_value"):
            self._inbox_timeout = bus.get_config_value("performance", "agent_inbox_timeout", 0.1)
        else:
            self._inbox_timeout = 0.1

        self._inbox: queue.Queue = queue.Queue()
        self._population: list[MessageHandler] | None = None

        self.running = True
        self.paused = False

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    # --- Outbound ---

    def send(self, topic: str, msg: Any) -> None:
        """Publish a message on the bus."""
        self.bus.publish(topic, msg)

    # --- Inbound ---

    def receive(self, evt: dict) -> None:
        """Place an event in the agent's private inbox (non-blocking)."""
        self._inbox.put(evt)

    def handle(self, msg: Any) -> None:
        """Override point: subclass logic for processing a message.

        Default implementation does nothing.
        """
        pass

    def _run_loop(self) -> None:
        """Main event processing loop running in the background thread.

        While paused, the loop idles without draining the inbox so messages
        accumulate until the agent resumes (matching the JIM paper: "messages
        accumulate in the queue but are not processed until the agent
        resumes"). Earlier drafts of this loop would `get()` then drop —
        that silently discarded events during pauses, contradicting the
        paper.

        Race handling: if pause() is called while the loop is blocked in
        get(), the get() can still return a message (it unblocks the moment
        an item arrives). To keep FIFO order across a pause/resume cycle,
        the message is stashed locally and processed FIRST when the agent
        next resumes, before pulling anything else from the inbox.

        Exceptions in `handle()` are logged but do not stop the loop.
        """
        stashed: Any = None
        while self.running:
            if self.paused:
                time.sleep(self._inbox_timeout)
                continue
            if stashed is not None:
                evt, stashed = stashed, None
                try:
                    self.handle(evt)
                except Exception as e:
                    logger.error(f"Error in agent {self.name}: {e}", exc_info=True)
                continue
            try:
                evt = self._inbox.get(timeout=self._inbox_timeout)
                if self.paused:
                    # Pause raced with our blocked get(). Hold the event
                    # locally; it will be the next one processed on resume.
                    stashed = evt
                    continue
                self.handle(evt)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in agent {self.name}: {e}", exc_info=True)

    # --- Lifecycle ---

    def pause(self) -> None:
        """Pause message processing. Inbox continues to accept messages."""
        self.paused = True

    def resume(self) -> None:
        """Resume message processing after pause."""
        self.paused = False

    def stop(self) -> None:
        """Shut the agent down cleanly. Drains and stops the worker thread."""
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    # --- Population helpers ---

    def set_population(self, population: list[MessageHandler]) -> None:
        """Wire this agent into a peer population for cross-agent discovery."""
        self._population = population

    def find_agent(self, condition: Callable[[MessageHandler], bool]) -> MessageHandler | None:
        """Return the first peer matching `condition`, or None."""
        if self._population is None:
            return None
        for agent in self._population:
            if condition(agent):
                return agent
        return None
