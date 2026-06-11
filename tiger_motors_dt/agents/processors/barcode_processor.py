"""BarcodeProcessor — routes workstation barcode scans to car/workstation agents.

Implements the four-route algorithm from JIM §4 Algorithm 1:
  Route 1: fault scanned while a car is at WS    -> send fault to that car
  Route 2: previously-unknown car id              -> create car + send busy/start
  Route 3: car already at this WS                 -> send done to WS and car
  Route 4: car at a different WS                  -> move it (send busy/start)

Route 4 uses the synchronously-updated `current_workstation` attribute
rather than the asynchronous state-machine `state` so move events are not
dropped under load.
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
                    new_car.current_workstation = ws_num
                    env.cars[payload_str] = new_car
                    self.send_to_agent(env, payload_str, {"type": "start", "ws_num": ws_num})
                return

            # Route 3: car already at this workstation -> operation complete
            if car_with_id.current_workstation == ws_num:
                ws = env.workstations.get(f"C{cell_num}WS{ws_num}")
                if ws:
                    msg = f"Completing car {payload_str} at WS{ws_num}"
                    logger.info(msg)
                    env.bus.publish("system_message", msg)
                    self.send_to_agent(env, ws_id, {"type": "done"})
                    self.send_to_agent(env, payload_str, {"type": "done", "ws_num": ws_num})

            # Route 4: car is at a different workstation -> it has moved.
            # Uses the synchronously-updated current_workstation (not the
            # async state attribute) so move events are not dropped under
            # load. The `ws_num` field on the dispatched event lets the
            # agent track its own workstation off the event stream, so the
            # comm thread's write to `current_workstation` here is only
            # used by this processor's own Route 3 vs Route 4 decision —
            # not by the agent's inspection check.
            elif car_with_id.current_workstation != ws_num:
                ws = env.workstations.get(f"C{cell_num}WS{ws_num}")
                if ws:
                    msg = f"Moving car {payload_str} to WS{ws_num}"
                    logger.info(msg)
                    env.bus.publish("system_message", msg)
                    car_with_id.current_workstation = ws_num
                    self.send_to_agent(env, ws_id, {"type": "busy"})
                    self.send_to_agent(env, payload_str, {"type": "start", "ws_num": ws_num})

        except Exception as e:
            logger.error(f"Error in BarcodeProcessor: {e}")

    @staticmethod
    def _car_at_workstation(env: Any, workstation: int):
        """Return the car currently at `workstation`, or None.

        O(n) scan over env.cars; n is bounded by WIP cap.
        """
        for car in env.cars.values():
            if hasattr(car, "current_workstation") and car.current_workstation == workstation:
                return car
        return None
