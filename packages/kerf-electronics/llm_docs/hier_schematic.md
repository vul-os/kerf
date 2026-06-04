# hier_schematic

*Module: `kerf_electronics.tools.hier_schematic` · Domain: electronics*

This module registers **7** LLM tool(s):

- [`add_sub_sheet`](#add-sub-sheet)
- [`remove_sub_sheet`](#remove-sub-sheet)
- [`add_global_label`](#add-global-label)
- [`add_hierarchical_label`](#add-hierarchical-label)
- [`flatten_hierarchy`](#flatten-hierarchy)
- [`validate_hierarchy`](#validate-hierarchy)
- [`replicate_channel`](#replicate-channel)

---

## `add_sub_sheet`

Add a sub-sheet symbol to a parent circuit. The sub-sheet references a child .circuit file by file_id and exposes hierarchical pins that connect to the child sheet's hierarchical_labels. Returns the updated circuit_json with a new sub_sheets entry including a generated id.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "object",
      "description": "The parent CircuitJSON board to modify."
    },
    "name": {
      "type": "string",
      "description": "Human-readable label for this sheet instance."
    },
    "file_id": {
      "type": "string",
      "description": "UUID of the child circuit file."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Schematic placement position [x, y]."
    },
    "pins": {
      "type": "array",
      "description": "Hierarchical pins exposed by this sheet symbol.",
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "type": {
            "type": "string",
            "enum": [
              "input",
              "output",
              "bidirectional",
              "passive"
            ]
          },
          "net_id": {
            "type": "string"
          }
        },
        "required": [
          "name",
          "type",
          "net_id"
        ]
      }
    }
  },
  "required": [
    "circuit_json",
    "name",
    "file_id"
  ]
}
```

---

## `remove_sub_sheet`

Remove a sub-sheet symbol from a circuit by its id. Also removes any hierarchical_labels in the same circuit that were scoped to that sheet. Returns the updated circuit_json.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "object"
    },
    "sub_sheet_id": {
      "type": "string",
      "description": "The sub_sheet.id to remove."
    }
  },
  "required": [
    "circuit_json",
    "sub_sheet_id"
  ]
}
```

---

## `add_global_label`

Add or update a global label on a circuit sheet. Global labels with the same name automatically connect across ALL sheets in a hierarchy (e.g. GND, VCC). Calling again with the same name updates the net_id. Returns the updated circuit_json.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "object"
    },
    "name": {
      "type": "string",
      "description": "Global net name, e.g. 'GND' or 'VCC'."
    },
    "net_id": {
      "type": "string",
      "description": "The local net identifier on this sheet."
    }
  },
  "required": [
    "circuit_json",
    "name",
    "net_id"
  ]
}
```

---

## `add_hierarchical_label`

Add or update a hierarchical label on a child circuit sheet. Hierarchical labels connect ONLY through the parent's matching sheet-symbol pin; they do not propagate globally. The sheet_id must match the sub_sheet.id in the parent circuit. Returns the updated circuit_json.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "object"
    },
    "name": {
      "type": "string",
      "description": "Pin name that must match the parent sheet symbol pin."
    },
    "net_id": {
      "type": "string",
      "description": "The local net identifier on this child sheet."
    },
    "sheet_id": {
      "type": "string",
      "description": "The sub_sheet.id in the parent that owns this label."
    }
  },
  "required": [
    "circuit_json",
    "name",
    "net_id",
    "sheet_id"
  ]
}
```

---

## `flatten_hierarchy`

Flatten a multi-sheet hierarchy into a single net equivalence list using union-find over (sheet_path, net_id) tuples. Global labels across all sheets are merged by label name. Sub-sheet pins are merged with the matching child hierarchical_label. Returns {net_groups: [[key, ...], ...]} where each group contains electrically equivalent 'sheet_path::net_id' keys.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "top_circuit_json": {
      "type": "object",
      "description": "The top-level CircuitJSON board."
    },
    "children": {
      "type": "object",
      "description": "Map of file_id \u2192 circuit_json for all referenced child sheets.",
      "additionalProperties": {
        "type": "object"
      }
    }
  },
  "required": [
    "top_circuit_json"
  ]
}
```

---

## `validate_hierarchy`

Validate a multi-sheet hierarchy. Checks: (1) every sub_sheet file_id is present in children; (2) every sheet-symbol pin has a matching hierarchical_label in the child; (3) no global label name collisions (same name → different net_id on same sheet); (4) no orphaned hierarchical_labels (label exists but no matching pin on parent). Returns {ok: bool, errors: [string]}.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "top_circuit_json": {
      "type": "object"
    },
    "children": {
      "type": "object",
      "additionalProperties": {
        "type": "object"
      }
    }
  },
  "required": [
    "top_circuit_json"
  ]
}
```

---

## `replicate_channel`

Replicate a schematic block N times (Altium-style multi-channel design). Each channel gets a unique prefix so its internal nets are independent. Global nets (GND, VCC, VDD, VBUS) are shared across all channels. Returns an array of merged circuit elements with offset positions.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "channel_circuit_json": {
      "type": [
        "object",
        "array"
      ],
      "description": "The single-channel template CircuitJSON (block to replicate)."
    },
    "count": {
      "type": "integer",
      "minimum": 2,
      "maximum": 64,
      "description": "Number of channels to produce (2\u201364)."
    },
    "channel_prefix": {
      "type": "string",
      "description": "Short identifier used as the net-name prefix, e.g. 'CH' or 'AMP'."
    },
    "x_spacing_mm": {
      "type": "number",
      "description": "Horizontal offset in mm between channel instances (default 50)."
    },
    "y_spacing_mm": {
      "type": "number",
      "description": "Vertical offset in mm between channel instances (default 0)."
    }
  },
  "required": [
    "channel_circuit_json",
    "count",
    "channel_prefix"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
