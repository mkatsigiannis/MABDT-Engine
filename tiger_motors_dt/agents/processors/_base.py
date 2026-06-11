"""Shared base for Tiger Motors TopicProcessors.

Encapsulates the regexes and the agent-lookup helper that every Tiger
processor uses. The mabdt.TopicProcessor is the framework contract;
TigerTopicProcessor adds Tiger-specific routing helpers on top.
"""

from __future__ import annotations

import re
from typing import Any

from mabdt import TopicProcessor


class TigerTopicProcessor(TopicProcessor):
    """Tiger-specific TopicProcessor base.

    Provides:
      - match_pattern: SUV/SPEEDSTER/fault payload regex
      - send_to_agent: route a message to an agent by id (workstation, car,
        or the singleton inspection station) via its inbox
    """

    _CAR_PATTERN = re.compile(r"^(SUV|SPEEDSTER|speed)(\d+)$", re.IGNORECASE)
    _FAULT_PATTERN = re.compile(r"^fault(\d+)$", re.IGNORECASE)

    @classmethod
    def match_pattern(cls, input_str: str) -> tuple[str, int] | None:
        """Parse a barcode payload.

        Returns:
            ("SUV"|"SPEEDSTER", id_number)  for car barcodes
            ("fault", code)                 for fault codes
            None                            otherwise
        """
        car_match = cls._CAR_PATTERN.match(input_str)
        if car_match:
            return (car_match.group(1).upper(), int(car_match.group(2)))
        fault_match = cls._FAULT_PATTERN.match(input_str)
        if fault_match:
            return ("fault", int(fault_match.group(1)))
        return None

    @staticmethod
    def send_to_agent(context: Any, agent_id: str, message: dict) -> None:
        """Deliver `message` to the named agent's inbox.

        `context` is the TigerMotorsEnvironment. Looks up the agent in
        workstations, cars, then the inspection station singleton.
        """
        if agent_id in context.workstations:
            context.workstations[agent_id].receive(message)
        elif agent_id in context.cars:
            context.cars[agent_id].receive(message)
        elif context.inspection_station is not None and agent_id in (
            "inspection",
            "InspectionStation",
        ):
            context.inspection_station.receive(message)
