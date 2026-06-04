# Schematic Editor

> Interactive schematic capture with KiCad-compatible symbols, hierarchical sheets, net labels, buses, and real-time ERC.

**Module**: `packages/kerf-electronics/src/kerf_electronics/schematic/capture.py`
**Shipped**: Wave 9C2
**LLM tools**: `electronics_place_symbol`, `electronics_connect_wires`, `electronics_add_label`, `electronics_validate_erc`

---

## What it is

The schematic editor is the front-end for all electronics work: you place component symbols, draw wires, add net labels, define bus bundles, and declare hierarchical sheet pins. The editor model is persistent JSON — every operation returns an updated schematic dict that can be stored, branched, and diffed. The LLM drives it through the same tool API that the interactive frontend uses, so chat and GUI are equivalent.

## How to use it

### From chat

> "Add a 10 kΩ pull-up resistor from 3.3V to the RESET net. Label the junction."

### From Python

```python
from kerf_electronics.schematic.capture import (
    Schematic, Sheet,
    place_symbol, connect_wires, add_label, add_junction, save_kicad_sch
)

sch = Schematic(sheets={"s1": Sheet()}, active_sheet="s1")
place_symbol(sch, "Device:R", "R1", "10k", (150, 100))
connect_wires(sch, [[150, 90], [150, 80], [200, 80]])  # to VCC
add_label(sch, at=(200, 80), net_name="+3.3V")
connect_wires(sch, [[150, 110], [150, 120]])  # to RESET
add_label(sch, at=(150, 125), net_name="RESET")
kicad_sch = save_kicad_sch(sch, "s1")
```

### From an LLM tool spec

```json
{"action": "place_symbol", "lib_ref": "Device:R",
 "designator": "R1", "value": "10k", "position": [150, 100]}
```

## How it works

The `Schematic` data model stores `sheets` (keyed by ID), each sheet holding lists of `Symbol`, `Wire`, `Junction`, `Label`, `Bus`, and sub-sheet reference objects. Operations are pure functions that mutate the dataclass and return `{"ok": True}` or `{"ok": False, "reason": ...}`. `build_netlist` performs a graph traversal: wires are connected if they share an endpoint or cross through a junction; net names propagate from labels. `save_kicad_sch` serialises one sheet to a KiCad v6 S-expression `.kicad_sch` file covering a minimal but parseable subset.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `place_symbol(sch, lib_ref, designator, value, position)` | `dict` | Place component |
| `connect_wires(sch, points)` | `dict` | Draw wire path |
| `auto_connect(pin_a, pin_b)` | `dict` | Auto 1-bend wire |
| `add_label(sch, at, net_name)` | `dict` | Net label |
| `add_junction(sch, at)` | `dict` | Junction dot |
| `hierarchical_port(sch, sheet, port_name, direction)` | `dict` | Sheet-level port |
| `build_netlist(sch)` | `dict` | Full netlist extraction |
| `validate_erc(sch)` | `dict` | ERC violations |
| `load_kicad_sch(text)` | `dict` | Import KiCad .kicad_sch |
| `save_kicad_sch(sch, sheet_id)` | `dict` | Export KiCad .kicad_sch |

## Example

```python
from kerf_electronics.schematic.capture import build_netlist, Schematic, Sheet
sch = Schematic(sheets={"s1": Sheet()}, active_sheet="s1")
place_symbol(sch, "Device:R", "R1", "1k", (100,100))
place_symbol(sch, "Device:R", "R2", "2k", (200,100))
connect_wires(sch, [[115,100],[185,100]])
nl = build_netlist(sch)
print(nl["nets"])
```

## Honest caveats

The KiCad S-expression parser covers the minimal subset needed for round-trip of 2-resistor test schematics; complex attributes (parametric fields, custom hierarchical sheet styles) may not round-trip correctly. Bus expansion (BUS[0..7] → individual nets) is parsed but not yet used in ERC/netlist. Library symbol pinout definitions are not bundled — only the connection geometry is tracked.

## References

- KiCad (2024). *KiCad File Format Reference, v6*. docs.kicad.org/6.0/en/file-formats/.
