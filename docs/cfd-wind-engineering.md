# Wind Engineering and Structural Wind Loads

> Compute mean wind pressure coefficients, vortex-shedding frequencies, and galloping stability for buildings and bluff bodies per EN 1991-1-4 and ASCE 7.

**Module**: `packages/kerf-cfd/src/kerf_cfd/wind_engineering/wind_tunnel.py`
**Shipped**: Wave 10
**LLM tools**: `cfd_wind_load`

---

## What it is

Wind engineering predicts the aerodynamic forces on buildings, bridges, and structures. For preliminary design, empirical methods from EN 1991-1-4 (Eurocode) and ASCE 7 give conservative but reliable estimates of mean wind pressure. For detailed analysis, CFD simulations with a turbulent atmospheric boundary layer profile give force distributions across the full structure.

This module provides: atmospheric wind profiles (log-law and power-law), building geometry specification, pressure coefficient computation from empirical correlations, Strouhal number-based vortex-shedding frequency estimation, and galloping critical velocity prediction using the Den Hartog criterion. Engineers use it for preliminary structural wind load calculations, fatigue assessment of chimneys and masts, and input to structural analysis.

## How to use it

### From chat (natural language)

> "Calculate the mean wind pressure on a 40m office tower at reference wind speed 30 m/s, terrain category II"

The LLM calls `cfd_wind_load` with the building geometry and site conditions.

### From Python

```python
from kerf_cfd.wind_engineering.wind_tunnel import (
    WindProfile, BuildingGeometry, compute_wind_load_aerodynamic,
    vortex_shedding_frequency, galloping_critical_velocity,
)

profile = WindProfile(
    z_ref=10.0, U_ref=30.0,
    roughness_category="II",   # open country
    profile_type="log_law",
)
building = BuildingGeometry(
    width=20.0, depth=20.0, height=40.0,
    cross_section="rectangular",
)
report = compute_wind_load_aerodynamic(profile, building)
print(f"Max windward pressure: {report.max_windward_pressure_kPa:.2f} kPa")

f_vs = vortex_shedding_frequency(U=30.0, D=20.0, St=0.2)
print(f"Vortex shedding frequency: {f_vs:.3f} Hz")
```

### From an LLM tool spec

```json
{"tool": "cfd_wind_load", "height_m": 40, "width_m": 20,
 "U_ref_m_s": 30, "terrain_category": "II"}
```

## How it works

The wind velocity at height z is computed from the log-law profile: U(z) = (u*/κ) ln(z/z₀), where z₀ is the roughness length for the terrain category and κ=0.41 is the von Kármán constant. Mean pressure coefficients Cp are computed from empirical correlations for rectangular buildings (positive on windward, negative on leeward and sides, with peak suctions at leading edges).

Vortex shedding frequency: f = St × U / D, where St is the Strouhal number (≈ 0.2 for rectangular sections). Galloping critical velocity uses Den Hartog's criterion: U_gall = 4mξωn / (ρ D (-dCL/dα|α=0)).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `compute_wind_load_aerodynamic(profile, building)` | `WindPressureReport` | Mean wind pressure map |
| `vortex_shedding_frequency(U, D, St)` | `float` | Strouhal vortex-shedding frequency |
| `galloping_critical_velocity(m, xi, omega_n, rho, D, dCL_da)` | `float` | Den Hartog galloping velocity |

`WindPressureReport` fields: `max_windward_pressure_kPa`, `max_suction_kPa`, `base_shear_kN`, `overturning_moment_kNm`.

## Example

```python
f_vs = vortex_shedding_frequency(U=25.0, D=1.0, St=0.2)
print(f"Chimney vortex shedding: {f_vs:.2f} Hz")
# If this matches the natural frequency → resonance risk
```

## Honest caveats

Empirical pressure coefficients are for standard rectangular/circular cross-sections in uniform flow — complex geometries, terrain shielding, and turbulence intensity effects require CFD or wind-tunnel testing. The galloping model assumes 2D Den Hartog instability; across-wind instability of slender structures requires full aeroelastic analysis. For code-compliant wind loads on buildings, use the full EN 1991-1-4 or ASCE 7 procedure.

## References

- EN 1991-1-4:2005. *Eurocode 1: Actions on structures — Part 1-4: Wind actions*. CEN.
- ASCE 7-22. *Minimum Design Loads and Associated Criteria for Buildings and Other Structures*. ASCE.
- Den Hartog (1934). "Mechanical vibrations." McGraw-Hill. §7.
