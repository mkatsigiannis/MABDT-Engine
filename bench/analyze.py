"""Aggregate the benchmark results into a paper-ready table and plots.

Reads bench/results/summary.csv (one row per N x rate run) and the
per-run latency CSVs (filenames stored in the `latency_csv` column),
prints a formatted table to stdout, and writes:

  - bench/results/scaling_latency.png  — latency vs N, one line per rate
  - bench/results/saturation.png       — actual throughput vs target,
                                         showing where the engine ceases
                                         to keep up

For a single-rate sweep (just rate=30) only the first plot is meaningful;
the saturation plot becomes interesting once the summary contains rows
at multiple target rates.
"""

from __future__ import annotations

import csv
import os
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
SUMMARY_CSV = os.path.join(RESULTS_DIR, "summary.csv")


# Engine-side throughput: events the engine actually processed per second
# of runner time. This is the right metric for the saturation curve: at
# offered loads above the engine's ceiling, `events_published` continues
# to grow (the generator keeps publishing into a buffer the broker drops
# from) but `rows` flattens at whatever the engine can handle.
def _row_throughput(row: dict[str, str]) -> float:
    try:
        rows = float(row.get("rows", 0) or 0)
        runtime = float(row.get("runner_runtime_s", 0) or 0)
        if runtime > 0:
            return rows / runtime
    except ValueError:
        pass
    # Backwards-compat fallback for older sweeps that lack `rows` or
    # `runner_runtime_s`: fall back to the publisher-side metric.
    for key in ("throughput_eps", "throughput_actual_eps"):
        if key in row and row[key]:
            try:
                return float(row[key])
            except ValueError:
                pass
    return 0.0


def per_agent_breakdown(latency_csv: str) -> dict[str, dict[str, float]]:
    """Return {category: {metric_stat: ms}} where category is 'car' or 'ws'."""
    cats: dict[str, dict[str, list[float]]] = {
        "car": {"inbox_wait_s": [], "handle_s": [], "e2e_s": []},
        "ws": {"inbox_wait_s": [], "handle_s": [], "e2e_s": []},
    }
    if not os.path.exists(latency_csv):
        return {}
    with open(latency_csv) as f:
        r = csv.DictReader(f)
        for row in r:
            cat = "car" if row["agent"].startswith("Car") else "ws"
            for k in cats[cat]:
                v = row.get(k, "")
                if v:
                    try:
                        cats[cat][k].append(float(v) * 1000.0)
                    except ValueError:
                        pass

    def stats(vals: list[float]) -> dict[str, float]:
        if not vals:
            return {"n": 0, "median": float("nan"), "p95": float("nan"), "p99": float("nan")}
        s = sorted(vals)
        return {
            "n": len(s),
            "median": statistics.median(s),
            "p95": s[int(0.95 * (len(s) - 1))],
            "p99": s[int(0.99 * (len(s) - 1))],
        }

    out: dict[str, dict[str, float]] = {}
    for cat in cats:
        out[cat] = {}
        for k, vals in cats[cat].items():
            st = stats(vals)
            for m, v in st.items():
                out[cat][f"{k}_{m}"] = v
    return out


def load_summary() -> list[dict[str, str]]:
    with open(SUMMARY_CSV) as f:
        return list(csv.DictReader(f))


