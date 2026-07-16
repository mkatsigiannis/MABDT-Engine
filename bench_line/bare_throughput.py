"""Instrumentation-free saturated-throughput check: the exit clock.

The latency harness observes the engine through four runtime patches
(bench_line/instrument.py) whose timestamps and shared log lock execute
on the measured threads. Below the ceiling this is invisible (bare and
instrumented runs complete the same workload within 0.01 s of each
other), but OVER the ceiling the patches reproducibly speed the engine
up: throttling the many agent threads un-starves the single dispatch
thread (a GIL-scheduling effect; verified not to be disk I/O — logging
to the null device changes nothing). Saturated-regime absolute
throughput is therefore harness-coupled, and this script measures it
with NO patches applied, using the only progress signal visible from
agent state alone — line exits (`CarAgent.current_workstation == N+1`):

    effective_eps = events_offered / (wall time until all offered cars exited)

Use an over-ceiling rate so completion is engine-bound rather than
schedule-bound, and compare the two modes at the same cell to quantify
the coupling. Run each mode in a fresh process (patches are
process-global):

    python -m bench_line.bare_throughput --N 50 --rate 5000 --mode bare
    python -m bench_line.bare_throughput --N 50 --rate 5000 --mode instrumented

Prints one JSON line; writes no result files (in instrumented mode the
latency log goes to the null device — content is irrelevant here).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bench_line.benchmark import build_config
from tiger_motors_dt.simulation.environment import TigerMotorsEnvironment


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("bare", "instrumented"), required=True)
    p.add_argument("--N", type=int, default=50)
    p.add_argument("--ws-per-cell", type=int, default=5)
    p.add_argument("--rate", type=float, default=5000.0, help="Offered rate 2N/T in events/s.")
    p.add_argument("--duration", type=float, default=30.0, help="Publish window in seconds.")
    p.add_argument(
        "--max-cycles",
        type=int,
        default=5000,
        help="Cycle cap (one CarAgent thread per cycle; see bench_line.benchmark).",
    )
    p.add_argument(
        "--stall-timeout",
        type=float,
        default=20.0,
        help="Give up this many seconds after the last exit if the publisher has finished "
        "(a dropped final scan under extreme overload would strand a car short of exit).",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8883)
    args = p.parse_args()

    cycle_time = 2.0 * args.N / args.rate
    cycles = min(args.max_cycles, max(5, math.ceil(args.duration / cycle_time)))
    events = args.N + 2 * args.N * cycles

    for ns in ("transitions", "tiger_motors_dt", "mabdt"):
        logging.getLogger(ns).setLevel(logging.ERROR)

    if args.mode == "instrumented":
        from bench_line import instrument

        instrument.enable(os.devnull)

    # Engine prints go to the void; only the JSON result reaches stdout.
    devnull = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    real_stdout = sys.stdout
    sys.stdout = devnull
    env = TigerMotorsEnvironment(
        config=build_config(args.N, args.ws_per_cell, args.host, args.port)
    )
    env.initialize()
    time.sleep(1.0)
    env.start_production()

    t0 = time.perf_counter()
    gen = subprocess.Popen(
        [
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
            str(cycle_time),
            "--cycles",
            str(cycles),
            "--arrival",
            "staggered",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def exits_observed() -> int:
        try:
            return sum(1 for c in list(env.cars.values()) if c.current_workstation == args.N + 1)
        except RuntimeError:  # cars dict mutated mid-scan; retry next poll
            return -1

    done_at = None
    last_n, last_growth = 0, time.perf_counter()
    while True:
        n = exits_observed()
        now = time.perf_counter()
        if n > last_n:
            last_n, last_growth = n, now
        if n >= cycles:
            done_at = now
            break
        if gen.poll() is not None and now - last_growth > args.stall_timeout:
            break
        time.sleep(0.25)
    try:
        gen.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        gen.kill()

    completion_s = (done_at if done_at is not None else last_growth) - t0
    result = {
        "mode": args.mode,
        "N": args.N,
        "rate_offered_eps": args.rate,
        "cycle_time_s": round(cycle_time, 6),
        "cycles": cycles,
        "events_offered": events,
        "exits_observed": last_n,
        "completed": done_at is not None,
        "time_to_completion_s": round(completion_s, 2),
        "effective_eps": round(events * last_n / cycles / completion_s, 1),
    }
    if args.mode == "instrumented":
        from bench_line import instrumentation as _bench

        result["latency_rows_written"] = _bench.rows_written()

    sys.stdout = real_stdout
    print(json.dumps(result), flush=True)
    sys.stderr.flush()
    # Skip engine teardown: over-ceiling runs leave a QoS-2 outbound
    # backlog that wedges paho's loop_stop (same rationale as the
    # teardown watchdog in bench_line.benchmark). Every engine thread
    # is a daemon and the result is already printed.
    os._exit(0)


if __name__ == "__main__":
    main()
