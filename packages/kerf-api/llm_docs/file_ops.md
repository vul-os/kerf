# file_ops

*Module: `kerf_api.tools.file_ops` · Domain: api*

This module registers **9** LLM tool(s):

- [`list_files`](#list-files)
- [`read_file`](#read-file)
- [`write_file`](#write-file)
- [`edit_file`](#edit-file)
- [`create_file`](#create-file)
- [`delete_file`](#delete-file)
- [`search_code`](#search-code)
- [`import_step`](#import-step)
- [`import_kicad`](#import-kicad)

---

## `list_files`

List every file in the current project as a flat array of absolute paths.

### Input schema

```json
{
  "type": "object",
  "properties": {}
}
```

---

## `read_file`

Read the full text content of a file by absolute path. Errors on binary kinds (e.g. step). Paths under '/docs/llm/' route to the embedded Kerf authoring corpus instead of the project tree (use search_kerf_docs to discover them).

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

## `write_file`

Replace the entire content of a text file. Creates intermediate folders if missing. Use edit_file for targeted edits.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "content": {
      "type": "string"
    }
  },
  "required": [
    "path",
    "content"
  ]
}
```

---

## `edit_file`

Replace a unique substring inside a text file. Errors if old_string occurs zero or more than one time. Use this for surgical edits.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "old_string": {
      "type": "string"
    },
    "new_string": {
      "type": "string"
    }
  },
  "required": [
    "path",
    "old_string",
    "new_string"
  ]
}
```

---

## `create_file`

Create a new file, folder, assembly, or drawing. Auto-creates intermediate folders. kind defaults to 'file'.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "content": {
      "type": "string"
    },
    "kind": {
      "type": "string",
      "enum": [
        "file",
        "folder",
        "assembly",
        "drawing"
      ]
    }
  },
  "required": [
    "path"
  ]
}
```

---

## `delete_file`

Delete the file or folder at the given absolute path (recursive for folders).

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

## `search_code`

Case-insensitive substring search across all text files in the project.

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

## `import_step`

Download a STEP file from an HTTPS URL into the project. Times out after 30s; rejects files over 50MB.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "url": {
      "type": "string"
    },
    "parent_path": {
      "type": "string"
    }
  },
  "required": [
    "name",
    "url"
  ]
}
```

---

## `import_kicad`

Import a KiCad schematic or PCB project into the current project. Accepts the path to a .kicad_sch file or a project directory containing .kicad_sch / .kicad_pcb files. Returns extracted components, nets, and footprints.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "project_path": {
      "type": "string",
      "description": "Absolute path to a .kicad_sch file or directory containing KiCad project files."
    }
  },
  "required": [
    "project_path"
  ]
}
```

---

## See also

- Package: `kerf_api`
