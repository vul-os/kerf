# 3DM File I/O and Hausdorff Deviation

> Read and write Rhinoceros 3DM files natively, and measure Hausdorff distance between two NURBS surfaces for import validation and tolerance checking.

**Module**: `packages/kerf-imports/src/kerf_imports/threedm_write.py`
**Shipped**: Wave 8
**LLM tools**: `feature_import_3dm`, `feature_export_3dm`

---

## What it is

Rhinoceros `.3dm` files are the native format of Rhino, the most widely used NURBS modelling tool in product design and architecture. Kerf reads and writes 3DM files natively — without requiring Rhino to be installed — using a pure-Python binary parser that decodes the chunk-based 3DM format (OpenNURBS specification).

The module also provides `hausdorff_distance`, which measures the one-sided and bidirectional Hausdorff distance between two NURBS surfaces. This is used to validate that an imported 3DM surface matches the design intent within tolerance, or to check that a simplified surface deviates less than a manufacturing tolerance from the original.

## How to use it

### From chat (natural language)

> "Import the door_panel.3dm file and check that the NURBS surface is within 0.05mm of the original scan"

The LLM calls `feature_import_3dm` then the surface deviation check.

### From Python

```python
from kerf_imports.threedm_write import (
    read_threedm_bytes, write_3dm, write_3dm_bytes,
    ThreeDmFile, hausdorff_distance,
)

# Read a 3DM file
with open("panel.3dm", "rb") as f:
    model: ThreeDmFile = read_threedm_bytes(f.read())

print(f"NURBS surfaces: {len(model.surfaces)}")
print(f"Meshes: {len(model.meshes)}")

# Check Hausdorff distance between two surfaces
d = hausdorff_distance(model.surfaces[0], reference_surf, n_samples=200)
print(f"Max deviation: {d['hausdorff_m']*1000:.3f} mm")

# Write a 3DM file
write_3dm(model, path="output.3dm")
```

### From an LLM tool spec

```json
{"tool": "feature_import_3dm", "path": "panel.3dm", "check_tolerance": 0.05}
```

## How it works

The 3DM binary format is a sequence of typed chunks with 4-byte type codes and 8-byte length headers. NURBS surfaces are stored as OpenNURBS `ON_NurbsSurface` chunks containing degree, knot vector, and control point arrays. Kerf's reader decodes each chunk type and populates a `ThreeDmFile` model object. The writer encodes Kerf `NurbsSurface` and `NurbsCurve` objects back to OpenNURBS chunks.

`hausdorff_distance` uses a two-phase approach: sample `n_samples²` points on the first surface, find the nearest point on the second surface using Newton iteration, then take the maximum. Both one-sided distances are computed for the bidirectional Hausdorff measure.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `read_threedm_bytes(data)` | `ThreeDmFile` | Parse 3DM binary |
| `write_3dm_bytes(model)` | `bytes` | Serialise to 3DM binary |
| `write_3dm(model, path)` | `None` | Write 3DM to disk |
| `hausdorff_distance(surf_a, surf_b, n_samples)` | `dict` | Hausdorff deviation |

`ThreeDmFile` fields: `surfaces`, `curves`, `meshes`, `metadata`, `version`.
`hausdorff_distance` returns: `hausdorff_m`, `one_sided_ab_m`, `one_sided_ba_m`, `rms_m`.

## Example

```python
with open("design.3dm", "rb") as f:
    model = read_threedm_bytes(f.read())
srf = model.surfaces[0]
d = hausdorff_distance(srf, scanned_surf, n_samples=100)
print(f"Hausdorff: {d['hausdorff_m']*1000:.4f} mm")
```

## Honest caveats

The 3DM reader supports OpenNURBS version 4/5/6/7 chunk formats for NURBS surfaces and curves. Non-NURBS geometry (SubD objects, extrusion objects, hatches) is skipped with a warning. Blocks (instances) and layers are partially parsed — geometry within blocks is extracted but block transforms are not applied. The Hausdorff computation samples the surface uniformly in UV space, which can miss narrow high-deviation spikes in regions with high parameter distortion; use `n_samples >= 200` for production checks.

## References

- McNeel (2023). OpenNURBS file format specification. developer.rhino3d.com.
- Aspert, Santa-Cruz & Ebrahimi (2002). "MESH: Measuring errors between surfaces using the Hausdorff distance." *ICME* 2002.
