# Persistent Face IDs

> Assign stable geometry-derived identifiers to BRep faces so fillets, threads, and constraints survive upstream edits without breaking downstream features.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/afr/persistent_face_id.py`
**Shipped**: Wave 9
**LLM tools**: `feature_assign_face_ids`, `feature_detect_id_breaks`

---

## What it is

In history-based parametric CAD, downstream features reference upstream faces by identity: "fillet the edge between face_23 and face_24". When the model regenerates — after a sketch edit, a dimension change, or a Boolean — the faces are renumbered by the kernel, breaking those references.

Kerf's persistent face ID system derives stable identifiers from geometry itself: the face centroid relative to the body centroid, the face area, and the surface normal direction are hashed into a `FacePersistentId`. After an edit, `reattach_face_ids_after_edit` matches old IDs to the new face set by proximity and reports breaks. This provides Solidworks-style parametric stability without requiring a full feature-tree replay engine.

## How to use it

### From chat (natural language)

> "Assign persistent IDs to the bracket faces and check what changed after the last edit"

The LLM calls `feature_assign_face_ids` then `feature_detect_id_breaks`.

### From Python

```python
from kerf_cad_core.afr.persistent_face_id import (
    assign_persistent_ids, reattach_face_ids_after_edit, detect_id_breaks,
)

# Assign IDs to all faces
body_with_ids = assign_persistent_ids(body_topology)

# After an upstream edit
remapped = reattach_face_ids_after_edit(old_body, new_body, tolerance=0.1)
breaks   = detect_id_breaks(old_body, new_body)
for b in breaks:
    print(f"Face {b['old_id']} lost — reason: {b['reason']}")
```

### From an LLM tool spec

```json
{"tool": "feature_assign_face_ids", "body_id": "bracket_v2"}
```

## How it works

Each face's persistent ID is built from three components: (1) its centroid relative to the body centroid (normalised by body bounding-box diagonal), (2) the signed face area, and (3) the dominant surface normal direction binned to an octant. These are hashed together into a 128-bit canonical signature. On reattachment, the algorithm performs a nearest-neighbour search in signature space, using the `feature_role` field (e.g. "hole_wall", "planar_face") as a secondary disambiguator for symmetric parts.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `assign_persistent_ids(body_topology)` | `dict` | Annotate faces with stable IDs |
| `reattach_face_ids_after_edit(old, new, tol)` | `dict` | Remap IDs after edit |
| `detect_id_breaks(old, new)` | `List[dict]` | List faces whose IDs broke |

`FacePersistentId` fields: `id_str`, `centroid_rel`, `area`, `normal_octant`, `feature_role`.

## Example

```python
b1 = assign_persistent_ids(topo_before)
b2 = assign_persistent_ids(topo_after)
breaks = detect_id_breaks(b1, b2)
print(f"{len(breaks)} face IDs broken after edit")
```

## Honest caveats

ID stability depends on centroid and normal hashing. Symmetric parts with many similar faces (gear teeth, bolt-hole patterns) can suffer hash collisions; the feature_role disambiguator helps but is not infallible. Faces that are deleted or merged by a Boolean will always break — the system reports them but cannot recover them. Coloured-face disambiguation is not yet implemented.

## References

- Kripac (1997). "A mechanism for persistently naming topological entities in history-based parametric solid models." *SMA* 1997.
