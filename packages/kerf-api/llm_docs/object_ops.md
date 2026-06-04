# object_ops

*Module: `kerf_api.tools.object_ops` · Domain: api*

This module registers **2** LLM tool(s):

- [`duplicate_object`](#duplicate-object)
- [`delete_object`](#delete-object)

---

## `duplicate_object`

Clone a single Object (one entry in a Part's exported `[{id, geom}, ...]` array) and append the clone after the original. Pass `new_id` to set the clone's id; otherwise it defaults to `<object_id>-copy[-N]`. Bails with PARSE_FAILED if the file's structure isn't a clean `return [{id,...}, ...]`.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "object_id": {
      "type": "string"
    },
    "new_id": {
      "type": "string"
    }
  },
  "required": [
    "path",
    "object_id"
  ]
}
```

---

## `delete_object`

Remove a single Object entry from a Part's exported `[{id, geom}, ...]` array. Bails with PARSE_FAILED if the file's structure isn't a clean `return [{id,...}, ...]`.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "object_id": {
      "type": "string"
    }
  },
  "required": [
    "path",
    "object_id"
  ]
}
```

---

## See also

- Package: `kerf_api`
