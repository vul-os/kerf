# Civil Horizontal Alignment

> AASHTO Green Book road/highway alignment geometry — tangents, circular arcs, and clothoid (Euler) spiral transitions.

**Module**: `packages/kerf-civil/src/kerf_civil/horizontal_alignment.py`
**Shipped**: Wave 9
**LLM tools**: `civil_alignment_geometry`, `civil_alignment_station`

---

## What it is

A horizontal alignment defines the plan-view path of a road or railway in the map plane. AASHTO requires three element types: straight tangents, simple circular arcs (constant curvature), and clothoid spirals (linearly increasing curvature) at tangent-to-curve transitions to limit the rate of change of centripetal acceleration. This module computes element geometry, station-coordinate relationships, and AASHTO design-speed superelevation.

## How to use it

### From chat

> "Design a horizontal alignment: 200 m tangent north, then a right-hand circular arc R = 400 m with 45° deflection, followed by a 60 m clothoid entry spiral. Give me the coordinates at every 20 m station."

### From Python

```python
from kerf_civil.horizontal_alignment import (
    TangentSegment, CircularArc, ClothoidSpiral,
    HorizontalAlignment, aashto_superelevation
)
import math

alignment = HorizontalAlignment(elements=[
    TangentSegment(length=200.0),
    CircularArc(radius=400.0, delta_rad=math.radians(45), right=True),
])
pts = alignment.sample_coords(interval=20.0)
print(f"{len(pts)} sample points")
e = aashto_superelevation(design_speed_mph=60, radius_ft=1312)  # 400 m
print(f"Superelevation: {e:.1f}%")
```

### From an LLM tool spec

```json
{"elements": [
  {"type": "tangent", "length": 200},
  {"type": "arc", "radius": 400, "delta_deg": 45, "right": true}
], "sample_interval_m": 20}
```

## How it works

Each element implements `arc_length()`, `end_bearing()`, and `coords_at(s, start_xy)`. Clothoid spiral x/y coordinates are computed using Fresnel integrals truncated at sufficient precision. Stationing is cumulative from the alignment start. `HorizontalAlignment.sample_coords(interval)` chains elements and transforms each element-local coordinate into the alignment-global frame by tracking the running bearing and position. AASHTO superelevation uses the tabulated emax = 8% design values per AASHTO Green Book Table 3-7.

## API reference

| Class / Function | Key methods | Purpose |
|---|---|---|
| `TangentSegment(length, bearing_rad)` | `coords_at(s)` | Straight section |
| `CircularArc(radius, delta_rad, right)` | `coords_at(s)`, `chord()`, `tangent_length()` | Simple curve |
| `ClothoidSpiral(length, radius_end)` | `coords_at(s)`, `theta_s` | Transition spiral |
| `HorizontalAlignment(elements)` | `sample_coords(interval)`, `station_at(point)` | Compound alignment |
| `aashto_superelevation(design_speed_mph, radius_ft)` | — | Design superelevation (%) |

## Example

```python
spiral = ClothoidSpiral(length=80.0, radius_end=300.0)
print(f"Spiral angle: {math.degrees(spiral.theta_s):.2f}°")
# = 80/(2×300) radians = 7.64°
x, y = spiral.coords_at(80.0)
print(f"End coords: ({x:.3f}, {y:.3f})")
```

## Honest caveats

Fresnel integral evaluation uses a power-series approximation; accuracy is within 0.01 mm for spirals under 200 m at typical highway radii. Vertical alignment (profile) is a separate module (`vertical_alignment.py`). AASHTO superelevation tables cover US highway practice only; other national standards (DMRB, RVS) require different lookup tables.

## References

- AASHTO (2018). *A Policy on Geometric Design of Highways and Streets* (Green Book), 7th ed. §3-2 (superelevation), §3-4 (spirals).
- Chaudhry, M.H. (1993). *Open-Channel Hydraulics*, 2nd ed. §1 (horizontal geometry basics).
