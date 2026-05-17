# Instant Meshes Runner (`instant_meshes_runner.py`)

Subprocess wrapper for the Instant Meshes quad-remeshing binary; converts
a triangle-mesh OBJ file into a quad-dominant mesh and returns structured
vertex/face data.

---

## When to use

Reach for this module (or the `feature_quad_remesh` tool that wraps it) when:

- preparing a scan or subdivision-surface mesh for Catmull-Clark SubD (requires quad topology)
- retopologising an organic shape before FEA meshing (structured quads give better element quality)
- converting a dense STL/OBJ to a coarser, more regular quad mesh for downstream modelling

---

## Entry point

### `run_instant_meshes(obj_path, target_verts, smoothness, align_to_boundary) -> dict`

```python
from kerf_cad_core.instant_meshes_runner import run_instant_meshes

result = run_instant_meshes(
    obj_path="/tmp/scan.obj",
    target_verts=5000,
    smoothness=2,
    align_to_boundary=True,
)
# result keys: vertices, quads, triangles, stats
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `obj_path` | str | — | Absolute path to input OBJ file |
| `target_verts` | int | 5000 | Approximate output vertex count (±20% actual) |
| `smoothness` | int | 2 | Smoothing iterations (0–6); higher = more regular faces, less feature detail |
| `align_to_boundary` | bool | True | Pass `--boundaries` to snap edge loops to sharp creases |

**Returns:**

```python
{
    "vertices":   [[x, y, z], ...],
    "quads":      [[a, b, c, d], ...],   # 0-based indices
    "triangles":  [[a, b, c], ...],      # residual tris
    "stats": {
        "vertex_count": int,
        "quad_count":   int,
        "tri_count":    int,
        "elapsed_s":    float,
        "target_verts": int,
        "smoothness":   int,
        "align_boundary": bool,
    },
}
```

**Raises:**

- `InstantMeshesNotInstalledError` — binary `instant-meshes` absent from PATH
- `RuntimeError` — non-zero exit code or output OBJ parse failure

---

## Supported input contract

- Input must be a valid OBJ file with `v` and `f` lines; `vn`/`vt` indices are stripped.
- Only tri and quad faces in the output are kept (n-gons with n > 4 are ignored).
- The binary is invoked with a 30-second timeout; large meshes may need `target_verts` reduced.
- Requires `instant-meshes` on PATH.  Pre-built releases:
  https://github.com/wjakob/instant-meshes/releases (MIT licence).

---

## LLM tool wrapper

The `feature_quad_remesh` tool (in `quad_remesh.py`) exposes this runner
as a registered LLM tool.  Use that for file-based chat workflows; use
`run_instant_meshes` directly in scripting / pipeline code.

---

## Usage examples

**Remesh a coarse STL-derived OBJ to 2000 quads:**

```python
result = run_instant_meshes("/tmp/part.obj", target_verts=2000, smoothness=3)
print(result["stats"]["quad_count"])  # e.g. 1987
```

**High-smoothness retopology for organic SubD modelling:**

```python
result = run_instant_meshes("/tmp/body.obj", target_verts=8000, smoothness=5, align_to_boundary=False)
```

**Binary-absent graceful fallback (from quad_remesh tool):**

```
feature_quad_remesh
  file_id: "<uuid>"  target_feature_ref: "pad-1"  target_vertex_count: 4000
→ {status: "binary_missing", warning: "...", hint: "Install Instant Meshes..."}
```

---

## References

Jakob, W., Tarini, M., Panozzo, D., Sorkine-Hornung, O. — *Instant Field-Aligned Meshes*, ACM Trans. Graph. 34(6), 2015.
