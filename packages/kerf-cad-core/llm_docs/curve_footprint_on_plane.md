# nurbs_curve_project_to_plane

*Module: `kerf_cad_core.geom.curve_footprint_on_plane` · Domain: cad*

## Description

Project a 3-D NURBS curve perpendicularly onto a plane, producing a planar 2-D NURBS curve (footprint / shadow) in plane UV coordinates.

Algorithm: orthographic (linear) projection — each control point P is dropped onto the plane along the plane normal:
  P' = P − ((P−O)·n̂) n̂   (Mortenson §4.4; Piegl & Tiller §6.1)
Knots, degree and weights are preserved exactly.

Use cases: drawing-view projection, CNC engraving toolpath flattening, PV-array layout.

HONEST LIMITS: orthographic only (no perspective); for rational NURBS the footprint control-points are correct homogeneous images, but the Euclidean evaluated curve does not equal a point-by-point projection.

Returns:
  ok                  : bool
  footprint_cp        : [[u, v], ...]  — 2-D control points in plane UV frame
  knots               : [float, ...]   — unchanged knot vector
  weights             : [float, ...] | null
  degree              : int
  projection_axis     : [nx, ny, nz]   — unit normal
  max_orig_depth      : float
  is_degenerate       : bool           — true if footprint collapses to a point
  honest_caveat       : str

Errors: {ok: false, reason}.  Never raises.

## Input schema

```json
{
  "type": "object",
  "required": [
    "control_points",
    "degree",
    "plane_point",
    "plane_normal"
  ],
  "properties": {
    "control_points": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      },
      "description": "3-D control points [[x, y, z], ...] of the input curve."
    },
    "degree": {
      "type": "integer",
      "description": "Polynomial degree of the curve."
    },
    "knots": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Knot vector.  If omitted, a uniform clamped knot vector is generated automatically."
    },
    "weights": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Per-CP weights (rational NURBS).  Null / omit for non-rational."
    },
    "plane_point": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "A point on the projection plane [x, y, z] (UV-frame origin)."
    },
    "plane_normal": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Normal to the projection plane [nx, ny, nz] (need not be unit)."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="nurbs_curve_project_to_plane",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
