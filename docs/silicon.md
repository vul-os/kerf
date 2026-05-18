# Silicon — IC Layout and Chip Design

`kerf-silicon` brings IC layout and chip design into Kerf projects. It provides
`.gds` / `.oas` file support (GDSII and OASIS formats), DRC/LVS integration,
and LLM tools for navigating hierarchical cell structures.

---

## Overview

| Property | Value |
|---|---|
| Package | `kerf-silicon` |
| Plugin entry-point | `kerf_silicon.plugin:register` |
| Capability tag | `silicon.layout` |
| Source | `packages/kerf-silicon/` |

---

## File types

| Extension | Kind | Description |
|---|---|---|
| `.gds` | `gds_layout` | GDSII stream format — the industry-standard IC layout interchange |
| `.oas` | `oas_layout` | OASIS format — compressed alternative to GDSII |
| `.lef` | `lef_abstract` | Library Exchange Format — cell abstracts (pin geometry, obstructions) |
| `.def` | `def_floorplan` | Design Exchange Format — placed-and-routed netlist with physical coordinates |
| `.lyp` | `klayout_props` | KLayout layer properties file — display colours and patterns |

GDSII and OASIS files are parsed via
[gdstk](https://heitzmann.github.io/gdstk/) (BSD-2, in-process). LEF/DEF
parsing uses [OpenROAD](https://openroad.readthedocs.io/) invoked as a
subprocess.

---

## Key concepts

### Cells and hierarchy

GDSII/OASIS layouts are organised as a tree of **cells** (also called
structures). Each cell contains:

- **Polygons** — filled shapes on a layer/datatype pair
- **Paths** — stroked wire segments with an endcap style
- **Labels** — text annotations, typically pin names
- **References** (`SREF` / `AREF`) — instances of other cells, optionally
  arrayed

The top-level cell (usually named `TOP` or after the chip) is the root of the
hierarchy. Sub-cells represent standard cells, macros, I/O pads, and memory
blocks.

### Layers

Each polygon or path is tagged with a `(layer, datatype)` integer pair. Process
Design Kits (PDKs) define the semantics (e.g. `M1` metal, `POLY` polysilicon,
`NWELL` n-well implant). Kerf reads layer mappings from `.lyp` files or from a
PDK `layers.json` sidecar.

---

## LLM tools

### `list_gds_cells`

List all cells in a GDSII or OASIS file, with instance counts and bounding
boxes.

```json
{
  "file_id": "<uuid of .gds file in the project>"
}
```

Returns:

```json
{
  "top_cell": "TOP",
  "cells": [
    {
      "name": "inv_x1",
      "bbox": { "x_min": 0.0, "y_min": 0.0, "x_max": 1.4, "y_max": 2.8 },
      "polygon_count": 12,
      "reference_count": 0
    }
  ]
}
```

---

### `get_gds_cell`

Extract all geometry (polygons, labels, references) from a named cell.

```json
{
  "file_id": "<uuid>",
  "cell_name": "nand2_x2",
  "include_children": false
}
```

Setting `include_children: true` flattens all sub-cell references into the
top-level polygon list — useful for DRC checks.

---

### `run_drc`

Run a Design Rule Check against a built-in or project-supplied ruleset.

```json
{
  "file_id": "<uuid>",
  "ruleset": "sky130A",
  "cell": "TOP"
}
```

Built-in rulesets: `sky130A`, `gf180mcu`, `generic_2um`.

Returns a list of violations:

```json
{
  "violations": [
    {
      "rule": "M1.width",
      "layer": [49, 0],
      "message": "Metal 1 width 0.12 µm < 0.14 µm minimum",
      "location": { "x": 3.4, "y": 7.1 }
    }
  ],
  "summary": { "errors": 1, "warnings": 0 }
}
```

---

## HTTP routes

| Method | Path | Description |
|---|---|---|
| `POST` | `/silicon/parse-gds` | Parse a `.gds` / `.oas` file and return cell tree metadata |
| `POST` | `/silicon/drc` | Run DRC against a named ruleset |
| `GET` | `/silicon/cells/{file_id}` | List cells (cached after first parse) |

---

## Typical workflow

1. Upload a `.gds` file to a Kerf project via the file tree or drag-and-drop.
2. Kerf auto-detects the `gds_layout` kind and renders a layer stack preview.
3. Use `list_gds_cells` to navigate the cell hierarchy.
4. Run `run_drc` with your process node's ruleset to check for violations.
5. Iterate: edit the layout in your EDA tool (e.g. KLayout), re-upload, re-run.

---

## Related documentation

| Topic | Path |
|---|---|
| Electronics workflow | `docs/electronics.md` |
| Import pipeline | `docs/imports.md` |
| Plugin development | `docs/plugins-development.md` |
| LLM tool authoring | `docs/llm-tool-authoring.md` |
