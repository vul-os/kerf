# FEM Linear Static Analysis

> Compute deflections, stresses, and reactions for beams and bars under static loads — exact Euler-Bernoulli solutions for rapid sizing before full 3D FEA.

**Module**: `packages/kerf-fem/src/kerf_fem/linear_static.py`
**Shipped**: Wave 8
**LLM tools**: `fem_run`, `fem_nonlinear_bar`

---

## What it is

Linear static FEA assumes small displacements and elastic material behaviour, making the stiffness matrix constant and the load-displacement relationship linear: Ku = f. For beam and bar structures, Hermite-cubic Euler-Bernoulli elements give exact solutions for polynomial loading — meaning the element solution matches the analytical Roark formula to machine precision for cantilevers with tip loads and simply-supported beams with UDL.

This module provides 1D bar (axial), 1D Euler-Bernoulli beam (bending), and thermal stress bar solvers. Engineers use it for rapid preliminary sizing — checking tip deflection of a bracket, reaction forces at supports, thermal stress in a constrained shaft — before running a full 3D CalculiX job.

## How to use it

### From chat (natural language)

> "What is the tip deflection of a 1m steel cantilever beam with a 5kN tip load, IPE 200 section?"

The LLM calls `fem_run` (linear static) and returns the tip deflection.

### From Python

```python
from kerf_fem.linear_static import solve_beam, solve_axial_bar, solve_thermal_stress_bar

# Cantilever beam: clamped at x=0, 5kN tip load at x=1m
result = solve_beam(
    E=200e9, I=1.943e-5,  # IPE 200: I=19.43cm⁴
    L=1.0,
    supports={"0": "clamped"},
    loads={"1.0": {"P": -5000}},
    n_elem=10,
)
print(f"Tip deflection: {result['tip_deflection']*1000:.2f} mm")

# Thermal stress bar (constrained)
ts = solve_thermal_stress_bar(E=200e9, alpha=12e-6, dT=80)
print(f"Thermal stress: {ts['stress_Pa']/1e6:.1f} MPa")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "type": "beam", "E": 200e9, "I": 1.943e-5,
 "L": 1.0, "supports": {"0": "clamped"}, "loads": {"1.0": {"P": -5000}}}
```

## How it works

Hermite-cubic elements use a 4-DOF element stiffness matrix (two DOF per node: deflection and slope): Ke = (EI/L³) [[12, 6L, -12, 6L], [6L, 4L², -6L, 2L²], ...]. The global stiffness matrix is assembled, boundary conditions are enforced by row/column elimination (Dirichlet), and the system is solved by Gaussian elimination. Consistent nodal loads are used for distributed loads.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `solve_axial_bar(E, A, L, supports, loads)` | `dict` | Axial bar displacements and stresses |
| `solve_beam(E, I, L, supports, loads, n_elem)` | `dict` | Beam deflection and reactions |
| `solve_thermal_stress_bar(E, alpha, dT)` | `dict` | Thermal stress in constrained bar |

`solve_beam` returns: `tip_deflection`, `max_deflection`, `reactions`, `nodal_displacements`, `nodal_slopes`.

## Example

```python
result = solve_beam(E=70e9, I=5e-6, L=2.0,
                    supports={"0": "simply_supported", "2.0": "simply_supported"},
                    loads={"1.0": {"P": -10000}})
print(f"Max deflection: {result['max_deflection']*1000:.2f} mm")
print(f"Reactions: {result['reactions']}")
```

## Honest caveats

The pure-Python solvers cover 1D bar and Euler-Bernoulli beam problems only. Timoshenko shear deformation, torsion, and 2D/3D elements require `fem_run` dispatched to CalculiX. The beam solver requires nodes at all load and support positions. Shear-dominated short beams (L/h < 5) should use Timoshenko elements.

## References

- Roark & Young (2002). *Formulas for Stress and Strain*, 8th ed. Table 8.1.
- Hughes (2000). *The Finite Element Method*. Dover. Ch. 1–2.
