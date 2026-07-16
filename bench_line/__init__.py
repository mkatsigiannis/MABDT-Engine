"""Line-mode benchmark harness for the MABDT engine.

Successor to `bench/`: instead of round-robin synthetic traffic, the
generator emulates a paced assembly line. All N workstations are primed with a car (all Busy at
production start), and every cycle-time T the whole line advances one
station: each station completes its car, cars shift downstream together,
a new car enters at WS1, and the car at WS{N} exits the line.

This yields manufacturing-native metrics on top of the engine metrics:
exit rate / inter-departure time (achieved takt), per-car lead time
(ideal = N x T), and constant WIP = N, so Little's law holds by
construction.

Like `bench/`, this package imports from `mabdt` and `tiger_motors_dt`
but does NOT modify either; instrumentation is runtime monkey-patching
(`bench_line.instrument`). Unlike `bench/`, workstation agents are also
instrumented (their overridden `_run_loop` is patched too), and the
generator runs in a separate process so its publish cost does not share
the engine's GIL.

See bench_line/README.md for the experiment design and how to run it.
"""
