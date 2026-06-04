# family_library

*Module: `kerf_bim.tools.family_library` · Domain: bim*

This module registers **3** LLM tool(s):

- [`list_family_library`](#list-family-library)
- [`get_family_from_library`](#get-family-from-library)
- [`list_family_library_categories`](#list-family-library-categories)

---

## `list_family_library`

List pre-populated catalog families available cold-start (doors, windows, furniture, plumbing, lighting, structural). Optionally filter by exact category string.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "category": {
      "type": "string",
      "description": "Optional exact category filter (e.g. 'Door')."
    }
  },
  "required": []
}
```

---

## `get_family_from_library`

Return the full parameter schema and built-in type presets for one catalog family, looked up by its exact family name.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Exact family name, e.g. 'Single Swing Door'."
    }
  },
  "required": [
    "name"
  ]
}
```

---

## `list_family_library_categories`

List the distinct categories present in the cold-start family catalog.

### Input schema

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

---

## See also

- Package: `kerf_bim`
