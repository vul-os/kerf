# bim_categories

*Module: `kerf_bim.tools.bim_categories` · Domain: bim*

This module registers **6** LLM tool(s):

- [`set_element_category`](#set-element-category)
- [`set_element_host`](#set-element-host)
- [`unset_element_host`](#unset-element-host)
- [`move_element`](#move-element)
- [`find_hosted`](#find-hosted)
- [`validate_bim_categories`](#validate-bim-categories)

---

## `set_element_category`

Set the category field on a BIM element. Valid categories: Wall, Floor, Roof, Door, Window, Room, Column, Beam, Stair, Railing, Casework, Site, Generic, MEP_Duct, MEP_Pipe, MEP_Conduit

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    },
    "element_id": {
      "type": "string"
    },
    "category": {
      "type": "string"
    }
  },
  "required": [
    "file_id",
    "element_id",
    "category"
  ]
}
```

---

## `set_element_host`

Attach a BIM element to a host element via host_ref. Validates HOST_RULES (e.g. Door must host on Wall). Rejects invalid host category pairs.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    },
    "element_id": {
      "type": "string"
    },
    "host_ref": {
      "type": "string"
    }
  },
  "required": [
    "file_id",
    "element_id",
    "host_ref"
  ]
}
```

---

## `unset_element_host`

Remove the host_ref from a BIM element, detaching it from its host.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    },
    "element_id": {
      "type": "string"
    }
  },
  "required": [
    "file_id",
    "element_id"
  ]
}
```

---

## `move_element`

Translate a BIM element and all elements hosted on it (recursively) by delta=[dx, dy, dz] in millimetres.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    },
    "element_id": {
      "type": "string"
    },
    "delta": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 2,
      "maxItems": 3
    }
  },
  "required": [
    "file_id",
    "element_id",
    "delta"
  ]
}
```

---

## `find_hosted`

Return the ids of all elements directly hosted on a given host element.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    },
    "host_id": {
      "type": "string"
    }
  },
  "required": [
    "file_id",
    "host_id"
  ]
}
```

---

## `validate_bim_categories`

Validate all element categories and host_ref relationships in a .bim file. Returns {ok, errors, warnings}.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
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
