# Mold Parting Line & Moldability Check

> Draft-angle analysis, parting-surface generation, and moldability validation for injection-mold tooling design.

**Module**: `packages/kerf-mold/src/kerf_mold/mold.py`
**Shipped**: Wave 10C3
**LLM tools**: `mold_check_moldability`, `mold_draft_angles`, `mold_parting_surface`

---

## What it is

The parting line is the boundary where the core and cavity halves of a mold separate. Getting it wrong means undercuts, flash, or parts that cannot be ejected. This module validates an existing mold design for three common failure modes: insufficient draft angle, non-uniform wall thickness, and a parting surface that deviates from the pull direction.

Use it early in mold design to confirm that every face has positive draft before committing to hard tooling.

## How to use it

### From chat

> "Check moldability of my bracket mold — pull direction is +Z, minimum draft 1.5°, wall thicknesses are 2.1, 2.4, 2.2, 5.8 mm."

### From Python

```python
from kerf_mold.mold import (
    Face, EjectorPin, GateLocation, PartingLine, MoldDesign,
    check_moldability, draft_angle_per_face, generate_parting_surface
)

core_face = Face(vertices=[[0,0,0],[10,0,2],[10,10,2],[0,10,0]],
                 normal=[0, -0.196, 0.981], face_id="side_A")
cavity_face = Face(vertices=[[0,0,10],[10,0,8],[10,10,8],[0,10,10]],
                   normal=[0, 0.196, 0.981], face_id="top_B")
pl = PartingLine(points=[[0,0,0],[10,0,0],[10,10,0],[0,10,0]])
design = MoldDesign(core_faces=[core_face], cavity_faces=[cavity_face],
                    parting_line=pl, pull_direction=[0,0,1])
result = check_moldability(design, min_draft_deg=1.5, max_wall_ratio=3.0)
print(result["all_checks_pass"], result["failing_faces"])
```

### From an LLM tool spec

```json
{"faces": [{"vertices": [[0,0,0],[10,0,2],[10,10,2],[0,10,0]],
            "normal": [0,-0.196,0.981], "face_id": "side_A"}],
 "pull_direction": [0,0,1],
 "min_draft_deg": 1.5}
```

## How it works

Draft angle per face: `draft_deg = degrees(asin(n · pull_hat))`. Positive = face tilts away from pull (correct); negative = undercut. Wall uniformity: max_thickness / min_thickness must not exceed `max_wall_ratio` (default 3.0) to avoid sink marks. Parting-surface continuity: Newell's method computes the best-fit plane normal for the parting-line loop; this normal must be within 5° of the pull direction. `generate_parting_surface` triangulates the loop via fan triangulation (flat style) or ruled extrusion along the pull direction.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `check_moldability(design, min_draft_deg, max_wall_ratio)` | `dict` | Full three-check validation |
| `draft_angle_per_face(faces, pull_dir)` | `list[dict]` | Per-face draft angles |
| `generate_parting_surface(parting_line, style, pull_dir)` | `dict` | Flat or ruled surface patch |

## Example

```python
pl = PartingLine([[0,0,0],[50,0,0],[50,30,0],[0,30,0]])
surf = generate_parting_surface(pl, style="flat")
print(f"Area: {surf['area_mm2']:.1f} mm², planar: {surf['is_flat']}")
```

## Honest caveats

Draft-angle computation uses the face outward normal, not the actual surface geometry — curved faces need pre-tessellation. Wall-thickness uniformity requires the caller to supply sampled thickness values (Kerf does not raytrace the mesh). The parting-line continuity check is a linear best-fit — complex stepped parting lines will always exceed the 5° threshold.

## References

- Menges, G., Michaeli, W. & Mohren, P. (2001). *How to Make Injection Molds*, 3rd ed. Hanser. §4, §7, §8.
- Rosato, D.V. & Rosato, M.G. (2000). *Injection Molding Handbook*, 3rd ed. Kluwer. §5, §6.
