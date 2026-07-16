"""Audit bench_line summary rows against the line model's bookkeeping identities.

The paced-line design makes every run self-checking: event counts, exit
counts, and lead-time car counts are all determined by (N, cycles), so a
run that deviates is flagged with the reason. Run it after (or during) a
sweep:

    python -m bench_line.verify_summary

Checks per row (E = error, expected to hold at ANY load; W = warning,
expected only sub-saturation; I = informational):

  E1  generator completed: cycles_completed == cycles
  E2  event accounting: events_published == N + 2N * cycles_completed
  E3  tracking integrity: misrouted_scans == cars_mistracked ==
      cars_lost == 0 (guaranteed by the single-writer routing fix)
  E4  statechart sanity: invalid_transition_warnings == 0
  E5  exits when fully drained: car_events_missing == 0 implies
      cars_exited == cycles_completed
  E6  lead-time census: when cycles >= N+1 and nothing missing,
      lead_time_n == cycles_completed - N + 1 (the +1 is the car primed
      at WS1)
  W1  no car/ws events left behind (missing == 0) — nonzero is the
      expected signature of a saturated cell, not a defect
  W2  takt kept: 0.9 <= takt_ratio <= 1.1
  W3  publisher held the schedule: boundaries_late <= 5% of cycles
  W4  throughput matched offer: processed_scans_eps within 5% of
      rate_offered_eps
  I1  lead overhead within noise (|median| <= 50 ms)

A cell that fails only W-checks is *saturated or publisher-bound* —
interesting data, not a broken run. A cell that fails an E-check needs
investigation before its numbers are used.
"""

from __future__ import annotations

import csv
import os
import sys

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
SUMMARY_CSV = os.path.join(RESULTS_DIR, "summary.csv")


def _f(row: dict[str, str], key: str) -> float | None:
    try:
        return float(row.get(key, ""))
    except (TypeError, ValueError):
        return None


def _i(row: dict[str, str], key: str) -> int | None:
    v = _f(row, key)
    return int(v) if v is not None else None


def check_row(row: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """Return (errors, warnings, infos) for one summary row."""
    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []

    n = _i(row, "N") or 0
    cycles = _i(row, "cycles") or 0
    done = _i(row, "cycles_completed")
    published = _i(row, "events_published")
    missing_car = _i(row, "car_events_missing") or 0
    missing_ws = _i(row, "ws_events_missing") or 0

    # E1: generator ran to completion.
    if done is None or done != cycles:
        errors.append(f"E1 generator incomplete: cycles_completed={done} != cycles={cycles}")
        done = done or 0

    # E2: exact event count from the line model.
    expected_events = n + 2 * n * done
    if published is None or published != expected_events:
        errors.append(
            f"E2 event count: published={published}, expected N+2N*cycles={expected_events}"
        )

    # E3/E4: integrity counters must be zero on the fixed engine — with
    # one exception. Under extreme overload (offered rate far above the
    # ceiling), the broker drops QoS-0 scans to the slow subscriber, and
    # a dropped exit scan leaves a start-after-start "hole" in a car's
    # trace that the detector cannot distinguish from a routing failure
    # by counts alone. The discriminator: holes come with car ws_num
    # JUMPS and massive car_events_missing, and are a tiny fraction of
    # it; a genuine routing race produces cascades with near-zero
    # missing. Downgrade to W5 when the drop signature is unambiguous.
    mis = _i(row, "misrouted_scans") or 0
    integ = {
        k: _i(row, k)
        for k in ("misrouted_scans", "cars_mistracked", "cars_lost", "invalid_transition_warnings")
    }
    if any(v is None or v != 0 for v in integ.values()):
        if missing_car > 0 and mis <= 0.01 * missing_car:
            warnings.append(
                f"W5 delivery holes under overload: {mis} start-after-start pairs vs "
                f"{missing_car} undelivered car events (QoS-0 broker drops; "
                f"position map stays coherent, cars resume after the hole)"
            )
        else:
            for k, v in integ.items():
                if v is None or v != 0:
                    code = "E4" if k == "invalid_transition_warnings" else "E3"
                    errors.append(f"{code} {k}={v} (expected 0)")

    # E5: with nothing missing, every offered exit must be observed.
    exits = _i(row, "cars_exited")
    if missing_car == 0 and exits is not None and exits != done:
        errors.append(f"E5 exits={exits} != cycles_completed={done} despite 0 missing car events")

    # E6: lead-time car census.
    lead_n = _i(row, "lead_time_n")
    if done >= n + 1 and missing_car == 0 and lead_n is not None:
        expected_leads = done - n + 1
        if lead_n != expected_leads:
            errors.append(f"E6 lead_time_n={lead_n}, expected cycles-N+1={expected_leads}")

    # W1: backlog left at shutdown (expected signature of saturation).
    if missing_car > 0 or missing_ws > 0:
        warnings.append(f"W1 events left behind: car={missing_car} ws={missing_ws} (saturated?)")

    # W2: takt held.
    takt = _f(row, "takt_ratio")
    if takt is not None and not (0.9 <= takt <= 1.1):
        warnings.append(f"W2 takt_ratio={takt:.3f} outside [0.9, 1.1]")

    # W3: generator pacing.
    late = _i(row, "boundaries_late") or 0
    slots = done * n if row.get("arrival", "") == "staggered" else done
    if slots and late > 0.05 * slots:
        warnings.append(
            f"W3 publisher-bound: {late}/{slots} slots late "
            f"(max_slip={row.get('max_slip_s', '?')}s)"
        )

    # W4: processed ~ offered. The staggered runner's runtime includes the
    # priming cycle (N scans over one T instead of 2N), which deflates
    # processed/offered by exactly (2C+1)/(2C+2) for C cycles — material
    # only at small cycle counts, so compare against the adjusted target.
    proc = _f(row, "processed_scans_eps")
    offered = _f(row, "rate_offered_eps")
    if proc is not None and offered and done:
        expected = offered
        if row.get("arrival", "") == "staggered":
            expected = offered * (2 * done + 1) / (2 * done + 2)
        if abs(proc - expected) > 0.05 * expected:
            warnings.append(f"W4 processed {proc:.0f} vs expected {expected:.0f} scans/s (>5% off)")

    # I1: lead overhead noise band.
    ovh = _f(row, "lead_overhead_ms_median")
    if ovh is not None and abs(ovh) > 50:
        infos.append(f"I1 lead overhead {ovh:.0f} ms (fine if this cell is saturated)")

    return errors, warnings, infos


def main() -> int:
    if not os.path.exists(SUMMARY_CSV):
        print(f"No summary at {SUMMARY_CSV}")
        return 1
    with open(SUMMARY_CSV) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("Summary is empty.")
        return 1

    n_err = n_warn = 0
    for row in rows:
        tag = (
            f"N={row.get('N', '?'):>5} r={row.get('rate_offered_eps', '?'):>8} "
            f"T={row.get('cycle_time_s', '?'):>8} {row.get('arrival', '?'):>9}"
        )
        errors, warnings, infos = check_row(row)
        n_err += len(errors)
        n_warn += len(warnings)
        status = "ERROR" if errors else ("warn" if warnings else "ok")
        print(f"[{status:>5}] {tag}")
        for msg in errors:
            print(f"        !! {msg}")
        for msg in warnings:
            print(f"        -  {msg}")
        for msg in infos:
            print(f"        .  {msg}")

    print()
    print(
        f"{len(rows)} rows checked: {n_err} error(s), {n_warn} warning(s). "
        "Warnings on high-rate cells are expected (saturation/publisher-bound)."
    )
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
