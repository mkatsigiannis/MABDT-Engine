"""Single-configuration runner for the unified line-mode scaling study.

Boots the engine with N workstations, runs the paced-line generator
(bench_line/line_generator.py) as a SEPARATE PROCESS for a given cycle
time T (or offered rate r = 2N/T), samples CPU/RAM/threads, and writes
one summary row plus a detailed per-event latency CSV.

This single experiment subsumes the old bench/ study AND adds
assembly-line metrics:

  - Arrival pattern (`--arrival`): `staggered` (default) reproduces the
    uniform arrival statistics of bench/, so per-event dispatch latency
    and the throughput/saturation curves are directly comparable to the
    old grid; `burst` is the synchronized worst case.
  - Old-parity columns: `processed_scans_eps` (car rows / runner
    runtime, the old `_row_throughput` definition), `sustained_scans_eps`
    (car rows / observed wall span), and `car_handling_ms_median`
    (per-event mqtt_to_inbox + handle — the paper's "handling" metric,
    previously computed ad hoc).
  - Exit rate / inter-departure time: how often a finished car leaves
    the line, measured from the car `done` events at WS{N}. Ideal = one
    exit every T seconds.
  - Lead time: per-car time from the engine receiving the car's first
    `start` scan at WS1 to the engine finishing the `done` handling at
    WS{N}. Ideal = N x T in burst mode, N x T + (N-1) x T/N in staggered
    mode (hand-off phases). Only cars that traverse the whole line
    qualify, which requires cycles >= N + 1.
  - WIP is N by construction (the line is always full), so Little's law
    L = lambda x W holds directly: N = (1/T) x (N x T).

Usage:
    python -m bench_line.benchmark --N 15 --cycle-time 0.5 --cycles 40
    python -m bench_line.benchmark --N 150 --rate 3000 --duration 60
    python -m bench_line.benchmark --N 15 --rate 1000 --arrival burst
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import statistics
import subprocess
import sys
import threading
import time
from typing import Any

import psutil

# Project root is the parent of the bench_line/ folder.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Patches must land BEFORE the env module is imported, because importing
# the env triggers chains that touch the Agent base class.
from bench_line import instrument
from bench_line import instrumentation as _bench
from bench_line.line_generator import LineBenchmarkGenerator
from tiger_motors_dt.simulation.environment import TigerMotorsEnvironment

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BENCH_DIR, "results")
SUMMARY_CSV = os.path.join(RESULTS_DIR, "summary.csv")
DEFAULT_CONFIG = os.path.join(BENCH_DIR, "config_benchmark.json")

# Fixed summary schema. Some metrics are conditional (lead-time columns
# need full traversals; inter-departure stats need >= 2 exits), so rows
# MUST be written against one canonical field list — otherwise each
# run's DictWriter would emit its own column order and rows would
# misalign under the file's single header.
SUMMARY_FIELDS = [
    "N",
    "arrival",
    "tag",
    "timestamp",
    "cycle_time_s",
    "rate_offered_eps",
    "cycles",
    "cycles_completed",
    "duration_s",
    "runner_runtime_s",
    "events_published",
    "prime_publish_s",
    "boundaries_late",
    "max_slip_s",
    "mean_burst_s",
    "max_burst_s",
    "cpu_percent_norm_mean",
    "cpu_percent_norm_max",
    "rss_mb_max",
    "num_threads_max",
    "rows",
    "rows_car",
    "rows_ws",
    "rows_ws_scan",
    "car_e2e_ms_median",
    "car_e2e_ms_p95",
    "car_e2e_ms_p99",
    "car_inbox_wait_ms_median",
    "car_inbox_wait_ms_p95",
    "ws_e2e_ms_median",
    "ws_e2e_ms_p95",
    "ws_inbox_wait_ms_median",
    "ws_inbox_wait_ms_p95",
    "handle_ms_median",
    "car_handling_ms_median",
    "car_handling_ms_p95",
    "ws_handling_ms_median",
    "ws_handling_ms_p95",
    "throughput_eps",
    "processed_scans_eps",
    "sustained_scans_eps",
    "misrouted_scans",
    "cars_mistracked",
    "cars_lost",
    "cars_exited",
    "exit_rate_per_min",
    "interdeparture_s_median",
    "interdeparture_s_mean",
    "interdeparture_cv",
    "takt_ratio",
    "lead_time_n",
    "lead_time_s_median",
    "lead_time_s_p95",
    "lead_time_s_ideal",
    "lead_overhead_ms_median",
    "car_events_missing",
    "ws_events_missing",
    "invalid_transition_warnings",
    "latency_csv",
]


def build_config(
    n_workstations: int,
    ws_per_cell: int = 5,
    mqtt_host: str = "127.0.0.1",
    mqtt_port: int = 8883,
    base_path: str = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Load the benchmark config and override facility/MQTT for this run."""
    with open(base_path) as f:
        cfg = json.load(f)
    cfg["facility"]["total_workstations"] = n_workstations
    cfg["facility"]["workstations_per_cell"] = ws_per_cell
    cfg["facility"]["cells"] = max(1, (n_workstations + ws_per_cell - 1) // ws_per_cell)
    cfg["mqtt"]["host"] = mqtt_host
    cfg["mqtt"]["port"] = mqtt_port
    return cfg


class _WarningCounter(logging.Handler):
    """Counts WARNING+ records without emitting them anywhere.

    Used on the `transitions` logger: an invalid statechart trigger
    (e.g. a car receiving `start` while already in AssemblyAtStation)
    logs one warning per occurrence. Nonzero counts flag a routing
    regression or, under extreme overload, QoS-0 broker drops punching
    holes in a car's scan sequence (see verify_summary's W5) — worth
    counting either way, but printing hundreds of warnings to stderr
    would perturb the very timing being measured.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record) -> None:  # noqa: ARG002
        self.count += 1


class ResourceSampler:
    """Samples CPU% and RSS for the ENGINE process at a fixed interval.

    The generator runs in a separate process, so its publish cost is not
    included in these samples — unlike bench/, where generator and engine
    shared one process. CPU% is normalized by the logical core count.
    """

    def __init__(self, interval_s: float = 0.5):
        self.interval_s = interval_s
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc = psutil.Process()
        self._n_cores = psutil.cpu_count(logical=True) or 1

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                cpu = self._proc.cpu_percent(interval=self.interval_s)
                mem = self._proc.memory_info().rss
                threads = self._proc.num_threads()
                self.samples.append(
                    {
                        "t": time.time(),
                        "cpu_percent_norm": cpu / self._n_cores,
                        "rss_mb": mem / (1024 * 1024),
                        "num_threads": threads,
                    }
                )
            except Exception:
                pass

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)


def quantile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[idx]


def _f(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def analyze_latency_csv(
    path: str, n_workstations: int, cycle_time_s: float, arrival: str
) -> dict[str, Any]:
    """Single pass over the per-event CSV: latency stats + line metrics.

    Line metrics come from the car rows:
      - an exit is a car `done` row with ws_num == N (this is the event
        whose handling fires started_inspection in CarAgent);
      - a full traversal is a car whose first `start` row has ws_num == 1
        and that also has an exit row. Lead time = exit handle_end minus
        first-start mqtt_in (perf_counter stamps, comparable across
        threads within the engine process).
    """
    import csv

    out: dict[str, Any] = {"rows": 0, "rows_car": 0, "rows_ws": 0, "rows_ws_scan": 0}
    if not os.path.exists(path):
        return out

    e2e_car: list[float] = []
    e2e_ws: list[float] = []
    inbox_car: list[float] = []
    inbox_ws: list[float] = []
    handle_all: list[float] = []
    # The paper's "handling" metric: per-event dispatch + statechart
    # cost, i.e. e2e minus inbox wait, split by agent kind.
    handling_car: list[float] = []
    handling_ws: list[float] = []

    # car_id -> [first_start_at_ws1_perf, exit_handle_end_perf]
    car_first_start: dict[str, float] = {}
    car_exit_end: dict[str, float] = {}
    exit_walls: list[float] = []
    car_wall_min: float | None = None
    car_wall_max: float | None = None

    # Tracking-integrity detection. In a healthy trace a car's events
    # alternate start/done; a `start` directly following a `start` means
    # the car's exit at some station never registered. Two known causes:
    # a routing regression (the dual-writer `current_workstation` race
    # this detector originally caught, fixed by BarcodeProcessor's
    # single-writer position map — these columns remain as the canary),
    # and, under extreme overload only, QoS-0 broker drops that swallow
    # scans before dispatch (holes come with car ws_num jumps and large
    # car_events_missing; see verify_summary's W5). `cars_mistracked`
    # counts cars that broke at least once; a car may recover when a
    # later `start` resyncs its position.
    car_prev_event: dict[str, str] = {}
    misrouted_scans = 0
    cars_broken: set[str] = set()

    with open(path) as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            out["rows"] += 1
            kind = row["kind"]
            e2e = _f(row["e2e_s"])
            handle = _f(row["handle_s"])
            m2i = _f(row["mqtt_to_inbox_s"])
            if handle is not None:
                handle_all.append(handle * 1000.0)

            if kind == "ws":
                out["rows_ws"] += 1
                # Scan-driven WS events only; the rest are lifecycle rows
                # (prod_start, green from PLC init, prod_finish) that have
                # no corresponding scanner publish.
                if row["event_type"] in ("busy", "done"):
                    out["rows_ws_scan"] += 1
                    if e2e is not None:
                        e2e_ws.append(e2e * 1000.0)
                    iw_ws = _f(row["inbox_wait_s"])
                    if iw_ws is not None:
                        inbox_ws.append(iw_ws * 1000.0)
                    if m2i is not None and handle is not None:
                        handling_ws.append((m2i + handle) * 1000.0)
                continue
            if kind != "car":
                continue

            out["rows_car"] += 1
            wall = _f(row["wallclock"])
            if wall is not None:
                car_wall_min = wall if car_wall_min is None else min(car_wall_min, wall)
                car_wall_max = wall if car_wall_max is None else max(car_wall_max, wall)
            if e2e is not None:
                e2e_car.append(e2e * 1000.0)
            iw = _f(row["inbox_wait_s"])
            if iw is not None:
                inbox_car.append(iw * 1000.0)
            if m2i is not None and handle is not None:
                handling_car.append((m2i + handle) * 1000.0)

            event = row["event_type"]
            ws_num = _f(row["ws_num"])
            agent = row["agent"]
            if event == "start" and car_prev_event.get(agent) == "start":
                misrouted_scans += 1
                cars_broken.add(agent)
            car_prev_event[agent] = event
            if event == "start" and ws_num == 1 and agent not in car_first_start:
                # Anchor at MQTT receive; fall back to inbox/handle stamps
                # (mqtt_in is absent only for bus-delivered events).
                t0 = (
                    _f(row["mqtt_in_perf"])
                    or _f(row["inbox_in_perf"])
                    or _f(row["handle_start_perf"])
                )
                if t0 is not None:
                    car_first_start[agent] = t0
            elif event == "done" and ws_num == n_workstations:
                t1 = _f(row["handle_end_perf"])
                if t1 is not None and agent not in car_exit_end:
                    car_exit_end[agent] = t1
                    if wall is not None:
                        exit_walls.append(wall)

    # --- Latency stats ------------------------------------------------------
    out.update(
        {
            "car_e2e_ms_median": quantile(e2e_car, 0.5),
            "car_e2e_ms_p95": quantile(e2e_car, 0.95),
            "car_e2e_ms_p99": quantile(e2e_car, 0.99),
            "car_inbox_wait_ms_median": quantile(inbox_car, 0.5),
            "car_inbox_wait_ms_p95": quantile(inbox_car, 0.95),
            "ws_e2e_ms_median": quantile(e2e_ws, 0.5),
            "ws_e2e_ms_p95": quantile(e2e_ws, 0.95),
            "ws_inbox_wait_ms_median": quantile(inbox_ws, 0.5),
            "ws_inbox_wait_ms_p95": quantile(inbox_ws, 0.95),
            "handle_ms_median": quantile(handle_all, 0.5),
            "car_handling_ms_median": quantile(handling_car, 0.5),
            "car_handling_ms_p95": quantile(handling_car, 0.95),
            "ws_handling_ms_median": quantile(handling_ws, 0.5),
            "ws_handling_ms_p95": quantile(handling_ws, 0.95),
        }
    )
    # Car scans per second over the span they were actually handled —
    # the cleanest cross-experiment throughput number (excludes init,
    # includes drain only while events were still flowing).
    if car_wall_min is not None and car_wall_max is not None and car_wall_max > car_wall_min:
        out["sustained_scans_eps"] = round(out["rows_car"] / (car_wall_max - car_wall_min), 2)

    out["misrouted_scans"] = misrouted_scans
    out["cars_mistracked"] = len(cars_broken)
    out["cars_lost"] = len(
        [c for c in cars_broken if c not in car_exit_end and c in car_first_start]
    )

    # --- Exit / takt metrics --------------------------------------------------
    exit_walls.sort()
    out["cars_exited"] = len(exit_walls)
    if len(exit_walls) >= 2:
        span = exit_walls[-1] - exit_walls[0]
        interdep = [b - a for a, b in zip(exit_walls, exit_walls[1:], strict=False)]
        mean_i = statistics.fmean(interdep)
        out["exit_rate_per_min"] = (
            round((len(exit_walls) - 1) / span * 60.0, 3) if span > 0 else float("nan")
        )
        out["interdeparture_s_median"] = round(statistics.median(interdep), 4)
        out["interdeparture_s_mean"] = round(mean_i, 4)
        out["interdeparture_cv"] = (
            round(statistics.pstdev(interdep) / mean_i, 4) if mean_i > 0 else float("nan")
        )
        # 1.0 = the DT observes exactly the commanded takt.
        out["takt_ratio"] = round(statistics.median(interdep) / cycle_time_s, 4)

    # --- Lead-time metrics ------------------------------------------------------
    leads = [
        car_exit_end[c] - car_first_start[c]
        for c in car_first_start
        if c in car_exit_end and car_exit_end[c] > car_first_start[c]
    ]
    out["lead_time_n"] = len(leads)
    if leads:
        # Burst mode: a car entering at boundary i exits at boundary i+N.
        # Staggered mode: it enters at WS1's slot and exits at WS N's slot
        # N cycles later, adding the (N-1)*T/N phase spread.
        ideal = n_workstations * cycle_time_s
        if arrival == "staggered":
            ideal += (n_workstations - 1) * cycle_time_s / n_workstations
        med = statistics.median(leads)
        out["lead_time_s_median"] = round(med, 4)
        out["lead_time_s_p95"] = round(quantile(leads, 0.95), 4)
        out["lead_time_s_ideal"] = round(ideal, 4)
        # DT-side inflation over the paced ideal, in ms. Small NEGATIVE
        # values are expected sub-saturation: within a cycle burst the
        # enter scans are published (a burst-length) after the exit scans,
        # so the offered lead is N*T minus up to one burst, and OS timer
        # jitter adds a few ms either way. The column is meaningful once
        # |overhead| clearly exceeds max_burst_s + ~10 ms.
        out["lead_overhead_ms_median"] = round((med - ideal) * 1000.0, 3)
    return out


def _run_generator_subprocess(args, cycles: int) -> dict:
    """Launch line_generator.py as its own process; return its JSON stats."""
    cmd = [
        sys.executable,
        "-m",
        "bench_line.line_generator",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--total-workstations",
        str(args.N),
        "--workstations-per-cell",
        str(args.ws_per_cell),
        "--cycle-time",
        str(args.cycle_time),
        "--cycles",
        str(cycles),
        "--arrival",
        args.arrival,
    ]
    # Generous timeout: connect/init sleeps + paced runtime + slip margin.
    timeout = 60.0 + cycles * args.cycle_time * 1.5 + args.N * 0.02
    proc = subprocess.Popen(
        cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        out, err = proc.communicate()
        raise RuntimeError(
            f"Generator timed out after {timeout:.0f}s. stderr tail: {err[-500:]}"
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(f"Generator exited with {proc.returncode}. stderr tail: {err[-1000:]}")
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(f"Generator produced no JSON stats. stdout tail: {out[-500:]}")


def run(args) -> dict[str, Any]:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    run_tag = f"N{args.N}_T{args.cycle_time:g}_{args.arrival}"
    if args.tag:
        run_tag += f"_{args.tag}"
    latency_path = os.path.join(RESULTS_DIR, f"{run_tag}_latency.csv")
    engine_log_path = os.path.join(RESULTS_DIR, f"{run_tag}_engine.log")
    resources_path = os.path.join(RESULTS_DIR, f"{run_tag}_resources.csv")
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Silence INFO chatter (same rationale as bench/benchmark.py: per-event
    # INFO lines serialize the MQTT receive thread on Windows terminals).
    for namespace in ("transitions", "tiger_motors_dt", "mabdt"):
        logging.getLogger(namespace).setLevel(logging.WARNING)

    # Count invalid-transition warnings instead of printing them.
    warn_counter = _WarningCounter()
    trans_logger = logging.getLogger("transitions")
    trans_logger.addHandler(warn_counter)
    trans_logger.propagate = False

    cycles = args.cycles
    if cycles is None:
        if args.duration is not None:
            # Fixed observation window (grid mode): at least a few cycles
            # so takt/exit metrics exist even when T is large.
            cycles = max(5, math.ceil(args.duration / args.cycle_time))
        else:
            # Enough cycles for full-traversal lead times (N + lead_cars),
            # but never a shorter run than min_duration seconds.
            cycles = max(args.N + args.lead_cars, math.ceil(args.min_duration / args.cycle_time))
    if cycles > args.max_cycles:
        # Each cycle creates one CarAgent (one OS thread that lives until
        # shutdown), so unbounded cycle counts at small T exhaust threads.
        print(
            f"[bench_line] capping cycles {cycles} -> {args.max_cycles} "
            f"(--max-cycles; one car thread is created per cycle)",
            flush=True,
        )
        cycles = args.max_cycles

    rate_eps = 2.0 * args.N / args.cycle_time
    est_runtime = cycles * args.cycle_time
    lead_expected = max(0, cycles - args.N)
    print(
        f"[bench_line] N={args.N} T={args.cycle_time:g}s (r={rate_eps:.0f} eps) "
        f"arrival={args.arrival} cycles={cycles} est_paced_runtime={est_runtime:.0f}s "
        f"expected_exits={cycles} expected_lead_cars~{lead_expected}",
        flush=True,
    )
    if lead_expected == 0:
        print(
            f"[bench_line] NOTE: cycles ({cycles}) <= N ({args.N}); no car traverses "
            f"the full line, so lead-time columns will be empty (takt/exit metrics "
            f"and latency are still measured).",
            flush=True,
        )

    cfg = build_config(args.N, args.ws_per_cell, args.host, args.port)

    instrument.enable(latency_path)

    env = TigerMotorsEnvironment(config=cfg)
    env.initialize()
    time.sleep(1.0)  # let MQTT connect and subscriptions register
    env.start_production()

    sampler = ResourceSampler(interval_s=0.5)
    sampler.start()

    # Redirect engine prints to a per-run log so they don't pollute stdout.
    engine_log = open(engine_log_path, "w", buffering=8192)  # noqa: SIM115
    real_stdout = sys.stdout
    t0 = time.time()
    gen_stats: dict = {}
    try:
        sys.stdout = engine_log
        if args.in_process:
            gen = LineBenchmarkGenerator(
                mqtt_host=args.host,
                mqtt_port=args.port,
                total_workstations=args.N,
                workstations_per_cell=args.ws_per_cell,
                cycle_time_s=args.cycle_time,
                cycles=cycles,
                arrival=args.arrival,
            )
            gen_stats = gen.run()
        else:
            gen_stats = _run_generator_subprocess(args, cycles)

        # Drain until the engine goes quiet: no new latency rows for one
        # poll interval, or the drain cap expires. Replaces bench/'s fixed
        # 0.5 s sleep, which under-drained saturated runs.
        drain_t0 = time.time()
        last_rows = -1
        while time.time() - drain_t0 < args.max_drain:
            rows_now = _bench.rows_written()
            if rows_now == last_rows:
                break
            last_rows = rows_now
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        # Teardown watchdog. At heavily saturated cells the workstation
        # agents queue 10^5-10^6 QoS-2 LED/cycle-time messages into paho's
        # outbound queue; paho's loop_forever refuses to honor loop_stop
        # until that queue drains through the broker, so env.shutdown()
        # (comm agent -> protocol.disconnect -> loop_stop -> join) can
        # block for hours. Those queued publishes are workload
        # side-effects, not measurements — run the teardown on a worker
        # thread, and if it exceeds the deadline, close the latency log
        # ourselves and let main() hard-exit after the summary is written
        # (every engine thread is a daemon). Measurements are unaffected:
        # the measurement window ended before teardown began.
        teardown_forced = False

        def _teardown() -> None:
            env.stop_production()
            sampler.stop()
            env.shutdown()
            instrument.disable()

        try:
            teardown_thread = threading.Thread(target=_teardown, daemon=True)
            teardown_thread.start()
            teardown_thread.join(timeout=120.0 + 0.1 * args.N)
            if teardown_thread.is_alive():
                teardown_forced = True
                sampler.stop()
                instrument.disable()  # idempotent; closes the CSV so parsing sees all rows
        finally:
            sys.stdout = real_stdout
            engine_log.close()
        if teardown_forced:
            print(
                f"[bench_line] WARNING: teardown exceeded {120.0 + 0.1 * args.N:.0f}s "
                f"(paho draining outbound backlog); abandoning it after the summary "
                f"is written. Metrics are unaffected.",
                flush=True,
            )

    duration_actual = time.time() - t0

    # Persist the raw resource samples: RSS growth over a run gives the
    # per-car-agent memory footprint, and the CPU trace separates priming
    # from steady state. Not reconstructable from any other output.
    import csv as _csv

    with open(resources_path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["t", "cpu_percent_norm", "rss_mb", "num_threads"])
        for s in sampler.samples:
            w.writerow([s["t"], s["cpu_percent_norm"], s["rss_mb"], s["num_threads"]])

    # Drop the first sampler reading — it's the warm-up window.
    samples = sampler.samples[1:] if len(sampler.samples) > 1 else sampler.samples
    cpu_vals = [s["cpu_percent_norm"] for s in samples]
    rss_vals = [s["rss_mb"] for s in samples]
    thr_vals = [s["num_threads"] for s in samples]

    runner_runtime = float(gen_stats.get("runner_runtime_s", 0.0) or 0.0)
    events_published = int(gen_stats.get("events_published", 0) or 0)

    summary: dict[str, Any] = {
        "N": args.N,
        "arrival": args.arrival,
        "tag": args.tag,
        "timestamp": started_at,
        "cycle_time_s": args.cycle_time,
        "rate_offered_eps": round(rate_eps, 2),
        "cycles": cycles,
        "cycles_completed": gen_stats.get("cycles_completed", 0),
        "duration_s": round(duration_actual, 2),
        "runner_runtime_s": round(runner_runtime, 2),
        "events_published": events_published,
        "prime_publish_s": gen_stats.get("prime_publish_s", ""),
        "boundaries_late": gen_stats.get("boundaries_late", ""),
        "max_slip_s": gen_stats.get("max_slip_s", ""),
        "mean_burst_s": gen_stats.get("mean_burst_s", ""),
        "max_burst_s": gen_stats.get("max_burst_s", ""),
        "cpu_percent_norm_mean": round(statistics.fmean(cpu_vals), 1) if cpu_vals else 0.0,
        "cpu_percent_norm_max": round(max(cpu_vals), 1) if cpu_vals else 0.0,
        "rss_mb_max": round(max(rss_vals), 1) if rss_vals else 0.0,
        "num_threads_max": max(thr_vals) if thr_vals else 0,
    }

    summary.update(analyze_latency_csv(latency_path, args.N, args.cycle_time, args.arrival))

    # Every scan routes to exactly one car event (start/done) and one
    # workstation event (busy/done), so both counts should equal
    # events_published. A shortfall means events were still queued at
    # shutdown or lost before dispatch. rows_ws additionally contains a
    # few lifecycle rows per WS (prod_start, green, prod_finish), which is
    # why the scan-only count is compared here.
    rows_car = summary.get("rows_car", 0) or 0
    rows_ws_scan = summary.get("rows_ws_scan", 0) or 0
    summary["throughput_eps"] = (
        round((summary.get("rows", 0) or 0) / max(runner_runtime, 0.001), 2)
        if runner_runtime
        else 0.0
    )
    # Old bench/ parity: scans processed per second of generator runtime
    # (bench/analyze.py's `_row_throughput`, car rows only). This is the
    # column to place against the old saturation table.
    summary["processed_scans_eps"] = (
        round(rows_car / max(runner_runtime, 0.001), 2) if runner_runtime else 0.0
    )
    summary["car_events_missing"] = max(0, events_published - rows_car)
    summary["ws_events_missing"] = max(0, events_published - rows_ws_scan)
    summary["invalid_transition_warnings"] = warn_counter.count
    # JSON-only flag (deliberately NOT in SUMMARY_FIELDS: adding a CSV
    # column mid-sweep would misalign against the existing file header).
    summary["teardown_forced"] = int(teardown_forced)
    trans_logger.removeHandler(warn_counter)
    trans_logger.propagate = True
    summary["latency_csv"] = os.path.basename(latency_path)

    write_header = not os.path.exists(SUMMARY_CSV)
    import csv as _csv

    with open(SUMMARY_CSV, "a", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, restval="", extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow(summary)

    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--N", type=int, required=True, help="Number of workstations.")
    p.add_argument("--ws-per-cell", type=int, default=5)
    p.add_argument(
        "--cycle-time",
        type=float,
        default=None,
        help="Line cycle time T in seconds. Offered rate is 2N/T events/s.",
    )
    p.add_argument(
        "--rate",
        type=float,
        default=None,
        help="Alternative to --cycle-time: offered event rate in events/s; T = 2N/rate.",
    )
    p.add_argument(
        "--arrival",
        choices=("staggered", "burst"),
        default="staggered",
        help="Arrival pattern: 'staggered' phases stations across the cycle "
        "(uniform arrivals, comparable to bench/); 'burst' fires all stations "
        "at the boundary (synchronized worst case).",
    )
    p.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="Paced cycles to run. Default: max(N + lead-cars, min-duration/T), "
        "or max(5, duration/T) when --duration is given. Full-traversal lead "
        "times require cycles >= N + 1.",
    )
    p.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Grid mode: target a fixed observation window in seconds instead of "
        "a lead-time car count (cycles = max(5, duration/T)).",
    )
    p.add_argument(
        "--lead-cars",
        type=int,
        default=25,
        help="Default cycle count targets this many full-traversal lead-time cars.",
    )
    p.add_argument(
        "--min-duration",
        type=float,
        default=30.0,
        help="Minimum paced runtime in seconds when --cycles/--duration are not given.",
    )
    p.add_argument(
        "--max-cycles",
        type=int,
        default=5000,
        help="Hard cap on cycles: each cycle creates one CarAgent thread that "
        "lives until shutdown, so unbounded counts exhaust OS threads.",
    )
    p.add_argument(
        "--max-drain",
        type=float,
        default=60.0,
        help="Post-run drain cap in seconds. Sub-saturation runs exit the drain "
        "in under a second; the cap only bounds saturated cells, and a generous "
        "cap lets them demonstrate that backlog is delayed, not lost.",
    )
    p.add_argument(
        "--tag",
        default="",
        help="Optional label appended to output filenames and stored in the "
        "summary (e.g. rep1/rep2 for repetition sweeps).",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8883)
    p.add_argument(
        "--in-process",
        action="store_true",
        help="Run the generator in this process instead of a subprocess (diagnostics only; "
        "reintroduces GIL sharing between publisher and engine).",
    )
    args = p.parse_args()

    if (args.cycle_time is None) == (args.rate is None):
        p.error("Give exactly one of --cycle-time or --rate.")
    if args.cycle_time is None:
        args.cycle_time = 2.0 * args.N / args.rate
    if args.cycles is not None and args.duration is not None:
        p.error("Give at most one of --cycles or --duration.")

    summary = run(args)
    print(json.dumps(summary, indent=2))
    if summary.get("teardown_forced"):
        # Abandon the wedged paho drain: every remaining thread is a
        # daemon, the summary row and JSON are already out.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
