import json
import threading
import time

from transitions.extensions import HierarchicalMachine as Machine

from mabdt.agent.statemachine import StateMachineAgent
from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class InspectionStationAgent(StateMachineAgent):
    """
    Inspection station agent — final quality control point in the manufacturing system.

    Models the physical inspection station where cars are manually inspected
    and data is provided using a barcode scanner.

    Agent Interaction List:
        Incoming: CommunicationAgent (start_inspection, end_inspection, pass, fault)
        Outgoing: CarAgent (finished_inspection, started_inspection)

    State Communication Interfaces:
        waiting_for_car:
            - write_inspection_result: external, outgoing — publish pass/fail to MQTT
            - write_inspection_faults: external, outgoing — publish fault details to MQTT
    """

    def __init__(self, bus):
        """
        Initialize the inspection station agent with state machine.

        Args:
            bus: EventBus instance for inter-agent communication
        """
        super().__init__("InspectionStation", bus)

        # --- Properties ---
        self.mqtt_agent = None  # Reference to communication agent

        # --- Variables ---
        self.current_car = None  # Current car being inspected
        self.newest_fault = None  # Latest fault identified
        self._last_processed_car = None  # Duplicate processing guard

        # --- State Machine ---
        states = ["waiting_for_car", "inspecting_car", "passed_inspection", "add_fault"]

        transitions = [
            # Main workflow transitions
            {"trigger": "start_inspection", "source": "waiting_for_car", "dest": "inspecting_car"},
            {"trigger": "end_inspection", "source": "inspecting_car", "dest": "waiting_for_car"},
            # Allow end_inspection from passed_inspection state (for rapid sequences)
            {"trigger": "end_inspection", "source": "passed_inspection", "dest": "waiting_for_car"},
            # Inspection result transitions
            {"trigger": "pass", "source": "inspecting_car", "dest": "passed_inspection"},
            {"trigger": "fault", "source": "inspecting_car", "dest": "add_fault"},
            # Automatic returns to inspecting_car
            {
                "trigger": "return_to_inspecting",
                "source": "passed_inspection",
                "dest": "inspecting_car",
            },
            {"trigger": "return_to_inspecting", "source": "add_fault", "dest": "inspecting_car"},
        ]

        config = self.get_state_machine_config()
        self.machine = Machine(
            model=self, states=states, transitions=transitions, initial="waiting_for_car", **config
        )

        logger.info("[InspectionStation] Agent created")

    # --- Message Handling ---

    def create_message_key(self, event_type: str, message_dict: dict) -> str:
        """
        Create a unique key for message deduplication.
        Include fault information for fault events.
        """
        if event_type == "fault":
            return f"{event_type}_{self.newest_fault}"
        return event_type

    # --- Outgoing Messages ---

    def send_finished_inspection(self, car_agent):
        """Send 'finished_inspection' to CarAgent via direct message.

        Notifies the car that its inspection cycle is complete so it can
        transition to the Finished state.

        Args:
            car_agent: Target CarAgent instance.
        """
        try:
            if car_agent and hasattr(car_agent, "handle"):
                car_agent.handle({"type": "finished_inspection"})
                logger.info(f"[InspectionStation] Sent finished_inspection to {car_agent.car_id}")
            else:
                logger.error(
                    "[InspectionStation] Cannot send finished_inspection - invalid target agent"
                )
        except Exception as e:
            logger.error(f"[InspectionStation] Error sending finished_inspection: {str(e)}")

    def send_started_inspection(self, car_agent):
        """Send 'started_inspection' to CarAgent via direct message.

        Notifies the car that it is now being inspected so it can
        transition to the WaitingInspection state.

        Args:
            car_agent: Target CarAgent instance.
        """
        try:
            if car_agent and hasattr(car_agent, "handle"):
                car_agent.handle({"type": "started_inspection"})
                logger.info(f"[InspectionStation] Sent started_inspection to {car_agent.car_id}")
            else:
                logger.error(
                    "[InspectionStation] Cannot send started_inspection - invalid target agent"
                )
        except Exception as e:
            logger.error(f"[InspectionStation] Error sending started_inspection: {str(e)}")

    # --- State Callbacks ---

    def on_enter_waiting_for_car(self):
        """Entry actions for waiting_for_car state."""
        logger.info("[InspectionStation] Waiting for next car")
        self._publish_inspection_results()

    def on_exit_waiting_for_car(self):
        """Exit actions for waiting_for_car state."""
        self._notify_car_inspection_started()

    def on_enter_passed_inspection(self):
        """Entry actions for passed_inspection state (transient)."""
        logger.info(
            f"[InspectionStation] Car {self.current_car.car_id if self.current_car else 'Unknown'} passed inspection"
        )
        self._schedule_return_to_inspecting()

    def on_enter_add_fault(self):
        """Entry actions for add_fault state (transient)."""
        self._add_fault_to_car()
        self._schedule_return_to_inspecting()

    # --- Action Implementations ---

    def _publish_inspection_results(self):
        """Publish inspection results for the car that just finished inspection.

        Sends finished_inspection to the car, then writes pass/fail status
        and individual fault details to external MQTT topics.
        """
        if self.current_car is None:
            return

        car_id = self.current_car.car_id

        # Prevent duplicate processing for the same car in the same inspection cycle
        if self._last_processed_car == car_id:
            logger.info(f"[InspectionStation] Car {car_id} already completed this inspection cycle")
            self.current_car = None
            return

        self._last_processed_car = car_id

        # Notify car that inspection is finished
        self.send_finished_inspection(self.current_car)

        # Publish results to external MQTT topics
        try:
            faults = self.current_car.faults
            result = "pass" if not faults else "fail"
            self.write_inspection_result(car_id, result)

            if faults:
                self.write_inspection_faults(car_id, faults)
        except Exception as e:
            logger.error(f"[InspectionStation] Error publishing MQTT messages: {str(e)}")

    def _notify_car_inspection_started(self):
        """Notify the current car that inspection has started."""
        if self.current_car is not None:
            self.send_started_inspection(self.current_car)

    def _add_fault_to_car(self):
        """Add the newest fault to the current car's fault list."""
        if self.current_car is not None and self.newest_fault is not None:
            if self.newest_fault not in self.current_car.faults:
                self.current_car.faults.append(self.newest_fault)
                logger.info(
                    f"[InspectionStation] Added fault {self.newest_fault} to car {self.current_car.car_id}"
                )
            else:
                logger.info(
                    f"[InspectionStation] Fault {self.newest_fault} already exists for car {self.current_car.car_id}"
                )
            logger.info(
                f"[InspectionStation] Car {self.current_car.car_id} now has faults: {self.current_car.faults}"
            )

    def _schedule_return_to_inspecting(self):
        """Schedule a delayed return to inspecting_car state.

        Uses a short delay for state stability before triggering
        the automatic return transition.
        """

        def delayed_return():
            delay = self.bus._config.get("performance", {}).get("state_stability_delay", 0.005)
            time.sleep(delay)
            try:
                self.return_to_inspecting()
            except Exception as e:
                logger.error(f"[InspectionStation] Error returning to inspecting: {str(e)}")

        threading.Thread(target=delayed_return, daemon=True).start()

    # --- Communication Interface Helpers ---

    def write_inspection_result(self, car_id, result, qos=2):
        """Write external data point: publish pass/fail to 'inspection_pass_fail' MQTT topic.

        Scope: external | Direction: outgoing
        Used in 'waiting_for_car' state after inspection completes.

        Args:
            car_id: Identifier of the inspected car.
            result: 'pass' or 'fail'.
            qos: MQTT quality of service level.
        """
        payload = json.dumps({"car_id": car_id, "result": result})
        self.bus.publish_mqtt("inspection_pass_fail", payload, qos=qos)
        logger.info(f"[InspectionStation] Published to inspection_pass_fail: {payload}")

    def write_inspection_faults(self, car_id, faults, qos=2):
        """Write external data point: publish fault details to 'inspection_faults' MQTT topic.

        Scope: external | Direction: outgoing
        Used in 'waiting_for_car' state when car has faults.

        Args:
            car_id: Identifier of the inspected car.
            faults: List of fault identifiers found during inspection.
            qos: MQTT quality of service level.
        """
        for fault in faults:
            payload = json.dumps({"car_id": car_id, "fault": f"fault{fault}"})
            self.bus.publish_mqtt("inspection_faults", payload, qos=qos)
            logger.info(f"[InspectionStation] Published to inspection_faults: {payload}")

    # --- Lifecycle ---

    def set_mqtt_agent(self, mqtt_agent):
        """
        Set reference to the communication agent for MQTT messaging.

        Args:
            mqtt_agent: CommunicationAgent instance
        """
        self.mqtt_agent = mqtt_agent

    def stop(self):
        """Stop the inspection station agent."""
        super().stop()
        logger.info("[InspectionStation] Agent stopped")

    def get_status_summary(self):
        """
        Get a summary of the inspection station's current status.

        Returns:
            dict: Status information including current state and car being inspected
        """
        return {
            "state": self.state,
            "current_car": self.current_car.car_id if self.current_car else None,
            "newest_fault": self.newest_fault,
        }
