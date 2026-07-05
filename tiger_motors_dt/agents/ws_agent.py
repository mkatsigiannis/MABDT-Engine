import queue
import struct
import threading
import time

from transitions.extensions import HierarchicalMachine as Machine

from mabdt import StateTimer
from mabdt.agent.statemachine import StateMachineAgent
from mabdt.utils.logging import get_logger
from tiger_motors_dt.topic_helper import WorkstationTopicHelper

logger = get_logger(__name__)


class WorkstationAgent(StateMachineAgent):
    """
    Workstation agent modeling manufacturing workstations with Andon light systems.

    Models a physical workstation with hierarchical states covering production
    lifecycle, Andon light control (green/yellow/red), and cycle time tracking.
    Preserves green sub-state memory across yellow/red interruptions.

    Agent Interaction List:
        Incoming: CommunicationAgent (green, yellow, red, busy, done),
                  TigerMotorsEnvironment (prod_start, prod_finish)
        Outgoing: (none — communicates via MQTT and shared main object)

    State Communication Interfaces:
        Production_GreenAndon_Busy:
            - write_led_status: external, outgoing — publish LED ON/OFF to MQTT
            - write_cycle_time: external, outgoing — publish cycle time binary to MQTT
        Initialize:
            - write_init_request: external, outgoing — publish init request to MQTT
        All Production states:
            - read_production_status: inter-model, incoming — read main.tracking_production

    Recurring Events:
        - tick: 10ms interval — send PLC init request while in Initialize.
                State-time tracking is wall-clock-based via StateTimer
                (see _on_state_change) and does NOT depend on this tick.
    """

    # Map hierarchical state-machine state names to the utilization-bucket
    # names exposed via the DTO converter. States not listed here (e.g.
    # ProductionStart, Initialize, ProductionFinished) are untracked and
    # time spent in them is not credited to any bucket.
    _TRACKED_STATES = {
        "Production_GreenAndon_Idle": "Idle",
        "Production_GreenAndon_Busy": "Busy",
        "Production_YellowAndon": "Yellow",
        "Production_RedAndon": "Red",
    }

    def __init__(self, ws_id, bus):
        """
        Initialize a new workstation agent with state machine and memory features.

        Args:
            ws_id: Workstation identifier (e.g., "C1WS1", "C2WS5", "C3WS12")
            bus: EventBus instance for inter-agent communication
        """
        super().__init__(f"{ws_id}", bus)

        # --- Properties ---
        self.ws_id = ws_id
        try:
            self.ws_num = int(ws_id.split("WS")[1])
        except (IndexError, ValueError):
            logger.warning(f"Invalid workstation ID '{ws_id}', defaulting to 1")
            self.ws_num = 1

        # Topic builder. Reads workstations_per_cell from the env's loaded
        # config (looked up via the bus' "main" entry — same pattern car_agent
        # uses for total_workstations). Defaults to 5 if the env isn't on the
        # bus yet (e.g. unit tests constructing an agent in isolation).
        main = bus.get("main") if bus is not None else None
        ws_per_cell = (
            main.config.get("facility", {}).get("workstations_per_cell", 5)
            if main is not None
            else 5
        )
        self._topic_helper = WorkstationTopicHelper(ws_per_cell)

        # --- Variables ---
        # State-time tracking. StateTimer measures wall-clock time spent
        # in each Andon sub-state, hooked from the state machine's
        # after_state_change callback below. Replaces the legacy pattern
        # of counting tick events.
        self._state_timer = StateTimer(["Idle", "Busy", "Yellow", "Red"])
        self.current_start_time = 0
        self.previous_green_state = "Production_GreenAndon_Idle"

        # Busy-state entry/exit dedup. Distinct from the framework's
        # paper's processing guard (which is provided by the single-threaded
        # inbox loop); this flag dedupes _start_processing / _stop_processing
        # in case the transitions library fires the entry/exit callback
        # twice for the same logical transition.
        self.is_processing: bool = False
        self.processing_lock = threading.Lock()

        # --- State Machine ---
        states = [
            "ProductionStart",
            "Initialize",
            {
                "name": "Production",
                "children": [
                    {"name": "GreenAndon", "children": ["Idle", "Busy"]},
                    "YellowAndon",
                    "RedAndon",
                ],
            },
            "ProductionFinished",
        ]

        transitions = [
            # Production lifecycle
            {"trigger": "prod_start", "source": "ProductionStart", "dest": "Initialize"},
            # Initialize to Production Andon states
            {"trigger": "green", "source": "Initialize", "dest": "Production_GreenAndon_Idle"},
            {"trigger": "yellow", "source": "Initialize", "dest": "Production_YellowAndon"},
            {"trigger": "red", "source": "Initialize", "dest": "Production_RedAndon"},
            # Green Andon internal transitions (Idle <-> Busy)
            {
                "trigger": "busy",
                "source": "Production_GreenAndon_Idle",
                "dest": "Production_GreenAndon_Busy",
            },
            {
                "trigger": "done",
                "source": "Production_GreenAndon_Busy",
                "dest": "Production_GreenAndon_Idle",
            },
            # Andon light transitions with memory preservation
            {
                "trigger": "yellow",
                "source": ["Production_GreenAndon_Idle", "Production_GreenAndon_Busy"],
                "dest": "Production_YellowAndon",
                "before": "save_green_state",
            },
            {
                "trigger": "red",
                "source": ["Production_GreenAndon_Idle", "Production_GreenAndon_Busy"],
                "dest": "Production_RedAndon",
                "before": "save_green_state",
            },
            # Recovery with state memory restoration
            {
                "trigger": "green",
                "source": ["Production_YellowAndon", "Production_RedAndon"],
                "dest": "Production_GreenAndon_Idle",
                "after": "restore_green_state",
            },
            # Escalation between non-green states
            {"trigger": "red", "source": "Production_YellowAndon", "dest": "Production_RedAndon"},
            {
                "trigger": "yellow",
                "source": "Production_RedAndon",
                "dest": "Production_YellowAndon",
            },
            # Production completion from any production sub-state
            {
                "trigger": "prod_finish",
                "source": [
                    "Production_GreenAndon_Idle",
                    "Production_GreenAndon_Busy",
                    "Production_YellowAndon",
                    "Production_RedAndon",
                ],
                "dest": "ProductionFinished",
            },
            # Restart production cycle
            {"trigger": "prod_start", "source": "ProductionFinished", "dest": "Initialize"},
        ]

        config = self.get_state_machine_config()
        self.machine = Machine(
            model=self,
            states=states,
            transitions=transitions,
            initial="ProductionStart",
            after_state_change="_on_state_change",
            **config,
        )

        # Set up recurring event for state tracking
        self._setup_recurring_event()

    # --- Recurring Events ---

    def _setup_recurring_event(self):
        """Subscribe to EventBus tick for state tracking and PLC initialization."""

        def on_tick(message=None):
            try:
                self._inbox.put({"type": "internal_tick"})
            except Exception as e:
                logger.error(f"Error in workstation {self.ws_id} recurring event: {str(e)}")

        self.bus.subscribe("tick", on_tick)

    def _handle_internal_tick(self):
        """Handle tick events in the agent's own thread.

        Sends initialization requests to the PLC bridge while in Initialize
        state. State-time tracking is no longer driven from here; the
        StateTimer wall-clock approach in _on_state_change replaces it.
        """
        try:
            if self.state == "Initialize":
                main = self.bus.get("main")
                if main and main.tracking_production:
                    self.write_init_request()
        except Exception as e:
            logger.error(f"Error in workstation {self.ws_id} internal tick: {str(e)}")

    # --- State-time tracking (timestamp-based) ---

    def _on_state_change(self):
        """Update the wall-clock state timer on every state transition.

        Hooked into the transitions library via `after_state_change` in
        the Machine constructor. Called after the model's `self.state` has
        been updated to the new state.
        """
        try:
            self._state_timer.on_state_change(self._TRACKED_STATES.get(self.state))
        except Exception as e:
            logger.error(f"Error updating state timer for workstation " f"{self.ws_id}: {str(e)}")

    def pause(self):
        """Pause the agent and stop crediting time to the current state."""
        super().pause()
        self._state_timer.on_state_change(None)

    def resume(self):
        """Resume the agent and re-enter the tracked state (if any)."""
        super().resume()
        self._state_timer.on_state_change(self._TRACKED_STATES.get(self.state))

    @property
    def idle_time(self) -> float:
        """Wall-clock seconds the workstation has been in GreenAndon_Idle."""
        return self._state_timer.get("Idle")

    @property
    def busy_time(self) -> float:
        """Wall-clock seconds the workstation has been in GreenAndon_Busy."""
        return self._state_timer.get("Busy")

    @property
    def yellow_time(self) -> float:
        """Wall-clock seconds the workstation has been in YellowAndon."""
        return self._state_timer.get("Yellow")

    @property
    def red_time(self) -> float:
        """Wall-clock seconds the workstation has been in RedAndon."""
        return self._state_timer.get("Red")

    # --- Message Handling ---

    def handle(self, msg: dict):
        """Queue incoming messages for processing in _run_loop."""
        try:
            self._inbox.put(msg)
        except Exception as e:
            logger.error(f"Error in workstation {self.ws_id} message handling: {str(e)}")

    def _run_loop(self):
        """Main run loop with state validation.

        Processes messages from inbox, validates transitions against
        current state, and handles internal tick events.
        """
        while self.running:
            try:
                try:
                    message = self._inbox.get(timeout=0.1)
                except queue.Empty:
                    continue

                msg_type = message.get("type", "")

                # Internal tick — must be processed every tick, so it bypasses
                # the duplicate-message detection below. With 100 Hz ticks,
                # the 1 s dedup window would otherwise drop 99/100 ticks and
                # undercount the idle/busy/yellow/red counters by the same
                # factor (visible as workstation time totals that don't add
                # up to the production run's elapsed time).
                if msg_type == "internal_tick":
                    self._handle_internal_tick()
                    continue

                # Duplicate message detection (state-machine messages only)
                current_time = time.time()
                message_key = f"{msg_type}_{message.get('data', '')}"
                if self.last_message == message_key and current_time - self.last_message_time < 1.0:
                    continue

                self.last_message = message_key
                self.last_message_time = current_time

                current_state = self.state

                # Skip production messages after finish
                if current_state == "ProductionFinished" and msg_type in [
                    "green",
                    "yellow",
                    "red",
                    "busy",
                    "done",
                ]:
                    msg = f"[{self.ws_id}] Production stopped - ignoring {msg_type} message"
                    logger.info(msg)
                    self.bus.publish("system_message", msg)
                    continue

                # Validate and execute transitions
                if msg_type == "prod_start":
                    if current_state in ["ProductionStart", "ProductionFinished"]:
                        self.prod_start()

                elif msg_type == "green":
                    if current_state in [
                        "Initialize",
                        "Production_YellowAndon",
                        "Production_RedAndon",
                    ]:
                        self.green()

                elif msg_type == "yellow":
                    if current_state in [
                        "Initialize",
                        "Production_GreenAndon_Idle",
                        "Production_GreenAndon_Busy",
                        "Production_RedAndon",
                    ]:
                        self.yellow()

                elif msg_type == "red":
                    if current_state in [
                        "Initialize",
                        "Production_GreenAndon_Idle",
                        "Production_GreenAndon_Busy",
                        "Production_YellowAndon",
                    ]:
                        self.red()

                elif msg_type == "busy":
                    if current_state == "Production_GreenAndon_Idle":
                        self.busy()

                elif msg_type == "done":
                    if current_state == "Production_GreenAndon_Busy":
                        self.done()

                elif msg_type == "prod_finish":
                    if current_state in [
                        "Production_GreenAndon_Idle",
                        "Production_GreenAndon_Busy",
                        "Production_YellowAndon",
                        "Production_RedAndon",
                    ]:
                        self.prod_finish()

            except Exception as e:
                logger.error(f"Error in workstation {self.ws_id} run loop: {str(e)}")
                time.sleep(1)

    # --- State Callbacks ---

    def on_enter_Initialize(self):
        """Entry actions for Initialize state."""
        self._reset_counters()

    def on_enter_Production_GreenAndon_Idle(self):
        """Entry actions for GreenAndon_Idle state."""
        if self.state != "Production_GreenAndon_Idle":
            self._reset_counters()

    def on_enter_Production_GreenAndon_Busy(self):
        """Entry actions for GreenAndon_Busy state."""
        self._start_processing()

    def on_exit_Production_GreenAndon_Busy(self):
        """Exit actions for GreenAndon_Busy state."""
        self._stop_processing()

    # --- Transition Callbacks ---

    def save_green_state(self):
        """Called before transition from green to yellow/red.

        Saves the current green sub-state so it can be restored
        when the workstation recovers to green.
        """
        if self.state in ["Production_GreenAndon_Idle", "Production_GreenAndon_Busy"]:
            self.previous_green_state = self.state

    def restore_green_state(self):
        """Called after transition from yellow/red back to green.

        Restores the previous green sub-state (idle or busy). If the
        workstation was busy before the interruption, re-triggers the
        busy transition after a short delay for state stability.
        """

        def delayed_restore():
            if self.previous_green_state == "Production_GreenAndon_Busy":
                if self.state == "Production_GreenAndon_Idle":
                    self.busy()

        delay = self.bus.get_config_value("performance", "state_stability_delay", 0.005)
        threading.Timer(delay, delayed_restore).start()

    # --- Action Implementations ---

    def _reset_counters(self):
        """Reset all performance counters and timers for a new production run."""
        self.current_start_time = None
        self.cars_processed = 0
        self.total_cycle_time = 0

    def _start_processing(self):
        """Start processing — record time and turn on LED.

        Uses a processing lock to guard against duplicate calls.
        """
        with self.processing_lock:
            if self.is_processing:
                logger.info(f"[{self.ws_id}] Processing already started - ignoring duplicate")
                return
            self.is_processing = True

        logger.info(f"[{self.ws_id}] Processing started")
        self.current_start_time = time.perf_counter()
        self.write_led_status("ON")

    def _stop_processing(self):
        """Stop processing — calculate cycle time and turn off LED.

        Uses a processing lock to guard against duplicate calls.
        """
        with self.processing_lock:
            if not self.is_processing:
                logger.info(f"[{self.ws_id}] Processing already stopped - ignoring duplicate")
                return
            self.is_processing = False

        end_time = time.perf_counter()
        cycle_time = round(end_time - self.current_start_time, 4)
        logger.info(f"[{self.ws_id}] Processing completed ({cycle_time:.4f}s)")

        self.write_cycle_time(cycle_time)
        self.write_led_status("OFF")

    # --- Communication Interface Helpers ---

    def write_led_status(self, status, qos=2):
        """Write external data point: publish LED ON/OFF to MQTT leds topic.

        Scope: external | Direction: outgoing
        Used on enter/exit of 'Production_GreenAndon_Busy' state.

        Args:
            status: 'ON' or 'OFF'.
            qos: MQTT quality of service level.
        """
        topic = self._topic_helper.create_led_topic(self.ws_num)
        self.bus.publish_mqtt(topic, status, qos=qos)

    def write_cycle_time(self, cycle_time, qos=2):
        """Write external data point: publish cycle time to MQTT ws_cycle_time topic.

        Scope: external | Direction: outgoing
        Used on exit from 'Production_GreenAndon_Busy' state.
        Packs cycle time as big-endian double for Node-RED consumption.

        Args:
            cycle_time: Cycle time in seconds (float).
            qos: MQTT quality of service level.
        """
        cycle_time_binary = struct.pack(">d", cycle_time)
        topic = self._topic_helper.create_cycle_time_topic(self.ws_num)
        self.bus.publish_mqtt(topic, cycle_time_binary, qos=qos)

    def write_init_request(self, qos=2):
        """Write external data point: publish init request to MQTT ws_init topic.

        Scope: external | Direction: outgoing
        Used in 'Initialize' state during tick events to request current
        Andon light status from PLC.

        Args:
            qos: MQTT quality of service level.
        """
        topic = self._topic_helper.create_init_topic(self.ws_num)
        self.bus.publish_mqtt(topic, "True", qos=qos)

    # --- Lifecycle ---

    def stop(self):
        """Stop the workstation agent gracefully."""
        self.running = False
        if hasattr(self, "_thread") and self._thread.is_alive():
            self._thread.join(timeout=1.0)
