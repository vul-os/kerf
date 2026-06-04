# Landscape Grading

> Contour generation from a DEM, cut/fill volume computation, and uniform planar grade design for landscape and site-grading projects.

**Module**: `packages/kerf-landscape/src/kerf_landscape/grading.py`
**Shipped**: Wave 12B5
**LLM tools**: `landscape_grade_surface`, `landscape_cut_fill`, `landscape_contours`

---

## What it is

Site grading balances earthwork across a project area: material excavated (cut) from high spots is used to fill low spots, minimising hauling cost. The designer specifies a target grade (slope and direction) and the grading module computes the design surface, extracts contours for the grading plan, and calculates the net cut/fill volumes that drive the earthwork budget.

## How to use it

### From chat

> "Grade this 40 × 30 m site to 2% slope running north, starting from elevation 10.5 m at the south edge. Calculate cut and fill volumes versus the existing DEM."

### From Python

```python
from kerf_landscape.grading import (
    grade_surface, cut_fill_volumes, contours_from_dem
)
import numpy as np

nx, ny = 20, 15
x = np.linspace(0, 40, nx)
y = np.linspace(0, 30, ny)
existing_dem = np.random.uniform(10.0, 11.5, (nx, ny))

design_dem = grade_surface(
    dem=existing_dem, x_coords=x, y_coords=y,
    target_grade=0.02, origin_xy=(20, 0), direction="north"
)
vols = cut_fill_volumes(existing_dem, design_dem,
                        cell_width=40/nx, cell_height=30/ny)
print(f"Cut: {vols['cut_m3']:.1f} m³, Fill: {vols['fill_m3']:.1f} m³")
```

### From an LLM tool spec

```json
{"dem_grid": [[10.1, 10.3], [10.5, 10.8]],
 "cell_width_m": 2.0, "cell_height_m": 2.0,
 "target_grade": 0.02, "direction": "north",
 "origin_elevation_m": 10.5}
```

## How it works

`grade_surface` constructs a uniform tilted plane through the origin point at the specified slope in the given compass direction. The design elevation at each DEM cell is the plane evaluation at that cell's centroid coordinates. `cut_fill_volumes` computes cell-level differences: positive difference = cut (existing above design), negative = fill. Volumes use a simple prismatic cell approximation (cell area × average depth). `contours_from_dem` implements the marching-squares algorithm on adjacent 2×2 cell quads, linearly interpolating crossing points for each iso-elevation level.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `grade_surface(dem, x_coords, y_coords, target_grade, origin_xy, direction)` | `ndarray` | Design DEM from planar grade |
| `cut_fill_volumes(dem_existing, dem_design, cell_width, cell_height)` | `dict` | Cut, fill, net volumes (m³) |
| `contours_from_dem(dem, x_coords, y_coords, levels)` | `list[dict]` | Iso-contour segments per level |

## Example

```python
from kerf_landscape.grading import cut_fill_volumes
import numpy as np
ex = np.array([[1.0, 1.5],[1.2, 1.8]])
des = np.ones((2,2)) * 1.3
r = cut_fill_volumes(ex, des, 2.0, 2.0)
print(r)  # {"ok": True, "cut_m3": 0.8, "fill_m3": 0.4, "net_m3": 0.4}
```

## Honest caveats

The planar-grade design assumes a single slope direction; compound-grade or curved grading designs are not supported. Volumes use a cell-average prism approximation (Simpson's rule or the Average End-Area method would be more accurate for linear features). The marching-squares contour algorithm does not close saddle-point ambiguities deterministically; small artefacts may appear on nearly-flat terrain.

## References

- Landscape Architecture Foundation (2014). *Site Engineering for Landscape Architects*, 6th ed. §6 (grading and earthwork).
- Fazio, J.R. (2009). *Stormwater Management Handbook*. Chapter 3 (grading and drainage).
