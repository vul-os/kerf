# Caustic Solver

> Render focal caustic patterns cast by refractive geometry — for optical verification of lens and concentrator designs.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/optics/caustic_solver.py`
**Shipped**: Wave 9
**LLM tools**: `optics_caustic_render`

---

## What it is

Caustics are the bright patterns of concentrated light formed when rays refract or reflect through curved surfaces — the shimmer of light at the bottom of a swimming pool, or the bright rings inside a wine glass. In optical engineering, caustic analysis reveals whether a concentrating lens or solar collector delivers uniform illumination or has hot-spots, and helps verify the focal quality of a custom refractive element.

This module computes caustic patterns by tracing a dense grid of rays through or off a surface and accumulating their intersections with a receiver plane. The result is a `CausticPattern` image (n×n float array, units of W/m²) representing the irradiance distribution at the receiver.

## How to use it

### From chat (natural language)

> "Render the caustic pattern of a plano-convex BK7 lens (R=50mm, diameter=25mm) at 200mm behind the lens"

The LLM calls `optics_caustic_render` with the lens geometry and receiver plane.

### From Python

```python
from kerf_cad_core.optics.caustic_solver import render_caustic, CausticPattern

pattern: CausticPattern = render_caustic(
    surface=lens_surface,    # NurbsSurface or analytic conic
    n_rays=200,              # grid dimension (200×200 = 40k rays)
    receiver_z=200.0,        # receiver plane distance (mm)
    n1=1.0, n2=1.517,       # incident and transmitted n
    illumination="parallel", # "parallel" | "point" | "solar"
)

print(f"Peak irradiance: {pattern.peak_irradiance:.2f} W/m²")
print(f"Concentration ratio: {pattern.concentration_ratio:.2f}x")
```

### From an LLM tool spec

```json
{"tool": "optics_caustic_render", "surface_id": "lens1",
 "n_rays": 200, "receiver_z_mm": 200, "n1": 1.0, "n2": 1.517}
```

## How it works

A uniform grid of `n_rays × n_rays` parallel rays is launched along the optical axis (or from a point source). Each ray is intersected with the optical surface using Newton-Raphson iteration on the surface implicit equation. The refracted direction is computed from Snell's law in vector form: `n1 * (d × n̂) = n2 * (d' × n̂)`, where `n̂` is the surface normal. The refracted ray is propagated to the receiver plane and its irradiance contribution is accumulated in a 2D histogram.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `render_caustic(surface, n_rays, receiver_z, n1, n2, illumination)` | `CausticPattern` | Main caustic renderer |

`CausticPattern` fields: `irradiance` (n×n array, W/m²), `peak_irradiance`, `total_power`, `concentration_ratio`, `centroid_mm`.

## Example

```python
pattern = render_caustic(plano_convex_surf, n_rays=100, receiver_z=150.0,
                          n1=1.0, n2=1.517)
print(f"Concentration: {pattern.concentration_ratio:.1f}x at z=150mm")
```

## Honest caveats

This is a geometric optics caustic solver — it does not account for diffraction or interference. The receiver irradiance map assumes infinitesimally thin rays; for finite aperture effects use the photon-map module. Near the paraxial focus, the geometric ray density diverges and the caustic image will show unphysical spikes; use a finite extent receiver grid to avoid this.

## References

- Stavroudis (1972). *The Optics of Rays, Wavefronts, and Caustics*. Academic Press.
- Born & Wolf (1999). *Principles of Optics*, 7th ed. §3.3.
