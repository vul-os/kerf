# Netlist Code Generation

> Export CircuitJSON netlists to KiCad, Specctra DSN, IPC-2581, ODB++, and SPICE formats for hand-off to downstream EDA tools and fabricators.

**Module**: `packages/kerf-electronics/src/kerf_electronics/tools/netlist_export.py`, `fab/ipc2581.py`, `fab/odbpp/writer.py`
**Shipped**: Wave 10
**LLM tools**: `electronics_export_netlist`, `electronics_export_ipc2581`, `electronics_export_odbpp`

---

## What it is

CircuitJSON is Kerf's internal board representation. To send a board to a fabricator or import into KiCad/Allegro/Altium you need a standard interchange format. This module generates: (1) KiCad `.net` netlist for back-annotation, (2) Specctra DSN for FreeRouting/Allegro, (3) IPC-2581 XML for CAM-independent fabrication data, and (4) ODB++ directory structure for high-end PCB shops. SPICE netlist export feeds the BSIM4/sim_corner pipeline.

## How to use it

### From chat

> "Export my PCB as an IPC-2581 file for the board house and also generate a KiCad netlist for back-annotation."

### From Python

```python
from kerf_electronics.tools.netlist_export import export_kicad_netlist, export_spice
from kerf_electronics.fab.ipc2581 import export_ipc2581

kicad_net = export_kicad_netlist(circuit_json)
spice_net = export_spice(circuit_json)
ipc_xml = export_ipc2581(circuit_json)

with open("board.net", "w") as f:
    f.write(kicad_net)
with open("board.xml", "w") as f:
    f.write(ipc_xml)
```

### From an LLM tool spec

```json
{"circuit_json_id": "<uuid>",
 "formats": ["kicad_netlist", "ipc2581", "spice"]}
```

## How it works

`export_kicad_netlist` walks the CircuitJSON components and nets and emits a KiCad Classic netlist (old-style S-expression format for `(Export (version D) ...)`). `export_ipc2581` serialises the board to IPC-2581 Rev C XML: BOM, netlist, layer stackup, padstack definitions, and component placement. `export_odbpp` creates the ODB++ directory tree with `matrix/`, `steps/`, `symbols/` etc. required by Valor/Genesis CAM systems. SPICE netlist walks all components and emits element lines with node connectivity.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `export_kicad_netlist(circuit_json)` | `str` | KiCad .net format |
| `export_spice(circuit_json)` | `str` | SPICE netlist |
| `export_ipc2581(circuit_json)` | `str` | IPC-2581 Rev C XML |
| `export_odbpp(circuit_json, output_dir)` | `None` | ODB++ directory tree |

## Example

```python
from kerf_electronics.tools.netlist_export import export_spice
spice = export_spice(circuit_json)
# Paste first few lines for verification:
print(spice[:300])
```

## Honest caveats

IPC-2581 export produces Rev C (2012) format; some older CAM systems accept Rev A/B only. ODB++ output has been validated against a single reference board; complex flex/rigid-flex stackups may require manual correction. SPICE export maps component types from CircuitJSON conventions to standard SPICE element letters (R, C, L, Q, M, X); custom component types are exported as subcircuit references with a warning.

## References

- IPC-2581 (2012). *Printed Board Assembly Product Description Data and Transfer Methodology*. Rev C.
- Valor (2010). *ODB++ Format Specification*, v8.1. Mentor Graphics.
