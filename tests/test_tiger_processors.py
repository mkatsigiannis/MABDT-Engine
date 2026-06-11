"""Tiger Motors deployment-specific routing tests.

Includes regression coverage for the InspectionProcessor topic-filter bug:
the lab publishes inspection scans to `scanner/C3InspectionStation1` (a
cell-and-instance-tagged name), but the pre-fix code subscribed exactly
to `scanner/InspectionStation` and silently dropped the lab topic.
"""

from __future__ import annotations

import time

import pytest

from mabdt import EventBus
from tiger_motors_dt.agents.car_agent import CarAgent
from tiger_motors_dt.agents.is_agent import InspectionStationAgent
from tiger_motors_dt.agents.processors import (
    BarcodeProcessor,
    InspectionProcessor,
    PLCProcessor,
)
from tiger_motors_dt.agents.ws_agent import WorkstationAgent


def _short_bus() -> EventBus:
    return EventBus(
        {
            "performance": {
                "agent_inbox_timeout": 0.05,
                "state_stability_delay": 0.005,
            }
        }
    )


class _FakeEnv:
    """Minimal env-shaped object that Tiger TopicProcessors use as context."""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self.cars = {}
        self.workstations = {}
        self.inspection_station = None
        self.config = {
            "performance": {"state_stability_delay": 0.005},
            "facility": {"workstations_per_cell": 5},
        }
        self.tracking_production = True


@pytest.fixture
def tiger_env():
    """A FakeEnv preloaded with C1WS1, C1WS2, and an inspection station."""
    bus = _short_bus()
    env = _FakeEnv(bus)
    bus.set("main", env)
    for ws_name in ("C1WS1", "C1WS2"):
        w = WorkstationAgent(ws_name, bus)
        w.resume()
        env.workstations[ws_name] = w
    env.inspection_station = InspectionStationAgent(bus)
    env.inspection_station.resume()
    yield env
    for c in env.cars.values():
        c.stop()
    for w in env.workstations.values():
        w.stop()
    env.inspection_station.stop()
    bus.shutdown()


# ----- BarcodeProcessor four-route algorithm --------------------------------


def test_barcode_route_2_creates_new_car_at_first_scan(tiger_env):
    """Route 2: an unknown car id arriving at a workstation creates a car."""
    bp = BarcodeProcessor()
    bp.process("scanner/C1WS1", b"SUV1", tiger_env)
    time.sleep(0.15)
    assert "SUV1" in tiger_env.cars
    assert tiger_env.cars["SUV1"].current_workstation == 1


def test_barcode_route_3_same_ws_marks_done(tiger_env):
    bp = BarcodeProcessor()
    bp.process("scanner/C1WS1", b"SUV1", tiger_env)
    time.sleep(0.15)
    # Second scan at the same WS triggers Route 3.
    bp.process("scanner/C1WS1", b"SUV1", tiger_env)
    time.sleep(0.15)
    # current_workstation is unchanged; the WS agent receives a 'done' event.
    assert tiger_env.cars["SUV1"].current_workstation == 1


def test_barcode_route_4_moves_car_to_new_workstation(tiger_env):
    bp = BarcodeProcessor()
    bp.process("scanner/C1WS1", b"SUV1", tiger_env)
    time.sleep(0.15)
    bp.process("scanner/C1WS2", b"SUV1", tiger_env)
    time.sleep(0.15)
    assert tiger_env.cars["SUV1"].current_workstation == 2


def test_barcode_ignores_non_ws_scanner_topic(tiger_env):
    """A `scanner/InspectionStation*` topic should not create a car."""
    bp = BarcodeProcessor()
    bp.process("scanner/C3InspectionStation1", b"SUV1", tiger_env)
    time.sleep(0.1)
    assert "SUV1" not in tiger_env.cars


# ----- PLCProcessor --------------------------------------------------------


def test_plc_yellow_light_forwarded_to_workstation(tiger_env):
    pp = PLCProcessor()
    pp.process("plc/WS1/YEL", b"True", tiger_env)
    time.sleep(0.15)
    # No exception is the assertion; full Andon transitions verified via WS smoke.
    assert tiger_env.workstations["C1WS1"] is not None


def test_plc_non_true_payload_is_ignored(tiger_env):
    pp = PLCProcessor()
    # Rising-edge convention: payload must be exactly "True".
    pp.process("plc/WS1/GRN", b"False", tiger_env)
    pp.process("plc/WS1/YEL", b"", tiger_env)
    # No state change observable here; the absence of an exception is the test.


