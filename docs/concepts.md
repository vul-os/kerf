# Concepts

Kerf is a multi-domain CAD kernel where the **LLM is the primary author**. Every file is JSON,
every UI action is a tool call, and one project spans mechanical, electronics, architecture,
drafting, simulation, and scripting — with no separate apps or workbenches to switch between.

## The five nouns

```
Project
└── File           (.jscad, .feature, .sketch, .assembly, .bim, .circuit.tsx, ...)
    └── Object     (one entry in a file's export array)
                   └── Component  (an Assembly's instance of an Object at a transform)
```

Everything else — chat threads, revisions, members, share links — hangs off the Project.
Files cannot import across project boundaries; all geometry references stay within a project.

## 1. File kinds are first-class

Kerf supports **40+ file kinds**. Every domain is a JSON file kind with a schema doc in
`backend/llm_docs/<kind>.md`. The LLM reads the relevant schema doc before authoring or
editing that kind — no guessing, no hallucinated field names.

Key kinds:

| Kind | Extension | What it stores |
|------|-----------|----------------|
| `jscad` | `.jscad` | Code-driven mesh via `@jscad/modeling` in a Web Worker |
| `feature` | `.feature` | OCCT B-rep feature tree (pad/pocket/fillet/shell/draft…) |
| `sketch` | `.sketch` | 2D constraint geometry solved by planegcs |
| `assembly` | `.assembly` | Array of Components referencing Objects from other files |
| `drawing` | `.drawing` | Multi-sheet 2D manufacturing drawings with GD&T |
| `part` | `.part` | Library part with MPN, distributors, photos |
| `circuit` | `.circuit.tsx` | tscircuit electronics (JSX) |
| `bim` | `.bim` | Revit-style building model with hosted elements |
| `simulation` | `.simulation` | FEM/SPICE/RF/topology/CAM study metadata |
| `fem` | `.fem` | Finite element mesh + boundary conditions |
| `graph` | `.graph` | Grasshopper-style node-based DAG pipeline |
| `equations` | `.equations` | Project-scoped scalar parameters |
| `cam` | `.cam` | CNC toolpath + operation list |
| `step` | `.step` | Binary STEP B-rep import (read-only mirror) |

Binary files (STEP) keep a pointer in Postgres; bytes live in the configured Storage
backend (local disk, S3/R2/MinIO, or filesystem mirror). Every text file edit
appends a row to `file_revisions`, capped at 200 per file.

See [architecture.md](./architecture.md) for the full table and
[backend/llm_docs/index.md](../backend/llm_docs/index.md) for all schema docs.

## 2. LLM as primary author

The AI chat edits JSON via tool calls. Every UI action is also a tool call — the UI is a
**thin emitter** that translates user gestures into the same tool call interface the LLM uses.
One `make this 6 mm thicker` chains read → edit → validate as individual chat rows visible in
the thread.

`backend/tools/` exposes **60+ modules / 150+ tools**. Every tool is registered via
`@register(ToolSpec(...), write=...)` and the LLM sees a role-filtered list:
`viewer` role gets read-only tools only. `write=True` marks tools that mutate project state.

Before touching any non-`.jscad` file, the LLM queries `search_kerf_docs` → reads the
matching `backend/llm_docs/<topic>.md` → makes an informed tool call. This doc-search loop
is the reason the LLM can productively edit `.feature`, `.bim`, `.circuit`, and all the
other domain-specific kinds without hallucinating schemas.

See [llm-tools.md](./llm-tools.md) for the full tool surface.

## 3. Two kernels in one project

**JSCAD** — evaluates `.jscad` code in a Web Worker. Triangulated mesh output. Cheap,
scriptable, great for parametric exploration. The LLM can freely generate and mutate it.
IndexedDB caches meshes keyed by JSCAD content hash so repeated evals are instant.

**.feature** — JSON feature tree evaluated by OCCT (WASM in pyworker). Real B-rep:
fillets, chamfers, shell, draft, holes, ribs, helical threads. Edge identity is preserved
for selection-driven ops. Lossless STEP export. No code — just a declarative list of
ordered operations.

Both kernels coexist per-file. Assemblies compose both at the mesh level — same trade
Rhino and FreeCAD make. This is intentional: code-first is unbeatable when the LLM is in
the loop; B-rep is unbeatable when you need precision and edge ops a mesh can't give you.

See [backend/llm_docs/feature.md](../backend/llm_docs/feature.md) and
[backend/llm_docs/jscad.md](../backend/llm_docs/jscad.md).

## 4. File revisions are diff-compressed

Every text edit appends a row to `file_revisions` with `source` of `'user' | 'llm' | 'tool' | 'restore'`.
The backend stores a **content-hashed delta chain** — revisions share content-addressed blobs.
This achieves ~82x size reduction compared to storing full copies.

