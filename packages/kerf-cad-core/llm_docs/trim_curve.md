# trim_curve

*Module: `kerf_cad_core.geom.trim_curve` · Domain: cad*

This module registers **2** LLM tool(s):

- [`query_trim_curve_uv`](#query-trim-curve-uv)
- [`validate_trim_curve`](#validate-trim-curve)

---

## `query_trim_curve_uv`

Project a 3D trim curve (given as a list of [x, y, z] points) onto the UV domain of a NURBS surface (described by its degree and control-point grid) and return the UV-space projection.  Use this to preview where a trim curve will land on a surface before committing the actual B-rep split via feature_trim_by_curve.

Returns:
  ok            : bool
  uv_samples    : list of [u, v] pairs (projected points)
  is_closed     : bool — trim curve forms a closed loop
  crosses_boundary : bool — curve can divide the face
  num_samples   : int

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "degree_u": {
      "type": "integer",
      "description": "NURBS surface degree in U direction (>= 1)."
    },
    "degree_v": {
      "type": "integer",
      "description": "NURBS surface degree in V direction (>= 1)."
    },
    "control_points": {
      "type": "array",
      "description": "Flattened list of control points as [[x,y,z], ...] in row-major order (nu*nv points).",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      }
    },
    "num_u": {
      "type": "integer",
      "description": "Number of control points in U direction."
    },
    "num_v": {
      "type": "integer",
      "description": "Number of control points in V direction."
    },
    "trim_points": {
      "type": "array",
      "description": "List of 3D points [[x,y,z], ...] defining the trim curve.",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      }
    },
    "tolerance": {
      "type": "number",
      "description": "Projection convergence tolerance (default 1e-6)."
    }
  },
  "required": [
    "degree_u",
    "degree_v",
    "control_points",
    "num_u",
    "num_v",
    "trim_points"
  ]
}
```

---

## `validate_trim_curve`

Validate a trim curve (3D polyline) against a NURBS surface.  Checks that the curve projects successfully onto the UV domain, that it crosses the face boundary (required for B-rep split), and classifies the side of a query UV point.  Returns a health report with warnings and errors — use before calling feature_trim_by_curve to catch problems early.

Returns:
  ok            : bool
  errors        : list of str (fatal)
  warnings      : list of str (non-fatal)
  num_uv_samples : int
  is_closed     : bool
  crosses_boundary : bool

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "degree_u": {
      "type": "integer"
    },
    "degree_v": {
      "type": "integer"
    },
    "control_points": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      }
    },
    "num_u": {
      "type": "integer"
    },
    "num_v": {
      "type": "integer"
    },
    "trim_points": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      }
    },
    "tolerance": {
      "type": "number"
    },
    "keep_side": {
      "type": "string",
      "enum": [
        "positive",
        "negative"
      ]
    }
  },
  "required": [
    "degree_u",
    "degree_v",
    "control_points",
    "num_u",
    "num_v",
    "trim_points"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
