"""Print the fidelity comparison table from bench_fidelity/results/summary.csv.

One row per run: ground truth vs digital-twin observation, paired lead
errors, exit-CV agreement, utilization error, bottleneck localization.
The per-run ECDF and utilization figures are produced by the runner
itself (results/{tag}_lead_ecdf.png, {tag}_utilization.png).
"""

from __future__ import annotations

import csv
import os

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
SUMMARY_CSV = os.path.join(RESULTS_DIR, "summary.csv")


def main() -> None:
    with open(SUMMARY_CSV) as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: (r["scenario"], int(r["seed"])))

    cols = [
        ("scenario", "scenario"),
        ("seed", "seed"),
        ("cars", "cars"),
        ("compression", "compr"),
        ("cars_exited_true", "exits_true"),
        ("cars_exited_dt", "exits_dt"),
        ("true_lead_real_s_median", "lead_true_s"),
        ("dt_lead_real_s_median", "lead_dt_s"),
        ("lead_err_ms_median", "err_med_ms"),
        ("lead_err_ms_p95", "err_p95_ms"),
        ("lead_ks", "KS"),
        ("true_exit_cv", "cv_true"),
        ("dt_exit_cv", "cv_dt"),
        ("util_relerr_mean_pct", "util_err%"),
        ("true_bottleneck_ws", "bn_true"),
        ("dt_bottleneck_ws", "bn_dt"),
        ("bottleneck_identified", "bn_ok"),
        ("misrouted_scans", "misroutes"),
        ("car_events_missing", "missing"),
    ]
    widths = [max(len(label), 10) for _, label in cols]
    print("=== FIDELITY SUMMARY (truth vs digital twin) ===")
    print(" | ".join(label.rjust(w) for (_, label), w in zip(cols, widths, strict=False)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        vals = []
        for (k, _), w in zip(cols, widths, strict=False):
            v = row.get(k, "")
            if k not in ("scenario",):
                try:
                    v = f"{float(v):.3f}"
                except (TypeError, ValueError):
                    pass
            vals.append(str(v).rjust(w))
        print(" | ".join(vals))
    print()
    print("Notes: bn_true/bn_dt/bn_ok are meaningful only for bottleneck rows")
    print("(on a balanced line the busiest station is sampling noise).")
    print("err_* are paired per-car (DT lead - true lead) in wall-clock ms;")
    print("multiply by the compression factor for real-line equivalents.")


if __name__ == "__main__":
    main()
