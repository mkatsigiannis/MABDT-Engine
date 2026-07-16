"""Paced-assembly-line MQTT generator for the unified scaling study.

Emulates how the physical line actually operates, unlike the
round-robin generator in bench/: the line starts full (every
workstation holds a car, all Busy), and every cycle time T each car
advances exactly one station — one finished car leaves the line per
cycle, one new car enters at WS1, WIP stays constant at N.

Two arrival patterns for the same line semantics (`--arrival`):

  staggered (default)
      Station k acts at a fixed phase offset (k-1) * T/N inside each
      cycle. At its slot it publishes its "finished" scan and then the
      "arrived" scan for the car handed off from station k-1 earlier in
      the same cycle. This models a takt-paced flow line with hand-offs
      (like Tiger Motors) and produces an (almost) uniform message
      stream — pairs of scans every T/N — which makes per-event latency
      directly comparable to the uniform-arrival study in bench/.
      Priming occupies cycle 0: station k scans its initial car at its
      own slot, so the whole line is busy after one cycle.

  burst
      All stations act at the cycle boundary: N exit scans (downstream
      first), the shift, then N enter scans. This models a synchronized
      indexing/transfer line and is the worst-case arrival pattern —
      every cycle the engine absorbs a burst of 2N messages at once.
      Priming is a single burst before cycle 1.

Per cycle the generator publishes 2N scans, so the average offered rate
is r = 2N / T in both modes. Exits occur once per cycle from cycle 1
onward, so the ideal inter-departure time — the takt the digital twin
should observe — is exactly T. Ideal lead times differ by mode: a car
entering at WS1 exits N cycles later, at the same boundary in burst
mode (N x T) but at station N's late slot in staggered mode
(N x T + (N-1) x T/N).

Routing guarantees (single MQTT connection, publish order preserved):
each workstation sees `done` (old car) before `busy` (new car), and
each car sees `done@k` before `start@k+1`. Per-agent dedup keys always
alternate, so duplicate-message detection never drops a scan.

Like bench/, publishes at QoS 0 (see bench/benchmark_generator.py for
the QoS 1 duplicate-delivery rationale) and injects no faults, no
rework, and no inspection-station traffic.

Runs standalone (prints a JSON stats line on exit) so the benchmark
runner can launch it as a separate OS process: publish cost then never
shares the engine's GIL, which kept the old in-process generator from
reaching its target at high rates. Slot pacing uses sleep-then-spin for
sub-millisecond precision; spinning is acceptable because this process
is isolated from the engine being measured.

Usage (normally invoked by bench_line.benchmark):
    python -m bench_line.line_generator --total-workstations 15 \
        --cycle-time 0.5 --cycles 40 --arrival staggered
"""

from __future__ import annotations

import argparse
import json
import threading
import time

import paho.mqtt.client as mqtt

ARRIVAL_MODES = ("staggered", "burst")


def cell_from_ws(ws_num: int, workstations_per_cell: int) -> int:
    return (ws_num - 1) // workstations_per_cell + 1


