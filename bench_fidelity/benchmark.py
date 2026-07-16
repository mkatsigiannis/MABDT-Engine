"""Fidelity benchmark runner: stochastic line vs. digital-twin observation.

Boots the engine, replays a seeded stochastic-line schedule against the
broker (bench_fidelity/stochastic_generator.py, separate process), and
quantifies how faithfully the digital twin mirrors the simulated
physical line's GROUND TRUTH:

  - Lead time, paired per car: the generator's true enter@WS1 ->
    exit@WS{N} duration vs. the DT's first-start-received ->
    final-done-handled duration. Reported as paired error (ms) plus a
    two-sample KS distance between the distributions.
  - Exit behavior: true vs. DT-observed inter-departure CV and counts.
  - Utilization: per-station true busy time (sum of service times) vs.
    the DT WorkstationAgent StateTimer's Busy time; includes whether the
    DT localizes the bottleneck station (argmax busy) correctly.

Everything the DT is graded on is emergent — queues forming behind slow
cycles, starvation, the fill transient — none of it is scripted into
the scan stream explicitly.

Engine instrumentation is reused from bench_line (same four patches);
neither engine package is modified. Times: the generator thinks in
REAL line seconds and replays at 1/compression; DT-side measurements are
wall seconds. Comparisons convert to a common basis (wall seconds for
errors, real-line units for the plots).

Usage:
    python -m bench_fidelity.benchmark --cars 120 --compression 100 --seed 1
    python -m bench_fidelity.benchmark --bottleneck-station 8 --seed 1
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import subprocess
import sys
import time
from typing import Any

# Project root is the parent of the bench_fidelity/ folder.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Patches must land BEFORE the env module is imported. Reused from
# bench_line: identical timing hooks, identical CSV format.
from bench_line import instrument
from bench_line import instrumentation as _bench
from bench_line.benchmark import ResourceSampler, _WarningCounter, build_config, quantile
from tiger_motors_dt.simulation.environment import TigerMotorsEnvironment

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BENCH_DIR, "results")
SUMMARY_CSV = os.path.join(RESULTS_DIR, "summary.csv")

SUMMARY_FIELDS = [
    "N",
    "scenario",
    "seed",
    "tag",
    "timestamp",
    "cars",
    "takt_s",
    "tri_min",
    "tri_mode",
    "tri_max",
    "bottleneck_station",
    "bottleneck_factor",
    "compression",
    "sim_makespan_s",
    "runner_runtime_s",
    "duration_s",
    "events_published",
    "publishes_late",
    "max_slip_s",
    "rows",
    "rows_car",
    "rows_ws_scan",
    "car_events_missing",
    "ws_events_missing",
    "misrouted_scans",
    "cars_mistracked",
    "invalid_transition_warnings",
    "cars_exited_true",
    "cars_exited_dt",
    "true_lead_real_s_median",
    "true_lead_real_s_p95",
    "dt_lead_real_s_median",
    "dt_lead_real_s_p95",
    "lead_pairs_n",
    "lead_err_ms_median",
    "lead_err_ms_p95",
    "lead_ks",
    "true_exit_cv",
    "dt_exit_cv",
    "exit_cv_abs_err",
    "true_bottleneck_ws",
    "dt_bottleneck_ws",
    "bottleneck_identified",
    "util_relerr_mean_pct",
    "util_relerr_max_pct",
    "car_e2e_ms_median",
    "car_e2e_ms_p95",
    "ws_e2e_ms_median",
    "cpu_percent_norm_mean",
    "rss_mb_max",
    "num_threads_max",
    "latency_csv",
]


def _f(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ks_distance(a: list[float], b: list[float]) -> float:
    """Two-sample Kolmogorov-Smirnov statistic (max ECDF gap)."""
    if not a or not b:
        return float("nan")
    a, b = sorted(a), sorted(b)
    i = j = 0
    d = 0.0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            i += 1
        else:
            j += 1
        d = max(d, abs(i / len(a) - j / len(b)))
    return round(d, 4)


def parse_truth(path: str, n_stations: int) -> dict[str, Any]:
    """Ground truth from the generator's schedule (real-line seconds)."""
    import csv

    lead: dict[str, float] = {}  # car -> true lead (enter@1 -> exit@N)
    enter1: dict[str, float] = {}
    exits_n: list[float] = []
    busy: dict[int, float] = {k: 0.0 for k in range(1, n_stations + 1)}
    with open(path) as fh:
        for row in csv.DictReader(fh):
            ws = int(row["ws"])
            enter, exit_ = float(row["enter_s"]), float(row["exit_s"])
            busy[ws] += exit_ - enter
            if ws == 1:
                enter1[row["car"]] = enter
            if ws == n_stations:
                exits_n.append(exit_)
                if row["car"] in enter1:
                    lead[row["car"]] = exit_ - enter1[row["car"]]
    exits_n.sort()
    interdep = [b - a for a, b in zip(exits_n, exits_n[1:], strict=False)]
    cv = (
        statistics.pstdev(interdep) / statistics.fmean(interdep)
        if interdep and statistics.fmean(interdep) > 0
        else float("nan")
    )
    return {"lead": lead, "exit_cv": round(cv, 4), "exits": len(exits_n), "busy": busy}


