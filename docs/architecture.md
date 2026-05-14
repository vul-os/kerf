# Architecture

How Kerf is wired end to end — from a chat message to a re-rendered model.

## The big picture

```
┌───────────────────────────┐         ┌────────────────────────────┐
│        Browser            │         │     Python server (kerf)      │
│                           │         │                            │
│  React + Vite + Three.js  │ ◄─────► │  FastAPI · asyncpg · auth   │
│  Monaco · planegcs · OCCT │   HTTP  │  Storage · LLM clients     │
│  IndexedDB mesh cache     │         │  Tool registry · Agent loop│
│  Web Worker (JSCAD eval)  │         │  pyworker compute sidecar  │
└───────────────────────────┘         └─────────────┬──────────────┘
                                                     │
                                        ┌────────────┴─────────────┐
                                        │     Postgres (asyncpg)       │
                                        │  users / projects /      │
                                        │  files / file_revisions  │
                                        │  chat_threads / messages │
                                        └────────────┬─────────────┘
                                                     │
                                        ┌────────────┴─────────────┐
                                        │   Storage (local/s3/git) │
                                        │  STEP files, chunks,     │
                                        │  cloud thumbnails        │
                                        └──────────────────────────┘
```

Single binary. Single Postgres. Pluggable storage. Pluggable LLM provider.

## Stack

- **Frontend**: Vite 8 + React 19 + React Router 7 SPA. Tailwind v4. Zustand state.
  Three.js r160 3D viewport with BVH raycaster. `@jscad/modeling` 2.x in a Web
  Worker for non-blocking mesh eval. `@salusoft89/planegcs` sketch solver.
  `occt-import-js` STEP loader. IndexedDB mesh cache keyed by JSCAD content hash.
- **Backend**: Python FastAPI. asyncpg + SQLAlchemy (async). JWT + opaque refresh
  tokens. Google OAuth via `authlib`. TOML config (`tomllib`/`tomli`).
  Provider-agnostic LLM ABC with concrete clients for Anthropic, OpenAI, Moonshot,
  Gemini.
- **Compute sidecar**: `pyworker` — async Python worker for heavy CPU/GPU tasks
  (render, simulation, FEM, RF study). Communicates over HTTP or Redis queue.
- **Storage**: See §Storage abstraction.

## Frontend (detail)

A 4-tier debounce throttles JSCAD re-eval based on file size: 250 ms for tiny
files up to ~3 s for huge ones, so the viewport stays responsive whatever
the source size.

## File kinds

Kerf supports **40+ file kinds**. Each kind has a dedicated schema doc in
`backend/llm_docs/<kind>.md` consulted by the LLM before authoring or editing
that kind.

| Kind | Purpose | Doc |
|------|---------|-----|
| `.jscad` | Code-driven mesh via JSCAD scripting | [jscad.md](./backend/llm_docs/jscad.md) |
| `.feature` | OCCT B-rep feature tree (pad/pocket/fillet/etc.) | [feature.md](./backend/llm_docs/feature.md) |
| `.sketch` | 2D constraint-managed geometry (planegcs) | [sketch.md](./backend/llm_docs/sketch.md) |
| `.assembly` | BOM-driven product structure | [assembly.md](./backend/llm_docs/assembly.md) |
| `.drawing` | Multi-sheet manufacturing drawings with GD&T | [drawing.md](./backend/llm_docs/drawing.md) |
| `.part` | Library part with MPN, distributors, photos | [part.md](./backend/llm_docs/part.md) |
| `.circuit.tsx` | tscircuit electronics (JSX) | [circuit.md](./backend/llm_docs/circuit.md) |
| `.simulation` | FEA/simulation metadata | [simulation.md](./backend/llm_docs/simulation.md) |
| `.bim` | Building information model elements | [bim.md](./backend/llm_docs/bim.md) |
| `.family` | Part family with parameter variants | [family.md](./backend/llm_docs/family.md) |
| `.schedule` | BOM/configuration schedule | [schedule.md](./backend/llm_docs/schedule.md) |
| `.view` | Saved camera + visibility state | [view.md](./backend/llm_docs/view.md) |
| `.sheet` | Layout sheet for drawings | [sheet.md](./backend/llm_docs/sheet.md) |
| `.render` | Blender Cycles render scene | [render.md](./backend/llm_docs/render.md) |
| `.graph` | Signal/power graph connectivity | [graph.md](./backend/llm_docs/graph.md) |
| `.subd` | Subdivision surface mesh | [subd.md](./backend/llm_docs/subd.md) |
| `.mesh` | Raw triangulated mesh | [mesh.md](./backend/llm_docs/mesh.md) |
| `.draft` | Sheet metal draft analysis | [draft.md](./backend/llm_docs/draft.md) |
| `.tolerance` | GD&T tolerance schema | [tolerance.md](./backend/llm_docs/tolerance.md) |
| `.fem` | Finite element mesh + boundary conditions | [fem.md](./backend/llm_docs/fem.md) |
| `.topo` | Topological optimization study | [topo.md](./backend/llm_docs/topo.md) |
| `.cam` | CNC toolpath + operation list | [cam.md](./backend/llm_docs/cam.md) |
| `.rf-study` | RF electromagnetic study | [rf.md](./backend/llm_docs/rf.md) |
| `.material` | Material definition with properties | [material.md](./backend/llm_docs/material.md) |
| `.equations` | Project-scoped parametric equations | [equations.md](./backend/llm_docs/equations.md) |
| `.canvas` | Freeform 2D annotation canvas | [canvas.md](./backend/llm_docs/canvas.md) |
| `.stair` | Staircase geometry + accessibility | [stairs.md](./backend/llm_docs/stairs.md) |
| `.railing` | Railing/guardrail system | [railings.md](./backend/llm_docs/railings.md) |
| `.curtain-wall` | Curtain wall panel system | [curtain_wall.md](./backend/llm_docs/curtain_wall.md) |
| `.duct` | HVAC duct routing | [mep.md](./backend/llm_docs/mep.md) |
| `.pipe` | Piping system routing | [mep.md](./backend/llm_docs/mep.md) |
| `.conduit` | Electrical conduit routing | [mep.md](./backend/llm_docs/mep.md) |
| `.step` | STEP B-rep import (read-only mirror) | [surfacing.md](./backend/llm_docs/surfacing.md) |
| `.step-ref` | External STEP file reference | [surfacing.md](./backend/llm_docs/surfacing.md) |

