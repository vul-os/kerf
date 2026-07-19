# How Kerf is built

A quick orientation for contributors, plugin authors, and self-hosters who want
to understand what's happening under the hood.

---

## The short version

Kerf is a **single binary** — one Python server process serves both the REST/RPC
API and the pre-built React SPA. One Postgres database. Pluggable storage
(local disk, S3/R2, filesystem mirror, or git). Pluggable LLM provider
(Anthropic, OpenAI, Moonshot, Gemini).

```
Browser (React + Three.js)  ←→  Python FastAPI server  ←→  Postgres
                                       ↕
                              Plugin packages (19 plugins)
                              Tool registry (~150 LLM tools)
                              Storage backend (local / S3 / git)
```

---

## One node type, not OSS vs Cloud

There is no "cloud edition" versus "local edition" — Kerf is 100% MIT and
every install (a laptop, a homelab box, or a Vulos-hosted instance like
`kerf.sh`) runs byte-identical software. A node's behavior is governed
entirely by config toggles (`publicly-reachable`, `relay-for-others`,
`pin-storage`, `offer-compute`), never by a license gate or a proprietary
package. See [node-architecture.md](./node-architecture.md) and
[oss-cloud-separation.md](./oss-cloud-separation.md) for the current model.

---

## Two kernels, one project

Kerf lets you mix two geometry backends in the same project:

### JSCAD (code → mesh)

`.jscad` files are JavaScript modules evaluated in a **Web Worker**. The result
is a triangulated mesh rendered by Three.js. JSCAD is great for LLM-driven
parametric work — the model is code, edits are text diffs, and re-eval is fast.

A 4-tier debounce throttles re-eval based on file size (250 ms for tiny files up
to ~3 s for large ones) to keep the viewport responsive.

### OCCT feature tree (B-rep)

`.feature` files hold a JSON feature tree evaluated by OCCT
(`occt-import-js` in the browser, `pythonOCC` on the server via `kerf-cad-core`).
You get real B-rep features — fillets, chamfers, shell, draft, holes — with edge
identity for selection-driven operations and lossless STEP export.

**Which should you use?** JSCAD when the LLM is driving and you want quick
iteration. `.feature` when you need manufacturing precision, GD&T, or STEP
interop.

Cross-kernel assembly (combining JSCAD and feature-tree bodies in one assembly)
works at the mesh level — the same trade Rhino and FreeCAD make.

---

## File kinds

Kerf supports **40+ file kinds**. Each kind has a dedicated schema doc in its
plugin's `llm_docs/<kind>.md`, consulted by the AI via `search_kerf_docs`.

| Kerf file kind | Purpose | Plugin |
|----------------|---------|--------|
| `.jscad` | Code-driven mesh (JSCAD scripting) | kerf-api |
| `.feature` | OCCT B-rep feature tree | kerf-cad-core |
| `.sketch` | 2D constraint geometry (planegcs) | kerf-cad-core |
| `.assembly` | BOM-driven product structure | kerf-api + kerf-mates |
| `.drawing` | Multi-sheet manufacturing drawings + GD&T | kerf-imports |
| `.part` | Library part with MPN, distributors, photos | kerf-api |
| `.circuit.tsx` | tscircuit electronics (JSX) | kerf-electronics |
| `.simulation` | FEA/simulation metadata | kerf-fem |
| `.bim` | Building information model | kerf-bim |
| `.render` | Blender Cycles render scene | kerf-render |
| `.fem` | Finite element mesh + BCs | kerf-fem |
| `.topo` | Topology optimisation study | kerf-topo |
| `.cam` | CNC toolpath + operation list | kerf-cam |
| `.step` / `.step-ref` | STEP B-rep import + pointer | kerf-cad-core |

---

## Plugins

Kerf is a meta-package that pulls a **persona bundle** of plugins:

```
api-only · mech · electronics · bim · full · compute-only
```

19 plugin packages live under `packages/kerf-<name>/`. Each plugin follows the
same layout:

```
packages/kerf-<name>/
├── pyproject.toml         # entry-point: kerf.plugins group
├── src/kerf_<name>/
│   ├── plugin.py          # register(app, ctx) → PluginManifest
│   ├── routes*.py         # FastAPI routers (service plugins)
│   ├── tools/             # LLM tools registered into ctx.tools
│   └── llm_docs/          # corpus markdown for the AI
└── tests/
```

Plugins register via Python entry points and are discovered at startup — no
static list. Add a plugin to a persona in `pyproject.toml` and it's live.

