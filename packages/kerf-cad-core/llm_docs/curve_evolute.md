# nurbs_compute_curve_evolute

*Module: `kerf_cad_core.geom.curve_evolute` · Domain: cad*

## Description

Compute the evolute E(t) of a 2D NURBS curve C(t).

The evolute is the locus of centres of osculating circles:
  E(t) = C(t) + n̂(t) / κ(t)
where n̂ is the unit left-hand normal and κ is the curvature.

Applications: cycloidal-gear design, cam-profile cusp analysis, CNC offset self-intersection prediction.

Returns:
  evolute_points      : [[x,y], ...] evolute sample coordinates
  t_params            : parameter values for each evolute point
  num_samples         : total samples taken
  num_cusps_detected  : number of cusp-like extrema found
  cusp_t_params       : t values at detected cusps
  honest_caveat       : scope and accuracy caveats

HONEST: 2D only.  3D Frenet-Serret evolutes not yet supported.
Samples where |κ| < min_curvature are skipped (evolute → ∞).
Never raises — returns {ok:false, reason} for invalid inputs.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "degree": {
      "type": "integer",
      "description": "B-spline degree (>= 1; degree 2+ needed for curvature)."
    },
    "control_points": {
      "type": "array",
      "description": "List of 2D control points [[x,y], ...] or [[x,y,z], ...] (z components are ignored for the 2D evolute).",
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
    "num_samples": {
      "type": "integer",
      "description": "Number of uniform parameter samples (default 200)."
    },
    "min_curvature": {
      "type": "number",
      "description": "Samples with |\u03ba| < min_curvature are skipped (evolute diverges). Default 1e-6."
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
    tool_name="nurbs_compute_curve_evolute",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
