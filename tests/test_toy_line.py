"""End-to-end smoke test for the toy_line example.

If `examples/toy_line/main.py` stops running to completion, this test
fails — useful as a canary for engine-level regressions.
"""

from __future__ import annotations

import time

from examples.toy_line.main import (
    NUM_CARS,
    NUM_WORKSTATIONS,
    ToyLineEnvironment,
    ToyLineInterface,
    run_synthetic_generator,
)


def test_every_car_finishes():
    env = ToyLineEnvironment(config={"performance": {"agent_inbox_timeout": 0.02}})
    iface = ToyLineInterface(env)
    iface.initialize()
    iface.start_production()
    run_synthetic_generator(env, NUM_CARS)
    time.sleep(0.5)  # let the last events drain
    assert iface.finished_cars() == NUM_CARS
    iface.shutdown()


def test_every_workstation_serves_every_car():
    env = ToyLineEnvironment(config={"performance": {"agent_inbox_timeout": 0.02}})
    iface = ToyLineInterface(env)
    iface.initialize()
    iface.start_production()
    run_synthetic_generator(env, NUM_CARS)
    time.sleep(0.5)
    loads = iface.workstation_loads()
    assert set(loads.keys()) == {f"WS{i}" for i in range(1, NUM_WORKSTATIONS + 1)}
    assert all(load == NUM_CARS for load in loads.values()), f"got {loads}"
    iface.shutdown()
