# xref

*Module: `kerf_bim.tools.xref` · Domain: bim*

This module registers **5** LLM tool(s):

- [`bim_add_xref`](#bim-add-xref)
- [`bim_check_xref_status`](#bim-check-xref-status)
- [`bim_refresh_xref`](#bim-refresh-xref)
- [`bim_compose_federated`](#bim-compose-federated)
- [`bim_list_xrefs`](#bim-list-xrefs)

---

## `bim_add_xref`

Add an external IFC file as a live federated reference (XRef) to the project. Specify the path to the .ifc file, its discipline (structural/mep/architecture/civil), an optional placement origin in mm, and an optional Z-axis rotation. Returns an updated XRefManifest JSON containing all references.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "manifest": {
      "description": "Existing XRefManifest JSON string or dict. Pass {} or omit for a new manifest."
    },
    "source_path": {
      "type": "string",
      "description": "Absolute or project-relative path to the .ifc file."
    },
    "discipline": {
      "type": "string",
      "enum": [
        "architecture",
        "civil",
        "mep",
        "structural"
      ],
      "description": "Discipline classification of the linked model."
    },
    "reference_origin_xyz_mm": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 3,
      "maxItems": 3,
      "description": "[x, y, z] offset in mm for composing into the federated model."
    },
    "reference_rotation_deg": {
      "type": "number",
      "description": "Z-axis rotation in degrees (default 0)."
    }
  },
  "required": [
    "source_path",
    "discipline"
  ]
}
```

---

## `bim_check_xref_status`

Check whether a federated IFC reference is current, stale, or missing. Compares the stored SHA-256 hash against the current file on disk. No IFC parsing is performed — fast disk-hash only.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "source_path": {
      "type": "string",
      "description": "Path to the .ifc file (same value used in bim_add_xref)."
    },
    "discipline": {
      "type": "string",
      "enum": [
        "architecture",
        "civil",
        "mep",
        "structural"
      ]
    },
    "last_loaded_hash": {
      "type": "string",
      "description": "Hash stored in XRefSpec. Pass '' if never loaded."
    }
  },
  "required": [
    "source_path",
    "discipline"
  ]
}
```

---

## `bim_refresh_xref`

Re-import a federated IFC reference from disk, update its SHA-256 hash, and return geometry statistics. Use after bim_check_xref_status reports is_stale=true. Returns {status, element_count, updated_spec}.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "source_path": {
      "type": "string",
      "description": "Path to the .ifc file."
    },
    "discipline": {
      "type": "string",
      "enum": [
        "architecture",
        "civil",
        "mep",
        "structural"
      ]
    },
    "reference_origin_xyz_mm": {
      "type": "array",
      "items": {
        "type": "number"
      }
    },
    "reference_rotation_deg": {
      "type": "number"
    },
    "last_loaded_hash": {
      "type": "string"
    }
  },
  "required": [
    "source_path",
    "discipline"
  ]
}
```

---

## `bim_compose_federated`

Build the complete federated model by refreshing all XRefs in the manifest and grouping loaded geometry by discipline. Returns {per_discipline_counts, total_elements, disciplines_loaded}.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "manifest": {
      "description": "XRefManifest JSON string or dict."
    }
  },
  "required": [
    "manifest"
  ]
}
```

---

## `bim_list_xrefs`

List all federated XRef entries in the manifest, including their discipline, path, and last-loaded hash. Cheap read-only operation.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "manifest": {
      "description": "XRefManifest JSON string or dict."
    }
  },
  "required": [
    "manifest"
  ]
}
```

---

## See also

- Package: `kerf_bim`
