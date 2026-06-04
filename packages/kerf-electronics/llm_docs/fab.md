# fab

*Module: `kerf_electronics.tools.fab` · Domain: electronics*

This module registers **3** LLM tool(s):

- [`export_gerber`](#export-gerber)
- [`export_fab_package`](#export-fab-package)
- [`export_board_step`](#export-board-step)

---

## `export_gerber`

Export a CircuitJSON board as Gerber RS-274X files (one per layer). Returns a list of {filename, content_b64} objects — one entry per layer (GTL top copper, GBL bottom copper, GTO/GBO silkscreen, GTS/GBS soldermask, GKO board outline, inner layers if present). Pass the circuit_json array from the active .circuit.tsx file. Use this to generate individual Gerber files; for a complete fab package use export_fab_package instead.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "array",
      "description": "Parsed CircuitJSON array from the board file.",
      "items": {
        "type": "object"
      }
    },
    "stem": {
      "type": "string",
      "description": "Base filename stem (no extension). Defaults to 'board'."
    }
  },
  "required": [
    "circuit_json"
  ]
}
```

---

## `export_fab_package`

Bundle a complete PCB fabrication package from a CircuitJSON board. Returns a zip archive (base64-encoded) containing: Gerber RS-274X per-layer files, Excellon drill file(s), pick-and-place CSVs (top + bottom), fab BOM CSV, and an IPC-2581 XML. This is the deliverable a fab house ingests (upload to JLC/PCBWay/MacroFab). The zip filename is <stem>-fab.zip.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "array",
      "description": "Parsed CircuitJSON array from the board file.",
      "items": {
        "type": "object"
      }
    },
    "stem": {
      "type": "string",
      "description": "Base filename stem used for all files (default: 'board')."
    }
  },
  "required": [
    "circuit_json"
  ]
}
```

---

## `export_board_step`

Export a CircuitJSON PCB board as a 3D STEP assembly for MCAD-ECAD co-design. Builds: (1) the board substrate — edge_cuts outline extruded to board_thickness_mm (default 1.6 mm FR4); (2) drilled holes subtracted from the substrate; (3) a parametric box body for each placed component at its (x, y, rotation, side). If a component element carries a 'step_model' path to an existing STEP file, that model is imported instead. Returns the STEP file bytes as base64 so the user can download it and drop the PCB into a mechanical assembly (enclosure fit-check, collision detection, etc.). Requires pythonOCC (conda install -c conda-forge pythonocc-core). If pythonOCC is not installed, returns an error with install instructions. Use export_fab_package for 2D fab files (Gerbers/drill/BOM); use this tool when the user needs a 3D model of the board.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "array",
      "description": "Parsed CircuitJSON array from the board file.",
      "items": {
        "type": "object"
      }
    },
    "stem": {
      "type": "string",
      "description": "Base filename stem for the STEP file (default: 'board')."
    },
    "board_thickness_mm": {
      "type": "number",
      "description": "PCB substrate thickness in millimetres. Default 1.6 mm (standard FR4). Common values: 0.8, 1.0, 1.2, 1.6, 2.0."
    },
    "drill_holes": {
      "type": "boolean",
      "description": "If true (default), subtract cylindrical holes from the substrate using via and PTH pad coordinates. Set false for a solid block."
    },
    "place_components": {
      "type": "boolean",
      "description": "If true (default), add a parametric body solid for each placed pcb_component. Set false for a board-only export."
    }
  },
  "required": [
    "circuit_json"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
