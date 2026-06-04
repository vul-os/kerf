# nurbs_surface_offset_robust

*Module: `kerf_cad_core.geom.offset_far_correction` · Domain: cad*

## Description

Offset a NURBS surface by a signed distance with full curvature-aware fold prevention. Unlike the basic surface_offset tool, this handles large offset distances (> 0.5 × min_curvature_radius) where the naive Tiller-Hanson displacement produces folded or inverted surfaces.

Algorithm (Maekawa 1999 §6; Hoschek-Lasser 1993 §17):
1. Samples a curvature grid over the surface to find the global minimum    curvature radius R_min.
2. If |distance| ≤ 0.95 * R_min, the standard analytic or Tiller-Hanson    offset is used (exact for spheres/planes).
3. If |distance| > 0.95 * R_min, each control point's displacement is    clamped to the local safe limit — producing a fold-free approximation    and flagging the unsafe parametric regions.

Returns:
  ok           : bool
  is_fully_safe: bool — True when the full offset is geometrically valid
  safe_distance: float — maximum safe offset distance (0.95 × R_min)
  R_min        : float — minimum curvature radius over the surface
  unsafe_regions: list of {u_lo, u_hi, v_lo, v_hi} problem rectangles
  offset_surface: {degree_u, degree_v, control_points, num_u, num_v,                    knots_u, knots_v, weights} — the offset NurbsSurface

## Input schema

```json
{
  "type": "object",
  "properties": {
    "distance": {
      "type": "number",
      "description": "Signed offset distance. Positive = outward (positive normal)."
    },
    "degree_u": {
      "type": "integer",
      "description": "Surface degree in U."
    },
    "degree_v": {
      "type": "integer",
      "description": "Surface degree in V."
    },
    "control_points": {
      "type": "array",
      "description": "Flattened nu\u00d7nv control points as [[x,y,z], \u2026] (row-major, U outer / V inner).",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      }
    },
    "num_u": {
      "type": "integer",
      "description": "Number of control points in U."
    },
    "num_v": {
      "type": "integer",
      "description": "Number of control points in V."
    },
    "knots_u": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Knot vector in U (length = num_u + degree_u + 1). Omit to use an open-uniform knot vector."
    },
    "knots_v": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Knot vector in V. Omit for open-uniform."
    },
    "weights": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Rational weights as a flattened nu\u00d7nv array. Omit for non-rational (uniform weights = 1)."
    }
  },
  "required": [
    "distance",
    "degree_u",
    "degree_v",
    "control_points",
    "num_u",
    "num_v"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="nurbs_surface_offset_robust",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
