# 3D STEP Board Export (MCAD-ECAD co-design)

## `export_board_step`

Generates a 3D STEP AP214 assembly from a CircuitJSON PCB board so the
populated PCB can be dropped into a mechanical assembly for enclosure design,
collision detection, and MCAD-ECAD co-design workflows.

**When to use:**
- User asks for a 3D model of the PCB.
- User wants to import the board into CAD (SOLIDWORKS, Fusion 360, FreeCAD, etc.).
- User wants to check that the board fits in an enclosure.
- User needs a STEP file for mechanical co-design.

**Requires pythonOCC** (not installed by default):
```
conda install -c conda-forge pythonocc-core
```
If pythonOCC is absent the tool returns a clear `OCC_NOT_AVAILABLE` error —
it does **not** crash the server.

---

## Input

| Parameter              | Type    | Default | Description |
|------------------------|---------|---------|-------------|
| `circuit_json`         | array   | —       | Parsed CircuitJSON array (required). |
| `stem`                 | string  | `"board"` | Output filename stem. |
| `board_thickness_mm`   | number  | `1.6`   | PCB substrate thickness mm. Common: 0.8 / 1.0 / 1.2 / **1.6** / 2.0. |
| `drill_holes`          | boolean | `true`  | Subtract cylindrical vias/PTH holes from substrate. |
| `place_components`     | boolean | `true`  | Add parametric box body per placed component. |

---

## Output

```jsonc
{
  "step_filename": "board.step",
  "step_b64": "<base64 STEP bytes>",      // decode to get the AP214 file
  "step_size_bytes": 48210,
  "substrate_volume_mm3": 12800.0,
  "hole_count": 3,
  "component_count": 5,
  "board_thickness_mm": 1.6,
  "message": "STEP export complete: board.step ..."
}
```

Decode `step_b64` and save as `<stem>.step`; open in any MCAD tool.

---

## What gets built

### 1. Board substrate
- Outline sourced from (in priority order):
  1. `pcb_outline_path` elements (explicit polygon)
  2. `pcb_board` / `board` element (rectangular outline via `width` × `height`)
  3. 100 × 100 mm default square
- Polygon face extruded to `board_thickness_mm` along +Z.

### 2. Drilled holes
When `drill_holes=true`, cylinders are Boolean-subtracted from the substrate:

| CircuitJSON element    | Drill diameter attribute |
|------------------------|--------------------------|
| `pcb_via`              | `hole_diameter` / `drill_diameter` / `drill` |
| `pcb_plated_pad`       | `hole_diameter` / `drill_diameter` / `drill_size` |
| `pcb_pad`              | same as above |
| `pcb_hole`             | `hole_diameter` / `diameter` |
| `pcb_mounting_hole`    | same as above |

### 3. Component bodies
When `place_components=true`, each `pcb_component` element gets a box solid:

- **Top-side** components: body placed on top surface (z = `board_thickness_mm`).
- **Bottom-side** components: body hangs below (z = `−body_height`).
- Rotation applied about the component's Z-axis.
- Body dimensions derived from `footprint` name lookup table (covers 0402–QFN,
  SOT-23, SOIC, TQFP, BGA, JST, USB families); unknown footprints fall back to
  a 2.5 × 2.5 × 1.5 mm generic box.
- If a `pcb_component` (or its linked `source_component`) carries a
  `"step_model": "/path/to/body.step"` string and that file exists, it is
  imported and placed instead of synthesising a box.

---

## Example prompt

> "Export a STEP of this board for enclosure design."

→ Call `export_board_step` with the current `circuit_json`.  Offer the
decoded bytes as a `.step` download.

---

## Relationship to other fab tools

| Tool                 | Output           | Use case |
|----------------------|------------------|----------|
| `export_gerber`      | Gerber RS-274X   | PCB manufacture (2D copper layers) |
| `export_fab_package` | Zip (Gerbers + drill + BOM + IPC-2581) | Send to fab house |
| `export_board_step`  | STEP AP214       | 3D MCAD-ECAD co-design |
