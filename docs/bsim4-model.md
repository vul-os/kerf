# BSIM4 MOSFET Model

> Compact MOSFET device model (BSIM4-compatible parameter set) for analog and mixed-signal SPICE simulation within the Kerf electronics environment.

**Module**: `packages/kerf-silicon/src/kerf_silicon/analog/pvt.py`, `bridges/spice_netlist.py`
**Shipped**: Wave 9C1
**LLM tools**: `electronics_spice_sim`, `silicon_pvt_corners`

---

## What it is

BSIM4 (Berkeley Short-channel IGFET Model v4) is the industry-standard compact MOSFET model used in TSMC, Samsung, and GLOBALFOUNDRIES PDKs. It captures subthreshold leakage, velocity saturation, drain-induced barrier lowering (DIBL), and gate-oxide tunnelling — effects that dominate below 250 nm processes. Kerf's silicon package wraps an ngspice bridge that accepts BSIM4 `.model` cards from a standard PDK and runs DC, AC, and transient analyses.

## How to use it

### From chat

> "Simulate an NMOS common-source amplifier using a TSMC 180nm BSIM4 model: W/L = 10/0.18 µm, Vdd = 1.8 V, R_D = 5 kΩ. Find the DC operating point and small-signal gain."

### From Python

```python
from kerf_silicon.bridges.spice_netlist import build_spice_netlist
from kerf_silicon.bridges.ngspice_bridge import run_ngspice

netlist = build_spice_netlist(
    elements=[
        {"type": "M", "ref": "M1", "nodes": ["drain","gate","0","0"],
         "model": "nmos_180nm", "W": 10e-6, "L": 0.18e-6},
        {"type": "R", "ref": "RD", "nodes": ["vdd","drain"], "value": 5e3},
        {"type": "VDC", "ref": "VDD", "nodes": ["vdd","0"], "value": 1.8},
        {"type": "VDC", "ref": "VGS", "nodes": ["gate","0"], "value": 0.7},
    ],
    model_cards=[open("tsmc180nm.lib").read()]
)
result = run_ngspice(netlist, analysis="op")
print("Drain current:", result["I(M1:d)"], "A")
```

### From an LLM tool spec

```json
{"circuit": "<spice netlist string>",
 "analysis": "op",
 "model_lib": "tsmc180nm"}
```

## How it works

`build_spice_netlist` assembles a SPICE deck in standard ngspice syntax. The BSIM4 model card is included as-is from the PDK `.lib` file. `run_ngspice` invokes ngspice as a subprocess with `-b` (batch) mode, parses the raw output file for node voltages and branch currents, and returns them as a Python dict. PVT corners (`pvt.py`) iterate the simulation over the PDK's TT/FF/SS/SF/FS model corners and −40/27/125°C temperature points.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `build_spice_netlist(elements, model_cards)` | `str` | SPICE deck string |
| `run_ngspice(netlist, analysis)` | `dict` | ngspice simulation result |
| `pvt_corners(netlist_template, corners, temps)` | `list[dict]` | PVT sweep results |

## Example

```python
from kerf_silicon.bridges.ngspice_bridge import run_ngspice
result = run_ngspice("* RC\nR1 in out 1k\nC1 out 0 1n\nV1 in 0 AC 1\n.AC DEC 10 1k 1G\n.END", "ac")
print(result.get("freq_hz")[:3], result.get("V(out)")[:3])
```

## Honest caveats

ngspice must be installed on the host (`brew install ngspice` or `apt install ngspice`). BSIM4 model cards are not bundled — the user must supply PDK-licensed `.lib` files. This wrapper does not implement BSIM4 itself; it delegates to ngspice. For mixed-signal verification (digital + analog), Verilator co-simulation is not yet supported.

## References

- Cao, Y. et al. (2000). New paradigm of predictive MOSFET and interconnect modeling. *CICC 2000*. (BSIM4 overview)
- ngspice (2024). *ngspice Manual*, Release 43. §15 (MOSFET models level 14/BSIM4).
