# Simple Parametric + Cut List / Flat-Pack Path

Education / maker on-ramp. Given a prompt like *"make me a box 300 mm wide,
200 mm deep, 150 mm tall from 9 mm plywood"*, this module generates:

1. A resolved parametric part definition (panel list).
2. A printable / CNC-able cut list with sheet count and utilisation.
3. A flat-pack layout (x/y placement per sheet).
4. A JSCAD preview code string for the viewport.

Slicing (`packages/kerf-slicing`) and CAM (`packages/kerf-cam`) are already
shipped — this module bridges from the parametric prompt to the cut list,
which is the missing on-ramp for the education/hobbyist persona.

---

## Guided flow

```
list_maker_templates          ← discover what templates exist
       ↓
build_maker_part              ← instantiate with your dimensions
       ↓
compute_maker_cut_list        ← get sheet count + placement layout
       ↓
export_cut_list_csv           ← printable CSV for the workshop
```

---

## Tools

### `list_maker_templates`

List all built-in parametric starter templates.

**Input:** none

**Output:**
```json
{
  "ok": true,
  "count": 5,
  "templates": [
    {
      "key": "box",
      "description": "Open-top rectangular box (5 panels: bottom + 4 sides).",
      "params": {
        "width":     {"default": 200, "min": 10,  "max": 2000, "doc": "External width (mm)"},
        "depth":     {"default": 150, "min": 10,  "max": 2000, "doc": "External depth (mm)"},
        "height":    {"default": 100, "min": 10,  "max": 2000, "doc": "External height (mm)"},
        "thickness": {"default": 9,   "min": 3,   "max": 50,   "doc": "Sheet material thickness (mm)"}
      }
    },
    ...
  ]
}
```

---

### `build_maker_part`

Instantiate a parametric template with user dimensions.

**Input:**
- `template` (required) — one of: `box`, `lid_box`, `enclosure`, `shelf_bracket`, `t_slot_frame`
- `params` — flat object of `{param_name: number}`. Unknown keys ignored; missing keys use defaults.

**Output:**
```json
{
  "ok": true,
  "template": "box",
  "params": {"width": 300, "depth": 200, "height": 150, "thickness": 9},
  "panels": [
    {"name": "bottom", "w": 300, "h": 200, "thickness": 9, "qty": 1, "grain_dir": "width"},
    {"name": "front",  "w": 300, "h": 141, "thickness": 9, "qty": 1, "grain_dir": "width"},
    {"name": "back",   "w": 300, "h": 141, "thickness": 9, "qty": 1, "grain_dir": "width"},
    {"name": "left",   "w": 182, "h": 141, "thickness": 9, "qty": 1, "grain_dir": "height"},
    {"name": "right",  "w": 182, "h": 141, "thickness": 9, "qty": 1, "grain_dir": "height"}
  ],
  "jscad": "// box — flat-layout preview...",
  "description": "Open-top rectangular box..."
}
```

**Panel geometry convention (box family):**
- `bottom`: full external W × D
- `front` / `back`: full external W × (H − T)  — sit on top of bottom
- `left` / `right`: inner D × (H − T)  — slot between front/back

---

### `compute_maker_cut_list`

Convert a panel list into a cut list + flat-pack sheet layout.

**Input:**
- `panels` (required) — the `panels[]` array from `build_maker_part` (or raw panel objects)
- `sheet_w` — stock sheet width (mm), default 1220
- `sheet_h` — stock sheet height (mm), default 2440
- `material` — label string (e.g. `"9mm plywood"`)
- `kerf` — saw/laser kerf gap (mm), default 3
- `margin` — border margin per sheet (mm), default 10
- `allow_rotate` — try 90° rotation for better fit (default `true`)

**Output:**
```json
{
  "ok": true,
  "pieces": [
    {"name": "bottom", "w": 300, "h": 200, "thickness": 9, "qty": 1,
     "area_each_mm2": 60000, "area_total_mm2": 60000},
    ...
  ],
  "sheets_used": 1,
  "sheet_w": 1220,
  "sheet_h": 2440,
  "material": "9mm plywood",
  "kerf_mm": 3,
  "margin_mm": 10,
  "total_area_mm2": 285762,
  "total_sheet_area_mm2": 2976800,
  "utilization": 0.096,
  "placements": [
    {"sheet": 1, "name": "bottom", "x": 10, "y": 10, "w": 300, "h": 200, "rot": 0},
    ...
  ],
  "errors": []
}
```

**Algorithm:** greedy shelf packing — tallest panels first, left-to-right shelves.
New shelf opened when current shelf is full; new sheet opened when no shelf fits.
Rotation tried when `allow_rotate=true`. Deterministic.

---

### `export_cut_list_csv`

Format the cut-list dict as a printable CSV string.

**Input:**
- `cut_list` — the full output dict from `compute_maker_cut_list`

**Output:**
```json
{
  "ok": true,
  "csv": "Part name,Width (mm),Height (mm),...\nbottom,300.0,200.0,...",
  "line_count": 9
}
```

CSV columns: Part name, Width (mm), Height (mm), Thickness (mm), Qty,
Area each (mm²), Area total (mm²), plus a summary footer.

---

## Templates reference

| Key | Description | Key params |
|-----|-------------|------------|
| `box` | Open-top box (5 panels) | width, depth, height, thickness |
| `lid_box` | Closed box + removable lid (7–8 panels) | width, depth, height, thickness, lid_inset |
| `enclosure` | Electronics project enclosure (6 panels) | width, depth, height, thickness, boss_inset |
| `shelf_bracket` | L-bracket (2 panels) | shelf_w, shelf_d, wall_h, thickness |
| `t_slot_frame` | T-slot extrusion frame (cut-list members) | width, height, profile_mm, qty_frames |

---

## End-to-end example

**User prompt:** *"I want to laser-cut an enclosure for a Raspberry Pi,
roughly 150 × 100 × 60 mm in 3 mm acrylic. Give me the cut list."*

```
→ build_maker_part(template="enclosure",
    params={"width":150,"depth":100,"height":60,"thickness":3})

→ compute_maker_cut_list(panels=[...], material="3mm acrylic",
    sheet_w=600, sheet_h=400, kerf=0.2, margin=5)

→ export_cut_list_csv(cut_list={...})
```

Result: 6 panels (base, lid, front, back, left, right), all fitting on
one 600 × 400 mm acrylic sheet with >80% utilisation at 0.2 mm laser kerf.

---

## Integration with slicing + CAM

The `panels[]` array returned by `build_maker_part` maps directly to:

- **kerf-slicing** — use `nest_parts` from `kerf_cad_core.nesting` for
  optimised nesting if utilisation is poor on the greedy layout.
- **kerf-cam** — pass individual panel JSCAD geometry through the CAM
  workflow for CNC toolpath generation (profile cuts, pocket, drill).
- **3D print** — the `jscad` field renders the flat preview in the
  viewport; modify it for 3D-printed corners / joints as needed.
