# heal

*Module: `kerf_imports.heal` · Domain: imports*

This module registers **4** LLM tool(s):

- [`heal_mesh`](#heal-mesh)
- [`validate_watertight`](#validate-watertight)
- [`step_ap242_metadata`](#step-ap242-metadata)
- [`interop_report`](#interop-report)

---

## `heal_mesh`

Run the full geometry healing pipeline on a .mesh file: stitch gaps, remove slivers, merge tiny edges, unify normals, remove duplicates, detect self-intersections, detect non-manifold geometry, and fill small holes. Returns a per-step delta report.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the .mesh file."
    },
    "tolerance": {
      "type": "number",
      "description": "Merge/stitch tolerance in model units (default 1e-4)."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## `validate_watertight`

Check whether a .mesh file is a closed watertight 2-manifold. Runs an Euler-characteristic check (V−E+F) and boundary-edge scan.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the .mesh file."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## `step_ap242_metadata`

Parse STEP AP242 PMI and semantic metadata from a raw STEP file stored as a text/plain file. Extracts product name, GD&T annotation presence, assembly tree depth, and header timestamps.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the STEP file (kind=step or text)."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## `interop_report`

Generate a downstream interoperability readiness report for a .mesh file: watertight, manifold, issue count, and face/vertex stats.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the .mesh file."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## See also

- Package: `kerf_imports`
