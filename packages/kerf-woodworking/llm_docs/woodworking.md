# woodworking

*Module: `kerf_woodworking.tools` · Domain: woodworking*

This module registers **13** LLM tool(s):

- [`woodworking_mortise_tenon`](#woodworking-mortise-tenon)
- [`woodworking_dovetail`](#woodworking-dovetail)
- [`woodworking_finger_joint`](#woodworking-finger-joint)
- [`woodworking_dowel`](#woodworking-dowel)
- [`woodworking_biscuit`](#woodworking-biscuit)
- [`woodworking_pocket_screw`](#woodworking-pocket-screw)
- [`woodworking_cut_list`](#woodworking-cut-list)
- [`woodworking_grain_check`](#woodworking-grain-check)
- [`woodworking_hinge_cup_pattern`](#woodworking-hinge-cup-pattern)
- [`woodworking_shelf_pin_pattern`](#woodworking-shelf-pin-pattern)
- [`woodworking_drawer_runner_pattern`](#woodworking-drawer-runner-pattern)
- [`woodworking_euro_screw_pattern`](#woodworking-euro-screw-pattern)
- [`woodworking_handle_pattern`](#woodworking-handle-pattern)

---

## `woodworking_mortise_tenon`

Design a mortise-and-tenon joint. Returns geometry, engaged volumes, and any grain warnings. Tenon and mortise volumes are equal when shoulder_gap_mm is 0.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "tenon_width_mm": {
      "type": "number",
      "description": "Tenon cheek width (mm)"
    },
    "tenon_height_mm": {
      "type": "number",
      "description": "Tenon height (mm)"
    },
    "tenon_depth_mm": {
      "type": "number",
      "description": "Tenon engagement depth (mm)"
    },
    "shoulder_gap_mm": {
      "type": "number",
      "description": "Clearance per cheek face (mm, default 0.2)"
    },
    "shoulder_grain": {
      "type": "string",
      "enum": [
        "along",
        "across",
        "diagonal",
        "any"
      ],
      "description": "Grain direction at tenon shoulder"
    }
  },
  "required": [
    "tenon_width_mm",
    "tenon_height_mm",
    "tenon_depth_mm"
  ]
}
```

---

## `woodworking_dovetail`

Design a through or half-blind dovetail joint. Returns tail geometry and engagement depth.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "board_thickness_mm": {
      "type": "number"
    },
    "tail_count": {
      "type": "integer",
      "description": "Number of tails (default 4)"
    },
    "tail_angle_deg": {
      "type": "number",
      "description": "Splay angle in degrees (default 8)"
    },
    "baseline_offset_mm": {
      "type": "number",
      "description": "Baseline distance from face (default 3)"
    },
    "half_blind": {
      "type": "boolean",
      "description": "Half-blind dovetail (default false)"
    },
    "lap_mm": {
      "type": "number",
      "description": "Front lap thickness (half-blind only)"
    },
    "board_grain": {
      "type": "string",
      "enum": [
        "along",
        "across",
        "diagonal",
        "any"
      ]
    }
  },
  "required": [
    "board_thickness_mm"
  ]
}
```

---

## `woodworking_finger_joint`

Design a box / finger joint for a given board thickness.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "board_thickness_mm": {
      "type": "number"
    },
    "finger_width_mm": {
      "type": "number",
      "description": "Finger width (default 10 mm)"
    },
    "kerf_mm": {
      "type": "number",
      "description": "Router/saw kerf (default 3.175 mm)"
    }
  },
  "required": [
    "board_thickness_mm"
  ]
}
```

---

## `woodworking_dowel`

Design a dowel joint.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "diameter_mm": {
      "type": "number",
      "description": "Dowel diameter (default 8 mm)"
    },
    "length_mm": {
      "type": "number",
      "description": "Total dowel length (default 40 mm)"
    },
    "count": {
      "type": "integer",
      "description": "Number of dowels (default 2)"
    },
    "spacing_mm": {
      "type": "number",
      "description": "Centre-to-centre spacing"
    }
  }
}
```

---

## `woodworking_biscuit`

Design a biscuit (plate) joint. Standard sizes: #0, #10, #20.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "size": {
      "type": "string",
      "enum": [
        "#0",
        "#10",
        "#20"
      ],
      "description": "Biscuit size (default #20)"
    },
    "count": {
      "type": "integer",
      "description": "Number of biscuits (default 3)"
    },
    "spacing_mm": {
      "type": "number",
      "description": "Centre-to-centre spacing"
    }
  }
}
```

---

## `woodworking_pocket_screw`

Design a pocket-screw (Kreg-style) joint.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "board_thickness_mm": {
      "type": "number",
      "description": "Pocket board thickness (default 19 mm)"
    },
    "screw_diameter_mm": {
      "type": "number",
      "description": "Screw diameter (default 4.5 mm)"
    },
    "screw_length_mm": {
      "type": "number",
      "description": "Total screw length (default 32 mm)"
    },
    "count": {
      "type": "integer",
      "description": "Number of screws (default 2)"
    },
    "spacing_mm": {
      "type": "number",
      "description": "Centre-to-centre spacing"
    },
    "target_grain": {
      "type": "string",
      "enum": [
        "along",
        "across",
        "end",
        "any"
      ],
      "description": "Grain direction of the receiving board"
    }
  }
}
```

---

## `woodworking_cut_list`

Generate an optimised cut list (1-D guillotine bin-packing) from a bill-of-boards and stock size. Returns piece assignments, waste, utilisation percentage, and off-cut lengths.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "pieces": {
      "type": "array",
      "description": "List of required pieces",
      "items": {
        "type": "object",
        "properties": {
          "label": {
            "type": "string"
          },
          "length_mm": {
            "type": "number"
          },
          "quantity": {
            "type": "integer"
          },
          "grain_direction": {
            "type": "string"
          }
        },
        "required": [
          "label",
          "length_mm"
        ]
      }
    },
    "stock_length_mm": {
      "type": "number",
      "description": "Uniform stock board length (mm)"
    },
    "kerf_mm": {
      "type": "number",
      "description": "Saw kerf (default 3.175 mm)"
    },
    "allow_grain_mismatch": {
      "type": "boolean"
    }
  },
  "required": [
    "pieces",
    "stock_length_mm"
  ]
}
```

---

## `woodworking_grain_check`

Check grain-direction metadata on a joint descriptor dict. Returns a list of grain warnings.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "joint": {
      "type": "object",
      "description": "Joint descriptor as returned by any woodworking joint tool"
    }
  },
  "required": [
    "joint"
  ]
}
```

---

## `woodworking_hinge_cup_pattern`

Generate 35 mm hinge-cup and arm pilot-hole bore positions for a door panel. Follows the 32 mm System and Blum Clip-Top / INSERTA specifications. Returns hole centres (x, y), diameters, and depths for CNC machining.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "panel_height_mm": {
      "type": "number",
      "description": "Door height (mm)"
    },
    "panel_width_mm": {
      "type": "number",
      "description": "Door width (mm, default 600)"
    },
    "panel_thickness_mm": {
      "type": "number",
      "description": "Door thickness (mm, default 18)"
    },
    "overlay_mm": {
      "type": "number",
      "description": "Overlay over carcase (mm, default 0 = full-inset)"
    },
    "count": {
      "type": "integer",
      "description": "Number of hinges (default 2)"
    }
  },
  "required": [
    "panel_height_mm"
  ]
}
```

---

## `woodworking_shelf_pin_pattern`

Generate 5 mm shelf-pin socket holes on a 32 mm pitch for a cabinet side panel. Returns two rows of holes (front and rear) at the specified positions.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "panel_height_mm": {
      "type": "number",
      "description": "Cabinet side panel height (mm)"
    },
    "panel_width_mm": {
      "type": "number",
      "description": "Cabinet depth (mm, default 600)"
    },
    "panel_thickness_mm": {
      "type": "number",
      "description": "Panel thickness (mm, default 18)"
    },
    "num_positions": {
      "type": "integer",
      "description": "Number of shelf-pin positions per row (default 10)"
    },
    "start_y_mm": {
      "type": "number",
      "description": "Y of first hole from bottom (mm, default 96)"
    }
  },
  "required": [
    "panel_height_mm"
  ]
}
```

---

## `woodworking_drawer_runner_pattern`

Generate drawer-runner pilot-hole positions on a cabinet side panel. Supports undermount (Blum Movento / Tandem) and side-mount runner types.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "panel_height_mm": {
      "type": "number",
      "description": "Cabinet side panel height (mm)"
    },
    "drawer_height_mm": {
      "type": "number",
      "description": "Drawer box height (mm)"
    },
    "panel_width_mm": {
      "type": "number",
      "description": "Cabinet depth (mm, default 600)"
    },
    "runner_type": {
      "type": "string",
      "enum": [
        "undermount",
        "sidemount"
      ],
      "description": "Runner type (default 'undermount')"
    },
    "num_drawers": {
      "type": "integer",
      "description": "Number of drawers (default 1)"
    }
  },
  "required": [
    "panel_height_mm",
    "drawer_height_mm"
  ]
}
```

---

## `woodworking_euro_screw_pattern`

Generate Confirmat / Euro-screw face pilot-hole positions for RTA panel joints (shelf-to-side or floor-to-side connections). Returns 5 mm pilot holes on the face panel at the specified edge.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "panel_width_mm": {
      "type": "number",
      "description": "Panel width (mm)"
    },
    "panel_height_mm": {
      "type": "number",
      "description": "Panel height (mm)"
    },
    "panel_thickness_mm": {
      "type": "number",
      "description": "Panel thickness (mm, default 18)"
    },
    "edge": {
      "type": "string",
      "enum": [
        "bottom",
        "top",
        "left",
        "right"
      ],
      "description": "Which edge is being joined (default 'bottom')"
    },
    "spacing_mm": {
      "type": "number",
      "description": "Screw spacing (mm, default 128)"
    },
    "count": {
      "type": "integer",
      "description": "Number of screws (default 2)"
    }
  },
  "required": [
    "panel_width_mm",
    "panel_height_mm"
  ]
}
```

