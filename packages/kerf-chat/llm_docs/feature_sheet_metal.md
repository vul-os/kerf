# Sheet metal tools — T-1 / T-2 / T-3

Three tools cover the full workflow from folded solid → developed length →
flat-pattern DXF.  They share the same parameter set (`bend_radius`,
`bend_angle_deg`, `thickness`, `k_factor`, `flange_length`); T-2 and T-3 take
those values directly and return computed results without writing to the DB.

| Tool | Task | Description |
|---|---|---|
| `sheet_metal_flange` | T-1 | Append a folded B-rep node to a `.feature` file |
| `sheet_metal_unfold` | T-2 | Compute developed length + bend-line table (pure math, no DB write) |
| `sheet_metal_flat_pattern` | T-3 | Emit a 2D flat-pattern as DXF R12 (no DB write) |

> **Deferred (T-4)**: `sheet_metal_bend_table` — material-specific allowance
> lookup from DB.

---

# `sheet_metal_flange` — folded sheet-metal base plate + flange (T-1)

Appends a `sheet_metal_flange` node to a `.feature` file.  Produces a single
folded solid B-rep: a rectangular base plate with one bent flange along a
chosen top edge.  Wall thickness is uniform throughout.

> The `k_factor` stored on the node is consumed by `sheet_metal_unfold` (T-2)
> to compute the neutral-axis developed length.

## Tool name

`sheet_metal_flange`

## Schema

