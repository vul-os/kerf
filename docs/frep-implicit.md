# F-Rep Implicit Modelling

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/frep/` · Shipped: Wave 7*

## Overview

Function-representation (F-Rep) implicit solid modelling: R-function CSG (R-union, R-intersection, R-difference) with smooth blending, TPMS (Triply Periodic Minimal Surface) lattice generation (Gyroid, Schwartz-P, Diamond, Lidinoid), and implicit-to-mesh extraction via marching cubes. Used for designing lightweight infill lattices and topology-optimised bio-inspired structures.

## When to use

- Designing Gyroid or Schwartz-P infill lattices for additive manufacturing.
- Creating smooth blend primitives using R-function algebra.
- Generating heterogeneous density lattices for bone-scaffold or heat-exchanger applications.

## API

```python
from kerf_cad_core.frep.tpms import (
    gyroid, schwartz_p, diamond, lidinoid,
    tpms_to_mesh,
)

# Generate a Gyroid lattice in a 30mm cube, 2.5mm cell size
mesh = tpms_to_mesh(
    tpms_fn=gyroid,
    bounds=((-15,-15,-15), (15,15,15)),
    cell_size_mm=2.5,
    resolution=64,
    isovalue=0.0,
    wall_thickness=0.5,
)
```

## LLM tools

`feature_frep_tpms`, `feature_frep_csg`

## References

- Schwartz, "Gesammelte Mathematische Abhandlungen" (1890) — minimal surfaces.
- Schoen, "Infinite periodic minimal surfaces without self-intersections", *NASA TN D-5541*, 1970.
- Rvachev, "On analytical description of some geometric objects", *Rep. Ukr. SSR* 153, 1963 (R-functions).

## Honest caveats

TPMS isovalue selection controls the solid/void balance: isovalue = 0 produces an equal-volume split for Gyroid and Schwartz-P, but this varies by surface type. Mesh extraction via marching cubes at resolution 64 produces approximately 200k triangles per 30mm cube; increase to 128 for smoother results at the cost of higher polygon count. The F-Rep CSG does not produce exact-distance SDFs; apply `mesh_repair` before downstream operations requiring watertight meshes.
