# draft

*Module: `kerf_imports.tools.draft` · Domain: imports*

This module registers **6** LLM tool(s):

- [`create_draft`](#create-draft)
- [`add_draft_entity`](#add-draft-entity)
- [`offset_draft_entity`](#offset-draft-entity)
- [`fillet_draft_corner`](#fillet-draft-corner)
- [`pattern_linear_draft`](#pattern-linear-draft)
- [`export_draft_dxf`](#export-draft-dxf)

---

## `create_draft`

Create a new empty .draft document.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    }
  },
  "required": [
    "name"
  ]
}
```

---

## `add_draft_entity`

Add an entity to a .draft document.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "draft": {
      "type": "object"
    },
    "entity": {
      "type": "object"
    }
  },
  "required": [
    "draft",
    "entity"
  ]
}
```

---

## `offset_draft_entity`

Offset a line or polyline entity perpendicularly.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "draft": {
      "type": "object"
    },
    "id": {
      "type": "string"
    },
    "distance": {
      "type": "number"
    }
  },
  "required": [
    "draft",
    "id",
    "distance"
  ]
}
```

---

## `fillet_draft_corner`

Fillet (round) the corner between two lines with a given radius.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "draft": {
      "type": "object"
    },
    "line1_id": {
      "type": "string"
    },
    "line2_id": {
      "type": "string"
    },
    "radius": {
      "type": "number"
    }
  },
  "required": [
    "draft",
    "line1_id",
    "line2_id",
    "radius"
  ]
}
```

---

## `pattern_linear_draft`

Array-copy an entity in a linear pattern.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "draft": {
      "type": "object"
    },
    "id": {
      "type": "string"
    },
    "count": {
      "type": "integer"
    },
    "dx": {
      "type": "number"
    },
    "dy": {
      "type": "number"
    }
  },
  "required": [
    "draft",
    "id",
    "count",
    "dx",
    "dy"
  ]
}
```

---

## `export_draft_dxf`

Export a .draft document to DXF R12 text.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "draft": {
      "type": "object"
    }
  },
  "required": [
    "draft"
  ]
}
```

---

## See also

- Package: `kerf_imports`