def parse_dt(path: str, n_stations: int) -> dict[str, Any]:
    """DT-observed values from the per-event latency CSV (wall seconds)."""
    import csv

    first_start1: dict[str, float] = {}
    exit_end: dict[str, float] = {}
    exit_walls: list[float] = []
    e2e_car: list[float] = []
    e2e_ws: list[float] = []
    rows = rows_car = rows_ws_scan = 0
    prev_event: dict[str, str] = {}
    misrouted = 0
    broken: set[str] = set()

    with open(path) as fh:
        for row in csv.DictReader(fh):
            rows += 1
            kind = row["kind"]
            e2e = _f(row["e2e_s"])
            if kind == "ws":
                if row["event_type"] in ("busy", "done"):
                    rows_ws_scan += 1
                    if e2e is not None:
                        e2e_ws.append(e2e * 1000.0)
                continue
            if kind != "car":
                continue
            rows_car += 1
            if e2e is not None:
                e2e_car.append(e2e * 1000.0)
            agent = row["agent"]
            event = row["event_type"]
            ws_num = _f(row["ws_num"])
            if event == "start" and prev_event.get(agent) == "start":
                misrouted += 1
                broken.add(agent)
            prev_event[agent] = event
            car = agent.removeprefix("Car-")
            if event == "start" and ws_num == 1 and car not in first_start1:
                t0 = (
                    _f(row["mqtt_in_perf"])
                    or _f(row["inbox_in_perf"])
                    or _f(row["handle_start_perf"])
                )
                if t0 is not None:
                    first_start1[car] = t0
            elif event == "done" and ws_num == n_stations and car not in exit_end:
                t1 = _f(row["handle_end_perf"])
                if t1 is not None:
                    exit_end[car] = t1
                    wall = _f(row["wallclock"])
                    if wall is not None:
                        exit_walls.append(wall)

    lead = {
        c: exit_end[c] - first_start1[c]
        for c in first_start1
        if c in exit_end and exit_end[c] > first_start1[c]
    }
    exit_walls.sort()
    interdep = [b - a for a, b in zip(exit_walls, exit_walls[1:], strict=False)]
    cv = (
        statistics.pstdev(interdep) / statistics.fmean(interdep)
        if interdep and statistics.fmean(interdep) > 0
        else float("nan")
    )
    return {
        "lead": lead,
        "exit_cv": round(cv, 4),
        "exits": len(exit_walls),
        "rows": rows,
        "rows_car": rows_car,
        "rows_ws_scan": rows_ws_scan,
        "e2e_car": e2e_car,
        "e2e_ws": e2e_ws,
        "misrouted_scans": misrouted,
        "cars_mistracked": len(broken),
    }


