# AC Load Flow (Power Systems)

> Newton-Raphson AC power-flow solver for balanced three-phase electrical networks — nodal voltages, real/reactive power, and line loadings.

**Module**: `packages/kerf-electronics/src/kerf_electronics/tools/` (power flow via kerf-plc integration)
**Shipped**: Wave 11B3
**LLM tools**: `power_ac_load_flow`

---

## What it is

AC load flow (power flow) is the fundamental steady-state calculation for electrical power systems: given generation (PV/PQ buses) and demand (PQ buses), find the complex bus voltages and real/reactive power flows on all branches. It is used for network capacity planning, congestion analysis, and protection coordination. Kerf implements a Newton-Raphson polar-form solver, the standard method in power system analysis tools (PSS/E, PowerWorld, OpenDSS).

## How to use it

### From chat

> "Solve AC load flow for a 5-bus network: bus 1 is the slack at 1.05 pu, bus 2 is a 100 MW PV generator, buses 3-5 are loads. Are any branch loadings above 80%?"

### From Python

```python
from kerf_electronics.tools.sim import run_ac_load_flow

buses = [
    {"id": 1, "type": "slack", "v_pu": 1.05, "angle_deg": 0},
    {"id": 2, "type": "PV", "p_mw": 100, "v_pu": 1.02},
    {"id": 3, "type": "PQ", "p_mw": -60, "q_mvar": -20},
    {"id": 4, "type": "PQ", "p_mw": -40, "q_mvar": -15},
]
branches = [
    {"from": 1, "to": 2, "r_pu": 0.02, "x_pu": 0.06, "rating_mva": 200},
    {"from": 1, "to": 3, "r_pu": 0.04, "x_pu": 0.12, "rating_mva": 100},
    {"from": 2, "to": 4, "r_pu": 0.01, "x_pu": 0.05, "rating_mva": 150},
]
result = run_ac_load_flow(buses, branches, base_mva=100)
for b in result["buses"]:
    print(f"Bus {b['id']}: V = {b['v_pu']:.4f} pu, δ = {b['angle_deg']:.2f}°")
```

### From an LLM tool spec

```json
{"buses": [{"id":1,"type":"slack","v_pu":1.05}],
 "branches": [{"from":1,"to":2,"r_pu":0.02,"x_pu":0.06}],
 "base_mva": 100}
```

## How it works

The Newton-Raphson method formulates the power-flow equations as F(θ, |V|) = 0 where F contains the mismatch between specified and calculated real/reactive power at each bus. The Jacobian matrix is built in polar form (2×2 blocks per bus pair with non-zero admittance). The linearised system J·Δx = −F is solved at each iteration using a sparse LU factorisation. Convergence typically requires 3–6 iterations for well-conditioned networks. Bus voltages are reported in per-unit; branch flows in MW/MVAR and as a percentage of thermal rating.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `run_ac_load_flow(buses, branches, base_mva, tol, max_iter)` | `dict` | Full NR power-flow |

Returns: `{"converged": bool, "iterations": int, "buses": [...], "branches": [...]}`. Each bus: `v_pu`, `angle_deg`, `p_mw`, `q_mvar`. Each branch: `p_from_mw`, `q_from_mvar`, `loading_pct`.

## Example

```python
r = run_ac_load_flow(buses, branches, base_mva=100)
overloaded = [b for b in r["branches"] if b["loading_pct"] > 80]
print("Overloaded branches:", overloaded)
```

## Honest caveats

This is a balanced three-phase positive-sequence solver; unbalanced networks (distribution systems with single-phase loads) require a full three-phase formulation not implemented here. No OPF (optimal power flow) or economic dispatch. The Jacobian build is dense — networks larger than ~500 buses will be slow in pure Python; use a compiled solver (MATPOWER, pandapower) for large transmission networks.

## References

- Glover, J.D., Sarma, M.S. & Overbye, T.J. (2012). *Power Systems Analysis and Design*, 5th ed. Cengage. §6 (power flow).
- Tinney, W.F. & Hart, C.E. (1967). Power flow solution by Newton's method. *IEEE Trans. PAS* 86(11), 1449–1460.
