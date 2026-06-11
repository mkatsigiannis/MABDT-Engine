"""
Tiger Motors Digital Twin - Background Worker

This module contains worker classes for running background operations in separate threads.
This is essential for keeping the GUI responsive while the simulation runs.
"""

from PySide6.QtCore import QObject

from tiger_motors_dt.simulation.environment import TigerMotorsEnvironment


class EnvironmentWorker(QObject):
    """
    Worker class to run TigerMotorsEnvironment in a separate thread.

    In PySide6, long-running operations should never run on the main GUI thread
    because they would freeze the user interface. QObject subclasses can be
    moved to separate QThreads to handle background processing.

    This worker runs the main simulation loop while keeping the GUI responsive.
    """

    def __init__(self, environment: TigerMotorsEnvironment):
        super().__init__()  # Initialize the QObject base class
        self.environment = environment

    def run(self):
        """
        Main method that runs in the background thread.

        The TigerMotorsEnvironment is event-driven and doesn't require a run loop.
        The EventBus handles timing and coordination. This method ensures the
        environment stays initialized and responsive.
        """
        # The environment is event-driven and managed by its EventBus
        # No continuous run loop is needed - just keep the thread alive
        # while the environment is active
        if self.environment and self.environment.is_initialized():
            # Environment is already running via EventBus tick system
            # This thread just needs to stay alive to maintain the environment
            while self.environment.is_initialized():
                # Small sleep to prevent busy waiting
                # EventBus handles all the actual work
                import time

                time.sleep(0.1)
