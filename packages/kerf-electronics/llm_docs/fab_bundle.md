# fab_bundle

*Module: `kerf_electronics.tools.fab_bundle` · Domain: electronics*

This module registers **3** LLM tool(s):

- [`fab_bundle_export`](#fab-bundle-export)
- [`fab_readme_export`](#fab-readme-export)
- [`fab_vendor_presets`](#fab-vendor-presets)

---

## `fab_bundle_export`

Generate a one-click PCB fabrication bundle from a CircuitJSON board, ready to upload to a fab house. Returns a zip archive (base64-encoded) containing vendor-specific Gerber files (one per layer, with the fab house's expected naming), Excellon drill file, pick-and-place CSV, BOM CSV, optional IPC-2581 XML, and a README.txt with stackup/upload instructions. Supported vendors: jlcpcb (default), pcbway, oshpark, seeed, allpcb. JLCPCB output uses 'gerber_*.gbr' naming + CPL/BOM format required by their upload portal. OSHPark output uses standard Gerber extensions (.GTL/.GBL/.GTS etc.) that their parser detects automatically. Use this for the 'export to fab' / 'download gerbers' user action.

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
    "vendor": {
      "type": "string",
      "description": "Target fab house. One of: jlcpcb, pcbway, oshpark, seeed, allpcb. Defaults to 'jlcpcb'.",
      "enum": [
        "jlcpcb",
        "pcbway",
        "oshpark",
        "seeed",
        "allpcb"
      ]
    },
    "stem": {
      "type": "string",
      "description": "Base filename stem used for all output files (e.g. 'my-board'). Defaults to 'board'."
    },
    "copper_weight": {
      "type": "string",
      "description": "Copper weight for outer layers, e.g. '1oz', '2oz'. Default '1oz'."
    },
    "surface_finish": {
      "type": "string",
      "description": "PCB surface finish. Common values: 'HASL(with lead)', 'HASL(lead free)', 'ENIG', 'OSP'. Vendor default if omitted."
    },
    "soldermask": {
      "type": "string",
      "description": "Soldermask colour: 'green', 'black', 'blue', 'red', 'white', 'yellow', 'purple'. Default 'green'."
    },
    "silkscreen": {
      "type": "string",
      "description": "Silkscreen colour: 'white' or 'black'. Default 'white'."
    },
    "board_thickness": {
      "type": "string",
      "description": "Board thickness string, e.g. '1.6mm', '0.8mm', '2.0mm'. Default '1.6mm'."
    },
    "special": {
      "type": "string",
      "description": "Special fabrication instructions appended to the README."
    },
    "include_ipc2581": {
      "type": "boolean",
      "description": "If true, include an IPC-2581 XML in the bundle. Default: false for JLCPCB/OSHPark, true for PCBWay."
    }
  },
  "required": [
    "circuit_json"
  ]
}
```

---

## `fab_readme_export`

Generate a vendor-specific README.txt for a PCB fabrication bundle. The README includes: PCB stackup description, copper weight, surface finish, soldermask/silkscreen colours, board dimensions (extracted from the CircuitJSON), file contents list, and step-by-step upload instructions for the chosen fab house. Use this when the user wants to see or preview the fab instructions, or when generating a fab package for a human to review before uploading.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "array",
      "description": "Parsed CircuitJSON array (used to extract board dimensions).",
      "items": {
        "type": "object"
      }
    },
    "vendor": {
      "type": "string",
      "description": "Target fab house. One of: jlcpcb, pcbway, oshpark, seeed, allpcb.",
      "enum": [
        "jlcpcb",
        "pcbway",
        "oshpark",
        "seeed",
        "allpcb"
      ]
    },
    "copper_weight": {
      "type": "string"
    },
    "surface_finish": {
      "type": "string"
    },
    "soldermask": {
      "type": "string"
    },
    "silkscreen": {
      "type": "string"
    },
    "board_thickness": {
      "type": "string"
    },
    "special": {
      "type": "string"
    },
    "stem": {
      "type": "string"
    }
  },
  "required": [
    "circuit_json"
  ]
}
```

---

## `fab_vendor_presets`

Return the list of supported PCB fab vendors and their default fabrication options (copper weight, surface finish, soldermask, silkscreen, board thickness, whether IPC-2581 is included by default). Use this to discover supported vendors before calling fab_bundle_export, or to show the user what options are available.

### Input schema

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

---

## See also

- Package: `kerf_electronics`
