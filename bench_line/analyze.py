"""Aggregate unified line-mode benchmark results into a table and plots.

Reads bench_line/results/summary.csv (one row per (N, T, arrival) run),
prints a formatted table, and writes:

  - results/line_latency.png     — car & workstation e2e latency vs N,
                                   one line per (cycle time, arrival)
  - results/line_saturation.png  — processed scans/s vs offered rate,
                                   one line per (N, arrival). The
                                   old-bench saturation plot, regenerated
                                   from the unified experiment.
  - results/line_takt.png        — achieved takt ratio vs offered rate,
                                   one line per (N, arrival)
  - results/line_lead.png        — lead-time overhead over the paced
                                   ideal vs N

Plots are only written when the summary holds enough distinct points to
draw them.
"""

from __future__ import annotations

import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
SUMMARY_CSV = os.path.join(RESULTS_DIR, "summary.csv")


def load_summary() -> list[dict[str, str]]:
    with open(SUMMARY_CSV) as f:
        return list(csv.DictReader(f))


def _fl(row: dict[str, str], key: str) -> float | None:
    v = row.get(key, "")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _arrival(row: dict[str, str]) -> str:
    return row.get("arrival", "") or "burst"  # rows from before the column existed


def print_table(rows: list[dict[str, str]]) -> None:
    cols = [
        ("N", "N"),
        ("arrival", "arrival"),
        ("cycle_time_s", "T_s"),
        ("rate_offered_eps", "rate_eps"),
        ("processed_scans_eps", "proc_eps"),
        ("cars_exited", "exits"),
        ("takt_ratio", "takt_ratio"),
        ("lead_time_n", "lead_n"),
        ("lead_time_s_median", "lead_med_s"),
        ("lead_time_s_ideal", "lead_ideal_s"),
        ("lead_overhead_ms_median", "lead_ovh_ms"),
        ("car_e2e_ms_median", "car_e2e_ms"),
        ("ws_e2e_ms_median", "ws_e2e_ms"),
        ("car_handling_ms_median", "handling_ms"),
        ("car_events_missing", "missing"),
        ("cpu_percent_norm_mean", "cpu_%"),
        ("rss_mb_max", "rss_MB"),
        ("num_threads_max", "threads"),
    ]
    widths = [max(len(label), 10) for _, label in cols]
    print(" | ".join(label.rjust(w) for (_, label), w in zip(cols, widths, strict=False)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        vals = []
        for (k, _), w in zip(cols, widths, strict=False):
            v = row.get(k, "")
            if k not in ("arrival",):
                try:
                    v = f"{float(v):.3f}"
                except (TypeError, ValueError):
                    pass
            vals.append(str(v).rjust(w))
        print(" | ".join(vals))


def make_latency_plot(rows: list[dict[str, str]]) -> None:
    """Car and WS median e2e latency vs N, one line per (cycle time, arrival)."""
    groups: dict[tuple[float, str], list[dict[str, str]]] = {}
    for row in rows:
        t = _fl(row, "cycle_time_s")
        if t is not None:
            groups.setdefault((t, _arrival(row)), []).append(row)
    groups = {k: v for k, v in groups.items() if len(v) >= 2}
    if not groups:
        return
    for key in groups:
        groups[key].sort(key=lambda r: int(r["N"]))

    fig, (ax_car, ax_ws) = plt.subplots(1, 2, figsize=(12, 5))
    for t, arr in sorted(groups):
        g = groups[(t, arr)]
        ns = [int(r["N"]) for r in g]
        label = f"T={t:g}s {arr}"
        ax_car.plot(ns, [_fl(r, "car_e2e_ms_median") for r in g], "o-", label=label)
        ax_ws.plot(ns, [_fl(r, "ws_e2e_ms_median") for r in g], "s-", label=label)
    for ax, title in ((ax_car, "Car agents"), (ax_ws, "Workstation agents")):
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Workstation agents (N)")
        ax.set_ylabel("Median e2e latency (ms)")
        ax.set_title(title)
        ax.grid(True, which="both", linestyle=":", alpha=0.5)
        ax.legend(title="Cycle time / arrival", fontsize=8)
    out_path = os.path.join(RESULTS_DIR, "line_latency.png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {out_path}")


def make_saturation_plot(rows: list[dict[str, str]]) -> None:
    """Processed scans/s vs offered rate, one line per (N, arrival).

    The unified replacement for bench/'s saturation plot: a line hugging
    the diagonal keeps up with the offered load; flattening below it
    marks the ceiling for that N.
    """

    # Prefer sustained_scans_eps (car rows / observed wall span): in
    # saturated cells events keep draining after the publish window, so
    # processed_scans_eps (rows / publish runtime) overstates throughput.
    def _tp(row: dict[str, str]) -> float | None:
        return _fl(row, "sustained_scans_eps") or _fl(row, "processed_scans_eps")

    groups: dict[tuple[int, str], list[dict[str, str]]] = {}
    for row in rows:
        if _tp(row) is None:
            continue
        try:
            groups.setdefault((int(row["N"]), _arrival(row)), []).append(row)
        except (KeyError, ValueError):
            continue
    groups = {k: v for k, v in groups.items() if len(v) >= 2}
    if not groups:
        return

    fig, ax = plt.subplots(figsize=(7, 5))
    for n, arr in sorted(groups):
        g = sorted(groups[(n, arr)], key=lambda r: _fl(r, "rate_offered_eps") or 0)
        ax.plot(
            [_fl(r, "rate_offered_eps") for r in g],
            [_tp(r) for r in g],
            "o-" if arr == "staggered" else "s--",
            label=f"N={n} {arr}",
        )
    all_rates = sorted({_fl(r, "rate_offered_eps") for r in rows if _fl(r, "rate_offered_eps")})
    if all_rates:
        # Each published scan routes to exactly one car event, so an engine
        # keeping up processes scans at the offered rate: the diagonal.
        ax.plot(all_rates, all_rates, "k--", alpha=0.3, label="ideal (processed = offered)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Offered rate 2N/T (scans/s)")
    ax.set_ylabel("Sustained scans/s (car rows / observed span)")
    ax.set_title("Engine throughput vs offered load")
    ax.grid(True, which="both", linestyle=":", alpha=0.5)
    ax.legend(fontsize=8)
    out_path = os.path.join(RESULTS_DIR, "line_saturation.png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {out_path}")


def make_takt_plot(rows: list[dict[str, str]]) -> None:
    """Achieved takt ratio vs offered rate, one line per (N, arrival).

    A ratio of 1.0 means finished cars leave the digital twin exactly one
    commanded cycle time apart; departures from 1.0 show the DT losing
    the physical pace.
    """
    groups: dict[tuple[int, str], list[dict[str, str]]] = {}
    for row in rows:
        if _fl(row, "takt_ratio") is None:
            continue
        try:
            groups.setdefault((int(row["N"]), _arrival(row)), []).append(row)
        except (KeyError, ValueError):
            continue
    groups = {k: v for k, v in groups.items() if len(v) >= 2}
    if not groups:
        return

    fig, ax = plt.subplots(figsize=(7, 5))
    for n, arr in sorted(groups):
        g = sorted(groups[(n, arr)], key=lambda r: _fl(r, "rate_offered_eps") or 0)
        ax.plot(
            [_fl(r, "rate_offered_eps") for r in g],
            [_fl(r, "takt_ratio") for r in g],
            "o-" if arr == "staggered" else "s--",
            label=f"N={n} {arr}",
        )
    ax.axhline(1.0, color="k", linestyle="--", alpha=0.3, label="ideal (takt kept)")
    ax.set_xscale("log")
    ax.set_xlabel("Offered rate 2N/T (scans/s)")
    ax.set_ylabel("Median inter-departure / commanded cycle time")
    ax.set_title("Takt achievement vs offered load")
    ax.grid(True, which="both", linestyle=":", alpha=0.5)
    ax.legend(fontsize=8)
    out_path = os.path.join(RESULTS_DIR, "line_takt.png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {out_path}")


def make_lead_plot(rows: list[dict[str, str]]) -> None:
    """Lead-time overhead over the paced ideal vs N."""
    groups: dict[tuple[float, str], list[tuple[int, float]]] = {}
    for r in rows:
        ovh = _fl(r, "lead_overhead_ms_median")
        t = _fl(r, "cycle_time_s")
        if ovh is None or t is None:
            continue
        groups.setdefault((t, _arrival(r)), []).append((int(r["N"]), ovh))
    groups = {k: v for k, v in groups.items() if len(v) >= 2}
    if not groups:
        return

    fig, ax = plt.subplots(figsize=(7, 5))
    for t, arr in sorted(groups):
        g = sorted(groups[(t, arr)])
        ax.plot(
            [n for n, _ in g],
            [o for _, o in g],
            "o-" if arr == "staggered" else "s--",
            label=f"T={t:g}s {arr}",
        )
    ax.set_xscale("log")
    ax.set_xlabel("Workstation agents (N)")
    ax.set_ylabel("Median lead time - ideal (ms)")
    ax.set_title("Digital-twin lead-time overhead over the paced ideal")
    ax.grid(True, which="both", linestyle=":", alpha=0.5)
    ax.legend(title="Cycle time / arrival", fontsize=8)
    out_path = os.path.join(RESULTS_DIR, "line_lead.png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {out_path}")


def main() -> None:
    rows = load_summary()
    rows.sort(key=lambda r: (int(r["N"]), _arrival(r), float(r.get("cycle_time_s", 0) or 0)))

    print("=== UNIFIED LINE-MODE SUMMARY ===")
    print_table(rows)
    print()

    make_latency_plot(rows)
    make_saturation_plot(rows)
    make_takt_plot(rows)
    make_lead_plot(rows)


if __name__ == "__main__":
    main()