def make_plots(
    run_tag: str, truth: dict, dt: dict, dt_busy: dict[int, float], compression: float
) -> None:
    """Per-run figures: lead-time ECDF overlay + per-station busy time."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # ECDF overlay in real-line minutes.
    t_leads = sorted(v / 60.0 for v in truth["lead"].values())
    d_leads = sorted(v * compression / 60.0 for v in dt["lead"].values())
    if t_leads and d_leads:
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.step(
            t_leads,
            [i / len(t_leads) for i in range(1, len(t_leads) + 1)],
            where="post",
            label="physical line (ground truth)",
        )
        ax.step(
            d_leads,
            [i / len(d_leads) for i in range(1, len(d_leads) + 1)],
            where="post",
            linestyle="--",
            label="digital twin (observed)",
        )
        ax.set_xlabel("Lead time (real-line minutes)")
        ax.set_ylabel("ECDF")
        ax.set_title(f"Lead-time distribution: truth vs DT ({run_tag})")
        ax.grid(True, linestyle=":", alpha=0.5)
        ax.legend()
        out = os.path.join(RESULTS_DIR, f"{run_tag}_lead_ecdf.png")
        fig.tight_layout()
        fig.savefig(out, dpi=150)
        plt.close(fig)
        print(f"Plot saved: {out}")

    # Per-station busy time in real-line minutes.
    stations = sorted(truth["busy"])
    t_busy = [truth["busy"][k] / 60.0 for k in stations]
    d_busy = [dt_busy.get(k, 0.0) * compression / 60.0 for k in stations]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = range(len(stations))
    ax.bar([i - 0.2 for i in x], t_busy, width=0.4, label="ground truth")
    ax.bar([i + 0.2 for i in x], d_busy, width=0.4, label="digital twin")
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"WS{k}" for k in stations], rotation=45, fontsize=8)
    ax.set_ylabel("Busy time (real-line minutes)")
    ax.set_title(f"Per-station busy time: truth vs DT ({run_tag})")
    ax.grid(True, axis="y", linestyle=":", alpha=0.5)
    ax.legend()
    out = os.path.join(RESULTS_DIR, f"{run_tag}_utilization.png")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {out}")


def run(args) -> dict[str, Any]:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    scenario = "bottleneck" if args.bottleneck_station else "balanced"
    run_tag = f"N{args.N}_C{args.compression:g}_{scenario}_s{args.seed}"
    if args.tag:
        run_tag += f"_{args.tag}"
    latency_path = os.path.join(RESULTS_DIR, f"{run_tag}_latency.csv")
    truth_path = os.path.join(RESULTS_DIR, f"{run_tag}_truth.csv")
    engine_log_path = os.path.join(RESULTS_DIR, f"{run_tag}_engine.log")
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    for namespace in ("transitions", "tiger_motors_dt", "mabdt"):
        logging.getLogger(namespace).setLevel(logging.WARNING)
    warn_counter = _WarningCounter()
    trans_logger = logging.getLogger("transitions")
    trans_logger.addHandler(warn_counter)
    trans_logger.propagate = False

    est_makespan = args.cars * args.takt + (args.N + 30) * (args.tri[2] + args.grab[1])
    print(
        f"[bench_fidelity] N={args.N} cars={args.cars} scenario={scenario} "
        f"seed={args.seed} compression={args.compression:g}x "
        f"takt={args.takt:g}s tri={args.tri} "
        f"est_wall={est_makespan / args.compression:.0f}s",
        flush=True,
    )

    cfg = build_config(args.N, args.ws_per_cell, args.host, args.port)
    instrument.enable(latency_path)

    env = TigerMotorsEnvironment(config=cfg)
    env.initialize()
    time.sleep(1.0)
    env.start_production()

    sampler = ResourceSampler(interval_s=0.5)
    sampler.start()

    engine_log = open(engine_log_path, "w", buffering=8192)  # noqa: SIM115
    real_stdout = sys.stdout
    t0 = time.time()
    gen_stats: dict = {}
    dt_busy: dict[int, float] = {}
    try:
        sys.stdout = engine_log
        cmd = [
            sys.executable,
            "-m",
            "bench_fidelity.stochastic_generator",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--n-stations",
            str(args.N),
            "--workstations-per-cell",
            str(args.ws_per_cell),
            "--cars",
            str(args.cars),
            "--takt",
            str(args.takt),
            "--tri",
            str(args.tri[0]),
            str(args.tri[1]),
            str(args.tri[2]),
            "--grab",
            str(args.grab[0]),
            str(args.grab[1]),
            "--bottleneck-station",
            str(args.bottleneck_station),
            "--bottleneck-factor",
            str(args.bottleneck_factor),
            "--compression",
            str(args.compression),
            "--seed",
            str(args.seed),
            "--truth-out",
            truth_path,
        ]
        timeout = est_makespan / args.compression * 1.5 + 90
        proc = subprocess.Popen(
            cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            out, err = proc.communicate()
            raise RuntimeError(
                f"Generator timed out ({timeout:.0f}s). stderr: {err[-500:]}"
            ) from exc
        if proc.returncode != 0:
            raise RuntimeError(f"Generator exited {proc.returncode}. stderr: {err[-1000:]}")
        for line in reversed(out.strip().splitlines()):
            if line.strip().startswith("{"):
                gen_stats = json.loads(line)
                break

        # Drain until quiet, then read the DT's utilization clocks while
        # the agents are still live (StateTimer stops crediting on pause).
        drain_t0 = time.time()
        last_rows = -1
        while time.time() - drain_t0 < args.max_drain:
            rows_now = _bench.rows_written()
            if rows_now == last_rows:
                break
            last_rows = rows_now
            time.sleep(0.5)
        dt_busy = {ws.ws_num: ws.busy_time for ws in env.workstations.values()}
    except KeyboardInterrupt:
        pass
    finally:
        try:
            env.stop_production()
            sampler.stop()
            env.shutdown()
            instrument.disable()
        finally:
            sys.stdout = real_stdout
            engine_log.close()

    duration_actual = time.time() - t0

    truth = parse_truth(truth_path, args.N)
    dt = parse_dt(latency_path, args.N)

    # --- Paired lead-time comparison (wall seconds) -------------------------
    pairs = [
        (truth["lead"][c] / args.compression, dt["lead"][c])
        for c in truth["lead"]
        if c in dt["lead"]
    ]
    errs_ms = [(d - t) * 1000.0 for t, d in pairs]
    true_leads_wall = [t for t, _ in pairs]
    dt_leads_wall = [d for _, d in pairs]

    # --- Utilization comparison ----------------------------------------------
    rel_errs = []
    for k, t_busy_real in truth["busy"].items():
        t_wall = t_busy_real / args.compression
        d_wall = dt_busy.get(k, 0.0)
        if t_wall > 0:
            rel_errs.append(abs(d_wall - t_wall) / t_wall * 100.0)
    true_bn = max(truth["busy"], key=truth["busy"].get)
    dt_bn = max(dt_busy, key=dt_busy.get) if dt_busy else -1

    # Per-car and per-station dumps for plots / later analysis.
    import csv as _csv

    with open(os.path.join(RESULTS_DIR, f"{run_tag}_leads.csv"), "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["car", "true_lead_real_s", "dt_lead_wall_s", "err_ms"])
        for c in sorted(truth["lead"], key=lambda x: int(x.removeprefix("SUV"))):
            if c in dt["lead"]:
                t_real = truth["lead"][c]
                d_wall = dt["lead"][c]
                w.writerow(
                    [
                        c,
                        round(t_real, 3),
                        round(d_wall, 6),
                        round((d_wall - t_real / args.compression) * 1000.0, 3),
                    ]
                )
    with open(os.path.join(RESULTS_DIR, f"{run_tag}_utilization.csv"), "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["ws", "true_busy_real_s", "dt_busy_wall_s", "relerr_pct"])
        for k in sorted(truth["busy"]):
            t_wall = truth["busy"][k] / args.compression
            d_wall = dt_busy.get(k, 0.0)
            rel = abs(d_wall - t_wall) / t_wall * 100.0 if t_wall else float("nan")
            w.writerow([k, round(truth["busy"][k], 2), round(d_wall, 4), round(rel, 3)])

    make_plots(run_tag, truth, dt, dt_busy, args.compression)

    samples = sampler.samples[1:] if len(sampler.samples) > 1 else sampler.samples
    cpu_vals = [s["cpu_percent_norm"] for s in samples]
    rss_vals = [s["rss_mb"] for s in samples]
    thr_vals = [s["num_threads"] for s in samples]

    events_published = int(gen_stats.get("events_published", 0) or 0)
    summary: dict[str, Any] = {
        "N": args.N,
        "scenario": scenario,
        "seed": args.seed,
        "tag": args.tag,
        "timestamp": started_at,
        "cars": args.cars,
        "takt_s": args.takt,
        "tri_min": args.tri[0],
        "tri_mode": args.tri[1],
        "tri_max": args.tri[2],
        "bottleneck_station": args.bottleneck_station,
        "bottleneck_factor": args.bottleneck_factor if args.bottleneck_station else "",
        "compression": args.compression,
        "sim_makespan_s": gen_stats.get("sim_makespan_s", ""),
        "runner_runtime_s": gen_stats.get("runner_runtime_s", ""),
        "duration_s": round(duration_actual, 2),
        "events_published": events_published,
        "publishes_late": gen_stats.get("publishes_late", ""),
        "max_slip_s": gen_stats.get("max_slip_s", ""),
        "rows": dt["rows"],
        "rows_car": dt["rows_car"],
        "rows_ws_scan": dt["rows_ws_scan"],
        "car_events_missing": max(0, events_published - dt["rows_car"]),
        "ws_events_missing": max(0, events_published - dt["rows_ws_scan"]),
        "misrouted_scans": dt["misrouted_scans"],
        "cars_mistracked": dt["cars_mistracked"],
        "invalid_transition_warnings": warn_counter.count,
        "cars_exited_true": truth["exits"],
        "cars_exited_dt": dt["exits"],
        "true_lead_real_s_median": (
            round(statistics.median(truth["lead"].values()), 2) if truth["lead"] else ""
        ),
        "true_lead_real_s_p95": (
            round(quantile(sorted(truth["lead"].values()), 0.95), 2) if truth["lead"] else ""
        ),
        "dt_lead_real_s_median": (
            round(statistics.median(dt["lead"].values()) * args.compression, 2)
            if dt["lead"]
            else ""
        ),
        "dt_lead_real_s_p95": (
            round(quantile(sorted(dt["lead"].values()), 0.95) * args.compression, 2)
            if dt["lead"]
            else ""
        ),
        "lead_pairs_n": len(pairs),
        "lead_err_ms_median": round(statistics.median(errs_ms), 3) if errs_ms else "",
        "lead_err_ms_p95": round(quantile(errs_ms, 0.95), 3) if errs_ms else "",
        "lead_ks": ks_distance(true_leads_wall, dt_leads_wall),
        "true_exit_cv": truth["exit_cv"],
        "dt_exit_cv": dt["exit_cv"],
        "exit_cv_abs_err": (
            round(abs(truth["exit_cv"] - dt["exit_cv"]), 4)
            if truth["exit_cv"] == truth["exit_cv"] and dt["exit_cv"] == dt["exit_cv"]
            else ""
        ),
        "true_bottleneck_ws": true_bn,
        "dt_bottleneck_ws": dt_bn,
        "bottleneck_identified": int(true_bn == dt_bn),
        "util_relerr_mean_pct": round(statistics.fmean(rel_errs), 3) if rel_errs else "",
        "util_relerr_max_pct": round(max(rel_errs), 3) if rel_errs else "",
        "car_e2e_ms_median": quantile(dt["e2e_car"], 0.5),
        "car_e2e_ms_p95": quantile(dt["e2e_car"], 0.95),
        "ws_e2e_ms_median": quantile(dt["e2e_ws"], 0.5),
        "cpu_percent_norm_mean": round(statistics.fmean(cpu_vals), 1) if cpu_vals else 0.0,
        "rss_mb_max": round(max(rss_vals), 1) if rss_vals else 0.0,
        "num_threads_max": max(thr_vals) if thr_vals else 0,
        "latency_csv": os.path.basename(latency_path),
    }

    trans_logger.removeHandler(warn_counter)
    trans_logger.propagate = True

    write_header = not os.path.exists(SUMMARY_CSV)
    with open(SUMMARY_CSV, "a", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, restval="", extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow(summary)

    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--N", type=int, default=15, help="Number of workstations.")
    p.add_argument("--ws-per-cell", type=int, default=5)
    p.add_argument("--cars", type=int, default=120)
    p.add_argument("--takt", type=float, default=75.0)
    p.add_argument(
        "--tri", type=float, nargs=3, default=[50.0, 60.0, 70.0], metavar=("MIN", "MODE", "MAX")
    )
    p.add_argument("--grab", type=float, nargs=2, default=[1.0, 3.0], metavar=("MIN", "MAX"))
    p.add_argument("--bottleneck-station", type=int, default=0)
    p.add_argument("--bottleneck-factor", type=float, default=1.2)
    p.add_argument("--compression", type=float, default=100.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--tag", default="")
    p.add_argument("--max-drain", type=float, default=60.0)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8883)
    args = p.parse_args()

    summary = run(args)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
