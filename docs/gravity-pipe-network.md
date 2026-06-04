# Gravity Pipe Network (Sewer / Drainage)

> Manning's equation for part-full circular sewers and trapezoidal channels — normal depth, capacity, and storm runoff sizing.

**Module**: `packages/kerf-civil/src/kerf_civil/hydraulics_gravity.py`, `storm.py`
**Shipped**: Wave 11B2
**LLM tools**: `civil_sewer_manning_capacity`, `civil_storm_rational`

---

## What it is

Gravity sewers and storm drains operate under open-channel flow where the driving force is gravity rather than pressure. The key design question is: for a given pipe diameter, slope, and roughness, what is the normal (full) flow capacity, and at what depth does the design flow actually run? Getting this wrong leads to either surcharging (flooding) or oversized, expensive pipes. This module implements the standard Manning's equation for circular sections (part-full and full) and trapezoidal channels, plus the Rational Method for peak runoff estimation.

## How to use it

### From chat

> "Size a 600 mm diameter concrete sewer (n = 0.013) at 0.5% slope for a peak flow of 150 L/s. What is the normal-depth ratio y/D?"

### From Python

```python
from kerf_civil.hydraulics_gravity import (
    circular_full_flow, circular_normal_depth, circular_capacity_at_depth
)

d = 0.6   # 600 mm pipe, metres
Q_full = circular_full_flow(d, n=0.013, slope=0.005)
print(f"Full-flow capacity: {Q_full*1000:.1f} L/s")

yd = circular_normal_depth(d, n=0.013, slope=0.005, Q=0.150)
print(f"Normal depth y/D: {yd:.3f}  ({yd*d*1000:.0f} mm)")
```

### From an LLM tool spec

```json
{"diameter_m": 0.6, "manning_n": 0.013, "slope": 0.005,
 "design_flow_m3s": 0.150, "check": "normal_depth"}
```

## How it works

Manning's equation in SI: Q = (1/n) × A × R^(2/3) × S^(1/2). For a circular pipe at depth y: θ = 2 arccos(1 − 2y/d), A = d²(θ − sin θ)/8, R = A/P where P = dθ/2. Normal depth is found by Newton–Raphson iteration on Q(y) = Q_design (converges in < 60 iterations to tolerance 10⁻⁸). For trapezoidal channels: A = (b + zy)y, P = b + 2y√(1 + z²). Storm runoff: Q = C·i·A using the Rational Method (SI: C dimensionless, i in mm/hr, A in ha), standard for urban drainage catchments up to ~80 ha.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `circular_full_flow(d, n, slope)` | `float` (m³/s) | Full-pipe capacity |
| `circular_normal_depth(d, n, slope, Q)` | `float` (y/D ratio) | Normal-depth solve |
| `circular_capacity_at_depth(d, n, slope, y)` | `float` (m³/s) | Capacity at given depth |
| `circular_section_geometry(d, y)` | `dict` | Area, P, R, top-width |
| `trapezoidal_normal_depth(b, z, n, slope, Q)` | `float` (depth m) | Open-channel normal depth |
| `rational_method(C, i_mm_hr, area_ha)` | `float` (m³/s) | Peak storm runoff |

## Example

```python
from kerf_civil.hydraulics_gravity import circular_section_geometry
geom = circular_section_geometry(d=0.9, y=0.675)  # 75% full
print(f"Area: {geom['area']:.4f} m², R: {geom['hydraulic_radius']:.4f} m")
```

## Honest caveats

Manning's n values must be supplied by the caller — Kerf does not include a pipe-material roughness database. Normal-depth iteration may not converge for extremely low slopes (< 0.0001) or near-full pipes; the function returns the last iterate with a warning flag. The Rational Method is valid only for catchments where the time of concentration equals the storm duration; it overestimates peak flow for large or irregular catchments.

## References

- Chaudhry, M.H. (2008). *Open-Channel Hydraulics*, 2nd ed. Springer. §2.5.
- Mays, L.W. (2011). *Water Resources Engineering*, 2nd ed. Wiley. Table 4.1 (circular section).
- Kuichling, E. (1889). The relation between the rainfall and the discharge of sewers. *Trans. ASCE* 20, 1–56.
