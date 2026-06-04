# nurbs_osculating_circle

*Module: `kerf_cad_core.geom.osculating_circle` · Domain: cad*

## Description

Compute the osculating circle of a NURBS curve at one or more parameter values (do Carmo §1.5).

The osculating circle is the unique circle that:
  * is tangent to the curve at t (same tangent line);
  * matches the curve's curvature at t.

Returns per sample:
  t             : parameter
  point         : [x,y,z] on the curve
  tangent       : unit tangent [x,y,z]
  curvature     : κ(t) ≥ 0
  radius        : 1/κ, or null when κ=0 (straight / inflection)
  center        : [x,y,z] centre of curvature, or null
  normal_plane_normal : unit normal of the osculating plane
  is_degenerate : true when κ=0 or the curve is singular at t

Inputs: NURBS curve described by degree + control_points + knots (+ optional weights for rational curves).  If `samples` is given instead of `t_values`, the curve is uniformly sampled.

Never raises — returns {ok:false, reason} for invalid inputs.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "degree": {
      "type": "integer",
      "description": "B-spline degree (>= 1)."
    },
    "control_points": {
      "type": "array",
      "description": "List of control points [[x,y,z], ...] or [[x,y], ...].",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      }
    },
    "knots": {
      "type": "array",
      "description": "Knot vector (non-decreasing, clamped).",
      "items": {
        "type": "number"
      }
    },
    "weights": {
      "type": "array",
      "description": "Optional per-control-point weights (rational NURBS).",
      "items": {
        "type": "number"
      }
    },
    "t_values": {
      "type": "array",
      "description": "Parameter values at which to evaluate (overrides `samples`).",
      "items": {
        "type": "number"
      }
    },
    "samples": {
      "type": "integer",
      "description": "Number of uniform samples when t_values not given (default 20)."
    }
  },
  "required": [
    "degree",
    "control_points",
    "knots"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="nurbs_osculating_circle",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
