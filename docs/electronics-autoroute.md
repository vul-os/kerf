# PCB Auto-Routing (FreeRouting)

> Automatic PCB trace routing via the FreeRouting push-and-shove router, driven from CircuitJSON netlists through a Specctra DSN/SES pipeline.

**Module**: `packages/kerf-electronics/src/kerf_electronics/freerouting/freerouting.py`
**Shipped**: Wave 8
**LLM tools**: `electronics_autoroute`

---

## What it is

Manual PCB routing is tedious for boards with more than a few dozen nets. FreeRouting is a mature open-source push-and-shove auto-router that produces high completion rates on multi-layer boards. Kerf wraps it in a subprocess pipeline: the CircuitJSON board is exported to Specctra DSN format, FreeRouting routes it, the SES session file is read back, and the resulting traces are merged into the CircuitJSON.

## How to use it

### From chat

> "Auto-route all unrouted connections on my PCB using FreeRouting with 0.15 mm minimum trace width. Show me the completion rate."

### From Python

```python
from kerf_electronics.freerouting.freerouting import run_freerouting

result = run_freerouting(
    circuit_json=circuit,
    min_trace_width_mm=0.15,
    passes=3
)
print(f"Routed: {result['routed_count']}/{result['total_count']} nets")
print(f"Completion: {result['completion_pct']:.1f}%")
```

### From an LLM tool spec

```json
{"circuit_json_id": "<uuid>", "min_trace_width_mm": 0.15,
 "passes": 3, "layer_count": 2}
```

## How it works

1. `dsn_writer.py` converts CircuitJSON board geometry (components, pads, keepouts) to a Specctra DSN text file in the FreeRouting format.
2. FreeRouting JAR (v1.9.0, SHA-256 pinned) is invoked as a subprocess: `java -jar freerouting.jar -de input.dsn -do output.ses`.
3. `ses_reader.py` parses the resulting Specctra SES session file and extracts routed wire coordinates.
4. Routes are merged back into the CircuitJSON as `pcb_trace` elements.

Java 17+ must be installed. The JAR is downloaded and cached at `~/.cache/kerf/freerouting/` on first use with SHA-256 integrity verification.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `run_freerouting(circuit_json, min_trace_width_mm, passes)` | `dict` | Full auto-route pipeline |
| `write_dsn(circuit_json)` | `str` | CircuitJSON → Specctra DSN |
| `read_ses(ses_text, circuit_json)` | `dict` | Merge SES routes back |

## Example

```python
from kerf_electronics.freerouting.dsn_writer import write_dsn
dsn = write_dsn(circuit_json)
print(dsn[:200])  # Specctra DSN preamble
```

## Honest caveats

FreeRouting requires Java 17+ on the host — Kerf does not bundle a JRE. The JAR is downloaded automatically but blocked by corporate firewalls; manual placement at the cache path bypasses the download. Differential pairs, length-matched nets, and controlled-impedance rules require net class annotations in the DSN that Kerf does not yet emit — route these manually. Completion rate on dense 4+ layer boards is typically 85–95%.

## References

- Muller, A. (2008). FreeRouting open-source auto-router. *EDA Café* community project.
- IPC-2141A (2004). *Controlled Impedance Circuit Boards and High Speed Logic Design*. §5.
