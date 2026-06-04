# PVT Corner and Monte Carlo SPICE Analysis

*Domain: Electronics · Module: `packages/kerf-electronics/src/kerf_electronics/sim_corner.py` · Shipped: Wave 10*

## Overview

Runs DC operating point, AC transfer function, corner analysis, Monte Carlo yield, sensitivity analysis, and temperature sweep simulations on SPICE netlists using a pure-Python MNA (Modified Nodal Analysis) solver. Covers resistors, capacitors, inductors, voltage sources, current sources, and diodes. Monte Carlo sampling uses a seeded LCG with Box-Muller Gaussian transforms for yield estimation.

## When to use

- Quick DC/AC verification of a netlist before running ngspice.
- Corner analysis across process/voltage/temperature variations.
- Monte Carlo yield estimation for tolerance-critical designs.
- Sensitivity sweep to identify which component values affect the output most.

## API

```python
from kerf_electronics.sim_corner import (
    run_dc_op, run_ac_transfer,
    corner_analysis, monte_carlo,
    sensitivity_analysis, tempco_sweep,
)

netlist = [
    {"type": "R", "name": "R1", "nodes": ["in", "out"], "value": 1e3},
    {"type": "C", "name": "C1", "nodes": ["out", "gnd"], "value": 1e-9},
    {"type": "V", "name": "Vin", "nodes": ["in", "gnd"], "value": 1.0},
]

dc = run_dc_op(netlist, values={}, nodes_of_interest=["out"])
ac = run_ac_transfer(netlist, values={}, f_start=1e3, f_stop=1e9, n_pts=50)

# 3-corner analysis (min/typ/max)
corners = corner_analysis(netlist, param="R1",
                          nominal=1e3, spread_frac=0.05)
```

## LLM tools

`run_mc_corner_analysis`

## References

- Nagel, "SPICE2: A computer program to simulate semiconductor circuits", *UCB/ERL M520*, 1975.
- Tuinenga, *SPICE: A Guide to Circuit Simulation and Analysis*.

## Honest caveats

The MNA solver supports resistors, capacitors, inductors, voltage sources, current sources, and a piece-wise-linear diode. Bipolar transistors, MOSFETs, and transmission lines are not implemented — for those, use the ngspice bridge. AC analysis uses small-signal linearisation around the DC operating point; nonlinear behaviour under large signals is not captured.