class LineBenchmarkGenerator:
    def __init__(
        self,
        mqtt_host: str = "127.0.0.1",
        mqtt_port: int = 8883,
        total_workstations: int = 15,
        workstations_per_cell: int = 5,
        cycle_time_s: float = 1.0,
        cycles: int = 40,
        arrival: str = "staggered",
        car_prefix: str = "SUV",
    ):
        if cycles < 1:
            raise ValueError("cycles must be >= 1")
        if cycle_time_s <= 0:
            raise ValueError("cycle_time_s must be > 0")
        if arrival not in ARRIVAL_MODES:
            raise ValueError(f"arrival must be one of {ARRIVAL_MODES}")
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.total_workstations = total_workstations
        self.workstations_per_cell = workstations_per_cell
        self.cycle_time_s = cycle_time_s
        self.cycles = cycles
        self.arrival = arrival
        self.car_prefix = car_prefix

        self._client: mqtt.Client | None = None
        self._stop = threading.Event()

        # Shared counters, filled by the mode-specific run loop.
        self._events_published = 0
        self._next_car_idx = 0
        self._slots_late = 0
        self._max_slip_s = 0.0

    def _topic(self, ws_num: int) -> str:
        cell = cell_from_ws(ws_num, self.workstations_per_cell)
        return f"scanner/C{cell}WS{ws_num}"

    def _publish_plc_init(self) -> None:
        """Set all workstations to green Andon so `busy` transitions work."""
        for ws_num in range(1, self.total_workstations + 1):
            cell = cell_from_ws(ws_num, self.workstations_per_cell)
            self._client.publish(f"plc/C{cell}WS{ws_num}/GRN", "True", qos=0)

    def _publish_scan(self, ws_num: int, car_id: str) -> None:
        self._client.publish(self._topic(ws_num), car_id, qos=0)
        self._events_published += 1

    def _new_car(self) -> str:
        car_id = f"{self.car_prefix}{self._next_car_idx}"
        self._next_car_idx += 1
        return car_id

    def _pace_until(self, target: float) -> None:
        """Wait until perf_counter() reaches `target`; track lateness.

        Sleeps until ~2 ms before the target, then spins for sub-ms
        precision (Windows sleep granularity is far coarser than the
        slot spacing at high rates). If already past the target, publish
        immediately and record the slip — the schedule stays absolute,
        so a slipping generator is visible, not silently corrected.
        """
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

    def stop(self) -> None:
        """Request an early stop; run() finishes the current cycle and returns."""
        self._stop.set()

    # --- Mode-specific run loops -------------------------------------------

    def _run_burst(self) -> dict:
        """Synchronized indexing line: everything happens at the boundary."""
        n, t_cycle = self.total_workstations, self.cycle_time_s

        # Priming: one burst fills the line before cycle 1.
        prime_t0 = time.perf_counter()
        line = [self._new_car() for _ in range(n)]
        for ws_num in range(1, n + 1):
            self._publish_scan(ws_num, line[ws_num - 1])
        prime_publish_s = time.perf_counter() - prime_t0

        start = time.perf_counter()
        cycles_completed = 0
        cars_exited = 0
        burst_total_s = 0.0
        max_burst_s = 0.0

        for i in range(1, self.cycles + 1):
            if self._stop.is_set():
                break
            self._pace_until(start + i * t_cycle)

            burst_t0 = time.perf_counter()
            # Exit scans, downstream first (WS N clears the line).
            for ws_num in range(n, 0, -1):
                self._publish_scan(ws_num, line[ws_num - 1])
            # Shift one station downstream; new car enters at WS1.
            line.pop()
            cars_exited += 1
            line.insert(0, self._new_car())
            # Enter scans, upstream first.
            for ws_num in range(1, n + 1):
                self._publish_scan(ws_num, line[ws_num - 1])

            burst_s = time.perf_counter() - burst_t0
            burst_total_s += burst_s
            max_burst_s = max(max_burst_s, burst_s)
            cycles_completed += 1

        return {
            "cycles_completed": cycles_completed,
            "cars_exited_offered": cars_exited,
            "prime_publish_s": round(prime_publish_s, 4),
            "runner_runtime_s": round(time.perf_counter() - start, 3),
            "mean_burst_s": (
                round(burst_total_s / cycles_completed, 5) if cycles_completed else 0.0
            ),
            "max_burst_s": round(max_burst_s, 5),
        }

    def _run_staggered(self) -> dict:
        """Takt-paced flow line: station k acts at offset (k-1)*T/N.

        Cycle 0 is the staggered priming pass. From cycle 1 on, each
        station's slot publishes the exit scan of its current car and
        the enter scan of the car handed off from the previous station's
        slot earlier in the same cycle (a fresh car at WS1). The car
        exiting station N leaves the line.
        """
        n, t_cycle = self.total_workstations, self.cycle_time_s
        slot = t_cycle / n

        start = time.perf_counter()

        # Cycle 0: staggered priming — the line is full after one cycle.
        line: list[str] = []
        for k in range(1, n + 1):
            self._pace_until(start + (k - 1) * slot)
            car_id = self._new_car()
            self._publish_scan(k, car_id)
            line.append(car_id)
        prime_publish_s = time.perf_counter() - start

        cycles_completed = 0
        cars_exited = 0

        for i in range(1, self.cycles + 1):
            if self._stop.is_set():
                break
            in_transit = self._new_car()  # enters at WS1 this cycle
            for k in range(1, n + 1):
                self._pace_until(start + i * t_cycle + (k - 1) * slot)
                exiting = line[k - 1]
                self._publish_scan(k, exiting)  # done at station k
                self._publish_scan(k, in_transit)  # arrival at station k
                line[k - 1] = in_transit
                in_transit = exiting  # hand off to station k+1
            # After the last slot, in_transit is the car from WS N: it
            # has left the line (its final `done` fired inspection).
            cars_exited += 1
            cycles_completed += 1

        return {
            "cycles_completed": cycles_completed,
            "cars_exited_offered": cars_exited,
            "prime_publish_s": round(prime_publish_s, 4),
            # Includes the priming cycle: the staggered runner is "live"
            # from its first slot onward.
            "runner_runtime_s": round(time.perf_counter() - start, 3),
            "mean_burst_s": 0.0,  # n/a: no bursts in staggered mode
            "max_burst_s": 0.0,
        }

    # --- Entry point ----------------------------------------------------------

    def run(self) -> dict:
        """Blocking: prime the line, run the paced cycles, return stats."""
        self._client = mqtt.Client(client_id=f"bench_line_gen_{int(time.time())}")
        self._client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
        self._client.loop_start()
        time.sleep(0.5)  # let the broker register the connection

        self._publish_plc_init()
        time.sleep(0.2)

        if self.arrival == "burst":
            stats = self._run_burst()
        else:
            stats = self._run_staggered()

        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

        stats.update(
            {
                "arrival": self.arrival,
                "total_workstations": self.total_workstations,
                "cycle_time_s": self.cycle_time_s,
                "cycles_requested": self.cycles,
                "events_published": self._events_published,
                "cars_entered": self._next_car_idx,
                "boundaries_late": self._slots_late,
                "max_slip_s": round(self._max_slip_s, 4),
            }
        )
        return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8883)
    parser.add_argument("--total-workstations", "-N", type=int, default=15)
    parser.add_argument("--workstations-per-cell", type=int, default=5)
    parser.add_argument(
        "--cycle-time", type=float, default=1.0, help="Line cycle time T in seconds."
    )
    parser.add_argument("--cycles", type=int, default=40, help="Number of paced cycles to run.")
    parser.add_argument("--arrival", choices=ARRIVAL_MODES, default="staggered")
    parser.add_argument("--car-prefix", default="SUV")
    args = parser.parse_args()

    gen = LineBenchmarkGenerator(
        mqtt_host=args.host,
        mqtt_port=args.port,
        total_workstations=args.total_workstations,
        workstations_per_cell=args.workstations_per_cell,
        cycle_time_s=args.cycle_time,
        cycles=args.cycles,
        arrival=args.arrival,
        car_prefix=args.car_prefix,
    )
    try:
        stats = gen.run()
    except KeyboardInterrupt:
        gen.stop()
        stats = {"interrupted": True}
    # The runner parses the last stdout line as JSON. Keep it last.
    print(json.dumps(stats), flush=True)


if __name__ == "__main__":
    main()
