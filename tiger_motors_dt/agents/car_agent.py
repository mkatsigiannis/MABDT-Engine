import threading
import time

from transitions.extensions import HierarchicalMachine as Machine

from mabdt.agent.statemachine import StateMachineAgent
from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class CarAgent(StateMachineAgent):
    """
    Car agent representing vehicles in the manufacturing system.

    Models a physical car moving through the Tiger Motors production line
    with hierarchical states covering assembly, fault handling, inspection,
    and completion.

    Agent Interaction List:
        Incoming: CommunicationAgent (start, done, fault),
                  InspectionStationAgent (started_inspection, finished_inspection)
        Outgoing: (none — communicates via shared main object on EventBus)

    State Communication Interfaces:
        BeingMade_AssemblyAtStation:
            - write_cell_completion: inter-model, outgoing — update cell completion counters on main
        Finished:
            - write_lead_time: inter-model, outgoing — record lead time to main dataset
    """

    def __init__(self, car_id, bus):
        """
        Initialize a new car agent with state machine and tracking features.

        Args:
            car_id: Car identifier (e.g., "SUV1", "SPEEDSTER5")
            bus: EventBus instance for inter-agent communication
        """
        super().__init__(f"Car-{car_id}", bus)

        # --- Properties ---
        self.car_id = car_id
        self.vin = car_id  # Alias for compatibility
        self.mqtt_agent = None  # Reference to communication agent if needed

        # --- Variables ---
        # Inspection trigger fires when current_workstation reaches the
        # configured line length, regardless of how many stations the
        # deployment has. The Tiger Motors facility uses 15.
        main = bus.get("main")
        if main is not None:
            self.total_workstations = main.config.get("facility", {}).get("total_workstations", 15)
        else:
            self.total_workstations = 15
        self.current_workstation = (
            None  # 1..total_workstations, or total_workstations+1 once in inspection
        )
        self.latest_fault_id = None  # Latest fault detected from workstation scan
        self.during_production_faults = []  # Faults detected during production
        self.faults = []  # Faults detected at inspection station
        self.starting_time = time.time()  # Production start time for lead time calculation
        self.final_lead_time = None  # Final lead time when car completes

        # --- State Machine ---
        states = [
            {"name": "BeingMade", "children": ["AssemblyAtStation", "WaitInQueue"]},
            "FaultDetected",
            "WaitingInspection",
            "Finished",
        ]

        transitions = [
            # Normal production workflow
            {
                "trigger": "start",
                "source": "BeingMade_WaitInQueue",
                "dest": "BeingMade_AssemblyAtStation",
            },
            {
                "trigger": "done",
                "source": "BeingMade_AssemblyAtStation",
                "dest": "BeingMade_WaitInQueue",
            },
            # Fault detection — can occur from any BeingMade sub-state
            {
                "trigger": "fault",
                "source": ["BeingMade_AssemblyAtStation", "BeingMade_WaitInQueue"],
                "dest": "FaultDetected",
            },
            # Automatic return from fault after delay
            {
                "trigger": "resolve_fault",
                "source": "FaultDetected",
                "dest": "BeingMade_AssemblyAtStation",
            },
            # Move to inspection
            {
                "trigger": "started_inspection",
                "source": ["BeingMade_AssemblyAtStation", "BeingMade_WaitInQueue"],
                "dest": "WaitingInspection",
            },
            # Final completion
            {"trigger": "finished_inspection", "source": "WaitingInspection", "dest": "Finished"},
        ]

        config = self.get_state_machine_config()
        self.machine = Machine(
            model=self,
            states=states,
            transitions=transitions,
            initial="BeingMade_WaitInQueue",
            **config,
        )

        logger.info(f"[{self.car_id}] Car agent created, starting production")

    # --- Message Handling ---

    def create_message_key(self, event_type: str, message_dict: dict) -> str:
        """
        Create a unique key for message deduplication.

        Workstation context is folded into both 'start' and 'done' keys so
        that debouncing only ever drops a re-delivery of the SAME scan at
        the SAME station. A bare 'start' key would make consecutive starts
        at successive stations look like duplicates whenever they arrive
        within the dedup window — the agent would silently skip stations
        when the line moves faster than the window.
        """
        if event_type == "start":
            return f"{event_type}_{message_dict.get('ws_num')}"
        if event_type == "done":
            return f"{event_type}_{self.current_workstation}"
        return event_type

    def process_event(self, event_type: str, message_dict: dict):
        """
        Process a normalized event with car-specific logic.

        Sync `self.current_workstation` from the `ws_num` field on the
        event the agent is currently processing. After creation this
        thread is the attribute's only writer: the barcode processor
        routes from its own single-writer position map and does not
        touch the attribute again, so the value here always reflects
        the event stream this agent has actually handled.

        Intercepts 'done' at the final workstation to transition
        directly to inspection instead of back to WaitInQueue.
        """
        if "ws_num" in message_dict:
            self.current_workstation = message_dict["ws_num"]

        if event_type == "done" and self.current_workstation == self.total_workstations:
            self.current_workstation = self.total_workstations + 1
            self.started_inspection()
            return

        self.trigger_state_event(event_type)

    # --- State Callbacks ---

    def on_enter_BeingMade_AssemblyAtStation(self):
        """Entry actions for AssemblyAtStation state."""
        logger.info(f"[{self.car_id}] Starting work at WS{self.current_workstation}")

    def on_exit_BeingMade_AssemblyAtStation(self):
        """Exit actions for AssemblyAtStation state."""
        self._update_cell_completion()

    def on_enter_BeingMade_WaitInQueue(self):
        """Entry actions for WaitInQueue state."""
        self._check_final_workstation()

    def on_enter_FaultDetected(self):
        """Entry actions for FaultDetected state."""
        self._record_fault()
        self._schedule_fault_resolve()

    def on_enter_WaitingInspection(self):
        """Entry actions for WaitingInspection state."""
        logger.info(f"[{self.car_id}] Waiting for inspection")

    def on_enter_Finished(self):
        """Entry actions for Finished state."""
        self._calculate_lead_time()

    # --- Action Implementations ---

    def _update_cell_completion(self):
        """Update cell completion counters on the main environment object.

        Each cell boundary (WS5, WS10, WS15) increments the corresponding
        cell counter, matching the AnyLogic implementation.
        """
        try:
            main = self.bus.get("main")
            if main and self.current_workstation:
                self.write_cell_completion(main, self.current_workstation)

            logger.info(f"[{self.car_id}] Completed work at WS{self.current_workstation}")
        except Exception as e:
            logger.error(f"[{self.car_id}] Error in assembly exit: {str(e)}")

    def _check_final_workstation(self):
        """Check if car is at the final workstation and should move to inspection.

        Safety net: if current_workstation equals the configured line
        length on entering WaitInQueue, auto-transition to inspection.
        Normally handled by process_event.
        """
        try:
            if self.current_workstation == self.total_workstations:
                self.current_workstation = self.total_workstations + 1
                logger.info(
                    f"[{self.car_id}] Auto-transitioning from WS"
                    f"{self.total_workstations} to inspection"
                )
                self.started_inspection()
                return

            logger.info(f"[{self.car_id}] Waiting in queue (last WS: {self.current_workstation})")
        except Exception as e:
            logger.error(f"[{self.car_id}] Error in wait queue entry: {str(e)}")

    def _record_fault(self):
        """Record the latest fault in the during-production faults list."""
        if self.latest_fault_id is not None:
            self.during_production_faults.append(self.latest_fault_id)
            logger.info(f"[{self.car_id}] Fault {self.latest_fault_id} recorded")

    def _schedule_fault_resolve(self):
        """Schedule automatic return from FaultDetected after a configurable delay."""

        def delayed_resolve():
            delay = self.bus.get_config_value("performance", "state_stability_delay", 0.005)
            time.sleep(delay)
            if self.state == "FaultDetected":
                self.resolve_fault()

        threading.Thread(target=delayed_resolve, daemon=True).start()

    def _calculate_lead_time(self):
        """Calculate and record final lead time statistics."""
        try:
            lead_time = time.time() - self.starting_time
            self.final_lead_time = lead_time

            main = self.bus.get("main")
            if main:
                self.write_lead_time(main, lead_time)

            logger.info(f"[{self.car_id}] Production COMPLETE! Lead time: {lead_time:.2f}s")
        except Exception as e:
            logger.error(f"[{self.car_id}] Error in finished state: {str(e)}")

    # --- Communication Interface Helpers ---

    def write_cell_completion(self, main, workstation_num):
        """Write inter-model data point: increment cell completion counter.

        Scope: inter-model | Direction: outgoing
        Used on exit from 'BeingMade_AssemblyAtStation' state.

        Args:
            main: Main environment object from EventBus.
            workstation_num: The workstation number that was completed.
        """
        if workstation_num == 5:
            main.cell1_finished_cars = getattr(main, "cell1_finished_cars", 0) + 1
        elif workstation_num == 10:
            main.cell2_finished_cars = getattr(main, "cell2_finished_cars", 0) + 1
        elif workstation_num == 15:
            main.cell3_finished_cars = getattr(main, "cell3_finished_cars", 0) + 1

    def write_lead_time(self, main, lead_time):
        """Write inter-model data point: record lead time to main datasets.

        Scope: inter-model | Direction: outgoing
        Used on entry to 'Finished' state.

        Args:
            main: Main environment object from EventBus.
            lead_time: Calculated lead time in seconds.
        """
        if not hasattr(main, "lead_time_dataset"):
            main.lead_time_dataset = []
        if not hasattr(main, "lead_time_histogram"):
            main.lead_time_histogram = []

        main.lead_time_dataset.append(lead_time)
        main.lead_time_histogram.append(lead_time)

    # --- Lifecycle ---

    def stop(self):
        """Stop the car agent and clean up resources."""
        logger.info(f"[{self.car_id}] Car agent stopping")
        self.running = False

    def get_production_summary(self):
        """
        Get a summary of the car's production status and metrics.

        Returns:
            dict: Summary including current state, faults, timing, etc.
        """
        return {
            "car_id": self.car_id,
            "current_state": self.state,
            "current_workstation": self.current_workstation,
            "during_production_faults": self.during_production_faults,
            "inspection_faults": self.faults,
            "starting_time": self.starting_time,
            "lead_time": time.time() - self.starting_time if self.state != "Finished" else None,
        }
