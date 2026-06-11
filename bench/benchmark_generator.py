"""Parametrized synthetic MQTT generator for the scaling benchmark.

Drives the engine end-to-end without touching the lab hardware:

  - Supports arbitrary total_workstations (not just the Tiger Motors 15).
    Cars walk the full configured line; CarAgent reads the line length
    from facility config, so the inspection trigger fires at WS{N}.
  - Publishes at a controlled per-station event rate from a single thread,
    so the generator's own CPU cost doesn't pollute the engine's CPU%
    samples.
  - **Publishes at QoS=0** (fire-and-forget). With QoS=1 the broker
    retransmits any message whose PUBACK from the subscriber arrives
    late, and paho-mqtt does not filter DUP=1 retransmissions — under
    sustained synthetic load the engine then sees the same scan twice,
    Route 4 fires for each copy, the car gets two `start` events in a
    row, and `transitions` logs `Can't trigger event 'start' from
    state(s) BeingMade_AssemblyAtStation`. QoS=0 eliminates that
    duplication. Dropped messages under broker queue pressure become an
    honest saturation signal instead. The engine subscribes at QoS=1
    in production; only the synthetic publisher runs at QoS=0.
  - No fault injection, no rework loops, no inspection station. The
    benchmark measures dispatch and statechart throughput, not the
    deployment's full fault paths.

A "car" enters at WS1 and walks through every workstation in sequence
(enter, exit, enter, exit, ...). Once it finishes the last workstation,
the CarAgent cleanly transitions into `WaitingInspection` and the
generator recycles the car_id with a fresh SUV at WS1.
"""

from __future__ import annotations

import argparse
import json
import threading
import time

import paho.mqtt.client as mqtt


def cell_from_ws(ws_num: int, workstations_per_cell: int) -> int:
    return (ws_num - 1) // workstations_per_cell + 1


class BenchmarkGenerator:
    def __init__(
        self,
        mqtt_host: str = "127.0.0.1",
        mqtt_port: int = 8883,
        total_workstations: int = 15,
        workstations_per_cell: int = 5,
        cars_in_flight: int = 5,
        events_per_second: float = 10.0,
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.total_workstations = total_workstations
        self.workstations_per_cell = workstations_per_cell
        self.cars_in_flight = cars_in_flight
        self.events_per_second = events_per_second

        self._client: mqtt.Client | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._events_published = 0
        # Captured by _runner around the actual publish loop so callers can
        # compute throughput against the time the runner spent publishing,
        # not against total benchmark wall time (which includes init +
        # env.shutdown). Stays at 0.0 until the runner exits.
        self._runner_start_perf: float | None = None
        self._runner_end_perf: float | None = None

    def _topic(self, ws_num: int) -> str:
        cell = cell_from_ws(ws_num, self.workstations_per_cell)
        return f"scanner/C{cell}WS{ws_num}"

    def _publish_plc_init(self) -> None:
        """Set all workstations to green Andon at start."""
        for ws_num in range(1, self.total_workstations + 1):
            cell = cell_from_ws(ws_num, self.workstations_per_cell)
            topic = f"plc/C{cell}WS{ws_num}/GRN"
            self._client.publish(topic, "True", qos=0)

    def _runner(self) -> None:
        """Publish a steady stream of barcode-scan events.

        Each car alternates two phases across workstations:
          - enter WSk : publish car_id on scanner/CcWSk (creates/moves car)
          - exit  WSk : publish car_id again on the same topic (completes)

        Per-car cycle = 2 events. With C cars in flight and r events/s,
        each car advances one station every C / (r/2) seconds. A car is
        recycled (new car_id at WS1) once it finishes the last
        workstation in the configured line.
        """
        interval = 1.0 / max(self.events_per_second, 0.001)
        # Per-car state: [car_id, current_ws_num, phase] where phase 0=enter, 1=exit
        cars: list[list] = []
        next_car_idx = 0
        for _ in range(self.cars_in_flight):
            car_id = f"SUV{next_car_idx}"
            next_car_idx += 1
            cars.append([car_id, 1, 0])

        self._runner_start_perf = time.perf_counter()
        next_time = self._runner_start_perf
        i = 0
        while not self._stop.is_set():
            car = cars[i % len(cars)]
            car_id, ws_num, phase = car
            topic = self._topic(ws_num)
            self._client.publish(topic, car_id, qos=0)
            self._events_published += 1

            if phase == 0:
                car[2] = 1  # next event will complete this station
            else:
                if ws_num < self.total_workstations:
                    car[1] = ws_num + 1
                    car[2] = 0
                else:
                    # Car reached the last workstation. The CarAgent
                    # transitions to WaitingInspection on this last `done`
                    # event and stops receiving traffic. Replace the slot
                    # with a fresh car_id at WS1.
                    car[0] = f"SUV{next_car_idx}"
                    next_car_idx += 1
                    car[1] = 1
                    car[2] = 0

            i += 1
            next_time += interval
            now = time.perf_counter()
            sleep = next_time - now
            if sleep > 0:
                time.sleep(sleep)
            elif sleep < -0.5:
                # Lagging by more than 0.5s; reset pacing to avoid runaway catch-up.
                next_time = now

        self._runner_end_perf = time.perf_counter()

    def start(self) -> None:
        self._client = mqtt.Client(client_id=f"bench_gen_{int(time.time())}")
        self._client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
        self._client.loop_start()
        time.sleep(0.5)  # let the broker register
        self._publish_plc_init()
        time.sleep(0.2)
        self._stop.clear()
        self._thread = threading.Thread(target=self._runner, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass

    @property
    def events_published(self) -> int:
        return self._events_published

    @property
    def runner_runtime_s(self) -> float:
        """Time the _runner spent publishing, in seconds.

        Computed from `time.perf_counter()` stamps taken at the start of
        the publish loop and at exit. Returns 0.0 if the runner never
        started or never exited.
        """
        if self._runner_start_perf is None or self._runner_end_perf is None:
            return 0.0
        return max(0.0, self._runner_end_perf - self._runner_start_perf)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8883)
    parser.add_argument("--total-workstations", "-N", type=int, default=15)
    parser.add_argument("--workstations-per-cell", type=int, default=5)
    parser.add_argument("--cars-in-flight", type=int, default=5)
    parser.add_argument("--rate", type=float, default=10.0, help="Events per second")
    parser.add_argument(
        "--duration", type=float, default=30.0, help="Seconds to run before stopping"
    )
    args = parser.parse_args()

    gen = BenchmarkGenerator(
        mqtt_host=args.host,
        mqtt_port=args.port,
        total_workstations=args.total_workstations,
        workstations_per_cell=args.workstations_per_cell,
        cars_in_flight=args.cars_in_flight,
        events_per_second=args.rate,
    )
    gen.start()
    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        gen.stop()
    print(
        json.dumps(
            {
                "events_published": gen.events_published,
                "duration_s": args.duration,
                "rate_target_eps": args.rate,
            }
        )
    )


if __name__ == "__main__":
    main()
