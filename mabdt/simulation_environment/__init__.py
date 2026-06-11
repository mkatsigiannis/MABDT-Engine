"""Simulation Environment (JIM §3.1).

Holds the agent populations, the start-up logic, and the bindings between
the agents and the communication kernel.
"""

from mabdt.simulation_environment.environment import Environment
from mabdt.simulation_environment.factory import create_environment
from mabdt.simulation_environment.population import AgentPopulation

__all__ = ["AgentPopulation", "Environment", "create_environment"]
