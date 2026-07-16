"""Seeded stochastic-line generator: simulate first, then replay over MQTT.

Models the Tiger Motors line as a tandem queueing system:

  - Cars are released to WS1's queue at a fixed takt (75 s real-line
    time by default), starting from an EMPTY line — the fill transient
    is part of a realistic shift start.
  - Station k serves cars FIFO, one at a time: when the station is free
    and a car is waiting, the operator grabs the car (Uniform grab
    delay), scans it (ENTER scan published), assembles for a
    Triangular(min, mode, max) service time, then scans again (EXIT
    scan) and passes the car to station k+1's queue instantly.
  - An optional bottleneck station has all three Triangular parameters
    scaled by a factor, reproducing the classic constraint signature:
    queue upstream, starvation downstream, utilization near 1.

Because service is FIFO with a single server per station, the whole
timeline follows the standard tandem-queue recursion and can be computed
car by car BEFORE anything touches the network:

    start(i, k) = max(avail(i, k), free(k)) + grab
    end(i, k)   = start(i, k) + service
    avail(i, k+1) = end(i, k);  free(k) = end(i, k)

The precomputed schedule is then replayed in real time, divided by a
compression factor (all sleeps/publishes at scheduled instants, slip
tracked). The schedule IS the ground truth: it is written to a CSV so
the benchmark can compare what the digital twin observed against what
the simulated physical line actually did.

Scan-routing guarantees match bench_line: per car, events alternate
done@k / start@k+1 (grab > 0 makes ordering strict); per station, busy
and done alternate (FIFO single server); dedup keys therefore never
collide. QoS 0, no faults/rework (kept out of v1 so ground-truth lead
times stay unambiguous).

Usage (normally invoked by bench_fidelity.benchmark):
    python -m bench_fidelity.stochastic_generator --cars 120 \
        --compression 100 --seed 1 --truth-out results/truth.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time

import paho.mqtt.client as mqtt


def cell_from_ws(ws_num: int, workstations_per_cell: int) -> int:
    return (ws_num - 1) // workstations_per_cell + 1


class StochasticLineGenerator:
    def __init__(
        self,
        mqtt_host: str = "127.0.0.1",
        mqtt_port: int = 8883,
        n_stations: int = 15,
        workstations_per_cell: int = 5,
        cars: int = 120,
        takt_s: float = 75.0,
        tri: tuple[float, float, float] = (50.0, 60.0, 70.0),
        grab: tuple[float, float] = (1.0, 3.0),
        bottleneck_station: int = 0,
        bottleneck_factor: float = 1.2,
        compression: float = 100.0,
        seed: int = 1,
        car_prefix: str = "SUV",
    ):
        if cars < 1:
            raise ValueError("cars must be >= 1")
        if compression <= 0:
            raise ValueError("compression must be > 0")
        if not (tri[0] <= tri[1] <= tri[2]):
            raise ValueError("tri must satisfy min <= mode <= max")
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.n = n_stations
        self.workstations_per_cell = workstations_per_cell
        self.cars = cars
        self.takt_s = takt_s
        self.tri = tri
        self.grab = grab
        self.bottleneck_station = bottleneck_station
        self.bottleneck_factor = bottleneck_factor
        self.compression = compression
        self.seed = seed
        self.car_prefix = car_prefix

        self._client: mqtt.Client | None = None
        self._slots_late = 0
        self._max_slip_s = 0.0

    def _topic(self, ws_num: int) -> str:
        cell = cell_from_ws(ws_num, self.workstations_per_cell)
        return f"scanner/C{cell}WS{ws_num}"

    # --- Simulation (pure, no I/O) -----------------------------------------

    def simulate(self) -> tuple[list[tuple[float, int, str]], list[dict]]:
        """Compute the full timeline. All times in REAL line seconds.

        Returns (schedule, truth):
          schedule — [(t, ws_num, car_id), ...] sorted by t; one entry per
                     scan (each station visit publishes enter and exit).
          truth    — [{car, ws, enter_s, exit_s}, ...] per station visit.
        """
        rng = random.Random(self.seed)
        free_at = [0.0] * (self.n + 1)  # index 1..n
        schedule: list[tuple[float, int, str]] = []
        truth: list[dict] = []

        # Per-station service parameters; the bottleneck station has all
        # three Triangular parameters scaled.
        params = {}
        for k in range(1, self.n + 1):
            f = self.bottleneck_factor if k == self.bottleneck_station else 1.0
            params[k] = (self.tri[0] * f, self.tri[1] * f, self.tri[2] * f)

        for i in range(self.cars):
            car_id = f"{self.car_prefix}{i}"
            avail = i * self.takt_s  # takt-paced release into WS1's queue
            for k in range(1, self.n + 1):
                a, m, b = params[k]
                grab_t = rng.uniform(*self.grab)
                # random.triangular takes (low, high, mode).
                svc = rng.triangular(a, b, m)
                start = max(avail, free_at[k]) + grab_t
                end = start + svc
                free_at[k] = end
                schedule.append((start, k, car_id))  # enter scan
                schedule.append((end, k, car_id))  # exit scan
                truth.append(
                    {"car": car_id, "ws": k, "enter_s": round(start, 4), "exit_s": round(end, 4)}
                )
                avail = end  # instant transfer to station k+1's queue
        schedule.sort(key=lambda e: e[0])
        return schedule, truth

    # --- Replay ------------------------------------------------------------

    def _pace_until(self, target: float) -> None:
        """Sleep/spin to `target` (perf_counter); record lateness > 1 ms."""
        now = time.perf_counter()
        delta = target - now
        if delta <= 0:
            if -delta > 0.001:
                self._slots_late += 1
                self._max_slip_s = max(self._max_slip_s, -delta)
            return
        if delta > 0.002:
            time.sleep(delta - 0.002)
        while time.perf_counter() < target:
            pass

    def run(self, truth_out: str) -> dict:
        """Simulate, write ground truth, replay the schedule. Blocking."""
        schedule, truth = self.simulate()
        with open(truth_out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["car", "ws", "enter_s", "exit_s"])
            w.writeheader()
            w.writerows(truth)

        self._client = mqtt.Client(client_id=f"bench_fid_gen_{int(time.time())}")
        self._client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
        self._client.loop_start()
        time.sleep(0.5)

        # Green Andon for every station so `busy` transitions are enabled.
        for ws_num in range(1, self.n + 1):
            cell = cell_from_ws(ws_num, self.workstations_per_cell)
            self._client.publish(f"plc/C{cell}WS{ws_num}/GRN", "True", qos=0)
        time.sleep(0.2)

        events_published = 0
        start = time.perf_counter()
        for t, ws_num, car_id in schedule:
            self._pace_until(start + t / self.compression)
            self._client.publish(self._topic(ws_num), car_id, qos=0)
            events_published += 1
        runner_runtime_s = time.perf_counter() - start

        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

        return {
            "n_stations": self.n,
            "cars": self.cars,
            "takt_s": self.takt_s,
            "tri": list(self.tri),
            "grab": list(self.grab),
            "bottleneck_station": self.bottleneck_station,
            "bottleneck_factor": self.bottleneck_factor,
            "compression": self.compression,
            "seed": self.seed,
            "events_published": events_published,
            "sim_makespan_s": round(schedule[-1][0], 2),
            "runner_runtime_s": round(runner_runtime_s, 3),
            "publishes_late": self._slots_late,
            "max_slip_s": round(self._max_slip_s, 4),
        }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8883)
    p.add_argument("--n-stations", "-N", type=int, default=15)
    p.add_argument("--workstations-per-cell", type=int, default=5)
    p.add_argument("--cars", type=int, default=120)
    p.add_argument("--takt", type=float, default=75.0, help="Release takt, real-line seconds.")
    p.add_argument(
        "--tri",
        type=float,
        nargs=3,
        default=[50.0, 60.0, 70.0],
        metavar=("MIN", "MODE", "MAX"),
        help="Triangular service time parameters, real-line seconds.",
    )
    p.add_argument(
        "--grab",
        type=float,
        nargs=2,
        default=[1.0, 3.0],
        metavar=("MIN", "MAX"),
        help="Uniform car-grab delay, real-line seconds.",
    )
    p.add_argument(
        "--bottleneck-station",
        type=int,
        default=0,
        help="Station whose service parameters are scaled (0 = balanced line).",
    )
    p.add_argument("--bottleneck-factor", type=float, default=1.2)
    p.add_argument("--compression", type=float, default=100.0, help="Real seconds per wall second.")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--truth-out", required=True, help="Path for the ground-truth CSV.")
    args = p.parse_args()

    gen = StochasticLineGenerator(
        mqtt_host=args.host,
        mqtt_port=args.port,
        n_stations=args.n_stations,
        workstations_per_cell=args.workstations_per_cell,
        cars=args.cars,
        takt_s=args.takt,
        tri=tuple(args.tri),
        grab=tuple(args.grab),
        bottleneck_station=args.bottleneck_station,
        bottleneck_factor=args.bottleneck_factor,
        compression=args.compression,
        seed=args.seed,
    )
    try:
        stats = gen.run(args.truth_out)
    except KeyboardInterrupt:
        stats = {"interrupted": True}
    # The runner parses the last stdout line as JSON. Keep it last.
    print(json.dumps(stats), flush=True)


if __name__ == "__main__":
    main()
