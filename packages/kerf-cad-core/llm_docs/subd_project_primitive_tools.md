# subd_project_primitive_tools

*Module: `kerf_cad_core.geom.subd_project_primitive_tools` · Domain: cad*

This module registers **3** LLM tool(s):

- [`subd_project_cage_to_sphere`](#subd-project-cage-to-sphere)
- [`subd_project_cage_to_cylinder`](#subd-project-cage-to-cylinder)
- [`subd_project_cage_to_plane`](#subd-project-cage-to-plane)

---

## `subd_project_cage_to_sphere`

Project every vertex of a SubD control cage onto a sphere surface.

For each cage vertex **v**, the new position is:
  v' = center + radius * (v - center) / |v - center|

Vertices coincident with the center are left unchanged.

**Use case**: clean up a coarse cage that approximates a sphere (e.g. a unit-cube cage) so that all control points sit exactly on the analytic sphere before Catmull-Clark subdivision.  Two levels of subdivision on the projected cage produce a limit surface whose deviation from the true sphere is dramatically smaller than the pre-projection approximation.

**Honest flag**: face areas and edge lengths are NOT preserved — only vertex positions are snapped.  The report includes `max_projection_distance` (maximum vertex displacement) and `mean_projection_distance`.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "vertices": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 3,
        "maxItems": 3
      },
      "description": "List of [x, y, z] cage vertex coordinates."
    },
    "faces": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "integer"
        }
      },
      "description": "List of face vertex-index lists (quads or polygons)."
    },
    "center": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 3,
      "maxItems": 3,
      "description": "Sphere center [cx, cy, cz]. Default [0, 0, 0]."
    },
    "radius": {
      "type": "number",
      "description": "Sphere radius (positive). Default 1.0."
    }
  },
  "required": [
    "vertices",
    "faces"
  ]
}
```

---

## `subd_project_cage_to_cylinder`

Project every vertex of a SubD control cage onto an infinite right-circular cylinder surface.

Algorithm per vertex:
  1. Project vertex onto the axis line to find the foot point.
  2. Compute the radial vector (perpendicular to axis).
  3. Scale the radial vector to `radius`.
  4. New position = foot + scaled radial.

Vertices on the axis (radial magnitude < 1e-12) are left unchanged.
The cylinder is infinite — no height capping.

**Honest flag**: face areas and edge lengths are NOT preserved — only vertex positions are snapped.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "vertices": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 3,
        "maxItems": 3
      },
      "description": "List of [x, y, z] cage vertex coordinates."
    },
    "faces": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "integer"
        }
      },
      "description": "List of face vertex-index lists."
    },
    "axis_origin": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 3,
      "maxItems": 3,
      "description": "A point on the cylinder axis [ox, oy, oz]. Default [0, 0, 0]."
    },
    "axis_direction": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 3,
      "maxItems": 3,
      "description": "Direction vector of the cylinder axis [dx, dy, dz]. Default [0, 0, 1]."
    },
    "radius": {
      "type": "number",
      "description": "Cylinder radius (positive). Default 1.0."
    }
  },
  "required": [
    "vertices",
    "faces"
  ]
}
```

---

## `subd_project_cage_to_plane`

Project every vertex of a SubD control cage onto a plane.

Formula: p' = p - dot(p - origin, n_hat) * n_hat

If the normal vector is zero, the cage is returned unchanged.

**Honest flag**: face areas and edge lengths are NOT preserved — only vertex positions are snapped.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "vertices": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 3,
        "maxItems": 3
      },
      "description": "List of [x, y, z] cage vertex coordinates."
    },
    "faces": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "integer"
        }
      },
      "description": "List of face vertex-index lists."
    },
    "origin": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 3,
      "maxItems": 3,
      "description": "A point on the plane [ox, oy, oz]. Default [0, 0, 0]."
    },
    "normal": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 3,
      "maxItems": 3,
      "description": "Plane normal vector [nx, ny, nz] (need not be unit length). Default [0, 0, 1]."
    }
  },
  "required": [
    "vertices",
    "faces"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
