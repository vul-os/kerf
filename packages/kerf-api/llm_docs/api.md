# kerf-api — HTTP API layer + LLM tool families

`kerf-api` is the primary REST API plugin. It mounts all project/file/user/workspace management routes under `/api/` and registers the core LLM tool families used by the chat agent to manipulate project content.

Depends on `kerf-auth` (loads after it).

---

## Plugin registration

```python
# kerf_api/plugin.py
PLUGIN_DEPENDS = ["kerf-auth"]

async def register(app, ctx) -> PluginManifest:
    app.include_router(router, prefix="/api")
    _register_tools(ctx)   # imports each tool module, wires spec+handler pairs
    return PluginManifest(
        name="kerf-api",
        provides=["api.rest", "files.crud", "projects.crud"],
        depends=["kerf-auth"],
    )
```

Tool modules registered at startup:
`file_ops`, `object_ops`, `scaffold`, `revisions`, `configurations`, `equations`, `validation`, `project_layers`, `material`

Each module exposes `<name>_spec` (a `ToolSpec`) and `run_<name>` (an async handler). The plugin walks these pairs by convention and registers them into `ctx.tools`.

---

## REST routes (`/api/…`)

### Bootstrap

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/config` | None | Server-side feature flags for the frontend (`local_mode`, OAuth availability). No secrets. |

### Users / Me

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/me` | JWT | Authenticated user + default workspace |
| PATCH | `/api/me` | JWT | Update display name, avatar |
| GET | `/api/me/preferences` | JWT | User preferences blob |
| PATCH | `/api/me/preferences` | JWT | Update preferences |

### Workspaces

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/workspaces` | JWT | List workspaces the user belongs to |
| POST | `/api/workspaces` | JWT | Create workspace |
| GET | `/api/workspaces/{slug}` | JWT | Get workspace by slug |
| PATCH | `/api/workspaces/{slug}` | JWT | Update name/avatar |
| GET | `/api/workspaces/{slug}/members` | JWT | List members |
| POST | `/api/workspaces/{slug}/members` | JWT | Invite member |
| DELETE | `/api/workspaces/{slug}/members/{uid}` | JWT | Remove member |

### Projects

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/projects` | JWT | List projects in a workspace (query: `workspace_slug`) |
| POST | `/api/projects` | JWT | Create project |
| GET | `/api/projects/{id}` | JWT/public | Get project details |
| PATCH | `/api/projects/{id}` | JWT | Update name, description, visibility |
| DELETE | `/api/projects/{id}` | JWT | Soft-delete project |
| GET | `/api/projects/{id}/thumbnail` | None | Redirect to project thumbnail |

### Files

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/projects/{id}/files` | JWT | List file tree |
| POST | `/api/projects/{id}/files` | JWT | Create file/folder |
| GET | `/api/projects/{id}/files/{fid}` | JWT | Get file content + metadata |
| PATCH | `/api/projects/{id}/files/{fid}` | JWT | Update content or rename |
| DELETE | `/api/projects/{id}/files/{fid}` | JWT | Soft-delete |
| GET | `/api/projects/{id}/files/{fid}/revisions` | JWT | List revision history |
| GET | `/api/projects/{id}/files/{fid}/revisions/{rid}` | JWT | Get specific revision content |
| POST | `/api/projects/{id}/files/upload` | JWT | Initiate chunked upload session |
| PUT | `/api/projects/{id}/files/upload/{key}/{n}` | JWT | Upload chunk `n` |
| POST | `/api/projects/{id}/files/upload/{key}/complete` | JWT | Finalize chunked upload |

### Chat / Tool-call dispatch

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/projects/{id}/chat` | JWT | Send a message to the chat agent. Streams SSE events. |
| GET | `/api/projects/{id}/threads` | JWT | List chat threads |
| GET | `/api/projects/{id}/threads/{tid}/messages` | JWT | Get messages in a thread |
| DELETE | `/api/projects/{id}/threads/{tid}` | JWT | Delete thread |

