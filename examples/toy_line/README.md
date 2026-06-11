# Toy assembly line

The smallest realistic deployment built on `mabdt`: two workstations, a
stream of cars cycling through both stations, no GUI, no MQTT broker.

Run with:

```bash
python -m examples.toy_line.main
```

Expected output:

```
Toy line started. Sending 5 cars through 2 workstations.

Cars finished: 5 / 5
Workstation loads:
  WS1: served 5 cars
  WS2: served 5 cars
```

## What it shows

The single file `main.py` walks through every engine component from JIM §3:

| Section | Engine concept (paper §) |
|---|---|
| `ToyWorkstationAgent`, `ToyCarAgent` | DT agents with hierarchical statecharts (§3.1) |
| `ToyBarcodeProcessor` | Rule-based routing pipeline (§3.2) |
| `ToyLineEnvironment(mabdt.Environment)` | Environment orchestrator with declarative populations (§3.1) |
| `mabdt.CommunicationAgent` + `mabdt.InMemoryProtocol` | Communication kernel (§3.2) |
| `ToyLineInterface(mabdt.SimulationInterface)` | Interface layer with domain queries (§3.3) |
| `run_synthetic_generator` | Stands in for the physical layer (§3.4 application path) |

The Tiger Motors deployment in this repository implements the same
pattern at full scale (15 workstations, three-cell layout, real MQTT
broker, PySide6 GUI, MING dashboards). Compare `examples/toy_line/main.py`
with `tiger_motors_dt/simulation/environment.py` and
`tiger_motors_dt/agents/comm_agent.py` to see the mapping from the
minimal example to a production-shaped deployment.

## Adapt this to your own line

Five steps take this from a toy to a deployment:

1. **Define your statecharts.** Replace `ToyWorkstationAgent` and
   `ToyCarAgent` with one `mabdt.StateMachineAgent` subclass per DT
   agent type, declaring states and transitions in the `transitions`
   library's dict format.
2. **Write one `mabdt.TopicProcessor` per inbound topic family.**
   `ToyBarcodeProcessor` is the template; declare `subscriptions`,
   parse the payload in `process()`, and route into agent inboxes via
   `receive()`. Multiple processors register on the same
   `CommunicationAgent`.
3. **Subclass `mabdt.Environment` and override `_declare()`.** Call
   `register_population` for each static agent type, `register_singleton`
   for one-off agents, and `register_messaging` for the communication
   agent. Production-lifecycle policy goes in
   `on_production_started()` / `on_production_stopped()` hooks.
4. **Swap `InMemoryProtocol` for `MqttProtocol`** when you're ready to
   talk to a real broker — same `mabdt.CommunicationAgent` constructor,
   point it at the new protocol.
5. **Extend `mabdt.SimulationInterface` with the queries your
   applications need.** The two methods in `ToyLineInterface` show the
   shape: take the inherited lock, validate the environment, return
   read-only data.

The Tiger Motors deployment is a worked-out example of each of these
five steps at production scale.

## Use as a smoke test

`tests/test_toy_line.py` imports the example end-to-end and asserts that
every car reaches `Finished` and every workstation serves every car.
Beyond verifying the example itself, it doubles as a sanity check that
`mabdt` is still usable as a library — if it stops running to completion
in under ~5 seconds, something in the engine has regressed.
