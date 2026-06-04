# Armature Poser

> Evaluate a skeleton at any animation time and apply the resulting pose to a skinned mesh.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/animation/armature.py`
**Shipped**: Wave 9B2
**LLM tools**: `animation_apply_pose`

---

## What it is

The armature poser evaluates a hierarchical skeleton (`Armature`) at a given animation time by traversing the bone hierarchy and accumulating local-to-world matrices. It then applies Linear Blend Skinning to deform a vertex array. This covers the Blender "Armature Modifier" workflow: define bones, key their rotations in F-curves, evaluate at any frame.

## How to use it

### From chat

> "Evaluate my character armature at frame 24 and return the deformed mesh vertices."

### From Python

```python
from kerf_cad_core.animation.armature import (
    Armature, evaluate_armature_at_time, linear_blend_skinning,
)

# Build or load armature
armature = Armature(
    bones=[
        {"name": "root", "parent": None, "rest_head": [0,0,0], "rest_tail": [0,0,0.5]},
        {"name": "spine", "parent": "root", "rest_head": [0,0,0.5], "rest_tail": [0,0,1.0]},
    ],
    fcurves={"spine.rotation_x": fcurve_spine_x},
)
pose_matrices = evaluate_armature_at_time(armature, t=0.5)  # time in seconds
deformed_v = linear_blend_skinning(
    vertices=bind_pose_v,
    weights=skin_weights,   # (N, n_bones) float array
    pose_matrices=pose_matrices,  # list of 4×4 matrices
)
```

### From an LLM tool spec

```json
{"tool": "animation_apply_pose", "input": {"bones": [...], "time": 0.5, "vertices": [...], "weights": [...]}}
```

## How it works

`evaluate_armature_at_time` walks the bone tree depth-first. For each bone it evaluates the F-curves at `t` to get local rotation (as a 3×3 matrix), computes the local-to-parent matrix, and concatenates with the parent's world matrix. The world matrix is then multiplied by the inverse bind-pose matrix to produce the skinning matrix. `linear_blend_skinning` sums the weighted skinning matrices per vertex.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `evaluate_armature_at_time(armature, t)` | `list[np.ndarray]` | List of 4×4 world-space pose matrices per bone |
| `linear_blend_skinning(vertices, weights, pose_matrices)` | `np.ndarray` | Deformed vertex positions |
| `Armature(bones, fcurves)` | instance | Skeleton with animated bone channels |

## Example

```python
mats = evaluate_armature_at_time(armature, t=1.0)
posed_v = linear_blend_skinning(rest_v, weights, mats)
# posed_v.shape == (N, 3)
```

## Honest caveats

This module uses Linear Blend Skinning which is the industry-standard method but exhibits the "candy-wrapper" twist artefact at large rotation angles. Dual quaternion skinning, which avoids this, is not yet implemented. The bone hierarchy must be a strict tree (no cycles). Inverse kinematics are solved separately by `ik_solver.py` and the resulting angles must be written into the F-curves manually.

## References

- Lewis, Cordner & Fong, "Pose Space Deformation," *SIGGRAPH* (2000).
- Kavan et al., "Skinning with Dual Quaternions," *I3D* (2007).
