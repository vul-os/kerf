# STOP Multiphysics Analysis (Structural-Thermal-Optical)

> Propagate thermal and structural perturbations through an optical system to predict wavefront error — for space, defence, and high-power laser systems.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/optics/stop_analysis.py`
**Shipped**: Wave 9
**LLM tools**: `optics_stop_analysis`, `optics_thermal_expansion`

---

## What it is

STOP analysis (Structural-Thermal-Optical Performance) traces how temperature changes and mechanical loads in an optical system produce surface deformations and refractive index changes that degrade wavefront quality. It is essential for space telescopes, airborne sensors, high-power laser systems, and any optic that operates in a thermally or mechanically loaded environment.

This module computes: thermal expansion displacements of optical surfaces (from ΔT and CTE), rigid-body perturbations (tip, tilt, despace, decenter) from structural loads, surface wavefront error contributions (from surface deformation mapped to Zernike polynomials), and a total wavefront error (WFE) budget. The result is a `StopReport` that engineers can use to assess whether the system meets its WFE allocation.

## How to use it

### From chat (natural language)

> "Compute the wavefront error for a 3-mirror telescope after a 10K thermal soak, CTE=1e-6/K"

The LLM calls `optics_stop_analysis` with the optical prescription and thermal load.

### From Python

```python
from kerf_cad_core.optics.stop_analysis import (
    compute_stop_perturbation, StopReport, OpticalSurface,
)

surfaces = [
    OpticalSurface(name="M1", R_mm=1000, cte=1e-6, area_m2=0.5),
    OpticalSurface(name="M2", R_mm=300,  cte=1e-6, area_m2=0.1),
]
report: StopReport = compute_stop_perturbation(
    surfaces=surfaces,
    delta_T=10.0,       # K
    wavelength_nm=633,
)
print(f"Total WFE RMS: {report.wfe_rms_waves:.4f} waves")
print(f"Dominant term: {report.dominant_zernike}")
```

### From an LLM tool spec

```json
{"tool": "optics_stop_analysis", "delta_T": 10.0, "wavelength_nm": 633,
 "surface_ids": ["M1", "M2"]}
```

## How it works

Thermal expansion produces an axial displacement `Δz = CTE × ΔT × L` and a lateral expansion of the surface clear aperture. For a mirror with radius of curvature R, an axial shift Δz produces a wavefront error contribution of Δz/R wavefronts (defocus). Rigid-body perturbations (decenter, tip/tilt) are computed from structural FEA results (or simplified load-displacement models) and mapped to Zernike aberration terms using the standard sensitivity matrix approach.

Surface figure errors are expanded in Zernike polynomials (up to order 36, Noll ordering) and the RMS WFE is computed as √(Σ cᵢ²). The total WFE budget sums all surface contributions in quadrature.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `compute_stop_perturbation(surfaces, delta_T, wavelength_nm)` | `StopReport` | Full STOP analysis |
| `thermal_expansion_displacement(surface, delta_T)` | `dict` | Axial and lateral displacement |

`StopReport` fields: `wfe_rms_waves`, `dominant_zernike`, `per_surface_wfe`, `zernike_coefficients`.

## Example

```python
rpt = compute_stop_perturbation(surfaces, delta_T=5.0, wavelength_nm=1064)
print(f"WFE = {rpt.wfe_rms_waves:.3f} λ RMS ({rpt.wfe_rms_waves*1064:.1f} nm RMS)")
```

## Honest caveats

The module uses simplified (analytic or semi-analytic) structural models — not a full FEA. For systems where structural deformation is not simply thermal expansion, provide deformation data from an external FEA solver (CalculiX, Nastran) and use `compute_stop_perturbation` with pre-computed surface displacements. Refractive index change with temperature (dn/dT) is not yet implemented; this is significant for glass elements in thermal environments.

## References

- Doyle, Genberg & Michels (2012). *Integrated Optomechanical Analysis*, 2nd ed.
- Noll (1976). "Zernike polynomials and atmospheric turbulence." *JOSA* 66(3).
