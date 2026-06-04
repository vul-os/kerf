# cam_verify_toolpath_collision

*Module: `kerf_cad_core.cam_toolpath_collision` · Domain: cad*

## Description

Verify a CAM toolpath segment-by-segment for holder/spindle collisions against the workpiece (stock) and optional fixturing geometry.

For each segment the tool holder capsule is checked against the stock AABB and optional triangle mesh at 1 mm sampling resolution. Returns a list of collision events with segment index, position, and clearance distance.

Inputs:
  toolpath       — list of {x,y,z,feedrate} waypoints (mm)
  flute_radius   — cutting flute radius (mm)
  flute_length   — cutting flute length (mm)
  holder_radius  — holder cylinder radius (mm; must be > flute_radius)
  holder_length  — holder cylinder length above flute (mm)
  stock_aabb_min — [xmin,ymin,zmin] of stock bounding box (mm)
  stock_aabb_max — [xmax,ymax,zmax] of stock bounding box (mm)
  stock_triangles — optional list of triangles [[p0,p1,p2],…] for mesh stock
  fixture_triangles — optional list of triangles for fixturing
  safety_margin  — required holder clearance in mm (default 2.0)
  step_mm        — sampling resolution along each segment (default 1.0)

## Input schema

```json
{
  "type": "object",
  "required": [
    "toolpath",
    "flute_radius",
    "flute_length",
    "holder_radius",
    "holder_length",
    "stock_aabb_min",
    "stock_aabb_max"
  ],
  "properties": {
    "toolpath": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "x": {
            "type": "number"
          },
          "y": {
            "type": "number"
          },
          "z": {
            "type": "number"
          },
          "feedrate": {
            "type": "number"
          }
        },
        "required": [
          "x",
          "y",
          "z"
        ]
      },
      "description": "Ordered list of tool-tip waypoints (mm)."
    },
    "flute_radius": {
      "type": "number"
    },
    "flute_length": {
      "type": "number"
    },
    "holder_radius": {
      "type": "number"
    },
    "holder_length": {
      "type": "number"
    },
    "stock_aabb_min": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 3,
      "maxItems": 3
    },
    "stock_aabb_max": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 3,
      "maxItems": 3
    },
    "stock_triangles": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "array",
          "items": {
            "type": "number"
          }
        }
      },
      "description": "Optional triangle mesh for stock."
    },
    "fixture_triangles": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "array",
          "items": {
            "type": "number"
          }
        }
      },
      "description": "Optional triangle mesh for fixturing."
    },
    "safety_margin": {
      "type": "number",
      "default": 2.0
    },
    "step_mm": {
      "type": "number",
      "default": 1.0
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="cam_verify_toolpath_collision",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
