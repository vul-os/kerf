# material

*Module: `kerf_api.tools.material` · Domain: api*

This module registers **3** LLM tool(s):

- [`read_material`](#read-material)
- [`find_material_by_name`](#find-material-by-name)
- [`set_part_material`](#set-part-material)

---

## `read_material`

Read a .material engineering-property file by absolute path. Returns the parsed JSON shape with mechanical / thermal / physical groups.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    }
  },
  "required": [
    "path"
  ]
}
```

---

## `find_material_by_name`

Fuzzy-search every .material file in the project by name + common_names. Returns up to N matches (default 5, capped at 25).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string"
    },
    "max": {
      "type": "integer"
    }
  },
  "required": [
    "query"
  ]
}
```

---

## `set_part_material`

Attach a material to a Part by setting its `material_path` field. Both paths are absolute. Validates that material_path resolves to a kind='material' file before writing.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "part_path": {
      "type": "string"
    },
    "material_path": {
      "type": "string"
    }
  },
  "required": [
    "part_path",
    "material_path"
  ]
}
```

---

## See also

- Package: `kerf_api`
