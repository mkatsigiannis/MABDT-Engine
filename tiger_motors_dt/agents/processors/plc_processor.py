"""PLCProcessor — routes Andon light updates from the PLC bridge.

Topic shape: `plc/C#WS#/{GRN|YEL|RED}` with payload `"True"` on the rising
edge. The processor forwards the corresponding `green`/`yellow`/`red` event
to the targeted workstation agent.
"""

from __future__ import annotations

from typing import Any

from mabdt.utils.logging import get_logger
from tiger_motors_dt.agents.processors._base import TigerTopicProcessor

logger = get_logger(__name__)


class PLCProcessor(TigerTopicProcessor):
    """Routes PLC Andon topics (`plc/C#WS#/{GRN|YEL|RED}`) to workstation agents."""

    _COLOR_MAP = {"GRN": "green", "YEL": "yellow", "RED": "red"}

    @property
    def subscriptions(self) -> list[tuple[str, int]]:
        return [("plc/#", 1)]

    def process(self, topic: str, payload: bytes, context: Any) -> None:
        env = context
        try:
            payload_str = payload.decode() if isinstance(payload, bytes) else str(payload)
            if payload_str != "True":
                return

            topic_parts = topic.split("/")
            if len(topic_parts) < 3:
                return

            # topic_parts[1] is like 'C1WS3' or 'WS3'; extract trailing integer
            ws_id_int = self._get_trailing_int(topic_parts[1])
            if ws_id_int == -1:
                return

            workstations_per_cell = env.config.get("facility", {}).get("workstations_per_cell", 5)
            ws_key = f"C{(ws_id_int - 1) // workstations_per_cell + 1}WS{ws_id_int}"
            ws = env.workstations.get(ws_key)
            if not ws:
                return

            color = topic_parts[2]
            event = self._COLOR_MAP.get(color)
            if event is None:
                return

            self.send_to_agent(env, ws.name, {"type": event})
            msg = f"WS{ws_id_int}: {color} light"
            logger.info(msg)
            env.bus.publish("system_message", msg)

        except Exception as e:
            logger.error(f"Error in PLCProcessor: {e}")

    @staticmethod
    def _get_trailing_int(input_str: str) -> int:
        """Extract the trailing integer from a string. Returns -1 if none."""
        for i in range(len(input_str) - 1, -1, -1):
            try:
                result = int(input_str[i:])
                if i == 0:
                    return result
            except ValueError:
                if i == len(input_str) - 1:
                    break
                return int(input_str[i + 1 :])
        return -1
