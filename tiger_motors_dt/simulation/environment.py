"""Tiger Motors simulation environment.

A `mabdt.Environment` subclass that declares the deployment's agent
populations and the communication agent. Driven entirely by the
declarative API the JIM paper presents in §3.1:

  - workstations: a static population (15 agents, IDs from config)
  - inspection_station: a singleton
  - cars: dynamic agents created at runtime by BarcodeProcessor (§3.1 C14);
    kept as a plain dict on the environment because they have no fixed ID
    set declared up front

Tiger-specific lifecycle policy (production_start_time, prod_start /
prod_finish broadcast, MQTT announcement) lives in `on_production_started`
and `on_production_stopped`. The mabdt base handles the rest of the
lifecycle (resume/pause populations and singletons, build agents, start
the comm agent).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from mabdt import Environment as _MABDTEnvironment
from mabdt.communication_kernel.event_bus import EventBus
from mabdt.exceptions import CommunicationError, ConfigurationError
from mabdt.utils.logging import get_logger
from tiger_motors_dt.agents import (
    CarAgent,
    InspectionStationAgent,
    WorkstationAgent,
)
from tiger_motors_dt.agents import CommAgent as CommunicationAgent
from tiger_motors_dt.config import load_config

logger = get_logger(__name__)


class TigerMotorsEnvironment(_MABDTEnvironment):
    """Deployment-specific environment for the Tiger Motors lab.

    Args:
        config: Optional configuration dict. If None, loads `config.json`
                via `tiger_motors_dt.config.load_config` (which applies
                Tiger-specific validation).
        bus: Optional pre-built EventBus. If None, the mabdt base creates one.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        bus: EventBus | None = None,
    ) -> None:
        if config is None:
            try:
                config = load_config()
            except (OSError, json.JSONDecodeError, ValueError) as e:
                raise ConfigurationError(
                    f"Failed to load Tiger Motors configuration: {e}",
                    error_code="SIM_CONFIG_LOAD_FAILED",
                ) from e

        super().__init__(config=config, bus=bus)

        # Dynamic-agent dict (JIM §3.1 C14: agents created by the
        # CommunicationAgent at runtime). Mutated by BarcodeProcessor.
        self.cars: dict[str, CarAgent] = {}

        # Tiger-specific production state. mabdt provides tracking_production.
        self.production_start_time: float | None = None

        # Convenience attributes for code that reads workstations/
        # inspection_station off the env. Populated in `initialize` after the
        # mabdt base builds the population and singleton.
        self.workstations: dict[str, WorkstationAgent] = {}
        self.inspection_station: InspectionStationAgent | None = None

        logger.info(
            f"TigerMotorsEnvironment created with MQTT broker "
            f"{self.config['mqtt']['host']}:{self.config['mqtt']['port']}"
        )

    # --- Declarative wiring (called from mabdt base initialize) -------------

    def _declare(self) -> None:
        """Register the deployment's static populations and the comm agent."""
        facility = self.config["facility"]
        total = facility["total_workstations"]
        per_cell = facility["workstations_per_cell"]
        ws_ids = [f"C{(i - 1) // per_cell + 1}WS{i}" for i in range(1, total + 1)]

        self.register_population(
            name="workstations",
            factory=lambda ws_id, bus: WorkstationAgent(ws_id, bus),
            ids=ws_ids,
            paused=True,
        )
        self.register_singleton(
            name="inspection_station",
            factory=lambda bus: InspectionStationAgent(bus),
            paused=True,
        )

        mqtt_config = self.config["mqtt"]
        for required in ("host", "port"):
            if required not in mqtt_config:
                raise ConfigurationError(
                    f"Missing required MQTT configuration key: {required}",
                    error_code="CONFIG_MQTT_INCOMPLETE",
                    context={"missing_key": required},
                )
        comm = CommunicationAgent(
            self.bus,
            mqtt_host=mqtt_config["host"],
            mqtt_port=mqtt_config["port"],
            context=self,
            gate=lambda: self.tracking_production,
        )
        self.register_messaging(comm)

    # --- Lifecycle overrides ------------------------------------------------

    def initialize(self) -> None:
        """Build agents via the mabdt base, then start the engine tick.

        Sets `self.workstations` / `self.inspection_station` as views over
        the mabdt-managed population and singleton, and exposes the env on
        the shared lookup table (JIM §3.2 C24) so DT agents that need
        `tracking_production` or cell-completion counters can read it.
        """
        super().initialize()

        # Resolve population/singleton views for legacy attribute access.
        ws_pop = self.get_population("workstations")
        self.workstations = {ws.name: ws for ws in ws_pop}
        self.inspection_station = self.get_singleton("inspection_station")

        # Expose self on the shared lookup table for car/ws agents that
        # read env.tracking_production or write cell-completion counts.
        self.bus.set("main", self)
        self.bus.start_tick()

        logger.info(
            f"TigerMotorsEnvironment initialized: "
            f"{len(self.workstations)} workstations, 1 inspection station, "
            f"comm agent at {self.config['mqtt']['host']}:{self.config['mqtt']['port']}"
        )

    def shutdown(self) -> None:
        """Stop dynamic cars, then delegate the rest to the mabdt base."""
        with self._lock:
            for car in self.cars.values():
                car.stop()
            self.cars.clear()
        super().shutdown()
        logger.info("TigerMotorsEnvironment shutdown complete")

    # --- Production-lifecycle hooks -----------------------------------------

    def on_production_started(self) -> None:
        """Tiger-specific actions after the mabdt base resumes agents.

        - Record the production start timestamp.
        - Broadcast `prod_start` to every workstation (drives their state
          machines out of Initialize).
        - Resume any cars that were created before this start cycle.
        - Publish a `production_start` MQTT message via the outbound bus
          topic so MING / Grafana see the event.
        """
        self.production_start_time = time.time()

        ws_pop = self.get_population("workstations")
        ws_pop.broadcast({"type": "prod_start"})

        for car in self.cars.values():
            car.resume()

        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            payload = json.dumps({"timestamp": timestamp})
            self.bus.publish_mqtt(self.config["topics"]["production_start"], payload, qos=2)
            logger.info("Published production_start to MQTT")
        except Exception as e:
            raise CommunicationError(
                f"Failed to publish production_start: {e}",
                error_code="COMM_PROD_START_FAILED",
            ) from e

    def on_production_stopped(self) -> None:
        """Tiger-specific actions before the mabdt base pauses agents.

        Broadcasts `prod_finish` to workstations so their statecharts
        wrap up the current cycle cleanly, and pauses any active cars.
        The mabdt base's stop_production calls this hook BEFORE pausing
        populations/singletons, so messages get processed first.
        """
        ws_pop = self.get_population("workstations")
        ws_pop.broadcast({"type": "prod_finish"})

        for car in self.cars.values():
            car.pause()

    # --- Deployment helpers -------------------------------------------------

    def test_led(self, topic: str, state: str) -> bool:
        """Publish an LED state to the broker via the outbound bus topic.

        Used by the CLI / GUI to drive Andon lights for testing.
        """
        if self.comm_agent is None:
            raise CommunicationError(
                "Communication agent not initialized",
                error_code="COMM_NOT_AVAILABLE",
                context={"topic": topic, "state": state},
            )
        try:
            self.bus.publish_mqtt(topic, state, qos=1)
            logger.info(f"LED command sent: {topic} -> {state}")
            return True
        except Exception as e:
            raise CommunicationError(
                f"Failed to send LED command: {e}",
                error_code="COMM_LED_FAILED",
                context={"topic": topic, "state": state},
            ) from e

    def get_configuration_summary(self) -> dict[str, Any]:
        """Return a flat dict summary of MQTT, facility, and performance config."""
        perf = self.config.get("performance", {})
        return {
            "mqtt": {
                "host": self.config["mqtt"]["host"],
                "port": self.config["mqtt"]["port"],
                "keepalive": self.config["mqtt"].get("keepalive", 60),
            },
            "facility": {
                "total_workstations": self.config["facility"]["total_workstations"],
                "cells": self.config["facility"]["cells"],
                "workstations_per_cell": self.config["facility"]["workstations_per_cell"],
            },
            "production": {
                "target_takt_time": self.config["production"]["target_takt_time"],
                "target_cycle_time": self.config["production"]["target_cycle_time"],
            },
            "performance": {
                "eventbus_tick_interval_ms": perf.get("eventbus_tick_interval", 0.01) * 1000,
                "gui_update_interval_ms": perf.get("gui_update_interval", 0.05) * 1000,
                "state_stability_delay_ms": perf.get("state_stability_delay", 0.005) * 1000,
                "agent_inbox_timeout_ms": perf.get("agent_inbox_timeout", 0.1) * 1000,
            },
        }

    def get_agent_counts(self) -> dict[str, int]:
        return {
            "workstations": len(self.workstations),
            "cars": len(self.cars),
            "inspection_station": 1 if self.inspection_station else 0,
            "communication_agent": 1 if self.comm_agent else 0,
        }

    def get_production_metrics(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "tracking_production": self.tracking_production,
            "production_start_time": self.production_start_time,
            "elapsed_time": None,
        }
        if self.tracking_production and self.production_start_time:
            metrics["elapsed_time"] = time.time() - self.production_start_time
        return metrics
