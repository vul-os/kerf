# bim

*Module: `kerf_bim.tools.bim` · Domain: bim*

This module registers **4** LLM tool(s):

- [`create_bim`](#create-bim)
- [`read_bim`](#read-bim)
- [`compile_bim_to_ifc`](#compile-bim-to-ifc)
- [`read_ifc`](#read-ifc)

---

## `create_bim`

Create a new empty .bim architecture file (IFC4 BIM model). After creation, populate by editing the JSON via write_file / edit_file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "site": {
      "type": "object",
      "properties": {
        "name": {
          "type": "string"
        },
        "latitude": {
          "type": "number"
        },
        "longitude": {
          "type": "number"
        },
        "elevation": {
          "type": "number"
        }
      }
    }
  },
  "required": [
    "path"
  ]
}
```

---

## `read_bim`

Read a .bim architecture file and return its full JSON body.

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

## `compile_bim_to_ifc`

Compile a .bim architecture file to an IFC4 .ifc binary using IfcOpenShell. The .ifc is stored in the same project and returned as a base64-encoded blob.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "bim_path": {
      "type": "string"
    }
  },
  "required": [
    "bim_path"
  ]
}
```

---

## `read_ifc`

Read the raw binary content of an existing .ifc file from the project, returned as base64.

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

## See also

- Package: `kerf_bim`
