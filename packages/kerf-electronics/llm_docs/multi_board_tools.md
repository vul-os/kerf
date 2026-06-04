# multi_board_tools

*Module: `kerf_electronics.multi_board.multi_board_tools` · Domain: electronics*

This module registers **5** LLM tool(s):

- [`electronics_mb3d_create_workspace`](#electronics-mb3d-create-workspace)
- [`electronics_mb3d_add_connector`](#electronics-mb3d-add-connector)
- [`electronics_mb3d_validate_workspace`](#electronics-mb3d-validate-workspace)
- [`electronics_mb3d_net_map`](#electronics-mb3d-net-map)
- [`electronics_mb3d_export_step`](#electronics-mb3d-export-step)

---

## `electronics_mb3d_create_workspace`

Create an Altium MB3D-style multi-board workspace. Accepts a workspace name and a list of board placements (board_id, file_path, position [x,y,z mm], rotation_xyz_deg, optional board_width_mm/board_height_mm). Returns workspace summary JSON including all board IDs and a preliminary overlap check. References: Altium MB3D §2-3; IPC-2581 §7.4.1.

### Input schema

```json
{
  "type": "object",
  "required": [
    "workspace_name",
    "boards"
  ],
  "properties": {
    "workspace_name": {
      "type": "string",
      "description": "Human-readable workspace name."
    },
    "boards": {
      "type": "array",
      "description": "List of board placement descriptors.",
      "items": {
        "type": "object",
        "required": [
          "board_id",
          "file_path",
          "position"
        ],
        "properties": {
          "board_id": {
            "type": "string"
          },
          "file_path": {
            "type": "string"
          },
          "position": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3
          },
          "rotation_xyz_deg": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3
          },
          "board_width_mm": {
            "type": "number"
          },
          "board_height_mm": {
            "type": "number"
          }
        }
      }
    },
    "enclosure_step_file": {
      "type": "string",
      "description": "Optional path to enclosure STEP model."
    }
  }
}
```

---

## `electronics_mb3d_add_connector`

Declare a mating inter-board connector pair in an existing workspace definition. Provide the connector name, both board_ids + designators, pin counts, and a pin_mapping dict ({from_pin: to_pin, ...}). The tool validates the mapping for pin-count consistency and flags mismatches (Altium §4.3 / IPC-2581 §7.4.2). Returns validation results for this connector.

### Input schema

```json
{
  "type": "object",
  "required": [
    "name",
    "from_board",
    "from_designator",
    "from_pin_count",
    "to_board",
    "to_designator",
    "to_pin_count",
    "pin_mapping"
  ],
  "properties": {
    "name": {
      "type": "string"
    },
    "from_board": {
      "type": "string"
    },
    "from_designator": {
      "type": "string"
    },
    "from_pin_count": {
      "type": "integer"
    },
    "to_board": {
      "type": "string"
    },
    "to_designator": {
      "type": "string"
    },
    "to_pin_count": {
      "type": "integer"
    },
    "pin_mapping": {
      "type": "object",
      "description": "JSON object: string pin numbers \u2192 string pin numbers.",
      "additionalProperties": {
        "type": "integer"
      }
    },
    "connector_type": {
      "type": "string",
      "enum": [
        "board_to_board",
        "flex_cable",
        "wire_harness"
      ]
    }
  }
}
```

---

## `electronics_mb3d_validate_workspace`

Validate a complete multi-board workspace: check all connector mating pairs for pin-count consistency, detect self-loops, identify boards with no connector declarations, and run a 2-D bounding-box overlap check. Accepts the same workspace JSON as electronics_mb3d_create_workspace plus a 'connectors' list. Returns a structured report with mating_issues and overlap_warnings.

### Input schema

```json
{
  "type": "object",
  "required": [
    "workspace_name",
    "boards",
    "connectors"
  ],
  "properties": {
    "workspace_name": {
      "type": "string"
    },
    "boards": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "board_id",
          "file_path",
          "position"
        ],
        "properties": {
          "board_id": {
            "type": "string"
          },
          "file_path": {
            "type": "string"
          },
          "position": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3
          },
          "rotation_xyz_deg": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3
          },
          "board_width_mm": {
            "type": "number"
          },
          "board_height_mm": {
            "type": "number"
          }
        }
      }
    },
    "connectors": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "name",
          "from_board",
          "from_designator",
          "from_pin_count",
          "to_board",
          "to_designator",
          "to_pin_count",
          "pin_mapping"
        ]
      }
    }
  }
}
```

---

## `electronics_mb3d_net_map`

Compute the cross-board net map for a multi-board workspace. Walks all connector pin_mappings and resolves global workspace-level net names from per-board local net names. Flags floating connector pins, impedance mismatches (Bogatin §11.3: >10% Z0 delta = warning, >25% = error), and differential pair health (IPC-2141A §6). board_net_assignments: {board_id: {designator: {pin_int: net_name}}}. board_impedances: {board_id: {net_name: Z0_ohm}}.

### Input schema

```json
{
  "type": "object",
  "required": [
    "workspace_name",
    "boards",
    "connectors"
  ],
  "properties": {
    "workspace_name": {
      "type": "string"
    },
    "boards": {
      "type": "array",
      "items": {
        "type": "object"
      }
    },
    "connectors": {
      "type": "array",
      "items": {
        "type": "object"
      }
    },
    "board_net_assignments": {
      "type": "object",
      "description": "Per-board connector pin\u2192net mapping."
    },
    "board_impedances": {
      "type": "object",
      "description": "Per-board net\u2192Z0 (\u03a9) mapping."
    }
  }
}
```

---

## `electronics_mb3d_export_step`

Export the multi-board assembly as a STEP AP242 file. Each board is placed at its declared position/rotation in the workspace coordinate frame (Altium MB3D §5 / STEP AP242 §9.3). Returns base64-encoded STEP bytes + a 'filename' suggestion. If pythonOCC is available, solid board geometry is produced; otherwise a parametric bounding-box STEP is returned (always valid for MCAD import).

### Input schema

```json
{
  "type": "object",
  "required": [
    "workspace_name",
    "boards",
    "connectors"
  ],
  "properties": {
    "workspace_name": {
      "type": "string"
    },
    "boards": {
      "type": "array",
      "items": {
        "type": "object"
      }
    },
    "connectors": {
      "type": "array",
      "items": {
        "type": "object"
      }
    },
    "enclosure_step_file": {
      "type": "string"
    }
  }
}
```

---

## See also

- Package: `kerf_electronics`