---

## `woodworking_handle_pattern`

Generate handle / rail through-hole positions for a cabinet door or drawer front. Supports horizontal and vertical handle orientations. Common centre-to-centre spacings: 96, 128, 160, 192, 224, 256, 320 mm.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "panel_width_mm": {
      "type": "number",
      "description": "Panel width (mm)"
    },
    "panel_height_mm": {
      "type": "number",
      "description": "Panel height (mm)"
    },
    "panel_thickness_mm": {
      "type": "number",
      "description": "Panel thickness (mm, default 18)"
    },
    "centres_mm": {
      "type": "number",
      "description": "Handle hole centres (mm, default 128)"
    },
    "orientation": {
      "type": "string",
      "enum": [
        "horizontal",
        "vertical"
      ],
      "description": "Handle orientation (default 'horizontal')"
    },
    "offset_from_edge_mm": {
      "type": "number",
      "description": "Distance from chosen edge to hole (mm, default 40)"
    },
    "edge": {
      "type": "string",
      "enum": [
        "top",
        "bottom",
        "left",
        "right"
      ],
      "description": "Edge the handle is near (default 'top')"
    }
  },
  "required": [
    "panel_width_mm",
    "panel_height_mm"
  ]
}
```

---

## See also

- Package: `kerf_woodworking`
