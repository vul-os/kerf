# SubD Cage Authoring

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/geom/subd_authoring.py` · Shipped: Wave 7 (GK-P45)*

## Overview

Provides the full set of SubD cage authoring operations: primitive creation, extrude, bevel, loop-cut, loop-slide, edge-split, crease weighting, poke, sculpt-brush, and multi-resolution displacement sculpting. Evaluation uses pure-Python Catmull-Clark subdivision; no OCC worker is required.

## When to use

- Building organic shapes (characters, ergonomic handles, packaging) via cage editing.
- Adding detail by inserting edge loops or poking faces.
- Sculpting vertices interactively with grab/smooth/inflate brushes.
- Multi-resolution displacement sculpting (ZBrush-style layered sculpt stacks).
- Retopology: snapping a cage to a high-res reference mesh.

## API

```python
from kerf_cad_core.geom.subd_authoring import (
    create_subd_primitive,
    subd_extrude, subd_bevel, subd_loop_cut,
    subd_set_crease, subd_set_bevel_weight,
    subd_poke, subd_extrude_along,
    sculpt_brush, MultiresStack,
)

# Start from a primitive
cage = create_subd_primitive("cube", w=2.0, h=2.0, d=2.0)

# Extrude a face outward
cage = subd_extrude(cage, face_id=4, offset=1.5)

# Insert a loop cut
cage = subd_loop_cut(cage, edge_id=2)

# Set a crease weight on an edge (0=smooth, 1=sharp)
cage = subd_set_crease(cage, edge_id=5, weight=0.8)

# Sculpt-grab vertices near a point
cage = sculpt_brush(cage, center=[0,0,3], radius=2.0, mode="grab",
                    direction=[0,0,1], strength=0.5)
```

## LLM tools

`feature_subd_poke`, `feature_subd_extrude_along`, `feature_sculpt_brush`, `feature_multires_evaluate`

## References

- Catmull & Clark, "Recursively Generated B-spline Surfaces on Arbitrary Topological Meshes", *CAD* 10(6), 1978.
- DeRose, Kass & Truong, "Subdivision Surfaces in Character Animation", *SIGGRAPH 1998*.

## Honest caveats

`sculpt_brush` never raises on out-of-range input; it returns an unmodified copy. `MultiresStack` displacement maps are stored as per-vertex delta lists — coarse-to-fine projection is the caller's responsibility. Loop subdivision (`loop_subdivide`) targets triangle meshes; Catmull-Clark is used for quad cages.
