"""Smoke tests for mabdt.Environment and mabdt.SimulationInterface.

Exercises the declarative population API (Phase 2 implementation), the
production-lifecycle hooks, and the interface-layer facade.
"""

from __future__ import annotations

import time

import pytest

from mabdt import Agent, Environment, SimulationError, SimulationInterface


class _Echo(Agent):
    def __init__(self, name, bus):
        super().__init__(name, bus)
        self.log: list = []

    def handle(self, msg):
        self.log.append(msg)


def _short_config() -> dict:
    return {"performance": {"agent_inbox_timeout": 0.05}}


class _PopEnv(Environment):
    def _declare(self) -> None:
        self.register_population(
            "echo",
            factory=lambda aid, bus: _Echo(aid, bus),
            ids=["e1", "e2", "e3"],
            paused=True,
        )


class _SingletonEnv(Environment):
    def _declare(self) -> None:
        self.register_singleton("solo", lambda bus: _Echo("solo", bus), paused=True)


class _HookedEnv(Environment):
    def __init__(self, config, bus=None):
        super().__init__(config, bus)
        self.started_calls = 0
        self.stopped_calls = 0

    def _declare(self) -> None:
        self.register_population("p", lambda aid, bus: _Echo(aid, bus), ["a"])

    def on_production_started(self):
        self.started_calls += 1

    def on_production_stopped(self):
        self.stopped_calls += 1


# ----- Environment: populations + lifecycle ---------------------------------


def test_environment_builds_population_in_paused_state():
    env = _PopEnv(_short_config())
    env.initialize()
    pop = env.get_population("echo")
    assert len(pop) == 3
    assert all(a.paused for a in pop)
    env.shutdown()


def test_environment_start_production_resumes_population_and_drains_inbox():
    env = _PopEnv(_short_config())
    env.initialize()
    for a in env.get_population("echo"):
        a.receive({"type": "queued"})
    time.sleep(0.15)
    # Paused → nothing processed yet
    for a in env.get_population("echo"):
        assert a.log == []
    env.start_production()
    time.sleep(0.15)
    for a in env.get_population("echo"):
        assert a.log == [{"type": "queued"}]
    env.shutdown()


def test_environment_stop_production_pauses_population():
    env = _PopEnv(_short_config())
    env.initialize()
    env.start_production()
    assert env.tracking_production is True
    env.stop_production()
    assert env.tracking_production is False
    for a in env.get_population("echo"):
        assert a.paused
    env.shutdown()


def test_register_population_after_initialize_raises():
    env = _PopEnv(_short_config())
    env.initialize()
    with pytest.raises(SimulationError):
        env.register_population("late", lambda i, b: _Echo(i, b), ["x"])
    env.shutdown()


def test_get_population_raises_for_unknown_name():
    env = _PopEnv(_short_config())
    env.initialize()
    with pytest.raises(SimulationError):
        env.get_population("does-not-exist")
    env.shutdown()


def test_environment_singletons_get_built_and_managed():
    env = _SingletonEnv(_short_config())
    env.initialize()
    agent = env.get_singleton("solo")
    assert agent.paused
    env.start_production()
    assert not agent.paused
    env.shutdown()


def test_lifecycle_hooks_fire_after_population_walk():
    env = _HookedEnv(_short_config())
    env.initialize()
    assert env.started_calls == 0
    env.start_production()
    assert env.started_calls == 1
    env.stop_production()
    assert env.stopped_calls == 1
    # Idempotent re-starts/stops don't double-fire.
    env.start_production()
    env.start_production()
    assert env.started_calls == 2
    env.shutdown()


# ----- SimulationInterface --------------------------------------------------


def test_simulation_interface_lifecycle_against_an_env():
    env = _PopEnv(_short_config())
    iface = SimulationInterface(environment=env)
    assert iface.is_initialized() is False
    iface.initialize()
    assert iface.is_initialized() is True
    assert iface.is_production_running() is False
    iface.start_production()
    assert iface.is_production_running() is True
    iface.stop_production()
    assert iface.is_production_running() is False
    iface.shutdown()


def test_simulation_interface_blocks_queries_before_initialize():
    iface = SimulationInterface(environment=_PopEnv(_short_config()))
    # Don't call initialize(); accessing a lifecycle method should fail.
    with pytest.raises(SimulationError):
        iface.start_production()
    iface.shutdown()


def test_simulation_interface_get_environment_returns_the_env():
    env = _PopEnv(_short_config())
    iface = SimulationInterface(environment=env)
    iface.initialize()
    assert iface.get_environment() is env
    iface.shutdown()
