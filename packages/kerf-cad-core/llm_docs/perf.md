# perf

*Module: `kerf_cad_core.assembly.perf` · Domain: cad*

This module registers **2** LLM tool(s):

- [`assembly_perf_report`](#assembly-perf-report)
- [`assembly_lod_plan`](#assembly-lod-plan)

---

## `assembly_perf_report`

Run a performance harness on a given assembly (or a freshly generated synthetic assembly of size N) and return structured timing + memory data. 
If ``assembly`` is supplied it is measured directly.  If ``n`` is supplied instead, a synthetic assembly of that many components is built first using the specified ``depth`` and ``branching`` parameters. 
Returns:
  n_components        — total leaf component count
  solve_time_s        — wall-clock seconds for solve_assembly
  bom_time_s          — wall-clock seconds for BOM roll-up
  total_time_s        — total measurement time
  peak_memory_bytes   — peak resident memory delta during measurement
  status              — constraint status ('fully_constrained' etc.)
  n_unique_parts      — number of distinct part_refs

Never raises; invalid inputs return a friendly error.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "assembly": {
      "type": "object",
      "description": "Assembly dict to measure (optional \u2014 mutually exclusive with n)."
    },
    "n": {
      "type": "integer",
      "description": "Component count for a fresh synthetic assembly (optional).",
      "minimum": 1
    },
    "depth": {
      "type": "integer",
      "description": "Sub-assembly nesting depth for synthetic assembly. Default 2.",
      "minimum": 0
    },
    "branching": {
      "type": "integer",
      "description": "Branching factor for synthetic assembly. Default 4.",
      "minimum": 1
    }
  },
  "required": []
}
```

---

## `assembly_lod_plan`

Compute a Level-of-Detail (LOD) plan for an assembly given a viewport triangle and part-count budget. 
Each component is assigned:
  'full'       — render at full triangle resolution
  'bbox_proxy' — render as a bounding-box proxy only
  'culled'     — do not render

Heuristic: largest/most complex components receive 'full' first until the triangle budget is exhausted; the next tier gets 'bbox_proxy' until the visible-part budget is exhausted; the rest are 'culled'. 
Returns:
  entries             — list of {instance_id, part_ref, detail, tri_count, importance}
  total_full_triangles — sum of triangles for 'full' components
  total_visible_parts — count of 'full' + 'bbox_proxy' components
  load_order          — instance_ids in recommended load order (nearest/largest first)
  error               — friendly message if budget is invalid (all culled)

Never raises; invalid budget returns a friendly error in the payload.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "assembly": {
      "type": "object",
      "description": "Assembly dict."
    },
    "max_triangles": {
      "type": "integer",
      "description": "Maximum total triangle count for full-detail components.",
      "minimum": 1
    },
    "max_visible_parts": {
      "type": "integer",
      "description": "Maximum total number of rendered components (full + bbox).",
      "minimum": 1
    },
    "camera_x": {
      "type": "number",
      "description": "Camera X position (mm). Default 0."
    },
    "camera_y": {
      "type": "number",
      "description": "Camera Y position (mm). Default 0."
    },
    "camera_z": {
      "type": "number",
      "description": "Camera Z position (mm). Default 0."
    },
    "mesh_url": {
      "type": "string",
      "description": "Optional URL or local path to the assembly's primary mesh asset (.glb/.gltf). When provided, the first component's triangle estimate is derived from the file byte count (triangles \u2248 bytes // 36) for a more accurate LOD tier."
    },
    "mesh_byte_count": {
      "type": "integer",
      "description": "Pre-computed byte size for an HTTP mesh_url (avoids network I/O)."
    }
  },
  "required": [
    "assembly",
    "max_triangles",
    "max_visible_parts"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
