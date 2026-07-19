# Changelog

All notable changes to Kerf are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The authoritative source for what's shipped vs. in-flight is
[ROADMAP.md](./ROADMAP.md). This file summarizes each tagged release.

---

## [Unreleased]

No unreleased changes.

---

## [0.1.0] - 2026-07-18

Initial public release. A complete, self-hosted CAD/EDA/BIM platform across
37 engineering domains, a distributed Workshop for sharing parts without a
central server, local git-backed version control, and no billing surface of
any kind — Kerf is 100% MIT and free to self-host, permanently.

### Added

- **Mechanical CAD** — 2D parametric sketcher (`planegcs` constraint solver,
  compiled to WASM) with trim/extend/fillet/mirror/pattern and multi-loop
  holes; feature-tree modeling (Pad, Pocket, Revolve, Fillet, Chamfer, Shell,
  Hole, Sweep1/2, Loft, Push-Pull, Linear/Polar/Mirror patterns) on
  OpenCascade `.feature` files; NURBS surfacing (`sweep1`, `sweep2`,
  `network_srf`, `blend_srf`) with G0–G2 continuity; direct-manipulation face
  and edge gumballs; persistent face/edge naming (sketch-anchored +
  topological-hash fallback) that survives upstream parameter edits;
  FreeCAD-parity sketch shortcuts; imports for KiCad, OpenSCAD, Rhino3DM, and
  FreeCAD (`.FCStd`).
- **A second, pure-Python geometry kernel** —
  `packages/kerf-cad-core/src/kerf_cad_core/geom/` implements B-rep topology
  (`Body → Solid → Shell → Face → Loop → Coedge → Edge → Vertex`, Euler
  operators, `validate_body`), tolerant solid booleans (cut/fuse/common) via
  face-imprint SSI, a parametric history DAG with `feature_id::role::
  fingerprint` selectors, G1/G2 fillets and chamfers, exact-distance offsets,
  Coons patches, and Piegl-method closest-point/point-inversion — all
  independent of OCCT, with 620 hermetic analytic-oracle-asserted tests.
- **CAE** — FEM (FEniCSx primary, CalculiX second solver; linear-static,
  modal, thermal, fatigue, explicit dynamics) with deformed-shape 3D overlay;
  CFD foundation (2D potential flow + lid-driven-cavity Navier-Stokes,
  citable Ghia/Roark/Blevins/Incropera reference values); topology
  optimization (FEniCSx SIMP + Gmsh + NURBS STEP export); tolerance stack-up
  (worst-case / RSS / Monte Carlo) walking assembly mate chains; 5-axis CAM
  (constant-tilt + 3+2 indexed).
- **Electronics (EDA)** — tscircuit-powered schematic, PCB, and 3D board
  viewers; server-side SPICE simulation via ngspice; RF analysis (Smith
  chart, S-parameters, VSWR) via scikit-rf; FreeRouting autoroute; WireViz
  wiring/harness diagrams.
- **Architecture (BIM)** — `.bim` text-DSL compiling to IFC4 via
  IfcOpenShell; Revit-parity authoring (families, schedules, views, sheets,
  phasing, view filters, stairs, railings, MEP routing, curtain walls); a
  web-ifc 3D viewer.
- **Distributed Workshop** — a federated protocol over **DMTAP-PUB**
  (`github.com/vul-os/dmtap` §22/§23): signed, content-addressed
  publish/follow/pin/fetch, no accounts, no central server, availability
  states (on-node / available / stale / unreachable). Any node — a homelab
  box or an always-on host — runs identical software; "the Workshop" is just
  feeds you choose to follow, not a service you register with.
- **Library + BOM** — curated parts with live distributor pricing (DigiKey /
  Mouser / LCSC), per-Component BOM export, multi-image galleries, and
  automatic thumbnail capture across every file kind.
- **Versioning + sync** — file revisions (fine-grained undo, diff-based
  storage, SHA-256 dedup) alongside a separate, deliberate cloud-git layer
  (`pygit2` backend) with commits, branches, merges, and GitHub sync, both
  stored on your own node; an S3-backed bare-repo storer for stateless
  deploys.
- **Scripting** — the `kerf-sdk` Python SDK on PyPI: JSON-RPC over `/v1/rpc`,
  API-token auth, namespaced wrappers for files / equations / configurations
  / revisions / docs, driven from your own machine.
