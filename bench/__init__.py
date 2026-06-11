"""Benchmark harness for the MABDT engine.

Self-contained scaling-study tooling that imports from `mabdt` and
`tiger_motors_dt` but does NOT modify either. Instrumentation is added at
runtime via monkey-patching (`bench.instrument`), so the engine code that
ships in the published release contains no benchmarking concerns.

See bench/README.md for how to run a sweep.
"""
