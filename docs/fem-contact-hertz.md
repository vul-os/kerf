# Hertzian Contact Mechanics

> Compute contact patch size, peak pressure, and subsurface stress for sphere-on-flat and cylinder-on-flat contacts.

**Module**: `packages/kerf-fem/src/kerf_fem/contact/hertzian.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

Hertzian contact theory gives closed-form solutions for the elastic contact between smooth curved bodies. The module computes the contact half-width (or radius), peak pressure, mean pressure, and maximum subsurface von Mises stress for sphere-on-flat and cylinder-on-flat (line contact) geometries. Used for bearing design, cam-follower sizing, and gear tooth contact checks.

## How to use it

### From chat

> "Compute the Hertz contact for a 10 mm steel ball on a flat steel plate under 500 N load."

### From Python

```python
from kerf_fem.contact.hertzian import (
    HertzianContactSpec, hertzian_sphere_on_flat, hertzian_cylinder_on_flat,
)

spec = HertzianContactSpec(
    R1_mm=5.0, R2_mm=1e12,  # sphere radius; flat = infinite radius
    E1=200e9, nu1=0.3,       # sphere material (steel)
    E2=200e9, nu2=0.3,       # flat material (steel)
    F_N=500.0,               # normal force, N
)
result = hertzian_sphere_on_flat(spec)
print(result.contact_radius_mm, result.peak_pressure_mpa)
print(result.max_von_mises_subsurface_mpa, result.depth_of_max_stress_mm)
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "hertz_contact", "R_mm": 5, "E": 200e9, "nu": 0.3, "F_N": 500}}
```

## How it works

The reduced modulus `E*` and reduced radius `R*` are computed from the two body properties. For sphere-on-flat: contact radius `a = (3 F_N R* / 4 E*)^(1/3)`, peak pressure `p₀ = 3 F_N / (2π a²)`. The subsurface von Mises stress peak occurs at depth `z ≈ 0.48 a` and has magnitude ≈ `0.31 p₀`. For line contact the analogous Hertz cylinder formulas are applied.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `hertzian_sphere_on_flat(spec)` | `HertzianContactResult` | Sphere contact radius, pressure, subsurface stress |
| `hertzian_cylinder_on_flat(spec)` | `HertzianContactResult` | Cylinder (line) contact half-width and pressure |
| `HertzianContactSpec(R1_mm, R2_mm, E1, nu1, E2, nu2, F_N)` | instance | Contact geometry and load |

## Example

```python
result = hertzian_sphere_on_flat(spec)
# HertzianContactResult(contact_radius_mm=0.227, peak_pressure_mpa=14580,
#                        max_von_mises_mpa=4520, depth_of_max_stress_mm=0.109)
```

## Honest caveats

Hertzian contact assumes perfectly smooth, frictionless, linearly elastic bodies with a small contact area relative to body dimensions. It does not apply to rough surfaces, elastic-plastic contact (contact pressures exceeding ~3× yield stress), or conformal contacts (gear tooth flanks with small curvature difference). Friction (Cattaneo-Mindlin) and adhesion (JKR/DMT) are not included.

## References

- Hertz, H., "Über die Berührung fester elastischer Körper," *J. Reine Angew. Math.* 92, 1881.
- Johnson, K.L., *Contact Mechanics*, Cambridge (1985), Ch. 4.
