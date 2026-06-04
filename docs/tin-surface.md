# TIN Terrain Surface

> Delaunay triangulated terrain model from survey points with contour extraction, slope, aspect, cut/fill volume and earthwork reports.

**Module**: `packages/kerf-civil/src/kerf_civil/tin.py`
**Shipped**: Wave 9
**LLM tools**: `civil_build_tin`, `civil_contours`, `civil_earthwork_volume`

---

## What it is

A Triangulated Irregular Network (TIN) is the standard terrain representation for civil engineering. It connects irregularly distributed survey points into a triangulated mesh that exactly passes through all data points, unlike grid-based DEMs that interpolate. From a TIN you can extract contours at any interval, compute slope and aspect for any triangle, calculate cut-and-fill volumes between existing and design surfaces, and derive earthwork quantities for cost estimation.

## How to use it

### From chat

> "Build a TIN from my 150-point survey and extract contours at 0.5 m intervals. What is the total cut volume if I grade to a flat platform at elevation 45.0 m?"

### From Python

```python
from kerf_civil.tin import build_tin, contours, volume_above
import numpy as np

# Survey points [x, y, z] in metres
pts = np.array([[0,0,44.1],[10,0,44.8],[20,0,45.6],[10,15,46.2]])
tin = build_tin(pts)
lines = contours(tin, interval=0.5, z_min=44.0, z_max=47.0)
print(f"{len(lines)} contour polylines")
vol = volume_above(tin, datum_z=45.0)
print(f"Volume above 45.0 m: {vol:.2f} m³")
```

### From an LLM tool spec

```json
{"points": [[0,0,44.1],[10,0,44.8],[20,0,45.6]],
 "contour_interval_m": 0.5,
 "datum_z": 45.0}
```

## How it works

`build_tin` uses `scipy.spatial.Delaunay` to construct the triangulation in the XY plane, then assigns the Z-coordinates from the input survey points. Contours are extracted by a per-triangle linear interpolation: for each triangle edge that straddles a contour level, the crossing point is computed and line segments are assembled into polylines. Slope per triangle is the angle of the steepest descent vector (magnitude of the 3D face normal projected to horizontal). `volume_above` sums the prism volume for each triangle above the datum using the trapezoidal rule on the three vertex heights.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `build_tin(points)` | `TIN` | Delaunay triangulation from (N,3) survey points |
| `contours(tin, interval, z_min, z_max)` | `list[list[tuple]]` | Iso-elevation polylines |
| `slope(tin, triangle_index)` | `float` | Max slope angle of a triangle (degrees) |
| `aspect(tin, triangle_index)` | `float` | Steepest downslope compass bearing (0–360°) |
| `area_2d(tin)` | `float` | Horizontal projected area (m²) |
| `volume_above(tin, datum_z)` | `float` | Volume above datum plane (m³) |

## Example

```python
import numpy as np
from kerf_civil.tin import build_tin, slope, aspect
pts = np.array([[0,0,0],[10,0,2],[10,10,2],[0,10,1]])
t = build_tin(pts)
print(f"Triangle 0 slope: {slope(t,0):.1f}°, aspect: {aspect(t,0):.0f}°")
```

## Honest caveats

Delaunay triangulation minimises the maximum interior angle but does not enforce specific breaklines (roads, ridge lines). For accurate earthwork near breaklines, supply dense survey points along them or add breakline constraints manually. Very large survey files (>50 000 points) may be slow — the Delaunay construction is O(N log N) but SciPy's implementation uses QHULL which has high overhead for degenerate point sets.

## References

- Guibas, L. & Stolfi, J. (1985). Primitives for the manipulation of general subdivisions. *ACM TOCG* 4(2), 74–123.
- Mays, L.W. (2011). *Water Resources Engineering*, 2nd ed. Wiley. §2 (terrain analysis).
