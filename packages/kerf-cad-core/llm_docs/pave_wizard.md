# pave_wizard

*Module: `kerf_cad_core.jewelry.pave_wizard` · Domain: cad*

This module registers **3** LLM tool(s):

- [`jewelry_pave_wizard`](#jewelry-pave-wizard)
- [`jewelry_pave_wizard_stats`](#jewelry-pave-wizard-stats)
- [`jewelry_pave_wizard_update`](#jewelry-pave-wizard-update)

---

## `jewelry_pave_wizard`

Auto-distribute pavé stones over a freeform surface region (MatrixGold parity). Given a target surface described by UV dimensions and optional sample points, and the stone + spacing parameters, this tool: (1) packs stones using hex, grid, or flow-line layout; (2) generates normal-aligned seat cutters per stone; (3) generates beads/prongs (shared_bead, fishtail, u_cut, or channel); (4) validates metal-bridge and wall-thickness; (5) returns stone count, total carat, metal removed (mm³), and coverage %. Appends a 'jewelry_pave_wizard' node to the .feature file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "region_width": {
      "type": "number",
      "description": "Width of the surface region to cover in mm (u-direction extent)."
    },
    "region_height": {
      "type": "number",
      "description": "Height of the surface region to cover in mm (v-direction extent)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of each stone in mm (e.g. 1.5 for 0.013 ct melee)."
    },
    "stone_spacing": {
      "type": "number",
      "description": "Minimum metal bridge between adjacent stone edges in mm. Typical range 0.1\u20130.3 mm."
    },
    "edge_margin": {
      "type": "number",
      "description": "Minimum metal bridge from the region boundary to the nearest stone edge in mm. Typical range 0.2\u20130.5 mm."
    },
    "layout": {
      "type": "string",
      "enum": [
        "hex",
        "grid",
        "flow_line"
      ],
      "description": "Stone packing layout. 'hex': hexagonal close-packing (default, highest density). 'grid': square lattice (calibrated rows). 'flow_line': stones follow iso-parametric ribbons across the surface."
    },
    "bead_style": {
      "type": "string",
      "enum": [
        "shared_bead",
        "fishtail",
        "u_cut",
        "channel"
      ],
      "description": "Stone retention style. 'shared_bead': one bead shared by four adjacent stones (default). 'fishtail': bright-cut fishtail seat + two beads per stone. 'u_cut': U-shaped groove with two prong tips per stone. 'channel': parallel rails, minimal beads (channel-pave hybrid)."
    },
    "cut": {
      "type": "string",
      "description": "Gemstone cut name for carat estimation (default 'round_brilliant'). Must be a valid cut from the gemstones module."
    },
    "min_bridge_mm": {
      "type": "number",
      "description": "Minimum acceptable metal bridge (mm); below this a 'thin_metal' warning is set. Default 0.1 mm."
    },
    "min_wall_mm": {
      "type": "number",
      "description": "Minimum acceptable edge wall (mm). Default 0.2 mm."
    },
    "samples": {
      "type": "array",
      "description": "Optional UV surface samples. Each sample: {u, v, x, y, z, nx, ny, nz} \u2014 u/v in [0,1], xyz in mm, nxyz unit normal. Omit for a flat region (normal = +Z).",
      "items": {
        "type": "object"
      }
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "region_width",
    "region_height",
    "stone_diameter",
    "stone_spacing",
    "edge_margin"
  ]
}
```

---

## `jewelry_pave_wizard_stats`

Read-only. Re-compute statistics (stone count, total carat, metal removed, coverage %) from an existing 'jewelry_pave_wizard' node in a .feature file.  Returns the stats dict without modifying the file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "node_id": {
      "type": "string",
      "description": "Id of the existing jewelry_pave_wizard node."
    }
  },
  "required": [
    "file_id",
    "node_id"
  ]
}
```

---

## `jewelry_pave_wizard_update`

Re-run the pavé wizard layout on an existing 'jewelry_pave_wizard' node with updated parameters (spacing, bead style, edge margin, or layout). The node is replaced in-place in the .feature file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "node_id": {
      "type": "string",
      "description": "Id of the existing jewelry_pave_wizard node to update."
    },
    "stone_spacing": {
      "type": "number",
      "description": "New stone spacing (mm)."
    },
    "edge_margin": {
      "type": "number",
      "description": "New edge margin (mm)."
    },
    "layout": {
      "type": "string",
      "enum": [
        "hex",
        "grid",
        "flow_line"
      ],
      "description": "New layout algorithm."
    },
    "bead_style": {
      "type": "string",
      "enum": [
        "shared_bead",
        "fishtail",
        "u_cut",
        "channel"
      ],
      "description": "New bead style."
    },
    "min_bridge_mm": {
      "type": "number",
      "description": "New minimum bridge (mm)."
    },
    "min_wall_mm": {
      "type": "number",
      "description": "New minimum wall (mm)."
    }
  },
  "required": [
    "file_id",
    "node_id"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
