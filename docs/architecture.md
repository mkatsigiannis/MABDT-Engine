# Architecture

This document maps the code in `mabdt/` and `tiger_motors_dt/` to the four
engine components defined in *Multi-Agent-Based Digital Twin Engine for
Manufacturing Operations* (Katsigiannis, JIM, under review). Read it
alongside [`../examples/toy_line/main.py`](../examples/toy_line/main.py),
which exercises every concept here at minimal scale.

## Package layout

```
mabdt/                            engine, deployment-agnostic
  agent/                            Agent, StateMachineAgent (§3.1)
  simulation_environment/           Environment, AgentPopulation (§3.1)
  communication_kernel/             CommunicationAgent, TopicProcessor,
                                    MessagingProtocol, EventBus (§3.2)
  interface_layer/                  SimulationInterface, DTO, Query (§3.3)
  services/                         IndependentService Protocol (§3.4)

tiger_motors_dt/                  reference deployment on top of mabdt
  agents/                           CarAgent, WorkstationAgent,
                                    InspectionStationAgent, TigerCommAgent
  agents/processors/                BarcodeProcessor, PLCProcessor,
                                    InspectionProcessor
  simulation/                       TigerMotorsEnvironment, TigerMotorsInterface,
                                    DTOs, Query helpers
  interfaces/gui/                   PySide6 GUI (widgets, managers, controllers)
  interfaces/cli/                   text console
  services/                         OPC UA bridge, barcode scanner service
  rag_system/, llm_service/         LLM chat with retrieval over DTOs
```

## §3.1 Simulation Environment

`mabdt.Environment` orchestrates an agent population's lifecycle. A
deployment subclasses it and implements `_declare()`, where it registers
populations and the messaging agent:

```python
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
        self.register_messaging(MyCommAgent(self.bus, ...))
```

The base class walks the registered specs in `initialize()`, builds agents,
starts the comm agent last (so no inbound message can find an unbuilt
agent), and drives `start_production()` / `stop_production()` / `shutdown()`.
Deployment-specific events (e.g. broadcasting `prod_start` to a particular
population) go in the `on_production_started()` / `on_production_stopped()`
hooks.

Agents subclass `mabdt.Agent` (a basic message loop) or
`mabdt.StateMachineAgent` (which adds a hierarchical state machine via the
`transitions` library, message dedup, a processing guard, and a pause-aware
FIFO inbox).

## §3.2 Communication Kernel

`mabdt.CommunicationAgent` is the boundary between the physical layer and
the rest of the engine. A subclass registers one or more `TopicProcessor`s;
the base class asks each processor for its subscription filters, applies
them to the underlying `MessagingProtocol` (deduplicating shared filters),
and dispatches inbound messages to the matching processor.

Two protocols ship with the engine:

- **`MqttProtocol`** — paho-mqtt client for production use.
- **`InMemoryProtocol`** — dict-of-subscribers backend for headless tests
  and the toy example.

A `TopicProcessor` declares its filters and a `process()` method:

```python
class BarcodeProcessor(mabdt.TopicProcessor):
    @property
    def subscriptions(self) -> list[tuple[str, int]]:
        return [("scanner/+", 1)]

    def process(self, topic: str, payload: bytes, context: Any) -> None:
        ...
```

The `gate` callable on `CommunicationAgent` lets a deployment block inbound
traffic when the simulation is not tracking production. Tiger Motors wires
it to `environment.tracking_production` so cold-start scans cannot
mutate state.

Outbound publishes go through the internal `EventBus`: a DT agent publishes
a `{"topic", "payload", "qos"}` message on the `mqtt` bus topic, and the
communication agent forwards it to the protocol. The rest of the engine
never talks to the broker directly.

## §3.3 Interface Layer

`mabdt.SimulationInterface` is a lock-protected facade over an
`Environment`. External callers (GUI, CLI, RAG context collector, web APIs)
interact only through this interface. The single `RLock` serializes
queries against lifecycle calls so a GUI refresh cannot tear during
`start_production()`.

A subclass adds domain queries. Each query takes the lock and returns
immutable `DTO` instances — frozen dataclasses that consumers cannot
mutate. Tiger Motors defines `CarStatus`, `WorkstationStatus`,
`InspectionStationStatus`, `ProductionMetrics`, and `SystemStatus`.

The DTO-only boundary is what keeps the GUI decoupled from the agents:
widgets call `iface.get_workstation(...)`, never reach into agent
internals. An escape hatch (`get_environment()`) exists for the agent
inspector debug panel but is not used in the normal display path.

## §3.4 Services (application-layer sidecars)

`IndependentService` is a `typing.Protocol`, not an abstract base class,
so PySide6 services that inherit `QObject` can satisfy it without MRO
friction. They just need `start()`, `stop()`, and `is_connected()`.

Two long-running sidecars satisfy it in the Tiger deployment:

- **OPC UA bridge** — subscribes to KepServerEX nodes, republishes the
  values as `plc/<tag>` MQTT messages.
- **Barcode scanner service** — logs every MQTT scan to an Excel file in
  `diagrams_and_data/` and announces itself on the network via Zeroconf.

Both services run alongside the engine and never see agent internals.

## Runtime data flow

```
physical layer (PLCs, scanners, LEDs)
      |
      v  MQTT
mabdt.CommunicationAgent --> TopicProcessor.process(...) --> Agent.receive(...)
                                                                 |
                                                                 v
                                                          StateMachineAgent
                                                                 |
                                                                 v
                                                  EventBus.publish(...)  <----+
                                                                              |
SimulationInterface --(DTOs)--> GUI / CLI / RAG -----------------------------+
```

Inbound messages enter through `CommunicationAgent`, are routed by
processors, and update agent state through the inbox queue. The interface
layer snapshots that state into DTOs on demand. Outbound publishes (LED
toggles, MING (MQTT, InfluxDB, Node-RED, Grafana) dashboard topics, OPC UA writes) leave through the same
protocol.

## Where to look next

- [`../examples/toy_line/main.py`](../examples/toy_line/main.py) — every
  concept above in one file.
- [`../mabdt/__init__.py`](../mabdt/__init__.py) — the engine's full public
  API surface.
- [`../tiger_motors_dt/simulation/environment.py`](../tiger_motors_dt/simulation/environment.py)
  — the Tiger Motors environment subclass with declarative population
  registration.
- [`../tiger_motors_dt/agents/comm_agent.py`](../tiger_motors_dt/agents/comm_agent.py)
  — Tiger's `CommunicationAgent` and processor wiring.
