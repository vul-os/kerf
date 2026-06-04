# brep_check_face_developable

*Module: `kerf_cad_core.geom.face_developable_check` · Domain: cad*

## Description

Check whether a B-rep face (NURBS surface) is *developable* — i.e. can be unrolled flat without stretching (like a cylinder or cone, but NOT a sphere or torus).

A surface is developable iff its Gaussian curvature K = κ_1·κ_2 = 0 everywhere (do Carmo §3.6; Pottmann-Wallner §4).

Algorithm: sample an N×N UV grid, compute K at each point via the shape operator (second fundamental form coefficients L, M, N and first fundamental form E, F, G).  Report max|K|, mean|K|, and whether the surface is ruled (one principal curvature consistently zero).

Returns:
  is_developable          — True when max|K| < tolerance
  max_abs_K               — maximum |K| across all valid samples
  mean_abs_K              — mean |K| across valid samples
  samples_valid           — non-degenerate sample count
  ruled_direction_if_any  — 'kappa_1' or 'kappa_2' if one principal curvature is identically ~0 (ruling direction indicator); null otherwise

Oracles:
  • Cylinder R=1:  K=0 everywhere → is_developable=true
  • Sphere R=1:    K=1.0 everywhere → is_developable=false
  • Cone:          K=0 along rulings → is_developable=true
  • Torus (R,r):   K varies in sign → is_developable=false
  • Plane:         K=0 → is_developable=true

HONEST CAVEAT: sampling-based. max_abs_K is a lower bound on the true supremum of |K|. High-curvature pockets between grid points may be missed. Use samples≥20 for high-confidence results.

Never raises — returns {ok:false, reason} for invalid inputs.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "degree_u": {
      "type": "integer",
      "description": "B-spline degree in u."
    },
    "degree_v": {
      "type": "integer",
      "description": "B-spline degree in v."
    },
    "control_points": {
      "type": "array",
      "description": "Control-point grid \u2014 list of rows, each row a list of [x,y,z] points.",
      "items": {
        "type": "array",
        "items": {
          "type": "array",
          "items": {
            "type": "number"
          }
        }
      }
    },
    "knots_u": {
      "type": "array",
      "description": "Knot vector in u.",
      "items": {
        "type": "number"
      }
    },
    "knots_v": {
      "type": "array",
      "description": "Knot vector in v.",
      "items": {
        "type": "number"
      }
    },
    "weights": {
      "type": "array",
      "description": "Optional (nu\u00d7nv) weight grid (rational NURBS).",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      }
    },
    "tolerance": {
      "type": "number",
      "description": "Gaussian curvature threshold. Default 1e-3."
    },
    "samples": {
      "type": "integer",
      "description": "UV grid points per axis. Default 10. Min 2."
    }
  },
  "required": [
    "degree_u",
    "degree_v",
    "control_points",
    "knots_u",
    "knots_v"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="brep_check_face_developable",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
