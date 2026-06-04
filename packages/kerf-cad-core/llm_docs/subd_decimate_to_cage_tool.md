# subd_decimate_dense_mesh_to_cage

*Module: `kerf_cad_core.geom.subd_decimate_to_cage_tool` · Domain: cad*

## Description

Given a dense triangle mesh (assumed to be limit-surface samples from a SubD or scanned surface), produce a low-poly SubD control cage that when Catmull-Clark subdivided reproduces the original mesh within tolerance.

**Algorithm**: Garland–Heckbert 1997 QEM edge collapse with 4×4 quadric per vertex and priority-queue collapse, followed by Bommes 2013 §3 triangle-pair → quad recovery, producing a Catmull-Clark valid quad cage.

**Inputs**: raw vertex / face arrays (triangle mesh).

**Outputs**: SubDCage (vertices + faces, mixed quad + tri fallback) plus a DecimationReport (deviation, quad_count, tri_fallback_count, collapse_iterations, deviation_ratio).

**target_quads**: approximate desired quad count. For a dense torus (1000 triangles) use target_quads=64. Actual count may be ±15% due to triangle pairing constraints.

**planar_dot**: minimum cos(angle) between adjacent face normals for quad pairing (default 0.95 ≈ 18°). Reduce to 0.85 for curved surfaces.

**Honest flag**: arbitrary triangle topology may not always recover ideal quads. Unmatched triangles fall back to triangle SubD faces and are reported in ``tri_fallback_count``.

## Input schema

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
      "description": "List of [x, y, z] vertex coordinates."
    },
    "faces": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "integer"
        },
        "minItems": 3,
        "maxItems": 3
      },
      "description": "List of [i, j, k] triangle face index triples."
    },
    "target_quads": {
      "type": "integer",
      "description": "Approximate desired quad count in output cage. Default 64."
    },
    "planar_dot": {
      "type": "number",
      "description": "Minimum normal dot product for quad pairing (0.95 = 18\u00b0). Default 0.95. Reduce to 0.85 for highly curved surfaces."
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
    tool_name="subd_decimate_dense_mesh_to_cage",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
