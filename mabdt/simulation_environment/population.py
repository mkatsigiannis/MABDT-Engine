"""AgentPopulation — typed collection of agents of one type."""

from __future__ import annotations

from collections.abc import Iterator

from mabdt.agent.base import Agent


class AgentPopulation:
    """A homogeneous collection of agents keyed by ID.

    Wraps a Dict[str, Agent] with lifecycle methods so the Environment can
    manipulate whole populations uniformly.

    Args:
        name: Population name (e.g. "workstations", "cars").
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._agents: dict[str, Agent] = {}

    # --- Membership ---

    def add(self, agent_id: str, agent: Agent) -> None:
        if agent_id in self._agents:
            raise ValueError(f"Agent '{agent_id}' already in population '{self.name}'")
        self._agents[agent_id] = agent

    def remove(self, agent_id: str) -> None:
        agent = self._agents.pop(agent_id, None)
        if agent is not None:
            agent.stop()

    def get(self, agent_id: str) -> Agent:
        return self._agents[agent_id]

    def contains(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def ids(self) -> list[str]:
        return list(self._agents.keys())

    def __iter__(self) -> Iterator[Agent]:
        return iter(self._agents.values())

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents

    # --- Lifecycle ---

    def pause_all(self) -> None:
        for agent in self._agents.values():
            agent.pause()

    def resume_all(self) -> None:
        for agent in self._agents.values():
            agent.resume()

    def stop_all(self) -> None:
        for agent in self._agents.values():
            agent.stop()

    def broadcast(self, msg: dict) -> None:
        """Deliver `msg` to every agent's inbox."""
        for agent in self._agents.values():
            agent.receive(msg)