```json
{
  "id": "sheet_metal_flange-1",
  "op": "sheet_metal_flange",
  "base_width": 100,
  "base_depth": 80,
  "thickness": 1.5,
  "edge_ref": "top-front",
  "flange_length": 25,
  "bend_angle_deg": 90,
  "bend_radius": 2,
  "k_factor": 0.44
}
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `file_id` | UUID string | — | Target `.feature` file (required). |
| `base_width` | number (mm) | 50 | X-dimension of the blank base plate. |
| `base_depth` | number (mm) | 50 | Y-dimension of the blank base plate. |
| `thickness` | number (mm) | 1.0 | Uniform sheet wall thickness. Must be > 0. |
| `edge_ref` | string | `"top-front"` | Which top edge to fold along. See edge reference below. |
| `flange_length` | number (mm) | 20 | Straight-wall length after the bend arc. Must be > 0. |
| `bend_angle_deg` | number (°) | 90 | How far the flange rotates from the base plane. Range (0, 180]. 90° = right-angle. |
| `bend_radius` | number (mm) | 1.0 | Inside radius of the bend arc. Must be > 0. |
| `k_factor` | number | 0.44 | Neutral-axis offset fraction, in (0, 1). Stored for unfold (T-2). |
| `id` | string | auto | Optional explicit node id. |

### `edge_ref` values

| Value | Description |
|---|---|
| `"top-front"` | Front edge of the top face (Y=0 side). Default. |
| `"top-back"` | Back edge (Y=base_depth side). |
| `"top-left"` | Left edge (X=−base_width/2 side). |
| `"top-right"` | Right edge (X=+base_width/2 side). |

Numeric edge references (`"edge-0"`, `"edge-3"`, etc.) from the inspector
are also accepted by the worker; the four named values are recommended for
LLM invocation.

### `k_factor` guidance

| Material | Typical k-factor |
|---|---|
| Hard / tool steel | 0.33 |
| Mild steel | 0.44 (default) |
| Stainless steel | 0.38 |
| Aluminium (5052) | 0.44–0.50 |
| Soft aluminium | 0.50 |

The k-factor does **not** change the folded geometry.  It is stored on the
node so that the unfold solver (T-2) can compute:
```
bend_allowance = (bend_radius + k_factor × thickness) × bend_angle_rad
```

## Geometry

1. **Base plate** — a box `base_width × base_depth × thickness` at Z = 0,
   centred on X.
2. **Bend arc** — a cylindrical sector of inner radius `bend_radius` and outer
   radius `bend_radius + thickness`, swept through `bend_angle_deg` about the
   chosen fold edge.
3. **Flange wall** — a rectangular prism of length `flange_length`, thickness
   `thickness`, width `base_width`, in the direction tangent to the arc at the
   far end.
4. The three volumes are **fused** into one watertight solid.

### OCCT-binding note

The bend arc is built with `BRepPrimAPI_MakeCylinder` (sector form) rather
than `BRepOffsetAPI_MakeOffsetShape` (not exposed in the current WASM build).
This is geometrically equivalent for the folded-shape purpose and does not
require additional WASM capabilities.

## Validation errors

| Code | Condition |
|---|---|
| `BAD_ARGS` | `edge_ref` is empty. |
| `BAD_ARGS` | `flange_length <= 0`. |
| `BAD_ARGS` | `bend_angle_deg` not in (0, 180]. |
| `BAD_ARGS` | `bend_radius <= 0`. |
| `BAD_ARGS` | `thickness <= 0`. |
| `BAD_ARGS` | `k_factor` not strictly in (0, 1). |
| `BAD_ARGS` | `base_width <= 0` or `base_depth <= 0`. |
| `NOT_FOUND` | `file_id` not found or is not a `.feature` file. |

## Example: 90° right-angle bracket

```python
result = await client.call("sheet_metal_flange", {
    "file_id": "<feature-file-uuid>",
    "base_width": 120,
    "base_depth": 80,
    "thickness": 2.0,
    "edge_ref": "top-front",
    "flange_length": 40,
    "bend_angle_deg": 90,
    "bend_radius": 3,
    "k_factor": 0.44,
})
```

Produces a 120 × 80 × 2 mm flat base with a 40 mm upright flange at the
front edge, inside bend radius 3 mm, suitable for a mild-steel bracket.

## Example: obtuse return flange

```python
result = await client.call("sheet_metal_flange", {
    "file_id": "<feature-file-uuid>",
    "base_width": 60,
    "base_depth": 40,
    "thickness": 1.2,
    "edge_ref": "top-back",
    "flange_length": 15,
    "bend_angle_deg": 135,
    "bend_radius": 1.5,
    "k_factor": 0.38,   # stainless
})
```

## Response

```json
{
  "ok": true,
  "data": {
    "file_id": "<uuid>",
    "id": "sheet_metal_flange-1",
    "op": "sheet_metal_flange",
    "edge_ref": "top-front",
    "flange_length": 25.0,
    "bend_angle_deg": 90.0,
    "bend_radius": 2.0,
    "thickness": 1.5,
    "k_factor": 0.44,
    "note": "Folded B-rep produced. Unfold / flat-pattern: use sheet_metal_unfold (T-2, not yet shipped)."
  }
}
```

## Roadmap / follow-ups

| Task | Status | Description |
|---|---|---|
| T-2 | **shipped** | `sheet_metal_unfold` — neutral-axis bend-allowance unfold solver |
| T-3 | **shipped** | `sheet_metal_flat_pattern` — 2D outline + bend lines, DXF R12 export |
| T-4 | deferred | `sheet_metal_bend_table` — material-specific allowance lookup from DB |

---

# `sheet_metal_unfold` — developed length + bend lines (T-2)

Computes the flat (developed) length of a flanged part and the positions of the
two bend lines.  **Pure-Python; no DB write.**  All inputs come directly from
the `sheet_metal_flange` node parameters.

## Bend-allowance formula

```
BA = angle_rad × (bend_radius + k_factor × thickness)
```

where `angle_rad = bend_angle_deg × π / 180`.

Developed length:
```
developed_length = base_length + BA + flange_length
```

## Tool name

`sheet_metal_unfold`

## Schema

```json
{
  "base_length": 80,
  "flange_length": 25,
  "bend_angle_deg": 90,
  "bend_radius": 2,
  "thickness": 1.5,
  "k_factor": 0.44
}
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `base_length` | number (mm) | — | Base plate dimension in the bend direction. Use `base_depth` for front/back bends; `base_width` for left/right bends. |
| `flange_length` | number (mm) | — | Straight-wall length after the bend arc. Matches the flange node. |
| `bend_angle_deg` | number (°) | 90 | Bend angle. Matches the flange node. |
| `bend_radius` | number (mm) | 1.0 | Inside bend radius. Matches the flange node. |
| `thickness` | number (mm) | 1.0 | Sheet thickness. Matches the flange node. |
| `k_factor` | number | 0.44 | Neutral-axis offset fraction, in (0, 1). Matches the flange node. |

