"""InspectionProcessor — routes inspection-station scanner events.

Topics: any `scanner/...` topic whose final segment contains the string
`InspectionStation`. The lab uses cell-and-instance-tagged names such as
`scanner/C3InspectionStation1`; older mocks and configs use the bare
`scanner/InspectionStation`. The processor accepts both shapes to match
the pre-refactor router's substring check.

Payloads:
  - "pass"                -> mark current car as inspection-passed
  - "fault<n>"            -> record fault against current car
  - "<car_id>"            -> begin inspection (if waiting) or end (if scanned twice)
                            or switch (if a different car appears)
"""

from __future__ import annotations

import time
from typing import Any

from mabdt.utils.logging import get_logger
from tiger_motors_dt.agents.processors._base import TigerTopicProcessor

logger = get_logger(__name__)


class InspectionProcessor(TigerTopicProcessor):
    """Routes inspection-station scanner payloads to the inspection station."""

    @property
    def subscriptions(self) -> list[tuple[str, int]]:
        # Match every single-level `scanner/...` topic; we filter for
        # inspection-station topics inside `process()` because MQTT
        # wildcards don't support substring matching within a level.
        # BarcodeProcessor also subscribes to `scanner/+` and silently
        # no-ops on inspection topics (its `C#WS#` regex fails on them).
        return [("scanner/+", 1)]

    def process(self, topic: str, payload: bytes, context: Any) -> None:
        env = context
        try:
            # Only handle inspection-station topics; the rest belong to
            # the workstation BarcodeProcessor.
            if "InspectionStation" not in topic:
                return

            if env.inspection_station is None:
                return

            payload_str = payload.decode() if isinstance(payload, bytes) else str(payload)

            # Route: pass result
            if payload_str == "pass":
                if (
                    env.inspection_station.state == "inspecting_car"
                    and env.inspection_station.current_car is not None
                ):
                    env.inspection_station.receive({"type": "pass"})
                else:
                    logger.info(
                        "[InspectionStation] Ignoring pass — no car currently being inspected"
                    )
                return

            content_match = self.match_pattern(payload_str)
            if not content_match:
                return
            id_letters, id_number = content_match

            # Route: fault during inspection
            if id_letters == "fault":
                env.inspection_station.newest_fault = id_number
                env.inspection_station.receive({"type": "fault"})
                return

            # Route: car ID scan
            scanned_car = env.cars.get(payload_str)
            current_car = env.inspection_station.current_car

            if env.inspection_station.state == "waiting_for_car":
                if scanned_car:
                    env.inspection_station.current_car = scanned_car
                    env.inspection_station.receive({"type": "start_inspection"})
            elif current_car and scanned_car and current_car.car_id == scanned_car.car_id:
                env.inspection_station.receive({"type": "end_inspection"})
            elif scanned_car and scanned_car != current_car:
                # Different car arriving — end current, start new
                if current_car:
                    env.inspection_station.receive({"type": "end_inspection"})
                    delay = env.config.get("performance", {}).get("state_stability_delay", 0.005)
                    time.sleep(delay)
                env.inspection_station.current_car = scanned_car
                env.inspection_station.receive({"type": "start_inspection"})

        except Exception as e:
            logger.error(f"Error in InspectionProcessor: {e}")
