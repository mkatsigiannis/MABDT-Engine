#!/usr/bin/env python3
"""Synthetic MQTT generator that exercises the Digital Twin without the lab.

Publishes scanner and PLC traffic for 15 workstations plus the
inspection station, with configurable cycle-time distributions and
fault rates. Used for development against the live MQTT pipeline.

Run `python -m tiger_motors_dt.tools.data_generator --help` for flags.
"""

import argparse
import random
import sys
import threading
import time
from typing import Any

import numpy as np
import paho.mqtt.client as mqtt

from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class DataGenerator:
    """Publishes a full synthetic production run to MQTT.

    Example:
        from tiger_motors_dt.config import load_config
        generator = DataGenerator(config=load_config(), number_of_cars=25)
        generator.run()

        # Using with custom settings
        generator = DataGenerator(
            mqtt_host="localhost",
            mqtt_port=1883,
            number_of_cars=50
        )
        generator.run()
    """

    # Default simulation parameters
    DEFAULT_TRIANG_MIN = 50  # Minimum cycle time (seconds)
    DEFAULT_TRIANG_MODE = 60  # Most common cycle time (seconds)
    DEFAULT_TRIANG_MAX = 70  # Maximum cycle time (seconds)
    DEFAULT_WS_FAULT_PROBABILITY = 0.05  # Workstation fault probability
    DEFAULT_IS_FAULT_PROBABILITY = 0.15  # Inspection station fault probability
    DEFAULT_UNFIXABLE_PROBABILITY = 0.0  # Unfixable fault probability

    # Cell mapping for MQTT topics (workstation index -> cell number)
    CELL_FROM_WORKSTATION = {
        0: 1,
        1: 1,
        2: 1,
        3: 1,
        4: 1,  # Cell 1: WS 1-5
        5: 2,
        6: 2,
        7: 2,
        8: 2,
        9: 2,  # Cell 2: WS 6-10
        10: 3,
        11: 3,
        12: 3,
        13: 3,
        14: 3,  # Cell 3: WS 11-15
    }

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        mqtt_host: str | None = None,
        mqtt_port: int | None = None,
        number_of_cars: int = 35,
        triang_min: float | None = None,
        triang_mode: float | None = None,
        triang_max: float | None = None,
        ws_fault_probability: float | None = None,
        is_fault_probability: float | None = None,
        unfixable_probability: float | None = None,
    ):
        """
        Initialize the data generator with configuration options.

        Configuration priority (highest to lowest):
        1. Explicit parameters (mqtt_host, mqtt_port, etc.)
        2. config dictionary values
        3. Default values

        Args:
            config: Optional configuration dictionary (typically from `load_config()`)
            mqtt_host: MQTT broker hostname (overrides config)
            mqtt_port: MQTT broker port (overrides config)
            number_of_cars: Total cars to simulate (minimum 15)
            triang_min: Minimum cycle time in seconds
            triang_mode: Mode (most common) cycle time in seconds
            triang_max: Maximum cycle time in seconds
            ws_fault_probability: Probability of workstation fault (0.0-1.0)
            is_fault_probability: Probability of inspection fault (0.0-1.0)
            unfixable_probability: Probability that a fault is unfixable (0.0-1.0)
        """
        # Store config for reference
        self.config = config or {}

        # MQTT configuration - parameter > config > default
        mqtt_config = self.config.get("mqtt", {})
        self.mqtt_host = mqtt_host or mqtt_config.get("host", "localhost")
        self.mqtt_port = mqtt_port or mqtt_config.get("port", 8883)

        # Timing parameters
        self.triang_min = triang_min or self.DEFAULT_TRIANG_MIN
        self.triang_mode = triang_mode or self.DEFAULT_TRIANG_MODE
        self.triang_max = triang_max or self.DEFAULT_TRIANG_MAX

        # Fault probabilities
        self.ws_fault_probability = (
            ws_fault_probability
            if ws_fault_probability is not None
            else self.DEFAULT_WS_FAULT_PROBABILITY
        )
        self.is_fault_probability = (
            is_fault_probability
            if is_fault_probability is not None
            else self.DEFAULT_IS_FAULT_PROBABILITY
        )
        self.unfixable_probability = (
            unfixable_probability
            if unfixable_probability is not None
            else self.DEFAULT_UNFIXABLE_PROBABILITY
        )

        # Ensure minimum car count (need at least 15 to populate all workstations)
        self.number_of_cars = max(number_of_cars, 15)

        # Initialize workstation infrastructure
        self.workstations = list(range(15))

        # Create initial car population with random types
        car_types = [
            f"SUV{i}" if random.randint(0, 1) == 1 else f"SPEEDSTER{i}"
            for i in range(self.number_of_cars)
        ]

        # Distribute cars: one per workstation queue, rest at WS0
        self.cars_in_queues: dict[int, list[str]] = {i: [car_types.pop(0)] for i in range(15)}
        self.cars_in_queues[0].extend(car_types)

        # Workstation availability tracking
        self.workstation_free: dict[int, bool] = {i: True for i in self.workstations}

        # Thread synchronization locks
        self.ws_locks: dict[int, threading.Lock] = {i: threading.Lock() for i in self.workstations}
        self.free_locks: dict[int, threading.Lock] = {
            i: threading.Lock() for i in self.workstations
        }

        # Production tracking
        self.total_cars_finished = 0
        self.inspection_queue: list[str] = []
        self.unfixable_count = 0
        self.unfixable_lock = threading.Lock()

        # MQTT client (initialized on first run)
        self.mqtt_client: mqtt.Client | None = None
        self._running = False

        logger.info(
            f"DataGenerator initialized: {self.number_of_cars} cars, "
            f"MQTT {self.mqtt_host}:{self.mqtt_port}"
        )

    def _init_mqtt(self) -> None:
        """Initialize MQTT client connection."""
        try:
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.on_connect = self._on_connect
            self.mqtt_client.on_disconnect = self._on_disconnect

            logger.info(f"Connecting to MQTT broker at {self.mqtt_host}:{self.mqtt_port}")
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.mqtt_client.loop_start()

        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def _on_connect(self, client, userdata, flags, rc) -> None:
        """Handle MQTT connection events."""
        if rc == 0:
            logger.info(f"Connected to MQTT broker (result code: {rc})")
        else:
            logger.warning(f"MQTT connection returned code: {rc}")

    def _on_disconnect(self, client, userdata, rc) -> None:
        """Handle MQTT disconnection events."""
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection (code: {rc})")

    def _make_car(self, ws_index: int, prev_q_lock: int, next_q_lock: int | None) -> None:
        """
        Simulate car assembly at a workstation.

        This method runs in a separate thread and simulates the complete
        assembly cycle for a car at the specified workstation.

        Args:
            ws_index: Workstation index (0-14)
            prev_q_lock: Index of the queue to pull car from
            next_q_lock: Index of the queue to push car to (None if last WS)
        """
        # Mark workstation as busy
        with self.free_locks[ws_index]:
            self.workstation_free[ws_index] = False

        # Simulate time to grab car from queue
        time.sleep(np.random.uniform(1.0, 3.0))

        # Get car from previous queue
        if prev_q_lock is not None:
            with self.ws_locks[prev_q_lock]:
                temp_car = self.cars_in_queues[prev_q_lock].pop(0)
        else:
            temp_car = "UNKNOWN"

        # Publish car scan message
        cell = self.CELL_FROM_WORKSTATION[ws_index]
        topic = f"scanner/C{cell}WS{ws_index + 1}"
        logger.info(f"[WS{ws_index + 1}] Starting assembly: {temp_car}")
        self.mqtt_client.publish(topic, temp_car, qos=2, retain=False)

        # Simulate assembly time with triangular distribution
        assembly_time = round(
            np.random.triangular(self.triang_min, self.triang_mode, self.triang_max), 2
        )
        time.sleep(assembly_time)

        # Fault injection logic
        unrepairable = False
        fault = False

        if random.random() < self.ws_fault_probability:
            fault = True
            if random.random() < self.unfixable_probability:
                # Unfixable fault - car is scrapped
                unrepairable = True
                with self.unfixable_lock:
                    self.unfixable_count += 1
                logger.warning(f"[WS{ws_index + 1}] UNFIXABLE FAULT: {temp_car} removed from line")
                self.mqtt_client.publish(topic, "FAULT5", qos=2, retain=False)
            else:
                # Repairable fault - supervisor called
                fault_code = random.randint(1, 4)
                logger.warning(f"[WS{ws_index + 1}] Fault {fault_code}: {temp_car}")
                self.mqtt_client.publish(topic, f"fault{fault_code}", qos=2, retain=False)
                time.sleep(random.randint(1, self.triang_max))

        if not unrepairable:
            # Publish assembly complete
            logger.info(f"[WS{ws_index + 1}] Completed: {temp_car} ({assembly_time:.1f}s)")
            self.mqtt_client.publish(topic, temp_car, qos=2, retain=False)

            if not fault:
                # Normal flow - move to next workstation or inspection
                if next_q_lock is not None:
                    with self.ws_locks[next_q_lock]:
                        self.cars_in_queues[next_q_lock].append(temp_car)
                else:
                    self.inspection_queue.append(temp_car)
            else:
                # Fault occurred - send car back to random earlier workstation
                rework_ws = random.randint(0, ws_index)
                with self.ws_locks[rework_ws]:
                    self.cars_in_queues[rework_ws].insert(0, temp_car)
                logger.info(f"[WS{ws_index + 1}] Rework: {temp_car} -> WS{rework_ws + 1}")

        # Mark workstation as free
        with self.free_locks[ws_index]:
            self.workstation_free[ws_index] = True

    def _inspect_car(self, car: str) -> None:
        """
        Simulate car inspection at the inspection station.

        Args:
            car: Car identifier to inspect
        """
        topic = "scanner/C3InspectionStation1"

        logger.info(f"[Inspection] Starting: {car}")
        self.mqtt_client.publish(topic, car, qos=2, retain=False)
        time.sleep(2)

        if random.random() < self.is_fault_probability:
            # Generate random faults (1-3 faults from fault types 1-4)
            num_faults = random.randint(1, 3)
            faults = random.sample([1, 2, 3, 4], num_faults)
            for fault_code in faults:
                logger.warning(f"[Inspection] Fault {fault_code}: {car}")
                self.mqtt_client.publish(topic, f"fault{fault_code}", qos=2, retain=False)
                time.sleep(1)
        else:
            logger.info(f"[Inspection] PASSED: {car}")
            self.mqtt_client.publish(topic, "pass", qos=2, retain=False)
            time.sleep(2)

        # Complete inspection
        self.mqtt_client.publish(topic, car, qos=2, retain=False)
        self.total_cars_finished += 1
        logger.info(
            f"[Inspection] Complete: {car} ({self.total_cars_finished}/{self.number_of_cars})"
        )

    def run(self) -> None:
        """
        Run the complete production simulation.

        This method orchestrates the entire simulation, starting assembly
        at all workstations and managing the flow of cars through the
        production line until all cars are completed.
        """
        logger.info("=" * 60)
        logger.info("Tiger Motors Data Generator Starting")
        logger.info(f"  Cars to process: {self.number_of_cars}")
        logger.info(
            f"  Cycle time: {self.triang_min}-{self.triang_max}s (mode: {self.triang_mode}s)"
        )
        logger.info(f"  WS fault rate: {self.ws_fault_probability:.1%}")
        logger.info(f"  Inspection fault rate: {self.is_fault_probability:.1%}")
        logger.info("=" * 60)

        # Initialize MQTT connection
        self._init_mqtt()
        self._running = True

        # Set all workstations to green andon light
        for ws_idx in self.workstations:
            cell = self.CELL_FROM_WORKSTATION[ws_idx]
            topic = f"plc/C{cell}WS{ws_idx + 1}/GRN"
            self.mqtt_client.publish(topic, "True", qos=2, retain=False)

        threads: list[threading.Thread] = []

        # Start first car at WS1
        thread = threading.Thread(target=self._make_car, args=(0, 0, 1), daemon=True)
        threads.append(thread)
        thread.start()

        # Main production loop
        try:
            while (
                self._running
                and (self.total_cars_finished + self.unfixable_count) < self.number_of_cars
            ):
                # Check each workstation for available work
                for ws_idx in self.workstations:
                    with self.free_locks[ws_idx]:
                        if self.workstation_free[ws_idx] and len(self.cars_in_queues[ws_idx]) > 0:
                            prev_ws = ws_idx
                            next_ws = ws_idx + 1 if ws_idx < 14 else None

                            thread = threading.Thread(
                                target=self._make_car,
                                args=(ws_idx, prev_ws, next_ws),
                                daemon=True,
                            )
                            threads.append(thread)
                            thread.start()

                # Check inspection queue
                if self.inspection_queue:
                    car = self.inspection_queue.pop(0)
                    thread = threading.Thread(target=self._inspect_car, args=(car,), daemon=True)
                    threads.append(thread)
                    thread.start()

                # Small delay for synchronization
                time.sleep(0.1)

            # Wait for all threads to complete
            for thread in threads:
                thread.join(timeout=5.0)

        except KeyboardInterrupt:
            logger.info("Simulation interrupted by user")
            self._running = False

        finally:
            # Cleanup
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()

        # Final summary
        logger.info("=" * 60)
        logger.info("Simulation Complete")
        logger.info(f"  Cars finished: {self.total_cars_finished}")
        logger.info(f"  Cars scrapped: {self.unfixable_count}")
        logger.info(f"  Remaining in queues: {sum(len(q) for q in self.cars_in_queues.values())}")
        logger.info("=" * 60)

    def stop(self) -> None:
        """Stop the simulation gracefully."""
        logger.info("Stopping data generator...")
        self._running = False


