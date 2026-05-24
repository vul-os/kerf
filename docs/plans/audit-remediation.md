# Audit Remediation Roadmap

Origin: 2026-05-24 full-codebase audit (13 parallel agents) covering frontend
wiring, stubs, redundancy, and security. This roadmap breaks the findings into
discrete, dispatchable tasks executed by worktree-isolated Sonnet agents and
integrated by commit SHA.

Legend: `[ ]` pending · `[~]` in progress · `[x]` done · `[!]` flagged / needs decision

Operating rules for the loop:
- One agent owns a disjoint file-set per wave (no two concurrent agents edit the same file).
- Each agent VERIFIES the finding against current code before fixing; reports false positives instead of forcing a change.
- Each agent runs the relevant tests and commits in its worktree; parent integrates by SHA.
- Never `DROP SCHEMA` / reset the shared Postgres DB while another agent runs.
- No backwards-compat shims; DBs are reset, baseline migrations are consolidated.

---

## Phase 1 — Security (highest priority)

- [ ] **P1-API** — kerf-api `routes.py`: (a) API-token revoke IDOR — add workspace/owner filter to `revoke_api_token`; (b) `delete_share_link` — verify `lid.project_id == pid`; (c) `accept_share` — fix `project_id` passed where `workspace_id` expected; (d) remove stale `p.owner_id` references in admin publisher SQL; (e) billing fail-closed — replace `except Exception: bucket=None` zero-cost fallthrough with hard 503; (f) `import_step` SSRF — block RFC1918/loopback/link-local after DNS resolve; (g) add `require_auth` to any kerf-api route missing it; (h) unify password hashing to bcrypt (drop SHA-256 path).
- [ ] **P1-SILICON** — kerf-silicon: sanitize `top`/`top_module` (`^[A-Za-z_]\w*$`) before Yosys script interpolation (`routes_silicon_synth.py`, `yosys_bridge.py`); add `require_auth` to `/silicon/synth`.
- [ ] **P1-IMPORTS** — kerf-imports: fix zip-slip in `kicad.py` + `kicad_library.py` (validate each member path stays within tmpdir; sanitize `file.filename`); add `require_auth` to `/import-kicad`, `/import-kicad-library`.
- [ ] **P1-RUNROUTES** — kerf-render + kerf-slicing + kerf-firmware: add `require_auth` to `/run-render`, `/run-print-slice`, `/firmware/*`; enforce workspace confinement on `stl_path` / `source_path` / `hex_path` (`resolve().is_relative_to(workspace_dir)`).
- [ ] **P1-HARDENING** — fail-closed secrets: refuse to boot in non-dev if `jwt_secret`/`password_pepper` (kerf-core `config.py`) or share-HMAC (kerf-cloud `share_link.py`) are the dev defaults; add SHA256 integrity check to freerouting JAR download (kerf-electronics).
- [ ] **P1-WEBXSS** — frontend: wire `markdownSanitize` (`urlTransform` + allowed elements) into `ChatPanel.jsx` and `CompareMd.jsx`; add a Content-Security-Policy (`index.html` meta or server header).

## Phase 2 — Frontend wiring + dead-code cleanup

- [ ] **P2-EDITOR** — `Editor.jsx`: wire the finished-but-orphaned viewers — CAMView (`.cam`), TopoView `onRun`→POST `/run-topo`, AirfoilPolarPlot (`.airfoil`), BIMView (IFC), OrbitViewer; plus create+mount the small composites CLT/failure panel.
- [ ] **P2-PLUGINREG** — register `routes_aero_orbit` in `plugin.py` (orphan router); audit for other unregistered routers.
- [ ] **P2-SIDEBAR** — new sidebar widgets for routes with real compute and no UI: atmosphere, tsiolkovsky/CEA (`aeroPropulsionBridge`), RF link budget (`/run-rf-study`), silicon synth viewer.
- [ ] **P2-DEADCODE** — delete stranded `KerfVs*.jsx` compare pages (4) + their routes in `App.jsx`; resolve `CompareLanding` vs `index.jsx` duplicate; remove `Settings.jsx`, `CommitDiff.jsx`, `cloud/DiffViewer.jsx`, `stores/dirtyStore.js`; refresh `docs/wiring-audit.md`.
- [ ] **P2-TODOCLUSTER** — resolve `TODO(parent): wire` components: MaterialPbrEditor→MaterialEditor, Chat AtopilePreview/CircuitJsonPreview→ChatMessage, LadderEditorWithFlow, AutosaveStatus; wire or delete the 9-panel render-settings cluster.

## Phase 3 — Stubs

- [ ] **P3-SURFACING** — `surfacing.py:~960` `sketch_to_nurbs_curve()` arc branch: implement arc→NURBS instead of silent `pass`/`None`.
- [ ] **P3-CEALITE** — `routes_aero_propulsion.py`: actually use `rocketcea` when importable instead of always falling through to the lookup table.
- [ ] **P3-RUNCAM** — kerf-cam `/run-cam`: return an honest `{status:"pending"}` (matching FEM/CFD convention) when opencamlib is absent, instead of mock 10×10 G-code.

## Phase 4 — Redundancy / shared-core extraction (preserve public APIs)

- [ ] **P4-FRICTION** — extract one Colebrook-White friction-factor util; refactor `piping/process.py`, `fluidpower/circuit.py`, `hvac/ducts.py`, `boiler/plant.py`, `kerf-hvac/pressure.py`.
- [ ] **P4-STEAM** — single steam-saturation property module (use boiler's complete set); `thermocycle` Rankine + `refrigeration` call through it.
- [ ] **P4-SOLAR** — shared solar-geometry (Spencer 1971); dedupe `solarpv/sizing.py` ↔ `kerf-energy/solar.py`.
- [ ] **P4-HYDRO** — single Simpson hydrostatics core (navalarch canonical); `marine/hull.py` + `kerf-marine` delegate.
- [ ] **P4-ITGRADE** — single ISO-286 IT-grade table in `gdt/`; `gdt_callouts` + `kerf-mates/tolerance.py` import it.
- [ ] **P4-LINALG** — shared pure-Python mat/vec/quat util; dedupe `mbd/solver.py`, `robotics/arm.py`, `kerf-motion`.
- [ ] **P4-CONCRETE** — `kerf-structural/rc_beam.py` imports `_beta1` + ACI flexure from `concrete/design.py`.
- [ ] **P4-WORMBEVEL** — `wormbevel/design.py:bevel_agma_stress` calls `gearstrength` AGMA functions.
- [ ] **P4-SCAN** — `scan/fit.py` delegates plane/sphere/cylinder RANSAC to `reverse_engineering/`.
- [ ] **P4-TPMS** — dedupe gyroid/schwarz-P between `geom/lattice.py` and `frep/sdf.py`.
- [ ] **P4-CUTPOWER** — single `cutting_power`; `cncfeeds` delegates to `cuttingtool` physics.
- [ ] **P4-GUARDS** — shared `_guard_positive`/`_guard_nonneg`/`_err` util; sweep callers (run LAST — touches many files).

## Phase 5 — Domain module merges (flagged: larger, API-affecting)

- [!] **P5-GEARS** — merge `gearbox`+`gearstrength`+`wormbevel` → `power_transmission/`.
- [!] **P5-LATERAL** — merge `seismic`+`windload` → `asce7_lateral/`.
- [!] **P5-LIFTING** — merge `crane`+`rigging` → `lifting/`.
- [!] **P5-MOTION** — fold `robotics/` FK/IK into `kerf-motion`.

These change the public module layout / LLM tool surface; attempt only after Phases 1–4 are green and verified, and re-confirm scope before executing.