### Library / Workshop / BOM

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/library` | Optional | Search/list published library items |
| POST | `/api/library/submit` | JWT | Submit project to library |
| GET | `/api/workshop` | Optional | Workshop feed |
| POST | `/api/workshop/{id}/like` | JWT | Like a workshop post |
| GET | `/api/projects/{id}/bom` | JWT | Bill of materials for a project |

### Distributors (cloud)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/distributors` | JWT | List configured distributor integrations |
| POST | `/api/distributors/{name}/credentials` | JWT | Save encrypted API credentials |
| DELETE | `/api/distributors/{name}/credentials` | JWT | Remove credentials |
| GET | `/api/distributors/{name}/search` | JWT | Search parts via distributor API |

---

## LLM tool families

### `file_ops` — CRUD on project files

Tools: `read_file`, `write_file`, `delete_file`, `move_file`, `list_files`, `create_folder`

All tools receive a `ProjectCtx` (pool, project_id, user_id, storage) and a JSON args bytes payload. They return JSON strings via `ok_payload(...)` / `err_payload(msg, code)`.

`write_file` automatically calls `write_revision` (from `kerf_core.revisions`) to record a diff/base revision. The revision cap is enforced (`file_revisions_max`, default 200).

### `object_ops` — STEP / mesh storage operations

Tools: `import_step`, `export_step`, `get_step_info`

Handles chunked storage-key resolution; posts to pyworker for STEP tessellation when a STEP file is uploaded above `LARGE_STEP_THRESHOLD` (5 MB).

### `scaffold` — project-type bootstrapping

Tools: `scaffold_project`, `create_part`, `create_circuit`, `create_script`

Creates the boilerplate file tree for a project type (mechanical, electronics, jewelry, BIM, etc.). `create_part` produces a `kind='part'` file with the canonical `.part` JSON body consumed by BOM/library tooling.

### `revisions` — fine-grained undo

Tools: `list_revisions`, `restore_revision`

`restore_revision` writes the historical content back as a new revision (non-destructive — the full history is preserved).

### `configurations` — parametric configurations

Tools: `create_configuration`, `list_configurations`, `apply_configuration`, `delete_configuration`

Configurations store named sets of equation/parameter overrides that can be swapped to drive design variants.

### `equations` — parameter/equation management

Tools: `set_equation`, `get_equation`, `list_equations`, `delete_equation`

Equations are stored in a `kind='equations'` file as a JSON dict. They drive parametric features via expression evaluation.

### `validation` — design rule checks

Tools: `validate_model`, `get_validation_results`

Dispatches to the appropriate validator (FEM mesh, drawing sheet, circuit BOM completeness, etc.) based on file kind.

### `project_layers` — PCB / CAD layer management

Tools: `list_project_layers`, `add_layer`, `update_layer`, `remove_layer`, `reorder_layers`

Manages the ordered layer stack for a project. Used by both PCB (copper/silkscreen layers) and CAD (visibility layers) workflows.

### `material` — material assignment

Tools: `assign_material`, `get_material`, `list_materials`, `remove_material`

Materials are stored in the project's `kind='material'` file. The material body carries name, density, Young's modulus, yield strength, and PBR rendering parameters used by the viewport.

### `assembly_management` — multi-body assembly

Tools: `add_component`, `remove_component`, `list_components`, `set_component_transform`

Manages the component list in an `assembly` file. Transforms are stored as 4×4 matrix floats.

---

## Request / response patterns

All LLM tool handlers follow:
```python
async def run_my_tool(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    # … business logic …
    return ok_payload({"key": value})
```

`ok_payload` wraps in `{"ok": true, ...}`. `err_payload(msg, code)` wraps in `{"ok": false, "error": msg, "code": code}`.

Standard error codes: `BAD_ARGS`, `NOT_FOUND`, `PERMISSION_DENIED`, `CONFLICT`, `WORKER_UNAVAILABLE`, `WORKER_ERROR`.

---

## Auth gates

All `/api/projects/{id}/*` endpoints verify that the calling user is the project owner or an invited project member. The `require_auth` dependency (from `kerf_core.dependencies`) handles JWT / opaque API token validation. Public endpoints (library search, workshop feed, project pages with `visibility='public'`) use `optional_auth`.
