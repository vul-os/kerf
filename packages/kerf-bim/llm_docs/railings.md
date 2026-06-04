# railings

*Module: `kerf_bim.tools.railings` · Domain: bim*

This module registers **4** LLM tool(s):

- [`create_railing`](#create-railing)
- [`railing_from_stair`](#railing-from-stair)
- [`set_baluster_spacing`](#set-baluster-spacing)
- [`validate_railing`](#validate-railing)

---

## `create_railing`

Create a parametric railing file from an explicit path. The path is a list of {x,y,z} points in mm.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Optional UUID for the new railing file."
    },
    "path": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "x": {
            "type": "number"
          },
          "y": {
            "type": "number"
          },
          "z": {
            "type": "number"
          }
        },
        "required": [
          "x",
          "y",
          "z"
        ]
      },
      "description": "List of {x,y,z} waypoints defining the railing centre-line."
    },
    "height_mm": {
      "type": "number",
      "description": "Top-rail height in mm (default 1000)."
    }
  },
  "required": [
    "path"
  ]
}
```

---

## `railing_from_stair`

Generate a railing along the edge(s) of an existing stair. side = 'left' | 'right' | 'both'. When side='both', two railing files are created.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "stair_file_id": {
      "type": "string",
      "description": "UUID of the source stair file."
    },
    "side": {
      "type": "string",
      "enum": [
        "left",
        "right",
        "both"
      ],
      "description": "Which edge(s) to add railing to."
    },
    "output_file_id": {
      "type": "string",
      "description": "Optional UUID for the output railing file (ignored when side='both')."
    },
    "height_mm": {
      "type": "number",
      "description": "Railing height mm (default 1000)."
    }
  },
  "required": [
    "stair_file_id",
    "side"
  ]
}
```

---

## `set_baluster_spacing`

Update the baluster spacing on an existing railing file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the railing file."
    },
    "spacing_mm": {
      "type": "number",
      "description": "New baluster centre-to-centre spacing in mm."
    }
  },
  "required": [
    "file_id",
    "spacing_mm"
  ]
}
```

---

## `validate_railing`

Validate a railing file for structural and code compliance.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the railing file."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## See also

- Package: `kerf_bim`
