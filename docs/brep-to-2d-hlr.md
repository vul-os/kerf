# BRep to 2D Hidden-Line Removal

> Project a 3D solid body to a 2D engineering view with visible and hidden lines — for drawings, DXF export, and documentation without a CAD kernel.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/drawings/brep_hlr.py`
**Shipped**: Wave 8
**LLM tools**: `feature_make2d`, `feature_drawing_view`

---

## What it is

Engineering drawings require 2D projections where edges behind surfaces are shown as hidden lines. This module tessellates a BRep Body, projects it from an arbitrary view direction, then classifies each projected edge segment as visible or hidden using a software depth-buffer (painter's algorithm). The output is SVG-ready polyline data with separate visible and hidden-line layers, matching ASME Y14.3 multi-view drawing conventions.

Standard orthographic and isometric views (front, top, right, isometric, back, left, bottom) are available as presets. The drawings module uses this path to generate all standard views on demand.

## How to use it

### From chat (natural language)

> "Generate a front and isometric view of the bracket with hidden lines shown"

The LLM calls `feature_drawing_view` with the body ID and view names.

### From Python

```python
from kerf_cad_core.drawings.brep_hlr import (
    project_brep_to_2d, make_standard_views, ProjectionView,
)

# Standard preset views
views = make_standard_views(body)
front_result = views["front"]

# Custom view direction
view = ProjectionView(direction=(1, -0.5, -0.5), up=(0, 0, 1))
result = project_brep_to_2d(body, view)

for edge in result.visible_edges:
    print(edge.start, edge.end)   # 2D coordinates (mm)
svg_path = result.to_svg()
```

### From an LLM tool spec

```json
{"tool": "feature_drawing_view", "body_id": "bracket1",
 "views": ["front", "top", "right"], "show_hidden": true}
```

## How it works

The body is tessellated into triangles using the built-in deflection-based tessellator (`linear_deflection` controls chord height). Each 3D edge is then projected along the view direction to 2D screen coordinates. Visibility is determined by a per-pixel depth buffer: for each 2D edge segment, the algorithm samples its depth against the depth buffer populated by all back-facing and front-facing triangles; segments where the sample depth is exceeded by a triangle depth are classified as hidden.

Silhouette edges (where a face transitions from front-facing to back-facing) are detected geometrically and always drawn as visible.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `project_brep_to_2d(body, view)` | `HlrResult` | Project body to 2D |
| `make_standard_views(body)` | `Dict[str, HlrResult]` | Front/top/right/iso etc. |

`HlrResult` fields: `visible_edges`, `hidden_edges`, `to_svg()`, `to_dxf_lines()`, `bbox_2d`.

## Example

```python
from kerf_cad_core.drawings.brep_hlr import make_standard_views

views = make_standard_views(my_body)
iso = views["isometric"]
print(f"{len(iso.visible_edges)} visible, {len(iso.hidden_edges)} hidden edges")
svg = iso.to_svg()
```

## Honest caveats

The depth-buffer approach can produce minor artifacts on near-coplanar surfaces. Curved silhouettes are approximated by the tessellated mesh — smaller `linear_deflection` gives smoother curves but more triangles. Performance is O(edges × triangles); complex assemblies should use a coarser tessellation for HLR. Exact OCCT HLR (`HLRBRep_Algo`) is available via the cloud rendering path and handles true silhouette curves without tessellation artifacts.

## References

- Appel (1967). "The notion of quantitative invisibility and the machine rendering of solids." *ACM* 1967.
- ASME Y14.3 — Multiview and Sectional View Drawings.
