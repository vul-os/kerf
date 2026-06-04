<div align="center">

<img src="public/favicon.svg" width="84" height="84" alt="Kerf">

# Kerf

**Chat-driven, multi-discipline CAD across 37 engineering domains — mechanical, BIM, civil, electronics, optics, composites, dental, jewelry, marine, aerospace, silicon, firmware, controls, and more — MIT open-core.**

JSCAD code · OpenCascade B-rep features · planegcs sketcher · tscircuit electronics · TechDraw drawings · assemblies · library + BOM · workshop sharing · workspace billing — with an LLM editing the source for you.

[![License: MIT](https://img.shields.io/badge/License-MIT-FFD633.svg?style=flat-square)](LICENSE)
[![Made in](https://img.shields.io/badge/Built%20in-Durban%20%F0%9F%87%BF%F0%9F%87%A6-1f2937?style=flat-square)](https://kerf.sh)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-FFD633.svg?style=flat-square)](#contributing)

[Website](https://kerf.sh) · [Docs](https://kerf.sh/docs) · [Roadmap](./ROADMAP.md) · [Contributing](#contributing)

</div>

---

## Screenshots

<!-- Drop the actual files into public/screenshots/ — the paths below resolve once images land. -->

<p align="center">
  <img src="public/screenshots/editor.png" alt="The Kerf editor: file tree, 3D viewport, chat panel" width="100%">
  <em>The editor — file tree, 3D viewport, and the LLM chat panel side by side.</em>
</p>

<p align="center">
  <img src="public/screenshots/sketcher-features.png" alt="Sketcher with constraints driving an OCCT feature timeline" width="100%">
  <em>2D parametric sketcher driving an OpenCascade B-rep feature timeline.</em>
</p>

---

## What it is

A single workspace for 37 engineering domains — mechanical, electronics / PCB / silicon, structural / FEA, thermal / fluid / HVAC, aerospace / marine / space, manufacturing / CAM, civil / geotechnical / hydraulics, dynamics / controls, electrical / PLC / firmware, tolerancing / QA, optics / acoustics, jewelry, BIM, cost / materials / LCA, injection mold, piping / P&ID, packaging / dieline, dental, composites, horology, and more — written entirely in code (JSCAD / `.feature` JSON / `.circuit.tsx` / `.sketch` / `.drawing`) so an LLM can read, diff, and edit it. Multi-domain projects via free-form tags. Browser-native. Local install or hosted at [kerf.sh](https://kerf.sh).

## Why

- **Code-first** — everything is text. Diffs, code review, branching, version control. The LLM doesn't have to "see" pixels — it edits source.
- **Two real kernels** — JSCAD for fast iteration; OpenCascade B-rep (`.feature` files) for fillets / shells / lossless STEP export. Pick per file.
- **Multi-domain** — mechanical assemblies and PCB schematics in the same project. Cross-reference a board outline from a mechanical Component. Run structural code checks, CAM toolpaths, and CFD in the same chat session.
- **Textbook-to-deep engines** — AISC 360-22 / ACI 318-19 / Eurocode EC2/3/5/8, IAPWS-IF97 steam, ISO 6336 gears, IBIS-AMI signal integrity, AC load-flow, analog PVT corner simulation, MITC4 plate FE, and more — all in the same open-source repo.
- **Open source** — MIT for the core. The hosted-tier plugins (`kerf-billing`, `kerf-cloud`) are proprietary but separable; everything else self-hosts MIT.
- **Local-first** — no telemetry, no phone-home. The hosted tier exists for convenience, not lock-in.

## What shipped recently (Waves 8–12)

These are the major capabilities that landed across the most recent development waves:

- **NURBS kernel depth** — analytic curve derivatives (Sturm inflection, evolute, arc-length), MatchSrf G3 continuity, surface-direct booleans, trim-by-curve, Stam limit-tangents + G1 at extraordinary SubD points, surface offset (Tiller-Hanson), iso-curve extraction, principal curvature heatmaps.
- **Optics panel** — `OpticsDesignPanel.jsx` wires 42 optics tools into 5 tabs: lens design, Seidel aberrations, diffraction MTF (mono + polychromatic + analytic-form), spot diagram + encircled energy, Zernike wavefront decomposition, piston/tip/tilt/defocus alignment analysis, pupil/vignetting tools, Schmidt corrector design.
- **Structural panel** — `StructuralPanel.jsx` surfaces 24 arch_* tools (ASCE 7-22 / ACI 318-19 / AISC 360-22 / TMS 402-22): beam/slab deflection, punching shear, wind loads, connections, base plates, retaining walls, stair stringers.
- **Manufacturing panel** — `ManufacturingPanel.jsx` wires 39 mold + electronics manufacturing-prep tools: moldflow checks, cooling pressure-drop, demold force, PCB trace current, differential-pair skew, FET SOA, inductor saturation, optocoupler CTR, EMI filter design, fuse I²t.
- **Composites depth** — AFP toolpath generation (5-axis G-code + APT export), CLT ABD matrix, drape simulation, fiber-orientation contour heatmap; full `LaminateStackup` UI.
- **Dental vertical** — anatomic multi-cusp crown, implant trajectory planning (Misch 2014 / EAO bone density D1–D4, nerve/sinus clearance), watertight surgical-guide B-rep + STL, occlusal contact analysis, full crown/implant/guide UI panels.
- **Electronics depth** — openEMS FDTD bridge for PCB microstrip/stripline, optocoupler CTR analysis (IEC 60747-5-5), inductor core saturation (temperature derating), GDT composite position tolerance (ASME Y14.5-2018 §10.5), IBIS-AMI signal integrity, AC PDN impedance sweep, arc-flash (IEEE 1584).
- **Controls / motion** — Adams MBD parity: multibody dynamics (rigid bodies + joints + RK4), 6 joint types, IK/FK, cam profiles, gear trains with undercutting checks, robot trajectory YAML export.
- **Civil / geotechnical** — LandXML 1.2 I/O, pressurised water-distribution (Hazen-Williams + Darcy-Weisbach), gravity sewer / storm drainage, Manning partial-flow, rational-method hydrographs + detention pond routing.
- **Compare coverage** — 876 yes / 143 partial across 1,265 feature rows in 46 competitor pages (86.0% saturation); 350+ LLM tools registered; 37 domains.

## Domains we cover

| Domain | Domain | Domain |
|---|---|---|
| Mechanical | Electronics / PCB | BIM / Architecture |
| Civil / Geotechnical | Aerospace | Marine / Naval |
| Silicon / IC | Firmware / Embedded | PLC / Industrial |
| Composites (CFRP/GFRP) | Optics / Acoustics | Dental / Medical |
| Jewelry / Horology | FEM + CFD | CAM / Manufacturing |
| Piping / P&ID | Packaging / Dieline | Mold / Injection |
| Motion / Dynamics | Textiles / Apparel | Materials + LCA |
| Tolerancing / QA | Structural codes | RF / Microwave |
| Solar PV | Woodworking | ... |

Full per-domain pages live at `/domains/<slug>` with a capability grid, file types, and LLM prompt examples.

## Install

### Hosted

[kerf.sh](https://kerf.sh) — sign up, you get 50 MB free, top up with credits when you need more LLM tokens or storage.

### Local (pip / pipx)

Kerf ships on PyPI. There is no Homebrew formula — pip/pipx is the one supported install path.

**Recommended — isolated install with pipx:**

```sh
pipx install kerf
```

**Alternative — inside a virtualenv:**

```sh
pip install kerf
```

**Self-host with the full server stack (Postgres required):**

```sh
pip install 'kerf[server]'

# Postgres must be running and DATABASE_URL must be set before starting.
# If you don't have Postgres yet:
#   docker run -d --name kerf-postgres -e POSTGRES_PASSWORD=kerf -p 5432:5432 postgres:16
#   export DATABASE_URL=postgres://postgres:kerf@localhost:5432/kerf

kerf serve      # fails fast with the above hint if DATABASE_URL is missing or unreachable
```

**Persona installs** (choose the feature set you need):

```sh
pip install 'kerf[mech]'          # mechanical CAD
pip install 'kerf[electronics]'   # EDA / PCB
pip install 'kerf[bim]'           # building information modelling
pip install 'kerf[full]'          # everything
```

### From source

```sh
git clone https://github.com/kerf-sh/kerf
cd kerf
pip install -e .[mech]   # or .[full] for everything; choose your persona
npm install
npm run dev              # vite :5173 + kerf-server :8080
```

You'll need Python 3.11+, Node 22+, and Postgres 14+. Run `npm run init` to generate `kerf.toml` from the example (add at least one LLM API key), then `npm run migrate` to initialise the database before starting the dev server.

## Build

```sh
npm run build              # full production build — compiles the SPA via Vite
npm run build:web          # just the Vite frontend (outputs to dist/)
npm run build:api          # install Python dependencies (pip install -e .[full])
npm run build:icons        # regenerate favicon set + OG image from public/favicon.svg
npm run build:docs         # rebuild public/docs-manifest.json from the markdown corpus
```

### Build flags

The Python backend uses environment variables and optional feature flags to gate the cloud bundle. Default is **OSS**.

```sh
# OSS build (default) — local install, no billing, no Workshop
pip install -e .[full] && kerf-server --reload

# Cloud build — adds Workshop sharing, billing, git, transactional email
CLOUD_ENABLED=true kerf-server --reload

# Or via npm
npm run build              # OSS
npm run build:cloud        # cloud
```

The same source tree runs both. Cloud-only plugins (`kerf-billing`, `kerf-cloud`) are only active when installed (e.g. `pip install -e .[full]`). The OSS install (`pip install -e .[mech]` etc.) cannot accidentally pull in cloud code.

### Configuration

`kerf.toml` (search order: `--config` flag → `KERF_CONFIG` env → `./kerf.toml` → `~/.config/kerf/config.toml` → `/etc/kerf/config.toml`). Starter file emitted on first run. Notable knobs:

| Key | Effect |
|---|---|
| `[server].local_mode = true` | Single-user mode; auto-login, skip register/login UI |
| `[server].port = 8080` | HTTP port |
| `[storage].backend = "filesystem"` | Mirror projects to `filesystem_root` for git workflows |
| `[storage].backend = "s3"` | S3 / R2 / MinIO; set credentials in `[storage.s3]` |
| `[llm.anthropic].api_key` / `[llm.openai].api_key` / etc. | Activate that LLM provider |
| `[limits].file_revisions_max` | Per-file undo history cap (default 200) |

Full schema: see [`kerf.example.toml`](./kerf.example.toml).

## Domains

Kerf is a single chat-driven tool across 37 engineering disciplines. Each
domain has a dedicated page (`/domains/<slug>`) with a hero illustration,
file types, capability grid, and an LLM-prompt example.

| Domain | File types | Highlights |
|---|---|---|
| **Mechanical** (`/domains/mechanical`) | `.feature` `.step` `.sketch` | Feature tree, OCCT B-rep, sheet metal, drawings, 3- and 5-axis CAM |
| **Electronics** (`/domains/electronics`) | `.tsx` `.ato` `.kicad_pcb` | tscircuit JSX + atopile + KiCad — schematic, PCB, 3D board viewer |
| **Architecture** (`/domains/architecture`) | `.bim` `.ifc` `.dxf` | Walls, slabs, doors, windows, schedules, sheets — IFC4 round-trip |
| **Jewelry** (`/domains/jewelry`) | `.feature` `.gem` `.step` | Gem cuts, ring/shank/seat/setting library, composites, Workshop sharing |
| **Automotive** (`/domains/automotive`) | `.feature` `.step` | Class-A surfacing, zebra-stripe continuity, NURBS Phase-4 trim |
| **Aerospace** (`/domains/aerospace`) | `.airfoil` `.orbit` `.bdf` `.step` | Airfoils, VLM + flutter, orbital mechanics, propulsion, ADCS, thermal |
| **Silicon / IC** (`/domains/silicon`) | `.vhd` `.v` `.gds` `.lef` `.lib` | RTL synthesis (Yosys), PnR (OpenROAD), DRC/LVS, GDS-II, Sky130 PDK |
| **Firmware** (`/domains/firmware`) | `.ino` `.c` `.cpp` `.fw.json` | Arduino + ESP32 + RP2040 + STM32 — build, upload, monitor, OTA |
| **PLC / Industrial** (`/domains/plc`) | `.plc` `.st` `.iec` | Ladder + ST + FBD + simulator + HMI tester, PLCopen XML |
| **Composites** (`/domains/composites`) | `.layup` `.cmh17` `.afp_plan` | CFRP/GFRP layup, ABD matrix, Tsai-Wu/Hill, AFP 5-axis toolpaths |
| **Dental** (`/domains/dental`) | `.feature` `.stl` | Crowns, aligners, implant planning, surgical guides, CBCT ingest |
| **Optics** (`/domains/optics`) | `.lens` `.zmx` | Lens design, Seidel + Zernike aberrations, MTF/PSF, Zemax import |
| **Horology** (`/domains/horology`) | `.feature` `.step` | Swiss-lever escapement, gear train, mainspring barrel |
| **Marine** (`/domains/marine`) | `.feature` `.iges` | Hull hydrostatics, GZ stability, strip-theory seakeeping RAOs, Holtrop-Mennen resistance |
| **Woodworking** (`/domains/woodworking`) | `.feature` `.dxf` | Joinery, cabinet designer, CNC router, cut list |
| **Textiles** (`/domains/textiles`) | `.pat` `.dxf` `.svg` | Pattern blocks, grading, marker making, drape sim |
| **Civil** (`/domains/civil`) | `.civ` `.ifc` `.dxf` `.landxml` | Horizontal/vertical alignment, corridor, earthwork, LandXML I/O, water-distribution / sewer / storm hydraulics |
| **Motion sim** (`/domains/motion`) | `.motion` `.urdf` | Multibody dynamics (RK4), 6 joint types, IK/FK |
| **FEM + CFD** (`/domains/femcfd`) | `.fem` `.cfd` `.bdf` | Linear/modal/nonlinear FEM, buckling, harmonic, random-vibration PSD, k-ω SST CFD, OpenFOAM bridge |
| **Mold** (`/domains/mold`) | `.feature` `.step` | Core/cavity split, parting surface, gate/runner design, cooling channels, moldflow |
| **Piping / P&ID** (`/domains/piping`) | `.pid` `.isogen` | P&ID with ISO 10628 symbols, 3D isometric model, ASME B31.3 stress compliance, spool drawings |
| **Packaging** (`/domains/packaging`) | `.dieline` `.dxf` | Parametric dielines, folding cartons, corrugated shippers, crease-rule DXF |

## What you can do today

| Capability | Status |
|---|---|
| JSCAD authoring + chat-driven edits | ✅ |
| OpenCascade `.feature` files (Pad / Pocket / Revolve / Fillet / Chamfer / Shell / Hole / Patterns / Push-Pull / Sweep1 / Sweep2 / Loft / NURBS surfacing + G3 blends + surface-direct booleans + trim-by-curve + matchSrf) | ✅ |
| FreeCAD-parity sketch shortcuts (boss-with-draft, cut-from-sketch, hole-pattern-from-sketch, symmetric loft, tangent-locked sweep) | ✅ |
| 2D parametric sketcher (planegcs constraints, live length/angle, BREP face/edge picker) | ✅ |
| TechDraw-flavored drawings (multi-sheet, dimensions, GD&T, hatching, leaders, balloons) | ✅ |
| Electronics via tscircuit (TSX → schematic + PCB + 3D board viewers) | ✅ |
| SPICE simulation (ngspice), RF s-parameters (scikit-rf), autoroute (FreeRouting) | ✅ |
| FEM (FEniCSx + CalculiX) — linear static + modal + buckling + harmonic + random-vibration PSD + fatigue (S-N / Coffin-Manson, rainflow) + geometric-nonlinear (Total-Lagrangian) + material-nonlinear (J2 plasticity, Riks arc-length) + thermal (steady + transient fin) + explicit dynamics (central-difference leapfrog) + solid tet/hex elements (H8 B-bar, Wave 11B4); *Honest outstanding: J2/Drucker-Prager/Hill plasticity in 3-D solids, thermal-structural coupling, composite layered shells (Tsai-Wu), contact mechanics (Hertz/penalty), fracture (J-integral/XFEM)* | ✅ |
| Topology optimization (FEniCSx SIMP + Gmsh mesh + NURBS STEP export) | ✅ |
| CAM (OpenCAMlib) — 2.5D + 3D parallel/waterline + lathe; G-code posts | ✅ |
| BIM (`.bim` text-DSL → IFC4 via IfcOpenShell; Revit-parity families/schedules/views/sheets/stairs/MEP/curtain wall) | ✅ |
| Library + BOM (per-Part visibility, distributors, photos, verified-publisher badge) | ✅ |
| Assemblies + 3D mates (coincident/concentric/distance/angle/tangent, BREP picker) | ✅ |
| Tolerance stack-up (worst-case / RSS / Monte Carlo + auto chain-walk through mates) | ✅ |
| Equations + global parameters (mathjs, injected into all runners) | ✅ |
| Workspaces (orgs) with members + roles + per-workspace billing | ✅ |
| Workshop sharing (free-tier social gallery, like + fork) | ✅ |
| Git (commits / branches / merge / GitHub sync) — S3-backed bare-repo storer | ✅ |
| STEP import/export, chunked resumable uploads, server-side pre-tessellation | ✅ |
| Imports: KiCad (Tier 1 + 2 libraries), OpenSCAD, Rhino3DM, FreeCAD (Tier 1: BRep-lift + Sketcher + PartDesign metadata + multi-Body) | ✅ |
| Scripting via `kerf-sdk` (PyPI, JSON-RPC to `/v1/rpc`) | ✅ |
| Sketch → JSCAD workflow (`extrude_sketch_to_jscad` + reactive re-eval) | ✅ |
| File revisions (Cmd+Z + diff-based gzip compression + SHA-256 dedup) | ✅ |
| Filesystem / S3 / R2 / MinIO storage | ✅ |
| Viewport perf — frustum culling + InstancedMesh batching for big assemblies | ✅ |
| NURBS Phase 4 — surface-direct booleans + trim-by-curve + matchSrf G3 continuity + analytic curve derivatives | ✅ |
| Optics panel — 42 tools: lens design, Seidel aberrations, diffraction MTF, Zernike decomposition, spot diagram | ✅ |
| Composites — AFP 5-axis toolpaths (G-code + APT), CLT ABD, drape sim, fiber orientation | ✅ |
| Dental — multi-cusp crown, implant trajectory planning (Misch / EAO), watertight surgical guide | ✅ |
| Manufacturing panel — 39 mold + electronics DFM tools unified in one UI | ✅ |
| Structural panel — 24 arch tools (ASCE 7-22 / ACI 318-19 / AISC 360-22 / TMS 402-22) | ✅ |
| PLC structured text (`.plc` / `.st` via IEC 61131-3 + PLCopen XML, Ladder + ST + FBD + simulator) | ✅ |
| Slicing — 3D-print G-code via Cura engine (`run_print_slice`) | ✅ |
| SubD modelling (Catmull-Clark, create / extrude-face / bevel-edge / crease) | ✅ |
| 📋 Grasshopper-style node graph | planned |

The full ROADMAP — shipped, in-flight, next, planned — is in [ROADMAP.md](./ROADMAP.md).

## Project structure

```
packages/
├── kerf-core/         — FastAPI app factory, plugin loader, DB, storage
├── kerf-auth/         — JWT + API tokens + sessions
├── kerf-api/          — core REST surface + ~50 LLM tools
├── kerf-chat/         — LLM agent loop + tool dispatch + llm_docs corpus
├── kerf-v1/           — `/v1/rpc` JSON-RPC for kerf-sdk
├── kerf-billing/      — billing (PROPRIETARY, cloud-only)
├── kerf-cloud/        — Workshop, git, GitHub sync, email, distributors (PROPRIETARY)
├── kerf-cad-core/     — pythonOCC: sketch, BREP, surfacing, .feature ops
├── kerf-tess/         — STEP → GLB tessellation worker
├── kerf-fem/          — FEM (FEniCSx primary, CalculiX second-solver)
├── kerf-cam/          — OpenCAMlib 2.5D + 3D + lathe + G-code posts
├── kerf-topo/         — SIMP topology optimization
├── kerf-mates/        — Assembly mate solvers + tolerance stack-up
├── kerf-bim/          — IFC compiler + Revit-parity families/schedules/views
├── kerf-electronics/  — ngspice, scikit-rf, FreeRouting, KiCad-parity
├── kerf-imports/      — KiCad, FreeCAD, OpenSCAD, Rhino3DM
├── kerf-dental/       — Crown, aligner, implant planning, surgical guide
├── kerf-composites/   — AFP toolpath, CLT, drape simulation
├── kerf-render/       — render route
├── kerf-workers/      — background-worker harness
└── kerf-sdk/          — Python SDK (PyPI: kerf-sdk) for scripting

Dockerfile             — monorepo image; KERF_PERSONA build-arg selects plugin set
docker-compose.yml     — local dev stack (app + postgres)
deployment/            — k8s + Cloud Run manifests

src/
├── components/        — React components + illustrations
├── routes/            — Landing, Editor, Projects, Library, Workshop, Docs
├── lib/               — runners (JSCAD / OCCT / sketch / equations), API client
├── store/             — Zustand stores
└── cloud/             — cloud-tier UI (PROPRIETARY)

docs/                  — public-facing docs (rendered at /docs)
public/                — static assets (icons, OG image, planegcs.wasm)
ROADMAP.md             — direction
docs/architecture.md   — API + data model
docs/capabilities.md   — plugin capability-tag reference
```

## Tech stack

- **Frontend**: Vite 8, React 19, React Router 7, Tailwind v4, Zustand, Three.js, `@jscad/modeling`, `@monaco-editor/react`
- **Sketcher**: planegcs (FreeCAD's solver, compiled to WASM)
- **B-rep kernel**: OpenCascade.js (~15 MB compressed wasm, lazy-chunked)
- **Electronics**: tscircuit (TSX → CircuitJSON), circuit-to-svg
- **Backend**: Python 3.11, FastAPI, asyncpg, SQLAlchemy, Alembic, PyJWT, `httpx`
- **DB**: Postgres 14+ (Supabase-compatible)
- **LLM**: multi-provider — Anthropic, OpenAI, Moonshot, Gemini (default `claude-opus-4-7`)

## Testing

```sh
# Backend — run from repo root so the root conftest loads
PYTHONHASHSEED=0 pytest packages/ -n auto        # full suite (~23,000+ tests)
pytest packages/kerf-api/tests/                  # one plugin
pytest packages/kerf-fem/tests/                  # FEM (skips dolfinx tests if not installed)

# Frontend (vitest)
npm test

# Lint
npm run lint
```

## Get involved

PRs welcome. Pick anything marked `📋 next` or `🔮 planned` in [ROADMAP.md](./ROADMAP.md). For larger work, open an issue first so we can align scope.

- **Issues + discussions**: [github.com/kerf-sh/kerf/issues](https://github.com/kerf-sh/kerf/issues) · [github.com/kerf-sh/kerf/discussions](https://github.com/kerf-sh/kerf/discussions)
- **Style**: ESLint + Prettier defaults. Match the surrounding code; we don't bikeshed.
- **Tests**: every PR that touches a plugin should add or extend a test in `packages/kerf-<plugin>/tests/`. Frontend changes: add a vitest if the logic isn't UI-only.
- **Commits**: imperative tense, ~70 chars (`fix sketcher line-tool double-commit`).
- **The LLM edits source files directly.** If you add a new file kind or feature, also add a `packages/kerf-chat/llm_docs/<topic>.md` so the model knows about it. The doc-search tool indexes that directory automatically.

See [docs/architecture.md](./docs/architecture.md) for the API + data model spec — the source of truth for cross-cutting changes.

## License

Dual-licensed:
- **MIT** for the core — see [LICENSE](./LICENSE). Covers everything outside `packages/kerf-billing/`, `packages/kerf-cloud/`, and `src/cloud/`.
- **Proprietary** for the hosted-tier bundle — see [LICENSE-CLOUD](./LICENSE-CLOUD).

Built in Durban by a small team. Engineered for engineers everywhere.

## Links

- [Docs](https://kerf.sh/docs) — getting started, concepts, sketching, assemblies, drawings, electronics
- [ROADMAP.md](./ROADMAP.md) — shipped · in-flight · next · planned
- [docs/architecture.md](./docs/architecture.md) — full API + data model
- [docs/capabilities.md](./docs/capabilities.md) — plugin capability-tag taxonomy
- [docs/cloud-operator.md](./docs/cloud-operator.md) — hosted-tier build/deploy notes
- [Issues](https://github.com/kerf-sh/kerf/issues) · [Discussions](https://github.com/kerf-sh/kerf/discussions)
