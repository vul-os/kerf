# SubD Cage to NURBS Body

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/geom/subd_to_nurbs.py` · Shipped: Wave 7 (GK-P12/P13)*

## Overview

Converts a quad-mesh SubD cage to a watertight NURBS Body using Catmull-Clark-derived Stam limit positions and tangent estimation. One bicubic NURBS patch is produced per quad face; patches are sewn into a closed shell. Extraordinary vertices (valence other than 4) are handled via the closed-form Stam (1998) limit formula, so the conversion is valid for any valence.

## When to use

- Converting organic SubD shapes to NURBS for downstream STEP export or machining.
- Generating a water-tight BRep from a sculpted cage for FEA meshing.
- Checking volume or mass properties on a subdivided mesh.

## API

```python
from kerf_cad_core.geom.subd_to_nurbs import (
    subd_cage_to_nurbs_body,
    subd_cage_to_nurbs_patches,
    subd_cage_to_limit_nurbs_body,
    subd_limit_positions,
)

# Convert cage to watertight NURBS body
body = subd_cage_to_nurbs_body(cage, tol=1e-6)

# Limit-surface variant (Stam limit positions at cage verts)
body = subd_cage_to_limit_nurbs_body(cage, tol=1e-6, sew_tol=1e-5)

# Just the per-face patches, without topology
patches = subd_cage_to_nurbs_patches(cage, tol=1e-6)

# Stam limit positions for all cage vertices
lim_pts = subd_limit_positions(cage)
```

## LLM tools

`feature_subd_to_nurbs`, `feature_subd_limit_convert`

## References

- Stam, "Exact Evaluation of Catmull-Clark Subdivision Surfaces at Arbitrary Parameter Values", *SIGGRAPH 1998*.
- Catmull & Clark, "Recursively Generated B-spline Surfaces on Arbitrary Topological Meshes", *CAD* 10(6), 1978.

## Honest caveats

G1 continuity across shared edges at extraordinary vertices is enforced (GK-P13) but G2 curvature continuity is not guaranteed at extraordinary points. For engineering-grade fillets, convert the cage to NURBS and then use `match_surface_edge` to enforce G2 locally.
