"""Single-N benchmark runner for the scaling study.

Boots the engine with N workstations, runs the synthetic generator at a
target event rate for a fixed duration, samples CPU/RAM/threads, and
writes one summary row plus a detailed latency CSV.

Usage:
    python -m bench.benchmark --N 15 --duration 60 --rate 30
    python -m bench.benchmark --N 500 --duration 60 --rate 30

The instrumentation hooks are applied before the environment is built,
so no engine source needs to be modified. See bench/instrument.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import threading
import time
from typing import Any

import psutil

# Project root is the parent of the bench/ folder.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Patches must land BEFORE the env module is imported, because importing
# the env triggers chains that touch the Agent base class.
from bench import instrument
from bench.benchmark_generator import BenchmarkGenerator

# Engine imports happen after the patches are wired into module-level
# class objects (the patches activate when enable() is called, but
# importing here keeps the order obvious to readers).
from tiger_motors_dt.simulation.environment import TigerMotorsEnvironment

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BENCH_DIR, "results")
SUMMARY_CSV = os.path.join(RESULTS_DIR, "summary.csv")
DEFAULT_CONFIG = os.path.join(BENCH_DIR, "config_benchmark.json")


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


class ResourceSampler:
    """Samples CPU% and RSS for the current process at a fixed interval.

    Uses a blocking cpu_percent() call so each sample measures over a known
    window — avoids garbage readings from too-short intervals on Windows.
    The reported CPU% is summed across cores; we normalize by dividing by
    psutil.cpu_count() to keep the metric comparable across machines.
    """

    def __init__(self, interval_s: float = 1.0):
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
                        "cpu_percent": cpu,
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


def summarize_latency_csv(path: str) -> dict[str, float]:
    """Read the per-event latency CSV and return summary stats in milliseconds."""
    e2e: list[float] = []
    inbox: list[float] = []
    mtoi: list[float] = []
    handle: list[float] = []
    rows = 0
    if not os.path.exists(path):
        return {"rows": 0}
    with open(path) as f:
        header = f.readline().strip().split(",")
        try:
            i_mtoi = header.index("mqtt_to_inbox_s")
            i_inbox = header.index("inbox_wait_s")
            i_handle = header.index("handle_s")
            i_e2e = header.index("e2e_s")
        except ValueError:
            return {"rows": 0}

        def _push(lst, idx, parts):
            v = parts[idx]
            if v:
                try:
                    lst.append(float(v) * 1000.0)  # to ms
                except ValueError:
                    pass

        for line in f:
            parts = line.rstrip("\n").split(",")
            rows += 1
            _push(mtoi, i_mtoi, parts)
            _push(inbox, i_inbox, parts)
            _push(handle, i_handle, parts)
            _push(e2e, i_e2e, parts)
    return {
        "rows": rows,
        "e2e_ms_median": quantile(e2e, 0.5),
        "e2e_ms_p95": quantile(e2e, 0.95),
        "e2e_ms_p99": quantile(e2e, 0.99),
        "inbox_wait_ms_median": quantile(inbox, 0.5),
        "inbox_wait_ms_p95": quantile(inbox, 0.95),
        "mqtt_to_inbox_ms_median": quantile(mtoi, 0.5),
        "handle_ms_median": quantile(handle, 0.5),
    }


def run(args) -> dict[str, Any]:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    # Include the rate in the per-run filenames so a sensitivity sweep
    # over (N x rate) doesn't overwrite earlier points.
    run_tag = f"N{args.N}_R{int(args.rate)}"
    latency_path = os.path.join(RESULTS_DIR, f"{run_tag}_latency.csv")
    engine_log_path = os.path.join(RESULTS_DIR, f"{run_tag}_engine.log")

    # Silence INFO chatter from the processors and agents. Each processor
    # logs one INFO line per event ("WS1: GRN light", "Car SUV0 scanned at
    # C1WS1", etc.). Python's logging writes to stderr by default, which on
    # Windows means a per-line terminal render of 50-200 ms. With 1000
    # init publishes that serializes the entire MQTT receive thread for a
    # minute or more — exactly long enough for the benchmark's
    # time.sleep(args.duration) to expire during init. Keeping only
    # WARNING+ collapses init from tens of seconds to milliseconds.
    for namespace in ("transitions", "tiger_motors_dt", "mabdt"):
        logging.getLogger(namespace).setLevel(logging.WARNING)

    cfg = build_config(args.N, args.ws_per_cell, args.host, args.port)

    print(
        f"[bench] N={args.N} cells={cfg['facility']['cells']} "
        f"ws_per_cell={cfg['facility']['workstations_per_cell']} "
        f"rate={args.rate} eps duration={args.duration}s",
        flush=True,
    )

    instrument.enable(latency_path)

    env = TigerMotorsEnvironment(config=cfg)
    env.initialize()
    time.sleep(1.0)  # let MQTT connect and subscriptions register
    env.start_production()

    sampler = ResourceSampler(interval_s=0.5)
    sampler.start()

    cars_in_flight = max(args.N // 5, 5)
    gen = BenchmarkGenerator(
        mqtt_host=args.host,
        mqtt_port=args.port,
        total_workstations=args.N,
        workstations_per_cell=cfg["facility"]["workstations_per_cell"],
        cars_in_flight=cars_in_flight,
        events_per_second=args.rate,
    )

    # Redirect engine prints (comm_agent status spam) to a per-run log so
    # they don't pollute stdout or contend for IO during the run. The
    # handle is closed in the matching `finally` block below; can't use a
    # `with` here because the redirect spans the entire run.
    engine_log = open(engine_log_path, "w", buffering=8192)  # noqa: SIM115
    real_stdout = sys.stdout
    t0 = time.time()
    try:
        sys.stdout = engine_log
        gen.start()
        try:
            time.sleep(args.duration)
        except KeyboardInterrupt:
            pass
        finally:
            gen.stop()
            time.sleep(0.5)  # drain
            env.stop_production()
            sampler.stop()
            env.shutdown()
            instrument.disable()
    finally:
        sys.stdout = real_stdout
        engine_log.close()

    duration_actual = time.time() - t0
    runner_runtime = gen.runner_runtime_s

    # Drop the first sampler reading — it's the warm-up window.
    samples = sampler.samples[1:] if len(sampler.samples) > 1 else sampler.samples
    cpu_vals = [s["cpu_percent_norm"] for s in samples]
    rss_vals = [s["rss_mb"] for s in samples]
    thr_vals = [s["num_threads"] for s in samples]
    summary = {
        "N": args.N,
        "rate_target_eps": args.rate,
        "duration_s": round(duration_actual, 2),
        "runner_runtime_s": round(runner_runtime, 2),
        "events_published": gen.events_published,
        # Throughput as seen by the engine during the active publish
        # window — divides by runner_runtime_s, NOT total benchmark
        # wall-clock. At large N, env.shutdown joining all WS threads
        # adds seconds-to-minutes of cost that aren't part of dispatch.
        "throughput_eps": round(gen.events_published / max(runner_runtime, 0.001), 2),
        # Kept for diagnostics: shows how much of the wall-clock was spent
        # outside the publish window (init + shutdown). Should equal
        # throughput_eps for small N and diverge as N grows.
        "throughput_walltime_eps": round(gen.events_published / max(duration_actual, 0.001), 2),
        "cpu_percent_norm_mean": round(statistics.fmean(cpu_vals), 1) if cpu_vals else 0.0,
        "cpu_percent_norm_max": round(max(cpu_vals), 1) if cpu_vals else 0.0,
        "rss_mb_max": round(max(rss_vals), 1) if rss_vals else 0.0,
        "num_threads_max": max(thr_vals) if thr_vals else 0,
    }
    summary.update(summarize_latency_csv(latency_path))
    # Events that reached the broker but never produced a latency row.
    # The two known reasons in the Tiger Motors deployment:
    #   - `StateMachineAgent.is_duplicate_message` filters events with the
    #     same dedup key within a 1 s window. Triggered at high per-WS
    #     rates (e.g. N=15 / rate=1000 where each WS sees a "busy"/"done"
    #     pair every ~75 ms).
    #   - Messages that arrived after `env.stop_production` flipped the
    #     gate closed but before the generator finished its publish loop.
    # The benchmark.record() callback also skips tick events, but those
    # aren't counted in events_published, so they don't show up here.
    rows_count = summary.get("rows", 0) or 0
    summary["events_dropped"] = max(0, gen.events_published - rows_count)
    summary["latency_csv"] = os.path.basename(latency_path)

    write_header = not os.path.exists(SUMMARY_CSV)
    fields = list(summary.keys())
    with open(SUMMARY_CSV, "a", newline="") as f:
        import csv as _csv

        w = _csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        w.writerow(summary)

    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--N", type=int, required=True, help="Number of workstations.")
    p.add_argument("--ws-per-cell", type=int, default=5)
    p.add_argument("--rate", type=float, default=30.0, help="Synthetic event rate (events/sec).")
    p.add_argument("--duration", type=float, default=60.0, help="Run duration in seconds.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8883)
    args = p.parse_args()
    summary = run(args)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
