# project_layers

*Module: `kerf_api.tools.project_layers` · Domain: api*

This module registers **6** LLM tool(s):

- [`create_layer`](#create-layer)
- [`delete_layer`](#delete-layer)
- [`set_project_layer_visibility`](#set-project-layer-visibility)
- [`set_project_layer_color`](#set-project-layer-color)
- [`assign_file_to_layer`](#assign-file-to-layer)
- [`switch_display_mode`](#switch-display-mode)

---

## `create_layer`

Create a new project layer. color must be a hex string like '#ff0000'. If a layer with the same name already exists the call is a no-op.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "color": {
      "type": "string",
      "default": "#aaaaaa"
    },
    "linetype": {
      "type": "string",
      "default": "continuous"
    },
    "locked": {
      "type": "boolean",
      "default": false
    }
  },
  "required": [
    "project_id",
    "name"
  ]
}
```

---

## `delete_layer`

Delete a project layer by id. Refuses if it is the last layer.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string"
    },
    "layer_id": {
      "type": "string"
    }
  },
  "required": [
    "project_id",
    "layer_id"
  ]
}
```

---

## `set_project_layer_visibility`

Show or hide a project layer.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string"
    },
    "layer_id": {
      "type": "string"
    },
    "visible": {
      "type": "boolean"
    }
  },
  "required": [
    "project_id",
    "layer_id",
    "visible"
  ]
}
```

---

## `set_project_layer_color`

Set the hex color of a project layer.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string"
    },
    "layer_id": {
      "type": "string"
    },
    "color": {
      "type": "string",
      "description": "Hex color e.g. '#ff0000'"
    }
  },
  "required": [
    "project_id",
    "layer_id",
    "color"
  ]
}
```

---

## `assign_file_to_layer`

Record which layer a project file belongs to. Stores the layer_id in the file's metadata JSON under key 'layer_id'. The file must belong to the same project.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string"
    },
    "file_id": {
      "type": "string",
      "description": "UUID of the file to assign"
    },
    "layer_id": {
      "type": "string"
    }
  },
  "required": [
    "project_id",
    "file_id",
    "layer_id"
  ]
}
```

---

## `switch_display_mode`

Set the active display mode for the project's 3D viewport. Built-in modes: shaded | wireframe | technical | rendered.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string"
    },
    "mode_id": {
      "type": "string",
      "description": "Display mode id, e.g. 'wireframe'"
    }
  },
  "required": [
    "project_id",
    "mode_id"
  ]
}
```

---

## See also

- Package: `kerf_api`
