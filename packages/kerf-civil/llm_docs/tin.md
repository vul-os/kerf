# kerf-civil · tin.py

Triangulated Irregular Network (TIN) terrain model from survey points.

## Entrypoints

### `build_tin(points) -> TIN`

Construct a Delaunay TIN from (x, y, z) survey points.

```python
from kerf_civil.tin import build_tin

points = [
    (0.0,  0.0, 10.0),
    (10.0, 0.0, 12.0),
    (5.0,  8.0, 15.0),
    (10.0, 8.0, 11.0),
    (0.0,  8.0, 13.0),
]
tin = build_tin(points)
print(tin.triangles.shape)   # (M, 3)
print(tin.points.shape)      # (5, 3)
```

### `contours(tin, interval, *, z_min=None, z_max=None) -> list[list[tuple]]`

Extract contour polylines at a given elevation interval using marching-triangle.

```python
from kerf_civil.tin import build_tin, contours

tin = build_tin(points)
lines = contours(tin, interval=1.0)
# lines: list of polylines; each polyline is a list of (x, y, z) tuples
for line in lines:
    print(f"z={line[0][2]:.1f}: {len(line)} vertices")
```

### `slope(tin, triangle_index) -> float`

Maximum slope angle in degrees (0° = horizontal, 90° = cliff).

```python
from kerf_civil.tin import build_tin, slope
s = slope(tin, 0)   # first triangle
```

### `aspect(tin, triangle_index) -> float`

Compass bearing (0–360°, clockwise from North) of the steepest downslope direction.

```python
from kerf_civil.tin import build_tin, aspect
a = aspect(tin, 0)
```

### `area_2d(tin) -> float`

Total horizontal (projected xy) area of the TIN in m².

### `volume_above(tin, datum_z) -> float`

Volume of material above a horizontal datum plane (m³), using truncated-prism
approximation per triangle.

## LLM tool: `civil_tin_build`

| Parameter          | Type    | Description |
|--------------------|---------|-------------|
| `points`           | array   | [[x,y,z], ...] survey points (min 3) |
| `contour_interval` | number  | Contour interval in metres (default 1.0) |
| `datum_z`          | number  | Datum elevation for volume_above (default 0) |

Returns `{triangle_count, point_count, area_m2, volume_above_datum_m3, contour_count, contours}`.

## TIN dataclass

```python
@dataclass
class TIN:
    points:    np.ndarray  # (N, 3) float64 — [x, y, z]
    triangles: np.ndarray  # (M, 3) int32   — 0-based vertex indices, CCW
```

## Algorithms

- **Triangulation:** scipy.spatial.Delaunay (Qhull backend)
- **Contours:** marching-triangle with linear edge interpolation + greedy segment chaining
- **Volume:** truncated-prism summation (average-height formula per triangle)
- **Aspect:** steepest-descent bearing from triangle normal projected to xy-plane
