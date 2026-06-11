# bench — Scaling study harness for the MABDT engine

Self-contained benchmark tooling that imports from `mabdt` and
`tiger_motors_dt` but **does not modify** either package. Instrumentation
is added at runtime via monkey-patching in `bench/instrument.py`, so the
published engine code has no benchmarking concerns.

## What it measures

For a given workstation count `N` and synthetic event rate `r`:

- **Throughput** — events the generator tried to publish vs. events the
  engine actually processed end-to-end.
- **Latency** — per-event timing decomposed into four stamps:
  - `mqtt_in` (MQTT receive)
  - `inbox_in` (queued on target agent)
  - `handle_start` / `handle_end` (statechart processing)
- **Cost** — process CPU%, RSS, and OS thread count, sampled every 500 ms.

Cars walk the full configured line of `N` workstations and exit into
inspection at WS{N}. Dispatch load is distributed across all `N`
workstation agents in proportion to the in-flight car population.

## Requirements

- A local MQTT broker on the configured host/port (defaults to
  `127.0.0.1:8883`). Mosquitto in Docker is fine.
- `psutil`, `matplotlib` in addition to the engine's runtime deps.

## Configuration overrides for the benchmark

`bench/config_benchmark.json` differs from `config_template.json` in two
ways that matter at large `N`:

- `barcode_scanner_service.enabled` and `opc_ua_service.enabled` are
  `false` — the synthetic generator drives MQTT directly.
- `performance.eventbus_tick_interval` is `1.0` instead of `0.01`. The
  default deployment value runs the tick at 100 Hz to feed Andon
  utilization counters; at `N=1000` that's `100,000` synchronous
  `queue.put()` calls per second on the tick thread, which saturates
  the GIL and starves paho's MQTT receive thread (the engine never
  dispatches the synthetic events). The benchmark cares about dispatch
  latency, not counter resolution, so the tick runs at 1 Hz.

## Run a single point

```
python -m bench.benchmark --N 15 --rate 30 --duration 60
python -m bench.benchmark --N 500 --rate 30 --duration 60
```

Each run writes:

- `bench/results/N{N}_latency.csv` — per-event timing rows
- `bench/results/N{N}_engine.log` — engine stdout for that run
- one row appended to `bench/results/summary.csv`

## Run a sweep

Three batch files at `bench/`:

- **`run_sweep.bat`** — single-rate sweep at 30 eps across
  `N in {15, 50, 150, 500, 1000}`. ~5 runs, ~10 minutes. Use this when
  you just want the latency-vs-N curve at production load.
- **`run_sensitivity.bat`** — full 5x6 grid:
  `N in {15, 50, 150, 500, 1000}` × `rate in {30, 100, 300, 1000, 3000, 10000}`.
  30 runs, ~50-70 minutes depending on shutdown cost at large N. The
  full characterization for the paper; produces both the scaling and
  the saturation plots in one pass.
- **`run_saturation.bat`** — just the high-rate slice of the grid:
  `N in {15, 50, 150, 500, 1000}` × `rate in {3000, 10000}`. 10 runs,
  ~20 minutes. Use when re-checking saturation behavior without
  rerunning the whole grid.

Both batch files clear `bench/results/summary.csv`, run the broker
reachability check first, then invoke `python -m bench.analyze` at the
end to produce the table and plots.

To run a single point manually:

```
python -m bench.benchmark --N 500 --rate 100 --duration 60
```

## Outputs

| File | What |
|---|---|
| `results/summary.csv` | One row per `(N, rate)` run. Headline metrics. |
| `results/N{N}_R{rate}_latency.csv` | Per-event timing for that run. |
| `results/N{N}_R{rate}_engine.log` | Engine stdout for that run (empty unless the engine prints WARNING+). |
| `results/scaling_latency.png` | Median + p95 e2e latency vs N. One line per rate. |
| `results/saturation.png` | Actual throughput vs target rate, one line per N. Only written when the summary has multiple rates. |

## Reading the summary columns

| Column | Meaning |
|---|---|
| `throughput_eps` | Events processed per second of **runner runtime**. This is the engine-side throughput — divides events_published by the time `_runner` was actually publishing, not total benchmark wall time. |
| `throughput_walltime_eps` | Same numerator, but divides by total wall time (includes `env.shutdown` joining all WS threads). Goes far below `throughput_eps` at large N because shutdown is slow. Kept for diagnostics. |
| `runner_runtime_s` | Time the publish loop ran. Should be very close to `--duration`. |
| `e2e_ms_*` | End-to-end latency = `handle_end - mqtt_in`. Median, p95, p99 in ms. |
| `inbox_wait_ms_*` | Time an event sat in the agent's inbox before `handle()` picked it up. |

## How the no-touch instrumentation works

`bench/instrument.py` replaces three methods on the engine's class
objects at runtime:

| Method | What the patch adds |
|---|---|
| `mabdt.agent.base.Agent.receive` | Lifts `mqtt_in` off thread-local into the event dict, stamps `inbox_in` |
| `mabdt.agent.base.Agent._run_loop` | Stamps `handle_start` / `handle_end` around `handle()`, writes a CSV row |
| `mabdt.communication_kernel.communication_agent.CommunicationAgent._on_message` | Stamps `mqtt_in` on the MQTT receive thread before dispatch |

`instrument.enable(latency_csv_path)` applies the patches AND starts
writing the latency log. `instrument.disable()` restores the originals.

**Apply the patch before constructing `TigerMotorsEnvironment`.** Agents
capture their bound `_run_loop` when they spin up their thread in
`Agent.__init__`, so a patch applied later won't reach already-running
threads. The runner (`bench/benchmark.py`) does this in the right order.

When `instrument.enable()` is not called, the latency logger is disabled
and the patched methods skip the timing block (one boolean check per
message). So the patches are safe to leave installed between runs.

## Maintenance

If `mabdt.agent.base.Agent._run_loop` ever changes (e.g. new race
handling), copy the new loop body into `_patched_run_loop` in
`instrument.py` and re-add the two `_bench.record(...)` blocks around the
`self.handle(evt)` call sites. The other two patches are thin shims and
should rarely need attention.
