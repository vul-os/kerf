# Paraxial Optics and Lens Design

> ABCD ray-transfer matrix optics for sequential lens systems — compute cardinal points, Gaussian beam propagation, MTF, and depth of field without Zemax or CODE V.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/optics/lens.py`
**Shipped**: Wave 9
**LLM tools**: `optics_paraxial_design`, `optics_gaussian_beam`, `optics_mtf`

---

## What it is

Paraxial optics describes ray behaviour in the small-angle approximation (sin θ ≈ θ). Under this approximation, every optical element — thin lens, thick lens, refractive interface, free-space propagation, mirror — is represented by a 2×2 ABCD ray-transfer matrix. Complex systems are analysed by multiplying element matrices left-to-right.

This module covers: lensmaker's equation, thin/thick lens imaging, two-lens systems, ABCD matrix composition, cardinal points (focal length, principal planes, nodal points), Gaussian beam propagation, f-number, numerical aperture, depth of field, hyperfocal distance, Airy spot radius, Snell's law, critical angle, Brewster's angle, and prism deviation. All computations are pure Python + NumPy; no external optics solver is required.

## How to use it

### From chat (natural language)

> "Design a two-lens system with EFL 100mm, f/4, wavelength 633nm — what are the cardinal points?"

The LLM calls `optics_paraxial_design` and returns the cardinal-point report.

### From Python

```python
from kerf_cad_core.optics.lens import (
    thin_lens_imaging, two_lens_system, abcd_system,
    abcd_thin_lens, abcd_free_space, fnumber, depth_of_field,
)

# Cardinal points of a two-lens system
result = two_lens_system(f1=80.0, f2=200.0, d=120.0)
print(f"EFL = {result['efl_mm']:.2f} mm")

# ABCD propagation
M = abcd_system([
    abcd_free_space(d=50.0),
    abcd_thin_lens(f=100.0),
    abcd_free_space(d=150.0),
])
print(f"System matrix: {M}")

# Depth of field
dof = depth_of_field(f=50.0, N=2.8, c=0.025, s=2000.0)
print(f"DoF: {dof['total_dof_mm']:.1f} mm")
```

### From an LLM tool spec

```json
{"tool": "optics_paraxial_design", "f1_mm": 80, "f2_mm": 200, "separation_mm": 120}
```

## How it works

The ABCD matrix for a thin lens is `[[1,0],[-1/f,1]]`; for free space: `[[1,d],[0,1]]`. Cardinal points are extracted from the system matrix: EFL = -1/C where C is the lower-left element; principal plane positions follow from the off-diagonal elements. Depth of field uses the standard circle-of-confusion formula DoF ≈ 2Nc(s/f)²(1 + f/s) where c is the CoC diameter.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `lensmaker(n, R1, R2, t)` | `dict` | Thick lens focal length |
| `thin_lens_imaging(f, s_o)` | `dict` | Image distance, magnification |
| `two_lens_system(f1, f2, d)` | `dict` | Cardinal points of two-lens system |
| `abcd_system(matrices)` | `dict` | Compose ABCD matrices |
| `fnumber(f, D)` | `dict` | f-number from focal length and aperture |
| `depth_of_field(f, N, c, s)` | `dict` | Near/far DoF limits |
| `snell(n1, theta1_rad, n2)` | `dict` | Snell's law refraction angle |

## Example

```python
from kerf_cad_core.optics.lens import airy_spot_radius
spot = airy_spot_radius(wavelength=0.550e-3, N=2.0)  # mm
print(f"Airy spot radius: {spot['airy_radius_mm']:.4f} mm")
```

## Honest caveats

All results are valid only in the paraxial (small-angle) approximation. Third-order Seidel aberrations (spherical, coma, astigmatism, field curvature, distortion) are not computed by the matrix method. For aberration analysis use the skew-ray tracer (`skew_ray_tracer.py`) or the physical-optics diffraction PSF. Non-sequential stray-light analysis is a separate operation.

## References

- Saleh & Teich (2019). *Fundamentals of Photonics*, 3rd ed.
- Hecht (2016). *Optics*, 5th ed.
- ISO 10110. *Optics and photonics — Preparation of drawings for optical elements and systems.*
