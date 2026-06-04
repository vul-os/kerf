# Conjugate Heat Transfer

> Solve coupled fluid-solid thermal problems — convective cooling, electronic thermal management, and heat-exchanger fin efficiency — with iterative fluid-solid temperature coupling.

**Module**: `packages/kerf-cfd/src/kerf_cfd/conjugate_ht/conjugate_solver.py`
**Shipped**: Wave 10
**LLM tools**: `cfd_conjugate_ht`

---

## What it is

Conjugate heat transfer (CHT) couples the temperature fields of a fluid and a solid that are in thermal contact. Unlike standard CFD (which prescribes a wall temperature or heat flux), CHT solves both domains simultaneously, with the interface temperature determined by the heat-flux continuity condition: q_fluid = h(T_fluid - T_wall) = -k_solid ∇T_solid · n̂.

This is critical for electronic cooling (junction temperatures depend on both convective resistance and substrate conduction), turbine blade internal cooling channels, and heat-exchanger efficiency. This module provides an iterative staggered solver: the fluid domain computes heat transfer coefficients h at the interface; the solid domain solves the conduction equation with those boundary conditions; then h is updated from the new solid temperatures.

## How to use it

### From chat (natural language)

> "Compute the steady-state junction temperature of a 10W chip cooled by forced convection at 5 m/s, substrate k=150 W/m·K"

The LLM calls `cfd_conjugate_ht` with the geometry and boundary conditions.

### From Python

```python
from kerf_cfd.conjugate_ht.conjugate_solver import (
    FluidSolidInterface, couple_fluid_solid_temperature,
    heat_flux_at_interface,
)

interface = FluidSolidInterface(
    area_m2=0.01,
    h_fluid=500.0,        # W/m²·K convection coefficient
    k_solid=150.0,        # W/m·K thermal conductivity
    L_solid=0.003,        # solid thickness (m)
    T_fluid_bulk=300.0,
    Q_source=10.0,        # W heat generation in solid
)
result = couple_fluid_solid_temperature(interface, n_iter=100)
print(f"Wall temperature: {result['T_wall_K']:.1f} K")
print(f"Solid hot-spot: {result['T_solid_max_K']:.1f} K")
```

### From an LLM tool spec

```json
{"tool": "cfd_conjugate_ht", "h_W_m2K": 500, "k_solid_W_mK": 150,
 "thickness_m": 0.003, "T_fluid_K": 300, "Q_W": 10}
```

## How it works

At the fluid-solid interface, energy conservation requires: h(T_fluid - T_wall) = k_solid (T_wall - T_solid_back) / L_solid. This is solved iteratively: (1) initialise T_wall = T_fluid; (2) solve solid conduction with Dirichlet T_wall BC; (3) update h from the new fluid-side solution; (4) compute new T_wall from interface heat-flux continuity; (5) repeat until convergence. Convergence is assessed by the relative change in T_wall.

`heat_flux_at_interface` computes the local heat flux q = h(T_fluid - T_wall) for output or post-processing.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `couple_fluid_solid_temperature(interface, n_iter)` | `dict` | Iterative CHT solver |
| `heat_flux_at_interface(T_fluid_face, T_solid_face, h)` | `float` | Interface heat flux W/m² |

`FluidSolidInterface` fields: `area_m2`, `h_fluid`, `k_solid`, `L_solid`, `T_fluid_bulk`, `Q_source`.

## Example

```python
flux = heat_flux_at_interface(T_fluid_face=320.0, T_solid_face=340.0, h=500.0)
print(f"Interface heat flux: {flux:.1f} W/m²")  # negative = into solid
```

## Honest caveats

This module solves a simplified 1D conjugate problem (lumped solid). For 3D CHT with complex geometries, use OpenFOAM `chtMultiRegionFoam`. The convective coefficient h must be supplied externally (from a CFD simulation or Nusselt number correlation) — this module does not compute h from first principles. Radiation is not included.

## References

- Incropera, Dewitt, Bergman & Lavine (2011). *Fundamentals of Heat and Mass Transfer*, 7th ed. Wiley.
- Patankar (1980). *Numerical Heat Transfer and Fluid Flow*. McGraw-Hill.
