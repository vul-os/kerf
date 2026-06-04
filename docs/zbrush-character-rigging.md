# Character Rigging and Skinning

> Bind a skeleton to a sculpted mesh with automatic proximity weights and linear blend skinning.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/sculpt/character_rigging.py`
**Shipped**: Wave 9B1
**LLM tools**: `sculpt_rig`

---

## What it is

Character rigging attaches a `Skeleton` (a hierarchy of `Bone` objects with rest poses) to a mesh using automatic proximity-based skinning weights, then evaluates posed deformation using Linear Blend Skinning (LBS). It mirrors the ZBrush ZSphere rigging + Blender auto-weight workflow: define bones, run `auto_weight_from_proximity`, then call `linear_blend_skinning` with any pose.

## How to use it

### From chat

> "Auto-rig my character mesh with the skeleton JSON I uploaded, then pose the left arm at 45 degrees."

### From Python

```python
from kerf_cad_core.sculpt.character_rigging import (
    Bone, Skeleton, auto_weight_from_proximity,
    linear_blend_skinning, make_bone,
)

bones = [
    make_bone("spine", head=(0, 0, 0), tail=(0, 0, 0.5)),
    make_bone("upper_arm_l", head=(0.2, 0, 0.45), tail=(0.5, 0, 0.45)),
]
skel = Skeleton(bones=bones)
weights = auto_weight_from_proximity(vertices=v, skeleton=skel)

# Pose: rotate upper_arm_l by 45°
poses = {1: rotation_matrix_x(45)}
posed_v = linear_blend_skinning(vertices=v, weights=weights, skeleton=skel, poses=poses)
```

### From an LLM tool spec

```json
{"tool": "sculpt_rig", "input": {"skeleton_json": {...}, "auto_weight": true}}
```

## How it works

`auto_weight_from_proximity` assigns each vertex a normalised weight vector across all bones, inversely proportional to the distance from the vertex to each bone segment. Weights are normalised to sum to 1.0. LBS deforms each vertex as a weighted sum of the bone-space transformations: `v' = Σ w_i * T_i * v`, where `T_i` is the pose matrix of bone `i`.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `auto_weight_from_proximity(vertices, skeleton)` | `WeightMap` | Proximity-based skinning weights |
| `linear_blend_skinning(vertices, weights, skeleton, poses)` | `np.ndarray` | Posed vertex positions |
| `make_bone(name, head, tail)` | `Bone` | Construct a bone from endpoint positions |
| `Skeleton(bones)` | instance | Bone hierarchy container |

## Example

```python
weights = auto_weight_from_proximity(v, skel)
posed_v = linear_blend_skinning(v, weights, skel, poses={1: R})
# posed_v.shape == (N, 3)
```

## Honest caveats

Proximity-based auto-weights work well for most body parts but can fail at joints with complex underlying geometry (e.g., shoulder). Manual weight painting or weight smoothing may be needed. LBS produces the "candy-wrapper" twist artefact at joint rotations larger than ~90°; dual quaternion skinning is not currently implemented. The rigging module does not support shape keys or corrective blend shapes.

## References

- Magnenat-Thalmann et al., "Joint-dependent local deformations for hand animation," *Graphics Interface* (1988).
- Kavan et al., "Skinning with Dual Quaternions," *I3D* (2007).
