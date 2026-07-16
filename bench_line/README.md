# bench_line — Unified paced-assembly-line scaling study for the MABDT engine

Successor to [`bench/`](../bench/) and the **single experiment** that
subsumes the old study: it reproduces the old grid's
latency/throughput/resource characterization (via staggered arrivals
over the same N × rate grid) *and* adds assembly-line metrics (takt
achievement, lead time, constant WIP). `bench/` is kept untouched so the
previously submitted numbers stay reproducible; this folder is
self-contained.
Like `bench/`, it imports from `mabdt` and `tiger_motors_dt` but
modifies neither — instrumentation is runtime monkey-patching.

## The line model

The generator emulates a full production line instead of round-robin
traffic:

- **Priming.** Every workstation scans a car (Route 2 of
  `BarcodeProcessor` creates each `CarAgent`); the line starts full,
  all stations Busy.
- **Every cycle time `T`** each car advances exactly one station: each
  station publishes an exit scan (Route 3 → `done` to workstation and
  car), cars shift downstream, a new car enters at WS1, each station
  publishes an enter scan (Route 4 `move` / Route 2 `create`). The car
  at WS{N} transitions to `WaitingInspection` and leaves the line — one
  finished car per cycle.

### Two arrival patterns, same line semantics (`--arrival`)