Every save is a checkpoint; `Cmd+Z` (Editor → Restore) calls the restore endpoint which
replays the revision chain backwards. Soft-deletes keep history readable so the History
drawer can resurrect a deleted file. The `[limits].file_revisions_max` (default 200) trims
the oldest rows on each write.

See [backend/llm_docs/sheet_revisions.md](../backend/llm_docs/sheet_revisions.md).

## 5. Library Parts and Assemblies share the same nouns

- **Part** = an entire file (`.jscad`, `.feature`, `.step`…). It exports an array of Objects.
  Think OnShape "part studio" — one source file produces a family of related solids,
  each independently selectable in the viewport or in an Assembly.
- **Object** = one entry in that array: `{ id, geom }` where `geom` is the geometry handle
  used everywhere (clicked in the viewport, dropped as a chip in chat, referenced from
  assemblies, imported by other files).
- **Component** = an Assembly's instance of an Object at a 4×4 transform.

```ts
// Assembly Component
{ id: 'left-bracket', file_id: '...', object_id: 'wall', transform: [...16 nums] }
```

The same Object can be placed multiple times (different `id`, different transform) —
that's how repeated parts (screws, clips, grommets) work. A `.part` file adds
MPN/distributor data on top of this structure for library management.

See [backend/llm_docs/part.md](../backend/llm_docs/part.md) and
[backend/llm_docs/assembly.md](../backend/llm_docs/assembly.md).

## 6. Doc-search loop

Before touching any file kind, the LLM queries `search_kerf_docs` → reads matching
`backend/llm_docs/<topic>.md` → makes an informed tool call. The corpus covers:

- Every file kind schema (40+ docs under `backend/llm_docs/`)
- MEP routing vocabulary ([mep.md](../backend/llm_docs/mep.md), [routing.md](../backend/llm_docs/routing.md), [duct.md](../backend/llm_docs/mep.md))
- PCB layer stack and DRC rules ([pcb_layers.md](../backend/llm_docs/pcb_layers.md), [pcb_drc.md](../backend/llm_docs/pcb_drc.md))
- Feature-tree semantics and multi-transform patterns ([feature.md](../backend/llm_docs/feature.md), [feature_multi_transform.md](../backend/llm_docs/feature_multi_transform.md))
- Simulation configs and solvers ([fem.md](../backend/llm_docs/fem.md), [rf.md](../backend/llm_docs/rf.md), [topo.md](../backend/llm_docs/topo.md), [cam.md](../backend/llm_docs/cam.md))
- BIM categories and hosted relationships ([bim.md](../backend/llm_docs/bim.md), [bim_categories.md](../backend/llm_docs/bim_categories.md))

The loop: **user chat → LLM queries docs → reads schema → tool call → execute → render → SSE push to viewport**.

## 7. OSS vs Cloud — same codebase

The `cloud_enabled` feature flag gates cloud-only additions at runtime. Same codebase,
same binary — flip a flag to go from self-hosted OSS to Kerf Cloud. The flag is read at
server startup via `KERF_CLOUD=1` / `cloud_enabled=true` in `.env`.

| Feature | Cloud-only |
|---------|------------|
| Paystack billing / prepaid credit (USD→ZAR daily FX, ZAR settlement) | ✅ |
| Email (Resend/SES/SMTP via `backend/cloud/email/mailer.py`) | ✅ |
| S3 Git Storer — stateless bare-repo deploys via pygit2 | ✅ |
| Distributor live pricing sweep (DigiKey/Mouser/LCSC, 6h sync) | ✅ |
| GitHub OAuth (AES-GCM encrypted tokens in `cloud_github_tokens`) | ✅ |
| Workshop sharing / publishing / forking / library submissions | ✅ |
| STEP pre-tessellation (server-side triangulation via `TESS_WORKERS`) | ✅ |
| Everything else | OSS |

`local_mode` is forced off when `cloud_enabled=true`. Pluggable storage (local / S3/R2/MinIO /
filesystem mirror / git mirror per-project). The rest of the codebase only sees the `Storage` ABC.

See [cloud.md](./cloud.md).

## 8. Parametric stack — three layers

Kerf has three distinct parametric layers, each with a different scope:

| Layer | File | What it does |
|-------|------|--------------|
| Scalar params | `.equations` | Project-wide numeric variables; evaluated via mathjs; feed into features and graphs |
| Feature placeholders | `.feature` | `${name}` placeholders resolve to equation values at eval time |
| Node DAG | `.graph` | Grasshopper-style pipeline; nodes drive feature ops via `@nX.out` references |

`.equations` and `.feature` compose: equations feed feature placeholders. `.graph` is the
highest-level layer — it can invoke feature ops as nodes.

