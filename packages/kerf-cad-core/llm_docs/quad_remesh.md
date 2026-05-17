# Quad Remesh (`quad_remesh.py`)

LLM tool that drives Instant Meshes to produce a quad-dominant remesh of
a triangle mesh, appending a `quad_remesh` node to a `.feature` file.

---

## When to use

Reach for this tool when the user asks to:

- retopologise a scan, SubD base, or triangle mesh for Catmull-Clark subdivision
- generate structured quads for downstream FEA meshing (better element quality)
- reduce polygon count while preserving topology flow

---

## Tool

### `feature_quad_remesh`

Append a `quad_remesh` node to a `.feature` file, then attempt to run
Instant Meshes on the referenced mesh.  If the binary is absent the node
is still written and the response includes an install hint.

**Required:**
- `file_id` (UUID) — target `.feature` file
- `target_feature_ref` (str) — node id of the source mesh (e.g. `pad-1`)

**Optional:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `target_vertex_count` | int | 5000 | Approximate output vertex count (±20%) |
| `crease_angle_deg` | float | 20.0 | Dihedral threshold for sharp creases (stored on node; `align_to_boundary` controls IM) |
| `align_to_boundary` | bool | true | Pass `--boundaries` to Instant Meshes |
| `smoothness_iters` | int | 2 | Smoothing passes (0–6) |

**Returns:**

```json
{
  "file_id": "<uuid>",
  "id": "quad-remesh-1",
  "op": "quad_remesh",
  "target_feature_ref": "pad-1",
  "target_vertex_count": 5000,
  "crease_angle_deg": 20.0,
  "align_to_boundary": true,
  "smoothness_iters": 2,
  "status": "ok",
  "stats": { "vertex_count": 4987, "quad_count": 4980, "tri_count": 7, "elapsed_s": 1.4 }
}
```

When `instant-meshes` binary is absent:

```json
{
  "status": "binary_missing",
  "warning": "...",
  "hint": "Install Instant Meshes and ensure 'instant-meshes' is on PATH..."
}
```

**Errors:** `{ok:false, reason}` for invalid `file_id` or missing `target_feature_ref`.

---

## Supported input contract

- Requires the `instant-meshes` binary on PATH.
- `target_vertex_count` must be ≥ 1; `smoothness_iters` must be 0–6.
- The tool writes a feature node regardless of whether IM is installed
  (graceful degradation — node is in the file for re-evaluation later).
- Full mesh extraction (OCC → OBJ) happens via the HTTP route; the LLM
  tool uses a placeholder cube OBJ for binary validation.

---

## Usage examples

**Retopologise a pad feature to 3000 quads:**

```
feature_quad_remesh
  file_id: "<uuid>"
  target_feature_ref: "pad-1"
  target_vertex_count: 3000
  smoothness_iters: 3
→ {id: "quad-remesh-1", status: "ok", stats: {quad_count: 2991, ...}}
```

**Graceful degradation (binary not installed):**

```
feature_quad_remesh
  file_id: "<uuid>"
  target_feature_ref: "sweep1-1"
→ {status: "binary_missing", hint: "Install Instant Meshes..."}
```

---

## References

Jakob, W. et al. — *Instant Field-Aligned Meshes*, ACM Trans. Graph. 34(6), 2015.
Instant Meshes source: https://github.com/wjakob/instant-meshes (MIT licence).