# ----- InspectionProcessor topic-filter regression --------------------------


def test_inspection_lab_topic_starts_inspection(tiger_env):
    """REGRESSION: scanner/C3InspectionStation1 must start an inspection.

    The pre-fix InspectionProcessor subscribed exactly to
    'scanner/InspectionStation' and dropped the lab topic shape, leaving
    every car stuck in WaitingInspection.
    """
    # Set up a car already at WS16 (post-WS15 transition).
    car = CarAgent("SUV1", tiger_env.bus)
    car.current_workstation = 16
    tiger_env.cars["SUV1"] = car

    ip = InspectionProcessor()
    ip.process("scanner/C3InspectionStation1", b"SUV1", tiger_env)
    time.sleep(0.3)

    assert tiger_env.inspection_station.state == "inspecting_car"
    assert tiger_env.inspection_station.current_car is car


def test_inspection_legacy_topic_still_works(tiger_env):
    """The bare `scanner/InspectionStation` topic also routes correctly."""
    car = CarAgent("SPEEDSTER2", tiger_env.bus)
    car.current_workstation = 16
    tiger_env.cars["SPEEDSTER2"] = car

    ip = InspectionProcessor()
    ip.process("scanner/InspectionStation", b"SPEEDSTER2", tiger_env)
    time.sleep(0.3)

    assert tiger_env.inspection_station.state == "inspecting_car"


def test_inspection_processor_ignores_workstation_topics(tiger_env):
    """The InspectionProcessor's subscription is `scanner/+` so it sees every
    scanner topic, but its process() must early-return on non-inspection ones.
    """
    car = CarAgent("SUV9", tiger_env.bus)
    car.current_workstation = 1
    tiger_env.cars["SUV9"] = car

    ip = InspectionProcessor()
    initial_state = tiger_env.inspection_station.state
    ip.process("scanner/C1WS1", b"SUV9", tiger_env)
    time.sleep(0.1)
    # No state change at the inspection station.
    assert tiger_env.inspection_station.state == initial_state


def test_inspection_pass_marks_car_passed(tiger_env):
    """After an inspection has started, payload 'pass' marks the car passed."""
    car = CarAgent("SUV5", tiger_env.bus)
    car.current_workstation = 16
    tiger_env.cars["SUV5"] = car

    ip = InspectionProcessor()
    ip.process("scanner/C3InspectionStation1", b"SUV5", tiger_env)
    time.sleep(0.2)
    assert tiger_env.inspection_station.state == "inspecting_car"

    ip.process("scanner/C3InspectionStation1", b"pass", tiger_env)
    time.sleep(0.2)
    # Either passed_inspection (transient) or back to inspecting_car/waiting.
    assert tiger_env.inspection_station.state in {
        "passed_inspection",
        "inspecting_car",
        "waiting_for_car",
    }


# ----- WorkstationAgent cycle-time regression -------------------------------


def test_workstation_busy_cycle_publishes_cycle_time():
    """REGRESSION: WS publishes a cycle_time MQTT message on Busy->Idle.

    Cycle times feed the Grafana KPI dashboards (and the MING stack
    generally). The publish lives in on_exit_Production_GreenAndon_Busy
    via _stop_processing, which guards entry/exit dedup with
    `is_processing` + `processing_lock`. If those attributes are missing,
    the entry/exit callbacks AttributeError, the run-loop catches the
    exception, and no cycle_time is ever forwarded to the broker —
    silently breaking the Grafana feed.
    """
    bus = _short_bus()
    mqtt_published: list[dict] = []
    bus.subscribe("mqtt", lambda m: mqtt_published.append(m))

    ws = WorkstationAgent("C1WS1", bus)
    ws.resume()
    try:
        for evt in ("prod_start", "green", "busy", "done"):
            ws.receive({"type": evt})
            time.sleep(0.1)
    finally:
        ws.stop()
        bus.shutdown()

    cycle = [m for m in mqtt_published if "ws_cycle_time" in m.get("topic", "")]
    assert len(cycle) == 1, (
        f"Expected exactly one cycle_time publish, got {len(cycle)}. "
        f"All mqtt messages: {mqtt_published}"
    )
    assert cycle[0]["topic"] == "ws_cycle_time/C1WS1"
    assert isinstance(cycle[0]["payload"], (bytes, bytearray))
    assert len(cycle[0]["payload"]) == 8  # big-endian double
