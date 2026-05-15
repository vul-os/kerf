# PCB Panelization

Arrays a single CircuitJSON board into an N×M production panel with separation
features and an optional border rail. Generates Gerber + Excellon fab files for
the entire panel.

## `panelize_board`

**When to use:** User wants to array their board for batch PCB production,
reduce per-unit cost at a fab house (JLC, PCBWay, etc.), or produce a panel
with separation features so boards snap apart after assembly.

**Input:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `circuit_json` | array | required | Parsed CircuitJSON array from the board file |
| `cols` | integer | 2 | Columns in the array |
| `rows` | integer | 2 | Rows in the array |
| `gap_x_mm` | number | 2.0 | Horizontal gap between boards (mm) |
| `gap_y_mm` | number | 2.0 | Vertical gap between boards (mm) |
| `separation` | string | "mousebites" | One of `mousebites`, `vscore`, `tab_route` |
| `alternating_rotate` | boolean | false | Rotate every other board 180° (chequerboard) |
| `mousebite_hole_diameter` | number | 0.8 | Hole diameter for mousebites (mm) |
| `mousebite_hole_pitch` | number | 1.2 | Spacing between mousebite holes (mm) |
| `tab_width_mm` | number | 3.0 | Tab width for tab_route (mm) |
| `tab_count` | integer | 2 | Tabs per board edge for tab_route |
| `tab_hole_diameter` | number | 0.8 | Breakaway hole diameter for tab_route (mm) |
| `add_frame` | boolean | true | Add border rail with tooling holes + fiducials |
| `rail_width_mm` | number | 5.0 | Rail width (mm) |
| `tooling_hole_diameter` | number | 2.0 | Tooling hole diameter (mm) |
| `stem` | string | "panel" | Base filename for output files |

**Output:**

| Field | Description |
|-------|-------------|
| `panel_w_mm`, `panel_h_mm` | Final panel dimensions |
| `board_w_mm`, `board_h_mm` | Source board dimensions |
| `cols`, `rows`, `instance_count` | Array dimensions |
| `separation` | Separation method used |
| `separation_feature_count` | Total separation feature elements |
| `frame` | `{tooling_holes, fiducials}` count or null |
| `gerber_layers` | List of Gerber filenames in the zip |
| `drill_files` | List of Excellon filenames in the zip |
| `panel_descriptor` | Full panel descriptor (pass to `panel_info`) |
| `zip_b64` | Base64-encoded zip of all fab files |
| `zip_filename` | e.g. `panel-fab.zip` |
| `message` | Human-readable summary |

**Example: 2×3 panel with V-score:**
```
panelize_board({
  circuit_json: [...],
  cols: 2,
  rows: 3,
  gap_x_mm: 2.0,
  gap_y_mm: 2.0,
  separation: "vscore",
  add_frame: true,
  rail_width_mm: 5.0,
})
```

## `panel_info`

**When to use:** Inspect an existing panel descriptor without re-generating fab
files. Shows board/panel dimensions, per-instance origins, separation feature
breakdown, and frame details.

**Input:**
- `panel_descriptor` (required) — the `panel_descriptor` object from a
  `panelize_board` result.

**Output:**

| Field | Description |
|-------|-------------|
| `cols`, `rows`, `instance_count` | Array layout |
| `board_w_mm`, `board_h_mm` | Source board size |
| `panel_w_mm`, `panel_h_mm` | Full panel size (including rail) |
| `gap_x_mm`, `gap_y_mm` | Gap settings |
| `separation` | Separation method |
| `alternating_rotate` | Whether chequerboard rotation was used |
| `instances` | `[{col, row, origin_x, origin_y, rotated180}]` |
| `separation_features_by_type` | Count per feature type |
| `total_separation_features` | Total count |
| `frame` | `{tooling_holes, fiducials, rail_x0/y0/x1/y1}` or null |

## Separation methods

### mousebites
Perforated row of drilled holes along each board–board gap. Boards snap apart
along the perforation line after SMT assembly. Recommended for most boards.

- `mousebite_hole_diameter`: 0.5–1.0 mm typical (default 0.8 mm)
- `mousebite_hole_pitch`: 1.0–2.0 mm typical (default 1.2 mm)
- Holes are placed on the gap centre line as non-plated (NPTH) drill hits in
  the Excellon file.

### vscore
V-groove score lines scribed into the board material at the gap centre. The fab
machine scores both sides; boards break cleanly along straight lines. Best for
rectangular boards without protruding components near edges.

- Two V-score lines are emitted per gap (one per side) — encoded as edge_cuts
  draw operations in the GKO Gerber file.
- Minimum gap for V-score: 0 mm (boards can be touching).

### tab_route
Thin routed tabs connect adjacent boards. Each tab has breakaway holes at its
ends for clean separation. Allows curved board outlines and per-edge control.

- `tab_width_mm`: width of each tab (default 3.0 mm).
- `tab_count`: number of tabs per board edge (default 2).
- `tab_hole_diameter`: breakaway hole diameter (default 0.8 mm).
- Tab segments appear on edge_cuts; breakaway holes are NPTH drill hits.

## Frame / rail

When `add_frame: true` (default), a border rail is added outside the board
array. The rail contains:

- **Tooling holes** — 6 NPTH holes (4 corners + 2 mid-edge) sized by
  `tooling_hole_diameter`. These locate the panel on the SMT pick-and-place
  machine fixture.
- **Fiducials** — 3 copper + soldermask openings (triangle pattern) on the top
  rail for vision alignment. Encoded as silk marks in the Gerber GTO layer.
- **Panel outline** — a single closed edge_cuts rectangle enclosing the entire
  panel including rails.

Rail dimensions: `panel_w = array_w + 2×rail_width_mm`,
`panel_h = array_h + 2×rail_width_mm`.

## Fab output wiring

`panelize_board` calls `export_panel_gerber` and `export_panel_excellon`
internally (both exported from `kerf_electronics.tools.panelize`).

These functions:
1. Collect all per-instance `circuit_json` arrays (already in panel
   coordinates) and merge them into a single virtual board.
2. Replace the individual `pcb_board` elements with a single panel-level
   `pcb_board` element at the panel dimensions.
3. Inject the panel outline as a `pcb_outline_path` element — this drives the
   GKO edge_cuts Gerber.
4. Inject vscore/tab lines as `pcb_silkscreen_line` elements on the
   `edge_cuts` layer so they appear in the GKO Gerber.
5. Inject mousebite/tooling holes as `pcb_hole` (NPTH) elements for the
   Excellon NPTH file.
6. Call the single-board `export_gerber` / `export_excellon` writers
   unchanged.

The result is the same `{filename: text}` mapping as the single-board writers,
compatible with `export_fab_package` zip bundling.

## Board model caveat

CircuitJSON does not carry a separate "courtyard" layer. The board bounding
box is derived from the `pcb_board` element's `width`/`height`/`center_x`/
`center_y`. If a board has no `pcb_board` element (e.g. a schematic-only
CircuitJSON), the bbox falls back to the union of all element `x`/`y`
coordinates — which may be inaccurate for boards with large component bodies
that extend beyond their anchor point. Always ensure the input CircuitJSON
includes a `pcb_board` element with accurate dimensions before panelizing.
