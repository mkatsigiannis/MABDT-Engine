# Contributing

Thanks for taking the time. This repository is the companion artifact
to a journal paper and a dissertation, so the bar isn't "ship it and
iterate" — it's "the next reader can trust this." That mostly means:
keep the engine boundary intact, keep tests green, and write changes a
reviewer can grasp without context.

## Setting up

```
git clone <repo>
cd TigerMotorsDTPython
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -e ".[tiger,dev]"
```

The `dev` extra alone is enough to run the test suite. Add `tiger` if
you want to launch the GUI or the LLM service locally.

## Running the checks locally

Run the same checks CI runs before pushing — saves a round trip:

```
pytest                                          # 81 tests, ~20 s
ruff check mabdt tiger_motors_dt tests examples bench
black --check mabdt tiger_motors_dt tests examples bench
```

If `black --check` reports drift, run `black <paths>` to apply it. If
`ruff check` reports drift, run `ruff check --fix <paths>` for the
safe rewrites and address the rest by hand.

## What CI runs

`.github/workflows/ci.yml` runs on every push and PR:

- **Lint** — `ruff check` and `black --check` on Ubuntu / Python 3.12.
- **Tests** — `pytest` on `{ubuntu, windows} × {3.10, 3.11, 3.12}`.

The test suite is engine-only (no PySide6 / OPC UA / matplotlib), so
the matrix is fast.

## Branch and commit hygiene

- Branch from the published default branch and open the PR against it.
- One commit per logical change. Bundling unrelated edits into one
  commit makes bisect useless.
- Commit messages: first line is a short imperative sentence; the
  body explains the **why**, not the **what** (the diff already shows
  the what).
- Don't include `Co-Authored-By:` lines unless you're recording a real
  human pair-programming contribution.

## Where new code goes

The two packages have very different roles. Putting code in the wrong
one is the most common review request:

- **`mabdt/`** — the engine. Pure framework abstractions: agent
  lifecycle, message bus, communication kernel, interface base class.
  **No Tiger Motors vocabulary anywhere.** No reference to
  workstations, cars, cells, inspection stations, MQTT topic shapes,
  config keys. If you'd write the same code for a different facility,
  it belongs here.
- **`tiger_motors_dt/`** — the deployment. Domain agents (Car,
  Workstation, InspectionStation), Tiger-specific DTOs and queries,
  the PySide6 GUI, the LLM service, the OPC UA bridge. Everything that
  knows about Tiger lives here.

If you're adding a feature that feels deployment-agnostic but reaches
into `tiger_motors_dt` for one detail, surface the detail through a
hook in `mabdt/` and call the hook from the Tiger code.

## Engine boundary

External callers (GUI, CLI, RAG context collector, future web APIs)
talk to the engine through `SimulationInterface` only. They receive
frozen DTOs from `tiger_motors_dt.simulation.dto`. They do **not**
walk the environment directly or reach into agent attributes.

The single allowed escape hatch for raw access is the named `debug_*`
methods on `TigerSimulationInterface` (used by the agent inspector
debug panel). New widgets do not get to add new escape hatches.

## Tests

- Engine-level changes need a test under `tests/`.
- Tests use `InMemoryProtocol` and the `mabdt` toy line where possible
  — no MQTT broker required.
- If a fix is one line, the test that demonstrates the bug is usually
  ten. Write the test anyway. Several of the regressions caught
  recently were *also* present in the prior implementation; they just
  weren't covered.

## Style

- The repository has a tropes file (`tropes.md`, gitignored, local only
  to the maintainer) listing AI-writing patterns to avoid in prose.
  Module-level and class-level docstrings should be **one or two
  sentences** describing what the thing is for. No "Key Features:"
  bullets, no "Design Principles:" headers, no auto-generated tool
  signatures.
- Inline comments explain *why*, not *what*. The diff already shows
  what. Comments rot, code doesn't.
- Type hints use PEP 604 syntax (`int | None`, not `Optional[int]`).
- Exception re-raises in `except` blocks use `raise ... from e` so the
  chain is preserved.
- Bare `except:` is a CI failure. Catch a specific exception type.
- `except Exception:` is fine at three kinds of boundaries: callback
  dispatch (the engine running user-supplied code that can raise
  anything — see `mabdt/communication_kernel/communication_agent.py`),
  agent / service top-level loop bodies that must keep the thread alive
  no matter what one event raises, and Qt signal handlers (Qt swallows
  exceptions silently, so the catch is the resilience layer). Everywhere
  else, catch the specific exception(s) the call site can actually
  raise — most of the engine's catches were narrowed during the v0.1
  release polish to make the intent grep-able.

## Filing issues and PRs

- For bugs, include the smallest reproduction you can. A failing test
  beats a paragraph of description.
- For features, open an issue first to confirm fit before writing the
  PR — given the scope of this repo, "nice to have" features usually
  belong in a downstream fork rather than the published artifact.
- PRs should be small and focused. A 1000-line PR is almost always
  several smaller PRs in disguise.

## Releasing (maintainer only)

1. Bump `version` in `pyproject.toml` and `CITATION.cff`.
2. Update `CITATION.cff` `date-released`.
3. Tag `vX.Y.Z` on the head of the release branch.
4. Push the tag.

## Code of conduct

Be professional. Disagree with code, not with people. This is a
research artifact attached to identifiable authors; the conversation
norms are the same as a journal review.
