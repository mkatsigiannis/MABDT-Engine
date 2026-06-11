"""GUI-side controller for simulation lifecycle and background threading.

Wraps `SimulationInterface` and exposes Qt signals for `initialized`,
`started`, `stopped`, `data_updated`, `error_occurred`, and
`status_changed` so the main window stays decoupled from the simulation
thread.
"""

import logging
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from mabdt.exceptions import CommunicationError, ConfigurationError, SimulationError
from tiger_motors_dt.simulation.interface import SimulationInterface
from tiger_motors_dt.widgets.worker import EnvironmentWorker

# Configure logging for this module
logger = logging.getLogger(__name__)


class SimulationController(QObject):
    """Controller for simulation lifecycle and background threading.

    All access to the simulation goes through `SimulationInterface`; the
    controller exposes Qt signals so the GUI can react without touching
    the simulation thread directly.

    Signals:
        simulation_initialized: simulation system is ready
        simulation_started: production tracking has started
        simulation_stopped: production tracking has stopped
        data_updated(dict): refreshed simulation data
        error_occurred(str): a simulation-side error
        status_changed(SystemStatus): system status changed
    """

    # Signals for thread-safe communication with GUI components
    simulation_initialized = Signal()
    simulation_started = Signal()
    simulation_stopped = Signal()
    data_updated = Signal(dict)
    error_occurred = Signal(str)
    status_changed = Signal(object)  # SystemStatus DTO

    def __init__(self):
        """Initialize the simulation controller with SimulationInterface."""
        super().__init__()

        # Core simulation interface - our only connection to simulation system
        self.interface = SimulationInterface()

        # Threading components
        self.worker: EnvironmentWorker | None = None
        self.thread: QThread | None = None

        # Data refresh timer for periodic updates
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_data)
        self.refresh_interval_ms = 100  # Default 100ms refresh rate

        # State tracking
        self._initialized = False
        self._production_running = False
        self._last_error_time = 0

        # Thread safety locks
        self._state_lock = threading.RLock()

        logger.info("SimulationController initialized")

    def initialize(self) -> bool:
        """
        Initialize simulation system in background thread.

        This method sets up the simulation environment, configures threading,
        and establishes communication channels. All initialization is performed
        through the SimulationInterface to maintain clean separation.

        Returns:
            bool: True if initialization successful, False otherwise

        Emits:
            simulation_initialized: On successful initialization
            error_occurred: On initialization failure
        """
        with self._state_lock:
            if self._initialized:
                logger.warning("Simulation already initialized")
                return True

            try:
                logger.info("Initializing simulation system...")

                # Initialize the simulation through interface
                success = self.interface.initialize()
                if not success:
                    error_msg = "Simulation interface initialization returned False"
                    logger.error(error_msg)
                    self.error_occurred.emit(error_msg)
                    return False

                # Set up background threading for simulation
                self._setup_threading()

                # Start data refresh timer
                self.refresh_timer.start(self.refresh_interval_ms)

                self._initialized = True
                logger.info("Simulation system initialized successfully")
                self.simulation_initialized.emit()

                # Emit initial status
                self._emit_status_update()

                return True

            except (SimulationError, ConfigurationError, CommunicationError) as e:
                error_msg = f"Simulation initialization failed: {e}"
                logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return False
            except Exception as e:
                error_msg = f"Unexpected error during initialization: {e}"
                logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return False

    def _setup_threading(self):
        """
        Set up background threading for simulation processing.

        This creates and configures the worker thread that will run the
        simulation engine in the background, keeping the GUI responsive.
        """
        try:
            # Get the environment instance through the interface
            # Note: This is a temporary bridge until full extraction is complete
            environment = self.interface._environment

            if environment:
                # Create worker object for background processing
                self.worker = EnvironmentWorker(environment)

                # Create thread and move worker to it
                self.thread = QThread()
                self.worker.moveToThread(self.thread)

                # Connect thread lifecycle signals
                self.thread.started.connect(self.worker.run)
                self.thread.finished.connect(self._on_thread_finished)

                # Start the background thread
                self.thread.start()

                logger.info("Background threading set up successfully")
            else:
                logger.warning("No environment available for threading setup")

        except Exception as e:
            error_msg = f"Failed to set up threading: {e}"
            logger.error(error_msg)
            self.error_occurred.emit(error_msg)

    def _on_thread_finished(self):
        """Handle cleanup when background thread finishes."""
        logger.info("Background simulation thread finished")

    def start_production(self) -> bool:
        """
        Start production tracking in the simulation.

        This method initiates production monitoring, which activates all agents
        and begins tracking production metrics. All operations are performed
        through the SimulationInterface.

        Returns:
            bool: True if production started successfully, False otherwise

        Emits:
            simulation_started: On successful production start
            error_occurred: On production start failure
        """
        with self._state_lock:
            try:
                if not self._initialized:
                    error_msg = "Cannot start production: simulation not initialized"
                    logger.warning(error_msg)
                    self.error_occurred.emit(error_msg)
                    return False

                if self._production_running:
                    logger.warning("Production is already running")
                    return True

                logger.info("Starting production tracking...")
                success = self.interface.start_production()

                if success:
                    self._production_running = True
                    logger.info("Production tracking started successfully")
                    self.simulation_started.emit()
                    self._emit_status_update()
                    return True
                else:
                    error_msg = "Failed to start production tracking"
                    logger.error(error_msg)
                    self.error_occurred.emit(error_msg)
                    return False

            except SimulationError as e:
                error_msg = f"Simulation error starting production: {e}"
                logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return False
            except Exception as e:
                error_msg = f"Unexpected error starting production: {e}"
                logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return False

    def stop_production(self) -> bool:
        """
        Stop production tracking in the simulation.

        This method halts production monitoring, which pauses all agents
        and stops tracking production metrics. All operations are performed
        through the SimulationInterface.

        Returns:
            bool: True if production stopped successfully, False otherwise

        Emits:
            simulation_stopped: On successful production stop
            error_occurred: On production stop failure
        """
        with self._state_lock:
            try:
                if not self._initialized:
                    error_msg = "Cannot stop production: simulation not initialized"
                    logger.warning(error_msg)
                    self.error_occurred.emit(error_msg)
                    return False

                if not self._production_running:
                    logger.warning("Production is not currently running")
                    return True

                logger.info("Stopping production tracking...")
                success = self.interface.stop_production()

                if success:
                    self._production_running = False
                    logger.info("Production tracking stopped successfully")
                    self.simulation_stopped.emit()
                    self._emit_status_update()
                    return True
                else:
                    error_msg = "Failed to stop production tracking"
                    logger.error(error_msg)
                    self.error_occurred.emit(error_msg)
                    return False

            except SimulationError as e:
                error_msg = f"Simulation error stopping production: {e}"
                logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return False
            except Exception as e:
                error_msg = f"Unexpected error stopping production: {e}"
                logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return False

    def get_current_data(self) -> dict[str, Any]:
        """
        Get current simulation data for GUI display.

        This method retrieves all current simulation state information
        through the SimulationInterface, providing a complete data snapshot
        for GUI components to display.

        Returns:
            Dict containing current simulation data with keys:
            - system_status: SystemStatus DTO
            - production_metrics: ProductionMetrics DTO
            - workstation_statuses: Dict of workstation status data
            - active_cars: List of active car status data
            - finished_cars: List of finished car status data
            - inspection_station: InspectionStationStatus DTO
        """
        try:
            if not self._initialized:
                return {}

            # Gather all data through SimulationInterface
            data = {
                "system_status": self.interface.get_system_status(),
                "production_metrics": self.interface.get_production_metrics(),
                "workstation_statuses": self.interface.get_all_workstation_statuses(),
                "active_cars": self.interface.get_active_cars(),
                "finished_cars": self.interface.get_finished_cars(),
                "inspection_station": self.interface.get_inspection_station_status(),
                "timestamp": time.time(),
            }

            return data

        except Exception as e:
            # Limit error message frequency to avoid spam
            current_time = time.time()
            if (current_time - self._last_error_time) > 5:
                error_msg = f"Error retrieving simulation data: {e}"
                logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                self._last_error_time = current_time

            return {}

    def _refresh_data(self):
        """
        Periodic data refresh method called by timer.

        This method retrieves current simulation data and emits the data_updated
        signal to notify GUI components of new information. It runs on a timer
        to provide regular updates without overwhelming the interface.
        """
        try:
            # Get current data and emit to listeners
            current_data = self.get_current_data()
            if current_data:
                self.data_updated.emit(current_data)

        except Exception as e:
            # Limit error frequency to avoid spam
            current_time = time.time()
            if (current_time - self._last_error_time) > 10:
                logger.error(f"Error in data refresh: {e}")
                self._last_error_time = current_time

    def _emit_status_update(self):
        """Emit current system status update."""
        try:
            status = self.interface.get_system_status()
            self.status_changed.emit(status)
        except Exception as e:
            logger.error(f"Error emitting status update: {e}")

    def set_refresh_interval(self, interval_ms: int):
        """
        Set the data refresh interval.

        Args:
            interval_ms: Refresh interval in milliseconds
        """
        if interval_ms > 0:
            self.refresh_interval_ms = interval_ms
            if self.refresh_timer.isActive():
                self.refresh_timer.stop()
                self.refresh_timer.start(interval_ms)
            logger.info(f"Data refresh interval set to {interval_ms}ms")
        else:
            logger.warning("Invalid refresh interval, must be > 0")

    def is_initialized(self) -> bool:
        """Check if simulation is initialized."""
        return self._initialized

    def is_production_running(self) -> bool:
        """Check if production is currently running."""
        return self._production_running

    def shutdown(self):
        """
        Gracefully shutdown the simulation controller.

        This method stops all timers, shuts down background threads,
        stops production if running, and cleans up all resources.
        Should be called when the application is closing.
        """
        with self._state_lock:
            logger.info("Shutting down SimulationController...")

            try:
                # Stop data refresh timer
                if self.refresh_timer.isActive():
                    self.refresh_timer.stop()

                # Stop production if running
                if self._production_running:
                    self.stop_production()

                # Clean up worker and thread
                if self.worker:
                    self.worker.deleteLater()
                    self.worker = None

                if self.thread and self.thread.isRunning():
                    # Try graceful shutdown first
                    self.thread.quit()
                    if not self.thread.wait(5000):  # Wait up to 5 seconds
                        logger.warning("Force terminating simulation thread...")
                        self.thread.terminate()
                        self.thread.wait(2000)
                    self.thread = None

                # Shutdown simulation interface
                if self._initialized:
                    self.interface.shutdown()

                self._initialized = False
                logger.info("SimulationController shutdown complete")

            except Exception as e:
                logger.error(f"Error during SimulationController shutdown: {e}")
                # Continue with shutdown even if errors occur
