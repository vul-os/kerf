# stairs

*Module: `kerf_bim.tools.stairs` · Domain: bim*

This module registers **4** LLM tool(s):

- [`create_stair`](#create-stair)
- [`add_stair_flight`](#add-stair-flight)
- [`add_stair_landing`](#add-stair-landing)
- [`validate_stair`](#validate-stair)

---

## `create_stair`

Create a parametric staircase file. Supports straight, L-shaped (90°), and U-shaped (180°) stairs. Returns the file_id of the created stair document.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Optional UUID for the new stair file."
    },
    "total_rise_mm": {
      "type": "number",
      "description": "Total vertical rise in mm."
    },
    "total_run_mm": {
      "type": "number",
      "description": "Total horizontal run in mm."
    },
    "kind": {
      "type": "string",
      "enum": [
        "straight",
        "L",
        "U"
      ],
      "description": "Stair shape: straight, L (90\u00b0), or U (180\u00b0)."
    },
    "start_point": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x, y, z] bottom start point in mm."
    },
    "direction": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[dx, dy, dz] direction vector for straight stair."
    },
    "riser_height_mm": {
      "type": "number",
      "description": "Riser height mm (default 175)."
    },
    "tread_depth_mm": {
      "type": "number",
      "description": "Tread depth mm (default 280)."
    },
    "width_mm": {
      "type": "number",
      "description": "Stair width mm (default 1000)."
    }
  },
  "required": [
    "total_rise_mm",
    "total_run_mm",
    "kind",
    "start_point"
  ]
}
```

---

## `add_stair_flight`

Append a new flight to an existing stair file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the stair file."
    },
    "start": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x, y, z] start point of flight."
    },
    "direction": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[dx, dy, dz] direction vector."
    },
    "step_count": {
      "type": "integer",
      "description": "Number of steps in this flight."
    }
  },
  "required": [
    "file_id",
    "start",
    "direction",
    "step_count"
  ]
}
```

---

## `add_stair_landing`

Append a landing platform to an existing stair file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the stair file."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x, y, z] corner position of landing."
    },
    "size_mm": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[width, depth] of landing in mm."
    }
  },
  "required": [
    "file_id",
    "position",
    "size_mm"
  ]
}
```

---

## `validate_stair`

Validate a stair file against building-code comfort rules. Checks riser height [100, 220], tread depth [200, 350], and 2R+T [550, 700].

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the stair file."
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
