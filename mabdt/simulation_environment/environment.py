"""Environment — declarative orchestrator for agent populations.

Maps to JIM §3.1 "Environment Orchestrator". The engine holds a set of agent
populations (one per DT-agent type), the communication agent that bridges
the physical layer, and the production-tracking lifecycle.

Deployments subclass Environment and use the declarative API in `_declare()`:

    class MyEnvironment(mabdt.Environment):
        def _declare(self) -> None:
            self.register_population(
                name="workstations",
                factory=lambda ws_id, bus: WorkstationAgent(ws_id, bus),
                ids=[f"WS{i}" for i in range(1, 16)],
            )
            self.register_singleton(
                name="inspection_station",
                factory=lambda bus: InspectionStationAgent(bus),
            )
            comm = MyCommAgent(self.bus, ...)
            self.register_messaging(comm)

The base class walks the registered populations to construct agents on
`initialize()`, drive lifecycle on `start_production()` / `stop_production()`,
and tear them down on `shutdown()`. Deployment-specific policy (e.g.
sending a `prod_start` message only to a particular population) goes in
the `on_production_started(self)` / `on_production_stopped(self)` hooks.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Any

from mabdt.agent.base import Agent
from mabdt.communication_kernel.communication_agent import CommunicationAgent
from mabdt.communication_kernel.event_bus import EventBus
from mabdt.exceptions import SimulationError
from mabdt.simulation_environment.population import AgentPopulation
from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


# Internal registration records — declarative metadata before initialize() runs.
class _PopulationSpec:
    def __init__(
        self,
        name: str,
        factory: Callable[[str, EventBus], Agent],
        ids: list[str],
        paused: bool,
    ) -> None:
        self.name = name
        self.factory = factory
        self.ids = ids
        self.paused = paused


class _SingletonSpec:
    def __init__(
        self,
        name: str,
        factory: Callable[[EventBus], Agent],
        paused: bool,
    ) -> None:
        self.name = name
        self.factory = factory
        self.paused = paused


class Environment:
    """Base class for deployment-specific simulation environments.

    Args:
        config: Configuration dict. Required keys are deployment-defined.
        bus: Optional EventBus instance. If None, one is created from `config`.
    """

    def __init__(
        self,
        config: dict[str, Any],
        bus: EventBus | None = None,
    ) -> None:
        self.config = config
        self.bus = bus if bus is not None else EventBus(config)

        self._populations: dict[str, AgentPopulation] = {}
        self._singletons: dict[str, Agent] = {}
        self.comm_agent: CommunicationAgent | None = None

        self._population_specs: list[_PopulationSpec] = []
        self._singleton_specs: list[_SingletonSpec] = []

        self.tracking_production = False
        self._initialized = False
        self._lock = threading.RLock()

    # --- Declarative registration API (called from _declare) ---

    def register_population(
        self,
        name: str,
        factory: Callable[[str, EventBus], Agent],
        ids: Iterable[str],
        paused: bool = True,
    ) -> None:
        """Declare a population of agents of one type.

        Recorded as a spec; agents are not constructed until `initialize()`.
        This separation ensures the full set of populations is known before
        any agent thread starts (avoids `find_agent` race conditions).
        """
        if self._initialized:
            raise SimulationError(
                "Cannot register population after initialize()",
                error_code="ENV_ALREADY_INITIALIZED",
            )
        self._population_specs.append(_PopulationSpec(name, factory, list(ids), paused))

    def register_singleton(
        self,
        name: str,
        factory: Callable[[EventBus], Agent],
        paused: bool = True,
    ) -> None:
        """Declare a single-instance agent (e.g. an inspection station)."""
        if self._initialized:
            raise SimulationError(
                "Cannot register singleton after initialize()",
                error_code="ENV_ALREADY_INITIALIZED",
            )
        self._singleton_specs.append(_SingletonSpec(name, factory, paused))

    def register_messaging(self, comm_agent: CommunicationAgent) -> None:
        """Bind the communication agent that bridges to the physical layer."""
        self.comm_agent = comm_agent

    # --- Overridable hooks ---

    def _declare(self) -> None:
        """Override point: register all populations and the comm agent."""
        raise NotImplementedError("Subclasses must implement _declare()")

    def on_production_started(self) -> None:
        """Hook called after the generic resume during start_production.

        Default no-op. Override to emit deployment-specific events (e.g.
        broadcast `prod_start` to a particular population).
        """
        ...

    def on_production_stopped(self) -> None:
        """Hook called after the generic pause during stop_production."""
        ...

    # --- Lifecycle ---

    def initialize(self) -> None:
        """Build all agents and wire them to the bus. Idempotent."""
        with self._lock:
            if self._initialized:
                return

            # 1. Let the subclass declare populations and comm agent.
            self._declare()

            # 2. Build populations.
            for spec in self._population_specs:
                pop = AgentPopulation(spec.name)
                for agent_id in spec.ids:
                    agent = spec.factory(agent_id, self.bus)
                    if spec.paused:
                        agent.pause()
                    pop.add(agent_id, agent)
                self._populations[spec.name] = pop
                logger.info(f"Built population '{spec.name}' with {len(pop)} agents")

            # 3. Build singletons.
            for spec in self._singleton_specs:
                agent = spec.factory(self.bus)
                if spec.paused:
                    agent.pause()
                self._singletons[spec.name] = agent
                logger.info(f"Built singleton '{spec.name}'")

            # 4. Start the comm agent last, after every population is registered,
            #    so that no inbound message can find an unbuilt agent.
            if self.comm_agent is not None:
                self.comm_agent.start()

            self._initialized = True

    def start_production(self) -> bool:
        with self._lock:
            if not self._initialized:
                raise SimulationError(
                    "Environment not initialized",
                    error_code="ENV_NOT_INITIALIZED",
                )
            if self.tracking_production:
                return True

            self.tracking_production = True

            # Resume every population and singleton.
            for pop in self._populations.values():
                pop.resume_all()
            for agent in self._singletons.values():
                agent.resume()

            # Deployment-specific events.
            self.on_production_started()
            return True

    def stop_production(self) -> bool:
        with self._lock:
            if not self.tracking_production:
                return True

            self.tracking_production = False

            self.on_production_stopped()

            for pop in self._populations.values():
                pop.pause_all()
            for agent in self._singletons.values():
                agent.pause()
            return True

    def shutdown(self) -> None:
        with self._lock:
            self.tracking_production = False
            for pop in self._populations.values():
                pop.stop_all()
            for agent in self._singletons.values():
                agent.stop()
            if self.comm_agent is not None:
                self.comm_agent.stop()
            self.bus.shutdown()
            self._initialized = False

    # --- Accessors ---

    def is_initialized(self) -> bool:
        with self._lock:
            return self._initialized

    def get_population(self, name: str) -> AgentPopulation:
        try:
            return self._populations[name]
        except KeyError as e:
            raise SimulationError(
                f"No population named '{name}'",
                error_code="ENV_NO_SUCH_POPULATION",
                context={"name": name, "available": list(self._populations)},
            ) from e

    def get_singleton(self, name: str) -> Agent:
        try:
            return self._singletons[name]
        except KeyError as e:
            raise SimulationError(
                f"No singleton named '{name}'",
                error_code="ENV_NO_SUCH_SINGLETON",
                context={"name": name, "available": list(self._singletons)},
            ) from e
