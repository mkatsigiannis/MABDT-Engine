"""Stochastic-line fidelity benchmark for the MABDT engine.

Third evaluation leg, alongside bench/ (frozen as-submitted scaling
study) and bench_line/ (unified paced-line scaling study). Addresses a
limitation of the paced experiments — they split work perfectly evenly,
while a real line has cycle-time variability, queues that grow and
drain, starving stations, and lead-time distributions rather than
values.

The generator here is a seeded, event-driven simulation of the Tiger
Motors line — takt-paced car release, per-station Triangular service
times, car-grab delays, FIFO buffers, optional bottleneck station —
replayed against the broker at a configurable time compression. Because
the generator computes the whole schedule up front, it knows the GROUND
TRUTH for every quantity the digital twin is supposed to mirror: per-car
lead times, exit inter-departure times, per-station busy time. The
benchmark then measures how faithfully the DT's observed values match
that truth (paired per-car lead errors, exit-CV agreement, utilization
error, bottleneck localization).

Parameters inherit from the deployment's verification generator
(tiger_motors_dt/tools/data_generator.py): Triangular(50, 60, 70) s
service, 75 s takt, Uniform(1, 3) s car-grab delay.

Instrumentation is imported from bench_line (same four runtime patches);
neither engine package is modified. See bench_fidelity/README.md.
"""