### Boot sequence

1. Load `kerf.toml`.
2. Build the `PluginContext` (asyncpg pool, storage, tool registry, config).
3. Discover plugins via `importlib.metadata.entry_points(group="kerf.plugins")`.
4. Call each plugin's `register(app, ctx)` in dependency order.
5. Aggregate `PluginManifest` objects → `/health/capabilities`.
6. Start registered workers via `ctx.workers.start_all()`.

### Runtime introspection

```sh
curl http://localhost:8080/health/capabilities
# → {"plugins":[…], "capabilities":["api.rest","cad.brep-mesh",…]}
```

The frontend reads this on load to decide which UI surfaces to render.

---

## The AI loop

```
User chat → POST /api/projects/:pid/threads/:tid/messages
  1. Persist message; build LLM history
  2. Call LLM with tool registry (role-filtered: viewer = read-only)
  3. Persist assistant turn + tool_calls
  4. No tool_calls? → done
  5. Execute every tool call
  6. Persist results; append to history
  7. Loop back to 2; cap at 10 iterations
  8. Re-render affected files → push viewport update via SSE
```

Single HTTP request. "Make this 6 mm thick" chains
read → edit → validate, all visible as individual chat rows.

---

## Storage

Three concrete backends, one interface (`StorageBackend` ABC in
`packages/kerf-core/src/kerf_core/storage/`):

| Kerf backend | Config | Best for |
|--------------|--------|----------|
| `local` | `storage.backend = "local"` | Local dev, single-machine self-host |
| `s3` | `storage.backend = "s3"` | Production; works with AWS S3, R2, MinIO |
| `filesystem` | `storage.backend = "filesystem"` | Edit files with your own tools on disk |
| `git` | (cloud) | Per-project git mirror; GitHub sync via `kerf-cloud` |

---

## Revision history

Every text edit writes a row to `file_revisions` with a `source` tag of
`user | llm | tool | restore`. Cmd+Z restores the previous revision.
Soft-delete keeps the revision log readable after a file is deleted.

`[limits].file_revisions_max` (default 200) prunes the oldest rows on each
write. See [file-revisions.md](./file-revisions.md) for the full model.

---

## Running a local server

See [getting-started.md](./getting-started.md) for a step-by-step walkthrough.
The one-liner for development:

```sh
npm run dev     # Vite SPA on :5173 + kerf-server on :8080, both with hot-reload
```

Production single-binary:

```sh
npm run build
kerf-server        # serves dist/ + API on :8080
```

---

## Future work

**Real-time multi-author sync (CRDT).** kerf does not ship a real-time
collaborative-editing engine today (see [concurrent-editing.md](./concurrent-editing.md)
for the optimistic-concurrency-control model kerf uses instead). A pure-Python
CRDT seed (`YMap`/`YArray`/`YDoc`/`PresenceChannel`, no network transport) once
lived at `packages/kerf-cloud/src/kerf_cloud/collab/` but was never wired into
any router and was pruned 2026-07-19 as dead code. The suite-wide decision is
that real-time CRDT sync — for kerf and for every other product in the suite —
will come from the shared substrate **Sync** spec
(`dmtap/substrate/SYNC.md`, capability ③: a signed, deterministic, multi-author
CRDT operation algebra with range-Merkle reconciliation) with proper language
bindings, rather than each product hand-rolling its own engine. When kerf adds
real-time collaborative editing, it should build on that spec instead of
reviving the pruned seed.

**Wake (push notifications for the Workshop).** See
[distributed-workshop.md](./distributed-workshop.md) and
[node-architecture.md](./node-architecture.md) for kerf-pub's optional Web
Push wake path (substrate capability ⑤, `dmtap/substrate/ROLES.md` §8) — a
content-free "new revision" ping that lets a follower skip re-crawl polling.
Frontend UI (browser `PushManager` subscription flow, a small "notify me"
toggle in the Workshop view) is a follow-up; the server-side subscription
registry and send path are implemented.

---

## Deep dives

- [capabilities.md](./capabilities.md) — capability tags + persona breakdown
- [llm-tools.md](./llm-tools.md) — full LLM tool reference
- [tool-registry.md](./tool-registry.md) — AI workflow and extending the tool system
- [render-pipeline.md](./render-pipeline.md) — Three.js + BVH + mesh caching
- [cloud-operator.md](./cloud-operator.md) — running a Vulos-hosted node like `kerf.sh`
- [plugins-development.md](./plugins-development.md) — writing a plugin
