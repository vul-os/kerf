# validation

*Module: `kerf_api.tools.validation` · Domain: api*

This module registers **2** LLM tool(s):

- [`validate_jscad`](#validate-jscad)
- [`generate_bom`](#generate-bom)

---

## `validate_jscad`

Stub: returns ok=true. Real validation runs in the browser.

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

## `generate_bom`

Generate a Bill of Materials for the current project. Walks every assembly file, recursively resolves nested assemblies, and aggregates leaf Part references by MPN (or by file id when MPN is missing). Returns rows with quantity, unit price (from the Part's first distributor with a price), and total price.

### Input schema

```json
{
  "type": "object",
  "properties": {}
}
```

---

## See also

- Package: `kerf_api`
