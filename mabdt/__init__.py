"""mabdt — Multi-Agent-Based Digital Twin Engine.

A reusable Python framework for building manufacturing digital twins under
the MABDT architecture (Katsigiannis 2025). The package implements the four
engine components described in Section 3 of the JIM paper:

  - simulation_environment: agent lifecycle and population orchestration
  - communication_kernel: MQTT boundary, event bus, processor dispatch
  - interface_layer: thread-safe, DTO-only external API
  - services: independent service Protocol for sidecars (scanners, bridges, ...)

The package is deployment-agnostic. To build a digital twin for a specific
facility, subclass the framework's base classes (Agent, StateMachineAgent,
CommunicationAgent, Environment, SimulationInterface) and supply the
deployment's TopicProcessors, DTOs, and Queries. See examples/toy_line/ for
a minimal end-to-end deployment.
"""

__version__ = "0.1.0"

from mabdt.agent.base import Agent
from mabdt.agent.statemachine import StateMachineAgent
from mabdt.communication_kernel.communication_agent import CommunicationAgent
from mabdt.communication_kernel.event_bus import EventBus
from mabdt.communication_kernel.processor import TopicProcessor
from mabdt.communication_kernel.protocol import (
    InMemoryProtocol,
    MessagingProtocol,
    MqttProtocol,
)
from mabdt.exceptions import (
    AgentError,
    CommunicationError,
    ConfigurationError,
    MABDTException,
    SimulationError,
)
from mabdt.interface_layer.dto import DTO
from mabdt.interface_layer.query import Query
from mabdt.interface_layer.simulation_interface import SimulationInterface
from mabdt.protocols import MessageHandler, Pausable, Publisher, Stoppable
from mabdt.services.base import IndependentService
from mabdt.simulation_environment.environment import Environment
from mabdt.simulation_environment.population import AgentPopulation
from mabdt.utils.state_timer import StateTimer

__all__ = [
    "Agent",
    "AgentError",
    "AgentPopulation",
    "CommunicationAgent",
    "CommunicationError",
    "ConfigurationError",
    "DTO",
    "Environment",
    "EventBus",
    "InMemoryProtocol",
    "IndependentService",
    "MABDTException",
    "MessageHandler",
    "MessagingProtocol",
    "MqttProtocol",
    "Pausable",
    "Publisher",
    "Query",
    "SimulationError",
    "SimulationInterface",
    "StateMachineAgent",
    "StateTimer",
    "Stoppable",
    "TopicProcessor",
]
