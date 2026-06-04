# scan_fit_nurbs_surface

*Module: `kerf_cad_core.scan.nurbs_fit_tools` · Domain: cad*

## Description

Fit a NURBS B-spline surface to a freeform point cluster from a scan_segment result (the non-primitive / organic-shape branch).

Algorithm:
  1. Centripetal parameterisation (robust for noisy, irregular clouds).
  2. Knot-vector placement via the averaging method (Piegl & Tiller §9.2.2).
  3. Damped linear least-squares:
       min ||N·P - Q||² + λ·||D·P||²
     where N is the tensor-product basis matrix and D is a second-difference smoothness operator.

Input: a list of [x, y, z] points (the freeform cluster). At least (u_degree+1)*(v_degree+1) points are required.

Output: {ok, primitive:'nurbs_surface', degree_u, degree_v, n_ctrl_u, n_ctrl_v, rms_residual, max_residual, condition_number, control_points:[[[x,y,z],...]], knots_u:[...], knots_v:[...]}.

Errors: {ok:false, reason} for degenerate/insufficient input. Never raises.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "points": {
      "type": "array",
      "description": "List of 3-D points as [[x,y,z], ...]. Minimum (u_degree+1)*(v_degree+1) points required.",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 3,
        "maxItems": 3
      }
    },
    "u_degree": {
      "type": "integer",
      "description": "B-spline degree in the U direction (1\u20137). Cubic (3) is standard. Default 3."
    },
    "v_degree": {
      "type": "integer",
      "description": "B-spline degree in the V direction. Default 3."
    },
    "n_u_ctrl": {
      "type": "integer",
      "description": "Number of control points in U. Must be >= u_degree+1. Default 8."
    },
    "n_v_ctrl": {
      "type": "integer",
      "description": "Number of control points in V. Default 8."
    },
    "lambda_smooth": {
      "type": "number",
      "description": "Smoothness regularisation weight (>= 0). Higher values produce smoother but less accurate surfaces. Default 1e-3."
    }
  },
  "required": [
    "points"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="scan_fit_nurbs_surface",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
