# bench_fidelity — Stochastic-line fidelity study for the MABDT engine

Third evaluation leg, next to [`bench/`](../bench/) (frozen as-submitted
scaling study) and [`bench_line/`](../bench_line/) (unified paced-line
scaling study). It answers a limitation of the paced experiments: they
*split work perfectly evenly*, while a real line has cycle-time
variability — and with variability come queues, starvation, lead-time
distributions, and exit jitter, none of which a deterministic paced
line can exhibit.

More importantly, it turns the evaluation into a **quantitative fidelity
measurement**. The generator is a seeded, event-driven simulation of the
line, so it knows the ground truth for everything the digital twin is
supposed to mirror. The benchmark grades the DT against that truth.

## The line model

- Cars are released to WS1's queue at a fixed **takt (75 s)**, starting
  from an empty line (the fill transient is part of a realistic shift).
- Each station serves FIFO, one car at a time: **Uniform(1, 3) s grab
  delay**, enter scan, **Triangular(50, 60, 70) s service**, exit scan,
  instant hand-off to the next queue. These are the same parameters the
  deployment's verification generator
  (`tiger_motors_dt/tools/data_generator.py`) has always used, keeping
  continuity with the dissertation's verification chapter.
- **Bottleneck scenario**: one station (default WS8) has all three
  Triangular parameters scaled by 1.2 → utilization ≈ 0.96, producing
  the classic constraint signature (queue upstream, starvation
  downstream).
- The whole timeline is **precomputed** from the tandem-queue recursion
  with a seeded RNG, dumped as ground truth, then replayed over MQTT at
  a **time compression** factor (default 100×: 60 s of line time per
  0.6 s of wall time). No faults/rework in v1 — ground-truth lead times
  stay unambiguous.

Compression bound: keep compressed cycle times comfortably above OS
scheduling-stall scale (≳0.3 s wall), the lesson from bench_line — at
100× the compressed service time is 0.5–0.7 s.

## What gets graded

| Fidelity metric | Ground truth | DT observation |
|---|---|---|
| Lead time (paired per car) | enter@WS1 → exit@WS{N} in the schedule | first `start@1` received → final `done@N` handled |
| Lead-time distribution | schedule ECDF | DT ECDF (plus two-sample KS distance) |
| Exit inter-departure CV | schedule exit times at WS{N} | DT-observed exit events |
| Per-station busy time | Σ service per station | `WorkstationAgent` StateTimer Busy clock |
| Bottleneck localization | argmax true busy | argmax DT busy (only meaningful in bottleneck runs) |

Everything the DT is graded on is *emergent* — queueing, starvation,
the fill transient — nothing is scripted into the scan stream.

Also carried over from bench_line: per-event latency, tracking-integrity
counters (`misrouted_scans` etc., expected 0), event-count identities
(published = 2·N·cars; exits = cars), resource sampling.

## Requirements & reuse

Same as bench_line (broker on 127.0.0.1:8883, psutil, matplotlib).
Instrumentation and the engine-boot helpers are **imported from
bench_line** (`instrument`, `instrumentation`, `ResourceSampler`,
`build_config`) — one source of truth for the four runtime patches;
neither engine package is modified.

## Run

```
python -m bench_fidelity.benchmark --cars 120 --compression 100 --seed 1
python -m bench_fidelity.benchmark --bottleneck-station 8 --seed 1
bench_fidelity\run_fidelity.bat      # balanced x3 seeds + bottleneck x3 seeds (~20 min)
python -m bench_fidelity.analyze     # comparison table
```

Each run writes the ground truth (`*_truth.csv`), the DT event log
(`*_latency.csv`), paired per-car leads (`*_leads.csv`), per-station
busy times (`*_utilization.csv`), and two figures: a truth-vs-DT
lead-time ECDF overlay and a per-station busy-time bar chart (both in
real-line units). Resource stats (CPU/RSS/threads) land in the summary
row.

## Reading the summary

- `lead_err_ms_median/p95` — paired (DT − truth) lead error in wall
  ms; multiply by compression for real-line equivalents. Sub-saturation
  this should be on the order of one event's end-to-end latency.
- `lead_ks` — two-sample KS distance between the lead distributions
  (0 = identical).
- `true_exit_cv` vs `dt_exit_cv` — does the DT reproduce the line's
  departure irregularity (not just its mean rate)?
- `util_relerr_mean/max_pct` — per-station busy-time agreement.
- `bottleneck_identified` — 1 if the DT's busiest station is the true
  constraint (bottleneck rows only; on a balanced line the argmax is
  sampling noise).
- Integrity columns must be 0 / complete as in bench_line.
