"""Tiger Motors workstation MQTT topic builder.

Encapsulates the `C{cell}WS{ws_num}` topic shape so callers don't have
to repeat the arithmetic. Cell ranges are driven by
`facility.workstations_per_cell` from the loaded config — pass it to
the constructor once, then call the instance methods.
"""


class WorkstationTopicHelper:
    """Build per-workstation MQTT topics for a known cell layout."""

    def __init__(self, workstations_per_cell: int):
        if workstations_per_cell <= 0:
            raise ValueError(f"workstations_per_cell must be positive, got {workstations_per_cell}")
        self._ws_per_cell = workstations_per_cell

    def get_cell_prefix(self, ws_num: int) -> str:
        """Return `"C{n}"` for the cell containing `ws_num` (1-based)."""
        if ws_num < 1:
            return "C1"
        cell_num = ((ws_num - 1) // self._ws_per_cell) + 1
        return f"C{cell_num}"

    def create_topic(self, topic_prefix: str, ws_num: int) -> str:
        """Compose `<prefix>/<cell><ws>` (e.g. `leds/C2WS7`)."""
        cell_prefix = self.get_cell_prefix(ws_num)
        return f"{topic_prefix}/{cell_prefix}WS{ws_num}"

    def create_init_topic(self, ws_num: int) -> str:
        return self.create_topic("ws_init", ws_num)

    def create_led_topic(self, ws_num: int) -> str:
        return self.create_topic("leds", ws_num)

    def create_cycle_time_topic(self, ws_num: int) -> str:
        return self.create_topic("ws_cycle_time", ws_num)
