"""Toy assembly line — minimal end-to-end deployment built on mabdt.

This example demonstrates the four engine components from the JIM paper with the
smallest realistic deployment: two workstations, a stream of cars that
move through both stations, and a console summary at the end. No GUI,
no MQTT broker — the InMemoryProtocol stands in for the physical layer.

Reading this file top-to-bottom is the recommended introduction to
building a new deployment on mabdt. The shape mirrors the Tiger Motors
deployment in this repository but at ~250 lines instead of ~2,000.

Run with:

    python -m examples.toy_line.main
"""

from __future__ import annotations

import logging
import time
from typing import Any

from transitions.extensions import HierarchicalMachine

import mabdt

# ----- Constants ------------------------------------------------------------

NUM_WORKSTATIONS = 2
NUM_CARS = 5
WS_CYCLE_SECONDS = 0.3  # time the operator "spends" at each station
TICK_SECONDS = 0.05  # protocol tick between scans (sleep, not real time)


# ----- DT agents (deployment-specific statecharts) --------------------------


class ToyWorkstationAgent(mabdt.StateMachineAgent):
    """Two states: Idle and Busy. Each Busy entry counts a car served."""

    def __init__(self, name: str, bus: mabdt.EventBus) -> None:
        super().__init__(name, bus)
        self.cars_served = 0
        states = ["Idle", "Busy"]
        transitions = [
            {"trigger": "busy", "source": "Idle", "dest": "Busy"},
            {"trigger": "done", "source": "Busy", "dest": "Idle"},
        ]
        config = self.get_state_machine_config()
        self.machine = HierarchicalMachine(
            model=self, states=states, transitions=transitions, initial="Idle", **config
        )

    def on_enter_Busy(self) -> None:
        self.cars_served += 1


class ToyCarAgent(mabdt.StateMachineAgent):
    """Three states: WaitInQueue, InProgress, Finished."""

    def __init__(self, car_id: str, bus: mabdt.EventBus) -> None:
        super().__init__(f"Car-{car_id}", bus)
        self.car_id = car_id
        self.current_workstation: int = 0
        self.finished = False

        states = ["WaitInQueue", "InProgress", "Finished"]
        transitions = [
            {"trigger": "start", "source": "WaitInQueue", "dest": "InProgress"},
            {"trigger": "done", "source": "InProgress", "dest": "WaitInQueue"},
            {
                "trigger": "finish",
                "source": ["WaitInQueue", "InProgress"],
                "dest": "Finished",
            },
        ]
        config = self.get_state_machine_config()
        self.machine = HierarchicalMachine(
            model=self,
            states=states,
            transitions=transitions,
            initial="WaitInQueue",
            **config,
        )

    def on_enter_Finished(self) -> None:
        self.finished = True


# ----- Deployment-specific routing (the JIM paper's "rule-based pipeline") --


class ToyBarcodeProcessor(mabdt.TopicProcessor):
    """Routes `scanner/WS<n>` topics to ToyCarAgent + ToyWorkstationAgent.

    Implements a stripped-down version of JIM Algorithm 1:
      - unknown car id at any WS:        create the car
      - known car id at the same WS:     emit `done` (and `finish` if last)
      - known car id at a different WS:  the car has moved (re-emit `busy`)
    """

    @property
    def subscriptions(self) -> list[tuple[str, int]]:
        return [("scanner/+", 1)]

    def process(self, topic: str, payload: bytes, context: Any) -> None:
        env = context  # type: ToyLineEnvironment
        ws_id = topic.split("/")[1]
        if not ws_id.startswith("WS"):
            return
        ws_num = int(ws_id[2:])
        car_id = payload.decode() if isinstance(payload, bytes) else str(payload)

        car = env.cars.get(car_id)
        ws = env.workstations.get(ws_id)
        if ws is None:
            return

        if car is None:
            # New car
            new_car = ToyCarAgent(car_id, env.bus)
            new_car.current_workstation = ws_num
            env.cars[car_id] = new_car
            ws.receive({"type": "busy"})
            new_car.receive({"type": "start"})
            return

        if car.current_workstation == ws_num:
            ws.receive({"type": "done"})
            car.receive({"type": "done"})
            if ws_num == NUM_WORKSTATIONS:
                car.receive({"type": "finish"})
        else:
            car.current_workstation = ws_num
            ws.receive({"type": "busy"})
            car.receive({"type": "start"})


