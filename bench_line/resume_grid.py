"""Resume an interrupted repetition sweep: run only the missing cells.

Reads results/summary.csv, computes which (rep, N, rate, arrival) cells
of the full grid are absent, and runs exactly those in canonical order,
then verifies and aggregates. Safe to re-run any number of times — it
always picks up wherever the summary left off. Unlike run_full_grid.bat,
it never deletes the summary.

    python -m bench_line.resume_grid --reps 5
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BENCH_DIR)
SUMMARY_CSV = os.path.join(BENCH_DIR, "results", "summary.csv")

NS = [15, 50, 150, 500, 1000]
RATES = [30, 100, 300, 1000, 3000, 10000]
BURST_RATE = 1000


def expected_cells(reps: int) -> list[tuple[str, int, int, str]]:
    cells = []
    for k in range(1, reps + 1):
        tag = f"rep{k}"
        for n in NS:
            for r in RATES:
                cells.append((tag, n, r, "staggered"))
        for n in NS:
            cells.append((tag, n, BURST_RATE, "burst"))
    return cells


def present_cells() -> set[tuple[str, int, int, str]]:
    if not os.path.exists(SUMMARY_CSV):
        return set()
    seen = set()
    with open(SUMMARY_CSV) as f:
        for row in csv.DictReader(f):
            try:
                seen.add(
                    (
                        row.get("tag", ""),
                        int(row["N"]),
                        int(float(row["rate_offered_eps"])),
                        row.get("arrival", ""),
                    )
                )
            except (KeyError, ValueError):
                continue
    return seen


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8883)
    args = p.parse_args()

    check = subprocess.run(
        [
            sys.executable,
            os.path.join(BENCH_DIR, "check_broker.py"),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=PROJECT_ROOT,
    )
    if check.returncode != 0:
        print("Broker not reachable; aborting.")
        return 1

    todo = [c for c in expected_cells(args.reps) if c not in present_cells()]
    total = len(expected_cells(args.reps))
    print(f"[resume] {total - len(todo)}/{total} cells already in summary; {len(todo)} to run.")

    for i, (tag, n, rate, arrival) in enumerate(todo, 1):
        print(f"[resume] ({i}/{len(todo)}) N={n} rate={rate} {arrival} {tag}", flush=True)
        rc = subprocess.run(
            [
                sys.executable,
                "-m",
                "bench_line.benchmark",
                "--N",
                str(n),
                "--rate",
                str(rate),
                "--duration",
                "60",
                "--arrival",
                arrival,
                "--tag",
                tag,
                "--host",
                args.host,
                "--port",
                str(args.port),
            ],
            cwd=PROJECT_ROOT,
        ).returncode
        if rc != 0:
            print(f"[resume] FAILED at N={n} rate={rate} {arrival} {tag} (exit {rc}); stopping.")
            return 1

    print("[resume] all cells present; verifying and aggregating.")
    subprocess.run([sys.executable, "-m", "bench_line.verify_summary"], cwd=PROJECT_ROOT)
    subprocess.run([sys.executable, "-m", "bench_line.analyze"], cwd=PROJECT_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
