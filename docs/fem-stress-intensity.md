# Stress Intensity Factors

> Extract mode-I, II, III stress intensity factors from FEM displacement fields using the displacement correlation method.

**Module**: `packages/kerf-fem/src/kerf_fem/fracture/stress_intensity.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

Stress Intensity Factors (SIF) K_I, K_II, K_III characterise the amplitude of the crack-tip stress singularity in linear elastic fracture mechanics (LEFM). This module extracts SIFs from FEM displacement fields using the displacement correlation (DC) method and estimates fracture toughness from load-displacement test data.

## How to use it

### From chat

> "Compute K_I from my FEM displacement field for a centre-cracked panel with a = 10 mm."

### From Python

```python
from kerf_fem.fracture.stress_intensity import (
    stress_intensity_from_displacement, fracture_toughness_from_load, k_to_j,
)

K_I = stress_intensity_from_displacement(
    crack_tip_node=1024,
    crack_face_nodes=[1023, 1025, 1020, 1026],  # nodes near crack tip
    displacements=u,          # (N, 2) displacement array
    E=200e9, nu=0.3,
    condition="plane_strain",
    r_extract=0.001,          # extraction radius, m
)
print(f"K_I = {K_I/1e6:.2f} MPa√m")

K_c = fracture_toughness_from_load(
    P_N=45000, B_m=0.025, W_m=0.05, a_m=0.025,
    specimen="CT",
)
print(f"K_Ic = {K_c/1e6:.1f} MPa√m")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "stress_intensity", "specimen": "CT", "P_N": 45000, "a_m": 0.025}}
```

## How it works

The displacement correlation method extracts K_I from the crack-opening displacement (COD) of nodes near the crack tip: `K_I = (E* / 4) √(2π/r) × (u_upper − u_lower)` where `r` is the distance from the crack tip, and `E*` is the plane-strain or plane-stress effective modulus. Quarter-point singular elements improve accuracy by placing nodes at `1/4` the element length from the crack tip. `fracture_toughness_from_load` uses ASTM E399 formulas for CT and SENB specimens.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `stress_intensity_from_displacement(...)` | `float` | K_I from FEM displacements |
| `fracture_toughness_from_load(P_N, B_m, W_m, a_m, specimen)` | `float` | K_Ic from test load (CT or SENB) |
| `k_to_j(K_I, E, nu, condition)` | `float` | Convert K_I to J-integral |

## Example

```python
K_Ic = fracture_toughness_from_load(45000, 0.025, 0.05, 0.025, "CT")
# 72.4 MPa√m — within range for structural steel
```

## Honest caveats

The displacement correlation method is sensitive to mesh refinement at the crack tip; refine to at least r ≈ 0.01a before extraction. Quarter-point singular elements are not automatically generated; they must be created in the mesh. K_I extraction assumes mode-I dominance; if the crack is not symmetrically loaded, K_II contributions will contaminate the result. ASTM E399 validity checks (specimen size, linearity) are not verified automatically.

## References

- ASTM E399-22, *Standard Test Method for Linear-Elastic Plane-Strain Fracture Toughness*.
- Anderson, *Fracture Mechanics*, 4th ed. (2017), Ch. 2.
