# kicad_bridge_tools

*Module: `kerf_electronics.tools.kicad_bridge_tools` · Domain: electronics*

This module registers **2** LLM tool(s):

- [`elec_export_kicad`](#elec-export-kicad)
- [`elec_import_kicad_pcb`](#elec-import-kicad-pcb)

---

## `elec_export_kicad`

Export a Kerf schematic + PCB layout to a KiCad project directory (*.kicad_pro + *.kicad_sch + *.kicad_pcb). The exported .kicad_pcb has all component footprints placed but routes/tracks intentionally empty — open it in KiCad Pcbnew to perform interactive routing, then use elec_import_kicad_pcb to bring the routed result back into Kerf. Returns the paths to the three written files plus metadata (component count, net count, layer count).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "array",
      "description": "Parsed CircuitJSON array from the active board/schematic file. Should contain source_component, source_net, source_trace, and pcb_component entries.",
      "items": {
        "type": "object"
      }
    },
    "output_dir": {
      "type": "string",
      "description": "Absolute or relative path to a directory where the KiCad project files will be written.  The directory is created if it does not exist."
    },
    "stem": {
      "type": "string",
      "description": "Base filename stem for all three files (e.g. 'my_board' produces my_board.kicad_pro, my_board.kicad_sch, my_board.kicad_pcb). Defaults to 'board'."
    }
  },
  "required": [
    "circuit_json",
    "output_dir"
  ]
}
```

---

## `elec_import_kicad_pcb`

Import a routed *.kicad_pcb file back into Kerf after interactive routing in KiCad. Extracts all routed track segments, vias, and updated footprint positions. Returns structured routing data that Kerf's DRC, simulation, and fabrication tools can consume.  Use this after the user has finished routing in KiCad Pcbnew and saved the .kicad_pcb file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "pcb_path": {
      "type": "string",
      "description": "Path to the routed *.kicad_pcb file.  Must be an absolute path or relative to the current working directory."
    }
  },
  "required": [
    "pcb_path"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
