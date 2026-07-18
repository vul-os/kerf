# kerf-tess — STEP-to-GLB tessellation plugin

`kerf-tess` converts STEP/B-rep files to GLB meshes for browser-side 3D rendering. It provides a `/run-tess` HTTP route, an `AutoTessWorker` for server-mode background pre-tessellation, and the `TessInputSpec` / `TessResult` data contracts used across the pipeline.

Depends on `cad-core`. Provides `tess.step-to-glb` when pythonOCC is available; falls back to the Node.js occt-import-js sidecar otherwise.

---

## Plugin registration

```python
# kerf_tess/plugin.py
async def register(app, ctx) -> PluginManifest:
    from kerf_tess.routes import router
    app.include_router(router)                      # mounts /run-tess

    if not ctx.local_mode:
        ctx.workers.register("auto_tess", auto_tess_factory)

    provides = ["tess.step-to-glb"] if _OCC_AVAILABLE else []
    return PluginManifest(
        name="tess",
        version="0.1.0",
        provides=provides,
        depends=["cad-core"],
    )
```

When `_OCC_AVAILABLE` is False the plugin still loads and the route still mounts — it just falls back to the Node sidecar path. The `tess.step-to-glb` capability flag is absent so other plugins can gate on it.

---

## `/run-tess` route

**POST /run-tess**

Accepts a base64-encoded STEP file and optional `TessInputSpec` parameters. Returns a base64-encoded GLB.

### Request body

```json
{
  "step_b64": "<base64-encoded STEP bytes>",
  "input_spec": {
    "resolution": 50000,
    "export_format": "glb",
    "scale": 1.0
  }
}
```

| Field | Default | Description |
|---|---|---|
| `resolution` | `50000` | Target triangle count for mesh LOD |
| `export_format` | `"glb"` | Output format: `"glb"` or `"obj"` |
| `scale` | `1.0` | Uniform scale factor applied before export |

### Response body

```json
{
  "glb_b64": "<base64-encoded GLB bytes>",
  "warnings": [],
  "errors": []
}
```

If tessellation fails, `glb_b64` is empty and `errors` contains the reason. The HTTP status is still 200 — callers must check `errors`.

### Node sidecar dispatch

The route dispatches to a `step-tessellate.mjs` Node.js script using `occt-import-js`. The script reads a JSON line from stdin (`{step_b64: ...}`) and writes `{glb_b64: ...}` to stdout.

Sidecar binary lookup order:
1. `<repo-root>/scripts/step-tessellate.mjs`
2. `<cwd>/scripts/step-tessellate.mjs`
3. `scripts/step-tessellate.mjs`

Configure the Node binary with `NODE_BIN` env var (default: `node`).

---

## Data contracts (`kerf_tess.specs`)

### TessInputSpec

```python
spec = TessInputSpec(resolution=50000, export_format="glb", scale=1.0)
spec_dict = spec.to_dict()
spec2 = TessInputSpec.from_dict(spec_dict)
```

### TessResult

```python
result = TessResult(output_key="artifacts/abc.glb", warnings=[], errors=[])
d = result.to_dict()
# → {"output_key": "...", "warnings": [], "errors": []}
```

Import from `kerf_tess.specs` to avoid a `backend` dependency.

---

## AutoTessWorker (server mode only)

`AutoTessWorker` is registered only when `local_mode=False`. In a single-user local install, tessellation happens in the browser instead.

### Trigger

The worker listens on the Postgres `NOTIFY` channel `step_file_uploaded`. When a STEP file is uploaded, the upload handler fires:

```python
from kerf_tess.worker import notify_step_uploaded
await notify_step_uploaded(conn, file_id)
```

The worker wakes immediately and claims the matching row from `step_tessellation_jobs`.

### Job lifecycle

1. Upload handler inserts a row in `step_tessellation_jobs` with `status='queued'`
2. `notify_step_uploaded` fires `pg_notify('step_file_uploaded', file_id)`
3. Worker claims the row with `FOR UPDATE SKIP LOCKED`
4. Worker fetches the STEP blob from object storage
5. Worker calls pyworker `/run-tess` (HTTP RPC to the Node sidecar process)
6. Worker stores the resulting GLB in `derived_artifacts` keyed by `(file_id, content_sha256, 'step_mesh')` — content-hash idempotency prevents duplicate work
7. Worker updates `files.mesh_storage_key` so the frontend can resolve the mesh directly
8. Worker marks the job `done` or `error`

Stuck jobs (running > 600 seconds) are automatically re-queued on worker startup.

### Error recovery

The worker uses `FOR UPDATE SKIP LOCKED` — multiple worker processes can run safely in parallel. Each takes a different queued row. On process crash, `stuck_running_recovery` re-queues jobs left in `running` state older than 10 minutes.

---

## Integration with kerf-api

When `kerf_api.tools.object_ops` receives a STEP upload above `LARGE_STEP_THRESHOLD` (5 MB), it directly calls `POST /run-tess` on the pyworker URL for an immediate synchronous tessellation. For smaller files the frontend can tessellate inline via the browser path.

The cloud AutoTessWorker is an asynchronous complement to this: it pre-computes the GLB and stores it, so repeat views of the same STEP do not re-tessellate.

---

## Usage example

```python
import base64, httpx

step_bytes = Path("part.step").read_bytes()
resp = httpx.post(
    "http://localhost:8000/run-tess",
    json={
        "step_b64": base64.b64encode(step_bytes).decode(),
        "input_spec": {"resolution": 20000, "export_format": "glb"},
    },
)
body = resp.json()
if not body["errors"]:
    Path("part.glb").write_bytes(base64.b64decode(body["glb_b64"]))
```
