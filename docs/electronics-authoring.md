# Electronics Authoring

> Create and manage electronic circuit designs in Kerf using atopile HDL, tscircuit CircuitJSON, or the LLM chat interface.

**Module**: `packages/kerf-electronics/src/kerf_electronics/atopile/`, `schematic/`
**Shipped**: Wave 8
**LLM tools**: `electronics_place_symbol`, `electronics_connect_wires`, `electronics_build_netlist`

---

## What it is

Electronics authoring in Kerf starts with a schematic — the abstract connectivity of components before any PCB geometry is assigned. Kerf supports two authoring paths: (1) **atopile HDL** — a typed, component-centric hardware-description language where connections are declared via typed interface ports, and (2) **native schematic capture** — placing KiCad-compatible symbols and drawing wire connections interactively or via the LLM. Both paths produce the same `CircuitJSON` netlist consumed by routing, DRC, and simulation tools.

## How to use it

### From chat

> "Place an STM32F4 microcontroller and a 100 nF decoupling cap on the schematic. Connect VDD to the cap's positive terminal and GND to negative."

### From Python

```python
from kerf_electronics.schematic.capture import (
    place_symbol, connect_wires, build_netlist, Schematic, Sheet
)

sch = Schematic(sheets={"s1": Sheet()}, active_sheet="s1")
place_symbol(sch, lib_ref="Device:C", designator="C1", value="100n",
             position=(100, 100))
place_symbol(sch, lib_ref="MCU:STM32F4", designator="U1", value="STM32F401",
             position=(200, 100))
connect_wires(sch, points=[[108, 100], [192, 100]])
netlist = build_netlist(sch)
print(netlist["nets"])
```

### From an LLM tool spec

```json
{"action": "place_symbol", "lib_ref": "Device:C",
 "designator": "C1", "value": "100n",
 "position": [100, 100]}
```

## How it works

The schematic capture data model stores symbols, wires, junctions, and net labels per sheet. `build_netlist` traces connectivity from placed symbols through wire segments and net labels to produce a JSON netlist and a KiCad-classic netlist string. The atopile compiler (`atopile/compile.py`) parses the `.ato` HDL grammar (tokenised via a hand-written lexer), resolves typed port connections, and emits a `CircuitJSON` board file. Both paths produce compatible output for downstream tools.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `place_symbol(sch, lib_ref, designator, value, position)` | `dict` | Add component to active sheet |
| `connect_wires(sch, points)` | `dict` | Draw wire path |
| `auto_connect(pin_a, pin_b)` | `dict` | Route 1-bend orthogonal wire |
| `build_netlist(schematic)` | `dict` | Extract connectivity to JSON netlist |
| `validate_erc(schematic)` | `dict` | Electrical Rules Check |

## Example

```python
from kerf_electronics.schematic.capture import validate_erc, Schematic, Sheet
sch = Schematic(sheets={"s1": Sheet()}, active_sheet="s1")
result = validate_erc(sch)
print(result["violations"])  # [] for an empty schematic
```

## Honest caveats

The atopile compiler handles the core grammar subset (component instances, port connections, values). Parameterised generics and `assert` statements are parsed but not yet evaluated — they are preserved as annotations. KiCad symbol library access requires either a local KiCad installation or the bundled minimal library subset. Hierarchical multi-sheet ERC for conflicting net drivers between sheets is not yet implemented.

## References

- atopile (2024). *atopile Language Reference*. github.com/atopile/atopile.
- KiCad (2024). *Schematic File Format Reference*. docs.kicad.org.
