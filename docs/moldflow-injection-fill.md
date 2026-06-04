# Injection-Mould Fill Simulation (Moldflow)

> Hele-Shaw isothermal FEA fill simulation — fill-time map, weld-line detection, and short-shot prediction for injection-moulded parts.

**Module**: `packages/kerf-manufacturing/src/kerf_manufacturing/moldflow/hele_shaw.py`
**Shipped**: Wave 9
**LLM tools**: `manufacturing_moldflow`

---

## What it is

Injection-mould flow analysis tells you whether your part will fill, where weld lines will appear, and whether the injection pressure is adequate — before cutting steel. The Hele-Shaw (lubrication) approximation reduces 3D melt flow to a 2D pressure equation on the mid-plane mesh, making it fast enough for interactive design feedback.

Reach for this tool when checking a new gate location, evaluating a wall-thickness change, or comparing ABS vs PP fill behaviour on an existing design.

## How to use it

### From chat

> "Run a moldflow simulation on my bracket shell mesh, gate at node 42, 150-bar injection pressure, ABS plastic."

### From Python

```python
from kerf_manufacturing.moldflow.hele_shaw import (
    ShellMesh, GateLocation, InjectionConditions, run_moldflow
)
import numpy as np

nodes = np.array([[0,0],[0.05,0],[0.05,0.03],[0,0.03]], dtype=float)
tris  = np.array([[0,1,2],[0,2,3]], dtype=int)
mesh  = ShellMesh(nodes=nodes, triangles=tris, thickness=2e-3)
gate  = GateLocation(node_index=0, injection_pressure_pa=1.5e7)
cond  = InjectionConditions(melt_temperature_k=503.15, max_fill_time_s=3.0)
result = run_moldflow(mesh, gate, conditions=cond)
print("fill_fraction:", result.fill_fraction)
print("short_shot:", result.short_shot)
```

### From an LLM tool spec

```json
{"nodes": [[0,0],[0.05,0],[0.05,0.03],[0,0.03]],
 "triangles": [[0,1,2],[0,2,3]],
 "thickness": 0.002,
 "gate_node": 0,
 "material_name": "ABS",
 "injection_pressure_bar": 150}
```

## How it works

The Laplace pressure equation ∇·(S∇P) = 0 is assembled on the full triangulated shell mesh using linear triangle elements (constant pressure gradient per element). Fluidity S = h³/(12η) where h is local wall thickness and η is the effective viscosity from a Cross-WLF model at the given melt temperature. Boundary conditions: P = P_inject at the gate, P = 0 at far-field boundary nodes (those in the upper half of gate-distance distribution). The nodal pressure field is solved with a sparse direct solver (scipy), then mapped to fill time via t_fill = (1 − P/P_inject) × T_total. Weld lines are detected where flow-front arrival-direction vectors from neighbouring nodes are anti-parallel (angle > 135°).

## API reference

| Function / Class | Returns | Purpose |
|---|---|---|
| `run_moldflow(mesh, gate, material, conditions)` | `MoldFlowResult` | Main fill solver |
| `ShellMesh(nodes, triangles, thickness)` | `ShellMesh` | Mid-plane mesh container |
| `GateLocation(node_index, injection_pressure_pa)` | `GateLocation` | Gate spec |
| `InjectionConditions(...)` | `InjectionConditions` | Process parameters |

`MoldFlowResult` fields: `fill_time` (N,), `pressure` (N,), `weld_line_edges`, `weld_line_segments`, `short_shot`, `fill_fraction`.

## Example

```python
# Check if fill fraction drops below 95% with a thinner wall
mesh2 = ShellMesh(nodes=nodes, triangles=tris, thickness=1e-3)
r = run_moldflow(mesh2, gate)
print(f"Fill fraction: {r.fill_fraction:.1%}, short-shot: {r.short_shot}")
```

## Honest caveats

V1 is isothermal only — no energy equation, no cooling, no fibre orientation. Single gate; multi-gate requires superposition. The Cross-WLF material database has ABS, PP, PA6 only. Results are mid-plane approximations; through-thickness effects (jetting, fountain flow) are not captured. For production tooling sign-off, validate against Moldflow Insight or Moldex3D.

## References

- Hieber, C.A. & Shen, S.F. (1980). A finite-element/finite-difference simulation. *J. Non-Newtonian Fluid Mech.* 7, 1–32.
- Tadmor, Z. & Gogos, C.G. (2006). *Principles of Polymer Processing*, 2nd ed. Wiley. §12.
