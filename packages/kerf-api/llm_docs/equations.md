# equations

*Module: `kerf_api.tools.equations` · Domain: api*

This module registers **2** LLM tool(s):

- [`read_equations`](#read-equations)
- [`set_equation`](#set-equation)

---

## `read_equations`

Read the project-level .equations parameter file. Returns the parsed JSON shape {version, params:[{name, expr, unit, comment}, ...]}. If no .equations file exists, returns an empty params array.

### Input schema

```json
{
  "type": "object",
  "properties": {}
}
```

---

## `set_equation`

Upsert a single named parameter in the project-level .equations file. Creates the file at /params.equations if none exists.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "expr": {
      "type": "string"
    },
    "unit": {
      "type": "string"
    },
    "comment": {
      "type": "string"
    }
  },
  "required": [
    "name",
    "expr"
  ]
}
```

---

## See also

- Package: `kerf_api`