- **Performance** — frustum culling + `InstancedMesh` batching in Three.js
  for assemblies with hundreds of identical components; server-side STEP
  pre-tessellation to GLB on upload, idempotent and content-hashed.
- **Plugin monorepo** — 37-domain platform split into ~57 packages under
  `packages/kerf-*/`, discovered via Python entry points, installable as one
  of six personas (`api-only` / `mech` / `electronics` / `bim` / `full` /
  `compute-only`).
- **Release pipeline** — tagged GitHub Releases (`.github/workflows/
  release.yml`) publishing installable `kerf-vX.Y.Z-{macos-arm64,macos-x64,
  linux-x64,src}.tar.gz` bundles + `SHA256SUMS`, a `curl -fsSL https://
  kerf.sh/install.sh | sh` one-liner, and persona Docker images on GHCR; see
  [docs/releasing.md](./docs/releasing.md).
- **Docs** — a public `/roadmap` page; per-cloud deployment guides
  (`deployment/fly.md`, `gcp.md`, `aws.md`, `azure.md`, `digitalocean.md`);
  `docs/node-architecture.md` and `docs/distributed-workshop.md` documenting
  the Workshop protocol; a redesigned docs viewer with grouped taxonomy,
  breadcrumbs, and TOC; ~75 per-package `llm_docs/` pages; a "Part of VulOS"
  standard README, docs, and `landing/index.html`, matching the sibling
  `wede`/`ofisi` product repos.

### Changed

- **No billing, ever** — an earlier plan to charge for hosted tiers (Free /
  Studio / Pro, at-cost LLM pricing via Paystack) was withdrawn before this
  release shipped. Kerf carries no accounts, no wallet, no metering, and no
  paid tier of any kind — self-host on your own hardware is the only
  distribution model. Optional VulOS services (Vulos Relay for public
  exposure, backup buckets) are separate products, not Kerf billing.
- **Hosted-infrastructure churn resolved** — a 2026-05-24 migration from
  Fly.io to Koyeb (chasing GPU render capacity) was withdrawn on 2026-06-01
  before DNS cutover; the confirmed reference stack is Fly.io (compute) +
  Neon Postgres + Cloudflare R2/Tigris (storage) + Resend (email), documented
  in `deployment/` and `docs/architecture/stack.md`.
- **Renderer hero / PBR upgrade** — 2048×2048 4× supersampled captures with
  ACES tonemapping and a PMREM-prefiltered HDRI environment, shared by
  Workshop covers, share-cards, and the primary 3D viewport.
- **Compare hub redesign** — per-category feature matrices (Mechanical /
  Electronic / BIM / Jewelry & NURBS / DCC) across 14 head-to-head comparison
  routes.

### Fixed

- **FCC Part 15 Class B EMC reference-distance** — wizard limits were
  ~10.46 dB too low against the published Class B mask; corrected at the
  reference-distance derivation.
- **Test collection** — an empty `tests/__init__.py` in the billing/pricing/
  plc packages was silently blocking whole-suite collection; removed.
- **Python 3.13 compatibility** — restored pre-3.10 `asyncio.get_event_loop()`
  semantics in the test process so the ship-gate suite runs on 3.13.
- **kerf-electronics test isolation** — ~202 order-dependent failures caused
  by cross-test pollution, repaired; the package suite is green whether run
  alone or as part of the full run.

### Known limitations

- **No compiled single-binary release yet.** Release tarballs bundle Python
  source plus a venv-based installer (see `docs/releasing.md`); a real
  single-binary build is a TODO for a future release.
- **5-axis CAM** ships constant-tilt + 3+2 indexed toolpaths; full G-code
  emission and a tool database are a v0.2 target.
- **NURBS Phase 4** ships the C1 binding probe, worker, and Python tool for
  surface-direct booleans; trim-by-curve, `matchSrf`, and G3 continuity land
  incrementally.
- **Azure Blob Storage** isn't S3-compatible — Azure self-hosters need a
  MinIO facade or cross-cloud S3 until a native adapter lands.
- **ASTM E1049 rainflow counting** has a known bug in `fatigue_fem.
  _rainflow` (one FEM reference-value test is skipped rather than xfail'd).

[Unreleased]: https://github.com/kerf-sh/kerf/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kerf-sh/kerf/releases/tag/v0.1.0
