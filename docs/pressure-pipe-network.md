# Pressure Pipe Network

> Steady-state water-distribution network solver using the Global Gradient Algorithm with Hazen-Williams or Darcy-Weisbach head-loss formulas.

**Module**: `packages/kerf-civil/src/kerf_civil/hydraulics_pressure.py`
**Shipped**: Wave 11
**LLM tools**: `civil_water_network_solve`

---

## What it is

Water distribution systems are pressurised networks where each node draws a demand and a pump or reservoir supplies head. The design engineer must verify that nodal pressures meet the minimum service pressure throughout the network — even at peak hour and under fire-flow conditions. This module solves the steady-state problem using the Global Gradient Algorithm (Todini & Pilati, 1988), the same method used by EPANET.

## How to use it

### From chat

> "Solve a two-loop network: reservoir at 50 m head, three demand nodes drawing 10, 15, and 8 L/s, five pipes with Hazen-Williams C = 120. Are all nodes above 20 m pressure?"

### From Python

```python
from kerf_civil.hydraulics_pressure import solve_network

nodes = [
    {"id": "N1", "demand_m3s": 0.0},   # reservoir
    {"id": "N2", "demand_m3s": 0.010},
    {"id": "N3", "demand_m3s": 0.015},
    {"id": "N4", "demand_m3s": 0.008},
]
reservoirs = [{"node_id": "N1", "head_m": 50.0}]
pipes = [
    {"id": "P1", "from": "N1", "to": "N2", "length_m": 500, "diameter_m": 0.2, "C": 120},
    {"id": "P2", "from": "N2", "to": "N3", "length_m": 400, "diameter_m": 0.15, "C": 120},
    {"id": "P3", "from": "N3", "to": "N4", "length_m": 300, "diameter_m": 0.15, "C": 120},
    {"id": "P4", "from": "N4", "to": "N1", "length_m": 450, "diameter_m": 0.2, "C": 120},
    {"id": "P5", "from": "N2", "to": "N4", "length_m": 350, "diameter_m": 0.1, "C": 120},
]
result = solve_network(nodes, reservoirs, pipes, formula="HW")
for n in result.nodes:
    print(f"{n.id}: H = {n.head_m:.2f} m")
```

### From an LLM tool spec

```json
{"nodes": [{"id": "N1", "demand_m3s": 0}],
 "reservoirs": [{"node_id": "N1", "head_m": 50}],
 "pipes": [{"id": "P1", "from": "N1", "to": "N2",
            "length_m": 500, "diameter_m": 0.2, "C": 120}],
 "formula": "HW"}
```

## How it works

The Global Gradient Algorithm builds a linearised nodal-conductance matrix at each iteration: for each pipe k, linearised conductance g_k = 1/(∂h_L/∂Q) where h_L is Hazen-Williams (h_L = r·Q^1.852) or Darcy-Weisbach (Swamee-Jain friction factor). The nodal admittance matrix A is assembled, and the linear system A·H = d is solved for unknown heads H. Pipe flows are updated from Q_k = g_k·(H_a − H_b). Iteration continues until max|ΔQ_k| < 10⁻⁶ m³/s (typically 10–30 iterations).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `solve_network(nodes, reservoirs, pipes, formula, max_iter, tol)` | `NetworkResult` | GGA pressure solver |

`NetworkResult` fields: `nodes` (list with `id`, `head_m`, `pressure_m`), `pipes` (list with `id`, `flow_m3s`, `velocity_m_s`, `headloss_m`), `converged`, `iterations`.

## Example

```python
r = solve_network(nodes, reservoirs, pipes, formula="DW")
print("Converged:", r.converged, "in", r.iterations, "iterations")
low_p = [n for n in r.nodes if n.pressure_m < 20]
print("Nodes below 20 m pressure:", [n.id for n in low_p])
```

## Honest caveats

The solver handles single-zone steady-state only — no time simulation, no pressure zones, no pumps, no check valves, no pressure-reducing valves. The Hazen-Williams formula is empirical and valid only for water at 10–30°C in turbulent flow; use Darcy-Weisbach for other fluids or low-velocity conditions. The linearisation may diverge for very poorly conditioned networks (disconnected or near-zero-flow pipes).

## References

- Rossman, L.A. (2000). *EPANET 2 Users Manual*. EPA/600/R-00/057. Chapter 3.
- Todini, E. & Pilati, S. (1988). A gradient algorithm for the analysis of pipe networks. *Computer Applications in Water Supply*, 1, 1–20.
