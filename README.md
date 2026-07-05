# MABDT Engine

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20755232.svg)](https://doi.org/10.5281/zenodo.20755232)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

This repository contains a Multi-Agent-Based Digital Twin (MABDT) engine and
a reference deployment for the Tiger Motors lab at Auburn University. It is
the companion artifact to the dissertation *Digitalizing Assembly Operations
Using Agent-Based Modeling Techniques and Digital Twin Technologies*
(Katsigiannis, 2026) and the paper submitted to the *Journal of Intelligent
Manufacturing*.

The repository is split into two Python packages:

- **`mabdt/`** — the engine. Four components from the JIM paper's "Engine Architecture" section: simulation
  environment, communication kernel, interface layer, services.
  Deployment-agnostic. No Tiger Motors vocabulary.
- **`tiger_motors_dt/`** — the Tiger Motors deployment built on `mabdt`:
  15 workstations across 3 cells, three barcode-driven topic processors,
  PySide6 GUI, OPC UA bridge, LLM chat.

A ~250-line toy deployment in `examples/toy_line/` shows how to use `mabdt`
end-to-end without a broker or GUI. Read that file first if you want to
build your own deployment.

## Install

Requires Python 3.10 or newer. From a fresh checkout:

```
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -e ".[tiger,dev]"
```

The `tiger` extra pulls in the deployment dependencies (PySide6, Ollama,
OPC UA, scanner, NumPy). For engine-only use, `pip install -e .` is enough.

## Run the toy example

```
python -m examples.toy_line.main
```

Five cars cycle through two workstations in under a second. See
[`examples/toy_line/README.md`](examples/toy_line/README.md) for what it
demonstrates.

## Run the Tiger Motors deployment

Copy the configuration template and edit the MQTT broker address:

```
copy config_template.json config.json    # Linux/macOS: cp config_template.json config.json
```

Set `mqtt.host` (and `port` if not 8883). Then launch one of:

```
python gui_main.py                       # PySide6 GUI
python cli_main.py                       # text console
```

`config.json` is gitignored, so each developer keeps their own broker
settings.

### Synthetic data generator

To exercise the GUI without the physical lab, run the synthetic generator.
It publishes scanner and PLC traffic to the configured broker so the GUI
behaves as if cars are flowing through the line:

```
python -m tiger_motors_dt.tools.data_generator
```

Pass `--help` for the car-count, cycle-time, and fault-rate flags.

## Build a portable Windows distribution

To produce a folder that runs on Windows machines without a Python install:

```
scripts\windows_build\build_standalone.bat
```

The output is `dist\TigerMotorsDT\TigerMotorsDT.exe`. See
[`scripts/windows_build/QUICK_START_BUILDING.txt`](scripts/windows_build/QUICK_START_BUILDING.txt)
for the build procedure and
[`scripts/windows_build/README_STANDALONE.txt`](scripts/windows_build/README_STANDALONE.txt)
for end-user notes.

## Tests

```
pytest
```

The suite covers `mabdt` core (agent, state machine, event bus,
communication agent, protocol matching, environment, interface), the three
Tiger processors, and the toy-line end-to-end smoke test.

## Reproducing the JIM scaling experiment

The scaling study reported in the paper lives in [`bench/`](bench/),
self-contained and instrumentation-via-monkey-patch so the engine
itself ships unencumbered. See [`bench/README.md`](bench/README.md) for
the full sweep procedure and what each output column means.

Quick check:

```
python -m bench.benchmark --N 15 --rate 30 --duration 60
```

Full sensitivity grid (~50–70 minutes):

```
bench\run_sensitivity.bat
```

A local MQTT broker on the configured host/port is required.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — the JIM paper's engine components mapped
  to code.
- [`examples/toy_line/main.py`](examples/toy_line/main.py) — the smallest
  working deployment, with comments tying each piece back to the paper.
- [`bench/README.md`](bench/README.md) — the scaling-study harness used
  for the JIM tables and plots.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — branch, lint, test policy for
  external contributors.
- The `mabdt/` and `tiger_motors_dt/` source files carry the rest. Module
  docstrings explain intent; class docstrings explain shape.

## Cite

If you use this engine, please cite the paper, the dissertation, and the
software release:

```bibtex
@article{katsigiannis2026jim,
  title   = {Multi-Agent-Based Digital Twin Engine for Manufacturing Operations},
  author  = {Katsigiannis, Michail and Mykoniatis, Konstantinos},
  journal = {Journal of Intelligent Manufacturing},
  year    = {2026},
  note    = {Under review}
}

@phdthesis{katsigiannis2026phd,
  title  = {Digitalizing Assembly Operations Using Agent-Based Modeling Techniques and Digital Twin Technologies},
  author = {Katsigiannis, Michail},
  school = {Auburn University},
  year   = {2026}
}

@software{katsigiannis2026mabdt,
  title   = {{MABDT Engine}: A Multi-Agent-Based Digital Twin Engine for Manufacturing Operations},
  author  = {Katsigiannis, Michail},
  year    = {2026},
  version = {0.1.0},
  doi     = {10.5281/zenodo.20755232},
  url     = {https://github.com/mkatsigiannis/MABDT-Engine},
  license = {MIT}
}
```

See [`CITATION.cff`](CITATION.cff) for canonical metadata.

## License

MIT. See [`LICENSE`](LICENSE).
