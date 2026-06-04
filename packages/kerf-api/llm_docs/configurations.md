# configurations

*Module: `kerf_api.tools.configurations` · Domain: api*

This module registers **2** LLM tool(s):

- [`add_configuration`](#add-configuration)
- [`set_active_config`](#set-active-config)

---

## `add_configuration`

Append (or update) a configuration on a file that supports per-file parameter overrides — Part (.part), Feature (.feature), or Sketch (.sketch).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    },
    "id": {
      "type": "string"
    },
    "label": {
      "type": "string"
    },
    "params": {
      "type": "object"
    }
  },
  "required": [
    "file_id",
    "id"
  ]
}
```

---

## `set_active_config`

Pin a configuration on an assembly's component.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "assembly_file_id": {
      "type": "string"
    },
    "component_id": {
      "type": "string"
    },
    "config_id": {
      "type": "string"
    }
  },
  "required": [
    "assembly_file_id",
    "component_id"
  ]
}
```

---

## See also

- Package: `kerf_api`
