# AFP/ATL Fibre-Placement Paths

> Automated Fibre Placement and Automated Tape Laying path planning for continuous-fibre composite layup on complex surfaces.

**Module**: `packages/kerf-composites/src/kerf_composites/drape.py`, `layup.py`
**Shipped**: Wave 9D3
**LLM tools**: `composites_drape`, `composites_afp_path`

---

## What it is

Automated Fibre Placement (AFP) and Automated Tape Laying (ATL) are robotic layup processes where narrow tow or wide tape is placed continuously on a mandrel. Path quality determines whether gaps and overlaps stay within specification (typically ±1 mm for AFP tows) and whether the tow can track the surface without wrinkling or bridging. This module generates geodesic-based reference paths and predicts shear angles to flag drape infeasibility before the programme is sent to the robot.

## How to use it

### From chat

> "Generate AFP reference paths for a cylindrical panel 600 mm × 400 mm, 0° ply direction, 6.35 mm tow width. Check that shear angles stay below 45°."

### From Python

```python
from kerf_composites.drape import drape_flat_to_surface, DrapeResult
import numpy as np

# Cylindrical surface: radius 300 mm
surface = lambda u, v: (300 * np.cos(u / 300), v, 300 * np.sin(u / 300))

result: DrapeResult = drape_flat_to_surface(
    surface_fn=surface,
    u_range=(0, 600),
    v_range=(0, 400),
    nu=30, nv=20
)
print("Max shear angle:", result.shear_angles.max(), "deg")
print("AFP feasible:", result.shear_angles.max() < 45)
```

### From an LLM tool spec

```json
{"surface_type": "cylinder", "radius": 300, "length": 400,
 "tow_width_mm": 6.35, "ply_angle_deg": 0,
 "nu": 30, "nv": 20}
```

## How it works

Drape uses a discrete pin-jointed (fishing-net) algorithm. The first row and column are pinned by placing nodes at geodesic distances along the surface. Subsequent nodes are located by intersecting two geodesic arcs from adjacent pinned neighbours (the compass algorithm). Shear angle at each interior node is the deviation from 90° of the angle between the two crossing fibre families. For an inextensible woven ply this equals the in-plane shear strain. AFP paths are extracted as iso-U contours of the draped grid; the robot follows each contour while depositing tow.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `drape_flat_to_surface(surface_fn, u_range, v_range, nu, nv)` | `DrapeResult` | Geodesic drape grid |
| `DrapeResult.flat_coords` | `ndarray (nu,nv,2)` | Flat (u,v) tow positions |
| `DrapeResult.surf_coords` | `ndarray (nu,nv,3)` | 3D draped positions |
| `DrapeResult.shear_angles` | `ndarray (nu,nv)` | Local shear angle (deg) |

## Example

```python
# Check saddle-surface feasibility
surface = lambda u, v: (u, v, 0.002 * u**2 - 0.001 * v**2)
dr = drape_flat_to_surface(surface, (-300,300), (-200,200), 24, 16)
violations = (dr.shear_angles > 45).sum()
print(f"{violations} cells exceed 45° shear limit")
```

## Honest caveats

The fishing-net algorithm assumes an inextensible woven fabric. Pre-preg slit-tape (AFP) has some extensibility that allows tow steering; this is not modelled. The geodesic approximation is accurate for convex surfaces but may diverge on strongly concave or saddle geometries — compare against full FEA drape for production programmes. No robot kinematics or stagger/seam planning is included.

## References

- Boon, Y.D. et al. (2022). A review of methods for fibre path optimisation. *Compos. Struct.* 285, 115220.
- Potter, K. (2002). *Resin Transfer Moulding*, 2nd ed. Chapman & Hall. §4 (drape geometry).
