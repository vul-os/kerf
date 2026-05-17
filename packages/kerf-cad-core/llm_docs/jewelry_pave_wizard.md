# jewelry_pave_wizard — Automatic Pavé-on-Freeform-Surface Wizard

MatrixGold / RhinoGold parity: distributes stones automatically over a freeform or flat surface, generates normal-aligned seat cutters, and produces bead/prong retention geometry.

## When to use

Use these tools when a jeweller needs to:
- Automatically populate a ring shoulder, halo face, or domed surface with pavé stones
- Choose between hexagonal close-pack, square-grid, or iso-curve flow-line stone distribution
- Specify shared-bead, fishtail, U-cut, or channel retention style
- Check minimum metal bridge between adjacent stone cutters
- Get stone count, total carat, metal-removed volume, and coverage percentage statistics
- Update an existing pavé node (re-run layout with new spacing or bead style)

Keywords: pavé, pave, pave wizard, stone distribution, hex packing, close pack, hexagonal, grid paving, flow line, shared bead, fishtail, u-cut, channel pave, retention style, stone placement, bead, coverage, metal bridge, freeform surface.

## Packing layouts

| Layout | Description |
|---|---|
| `hex` | Hexagonal close-packing (default); odd rows offset by half pitch; highest coverage fraction; mirrors the hand-paved look |
| `grid` | Square/rectangular lattice; lower coverage; calibrated rows |
| `flow_line` | Stones follow parametric iso-curves (constant-u or constant-v "ribbons"); spacing measured along the arc of each iso-curve |

## Retention / bead styles

| Style | Description |
|---|---|
| `shared_bead` | Single raised metal bead at midpoint of a 2×2 cluster; each stone shared by four surrounding beads; classic bright-set pavé |
| `fishtail` | Bright-cut fishtail seat with two small beads flanking each stone along the cross-rail direction |
| `u_cut` | U-shaped groove around each stone with two prong tips at ends; faster on curved surfaces |
| `channel` | Two parallel metal rails running along the v-direction; channel-pavé hybrid |

## Surface input

Pass one of:
- UV bounding box `{u_min, u_max, v_min, v_max}` + optional sample points `{u, v, x, y, z, nx, ny, nz}`; without samples treated as a flat plane with normal +Z
- Triangulated mesh: list of `{x, y, z, nx, ny, nz}` vertex dicts

## Metal bridge validation

After placement the wizard validates:
- `min_bridge_mm` — metal between adjacent stone cutters; flag `"warn": "thin_metal"` if violated
- `min_wall_mm` — metal at the edge of the region

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_pave_wizard` | Appends a `pave_wizard` node; all-in-one: surface + stone size + layout + retention; required: `file_id`, `stone_cut`, stone size (`stone_carat` or `stone_diameter_mm`), surface description |
| `jewelry_pave_wizard_stats` | Read-only: re-compute statistics (stone_count, total_carat, metal_removed_mm3, coverage_pct) from an existing `pave_wizard` node |
| `jewelry_pave_wizard_update` | Adjust spacing, bead style, or edge margin on an existing `pave_wizard` node and re-run the layout |

### Key inputs for `jewelry_pave_wizard`

- `stone_cut` — e.g. `round_brilliant` (most common for pavé)
- `stone_carat` or `stone_diameter_mm` — individual stone size
- `layout` — `hex` | `grid` | `flow_line` (default `hex`)
- `retention_style` — `shared_bead` | `fishtail` | `u_cut` | `channel`
- `stone_spacing_mm` — gap between stone cutters (default 0.10 mm)
- `edge_margin_mm` — clearance from the region boundary (default 0.30 mm)
- `min_bridge_mm` — minimum metal bridge between cutters (default 0.20 mm)
- Surface: `uv_bounds` dict or `mesh_vertices` list

### Statistics returned

- `stone_count` — total placed stones
- `total_carat` — sum of individual carat weights
- `metal_removed_mm3` — approximate volume removed by all seat cutters
- `coverage_pct` — stone projected area / region projected area × 100

## Example

Jeweller: "Fill the 8 mm × 3 mm shoulder of an engagement ring with 0.02 ct round brilliant pavé stones."

1. `jewelry_pave_wizard` — file_id=`<id>`, stone_cut=`round_brilliant`, stone_carat=0.02, layout=`hex`, retention_style=`shared_bead`, uv_bounds={u_min:0, u_max:8, v_min:0, v_max:3}
   → stone_count=18, total_carat=0.36 ct, coverage_pct=72%
2. `jewelry_pave_wizard_stats` — confirm totals without re-writing the node
