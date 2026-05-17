# kerf-cam — CNC CAM plugin: 3-axis + 5-axis G-code generation

`kerf-cam` generates G-code toolpaths from STEP/mesh geometry. It supports 3-axis (2.5D pocket/contour/facing) and 5-axis (constant-tilt surface machining, 3+2 indexed) operations, a tool database, and multiple machine controller posts.

Heavy deps (`opencamlib`, `pythonocc-core`) are optional. The plugin always loads and provides a mock toolpath when they are absent (`cam.2_5d` always declared; `cam.parallel-3d`, `cam.waterline`, `cam.lathe` conditional on opencamlib).

---

## Plugin registration

```python
async def register(app, ctx):
    app.include_router(router)                    # POST /run-cam
    ctx.tools.register("cam_run", ...)            # LLM: queue a CAM job
    ctx.tools.register("cam_job_status", ...)     # LLM: poll job status
    ctx.tools.register("create_tool", ...)        # Tool DB
    ctx.tools.register("update_tool", ...)
    ctx.tools.register("delete_tool", ...)
    ctx.tools.register("list_tools", ...)
    ctx.workers.register("cam", cam_worker_factory)
    return PluginManifest(
        name="cam",
        provides=["cam.2_5d", "cam.parallel-3d", ...],  # conditional on deps
        depends=["cad-core"],
    )
```

---

## LLM tools

### `cam_run` — queue a CAM operation

Inserts a row into `cam_jobs` with `status='queued'` and returns the `job_id` for polling.

```json
{
  "file_id": "<uuid of STEP/mesh file>",
  "operation": "pocket | contour | face | waterline | parallel | drill | lathe | 5axis_constant_tilt | 5axis_indexed_3_2",
  "tool_id": "<uuid from tool DB>",
  "stepdown": 2.0,
  "stepover": 5.0,
  "feedrate": 800,
  "spindle_rpm": 12000,
  "clearance_height": 10.0,
  "stock_offset": 0.5,
  "post": "grbl | linuxcnc | fanuc | mach3"
}
```

Returns: `{job_id: "<uuid>", status: "queued"}`.

### `cam_job_status` — poll a CAM job

```json
{"job_id": "<uuid>"}
```

Returns: `{status: "queued|running|done|error", result: {gcode_b64, stats}, error: "..."}`.

When `status == "done"`, `result.gcode_b64` contains the base64-encoded G-code text. `result.stats` has `{toolpath_length_mm, estimated_time_sec, operation, post}`.

### Tool database tools

| Tool | Description |
|---|---|
| `create_tool` | Add a cutting tool to the project's tool library (`kind, diameter_mm, flute_count, material, ...`) |
| `update_tool` | Modify tool parameters |
| `delete_tool` | Remove a tool |
| `list_tools` | List tools in the project's tool library |

---

## 3-axis operations

The 3-axis module wraps opencamlib (waterline, parallel, adaptive clearing) and generates G-code via post-processors.

### Posts (`kerf_cam.posts`)

| Post | Module | Controller |
|---|---|---|
| `grbl` | `posts/grbl_3x.py` | GRBL (hobby routers, laser cutters) |
| `linuxcnc` | `posts/linuxcnc_3x.py` | LinuxCNC (open-source machine controller) |
| `fanuc` | `posts/fanuc_3x.py` | Fanuc 0i / 21i |
| `mach3` | `posts/mach3_3x.py` | Mach3 / Mach4 (Windows CNC software) |

Common post fields: tool change (`T1 M6`), spindle on/off, flood coolant, coordinate mode (G90 absolute), units (G21 mm), end of program (M30).

---

## 5-axis operations (`kerf_cam.five_axis`)

### Constant-tilt surface machining

Machines a drive face with a fixed tool tilt angle (e.g. 15° from surface normal). Used for flank milling ruled surfaces and compound curved faces.

```python
# kerf_cam/five_axis/constant_tilt.py
result = machine_constant_tilt(
    drive_face,        # OCC TopoDS_Face
    tilt_deg=15.0,
    stepover_mm=0.5,
    tool_dia_mm=6.0,
    post="fanuc",
)
```

Posts: `five_axis/posts/fanuc_5x.py`, `five_axis/posts/linuxcnc_5x.py`.

### 3+2 indexed (G-code indexed)

Generates a 3-axis toolpath for a rotated workpiece orientation. The table tilts once to the indexed angle, then a standard 3-axis toolpath runs, then the table resets.

```python
# kerf_cam/five_axis/indexed_3_2.py
indexed_job(
    face,
    a_angle_deg=45.0,    # B-axis tilt
    b_angle_deg=0.0,     # A-axis rotation
    operation="pocket",
    post="fanuc",
)
```

The G-code uses `G68.2` / `G53.2` (Fanuc tilted work plane) or `G68 A B` / fixture offset (LinuxCNC) depending on the post.

---

## Tool DB (`kerf_cam.tool_db`)

Tools are stored as `kind='tool'` files in the project. The `tool_db` module provides CRUD operations backed by the project's file tree. Each tool record:

```json
{
  "version": 1,
  "kind": "endmill",
  "diameter_mm": 6.0,
  "flute_count": 4,
  "overall_length_mm": 75.0,
  "flute_length_mm": 22.0,
  "material": "carbide",
  "coating": "TiAlN",
  "max_rpm": 24000,
  "max_feedrate_mm_min": 3000,
  "notes": ""
}
```

---

## CAM worker (`kerf_cam.worker.CAMWorker`)

Extends `BaseWorker`. Claims rows from `cam_jobs` with `status='queued'`, dispatches to pyworker at `PYWORKER_URL/run-cam`, writes G-code back to the DB as `result_json`.

The pyworker side runs the OpenCASCADE + opencamlib code in a subprocess with the heavy deps installed.

---

## `/run-cam` route

Direct HTTP endpoint for integration tests. Accepts a `CamRequest` body with STEP content, operation spec, and tool parameters. Returns G-code synchronously (bypasses the job queue). Used primarily in `test_cam_step.py` and `test_5axis_e2e.py`.

---

## posts_common (`kerf_cam.posts_common`)

Shared utilities across all post-processors:
- `format_coord(value, decimals=3)` — format mm values
- `rapid(x, y, z)` → `G0 X… Y… Z…`
- `linear(x, y, z, feed)` → `G1 X… Y… Z… F…`
- `arc_cw / arc_ccw` → `G2/G3`
- Header / footer boilerplate per controller dialect