| | `staggered` (default) | `burst` |
|---|---|---|
| Model | Takt-paced flow line with hand-offs: station k acts at phase offset `(k-1)·T/N` inside the cycle, passing its car to station k+1's later slot | Synchronized indexing/transfer line: all stations act at the cycle boundary |
| Message stream | Pairs of scans every `T/N` — statistically the **uniform arrivals of the old bench/**, so per-event latency and saturation curves are directly comparable | 2N-message burst per boundary — the worst-case arrival pattern |
| Ideal lead time | `N·T + (N-1)·T/N` (hand-off phase spread) | `N·T` |
| Priming | Occupies cycle 0 (one slot per station) | One burst before cycle 1 |

Both modes: offered rate `r = 2N/T`, one exit per cycle (ideal
inter-departure = `T`), WIP = N, Little's law by construction.
Ordering guarantees (single MQTT connection): each workstation sees
`done` before the next `busy`; each car sees `done@k` before
`start@k+1`; per-agent dedup keys alternate, so debouncing never drops
a scan.

## How this subsumes the old `bench/` experiment

| Old deliverable | Where it comes from now |
|---|---|
| Sub-saturation e2e latency table | Staggered cells at the same offered rates (uniform arrivals) |
| Throughput vs offered rate (saturation) | `processed_scans_eps` column (car rows / runner runtime — the old `_row_throughput` definition) + `line_saturation.png`; this time r = 10,000 is genuinely offered (separate-process publisher, slip columns prove it) |
| "Handling stays flat under saturation" (paper's resource table) | `car_handling_ms_median` (per-event `mqtt_to_inbox + handle`), previously computed ad hoc |
| RSS / threads / CPU by N | Same sampler, now engine-only (generator excluded from the process) |
| — new | Takt/exit rate, lead time vs ideal, WIP = N, workstation-path latency (`WorkstationAgent._run_loop` patched too), burst-vs-staggered sensitivity |

Bookkeeping identities (sanity checks): events published =
`N + 2N × cycles`; exits = cycles; each scan produces exactly one car
event (`start`/`done`) and one workstation event (`busy`/`done`), so
`rows_car = rows_ws_scan = events_published` when nothing is lost or
left queued at shutdown (`*_events_missing` report the shortfall).
`rows_ws` additionally contains three lifecycle rows per workstation
(`prod_start`, `green` from PLC init, `prod_finish`).

## Choosing the run length

A car entering WS1 on cycle `i` exits on cycle `i + N`, so **full-line
lead times require `cycles ≥ N + 1`** (a run yields `cycles − N` of
them, plus the car primed at WS1). Three ways to set the length:

- `--cycles K` — explicit.
- `--duration S` (grid mode) — `cycles = max(5, S/T)`; lead-time columns
  populate automatically wherever a traversal fits the window (all of
  N=15; high-rate cells at larger N). Takt/exit/latency metrics are
  valid everywhere.
- default — `max(N + 25, 30s/T)`: targets 25 lead-time cars.

`--max-cycles` (default 5000) caps the count because **each cycle
creates one CarAgent whose thread lives until shutdown** — unbounded
cycle counts at small T exhaust OS threads.

**Publisher limit:** slot pacing uses sleep-then-spin for sub-ms
precision (the generator process is isolated, so spinning is free of
engine cost). If the publisher still can't hold the schedule,
`boundaries_late` / `max_slip_s` make it visible — treat cells with
significant slip as publisher-bound, not engine-bound.

## Requirements

Same as `bench/`: a local MQTT broker (default `127.0.0.1:8883`),
`psutil`, `matplotlib`, plus the engine's runtime deps.
`config_benchmark.json` carries the same two bench-only overrides
(scanner/OPC-UA services disabled, event-bus tick at 1 Hz).

## Run a single point

```
python -m bench_line.benchmark --N 15 --cycle-time 0.5
python -m bench_line.benchmark --N 150 --rate 3000 --duration 60     # grid cell
python -m bench_line.benchmark --N 15 --rate 1000 --arrival burst    # worst case
python -m bench_line.benchmark --N 15 --cycle-time 60 --cycles 40    # real takt (~45 min)
```

Each run writes `results/N{N}_T{T}_{arrival}_latency.csv` (one row per
handled event, car AND workstation, with `kind`, `ws_num`, four timing
stamps), `..._engine.log`, and one row appended to `results/summary.csv`.

## Run the full grid

`run_full_grid.bat` — 35 runs per repetition, ~60–90 min each:
old grid `N ∈ {15, 50, 150, 500, 1000} × r ∈ {30 … 10,000}` staggered
with 60 s windows, plus a burst-sensitivity pass at r = 1,000. Clears
`summary.csv`, checks the broker, ends with `python -m
bench_line.verify_summary` (audits every row against the bookkeeping
identities) and `python -m bench_line.analyze` (table + four plots).

Environment toggles (set before launching, e.g. `$env:REPS="5"` in
PowerShell or `set REPS=5` in cmd):

- `REPS=k` — repeat the whole grid k times; rows are tagged
  `rep1..repk` so per-run files don't collide.
- `RUN_SHOWCASE=1` — append the deployment-realistic showcase
  (N=15, T=60 s — the actual lab takt, 40 cycles, ~45 min), or run it
  manually: `python -m bench_line.benchmark --N 15 --cycle-time 60
  --cycles 40 --tag showcase`.
- `NOPAUSE=1` — no pause prompts (unattended/overnight runs).

If a sweep is interrupted, `python -m bench_line.resume_grid --reps k`
runs only the cells missing from `summary.csv` (it never deletes the
summary) and finishes with the same verify + analyze steps.

## Reading the summary columns

| Column | Meaning |
|---|---|
| `arrival` | `staggered` or `burst` (see above). |
| `cycle_time_s`, `rate_offered_eps` | Commanded cycle time `T`; offered rate `2N/T`. |
| `processed_scans_eps` | Car rows / runner runtime — **the old bench/ throughput definition**; place against the old saturation table. |
| `sustained_scans_eps` | Car rows / observed wall span of car rows — cleanest cross-experiment throughput. |
| `cars_exited`, `exit_rate_per_min` | Finished cars observed by the DT (car `done` at WS{N}); ideal = cycles, `60/T`. |
| `interdeparture_s_median`, `_mean`, `_cv` | Time between consecutive line exits. Ideal median = `T`, CV = 0. |
| `takt_ratio` | `interdeparture_s_median / T`. 1.0 = the DT keeps the commanded takt. |
| `lead_time_n` | Cars that traversed the full line (`cycles − N` expected, +1 for the WS1-primed car). |
| `lead_time_s_median`, `_p95`, `_ideal` | Engine-side lead time (first `start@WS1` MQTT receive → `done@WS{N}` handled) vs the mode-specific ideal. |
| `lead_overhead_ms_median` | Median lead − ideal: the DT's lag over a full traversal. Small **negative** values are normal sub-saturation (intra-cycle publish offsets + OS timer jitter); meaningful once it clearly exceeds ~10 ms. |
| `car_e2e_ms_*`, `ws_e2e_ms_*` | End-to-end latency (`handle_end − mqtt_in`) split by agent kind. |
| `car_handling_ms_median`, `ws_handling_ms_median` | Per-event dispatch + statechart cost (`mqtt_to_inbox + handle`), excluding inbox wait — the paper's "handling" metric, per kind. |
| `car_events_missing`, `ws_events_missing` | Scans that never produced a latency row (queued at shutdown or lost upstream). |
| `misrouted_scans`, `cars_mistracked`, `cars_lost` | Tracking-integrity checks: a car `start` row directly following a `start` means the car's exit at some station never registered. **Expected 0 at any load** since the single-writer routing fix (the barcode processor keeps its own car-position map instead of reading the attribute the car thread rewrites; `CarAgent` start dedup keys are station-scoped). Nonzero values indicate a routing regression — with one benign exception under extreme overload, where QoS-0 broker drops punch holes in car traces (`verify_summary` separates the two signatures; see its W5). |
| `invalid_transition_warnings` | `transitions`-library warnings (invalid trigger for the current state). Expected 0; kept as a canary for statechart-level anomalies (same overload exception as above). |
| `boundaries_late`, `max_slip_s`, `mean_burst_s`, `max_burst_s` | Generator pacing health (late slots/boundaries; burst stats are burst-mode only). |
| `throughput_eps` | All rows / runner runtime — engine-side processed events/s (car + WS + lifecycle). |

## How the instrumentation works

`instrument.py` patches four methods (vs. three in `bench/`):

| Method | What the patch adds |
|---|---|
| `mabdt.agent.base.Agent.receive` | Lifts `mqtt_in` off thread-local into the event dict, stamps `inbox_in` |
| `mabdt.agent.base.Agent._run_loop` | `handle_start`/`handle_end` stamps + CSV row (cars, inspection station) |
| `tiger_motors_dt.agents.ws_agent.WorkstationAgent._run_loop` | Same stamps for workstation agents, which override the base loop and were invisible to `bench/`'s patches |
| `mabdt...CommunicationAgent._on_message` | Stamps `mqtt_in` on the MQTT receive thread |

Apply the patches **before** constructing `TigerMotorsEnvironment`
(threads bind their `_run_loop` at agent construction). The runner does
this in the right order.

If `Agent._run_loop` or `WorkstationAgent._run_loop` ever changes in the
engine, copy the new body into the corresponding `_patched_*` function in
`instrument.py` and re-add the stamps.

## Quantifying the harness coupling

The patches execute on the measured threads, which perturbs the engine
under saturation (below the ceiling the effect is unmeasurable — bare
and instrumented runs complete the same workload within 0.01 s).
`bare_throughput.py` measures saturated throughput with **no patches
applied**, clocking the only progress signal visible from agent state
alone — line exits:

```
python -m bench_line.bare_throughput --N 50 --rate 5000 --mode bare
python -m bench_line.bare_throughput --N 50 --rate 5000 --mode instrumented
```

Comparing the two modes at the same over-ceiling cell quantifies the
coupling. Counterintuitively the instrumented engine is *faster* there,
and the effect scales with the number of live CarAgent threads (the
per-event stamps and shared log lock throttle the agent threads,
un-starving the single dispatch thread — a GIL-scheduling effect):
negligible (≤5%) for N ≥ 150, up to ~1.8× in small-N cells that
accumulate thousands of car threads. Saturated-regime throughput should
therefore be read as order-of-magnitude; sub-saturation metrics are
unaffected.
