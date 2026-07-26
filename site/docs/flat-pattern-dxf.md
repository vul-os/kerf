# Flat-Pattern DXF Export

> Export sheet-metal or composite flat patterns as self-contained DXF R12 files — no external DXF library needed.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/sheet_metal.py`
**Shipped**: Wave 8
**LLM tools**: `sheet_metal_flat_pattern`

---

## What it is

Flat-pattern DXF files are the lingua franca between CAD systems and CNC punch presses, laser cutters, and waterjet machines. Kerf's built-in R12 writer emits a minimal but standards-compliant DXF without any third-party dependency: the outline as a closed POLYLINE on layer "0" and bend lines as LINE entities on layer "BEND". Every major CAM system (Radan, Bysoft, Lantek) accepts this format.

## How to use it

### From chat

> "Export the flat pattern of my bracket as a DXF file. The blank is 80 × 60 mm with a 90° bend at y = 30 mm."

### From Python

```python
from kerf_cad_core.sheet_metal import sheet_metal_unfold, sheet_metal_flat_pattern

unfold = sheet_metal_unfold(
    base_width=80.0, base_depth=60.0,
    flange_length=30.0, bend_angle_deg=90.0,
    bend_radius=3.0, thickness=1.5, k_factor=0.44
)
result = sheet_metal_flat_pattern(unfold)
# result["dxf_string"] is the complete DXF R12 text
with open("bracket_flat.dxf", "w") as fh:
    fh.write(result["dxf_string"])
print("Blank dimensions:", result["blank_width_mm"], "×", result["blank_height_mm"], "mm")
```

### From an LLM tool spec

```json
{"base_width": 80, "base_depth": 60,
 "flange_length": 30, "bend_angle_deg": 90,
 "bend_radius": 3.0, "thickness": 1.5, "k_factor": 0.44}
```

## How it works

After `sheet_metal_unfold` computes the developed length using `BA = angle_rad × (R + k × t)`, the flat-pattern writer maps the folded profile back to 2D: the base rectangle is placed at the origin, the bend line is drawn at `x = base_depth`, and the flange rectangle is appended beyond that. The DXF writer constructs the minimal R12 sections: HEADER, TABLES (only the required LAYER table), ENTITIES (POLYLINE + LINE entities), and EOF. Coordinates are in millimetres.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `sheet_metal_unfold(base_width, base_depth, flange_length, bend_angle_deg, bend_radius, thickness, k_factor)` | `dict` | Compute developed dimensions |
| `sheet_metal_flat_pattern(unfold_result)` | `dict` | DXF R12 string + blank dimensions |

Output dict keys: `dxf_string`, `blank_width_mm`, `blank_height_mm`, `bend_lines`.

## Example

```python
r = sheet_metal_flat_pattern(
    sheet_metal_unfold(120, 80, 40, 135, 2.0, 1.2, 0.5)
)
print(r["blank_width_mm"])  # 120
# 135° bend BA = (3π/4) × (2.0 + 0.5×1.2)
```

## Honest caveats

Only single-bend parts are supported in this release (multi-bend sequences require T-4). The DXF R12 writer emits the minimal required entities only — no block references, no arcs for bend zones (bend zones appear as straight lines). Cutout features (holes, notches) are not included in the flat pattern; add them in your CAM system.

## References

- Autodesk DXF Reference 2022 — R12 entity specifications.
- SMACNA (2005). *Architectural Sheet Metal Manual*, 7th ed. §2 (K-factor and bend allowance tables).