Also: `.assembly_lock`, `.script`, `.configurations` (tracked internally; no
dedicated LLM doc).

## Tool registry

`backend/tools/` contains **60+ modules** exposing **150+ LLM tools**. Every
tool is registered via the `@register` decorator:

```python
from .registry import register, ToolSpec

@register(ToolSpec(name="my_tool", description="...", input_schema={...}), write=False)
async def my_tool(ctx: ProjectCtx, ...) -> str:
    ...
```

`write=True` marks tools that mutate project state. The decorator appends a
`Tool(spec=..., write=..., run=fn)` to the global `Registry`. At startup,
`executor.py` builds `specs()` (the tool list sent to the LLM) and `execute()`
(dispatches a tool call by name).

The LLM consults `backend/llm_docs/` as a **doc-search corpus** before
touching non-`.jscad` files. The corpus covers every file kind schema, MEP
routing vocab, PCB layer stack, feature-tree semantics, and more.

## The AI loop

```
User chat → POST /api/projects/:pid/threads/:tid/messages
  1. Persist message; build LLM history
  2. Call LLM with tool registry (role-filtered: viewer = read-only)
  3. Persist assistant turn + any tool_calls
  4. No tool_calls? → done
  5. Execute every tool call inside the request handler
  6. Persist role=tool result rows; append to history
  7. Loop back to step 2; cap at 10 iterations
  8. Render affected files → push viewport update via SSE
```

Single HTTP request. A "make this 6 mm thick" can chain read → edit →
validate all visible as individual chat rows.

## Storage abstraction

`backend/storage` defines a `Storage` ABC; concrete backends:

- **local** — disk under `./.kerf-storage`. Auth-protected
  `/api/blobs/{key}` serves bytes.
- **s3** — AWS SDK v2; works with S3, R2, MinIO. `download` returns a 302 to
  a presigned URL.
- **filesystem** — projects mirror to disk under `[storage].filesystem_root`
  as folders, so users can edit with their own tools.
- **git** — git mirror per-project; Kerf commits on every file write,
  branches per workspace variant.

Selection is config-driven; the rest of the codebase only sees the interface.

## File revisions = undo

Every text edit appends a row to `file_revisions` with `source` of
`'user' | 'llm' | 'tool' | 'restore'`. The PATCH path, every write tool, and
restore actions all funnel through the same insert. `Cmd+Z` in the editor
calls the restore endpoint. Soft-deletes (`deleted_at` flag) keep revisions
readable so the History drawer can resurrect a deleted file.

`[limits].file_revisions_max` (default 200) trims the oldest rows on each write.

## Two coexisting kernels

**JSCAD** — code → mesh in a Web Worker. Cheap, scriptable, great for
parametric exploration.

**.feature** — JSON feature tree backed by OCCT in a WASM/pyworker. Real B-rep
features (fillets, chamfers, shell, draft, holes), edge identity for
selection-driven ops, lossless STEP export.

Both kernels coexist per-file. Cross-kernel ops (Assembly combining `.jscad`
and `.feature` bodies) work at the mesh level — same trade Rhino and FreeCAD
make. This is intentional: code-first is unbeatable when the LLM is in the
loop; B-rep is unbeatable when you need precision and edge ops a mesh can't.

## Migrations

`backend/db/migrations/` holds SQL migration scripts named `NNN_kind_*.sql`.
The runner (`backend/db/migrations/runner.py`) applies them in order. Each
adds a new value to the `files.kind` enumeration and/or alters the schema.
046 (`046_kind_render.sql`) is the most recent.

## Build tags as feature flags

Cloud features are enabled via `KERF_CLOUD=1` and Vite env vars. No runtime
feature-flag system — the flag is read at server startup.

## Single-binary deploy

`npm run build` runs `vite build` → `backend/static/dist/`. The Python server
starts with `uvicorn backend.main:app`; static files served via FastAPI
StaticFiles mount. `uvicorn backend.main:app` (or `./kerf --config ./kerf.toml`)
boots everything: API + SPA + agent loop on `:8080`.

## Where to dive deeper

- **API + data model** — this document, plus per-kind schemas under `backend/llm_docs/`.
- **LLM tool surface** — [llm-tools.md](./llm-tools.md).
- **Backend internals** — [backend/README.md](../backend/README.md).
- **Roadmap + philosophy** — [ROADMAP.md](../ROADMAP.md).
- **Cloud build & pricing** — [cloud/README.md](../cloud/README.md).

Next: [llm-tools.md](./llm-tools.md)