def main():
    """Command-line entry point for the data generator."""
    parser = argparse.ArgumentParser(
        description="Tiger Motors Production Data Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default settings (35 cars)
  python -m tools.data_generator

  # Run with more cars
  python -m tools.data_generator --cars 100

  # Run with custom MQTT broker
  python -m tiger_motors_dt.tools.data_generator --host localhost --port 1883

  # Enable workstation faults (5% chance)
  python -m tools.data_generator --ws-fault-rate 0.05

  # Fast simulation (shorter cycle times)
  python -m tools.data_generator --min-time 5 --mode-time 10 --max-time 15
        """,
    )

    # MQTT options
    parser.add_argument(
        "--host",
        "-H",
        type=str,
        default=None,
        help="MQTT broker hostname (default: from config.json)",
    )
    parser.add_argument(
        "--port",
        "-P",
        type=int,
        default=None,
        help="MQTT broker port (default: from config.json)",
    )

    # Simulation options
    parser.add_argument(
        "--cars",
        "-n",
        type=int,
        default=35,
        help="Number of cars to simulate (default: 35, minimum: 15)",
    )
    parser.add_argument(
        "--min-time",
        type=float,
        default=None,
        help="Minimum cycle time in seconds (default: 20)",
    )
    parser.add_argument(
        "--mode-time",
        type=float,
        default=None,
        help="Mode (most common) cycle time in seconds (default: 30)",
    )
    parser.add_argument(
        "--max-time",
        type=float,
        default=None,
        help="Maximum cycle time in seconds (default: 40)",
    )

    # Fault injection options
    parser.add_argument(
        "--ws-fault-rate",
        type=float,
        default=None,
        help="Workstation fault probability 0.0-1.0 (default: 0.0)",
    )
    parser.add_argument(
        "--is-fault-rate",
        type=float,
        default=None,
        help="Inspection station fault probability 0.0-1.0 (default: 0.2)",
    )
    parser.add_argument(
        "--unfixable-rate",
        type=float,
        default=None,
        help="Unfixable fault probability 0.0-1.0 (default: 0.0)",
    )

    # Configuration file option
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to configuration file (default: config.json)",
    )

    args = parser.parse_args()

    # Load configuration if available
    config = None
    try:
        from tiger_motors_dt.config import DEFAULT_CONFIG_PATH, load_config

        config = load_config(args.config or DEFAULT_CONFIG_PATH)
    except Exception as e:
        logger.warning(f"Could not load config.json: {e}. Using defaults.")

    # Create and run generator
    generator = DataGenerator(
        config=config,
        mqtt_host=args.host,
        mqtt_port=args.port,
        number_of_cars=args.cars,
        triang_min=args.min_time,
        triang_mode=args.mode_time,
        triang_max=args.max_time,
        ws_fault_probability=args.ws_fault_rate,
        is_fault_probability=args.is_fault_rate,
        unfixable_probability=args.unfixable_rate,
    )

    try:
        generator.run()
    except KeyboardInterrupt:
        generator.stop()
        logger.info("Data generator stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Data generator failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
