"""Frozen-dataclass DTOs returned by `TigerMotorsInterface`.

Every public query method on the interface returns one of these. They
are immutable (frozen) so consumers (GUI, CLI, RAG collector) can safely
read them from any thread without synchronization.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkstationStatus:
    """
    Workstation status data transfer object.

    Represents the current status of a manufacturing workstation including
    its operational state, andon light status, time tracking metrics, and
    current car assignment.

    Attributes:
        id: Workstation identifier (e.g., "C1WS1", "C2WS5", "C3WS12")
        state: Current operational state (e.g., "idle", "busy", "yellow", "red")
        andon_color: Current andon light color ("green", "yellow", "red", "paused")
        current_car: VIN of car currently at this workstation (None if no car)
        idle_time: Total time spent in idle state (seconds as float)
        busy_time: Total time spent in busy state (seconds as float)
        yellow_time: Total time spent in yellow/caution state (seconds as float)
        red_time: Total time spent in red/stop state (seconds as float)
        is_paused: Whether the workstation is paused (not tracking production)
    """

    id: str
    state: str
    andon_color: str
    current_car: str | None
    idle_time: float
    busy_time: float
    yellow_time: float
    red_time: float
    is_paused: bool


@dataclass(frozen=True)
class CarStatus:
    """
    Car status data transfer object.

    Represents the current status of a vehicle in the manufacturing system
    including its location, production state, fault history, and timing metrics.

    Attributes:
        vin: Vehicle identification number (e.g., "SUV1", "SPEEDSTER5")
        state: Current production state (e.g., "BeingMade_AssemblyAtStation", "WaitingInspection", "Finished")
        current_workstation: Current workstation number (1-15 for assembly, 16 for inspection, None if not assigned)
        production_faults: List of fault IDs detected during assembly (workstations 1-15)
        inspection_faults: List of fault IDs detected at inspection station
        lead_time: Total production time if finished, current elapsed time if in progress (None if not started)
        starting_time: Production start timestamp as Unix epoch time
        is_finished: Whether the car has completed all production and inspection
    """

    vin: str
    state: str
    current_workstation: int | None
    production_faults: list[str]
    inspection_faults: list[str]
    lead_time: float | None
    starting_time: float
    is_finished: bool


@dataclass(frozen=True)
class InspectionStationStatus:
    """
    Inspection station status data transfer object.

    Represents the current status of the quality control inspection station
    including its operational state and the car currently being inspected.

    Attributes:
        state: Current inspection state ("waiting_for_car", "inspecting_car", "passed_inspection", "add_fault")
        current_car_vin: VIN of car currently being inspected (None if no car)
        newest_fault: Latest fault ID detected during current inspection (None if no fault)
        is_active: Whether the inspection station is actively processing a car
        is_paused: Whether the station is paused (not tracking production)
    """

    state: str
    current_car_vin: str | None
    newest_fault: str | None
    is_active: bool
    is_paused: bool


@dataclass(frozen=True)
class ProductionMetrics:
    """
    Production metrics data transfer object.

    Represents overall production system metrics including status, timing,
    throughput, and performance indicators.

    Attributes:
        is_tracking: Whether production tracking is currently active
        start_time: Production tracking start timestamp as Unix epoch time (None if not started)
        elapsed_time: Time since production started in seconds (None if not tracking)
        total_workstations: Total number of workstations in the system
        active_cars: Number of cars currently in production (not finished)
        finished_cars: Number of cars that have completed production
        cars_in_inspection: Number of cars currently at or waiting for inspection
        workstations_active: Number of workstations currently processing cars
        workstations_idle: Number of workstations currently idle
        workstations_caution: Number of workstations in yellow/caution state
        workstations_stopped: Number of workstations in red/stop state
        average_lead_time: Average lead time for completed cars (None if no completed cars)
    """

    is_tracking: bool
    start_time: float | None
    elapsed_time: float | None
    total_workstations: int
    active_cars: int
    finished_cars: int
    cars_in_inspection: int
    workstations_active: int
    workstations_idle: int
    workstations_caution: int
    workstations_stopped: int
    average_lead_time: float | None


@dataclass(frozen=True)
class SystemStatus:
    """
    Overall system status data transfer object.

    Represents the high-level status of the entire digital twin system
    including initialization state, component health, and configuration.

    Attributes:
        is_initialized: Whether the simulation environment is fully initialized
        is_production_tracking: Whether production tracking is active
        component_counts: Dictionary with counts of each component type
        mqtt_connected: Whether MQTT communication is active
        configuration_valid: Whether the current configuration is valid
        error_count: Number of errors encountered during current session
        uptime_seconds: Time since system initialization in seconds
    """

    is_initialized: bool
    is_production_tracking: bool
    component_counts: dict[str, int]
    mqtt_connected: bool
    configuration_valid: bool
    error_count: int
    uptime_seconds: float
