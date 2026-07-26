# Sheet Metal Flange & Flat-Pattern

> K-factor-aware bend-allowance unfolding and minimal DXF R12 flat-pattern export for sheet metal parts.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/sheet_metal.py`
**Shipped**: Wave 7
**LLM tools**: `sheet_metal_flange`, `sheet_metal_unfold`, `sheet_metal_flat_pattern`

---

## What it is

Sheet metal parts are designed folded but fabricated flat. The critical calculation is bend allowance: how much flat material is consumed by a bend, given the neutral-axis position (K-factor). Get it wrong and the flanges come out the wrong length after press-braking. This module handles flange creation, neutral-axis unfolding, and DXF export for the flat blank — no external DXF library required.

## How to use it

### From chat

> "Create a sheet metal flange: 2 mm thick mild steel, 4 mm bend radius, 90° bend along the top edge, 30 mm flange length. Then export the flat pattern as DXF."

### From Python

```python
from kerf_cad_core.sheet_metal import (
    sheet_metal_unfold, sheet_metal_flat_pattern
)

unfold_result = sheet_metal_unfold(
    base_width=80.0, base_depth=60.0,
    flange_length=30.0, bend_angle_deg=90.0,
    bend_radius=4.0, thickness=2.0, k_factor=0.45
)
print("Developed length:", unfold_result["developed_length_mm"])

dxf = sheet_metal_flat_pattern(unfold_result)
with open("blank.dxf", "w") as f:
    f.write(dxf["dxf_string"])
```

### From an LLM tool spec

```json
{"base_width": 80, "base_depth": 60,
 "flange_length": 30, "bend_angle_deg": 90,
 "bend_radius": 4.0, "thickness": 2.0,
 "edge_ref": "top", "k_factor": 0.45}
```

## How it works

Bend allowance is computed as `BA = angle_rad × (bend_radius + k_factor × thickness)`. The K-factor (0–1) represents the neutral-axis position as a fraction of the stock thickness from the inside surface. The folded B-rep is built in OCCT: a base plate fused with a quarter-cylinder (or partial arc) bend zone and the flange wall. The flat-pattern DXF uses a minimal inline R12 writer — the outline is a closed POLYLINE on layer "0" and bend lines are LINE entities on layer "BEND", producing files compatible with all CAM systems.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `sheet_metal_unfold(base_width, base_depth, flange_length, bend_angle_deg, bend_radius, thickness, k_factor)` | `dict` | Compute developed length + bend-line table |
| `sheet_metal_flat_pattern(unfold_result)` | `dict` | Emit flat-pattern as DXF R12 string |
| `sheet_metal_flange(...)` | `dict` | Append flange feature to `.feature` file |

## Example

```python
r = sheet_metal_unfold(100, 50, 40, 90, 3.0, 1.5, 0.33)
# r["developed_length_mm"] = 100 + BA(90°, r=3, t=1.5, k=0.33)
# r["bend_lines"] = [{"position_mm": ..., "angle_deg": 90}]
```

## Honest caveats

Multi-flange sequences (successive bends on the same blank) are deferred to T-4. Material-specific K-factor lookup from a database is not yet implemented — pass k_factor explicitly (0.33 for soft metals, 0.45 for mild steel, 0.50 for stiff alloys). The OCCT flange B-rep requires `pythonocc-core`; the unfold/DXF functions are pure Python and always available.

## References

- SMACNA (2005). *Architectural Sheet Metal Manual*, 7th ed. §2 (bend allowance).
- Oehler, L.K. & Kaiser, R.E. (1966). Bending in sheet metal. *Trans. ASME B*, 88(4).