# ----- Deployment Environment (the simulation-environment orchestrator) -----


class ToyLineEnvironment(mabdt.Environment):
    """Two workstations + a dynamic car collection + the comm agent."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # Cars are created at runtime by ToyBarcodeProcessor; they live in
        # this dict rather than a mabdt AgentPopulation because the toy
        # deployment doesn't need the population's lifecycle methods.
        self.cars: dict[str, ToyCarAgent] = {}
        self.workstations: dict[str, ToyWorkstationAgent] = {}
        # The protocol is exposed so the synthetic generator can publish
        # to it. A real deployment would use MqttProtocol pointing at a
        # broker, instead.
        self.protocol = mabdt.InMemoryProtocol()

    def _declare(self) -> None:
        self.register_population(
            "workstations",
            factory=lambda ws_id, bus: self._build_ws(ws_id, bus),
            ids=[f"WS{i}" for i in range(1, NUM_WORKSTATIONS + 1)],
            paused=False,
        )
        comm = mabdt.CommunicationAgent(
            bus=self.bus,
            protocol=self.protocol,
            context=self,
            gate=lambda: True,
        )
        comm.register_processor(ToyBarcodeProcessor())
        self.register_messaging(comm)

    def _build_ws(self, ws_id: str, bus: mabdt.EventBus) -> ToyWorkstationAgent:
        ws = ToyWorkstationAgent(ws_id, bus)
        self.workstations[ws_id] = ws
        return ws


# ----- Interface Layer ------------------------------------------------------


class ToyLineInterface(mabdt.SimulationInterface):
    """Adds two domain queries on top of the mabdt base."""

    def __init__(self, environment: ToyLineEnvironment) -> None:
        super().__init__(environment=environment)

    def finished_cars(self) -> int:
        with self._lock:
            self._validate_environment()
            return sum(1 for c in self._environment.cars.values() if c.finished)

    def workstation_loads(self) -> dict[str, int]:
        with self._lock:
            self._validate_environment()
            return {ws.name: ws.cars_served for ws in self._environment.workstations.values()}


# ----- Synthetic generator (stands in for the physical layer) --------------


def run_synthetic_generator(env: ToyLineEnvironment, num_cars: int) -> None:
    """Publish two scans per car per workstation (enter + exit), in order."""
    for i in range(num_cars):
        car_id = f"car{i}"
        for ws_num in range(1, NUM_WORKSTATIONS + 1):
            topic = f"scanner/WS{ws_num}"
            env.protocol.publish(topic, car_id)  # enter scan
            time.sleep(WS_CYCLE_SECONDS)
            env.protocol.publish(topic, car_id)  # exit scan
            time.sleep(TICK_SECONDS)


# ----- Entry point ----------------------------------------------------------


def main() -> None:
    # `transitions` logs every entry/exit/transition at INFO. For a smoke run
    # like this one, that buries the actual summary under ~80 lines of
    # state-machine plumbing. Turn the library logger up to WARNING.
    logging.getLogger("transitions").setLevel(logging.WARNING)

    env = ToyLineEnvironment(config={"performance": {"agent_inbox_timeout": 0.02}})
    iface = ToyLineInterface(env)
    iface.initialize()
    iface.start_production()

    print(f"Toy line started. Sending {NUM_CARS} cars through {NUM_WORKSTATIONS} workstations.")
    run_synthetic_generator(env, NUM_CARS)
    # Let the last batch of events drain.
    time.sleep(0.5)

    finished = iface.finished_cars()
    loads = iface.workstation_loads()

    print()
    print(f"Cars finished: {finished} / {NUM_CARS}")
    print("Workstation loads:")
    for ws_name, load in loads.items():
        print(f"  {ws_name}: served {load} cars")

    iface.shutdown()


if __name__ == "__main__":
    main()