def print_table(rows: list[dict[str, str]]) -> None:
    cols = [
        ("N", "N"),
        ("rate_target_eps", "rate_eps"),
        ("throughput_eps", "actual_eps"),
        ("events_dropped", "dropped"),
        ("runner_runtime_s", "runtime_s"),
        ("cpu_percent_norm_mean", "cpu_mean_%"),
        ("rss_mb_max", "rss_MB"),
        ("num_threads_max", "threads"),
        ("e2e_ms_median", "e2e_med_ms"),
        ("e2e_ms_p95", "e2e_p95_ms"),
        ("e2e_ms_p99", "e2e_p99_ms"),
        ("inbox_wait_ms_p95", "inbox_p95_ms"),
    ]
    widths = [max(len(label), 10) for _, label in cols]
    print(" | ".join(label.rjust(w) for (_, label), w in zip(cols, widths, strict=False)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        vals = []
        for (k, _), w in zip(cols, widths, strict=False):
            # Backwards compat: older sweeps wrote throughput_actual_eps.
            v = row.get(k, "")
            if not v and k == "throughput_eps":
                v = row.get("throughput_actual_eps", "")
            try:
                v = f"{float(v):.2f}"
            except (TypeError, ValueError):
                pass
            vals.append(str(v).rjust(w))
        print(" | ".join(vals))


def _group_by_rate(rows: list[dict[str, str]]) -> dict[float, list[dict[str, str]]]:
    """Return {rate: [rows]} sorted by N within each rate group."""
    groups: dict[float, list[dict[str, str]]] = {}
    for row in rows:
        try:
            r = float(row.get("rate_target_eps", 0))
        except ValueError:
            continue
        groups.setdefault(r, []).append(row)
    for r in groups:
        groups[r].sort(key=lambda x: int(x["N"]))
    return groups


def make_latency_plot(rows: list[dict[str, str]]) -> None:
    """Latency vs N, one line per target rate.

    For each rate in the summary, plots median + p95 e2e latency. Single-rate
    sweeps render as a clean two-line plot; multi-rate sweeps show how
    latency degrades as load rises.
    """
    groups = _group_by_rate(rows)
    if not groups:
        return

    fig, (ax_med, ax_p95) = plt.subplots(1, 2, figsize=(12, 5))
    rates = sorted(groups.keys())

    for rate in rates:
        rate_rows = groups[rate]
        Ns = [int(r["N"]) for r in rate_rows]
        try:
            med = [float(r["e2e_ms_median"]) for r in rate_rows]
            p95 = [float(r["e2e_ms_p95"]) for r in rate_rows]
        except (KeyError, ValueError):
            continue
        label = f"{int(rate)} eps"
        ax_med.plot(Ns, med, "o-", label=label)
        ax_p95.plot(Ns, p95, "s-", label=label)

    for ax, title in ((ax_med, "Median e2e latency"), (ax_p95, "p95 e2e latency")):
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Workstation agents (N)")
        ax.set_ylabel("Latency (ms)")
        ax.set_title(title)
        ax.grid(True, which="both", linestyle=":", alpha=0.5)
        ax.legend(title="Target rate")

    out_path = os.path.join(RESULTS_DIR, "scaling_latency.png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {out_path}")


def make_saturation_plot(rows: list[dict[str, str]]) -> None:
    """Actual throughput vs target rate, one line per N.

    A line that hugs the diagonal means the engine is keeping up at every
    rate. A line that flattens out below the diagonal shows the saturation
    ceiling for that N.
    """
    groups: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        try:
            N = int(row["N"])
        except (KeyError, ValueError):
            continue
        groups.setdefault(N, []).append(row)

    # Only draw if at least one N has more than one rate measured.
    if not any(len(v) >= 2 for v in groups.values()):
        return

    fig, ax = plt.subplots(figsize=(7, 5))
    Ns = sorted(groups.keys())
    for N in Ns:
        rate_rows = sorted(groups[N], key=lambda r: float(r["rate_target_eps"]))
        targets = [float(r["rate_target_eps"]) for r in rate_rows]
        actuals = [_row_throughput(r) for r in rate_rows]
        ax.plot(targets, actuals, "o-", label=f"N={N}")

    # Diagonal: ideal "actual == target" reference line.
    all_targets = sorted({float(r["rate_target_eps"]) for r in rows})
    if all_targets:
        ax.plot(all_targets, all_targets, "k--", alpha=0.3, label="ideal (actual = target)")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Target rate (events/sec)")
    ax.set_ylabel("Engine throughput, events processed/sec (rows / runner_runtime)")
    ax.set_title("Engine throughput vs. offered load")
    ax.grid(True, which="both", linestyle=":", alpha=0.5)
    ax.legend()

    out_path = os.path.join(RESULTS_DIR, "saturation.png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {out_path}")


def main() -> None:
    rows = load_summary()
    rows.sort(key=lambda r: (int(r["N"]), float(r.get("rate_target_eps", 0))))

    print("=== SUMMARY ===")
    print_table(rows)
    print()

    make_latency_plot(rows)
    make_saturation_plot(rows)


if __name__ == "__main__":
    main()
