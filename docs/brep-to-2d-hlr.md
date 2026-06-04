# BRep to 2D Hidden-Line Removal

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/geom/make2d.py` · Shipped: Wave 8*

## Overview

Projects a triangulated BRep or mesh from an arbitrary camera direction and classifies each edge segment as visible or hidden using a depth-buffer painter's algorithm. Produces SVG-ready 2D polyline output with separate visible and hidden-line layers. Used by the drawings module to generate standard views (front, top, right, isometric).

## When to use

- Generating engineering drawings with hidden-line views from a 3D model.
- Exporting 2D DXF / SVG projections for documentation.
- Checking what features are visible from a specific direction before rendering.

## API

```python
from kerf_cad_core.geom.make2d import (
    Make2DInput, ViewParams, Make2DResult,
    make2d, standard_views, make2d_from_brep,
)

# Standard views dict: "front", "top", "right", "isometric", etc.
views = standard_views()
view  = views["front"]

# Project a mesh
inp = Make2DInput(vertices=verts, triangles=tris)
result: Make2DResult = make2d(inp, view)

for seg in result.visible_segments:
    x0, y0, x1, y1 = seg  # projected 2D coordinates

# Convenience: project directly from a BRep Body
result = make2d_from_brep(body, view, linear_deflection=0.01)
```

## LLM tools

`feature_make2d`, `feature_drawing_view`

## References

- Appel, "The notion of quantitative invisibility and the machine rendering of solids", *ACM 1967*.
- Standard view projections per ASME Y14.3 (multi-view drawing).

## Honest caveats

Visibility classification uses a software depth buffer (painter's algorithm) and can produce minor artifacts on near-coplanar surfaces. Curve silhouettes are approximated by the tessellated edge mesh — curved silhouettes will show faceting proportional to the tessellation density. Performance scales as O(edges × triangles); complex assemblies should be tessellated at coarser deflection for HLR.
