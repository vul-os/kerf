# space

*Module: `kerf_bim.tools.space` · Domain: bim*

This module registers **2** LLM tool(s):

- [`bim_create_space`](#bim-create-space)
- [`bim_space_schedule`](#bim-space-schedule)

---

## `bim_create_space`

Create a BIM space / zone / room object (IfcSpace) with a plan-view boundary polygon, level assignment, ceiling height, and optional occupancy program. Returns computed area (m²), volume (m³), and occupancy. Spaces are automatically included in IFC export and area schedules.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Room / space name, e.g. 'Living Room', 'Office 1'."
    },
    "level": {
      "type": "string",
      "description": "Storey name, e.g. 'L1', 'Ground Floor'.",
      "default": "L1"
    },
    "boundary": {
      "type": "array",
      "description": "Plan-view boundary polygon as [[x, y], ...] in metres. Minimum 3 points; no closing duplicate needed.",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2,
        "maxItems": 2
      },
      "minItems": 3
    },
    "height_m": {
      "type": "number",
      "description": "Floor-to-ceiling height in metres (default 2.7).",
      "default": 2.7
    },
    "program": {
      "type": "string",
      "description": "Occupancy program category, e.g. 'residential', 'office', 'retail', 'circulation'.",
      "default": "residential"
    },
    "occupancy_per_m2": {
      "type": "number",
      "description": "Occupancy density in persons/m\u00b2 for code compliance (optional)."
    }
  },
  "required": [
    "name",
    "boundary"
  ]
}
```

---

## `bim_space_schedule`

Generate a BIM area / occupancy schedule from a list of space definitions. Returns per-space rows (name, level, area, volume, occupancy) plus totals and per-level subtotals. Conforms to IfcElementQuantity / IfcAreaMeasure conventions from ISO 16739-1:2018.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "spaces": {
      "type": "array",
      "description": "Array of space objects, each with name, boundary, level, height_m, program.",
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "level": {
            "type": "string"
          },
          "boundary": {
            "type": "array",
            "items": {
              "type": "array",
              "items": {
                "type": "number"
              }
            }
          },
          "height_m": {
            "type": "number"
          },
          "program": {
            "type": "string"
          },
          "occupancy_per_m2": {
            "type": "number"
          }
        },
        "required": [
          "name",
          "boundary"
        ]
      },
      "minItems": 1
    }
  },
  "required": [
    "spaces"
  ]
}
```

---

## See also

- Package: `kerf_bim`
