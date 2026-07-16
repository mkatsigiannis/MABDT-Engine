"""BarcodeProcessor — routes workstation barcode scans to car/workstation agents.

Implements the deployment's four-route scanner dispatch (a deployment-specific
processor in the sense of the JIM paper's "Communication Agent" subsection):
  Route 1: fault scanned while a car is at WS    -> send fault to that car
  Route 2: previously-unknown car id              -> create car + send busy/start
  Route 3: car already at this WS                 -> send done to WS and car
  Route 4: car at a different WS                  -> move it (send busy/start)

Routing state is single-writer: the processor keeps its own car-position
map (`_positions`), written and read only from the communication agent's
dispatch thread. Routing must NOT read `CarAgent.current_workstation`:
the car's own thread re-syncs that attribute from the event it is
currently handling, so under load it can transiently hold a PAST station
(the agent is catching up on its inbox) — and a Route 3 completion would
then misroute as a Route 4 move, silently losing the completion.
"""

from __future__ import annotations

import re
from typing import Any

from mabdt.utils.logging import get_logger
from tiger_motors_dt.agents.car_agent import CarAgent
from tiger_motors_dt.agents.processors._base import TigerTopicProcessor

logger = get_logger(__name__)

_WS_ID_RE = re.compile(r"C(\d+)WS(\d+)")


class BarcodeProcessor(TigerTopicProcessor):
    """Routes workstation barcode topics (`scanner/C#WS#`) to agents."""

    def __init__(self) -> None:
        # car_id -> workstation number, as last routed by THIS processor.
        # Single-writer: every process() call runs on the communication
        # agent's dispatch thread, so no lock is needed. Entries are
        # removed when a car completes the final workstation and leaves
        # the line for inspection.
        self._positions: dict[str, int] = {}

    @property
    def subscriptions(self) -> list[tuple[str, int]]:
        return [("scanner/+", 1)]

    def process(self, topic: str, payload: bytes, context: Any) -> None:
        env = context  # TigerMotorsEnvironment
        try:
            # Decode payload (paho callbacks pass bytes; in-memory passes bytes too).
            payload_str = payload.decode() if isinstance(payload, bytes) else str(payload)

            # Inspection station scans live on `scanner/InspectionStation` and are
            # claimed by InspectionProcessor. The topic doesn't match `C#WS#` so
            # we just short-circuit here for clarity.
            topic_parts = topic.split("/")
            if len(topic_parts) != 2:
                return
            ws_id = topic_parts[1]
            ws_match = _WS_ID_RE.match(ws_id)
            if not ws_match:
                return

            cell_num = int(ws_match.group(1))
            ws_num = int(ws_match.group(2))

            content_match = self.match_pattern(payload_str)
            if not content_match:
                return
            id_letters, id_number = content_match

            car_at_ws = self._car_at_workstation(env, ws_num)
            car_with_id = env.cars.get(payload_str)

            # Route 1: fault detected at the workstation that holds a car
            if car_at_ws and id_letters == "fault":
                msg = f"Fault {id_number} detected at WS{ws_num}"
                logger.info(msg)
                env.bus.publish("system_message", msg)
                car_at_ws.latest_fault_id = id_number
                self.send_to_agent(env, car_at_ws.vin, {"type": "fault"})
                return

            # Route 2: previously unknown car id -> create a new car
            if not car_with_id:
                ws = env.workstations.get(f"C{cell_num}WS{ws_num}")
                if ws:
                    msg = f"Starting car {payload_str} at WS{ws_num}"
                    logger.info(msg)
                    env.bus.publish("system_message", msg)
                    self.send_to_agent(env, ws_id, {"type": "busy"})
                    new_car = CarAgent(payload_str, env.bus)
                    # Initial position, written before the agent receives its
                    # first event; from here on the agent tracks its own
                    # position off the event stream (ws_num field).
                    new_car.current_workstation = ws_num
                    env.cars[payload_str] = new_car
                    self._positions[payload_str] = ws_num
                    self.send_to_agent(env, payload_str, {"type": "start", "ws_num": ws_num})
                return

            # Position as routed so far. Falls back to the agent attribute
            # for cars this processor never placed (e.g. constructed by a
            # deployment extension or a test fixture).
            position = self._positions.get(payload_str, car_with_id.current_workstation)

            # Route 3: car already at this workstation -> operation complete
            if position == ws_num:
                ws = env.workstations.get(f"C{cell_num}WS{ws_num}")
                if ws:
                    msg = f"Completing car {payload_str} at WS{ws_num}"
                    logger.info(msg)
                    env.bus.publish("system_message", msg)
                    self.send_to_agent(env, ws_id, {"type": "done"})
                    self.send_to_agent(env, payload_str, {"type": "done", "ws_num": ws_num})
                    total = env.config.get("facility", {}).get("total_workstations", 15)
                    if ws_num == total:
                        # The car leaves the line for inspection; it no longer
                        # occupies a scanner station.
                        self._positions.pop(payload_str, None)

            # Route 4: car is at a different workstation -> it has moved.
            else:
                ws = env.workstations.get(f"C{cell_num}WS{ws_num}")
                if ws:
                    msg = f"Moving car {payload_str} to WS{ws_num}"
                    logger.info(msg)
                    env.bus.publish("system_message", msg)
                    self._positions[payload_str] = ws_num
                    self.send_to_agent(env, ws_id, {"type": "busy"})
                    self.send_to_agent(env, payload_str, {"type": "start", "ws_num": ws_num})

        except Exception as e:
            logger.error(f"Error in BarcodeProcessor: {e}")

    def _car_at_workstation(self, env: Any, workstation: int):
        """Return the car currently at `workstation`, or None.

        Reads the processor's own position map (single-writer, so always
        consistent with the routing decisions made here). Cars that left
        the line for inspection have no entry and are never matched.
        """
        for car_id, position in self._positions.items():
            if position == workstation:
                return env.cars.get(car_id)
        return None
