# subd_export_limit_to_step

*Module: `kerf_cad_core.geom.subd_export_step` · Domain: cad*

## Description

Export a SubD control cage as a Catmull-Clark limit-surface mesh in STEP AP242 format (.stp ASCII, ISO 10303-242:2020).

Applies N levels of Catmull-Clark subdivision and emits a valid STEP file with CARTESIAN_POINTs, EDGE_CURVEs, ADVANCED_FACEs on PLANE surfaces, OPEN_SHELL, and SHELL_BASED_SURFACE_MODEL.

HONEST LIMITATIONS:
  - Faceted B-rep: each subdivided polygon is a flat PLANE face.
    STEP has no native SubD primitive. Not smooth NURBS.
  - Geometry only: no colour, material, PMI, or units conversion.
  - SI millimetre context is emitted for validator compliance.

Returns:
  ok             : bool
  step_text      : str   — full STEP ASCII content
  n_vertices     : int   — CARTESIAN_POINT count
  n_faces        : int   — ADVANCED_FACE count (= subdivision faces)
  levels_used    : int   — actual subdivision levels applied

Errors: {ok: false, reason}.  Never raises.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "vertices": {
      "type": "array",
      "description": "Control-mesh vertices [[x, y, z], ...].",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      }
    },
    "faces": {
      "type": "array",
      "description": "Face vertex-index lists [[i, j, k, l], ...].",
      "items": {
        "type": "array",
        "items": {
          "type": "integer"
        }
      }
    },
    "creases": {
      "type": "array",
      "description": "Optional crease list [{v1, v2, value}, ...].",
      "items": {
        "type": "object",
        "properties": {
          "v1": {
            "type": "integer"
          },
          "v2": {
            "type": "integer"
          },
          "value": {
            "type": "number"
          }
        },
        "required": [
          "v1",
          "v2",
          "value"
        ]
      }
    },
    "levels": {
      "type": "integer",
      "description": "Subdivision levels (default 2, range [0, 8]).",
      "default": 2,
      "minimum": 0,
      "maximum": 8
    }
  },
  "required": [
    "vertices",
    "faces"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="subd_export_limit_to_step",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
