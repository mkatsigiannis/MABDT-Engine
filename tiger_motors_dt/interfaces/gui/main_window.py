"""Main window for the Tiger Motors GUI.

Owns the QMainWindow and delegates work to three collaborators:
`SimulationController` (lifecycle + threading), `TabManager` (tab
construction), and `DisplayUpdateManager` (DTO-driven refresh).
"""

import logging
import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

# Import managers and controllers
from tiger_motors_dt.interfaces.gui.controllers.simulation_controller import SimulationController
from tiger_motors_dt.interfaces.gui.managers.display_manager import DisplayUpdateManager
from tiger_motors_dt.interfaces.gui.managers.tab_manager import TabManager

# LLM_AVAILABLE is True iff the optional `ollama` extra is installed;
# it guards the LLM chat widget construction below.
from tiger_motors_dt.widgets import LLM_AVAILABLE

logger = logging.getLogger(__name__)


class TigerMotorsDTGUI(QMainWindow):
    """Tiger Motors GUI main window — coordinates controller, tabs, and display refresh."""

    def __init__(self):
        super().__init__()

        # Window configuration
        self.setWindowTitle("Tiger Motors Digital Twin - Production Monitor & Configuration")
        self.setGeometry(100, 100, 1400, 800)

        # Initialize managers and controllers
        self.simulation_controller = SimulationController()
        self.tab_manager = TabManager(self)
        self.display_manager = DisplayUpdateManager(self)

        # Component state tracking
        self.environment = None  # Will be set by simulation controller
        self.iface = None  # SimulationInterface, set when the controller initializes
        self._initialization_complete = False

        # Setup the application
        self.setup_ui()
        self.connect_signals()
        self.initialize_simulation()

        logger.info("Simplified main window initialized")

    def setup_ui(self):
        """
        Setup user interface using the TabManager.

        This method delegates all UI creation to the TabManager, keeping
        the main window focused on coordination rather than UI details.
        """
        try:
            # Create central widget
            central_widget = QWidget()
            self.setCentralWidget(central_widget)

            # Create main layout
            main_layout = QVBoxLayout()

            # Create tab widget using TabManager
            self.tab_widget = self.tab_manager.create_all_tabs()
            main_layout.addWidget(self.tab_widget)

            # Apply layout to central widget
            central_widget.setLayout(main_layout)

            # Setup status bar
            self.statusBar().showMessage("Tiger Motors Digital Twin - Initializing...")

            logger.info("UI setup completed using TabManager")

        except Exception as e:
            logger.error(f"Error in UI setup: {e}")
            self.statusBar().showMessage(f"UI Setup Error: {e}")

    def connect_signals(self):
        """
        Connect signals between managers, controllers, and main window.

        This establishes the communication pathways between components:
        - Simulation controller events to main window
        - Tab manager events to main window
        - Display manager events to status updates
        - Production control signals to simulation controller
        """
        try:
            # Connect simulation controller signals
            self.simulation_controller.simulation_initialized.connect(
                self.on_simulation_initialized
            )
            self.simulation_controller.simulation_started.connect(self.on_simulation_started)
            self.simulation_controller.simulation_stopped.connect(self.on_simulation_stopped)
            self.simulation_controller.error_occurred.connect(self.on_simulation_error)
            self.simulation_controller.data_updated.connect(self.on_data_updated)

            # Connect display manager signals
            self.display_manager.status_updated.connect(self.statusBar().showMessage)
            self.display_manager.error_occurred.connect(self.on_display_error)

            # Connect production control signals (from tab widgets)
            self._connect_production_control_signals()

            logger.info("Signal connections established")

        except Exception as e:
            logger.error(f"Error connecting signals: {e}")

    def _connect_production_control_signals(self):
        """Connect production control widget signals to simulation controller."""
        try:
            # Get production control widget from tab manager
            production_tab = self.tab_manager.get_tab("Production Monitor")
            if production_tab and hasattr(self, "production_control"):
                # Connect production control signals to simulation controller
                self.production_control.production_started.connect(self.start_production)
                self.production_control.production_stopped.connect(self.stop_production)
                logger.debug("Production control signals connected")
        except Exception as e:
            logger.warning(f"Could not connect production control signals: {e}")

    def initialize_simulation(self):
        """
        Initialize simulation system using the SimulationController.

        This delegates simulation initialization to the controller,
        keeping the main window focused on coordination.
        """
        try:
            # Start simulation initialization in background
            success = self.simulation_controller.initialize()
            if not success:
                self.statusBar().showMessage("Simulation initialization failed")
                logger.error("Simulation controller initialization failed")
            else:
                logger.info("Simulation initialization started")

        except Exception as e:
            error_msg = f"Error initializing simulation: {e}"
            logger.error(error_msg)
            self.statusBar().showMessage(error_msg)

    def on_simulation_initialized(self):
        """
        Handle simulation initialization completion.

        This is called when the simulation controller has successfully
        initialized the simulation environment.
        """
        try:
            # Get interface + environment references from the simulation
            # controller. The display manager reads through `self.iface`
            # (DTO-only path); the environment is exposed as an explicit
            # escape hatch for the agent_inspector debug widget and for
            # services that still need a bus reference.
            self.iface = self.simulation_controller.interface
            self.environment = self.iface.get_environment()

            # Set environment reference for widgets that need it
            self._setup_environment_references()

            # Start display updates now that simulation is ready
            self.display_manager.start_updates()

            # Subscribe display manager to EventBus for system messages
            if self.environment and hasattr(self.environment, "bus"):
                self.environment.bus.subscribe(
                    "system_message", self.display_manager.add_system_message
                )
                logger.debug("Display manager subscribed to system messages")

            # Update status
            self.statusBar().showMessage("Tiger Motors Digital Twin - Ready")
            self._initialization_complete = True

            logger.info("Simulation initialization completed successfully")

        except Exception as e:
            error_msg = f"Error in simulation initialization completion: {e}"
            logger.error(error_msg)
            self.statusBar().showMessage(error_msg)

    def _setup_environment_references(self):
        """Setup environment references for widgets that need direct access."""
        try:
            if self.environment:
                # Set environment for LLM chat widget (for RAG functionality)
                if LLM_AVAILABLE and hasattr(self, "llm_chat_widget") and self.llm_chat_widget:
                    self.llm_chat_widget.set_environment(self.environment)
                    logger.debug("Environment reference set for LLM chat widget")

                # Integrate barcode service with EventBus if available
                if hasattr(self, "barcode_service_widget") and self.barcode_service_widget:
                    self._integrate_barcode_service()
                    logger.debug("Barcode service integrated with EventBus")

                # Integrate OPC UA service with EventBus if available
                if hasattr(self, "opc_service_widget") and self.opc_service_widget:
                    self._integrate_opc_service()
                    logger.debug("OPC UA service integrated with EventBus")

        except Exception as e:
            logger.warning(f"Error setting up environment references: {e}")

    def _integrate_barcode_service(self):
        """Integrate barcode service with the simulation EventBus."""
        try:
            if self.environment and hasattr(self.environment, "bus"):
                # Check if barcode service widget has integration capability
                if hasattr(self.barcode_service_widget, "integrate_with_eventbus"):
                    self.barcode_service_widget.integrate_with_eventbus(self.environment.bus)
                elif hasattr(self.barcode_service_widget, "set_event_bus"):
                    self.barcode_service_widget.set_event_bus(self.environment.bus)
                logger.debug("Barcode service EventBus integration completed")
        except Exception as e:
            logger.warning(f"Error integrating barcode service: {e}")

    def _integrate_opc_service(self):
        """Integrate OPC UA service with the simulation EventBus."""
        try:
            if self.environment and hasattr(self.environment, "bus"):
                # Set EventBus reference for OPC UA service
                if hasattr(self.opc_service_widget, "set_event_bus"):
                    self.opc_service_widget.set_event_bus(self.environment.bus)
                logger.debug("OPC UA service EventBus integration completed")
        except Exception as e:
            logger.warning(f"Error integrating OPC UA service: {e}")

    def start_production(self):
        """
        Start production tracking using the simulation controller.

        This delegates production control to the simulation controller
        instead of handling it directly.
        """
        try:
            success = self.simulation_controller.start_production()
            if success:
                logger.info("Production started successfully")
            else:
                logger.warning("Failed to start production")
        except Exception as e:
            logger.error(f"Error starting production: {e}")

    def stop_production(self):
        """
        Stop production tracking using the simulation controller.

        This delegates production control to the simulation controller
        instead of handling it directly.
        """
        try:
            success = self.simulation_controller.stop_production()
            if success:
                logger.info("Production stopped successfully")
            else:
                logger.warning("Failed to stop production")
        except Exception as e:
            logger.error(f"Error stopping production: {e}")

    def on_simulation_started(self):
        """Handle simulation start event from controller."""
        self.statusBar().showMessage("Production tracking started")
        logger.info("Production tracking started")

    def on_simulation_stopped(self):
        """Handle simulation stop event from controller."""
        self.statusBar().showMessage("Production tracking stopped")
        logger.info("Production tracking stopped")

    def on_simulation_error(self, error_message: str):
        """
        Handle simulation errors from controller.

        Args:
            error_message: Error message from simulation controller
        """
        self.statusBar().showMessage(f"Simulation Error: {error_message}")
        logger.error(f"Simulation error: {error_message}")

    def on_display_error(self, error_message: str):
        """
        Handle display errors from display manager.

        Args:
            error_message: Error message from display manager
        """
        logger.warning(f"Display error: {error_message}")
        # Don't update status bar for display errors to avoid spam

    def on_data_updated(self, data: dict):
        """
        Handle data updates from simulation controller.

        This can be used for any main window specific processing
        of simulation data updates.

        Args:
            data: Updated simulation data
        """
        # Main window generally doesn't need to process data updates directly
        # as the DisplayUpdateManager handles all display updates
        pass

    def closeEvent(self, event):
        """
        Handle application close event with proper resource cleanup.

        This ensures all managers and controllers are properly shut down
        before the application exits.

        Args:
            event: Close event from Qt
        """
        try:
            logger.info("Shutting down Tiger Motors Digital Twin GUI...")

            # Stop display updates first
            if hasattr(self, "display_manager"):
                self.display_manager.stop_updates()
                logger.debug("Display updates stopped")

            # Clean up specific widgets with special requirements
            self._cleanup_special_widgets()

            # Stop simulation controller
            if hasattr(self, "simulation_controller"):
                self.simulation_controller.shutdown()
                logger.debug("Simulation controller shutdown")

            # Clear managers
            if hasattr(self, "tab_manager"):
                self.tab_manager.clear_all_tabs()
                logger.debug("Tab manager cleared")

            logger.info("GUI shutdown completed successfully")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            # Always accept the close event to ensure application exits
            event.accept()

    def _cleanup_special_widgets(self):
        """Clean up widgets that require special shutdown handling."""
        try:
            # Clean up LLM chat widget
            if LLM_AVAILABLE and hasattr(self, "llm_chat_widget") and self.llm_chat_widget:
                if hasattr(self.llm_chat_widget, "closeEvent"):
                    self.llm_chat_widget.closeEvent(None)
                logger.debug("LLM chat widget cleaned up")

            # Clean up barcode service widget
            if hasattr(self, "barcode_service_widget") and self.barcode_service_widget:
                if hasattr(self.barcode_service_widget, "cleanup"):
                    self.barcode_service_widget.cleanup()
                logger.debug("Barcode service widget cleaned up")

            # Clean up OPC UA service widget
            if hasattr(self, "opc_service_widget") and self.opc_service_widget:
                if hasattr(self.opc_service_widget, "cleanup"):
                    self.opc_service_widget.cleanup()
                logger.debug("OPC UA service widget cleaned up")

        except Exception as e:
            logger.warning(f"Error cleaning up special widgets: {e}")

    def get_current_data(self) -> dict:
        """
        Get current simulation data through the simulation controller.

        Returns:
            dict: Current simulation data or empty dict if not available
        """
        try:
            if self.simulation_controller and self._initialization_complete:
                return self.simulation_controller.get_current_data()
            return {}
        except Exception as e:
            logger.warning(f"Error getting current data: {e}")
            return {}

    def is_initialized(self) -> bool:
        """
        Check if the main window and all components are fully initialized.

        Returns:
            bool: True if fully initialized and ready
        """
        return (
            self._initialization_complete
            and hasattr(self, "simulation_controller")
            and self.simulation_controller.is_initialized()
        )


def main():
    """
    Main application entry point for the simplified GUI.

    This creates the application and simplified main window, demonstrating
    the clean entry point pattern.
    """
    # Create QApplication
    app = QApplication(sys.argv)

    # Set application properties
    app.setApplicationName("Tiger Motors Digital Twin")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("Auburn University")

    # Create and show the simplified main window
    window = TigerMotorsDTGUI()
    window.show()

    # Start the application event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
