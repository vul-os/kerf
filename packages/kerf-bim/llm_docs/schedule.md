# schedule

*Module: `kerf_bim.tools.schedule` · Domain: bim*

This module registers **3** LLM tool(s):

- [`create_schedule`](#create-schedule)
- [`update_schedule_filter`](#update-schedule-filter)
- [`run_schedule`](#run-schedule)

---

## `create_schedule`

Create a new .schedule.json schedule definition file in the project tree.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "target_category": {
      "type": "string",
      "enum": [
        "Wall",
        "Door",
        "Window",
        "Room",
        "Slab",
        "Space",
        "Opening",
        "Level",
        "Site"
      ]
    },
    "columns": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "field": {
            "type": "string"
          },
          "label": {
            "type": "string"
          },
          "format": {
            "type": "string"
          }
        },
        "required": [
          "field"
        ]
      }
    },
    "filters": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "field": {
            "type": "string"
          },
          "op": {
            "type": "string",
            "enum": [
              "eq",
              "ne",
              "gt",
              "lt",
              "gte",
              "lte",
              "in",
              "contains"
            ]
          },
          "value": {}
        },
        "required": [
          "field",
          "op",
          "value"
        ]
      }
    },
    "group_by": {
      "type": "string"
    },
    "sort_by": {
      "type": "string"
    }
  },
  "required": [
    "path",
    "name",
    "target_category"
  ]
}
```

---

## `update_schedule_filter`

Update the filter on an existing .schedule.json file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    },
    "filter": {
      "type": "object",
      "properties": {
        "field": {
          "type": "string"
        },
        "op": {
          "type": "string",
          "enum": [
            "eq",
            "ne",
            "gt",
            "lt",
            "gte",
            "lte",
            "in",
            "contains"
          ]
        },
        "value": {}
      },
      "required": [
        "field",
        "op",
        "value"
      ]
    }
  },
  "required": [
    "file_id",
    "filter"
  ]
}
```

---

## `run_schedule`

Execute a .schedule.json against a .bim file and return the table result.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "schedule_file_id": {
      "type": "string"
    },
    "bim_file_id": {
      "type": "string"
    }
  },
  "required": [
    "schedule_file_id",
    "bim_file_id"
  ]
}
```

---

## See also

- Package: `kerf_bim`