```
.equations  →  .feature  →  .graph
     ↑               ↑
     └── configs override equations scope per-variant
```

Configurations (M3/M4/M5, long/short, engraved/blank) produce multiple flavors from a
single source file by merging config params *over* the equations scope at eval time.

See [parametric.md](./parametric.md), [backend/llm_docs/equations.md](../backend/llm_docs/equations.md),
[backend/llm_docs/feature.md](../backend/llm_docs/feature.md), and
[backend/llm_docs/graph.md](../backend/llm_docs/graph.md).

## 9. Categories + hosted refs in .bim

The `.bim` kind implements a **Revit-style data model** for architecture:

- **Categories** (walls, doors, windows, floors, ceilings, stairs, railings, curtain walls,
  MEP ducts/pipes/conduits) own **Element Types**
- **Elements** are instances of types, placed at a location with a level and a transform
- **Hosted elements** (doors in walls, windows in walls, fixtures on walls, electrical
  fixtures on ceilings) reference their host via `host_id`
- **Spatial hierarchy**: Site → Building → Level → Zone

```
Category: Walls
  └── Element Type: "Exterior Wall 200mm"
        └── Element: Wall #1 (host_id: null, level: Level 1)
              └── Element: Door #1 (host_id: wall-1)
                    └── Element: Door Hardware #1 (host_id: door-1)
```

Geometry is either `.jscad` mesh or `.feature` B-rep. BIM elements point to the geometry
file via `geometry_file_id` and `object_id`. MEP elements additionally carry routing
connectivity (duct/pipe segments connect at junctions).

See [backend/llm_docs/bim.md](../backend/llm_docs/bim.md) and
[backend/llm_docs/bim_categories.md](../backend/llm_docs/bim_categories.md).

## 10. Domain-specific simulations — server-side via pyworker

Heavy CPU/GPU compute runs in a `pyworker` sidecar (async Python worker over HTTP or Redis
queue), not the request thread. The LLM triggers runs and reads results via tool calls.

| Domain | Kinds | What it does |
|--------|-------|--------------|
| Structural FEM | `.fem`, `.simulation` | Linear static, modal, thermal — mesh + boundary conditions → stress/displacement results |
| SPICE circuit | `.circuit.tsx` | Circuit simulation via ngspice; AC/DC/transient analysis |
| RF / electromagnetic | `.rf-study` | S-parameter analysis, antenna design, EM simulation |
| Topology optimization | `.topo` | Density-based topology study → optimized geometry |
| CAM | `.cam` | CNC toolpath generation, operation list, feed/speed calculation |
| Sheet metal | `.draft` | Flat-pattern, bend deduction, K-factor analysis, springback |

All results are JSON blobs stored in Postgres + object storage. The LLM can query
simulation status, retrieve results, and trigger new runs. STEP files ≥5 MB are stored
as `kind='step-ref'` with a SHA256 content pointer to avoid duplicating large binaries.

See [backend/llm_docs/simulation.md](../backend/llm_docs/simulation.md),
[backend/llm_docs/fem.md](../backend/llm_docs/fem.md), [backend/llm_docs/rf.md](../backend/llm_docs/rf.md),
[backend/llm_docs/cam.md](../backend/llm_docs/cam.md), and [backend/llm_docs/topo.md](../backend/llm_docs/topo.md).

## Quick reference — schema docs by domain

| Domain | Start here |
|--------|------------|
| Mechanical / JSCAD | [jscad.md](../backend/llm_docs/jscad.md) · [feature.md](../backend/llm_docs/feature.md) |
| Sketching | [sketch.md](../backend/llm_docs/sketch.md) |
| Assemblies | [assembly.md](../backend/llm_docs/assembly.md) · [mates.md](../backend/llm_docs/mates.md) |
| Drawings | [drawing.md](../backend/llm_docs/drawing.md) · [sheet.md](../backend/llm_docs/sheet.md) |
| Architecture / BIM | [bim.md](../backend/llm_docs/bim.md) · [bim_categories.md](../backend/llm_docs/bim_categories.md) |
| Electronics | [circuit.md](../backend/llm_docs/circuit.md) · [pcb_layers.md](../backend/llm_docs/pcb_layers.md) |
| Parametric | [equations.md](../backend/llm_docs/equations.md) · [graph.md](../backend/llm_docs/graph.md) |
| Simulation | [simulation.md](../backend/llm_docs/simulation.md) · [fem.md](../backend/llm_docs/fem.md) |
| CAM | [cam.md](../backend/llm_docs/cam.md) |
| Surfacing / STEP | [surfacing.md](../backend/llm_docs/surfacing.md) |

---

Next: [sketching.md](./sketching.md) · [assemblies.md](./assemblies.md) · [parametric.md](./parametric.md) · [electronics.md](./electronics.md) · [architecture.md](./architecture.md)
