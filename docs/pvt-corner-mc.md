# PVT Corner & Monte-Carlo Analysis

> Deterministic Monte-Carlo and worst-case corner simulation for small analog netlists — DC operating point, AC transfer function, sensitivity ranking.

**Module**: `packages/kerf-electronics/src/kerf_electronics/sim_corner.py`
**Shipped**: Wave 9
**LLM tools**: `electronics_pvt_corner`, `electronics_monte_carlo`

---

## What it is

Analog circuits must work not just at nominal component values but across all combinations of process (component tolerances), voltage (supply variation), and temperature (operating range) — collectively PVT corners. A filter that rolls off at 10 kHz at nominal could shift to 8 kHz or 12 kHz at worst-case component tolerance. This module runs pure-Python corner and Monte-Carlo analysis on R/C/L netlists using Modified Nodal Analysis (MNA), with no external SPICE required.

## How to use it

### From chat

> "Run Monte-Carlo analysis on my RC low-pass filter: R1 = 10k ±5%, C1 = 10 nF ±10%. 1000 runs. What is the 3σ bandwidth spread?"

### From Python

```python
from kerf_electronics.sim_corner import run_monte_carlo

netlist = [
    {"ref": "R1", "type": "R", "nodes": ["in", "mid"], "value": 10e3, "tol_pct": 5.0},
    {"ref": "C1", "type": "C", "nodes": ["mid", "0"], "value": 10e-9, "tol_pct": 10.0},
    {"ref": "V1", "type": "V", "nodes": ["in", "0"], "value": 1.0},
]
result = run_monte_carlo(netlist, n_runs=1000, seed=42,
                         output_node="mid", freq_hz=1591.5)
print(f"|H| mean: {result['mean']:.4f}, σ: {result['std']:.4f}")
```

### From an LLM tool spec

```json
{"netlist": [{"ref":"R1","type":"R","nodes":["in","mid"],
              "value":10000,"tol_pct":5},
             {"ref":"C1","type":"C","nodes":["mid","0"],
              "value":1e-8,"tol_pct":10}],
 "n_runs": 1000, "output_node": "mid", "freq_hz": 1591.5}
```

## How it works

The DC solver uses Modified Nodal Analysis (MNA): node voltages and branch currents are the unknowns; conductance and source matrices are assembled per element type. Nonlinear devices (diode, ideal opamp) use Newton iteration (≤ 50 steps, 10⁻⁹ V tolerance). AC analysis builds a complex admittance matrix at the specified frequency and solves for complex node voltages. Monte-Carlo uses a seeded LCG random-number generator with Box-Muller transform for Gaussian-distributed tolerances — results are deterministic and reproducible. Corner analysis sweeps all 2^N min/max combinations of tolerance parameters.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `run_monte_carlo(netlist, n_runs, seed, output_node, freq_hz)` | `dict` | MC statistics |
| `run_corners(netlist, output_node, freq_hz)` | `dict` | Worst-case corners |
| `run_dc(netlist)` | `dict` | DC operating point |
| `sensitivity_analysis(netlist, output_node, freq_hz)` | `list[dict]` | Per-component dOut/dParam |

## Example

```python
from kerf_electronics.sim_corner import run_corners
r = run_corners(netlist, output_node="mid", freq_hz=1591.5)
print("Min |H|:", r["min_output"], "Max |H|:", r["max_output"])
```

## Honest caveats

The netlist supports R, C, L, V, I, ideal diode, and ideal opamp only — no BJT, MOSFET, or controlled sources beyond the opamp model. Convergence is not guaranteed for strongly nonlinear circuits or circuits with positive feedback. AC analysis is single-frequency; swept-frequency Bode plots require calling `run_ac` in a loop.

## References

- Pilkington, M. (2004). *SPICE: A Guide to Circuit Simulation and Analysis*. Prentice Hall. §3 (MNA formulation).
- Razavi, B. (2001). *Design of Analog CMOS Integrated Circuits*. McGraw-Hill. §2 (PVT corners).
