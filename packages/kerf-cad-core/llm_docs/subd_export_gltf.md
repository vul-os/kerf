# subd_export_limit_to_gltf

*Module: `kerf_cad_core.geom.subd_export_gltf` · Domain: cad*

## Description

Export a SubD control cage as a Catmull-Clark limit-surface mesh in glTF 2.0 format (.gltf JSON or .glb binary).

glTF is the Khronos 'JPEG of 3D' — consumed by Three.js, Babylon.js, Blender, Unity, and Unreal. Applies N levels of Catmull-Clark subdivision and emits a valid glTF 2.0 asset with POSITION attribute + triangle indices.

HONEST LIMITATIONS (v1):
  - Geometry only: no materials, normals, textures, animations, skinning.
  - Quads fan-triangulated: [a,b,c,d] → (a,b,c)+(a,c,d).
  - No KHR_mesh_quantization or Draco compression.

Returns:
  ok           : bool
  gltf_b64     : str   — base64-encoded .gltf or .glb bytes
  format       : str   — 'gltf' or 'glb'
  n_vertices   : int   — vertex count after subdivision
  n_triangles  : int   — triangle count after triangulation
  levels_used  : int   — actual subdivision levels applied

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
    },
    "format": {
      "type": "string",
      "description": "'gltf' (JSON + base64 buffer) or 'glb' (binary).",
      "enum": [
        "gltf",
        "glb"
      ],
      "default": "gltf"
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
    tool_name="subd_export_limit_to_gltf",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
