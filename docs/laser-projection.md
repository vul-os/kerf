# Laser Projection Layout

> Project ply and assembly outlines onto tooling surfaces for manual layup guidance, expressed as 3D polylines for laser projector control.

**Module**: `packages/kerf-composites/src/kerf_composites/drape.py`
**Shipped**: Wave 11
**LLM tools**: `composites_laser_projection`

---

## What it is

Laser projection systems replace physical templates in composite layup: a laser projects ply outlines directly onto a mold surface to guide hand-layup technicians. The projector needs a set of 3D polylines in its coordinate system — typically extracted by mapping flat ply boundaries onto the draped surface and then transforming to the projector frame. This feature generates those polylines from a draped DrapeResult.

## How to use it

### From chat

> "Generate laser projection lines for ply 3 (0° orientation) on my fuselage mold. Projector is at position [0, 2000, 1500] mm, looking toward [0, 0, 0]."

### From Python

```python
from kerf_composites.drape import drape_flat_to_surface

result = drape_flat_to_surface(
    surface_fn=lambda u, v: (u, v, 0.001 * u**2),
    u_range=(0, 800), v_range=(0, 500),
    nu=40, nv=25
)
# Boundary polyline in 3D: use the draped edge of the ply grid
boundary_3d = [tuple(result.surf_coords[i, 0]) for i in range(40)]
boundary_3d += [tuple(result.surf_coords[-1, j]) for j in range(25)]
boundary_3d += [tuple(result.surf_coords[39 - i, -1]) for i in range(40)]
boundary_3d += [tuple(result.surf_coords[0, 24 - j]) for j in range(25)]
```

### From an LLM tool spec

```json
{"ply_boundary_flat": [[0,0],[800,0],[800,500],[0,500]],
 "surface_type": "parabolic_crown", "crown_height_mm": 10,
 "projector_pos": [0, 2000, 1500], "projector_aim": [0, 0, 0]}
```

## How it works

The flat ply boundary is a closed 2D polygon. Each corner is mapped to 3D by looking up the nearest node in the draped grid's `flat_coords` array and returning the corresponding `surf_coords` entry. Bilinear interpolation fills in points between grid nodes. The resulting 3D polyline is expressed in the workpiece coordinate system; if a projector transform is supplied, the polyline is further rotated/translated to the projector frame using a simple rigid-body transform. The output format is a list of `{x, y, z}` dicts that can be sent directly to most laser projector SDKs.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `drape_flat_to_surface(surface_fn, ...)` | `DrapeResult` | Draped grid for surface mapping |
| `DrapeResult.surf_coords` | `ndarray (nu,nv,3)` | 3D node positions for boundary lookup |
| `DrapeResult.flat_coords` | `ndarray (nu,nv,2)` | Corresponding flat-ply positions |

## Example

```python
import numpy as np
dr = drape_flat_to_surface(lambda u,v: (u,v,0), (0,500),(0,300), 20, 12)
# All points are coplanar → shear angles are zero
assert np.allclose(dr.shear_angles, 0, atol=1e-6)
print("Flat surface: OK")
```

## Honest caveats

Laser projection accuracy depends on projector calibration and mold registration — Kerf provides the polyline data only. The bilinear interpolation between grid nodes introduces sub-millimetre positional error; reduce `nu`/`nv` step size for high-precision applications. No anti-occlusion logic: the projector beam direction is not checked for interference with mold geometry.

## References

- Assmann Laser Technology (2021). *LaserGuide Operator Manual*. §3 (projection programming).
- Mack, C. (2006). Fundamentals of microlithography. *SPIE Field Guide* FG06. (general projection principles)
