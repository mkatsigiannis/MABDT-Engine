"""Interactive CLI for the Tiger Motors deployment.

Drives the simulation through `SimulationInterface`. Commands:

    start | stop          start/stop production tracking
    led <topic> <state>   publish a manual LED control message
    config                print the loaded configuration
    status                print system + production status
    help                  show command help
    exit                  shut down cleanly
"""

import logging
import threading

from mabdt.exceptions import CommunicationError, ConfigurationError, SimulationError
from tiger_motors_dt.simulation.interface import SimulationInterface

# Configure logging for this module
logger = logging.getLogger(__name__)


class CLIInterface:
    """Interactive command loop over `SimulationInterface`. Call `run()` to start."""

    def __init__(self):
        """Initialize the CLI interface with SimulationInterface."""
        self.simulation = SimulationInterface()
        self.running = True
        self._command_thread: threading.Thread | None = None

        # Command registry for improved parsing
        self._commands = {
            "start": self._cmd_start_production,
            "stop": self._cmd_stop_production,
            "led": self._cmd_test_led,
            "config": self._cmd_show_config,
            "status": self._cmd_show_status,
            "help": self._cmd_show_help,
            "exit": self._cmd_exit,
            "quit": self._cmd_exit,  # Alias for exit
        }

        # Command help documentation
        self._help_docs = {
            "start": {
                "usage": "start",
                "description": "Start production tracking and resume all agents",
                "details": "Activates production monitoring, resumes all workstations, cars, and inspection station",
            },
            "stop": {
                "usage": "stop",
                "description": "Stop production tracking and pause all agents",
                "details": "Deactivates production monitoring, pauses all agents to stop message processing",
            },
            "led": {
                "usage": "led <topic> <state>",
                "description": "Test LED control via MQTT",
                "details": "Send LED command to specified MQTT topic\nExample: led leds/C1WS4 ON\nStates: ON, OFF, or color names",
            },
            "config": {
                "usage": "config",
                "description": "Display current system configuration",
                "details": "Shows MQTT broker settings, facility layout, production targets, and performance parameters",
            },
            "status": {
                "usage": "status",
                "description": "Show current system and production status",
                "details": "Displays system initialization state, production tracking status, and key metrics",
            },
            "help": {
                "usage": "help [command]",
                "description": "Show command help information",
                "details": "Without arguments: shows all commands\nWith command name: shows detailed help for that command",
            },
            "exit": {
                "usage": "exit",
                "description": "Exit the Tiger Motors Digital Twin CLI",
                "details": "Gracefully shutdown the simulation and exit the program",
            },
        }

        logger.info("CLIInterface initialized with SimulationInterface")

    def run(self):
        """
        Main CLI execution method.

        This method initializes the simulation system and starts the interactive
        command loop. It handles system initialization, user interaction, and
        graceful shutdown.
        """
        try:
            print("TIGER MOTORS DIGITAL TWIN - CLI Interface")
            print("=" * 50)

            # Initialize the simulation system
            print("Initializing simulation system...")
            if not self._initialize_simulation():
                print("[ERROR] Failed to initialize simulation system")
                return

            print("[OK] Simulation system ready")
            print("\nType 'help' for available commands or 'exit' to quit")

            # Start the interactive command loop
            self._command_loop()

        except KeyboardInterrupt:
            print("\n[STOP] Keyboard interrupt received")
        except Exception as e:
            print(f"[ERROR] Unexpected error in CLI: {e}")
            logger.error(f"Unexpected error in CLI run: {e}")
        finally:
            self._shutdown()

    def _initialize_simulation(self) -> bool:
        """
        Initialize the simulation system.

        Returns:
            bool: True if initialization successful, False otherwise
        """
        try:
            success = self.simulation.initialize()
            if success:
                logger.info("Simulation system initialized successfully")
                return True
            else:
                print("[ERROR] Simulation initialization returned False")
                return False

        except (SimulationError, ConfigurationError, CommunicationError) as e:
            print(f"[ERROR] Simulation initialization failed: {e}")
            logger.error(f"Simulation initialization failed: {e}")
            return False
        except Exception as e:
            print(f"[ERROR] Unexpected error during initialization: {e}")
            logger.error(f"Unexpected initialization error: {e}")
            return False

    def _command_loop(self):
        """Interactive command processing loop."""
        while self.running:
            try:
                command = input("> ").strip()
                if command:
                    self._handle_command(command)

            except KeyboardInterrupt:
                print("\n")
                self._cmd_exit([])
            except EOFError:
                print("\n")
                self._cmd_exit([])
            except Exception as e:
                print(f"[ERROR] Error processing command: {e}")
                logger.error(f"Command processing error: {e}")

    def _handle_command(self, command: str):
        """
        Parse and execute user commands.

        Args:
            command: Raw command string from user input
        """
        # Parse command into parts
        parts = command.strip().split()
        if not parts:
            return

        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        # Execute command if it exists
        if cmd in self._commands:
            try:
                self._commands[cmd](args)
            except Exception as e:
                print(f"[ERROR] Error executing command '{cmd}': {e}")
                logger.error(f"Command execution error for '{cmd}': {e}")
        else:
            print(f"[ERROR] Unknown command: '{cmd}'")
            print("Type 'help' for available commands")

    # Command implementations

    def _cmd_start_production(self, args):
        """Handle 'start' command - begin production tracking."""
        try:
            if self.simulation.is_production_running():
                print("[WARN] Production tracking is already running")
                return

            print("Starting production tracking...")
            success = self.simulation.start_production()

            if success:
                print("[OK] Production tracking started successfully")
                print("All agents resumed and monitoring production")
            else:
                print("[ERROR] Failed to start production tracking")

        except SimulationError as e:
            print(f"[ERROR] Simulation error: {e}")
        except Exception as e:
            print(f"[ERROR] Unexpected error starting production: {e}")

    def _cmd_stop_production(self, args):
        """Handle 'stop' command - stop production tracking."""
        try:
            if not self.simulation.is_production_running():
                print("[WARN] Production tracking is not currently running")
                return

            print("[STOP] Stopping production tracking...")
            success = self.simulation.stop_production()

            if success:
                print("[OK] Production tracking stopped successfully")
                print("All agents paused")
            else:
                print("[ERROR] Failed to stop production tracking")

        except SimulationError as e:
            print(f"[ERROR] Simulation error: {e}")
        except Exception as e:
            print(f"[ERROR] Unexpected error stopping production: {e}")

    def _cmd_test_led(self, args):
        """Handle 'led' command - test LED control via MQTT."""
        if len(args) != 2:
            print("[ERROR] Invalid LED command syntax")
            print("Usage: led <topic> <state>")
            print("Example: led leds/C1WS4 ON")
            return

        topic, state = args[0], args[1]

        try:
            # Note: This functionality requires direct MQTT access
            # For now, we'll provide feedback that the command was processed
            print(f"LED Test Command: {topic} -> {state}")
            print("[WARN] LED testing requires MQTT communication agent access")
            print("This feature will be implemented in the communication interface")

        except Exception as e:
            print(f"[ERROR] Error with LED command: {e}")

    def _cmd_show_config(self, args):
        """Handle 'config' command - display current configuration."""
        try:
            system_status = self.simulation.get_system_status()

            print("\nTiger Motors Digital Twin Configuration")
            print("=" * 50)

            # System status
            print("System Status:")
            print(f"   Initialized: {'Yes' if system_status.is_initialized else 'No'}")
            print(f"   MQTT Connected: {'Yes' if system_status.mqtt_connected else 'No'}")
            print(f"   Configuration Valid: {'Yes' if system_status.configuration_valid else 'No'}")
            print(f"   Uptime: {system_status.uptime_seconds:.1f} seconds")
            print(f"   Error Count: {system_status.error_count}")

            # Component counts
            print("Component Status:")
            for component, count in system_status.component_counts.items():
                print(f"   {component.title()}: {count}")

            # Production status
            print("Production Status:")
            production_status = "Running" if system_status.is_production_tracking else "Stopped"
            print(f"   Tracking: {production_status}")

            print("=" * 50)

        except SimulationError as e:
            print(f"[ERROR] Error retrieving configuration: {e}")
        except Exception as e:
            print(f"[ERROR] Unexpected error displaying configuration: {e}")

    def _cmd_show_status(self, args):
        """Handle 'status' command - show current system and production status."""
        try:
            # Get system status
            system_status = self.simulation.get_system_status()
            production_metrics = self.simulation.get_production_metrics()

            print("\nTiger Motors Digital Twin Status")
            print("=" * 50)

            # System overview
            print("System Overview:")
            print(f"   Status: {'Running' if system_status.is_initialized else 'Stopped'}")
            print(f"   Uptime: {system_status.uptime_seconds:.1f} seconds")
            print(f"   MQTT: {'Connected' if system_status.mqtt_connected else 'Disconnected'}")

            # Production metrics
            print("\nProduction Metrics:")
            print(f"   Tracking: {'Active' if production_metrics.is_tracking else 'Inactive'}")

            if production_metrics.is_tracking and production_metrics.elapsed_time is not None:
                print(f"   Runtime: {production_metrics.elapsed_time:.1f} seconds")

            print(f"   Active Cars: {production_metrics.active_cars}")
            print(f"   Finished Cars: {production_metrics.finished_cars}")
            print(f"   Cars in Inspection: {production_metrics.cars_in_inspection}")

            # Workstation summary
            print("\nWorkstation Summary:")
            print(f"   Total: {production_metrics.total_workstations}")
            print(f"   Active: {production_metrics.workstations_active}")
            print(f"   Idle: {production_metrics.workstations_idle}")
            print(f"   Caution: {production_metrics.workstations_caution}")
            print(f"   Stopped: {production_metrics.workstations_stopped}")

            if production_metrics.average_lead_time is not None:
                print("\nPerformance:")
                print(f"   Average Lead Time: {production_metrics.average_lead_time:.1f} seconds")

            print("=" * 50)

        except SimulationError as e:
            print(f"[ERROR] Error retrieving status: {e}")
        except Exception as e:
            print(f"[ERROR] Unexpected error displaying status: {e}")

    def _cmd_show_help(self, args):
        """Handle 'help' command - show command help information."""
        if args and args[0].lower() in self._help_docs:
            # Show detailed help for specific command
            cmd = args[0].lower()
            help_info = self._help_docs[cmd]

            print(f"\nHelp for '{cmd}' command:")
            print("=" * 30)
            print(f"Usage: {help_info['usage']}")
            print(f"Description: {help_info['description']}")
            print(f"\nDetails:\n{help_info['details']}")
            print("=" * 30)

        else:
            # Show general help for all commands
            print("\nTiger Motors Digital Twin - Available Commands")
            print("=" * 50)

            for cmd, help_info in self._help_docs.items():
                if cmd != "quit":  # Don't show the alias
                    print(f"  {help_info['usage']:<20} - {help_info['description']}")

            print("\nFor detailed help on a command: help <command>")
            print("Example: help start")
            print("=" * 50)

    def _cmd_exit(self, args):
        """Handle 'exit' command - graceful shutdown."""
        print("Exiting Tiger Motors Digital Twin CLI...")
        self.running = False

    def _shutdown(self):
        """Graceful shutdown of the CLI interface."""
        try:
            print("Shutting down simulation system...")

            # Stop production if running
            if self.simulation.is_initialized() and self.simulation.is_production_running():
                self.simulation.stop_production()

            # Shutdown simulation
            self.simulation.shutdown()

            print("[OK] Shutdown complete")
            logger.info("CLIInterface shutdown completed")

        except Exception as e:
            print(f"[WARN] Error during shutdown: {e}")
            logger.error(f"Shutdown error: {e}")
