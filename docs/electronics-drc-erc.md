# PCB DRC & Schematic ERC

> Design Rule Check (clearance, unrouted nets, missing footprints) and Electrical Rules Check (unconnected pins, driver conflicts) for PCB and schematic validation.

**Module**: `packages/kerf-electronics/src/kerf_electronics/drc.py`, `schematic/capture.py`
**Shipped**: Wave 8
**LLM tools**: `electronics_run_drc`, `electronics_validate_erc`

---

## What it is

DRC and ERC are the last line of defence before sending Gerbers to the fabricator or schematics to review. DRC catches physical spacing violations (copper-to-copper clearance, minimum trace width, unrouted connections) that cause manufacturing yield issues. ERC catches logical errors (floating pins, multiple drivers on one net, net name collisions) that indicate design intent errors. Running both is mandatory before generating fab output.

## How to use it

### From chat

> "Run DRC on my PCB with IPC-2221B Class B rules. List all violations and their severity."

### From Python

```python
from kerf_electronics.drc import run_drc, DEFAULT_RULES

violations = run_drc(circuit_json, rules=DEFAULT_RULES)
print(f"Errors: {violations['error_count']}, Warnings: {violations['warning_count']}")
for v in violations["violations"]:
    print(f"[{v['severity']}] {v['kind']}: {v['message']} at ({v['x']:.2f}, {v['y']:.2f})")
```

### From an LLM tool spec

```json
{"circuit_json_id": "<uuid>",
 "rules": {"min_clearance_mm": 0.2, "min_trace_width_mm": 0.15}}
```

## How it works

DRC runs three check families: (1) **clearance** — pad-to-pad, pad-to-trace, and trace-to-trace distances are computed using a segment-distance formula with bounding-box pre-filtering; violations fire when separation < `min_clearance_mm`. (2) **unconnected pads** — any pad carrying a net_id not appearing as a route endpoint is flagged as unrouted. (3) **missing footprints** — schematic components without a matching PCB component are listed. ERC (in `schematic/capture.py`) checks for unconnected pins (no wire at pin coordinate), multiple voltage drivers on one net, net name collisions across sheets, and dangling wire ends.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `run_drc(circuit_json, rules)` | `dict` | PCB physical design rule check |
| `validate_erc(schematic)` | `dict` | Schematic electrical rules check |

`run_drc` returns: `{"violations": [...], "error_count": int, "warning_count": int}`. Each violation: `{kind, message, x, y, severity}`.

## Example

```python
from kerf_electronics.drc import run_drc, DEFAULT_RULES

# Stricter rules for high-density board
tight = {**DEFAULT_RULES, "min_clearance_mm": 0.1}
r = run_drc(circuit_json, rules=tight)
errors = [v for v in r["violations"] if v["severity"] == "error"]
print(f"{len(errors)} DRC errors with 0.1 mm rules")
```

## Honest caveats

DRC clearance checks use a geometric segment-distance test, not polygon expansion — complex pad shapes (rotated rectangles, thermal reliefs) may produce false negatives. The trace-to-trace check uses bounding-box pre-filtering which can miss diagonal traces at near-threshold spacing. ERC driver-conflict detection covers simple voltage sources and power pins; open-collector and tri-state logic are not modelled.

## References

- IPC-2221B (2012). *Generic Standard on Printed Board Design*. §6.3 (spacing requirements).
- KiCad (2024). *DRC and ERC Reference*. docs.kicad.org.
