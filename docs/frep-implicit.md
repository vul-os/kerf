# F-Rep Implicit Modelling (TPMS Lattices)

> Design Gyroid, Schwartz-P, and Diamond infill lattices for additive manufacturing using R-function CSG and marching-cubes mesh extraction.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/frep/sdf.py`
**Shipped**: Wave 7
**LLM tools**: `feature_frep_tpms`, `feature_frep_csg`

---

## What it is

Function-representation (F-Rep) treats solids as the zero set of a continuous scalar function f(x,y,z). Triply Periodic Minimal Surfaces (TPMS) — Gyroid, Schwartz-P, Diamond, Fischer-Koch S, IWP — are a class of F-Rep solids with near-zero mean curvature everywhere, making them excellent infill lattices: high surface area, uniform wall thickness, and smooth stress distribution.

This module provides analytic TPMS functions, R-function CSG (smooth boolean algebra), and mesh extraction via marching cubes. Engineers use it to design lightweight infill for AM parts, bone scaffolds, and heat-exchanger surfaces.

## How to use it

### From chat (natural language)

> "Generate a Gyroid lattice in a 30mm cube with 2.5mm cell size, iso=0.0"

The LLM calls `feature_frep_tpms` and returns a triangle mesh.

### From Python

```python
from kerf_cad_core.frep.sdf import (
    sdf_gyroid, sdf_schwarz_p, sdf_diamond,
    csg_union, csg_intersection, csg_difference,
    csg_smooth_union,
)
from kerf_cad_core.geom.sdf_csg import marching_cubes

# Gyroid at cell period 5mm, iso=0 (equal solid/void split)
gyroid_fn = sdf_gyroid(period=5.0, iso=0.0)
mesh = marching_cubes(
    gyroid_fn,
    bounds=((-15,-15,-15), (15,15,15)),
    resolution=64,
)
print(f"{len(mesh['faces'])} triangles")
```

### From an LLM tool spec

```json
{"tool": "feature_frep_tpms", "type": "gyroid", "cell_size_mm": 2.5,
 "bounds": [[-15,-15,-15],[15,15,15]], "resolution": 64}
```

## How it works

TPMS functions are trigonometric level sets. For the Gyroid: f(x,y,z) = sin(2πx/p)cos(2πy/p) + sin(2πy/p)cos(2πz/p) + sin(2πz/p)cos(2πx/p), where p is the cell period. The iso-surface f = C gives a surface with adjustable solid/void fraction as C varies. R-function operations (Rvachev 1963) combine F-Rep solids while preserving the function's sign semantics.

Mesh extraction uses the marching-cubes algorithm on a regular grid, evaluated over the function domain.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `sdf_gyroid(period, iso)` | `SDF` | Gyroid TPMS |
| `sdf_schwarz_p(period, iso)` | `SDF` | Schwarz-P TPMS |
| `sdf_diamond(period, iso)` | `SDF` | Diamond TPMS |
| `sdf_fischer_koch_s(period, iso)` | `SDF` | Fischer-Koch S |
| `sdf_iwp(period, iso)` | `SDF` | Schoen IWP |
| `csg_union(a, b)` | `SDF` | Boolean union |
| `csg_smooth_union(a, b, k)` | `SDF` | Smooth union |

## Example

```python
gyroid = sdf_gyroid(period=4.0, iso=0.3)  # more solid than void
diamond = sdf_diamond(period=4.0, iso=0.0)
blended = csg_smooth_union(gyroid, diamond, k=0.5)
mesh = marching_cubes(blended, bounds=((-12,-12,-12),(12,12,12)), resolution=64)
print(f"Blended lattice: {len(mesh['faces'])} triangles")
```

## Honest caveats

Isovalue 0 gives a near-equal solid/void split for Gyroid and Schwartz-P, but the exact split depends on the surface type. Mesh extraction at resolution 64 produces ~200k triangles per 30mm cube; increase to 128 for smoother results at higher polygon counts. F-Rep CSG does not maintain exact Euclidean distance; apply mesh repair before watertight BRep conversion.

## References

- Schwartz (1890). *Gesammelte Mathematische Abhandlungen*. Minimal surfaces.
- Schoen (1970). "Infinite periodic minimal surfaces without self-intersections." *NASA TN D-5541*.
- Rvachev (1963). "On analytical description of some geometric objects." *Rep. Ukr. SSR* 153.
