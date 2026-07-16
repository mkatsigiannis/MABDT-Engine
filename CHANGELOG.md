# Changelog

## 1.0.0 — 2026-07-14

### Fixed

- **Car-position tracking race in the Tiger Motors deployment.**
  `BarcodeProcessor` decided between its "operation complete" and "car
  moved" routes by reading `CarAgent.current_workstation` — an attribute
  the car's own thread rewrites from whatever event it is currently
  processing. When a car thread lagged its scan stream by more than one
  line cycle, the attribute transiently held a past station, an exit
  scan misrouted as a move, and the car's bare `"start"` dedup key then
  suppressed the scans that would have resynchronized it. The processor
  now keeps its own single-writer car-position map (`_positions`,
  touched only from the communication agent's dispatch thread), and
  `CarAgent` deduplication keys are station-scoped (`start_{ws_num}`,
  `done_{ws_num}`-equivalent). The race only manifested at cycle times
  below ~0.3 s — benchmark time compression, far beyond the physical
  lab's 60 s takt — but any tracking error is a correctness bug for a
  digital twin. Verified before/after with the `bench_line` harness
  (N=50, r=1,000: 2,423 misrouted scans and 51 lost cars → zero; all
  300 offered line exits observed). No public API change.

### Added

- **`bench_line/`** — unified paced-assembly-line scaling study. A
  primed line of N stations advances one station per cycle time T
  (staggered or burst arrivals), measuring dispatch latency,
  throughput/saturation, and assembly-line quantities: takt achievement,
  per-car lead time against the paced ideal, constant WIP. The
  generator runs as a separate OS process (no GIL sharing with the
  engine), workstation agents are instrumented alongside car agents,
  and `verify_summary.py` audits every run against the line model's
  bookkeeping identities. Supersedes `bench/`, which is retained
  unchanged for reproducibility of the originally submitted numbers.
- **`bench_fidelity/`** — stochastic-line fidelity study. A seeded
  discrete-event simulation of the line (takt-paced release,
  Triangular(50, 60, 70) s service, Uniform(1, 3) s grab delays,
  optional bottleneck station) is replayed over MQTT under time
  compression; the digital twin's observations are graded against the
  simulation's ground truth: paired per-car lead-time error, lead-time
  distribution distance (two-sample KS), exit inter-departure CV
  agreement, per-station busy-time error, and bottleneck localization.

### Changed

- README: the evaluation section now documents both harnesses.
- Package version metadata (`pyproject.toml`, `mabdt.__version__`,
  `CITATION.cff`) bumped to 1.0.0.

## 0.1.0 — 2026-06-10

Initial public release: `mabdt` engine, Tiger Motors reference
deployment, toy-line example, test suite, and the `bench/` scaling
harness (git tag `v0.1.0`).
