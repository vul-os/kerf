# Getting started

Kerf is a browser-based CAD platform where an AI agent loop sits between your intent and your files. Describe what you want in plain English — "add a fillet here", "route this signal to pin 3", "optimize this topology" — and the LLM edits the underlying JSON or code directly, re-rendering in the viewport within milliseconds. Every edit is versioned; every file is plain JSON or script you can read, fork, and version-control.

## Quick start

```sh
git clone https://github.com/exolution/kerf
cd kerf
npm install
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --port 8080
# back in kerf root:
npm run dev
```

Open http://localhost:5173. On first run Kerf writes `kerf.toml` via `npm run init`; set `auth.optional = true` and your LLM API key (`[llm.anthropic]` or `[llm.openai]`). Full schema is in `kerf.example.toml`.

## What you can do

| File kind | What it is | LLM docs |
|-----------|------------|----------|
| `.jscad` | Parametric 3D model — JSCAD `[{id, geom}]` array, debounced re-render at ~250 ms | `/docs/llm/jscad.md` |
| `.feature` | OCCT B-rep feature tree — pad/pocket/revolve/fillet/chamfer/shell/hole | `/docs/llm/feature.md` |
| `.sketch` | 2D constraint sketch — planegcs geometric constraints + dimensions | `/docs/llm/sketch.md` |
| `.assembly` | Assembly composition — components placed at transforms, cycle rules | `/docs/llm/assembly.md` |
| `.drawing` | 2D technical drawing — multi-sheet, GD&T, centerlines, breaks | `/docs/llm/drawing.md` |
| `.part` | Library part metadata — MPN, distributors, photos, visibility | `/docs/llm/part.md` |
| `.circuit.tsx` | tscircuit PCB — JSX board/schematic, ERC, autoroute | `/docs/llm/circuit.md` |
| `.simulation` | SPICE netlist — op-amp, transient, AC sweep, noise analysis | `/docs/llm/simulation.md` |
| `.bim` | BIM architectural — walls/doors/windows/roofs as text DSL | `/docs/llm/bim.md` |
| `.family` | Parametric family — window/door/family definitions with types | `/docs/llm/family.md` |
| `.schedule` | Live BOM — rolling query across assemblies, totals by MPN | `/docs/llm/schedule.md` |
| `.view` | Derived viewport — saved camera, layers, section cuts | `/docs/llm/view.md` |
| `.sheet` | Print sheet — page size, title block, arranged views | `/docs/llm/sheet.md` |
| `.render` | Render config — lighting, environment, output resolution | `/docs/llm/render.md` |
| `.graph` | Parametric graph — Grasshopper-equivalent node network | `/docs/llm/graph.md` |
| `.subd` | Subdivision surface — smooth subdivision from mesh cage | `/docs/llm/subd.md` |
| `.mesh` | Mesh ops — import 3DM, repair, convert to solid | `/docs/llm/mesh.md` |
| `.draft` | Draft entity — slope, distance, reference lines in drawing | `/docs/llm/draft.md` |
| `.tolerance` | Tolerance stack-up — worst-case and RSS analysis | `/docs/llm/tolerance.md` |
| `.fem` | Mechanical FEA — mesh, boundary conditions, solve | `/docs/llm/fem.md` |
| `.topo` | Topology optimization — density field under constraints | `/docs/llm/topo.md` |
| `.cam` | CAM toolpath — facing, pocket, profile, drilling cycles | `/docs/llm/cam.md` |
| `.rf-study` | RF s-parameter study — port calibration, S/Y/Z parameters | `/docs/llm/rf.md` |
| `.material` | Material definition — 55 seeded (steel, aluminium, FR4, ...) | `/docs/llm/material.md` |
| `.equations` | Global equations — cross-file parameter references | `/docs/llm/equations.md` |

## AI loop

The chat input at the bottom of the viewport is the LLM agent. When you send a message it:

1. Calls `list_files` to see your project tree
2. Calls `search_kerf_docs` to find relevant docs in the 68-page embedded corpus (`backend/llm_docs/`)
3. Reads the matching `/docs/llm/<topic>.md` page via `read_file`
4. Calls `edit_file` / `write_file` / domain tools to mutate files
5. The viewport re-renders within ~250 ms

**Core tools (always available):** `list_files`, `read_file`, `write_file`, `edit_file`, `create_file`, `delete_file`, `search_code`, `import_step`, `duplicate_object`, `delete_object`, `validate_jscad`, `generate_bom`, `create_sketch`, `create_feature`, `create_part`, `create_circuit`, `search_kerf_docs`, `list_revisions`, `restore_revision`.

**Domain tools (50+):** Assembly placement/mates, PCB autoroute/shove/ERC/length-tuning/pour/DRC, feature draft/helix/mirror/multi-transform/rib, mesh repair/convert, render config, BIM curtain-wall/family/railings/stairs/MEP, graph nodes, SPICE simulation, RF s-parameters, CAM toolpaths, FEA solve, tolerance analysis, topology optimization, curve ops, sketch constraints, sheet layout, view config, material lookup, equation evaluation, configurations, pad overrides, inspection, and more.

## Next

- Sketching 2D with constraints → [sketching.md](./sketching.md)
- Electronics & PCB design → [electronics.md](./electronics.md)
- System internals → [architecture.md](./architecture.md)
- Multi-part assemblies → [assemblies.md](./assemblies.md)
- Dimensioned drawings → [drawings.md](./drawings.md)