### `k_factor` quick reference

| Material | Typical k-factor |
|---|---|
| Hard / tool steel | 0.33 |
| Mild steel | 0.44 (default) |
| Stainless steel | 0.38 |
| Aluminium (5052) | 0.44–0.50 |

## Response

```json
{
  "ok": true,
  "data": {
    "bend_allowance": 4.1783,
    "developed_length": 109.178,
    "bend_lines": [
      {"position": 80.0, "label": "bend-start"},
      {"position": 84.178, "label": "bend-end"}
    ]
  }
}
```

## Example: 90° mild-steel bracket

```python
result = await client.call("sheet_metal_unfold", {
    "base_length": 80,       # base_depth for a top-front bend
    "flange_length": 25,
    "bend_angle_deg": 90,
    "bend_radius": 2,
    "thickness": 1.5,
    "k_factor": 0.44,        # mild steel
})
# bend_allowance ≈ 4.178 mm
# developed_length ≈ 109.178 mm
```

---

# `sheet_metal_flat_pattern` — 2D DXF flat pattern (T-3)

Runs the T-2 unfold solver and emits a **self-contained DXF R12 string** with:
- Closed `POLYLINE` outline on layer `0` (the unfolded rectangle).
- `LINE` entities on layer `BEND` for each bend line.

**No DB write; returns the DXF string directly.**

> **DXF implementation note**: `kerf-cad-core` does not depend on
> `kerf-imports`.  Rather than add a cross-package dependency, the DXF R12
> string is generated by a small inline writer (~25 lines, same group-code
> format as `kerf_imports.tools.draft._export_dxf`).

## Tool name

`sheet_metal_flat_pattern`

## Schema

```json
{
  "base_length": 80,
  "width": 120,
  "flange_length": 25,
  "bend_angle_deg": 90,
  "bend_radius": 2,
  "thickness": 1.5,
  "k_factor": 0.44
}
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `base_length` | number (mm) | — | Base plate dimension in the bend direction (see `sheet_metal_unfold`). |
| `width` | number (mm) | — | Flat-pattern width perpendicular to the bend. Use `base_width` for front/back bends; `base_depth` for left/right. |
| `flange_length` | number (mm) | — | Straight-wall length after the bend. |
| `bend_angle_deg` | number (°) | 90 | Bend angle. |
| `bend_radius` | number (mm) | 1.0 | Inside bend radius. |
| `thickness` | number (mm) | 1.0 | Sheet thickness. |
| `k_factor` | number | 0.44 | Neutral-axis offset fraction. |

## Response

```json
{
  "ok": true,
  "data": {
    "dxf": "0\nSECTION\n2\nHEADER\n...\n0\nEOF",
    "developed_length": 109.178,
    "bend_allowance": 4.178,
    "bend_lines": [
      {"position": 80.0, "label": "bend-start"},
      {"position": 84.178, "label": "bend-end"}
    ],
    "width": 120.0,
    "dxf_note": "Self-contained DXF R12. Outline on layer '0'; bend lines on layer 'BEND'. kerf-imports DXF writer not used (no cross-package dep)."
  }
}
```

## Example

```python
result = await client.call("sheet_metal_flat_pattern", {
    "base_length": 80,    # base_depth (top-front bend)
    "width": 120,         # base_width
    "flange_length": 25,
    "bend_angle_deg": 90,
    "bend_radius": 2,
    "thickness": 1.5,
    "k_factor": 0.44,
})
# Write DXF to file:
open("bracket_flat.dxf", "w").write(result["dxf"])
```

## DXF layout

```
X ──────────────────────────────────────→  (developed_length)
│← base_length →│← BA →│← flange_length →│
0               80    84.18             109.18   mm
                 ↑      ↑
              bend-start bend-end  (BEND layer LINE entities)
```
