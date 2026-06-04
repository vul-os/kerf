# sheet

*Module: `kerf_bim.tools.sheet` · Domain: bim*

This module registers **4** LLM tool(s):

- [`create_sheet`](#create-sheet)
- [`add_viewport_to_sheet`](#add-viewport-to-sheet)
- [`remove_viewport`](#remove-viewport)
- [`add_revision_cloud`](#add-revision-cloud)

---

## `create_sheet`

Create a new .sheet.json layout file inside the project. path must end with .sheet.json.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string",
      "description": "Absolute project path ending in .sheet.json"
    },
    "name": {
      "type": "string"
    },
    "sheet_number": {
      "type": "string"
    },
    "size": {
      "type": "string",
      "enum": [
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "ANSI_A",
        "ANSI_B",
        "ANSI_C",
        "ANSI_D",
        "ANSI_E"
      ]
    },
    "orientation": {
      "type": "string",
      "enum": [
        "landscape",
        "portrait"
      ]
    }
  },
  "required": [
    "path",
    "name",
    "sheet_number",
    "size"
  ]
}
```

---

## `add_viewport_to_sheet`

Add a viewport referencing a .view.json file to an existing .sheet.json.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sheet_file_id": {
      "type": "string",
      "description": "UUID of the .sheet.json file"
    },
    "view_file_id": {
      "type": "string",
      "description": "UUID of the .view.json file"
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x, y] in mm"
    },
    "scale": {
      "type": "number",
      "description": "e.g. 0.02 for 1:50"
    },
    "title": {
      "type": "string"
    }
  },
  "required": [
    "sheet_file_id",
    "view_file_id",
    "position",
    "scale"
  ]
}
```

---

## `remove_viewport`

Remove a viewport from a .sheet.json file by its id.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sheet_file_id": {
      "type": "string"
    },
    "viewport_id": {
      "type": "string"
    }
  },
  "required": [
    "sheet_file_id",
    "viewport_id"
  ]
}
```

---

## `add_revision_cloud`

Add a revision cloud annotation to a .sheet.json file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sheet_file_id": {
      "type": "string"
    },
    "polygon": {
      "type": "array",
      "description": "List of [x,y] points (min 3)"
    },
    "revision": {
      "type": "string",
      "description": "Revision label e.g. 'A'"
    },
    "note": {
      "type": "string"
    }
  },
  "required": [
    "sheet_file_id",
    "polygon",
    "revision"
  ]
}
```

---

## See also

- Package: `kerf_bim`
