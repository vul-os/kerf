# Kerf — Roadmap

**Status glyphs:** `✅ shipped` · `🚧 in flight` · `🔴 not started`

---

## North Star

**The most comprehensive CAD on Earth — a single tool in which a person can design *anything*.** Mechanical engineering, electronics, PCB, architecture, civil engineering, drafting, jewelry, automotive — and every other CAD sector, including the small and niche ones. We are doing **everything**. Nothing here is "cut." Lower priority means *later*, not *dropped*.

This is a **priority-ordered** roadmap, not a date-ordered or effort-ordered one. The tiers (P0 → P3) express sequence and leverage: which items earn the most credibility per unit of work.

Kerf is dual-licensed: the OSS core (MIT) and the hosted-tier code under `packages/kerf-{billing,cloud}/` + `src/cloud/`.

### Why chat-driven CAD works

Kerf is **chat-driven** CAD. Every capability is designed around one constraint:

> *Can the LLM produce and re-edit this deliverable through a text-native tool, and verify the result?*

Professional CAD is overcomplicated mostly because of command-discovery affordances (ribbons, palettes, wizards) that an LLM does not need. Kerf ships professional **capability** while deliberately not shipping professional **UI complexity**. This makes the roadmap shorter than it looks: many "pro features" are UX wrappers around a parametric core we expose as a text schema + LLM tool + verifier.

**Hard guardrail:** simplification is about *authoring mechanics only*. It is never an excuse to drop a domain or to skimp on correctness, output formats, or standards compliance. Those are *more* important under an LLM, not less.

---

## Platform foundation

The sector work only matters if you **own your work, are not locked in, and can run Kerf wherever you want**. Four commitments, all decided:

1. **Every cloud project is a real git repository** — `git clone`-able with stock git, no special client. Large or binary files are auto-detected and stored with a small in-git pointer. Version control is two complementary layers: fine-grained automatic file history *and* deliberate, shareable commits with GitHub sync.

2. **One client, cloud by default, easy optional self-host** — `pip install kerf` for the hosted cloud; `pip install 'kerf[server]'` + bring-your-own-Postgres + `kerf serve` for self-host. Same client, same data model, both paths first-class.

3. **Portability is the anti-lock-in guarantee** — `kerf sync` mirrors to a local folder with two-way sync; `kerf export` / `kerf import` produce and ingest a plain file tree. Moving a project between cloud and self-host is painless.

4. **A fully-local / offline desktop app is committed but demand-gated** — portability + two-way sync + easy self-host is the complete launch answer to "I want to own my data." The standalone offline desktop build is sequenced behind real demand.

---

## What shipped

### Latest delta — 2026-05-30

**Compare-matrix flip pass** ✅ — Comprehensive audit of `compare-manifest.json` against 50+ SHAs shipped since 2026-05-29. 45 Kerf rows flipped from `partial`/`no` → `yes` across 14 competitor pages: clash-detection UI (`ClashPanel.jsx`, SHA 0c78f08d) → Fusion/SolidWorks/FreeCAD; assembly-motion UI (`AssemblyMotionPanel.jsx`, SHA 567cc619) → Fusion/SolidWorks/Inventor; 5-axis CAM UI (`CAMView.jsx`, SHA f18c927c) → SolidWorks/FreeCAD; GD&T toolbar + 3D PMI (`GdntToolbar.jsx` + `Pmi3DOverlay.jsx`, SHA 0d74e89c) → SolidWorks/Onshape/Inventor/Creo/FreeCAD/Blender; FEA solve panels (linear-static/modal/buckling/fatigue/vibration, SHA 7e2530e8) → SolidWorks/Onshape; nonlinear static Total-Lagrangian + arc-length (SHA 709fa568) + explicit dynamics (SHA 8b7ad261) → SolidWorks nonlinear row; dental UI (SHA 480afca5) + watertight surgical guide (SHA 163fcf75) → Fusion dental + all 3Shape rows; AFP CNC export (SHA 730f05c6) + laminate weight UI (SHA 9a222c43) → Fibersim; OpenFOAM bridge + k-ε RANS (SHAs c9008860, f9c33663) → OpenFOAM/SolidWorks/Onshape CFD; HVAC duct UI (SHA 9cbaec76) → SolidWorks HVAC; NURBS×NURBS boolean (SHA 419043fe) → Vectorworks NURBS; Gordon-surface guide-rail loft (SHA a468c5e1) → Creo NURBS; daylighting tool → IES-VE no→partial. 165 rows remain partial/no (interactive PCB routing, archviz rendering, entertainment design, federated BIM XRef, etc. — legitimately not shipped).

### Previous delta — 2026-05-29

**Civil infrastructure UIs** ✅ — four viewport components wired to kerf-civil backends: `TINView.jsx` (3-D isometric TIN surface, wireframe + contour overlay, dispatches `civil_tin_terrain`); `PipeNetworkView.jsx` (2-D plan view with click-to-inspect pipes, flow/pressure overlay, dispatches `civil_water_network_solve`); `GradingPlanView.jsx` (existing + proposed contour overlay, cut/fill colour bands, dispatches `civil_tin_terrain` volume op); `LandscapeView.jsx` (planting symbols + irrigation zones, dispatches `landscape_plants` + `landscape_irrigation_schedule`) — `src/components/civil/`. Editor shell wired for `.tin`, `.pipe_net`, `.grading`, `.landscape` file kinds. 62 SSR tests pass.

### Previous delta — 2026-05-26
**`cad_component` real geometry substitution** ✅ — Library-mapped components in the CircuitEditor 3D tab now render real geometry instead of indicator chips: JSCAD `model_3d` source is evaluated in-browser; STEP `model_3d_paths` entries are fetched via `/api/projects/:pid/model3d` and parsed via `occt-import-js`. Cache: per-file-id in `fetchCacheRef` (STEP bytes cached by SHA-256 in `stepLoader.js`). `substitute_component` LLM tool registered via `kerf_parts.plugin`; `_try_include` pattern wired in `kerf_api.plugin` — `src/lib/circuitMappings.js`, `src/components/CircuitEditor.jsx`, `packages/kerf-parts/src/kerf_parts/tools.py`, `packages/kerf-api/src/kerf_api/routes_model3d.py`.

### Earlier delta — 2026-05-26
**HVAC design UI** ✅ — Three interactive panels wired to the Editor for `.hvac.load` / `.hvac.duct` / `.hvac.equip` file kinds: `HVACLoadPanel` (ASHRAE CLTD/RTS zone cooling load + degree-day heating, zone breakdown, monthly profile sparklines); `DuctDesignPanel` (velocity-method sizing + Darcy-Weisbach/Colebrook-White pressure drop, material roughness catalogue, 7 ASHRAE fitting types, total system pressure); `EquipmentSelectPanel` (AHU/chiller/boiler/heat-pump with ASHRAE 90.1-2022 minimum-efficiency data, part-load curves). Dispatch via `POST /api/tools/call` with graceful client-side fallback. Compare pages added for Trace 3D Plus / Carrier HAP / IES VE / DesignBuilder — `src/components/hvac/`.

### Previous delta — 2026-05-26
**HVAC AHRI equipment catalogue** ✅ — 30 AHRI-certified models across 6 categories (rooftop AC, split AC, water-cooled chiller, air-cooled chiller, gas boiler, heat pump); 5 representative models per category with real AHRI certification numbers, full-load EER/IEER/COP/AFUE, and AHRI-certified part-load curves at 25/50/75/100% load. `hvac.equipment_select` LLM tool wired; `EquipmentSelectPanel.jsx` dispatches to backend. Source: AHRI Certified Products Directory (https://www.ahridirectory.org). Compare pages for Carrier HAP, IES VE, Trace 3D added — `kerf-hvac/src/kerf_hvac/ahri_catalogue.py`.

### Latest delta — 2026-05-26

**Civil hydraulics** ✅ — LandXML 1.2 import/export (`civil_landxml_import/export`); steady-state pressurised pipe network (Todini GGA + HW/DW, `civil_water_network_solve`); Manning circular/trapezoidal sewer (`civil_sewer_manning_capacity`); rational-method peak runoff (`civil_storm_rational`); HDS-5 inlet-control culvert (`civil_culvert_capacity`) — `kerf-civil/src/kerf_civil/tools_hydraulics.py`.

**FEM dynamics** ✅ — linear eigenvalue buckling (`fem_buckling_linear`); mode-superposition harmonic frequency response (`fem_harmonic_response`); random-vibration PSD / Miles equation (`fem_random_vibration_psd`); acoustics cavity FEM + BEM radiation; high-frequency EM (waveguide, S-params, FDTD); electrostatics + magnetostatics; 2-D projection Navier-Stokes — `kerf-fem/src/kerf_fem/{buckling,harmonic,random_vibration,acoustics_fem,em_highfreq,em_field,cfd_navier_stokes}.py`.

**Structural codes (AISI + TMS)** ✅ — AISI S100-16 cold-formed steel: effective-width, flexure (`structural_cfs_flexure`), compression (`structural_cfs_compression`), web-crippling (`structural_cfs_web_crippling`); TMS 402-16 masonry ASD: flexure/shear/axial (`structural_masonry_*`) — `kerf-structural/src/kerf_structural/{cold_formed_steel,masonry}.py`.

**G3 surfacing wired** ✅ — `feature_blend_srf_g3` (surfacing.py:1376) + `feature_g3_chain_blend` (surfacing.py:1894) registered as LLM tools via `surfacing` module in `_TOOL_MODULES`; `blend_srf_g3`, `curvature_rate_continuity_residual`, `zebra_stripe`, `reflection_lines`, `curvature_comb` all exported from `geom/__init__.py`; `feature_zebra_analysis` and `feature_isophote_analysis` also wired.

**Structural code design** ✅ — AISC 360-22 (Ch. E/F/H members + connections + base-plate, LRFD+ASD); ACI 318-19 (flexure/shear/PM + punching §22.6 + torsion §22.7); NDS 2018 timber; AISI S100-16 cold-formed steel (effective-width, flexure/compression/web-crippling); TMS 402-16 masonry ASD (flexure/shear/axial); ASCE 7-22 load combos + ELF + RSA/Newmark seismic. Full Eurocode: EC2, EC3, EC5, EC8.

**Native FE** ✅ — MITC4 plate/shell (Bathe-Dvorkin) + modal via inverse iteration; linear eigenvalue buckling + harmonic response + random-vibration PSD; 2D/3D frame stiffness + story drift; multi-axial critical-plane fatigue (Findley, SWT-3D, Brown-Miller); acoustics FEM/BEM + high-frequency EM + electrostatics/magnetostatics; geotech liquefaction triggering (Seed-Idriss/Tokimatsu).

**Machine elements depth** ✅ — ISO 6336 gear rating Method B; ISO/TS 16281 bearing modified life (aISO); planetary gearbox (3 Willis modes + compound); Taylor extended tool-life + Gilbert economics.

**Thermo-fluid depth** ✅ — IAPWS-IF97 steam Regions 1/2/4; Bell-Delaware shell-and-tube HX (TEMA + 5 correction factors); transient pipe-network (MOC waterhammer + surge-tank); ASHRAE CLTD/RTS transient cooling loads.

**Electronics / power depth** ✅ — IBIS-AMI signal integrity (Bergeron + PRBS eye); AC PDN impedance + decap optimiser; Newton-Raphson AC load-flow; IEC 60255 + IEEE C37.112 protection coordination + IEEE 1584-2018 arc-flash; fibre-optic link budget.

**Aero / marine / space depth** ✅ — 3D VLM + viscous strip drag + Prandtl-Glauert/Kármán-Tsien + Korn-Lock wave-drag; strip-theory seakeeping RAOs (Lewis-form + JONSWAP); Holtrop-Mennen resistance + EHP; multi-revolution Lambert (Lancaster-Blanchard/Izzo 2015).

**Manufacturing depth** ✅ — adaptive/trochoidal CAM HSM + rest machining; moldflow Hele-Shaw front tracking + weld-line + air-trap; casting Chvorinov + riser sizing + gating; NFP true-shape polygon nesting (57.6 % L-shape utilisation).

**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder) + UI parity shipped (CrownSculptingPanel, ImplantLibrary, SurgicalGuide — preset picker, occlusion overlay, filterable Straumann/Nobel/Zimmer/MIS catalogue, CBCT import + pose editor + sleeve preview, all dispatching to kerf-dental backend); Swiss lever escapement + mainspring + balance-wheel; solar PV partial shading + bypass-diode + MPPT; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).
**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder); surgical guide emits milling-ready B-rep + STL export ✅; Swiss lever escapement + mainspring + balance-wheel; solar PV partial shading + bypass-diode + MPPT; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).

**Building/PV UI** ✅ — `BuildingEnergyPanel` (zone-by-zone occupancy/lighting/equipment/infiltration/HVAC editor, EnergyPlus IDF export); `PVShadingPanel` (array layout + obstruction polygons + bypass-diode + MPPT + monthly yield chart); `MonthlyLoadChart` (SVG stacked-bar); `.energy.bldg` / `.energy.pv` / `.energy.load` file kinds wired in Editor.jsx.
**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder); surgical guide watertight single-solid ✅ (`surgical_guide_to_body` — boolean subtract of drill bores from plate, genus-validated); Swiss lever escapement + mainspring + balance-wheel; solar PV partial shading + bypass-diode + MPPT; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).
**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder); Swiss lever escapement + mainspring + balance-wheel; solar PV partial shading + bypass-diode + MPPT + full series IV convolution ✅; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).

**Tolerancing / QA** ✅ — 3D vector-loop tolerance stackup (6-DOF Jacobian); SPC control charts (Shewhart/CUSUM/EWMA + Nelson/WECO); ISO 286 limits & fits.

**Optics / acoustics** ✅ — Gaussian beam (complex-q + ABCD + M² + fibre coupling); non-sequential ray tracing + ghost detection; wave-domain room acoustics (image-source IR + Schroeder RT60 + SEA); Seidel S5 corrected.

**Implicit geometry** ✅ — F-rep CSG (union/intersect/subtract/blend/shell) + domain warps (twist/taper/wave) in `kerf_cad_core.frep.csg`.

**Materials + LCA** ✅ — Ashby database to ~200 materials (14 families) with Pareto-frontier multi-objective selection; full ISO 14040/44 LCA (4 phases, 6 impact categories, Monte-Carlo uncertainty).

**Compare matrices** ✅ — feature-matrix YAML for 14 reference CADs: Fusion 360, SolidWorks, Onshape, FreeCAD, Rhino, KiCad, CATIA, Creo, NX, Inventor, AutoCAD, Altium, Revit, Blender — 741 grounded rows total.

**Security hardening** ✅ — `/run-topo` auth gate; NFP `grid_step` clamped; PVT `n_mc` clamped; Yosys module-name injection blocked; shared `_guard_*` helpers extracted across 68 files (−2009/+129 lines net).

### Core platform

- **Auth + projects + files + chat (CRUD)** ✅ — Postgres, JWT, Google OAuth.
- **Plugin monorepo (`packages/kerf-*`)** ✅ — `kerf-core` app factory + entry-point loader; ~25 plugin packages; 864+ tests.
- **Single-binary build + brew/curl install** ✅ — embedded Vite SPA (~32 MB).
- **Auth-optional local mode** ✅ — `POST /auth/bootstrap-local` singleton user.
- **Cloud: workshop sharing, billing, LLM pricing, free/paid buckets + wallet** ✅ — USD-display, credits at cost, BYO-key plumbing.
- **Cloud: git (commits/branches/merge/GitHub sync) + git Storer** ✅.
- **Large-file git handling** ✅ — pointer kind, Phase 1.
- **Diff-based + compressed revisions** ✅ — 82× shrink.
- **Workspaces (orgs), activity timeline, avatars/CDN, collapsible chat** ✅.
- **E2E Playwright + per-plugin pytest suites** ✅.
- **Billing-ledger schema on fresh databases** ✅.

### Scripting / SDK

- **`.script.py` via `kerf-sdk`** ✅ — `/v1/rpc` JSON-RPC over the LLM tool registry; API tokens; PyPI publish.
- **SDKs: Python · TypeScript · Rust · Go · Lua** ✅ — same `/v1/rpc` wire format.

### Parametric core

- **Equations / global parameters** ✅ — `.equations`, mathjs.
- **Configurations / variants** ✅ — per-file param overrides, BOM rollup.
- **Materials database** ✅ — `.material` kind, 200 seeded materials.
- **Two coexisting kernels** ✅ — `.jscad` (mesh) + `.feature` (OCCT BRep), shared `.sketch`/`.assembly`/`.drawing`.
- **Pure-Python B-rep + NURBS kernel** ✅ — validated `Body` topology, tolerant booleans, G1/G2 fillets, closest-point, hardened SSI, parametric history DAG with persistent face naming. 620 hermetic analytic-oracle-asserted tests.

### Geometry kernel — depth

The pure-Python kernel (`packages/kerf-cad-core/src/kerf_cad_core/geom/`) now matches Rhino/Blender-class construction depth with an analytic foundation:

| Module | Description | Status |
|---|---|---|
| **`brep.py`** | B-rep topology: radial-edge `Body→Solid→Shell→Face→Loop→Coedge→Edge→Vertex`, nine Euler operators, Euler–Poincaré invariant enforced | ✅ shipped |
| **`brep_build.py`** | Analytic verbs (box/cylinder/sphere/Coons patch) → `validate_body`-clean `Body` | ✅ shipped |
| **`boolean.py`** | Tolerant pure-Python solid booleans (regularised cut/fuse/common) over the primitive matrix, 2-manifold result | ✅ shipped |
| **`fillet_solid.py` / `chamfer.py`** | G1/G2 surface blend + edge fillet + variable chamfer | ✅ shipped |
| **`offset.py`** | Exact-distance surface/curve/loop offsets with self-intersection trim | ✅ shipped |
| **`coons.py`** | Boundary-interpolation Coons patches, exact to 1e-12 | ✅ shipped |
| **`inversion.py`** | Closest-point / point-inversion (Piegl 6.1, analytic partials on rational surfaces) | ✅ shipped |
| **`intersection.py`** | Hardened SSI: loop-detection, tangential-branch detection, small-loop guard, analytic specialisations | ✅ shipped |
| **`intersection_degen.py` — Degenerate SSI (Legendre canonical forms)** | `detect_degenerate_ssi` + `compute_degenerate_ssi_curve` + `ssi_extended`; handles coaxial cylinders, coplanar planes, sphere-tangent-plane, Legendre/Weierstrass conic section for tangent quadric pairs; LLM tool `nurbs_ssi_with_degenerate_check` registered; 27 hermetic tests with analytical oracles | ✅ shipped |
| **`geom/history/`** | Parametric history DAG + `feature_id::role::fingerprint` persistent naming — downstream fillet survives upstream parameter edits | ✅ shipped |
| **G3 surfacing** | `feature_blend_srf_g3` (surfacing.py:1376) + `feature_g3_chain_blend` (surfacing.py:1894) registered LLM tools; `blend_srf_g3` / `curvature_rate_continuity_residual` / `zebra_stripe` / `reflection_lines` / `curvature_comb` exported from `geom/__init__.py`; `feature_zebra_analysis` + `feature_isophote_analysis` wired | ✅ shipped |
| **General solid boolean** | NURBS-faced / non-axis-aligned solids (today: axis-aligned only; general CSG delegates to OCCT worker) | 🔴 not started |
| **GK-P: Hollow operator** | Compound feature: shell offset + inner-face blend + inner-edge fillet + port drilling + optional ribs — `hollow_body` / `hollow_with_ribs`; LLM tool `brep_make_hollow` | ✅ shipped |

**GK-P (parity) series in flight.** A four-agent survey of Kerf vs ~18 kernel-relevant CADs found a concrete, finite gap list. GK-01..GK-139 are landed. The `GK-P` series (tracked in `tasks.md`) closes the remaining gaps:

- **Adaptive tessellation LOD chain** ✅ — `kerf_tess.adaptive_lod`: `generate_lod_chain` / `screen_error_to_chord_deviation` / `pick_lod_for_distance`; pinhole-camera screen-error math; 4-level independent mesh chain for three.js `MeshLOD`; `tess_generate_lod_chain` LLM tool registered.
- **Wiring** — expose shipped class-A math (G3 blends, zebra analyser, curvature-rate oracle) from `geom/__init__.py` and `surfacing.py`; all small, first in queue.
- **Foundational kernel** — general solid boolean for NURBS-faced bodies, MatchSrf G3, isophote/EMap, Stam limit-tangents + G1 at extraordinary SubD points, fractional creases, analytic surface derivatives.
- **Construction verbs** — loft guide-rails, sheet-metal hem/jog/multi-flange, direct-edit non-planar + delete-face, weldment gussets/end-treatments, surface patch-from-points.
- **SubD / mesh** — multires displacement, SDF CSG + marching-cubes, sculpt brush engine, isotropic remesh, surface-snap retopo, LSCM UV unwrap.
- **Architectural geometry** — B-rep→2D tessellate, roof/curtain-wall/corridor generators, wall compound-layer offset, hatch/section-fill.
- **Sketcher** — collinear constraint, ellipse solver entity, G2 continuity.
- **Interop** — 3DM write with read→write→read Hausdorff oracle.

### Mechanical / CAD

- **OCCT `.feature` Phase 2/3** ✅ — Pad/Pocket/Revolve/Hole/Fillet/Chamfer/Shell/Sweep/Loft/Push-Pull/Linear-Polar-Mirror patterns; face/edge gumball.
- **2D sketcher v1 + v2** ✅ — full constraint set, trim/extend, ellipse, B-spline, bezier, fillet, mirror, patterns.
- **Assembly model + 3D mates** ✅ — coincident/concentric/parallel/perp/distance/angle/tangent; gradient-descent solver.
- **Assembly clash detection UI** ✅ — OBB-SAT + BVH + tri-tri backend; Check Clashes side panel with pair list (part A / part B / severity / Jump-to); viewport highlight via `highlightFaces` hook — parity with SOLIDWORKS Interference / Fusion / Onshape clash detection.
- **Assembly clash detection** ✅ — hard/clearance/coincident OBB-SAT + triangle-mesh narrow phase; cross-discipline `by_discipline_pair` summary; real OBB fallback ✅: when a component has no `bbox` but carries a `step_blob` / `step_blob_ref`, a tight PCA-OBB is computed from the STEP geometry and SHA-256 cached — no more 1 mm³ approximation; unit-box fallback retained only when neither bbox nor STEP is available, with an explicit warning in `errors`.
- **Tolerance stack-up** ✅ — worst-case/RSS/Monte-Carlo + auto chain-walk.
- **2D drawings** ✅ — multi-sheet, dimensions, GD&T frames, section hatching, leaders/balloons, centerlines.
- **3D PMI + GD&T annotation UI** ✅ — ISO 1101 GD&T toolbar (DrawingToolbar + GdntToolbar) with all 14 characteristics; datum A/B/C placement; FCF click-to-place modal with tolerance value, diameter zone, material-condition modifier, datum refs; SVG FCF glyphs (FcfGlyph/DatumGlyph) rendered inline per standard; 3D PMI overlay (Pmi3DOverlay) projects FCF labels into the three.js viewport; annotations persist via addFcf/addDatumLabel in the drawing data model.
- **Auto-dim ISO 129-1:2018** ✅ — chain / baseline / mixed dimensioning (§5.1); extension-line gap + overshoot (§5.4); 10 mm line spacing; leader lines at preferred 15° angles (§10); symmetric / unilateral / limit tolerance formats (§8); compliance validator; 2 LLM tools (`drawing_auto_dimension_iso`, `drawing_validate_iso`).
- **NURBS surfacing (Phase 4)** ✅ — sweep1/2/network/blend/loft + `surface_continuity` (C0–C2/G0–G2); surface-direct boolean; trim-by-curve; curvature-comb viz; zebra/reflection-line viewport toggle. G3 *enforcement* on the OCCT side is structurally impossible (absent from OCCT's type system); pure-Python is the G3 path.
- **NURBS surfacing (Phase 4a — jewelry priority)** ✅ — `opSweep2` (two-rail sweep via `BRepFill_PipeShell`-style RMF midline, `sweep2_to_body` in `brep_build.py`), `opNetworkSrf` (Gordon/Coons-Gordon four-curve network, `network_srf_to_body`), `opBlendSrf` (G1/G2 Bezier blend strip, `blend_srf_to_body`); all three registered as LLM tools (`feature_sweep2`, `feature_network_srf`, `feature_blend_srf` in `surfacing.py`); 33 hermetic `validate_body`-clean tests in `test_phase4a_jewelry_surfacing.py`; scenario fixtures in `tests/fixtures/`.
- **Rhino parity** ✅ — 3DM I/O, SubD (Catmull-Clark), quad remesh, mesh tools, layers/display, parametric `.graph`, render output.
- **Persistent face naming** ✅ — sketch-anchored + topo-hash (frontend T1–T7) plus kernel-side `feature_id::role::fingerprint` selector in the pure-Python DAG.

### Simulation / manufacturing

- **FEM** ✅ — FEniCSx + CalculiX: linear-static + modal + steady thermal + bonded contact; linear eigenvalue buckling + harmonic frequency response + random-vibration PSD; MITC4 plate/shell; acoustics FEM/BEM; high-frequency EM; electrostatics + magnetostatics; multi-axial fatigue; 2-D projection NS solver. Reference-value suite with Roark/Blevins/Incropera oracles (42 of 43 green).
- **CFD foundation** ✅ — 2-D laminar: potential flow (`Cp(θ)=1−4sin²θ` oracle) + lid-driven cavity (Ghia Re=100 reference); 61 hermetic tests.
- **Topology optimization** ✅ — SIMP via FEniCSx; NURBS surface fit; multi-body.
- **CAM** ✅ — 2.5D + 3D parallel/waterline + lathe + 5-axis constant-tilt + 3+2 indexed; tool DB; LinuxCNC/GRBL/Fanuc posts.
- **5-axis CAM UI** ✅ — `CAMView.jsx` mode switch (3-axis / 5-axis-indexed / 5-axis-continuous); tilt axis (A/B/C) + angle; strategy (swarf / contour-on-tilted-plane / indexed-rough); spindle vector preview; dispatches `cam_run` backend tool (`operation=5axis_finish` or `3plus2`).
- **Slicing** ✅ — plane-section, CNC layered, 3D-print G-code (Cura, Tier 1).

### Electronics

- **KiCad-class PCB design** ✅ — ERC, hier-schematic, buses/diff-pairs, net classes/rules, length tuning, via stitching/teardrops, shove router, copper pour, DRC.
- **Library `cad_component` 3D substitution** ✅ — Library-mapped components resolve to real JSCAD/STEP geometry in the CircuitEditor 3D tab; indicator chips replaced; cache per component_id; `substitute_component` LLM tool.
- **Fabrication package** ✅ — Gerber RS-274X, Excellon drill, IPC-2581, ODB++, pick-and-place, fab BOM, 3D board STEP export.
- **SPICE + RF + autorouting** ✅ — ngspice, scikit-rf S-params/Smith chart, FreeRouting DSN/SES.
- **Wiring/harness** ✅ — WireViz YAML→SVG (2D; 3D in flight at P1-7).
- **PLC** ✅ — MATIEC lint Tier 1; PLCopen XML (IEC TR 61131-10) reader/writer (T-220); `import_plcopen_xml` + `export_plcopen_xml` LLM tools; LadderEditor Import/Export buttons wired.
- **Wiring/harness** ✅ — WireViz YAML→SVG (2D) + 3D polyline harness routing + formboard-flatten 2D manufacturing output (T-37, P1-7 complete).
- **PLC** ✅ — MATIEC lint Tier 1.
- **Silicon / IC layout** ✅ — VHDL + Verilog parsers; GHDL + Yosys + ngspice bridges; GDS II / OASIS I/O; SKY130 PDK; LEF/Liberty readers; OpenROAD place-and-route; DRC + LVS + parasitic extraction; mask fracturing. T-231..T-248.
- **Firmware / embedded** ✅ — board catalogue (Arduino/ESP32/STM32/RP2040/AVR); library cache; direct-gcc orchestrator (`avr-gcc`/`arm-none-eabi-gcc`/`xtensa-esp32-elf`); upload wrappers; serial monitor panel; LLM tools; cloud Flash via BYO worker ✅ (esptool/avrdude/openocd dispatched to enrolled workshop machine). T-225..T-230.
- **Silicon / IC layout** ✅ — VHDL + Verilog parsers; GHDL + Yosys + ngspice bridges; GDS II / OASIS I/O; SKY130 PDK; LEF/Liberty readers; OpenROAD place-and-route; DRC + LVS + parasitic extraction; mask fracturing; SPICE waveform viewer UI ✅. T-231..T-248.
- **Firmware / embedded** ✅ — board catalogue (Arduino/ESP32/STM32/RP2040/AVR); library cache; direct-gcc orchestrator (`avr-gcc`/`arm-none-eabi-gcc`/`xtensa-esp32-elf`); upload wrappers; serial monitor panel; LLM tools. T-225..T-230.

### Architecture / BIM

- **`.bim` text-DSL → IFC4** ✅ — walls/slabs/spaces/openings/levels/site.
- **IFC import Tier 1 + 2** ✅ — walls/slabs/spaces/levels/sites + openings/MEP/families/schedules.
- **Revit parity** ✅ — `.family`/`.schedule`/`.view`/`.sheet`, categories, type-vs-instance, phasing/filters, stairs/railings, MEP, curtain wall.

### Aerospace / composites

- **Applied aerodynamics** ✅ — ISA atmosphere, VLM/thin-airfoil, flight mechanics, propulsion, Breguet range/endurance; 6-DOF; orbital mechanics (Kepler/Lambert/Hohmann); rocket propulsion (CEA-lite); ADCS (quaternion + reaction wheels + magnetorquers); spacecraft thermal network.
- **Composites (CLT)** ✅ — ABD matrix, per-ply stress/strain, Tsai-Wu/max-stress/Hashin failure indices, first-ply-failure, laminate moduli.
- **Composites manufacturing UI** ✅ — `LaminateStackup` (drag-to-reorder ply table, balance/symmetry check, areal-weight + cost rollup, CLT stiffness matrix preview); `AFPToolpathView` (AFP 2D tape-path canvas, cure cycle plot, path-plan dispatch, **Export CNC dropdown → G-code / APT**); `FiberOrientationContour` (HSL contour heatmap, angle tooltip, exploded ply stack, drape sim dispatch). File kinds: `.layup` / `.afp_plan` / `.fiber_map`. Backend routes: `POST /api/composites/clt`, `POST /api/composites/afp` (+ `?format=gcode|apt`), `POST /api/composites/fiber_map`; auth-gated. **AFP CNC export ✅** — `afp_export.py` (`afp_to_gcode` 5-axis G-code with M200/M201/M202/M203/M204/M205 fibre M-codes; `afp_to_apt` APT/CL ISO 3592 GOTO/FEDRAT/AUXFUN); `composites_afp_export` LLM tool; Fibersim + VeriFiber AFP rows → yes; 79 tests green.
- **Aeroelasticity** ✅ — flutter boundary (Theodorsen + p-k method), doublet-lattice.

### Library / parts / BOM

- **Library system v1 + BOM** ✅ — `kind='part'`, distributor APIs (DigiKey/Mouser/LCSC), curated manufacturer libs.
- **Cross-project parts** ✅ — external_ref, lockfile, derived-artifact cache; compile-on-demand (hit→skip recompile, miss→store) ✅; dev cache-stats overlay ✅.
- **Cross-project parts** ✅ — external_ref, lockfile, derived-artifact cache; derived-cache hit response includes `last_accessed_at` + `cache_key` ✅.
- **Cross-project parts** ✅ — external_ref, lockfile, derived-artifact cache; DerivedCacheOverlay mounted (dev-only).
- **kerf-partsgen** ✅ — 5 ISO/DIN family generators shipped.

### Frontend / UX

- **Viewport** ✅ — Render dropdown, Daylight mode, Exposure slider, PCF soft-shadows, quality presets (Low/Medium/High/Ultra), material editor panel (roughness/metalness/opacity/emissive), viewport keybindings.
- **GDS layout viewer** ✅ — layer palette, zoom/pan, net highlight, DRC overlay.
- **Monaco editor modes** ✅ — VHDL, Verilog, SPICE syntax highlighting.
- **Compare pages** ✅ — 14 head-to-head comparison routes.
- **Docs viewer redesign** ✅ — grouped sidebar, breadcrumbs, TOC, audit-filter.
- **Pre-React boot loader** ✅ — Kerf-branded SVG triangles loader, zero flash.
- **Touch + responsive polish** ✅ — Renderer + Gumball touch gestures, Editor responsive layout.
- **Render output** ✅ — PBR hero / share-card pipeline at 2048×2048; Blender Cycles offline path for jewelry.

---

## In flight

| # | What | Why it matters | Status |
|---|---|---|---|
| **P0-5** | **Large-assembly performance ceiling** — measured budget + LOD / lazy-load for 1000s of parts. Automotive full-vehicle DMU is the extreme case. | First credibility block for automotive and large mechanical. | ✅ shipped — `assembly/perf.py` LOD planner + lazy-load ordering wired to `Renderer.jsx` viewport: camera-move debounce (200 ms) queries `assembly_lod_plan` tool, applies full/bbox_proxy/culled tiers to scene meshes; debug HUD toggle added to Render menu — `kerf_cad_core/assembly/perf.py`, `src/components/Renderer.jsx` |
| **P0-6** | **Broaden text / code file support** — common text and code files open as editable text with syntax highlighting. | Every project benefits; gates firmware depth. | ✅ shipped — `FileEditor.jsx` + `editorModes.js`: 30+ extensions (Python, C/C++, JS/TS, Markdown, YAML, …) mapped to Monaco language IDs — `src/components/FileEditor.jsx` |
| **P0-7** | **Project export / materialize foundation** — plain file-tree for `kerf export` / `kerf import` / `kerf sync`. | The anti-lock-in guarantee's substrate. | ✅ shipped — `GET /projects/{pid}/export` ZIP route + `POST /api/projects/import` bulk ZIP import (path-traversal guard, size cap, file-count cap, ext→kind mapping, binary/text split) — `kerf-api/routes.py`, `kerf-cli/portability.py` |
| **P0-8** | **Testing / seeding / deploy-hardening** — broad test suites + realistic seed data + one-command local/dev loops. | Quality gate before broader build-out. | 🚧 in flight |
| **P1-7** | **3D in-vehicle wiring harness** — route through DMU, bundle/segment/connector libs, formboard flatten, length/gauge/voltage-drop. | Closes the ECAD-to-harness loop. | ✅ shipped — 3D polyline bundle routing + wire-gauge + length/voltage-drop + formboard-flatten (T-37) all shipped — `kerf-wiring/harness3d.py`, `kerf-wiring/formboard_flatten.py`, `kerf-wiring/tools/route_harness_3d.py`, `kerf-wiring/tools/wiring_formboard_flatten.py` |
| **P1-8** | **Git-as-substrate with automatic large-file handling + free forks** — every project a stock-`git clone`-able repo; large/binary files auto-detected + kept in storage with a small in-git pointer; near-instant forks via shared content-addressed storage. | Own-your-data guarantee. | 🚧 in flight |
| **P1-9** | **Unified `pip install kerf` client** — cloud-default, easy optional self-host; fail-fast on missing database URL. | Reach: one client for all install modes. | 🚧 in flight |
| **P1-10** | **Local folder sync + export/import portability** — `kerf sync` two-way folder mirror; `kerf export` / `kerf import` plain file tree; symmetric cloud ↔ self-host. | Anti-lock-in, demonstrable not just promised. | 🚧 in flight — two-way sync daemon (one-shot + watch mode + OCC conflict detection) shipped; symmetric cloud↔self-host portability complete — `kerf-cli/sync.py`, `kerf-cli/portability.py` |
| **GK-P** | **Geometry kernel parity series** — close the gap list from the multi-CAD survey (GK-01..GK-139 landed; wiring + foundational + SubD + architectural geometry remaining). | Every persona's work quality depends on kernel robustness. | 🚧 in flight |
| **T-100** | **FEM matching CalculiX / Z88 / Mystran depth** — buckling + harmonic + PSD + acoustics + EM + fatigue shipped; remaining: explicit dynamics, full nonlinear static, k-ε turbulence, coupled variation. | Serious simulation work. | 🚧 in flight |
| **T-101** | **CFD (CfdOF-class)** — turbulence models, 3-D unstructured meshing, OpenFOAM bridge beyond the 2-D laminar foundation. | Fluid and aero simulation. | 🚧 in flight |
| **Hosted infra** | **Cloud infrastructure** — engine on Fly.io (`fra` Frankfurt, co-located with the DB, `shared-cpu-2x` / 2 GB), Neon Postgres (`eu-central-1`), Cloudflare R2 blobs (zero egress), Resend email. GPU renders via RunPod Serverless (L4→H100, scale-to-zero) — `GPUBackend` protocol + `RunPodGPUBackend` (submit/poll/fetch_result/capabilities, auth, retry/backoff) + `SelfHostedWorkerBackend` (BYO) all shipped; GPU worker dispatch foundation + BYO worker enrollment shipped (`POST /api/workers/enroll`, heartbeat, claim-job, complete + billing skip; Settings → Workers tab). See `deployment/fly.md`. | Stable pay-as-you-go stack; BYO workers run at zero credit cost; managed RunPod path now live. | ✅ shipped — see `packages/kerf-render/src/kerf_render/gpu_backend.py` |
| **GPU worker dispatch + BYO worker CLI** | **`kerf-worker` companion CLI shipped** — `pip install kerf-worker`; `kerf-worker enroll/run/status/revoke`; NVIDIA GPU probing via `nvidia-smi`; heartbeat every 30 s; long-poll claim-job with `cycles_render` (Blender) + `fem_solve` (CalculiX) dispatch; BYO billing short-circuit (`billing_bucket='byo'` → no credits charged). **SIGNED-UPLOAD-URL shipped** — claim-job returns `signed_upload_url` (presigned S3/R2 PUT, 90-min TTL), `result_key` (`worker-results/{job_id}.bin`), `result_ttl_seconds`; `/complete` accepts `result_key` (storage.head verification, no bytes through API) alongside legacy `signed_url`; `Storage.signed_put_url` + `Storage.head` added to base ABC, S3Storage, LocalStorage (`local://` fallback). `packages/kerf-worker/` — 4 commands, 8 hermetic tests. | Users on paid plans can register their own GPU hardware to run render/FEM jobs at zero credit cost. Delivers on the BYO-key billing tier promise. | ✅ shipped — `packages/kerf-worker/src/kerf_worker/` |

---

## Planned next

### Depth gaps (concrete, near-term)

| # | Gap | vs | Status |
|---|---|---|---|
| G-3 | **Interactive push-and-shove diff-pair tuning** — full diff-pair routing, length-skew tuning, and push-shove | KiCad / Altium | ✅ shipped — `route_diff_pair` + `tune_diff_pair_skew` + `validate_diff_pair` + `push_shove_segment` — `kerf-electronics/routing/push_shove.py` |
| G-4 | **Broader ECAD import** — Allegro / PADS / gEDA / Eagle v10 | Altium / Cadence | ✅ shipped — four dedicated readers with tests — `kerf-imports/src/kerf_imports/{allegro_reader,pads_reader,geda_reader,eagle_reader}.py` |
| G-5 | **Kernel G3 / class-A leading** — wired G3 blends + curvature-comb + imprint | Alias / ICEM Surf | ✅ frontend wiring shipped — Class-A viewport toggle (Render menu → "Class-A": zebra stripes + G2/G3 per-edge audit panel) + ImprintCurve inspector entry in FeatureView; backend `feature_global_continuity_audit` + `edge_continuity_report` + `imprint_curve_on_face` all pre-existing |
| G-6 | **SubD authoring with creases + edit workflow** | Rhino 8 SubD | ✅ shipped — cage creation/extrude/bevel/loop-cut/slide/crease/bevel-weight + Catmull-Clark evaluation — `kerf-cad-core/geom/subd_authoring.py` |
| G-7 | **Render: caustics + dispersion** — in-browser path-tracer + Blender Cycles spectral | Cycles / V-Ray / KeyShot | 🔴 not started — Cycles translator stashes Sellmeier/Abbe coefficients for downstream use but no caustic solver is wired; in-browser path-tracer not started |
| G-8 | **Direct + parametric history coexistence** | Fusion / Inventor / Onshape | ✅ shipped — history mode (direct edit promoted to DAG feature node, replays on upstream changes) + in-place mode; 30+ tests — `kerf-cad-core/direct_edit.py`, `geom/history/direct_edit.py` |
| G-9 | **Full joint system** — rigid/revolute/slider/cam/gear/pin-slot | Inventor / SolidWorks | ✅ shipped — all six joint types with analytic kinematics and drive support — `kerf-mates/joints.py` |
| G-10 | **BIM parametric family authoring UX** | Revit | ✅ shipped — `FamilyTemplate` schema + expression evaluator + cycle detection + `generate_body` — `kerf-bim/family_authoring.py` |
| G-11 | **BIM family library** — curated catalog | Revit | ✅ shipped — 40+ entries across Doors / Windows / Walls / Columns / MEP / Furniture categories — `kerf-bim/family_library.py`, `family_library_data.py` |
| G-12 | **BIM walls / doors / windows / slabs full parametric** | Revit | ✅ shipped — `Door` + `Window` + `JambProfile` hosted in walls with IFC mapping; walls/slabs already in core BIM — `kerf-bim/openings.py` |
| G-13 | **BIM stairs / ramps full** | Revit | ✅ shipped — multi-flight stairs + winder geometry + code-compliance (IBC/BS/SANS) + ramps + handrails + IFC export — `kerf-bim/stairs.py` |
| G-14 | **BIM structural grid + framing** | Revit Structure / Tekla | ✅ shipped — `StructuralGrid` axes + `ColumnMember`/`BeamMember`/`ConnectionNode` snapped to grid + rebar + IFC mapping — `kerf-bim/grid.py`, `kerf-bim/framing.py` |
| G-15 | **BIM site / earthwork (toposolids)** | Revit / Civil 3D | ✅ shipped — toposolid B-rep grading + IFC site export — `kerf-bim/tools/site_geometry.py`, `kerf-bim/site_ifc.py` |
| G-16 | **BIM material catalogue with render appearance** | Revit / Enscape | ✅ shipped — 40+ materials with PBR properties (`base_color`, `metallic`, `roughness`, `ior`, `transmission`) wired to Cycles translator — `kerf-bim/material_catalogue.py` |

### Long-tail verticals

Everything committed, lowest priority. Ordered roughly by near-term readiness.

**Mechanical / product:** cams generators · woodworking / furniture / joinery + cutlist · power one-line / switchgear · lighting / photometric · interior / space-planning / FF&E · kitchen / bath / cabinetry / millwork · landscape · scaffolding / formwork.

**Vehicles:** composites ply/layup authoring (draping / fiber-steering / Fibersim class) · hull fairing (NURBS-reachable) · 3D harness routing.

**Civil / infrastructure (distinct engines):** plan-and-profile sheet engine · IFC-4.3-infra I/O · bridge/tunnel · mining · marine/dredging · rail signaling. *(CRS engine, horizontal/vertical alignment, corridor, earthworks, geotechnical, LandXML 1.2 I/O, pressurized water-distribution networks (Todini GGA + Hazen-Williams/Darcy-Weisbach), gravity sewer (Manning), storm rational method + HDS-5 culverts already shipped; TINView / PipeNetworkView / GradingPlanView / LandscapeView UIs ✅ 2026-05-29.)*

**Body-worn / medical / craft:** watchmaking / horology · eyewear / frames · footwear / last design · dental CAD (crowns/aligners) · orthopedic / prosthetics · hearing aids.

**Soft goods (distinct 2D/developable engine):** apparel / pattern-making + drape · technical textiles / sails / membrane / tensile · upholstery / leather.

**Scientific / niche:** microfluidics / MEMS · signage / large-format.

**Silicon next:** verification depth + post-silicon (cocotb testbench harness, power analysis, STA, clock-tree synthesis, formal equivalence, Tiny Tapeout / Efabless harnesses). T-249..T-258.

**Firmware next:** RTOS primitives, OTA, RTOS-aware debugger, power profiling, pin-map cross-check vs PCB, USB-class drivers. T-259..T-265. **T-274 ✅** — Build / Flash / Monitor UI wired: `FirmwareProjectPanel`, `BuildOutput`, `SerialMonitor` in `src/components/firmware/`; `firmware_project` kind renders in Editor; PlatformIO + Arduino IDE compare rows added.

**Aerospace next:** XFOIL-class viscous solver, aircraft conceptual sizing (Raymer/Roskam), stability derivatives, aero-acoustics (FW-H), heat-shield/ablation, aerospace fasteners. T-266..T-272.

**Platform (demand-gated post-launch):** fully-local / offline / no-account desktop app — committed but not a launch pillar. Portability + two-way sync + easy self-host is the launch answer.

### Strategic AI-native capabilities

These are roadmap-level moats that span every sector simultaneously and compound leverage instead of adding it linearly.

| Capability | Status |
|---|---|
| **Generative / topology / multi-objective optimization** — manufacturing-constrained, multi-load-case, lattice-infill. Basic single-objective SIMP shipped; production-grade unbuilt. | 🚧 in flight |
| **Simulation pillar** — nonlinear FEA, explicit dynamics / crash, fatigue & durability, CFD (full turbulence), low/high-frequency EM, acoustics FEM, coupled multiphysics. Linear-static + modal + steady thermal + linear eigenvalue buckling + harmonic (mode-superposition) frequency response + random-vibration PSD (modal + Miles) + CFD 2-D laminar shipped. **FEA UI panels** ✅ — 5 solve panels (LinearStaticPanel, ModalPanel, BucklingPanel, FatiguePanel, VibrationPanel) wired in right-drawer FEA tab — `src/components/fea/`. | 🚧 in flight |
| **Automatic Feature Recognition (AFR)** — turns any imported "dumb" STEP into an editable parametric feature tree; critical for the LLM to edit any model, not just ones authored in Kerf. | ✅ complete — AAG-based classifier (through-hole, blind-hole, counterbore, countersink, pocket, slot, boss, fillet, chamfer, rib, step) + topology ordering into a replay-able parametric DAG (`afr_to_dag`) + `.feature` log emitter + `afr_to_parametric` LLM tool registered — `kerf-cad-core/afr/recognize.py`, `afr/dag.py`, `geom/feature_recognition.py` |
| **Knowledge-based engineering / code-compliance** — AISC/ACI/Eurocode/ASME/ISO rules driven directly by the model. Shipped: AISC 360-22 + ACI 318-19 + EC2/3/5/8 + NDS 2018 + ASCE 7-22 + ISO 6336 + IAPWS-IF97 + IEEE 1584 + IEC 60255. General KBE configurator layer unbuilt. | 🚧 in flight |
| **3D tolerance / variation analysis** — statistical stack-up + contributor analysis. Shipped: 1D worst-case/RSS/Monte-Carlo + 3D vector-loop 6-DOF Jacobian. Full FEA-coupled variation simulation ahead. | 🚧 in flight |
| **PLM depth** — configurator, 150% / effectivity BOM, where-used, ECR/ECO, digital thread, MBSE/SysML traceability. File revisions + cloud git + configurations + BOM rollup shipped (partial PLM). | 🚧 in flight |
| **Multi-CAD interop & geometry healing** — STEP AP242 / JT / Parasolid / QIF + automatic repair. STEP + JT + Parasolid + QIF + 3DM I/O shipped; body-level geometric heal (vertex weld, sliver-gap close, sub-tolerance edge removal) shipped — `kerf-cad-core/geom/body_heal.py`, `kerf-imports/heal.py`. FEA-grade topology repair for severely degenerate STEP not yet covered. | 🚧 in flight |
| **Reverse-engineering pipeline** — point cloud → segmentation → feature fit → parametric solid. | ✅ shipped — full pipeline: PLY/PCD I/O, outlier removal, sequential-RANSAC segmentation (plane/sphere/cylinder/cone/torus), feature-map classification, ICP mesh registration (dental), **freeform NURBS surface fit from segmented clusters** (centripetal param + P&T §9.2 knots + damped LS; **ordered-grid + adaptive knot refinement shipped** — ordered-grid uses P&T §9.4 row-by-row interpolation for near-exact fit on smooth grids; unordered cloud supports `target_rms` + Boehm knot insertion adaptive loop) — `kerf-cad-core/geom/nurbs_surface_fit.py`, `kerf-cad-core/scan/nurbs_fit_tools.py`. Topology ordering into replay-able parametric DAG remains outstanding. |
| **Mechanism synthesis & motion** — linkage / cam / gear-train *synthesis*. | ✅ shipped — four-bar (Burmester), cam-profile, and gear-train synthesis shipped with reference-oracle tests — `kerf-mates/synthesis/{fourbar,cam,gear_train}.py`. Multi-body dynamic simulation (kerf-motion integrator) also shipped. **Planar MBD UI shipped** — `AssemblyMotionPanel` wires the `simulate_motion` backend tool into the assembly side-panel: joint-list editor (revolute/prismatic/cylindrical), driver input (constant ω, sinusoidal, position-vs-time table), Run button, and timeline scrubber that drives `Renderer.setComponentTransforms` for playback (`src/components/AssemblyMotionPanel.jsx`). |
| **Reverse-engineering pipeline** — point cloud → segmentation → feature fit → parametric solid. | 🚧 in flight — full pipeline shipped: PLY/PCD I/O, outlier removal, sequential-RANSAC segmentation for plane/sphere/cylinder/cone/torus, feature-map classification, ICP mesh registration (dental) — `kerf-cad-core/reverse_engineering/pipeline.py`, `kerf-dental/registration.py`. Topology ordering + freeform NURBS fit deferred (depends on NURBS kernel). |
| **Mechanism synthesis & motion** — linkage / cam / gear-train *synthesis*. | 🚧 in flight — four-bar (Burmester), cam-profile, and gear-train synthesis shipped with reference-oracle tests — `kerf-mates/synthesis/{fourbar,cam,gear_train}.py`. Multi-body dynamic simulation (kerf-motion integrator) also shipped. Assembly motion UI (AssemblyMotionPanel) wired with joint-list editor, Run button, and timeline scrubber. Table-driver inverse-dynamics ✅ — position-vs-time table now drives joints via τ=I·α+c·ω (`kerf-motion/forces.py:table_driver_torque`). |

---

## Genuinely outstanding

*Last verified: 2026-05-26 (status verify-pass against live codebase).* Items that are actually `🔴 not started` or meaningfully incomplete after the pass above.

### Tractable soon (weeks, well-scoped)

- **G-7 caustics + in-browser path-tracer** — Cycles spectral dispersion data (Sellmeier/Abbe) is stashed by the translator but no caustic solver is wired; in-browser WebGPU path-tracer not started.
- ~~**P0-7 bulk import endpoint**~~ — ✅ shipped `POST /api/projects/import` (ZIP archive upload; path-traversal guard + size/count caps + ext→kind mapping).
- **P0-5 viewport integration** — LOD planner and lazy-load ordering are implemented in `assembly/perf.py` but not yet wired to the 3D viewport renderer.
- **P0-7 bulk import endpoint** — `POST /api/projects/import` (ZIP archive upload); workaround (file-by-file) exists; bulk path not yet implemented.
- **P0-5 real-part catalogue** — LOD planner heuristics use synthetic triangle / bbox estimates; wiring to real tessellated part geometry (via `mesh_url` pre-baked buffers) would sharpen tier boundaries for production DMU use.

### Multi-month epics

- **GK-P foundational kernel** — general solid boolean for NURBS-faced bodies; Stam limit-tangents + G1 at extraordinary SubD points; fractional creases; MatchSrf G3; analytic surface derivatives.
- **GK-P construction verbs** — loft guide-rails; sheet-metal hem/jog/multi-flange; direct-edit delete-face + non-planar push-pull; weldment gussets/end-treatments; surface patch-from-points.
- **GK-P SubD / mesh** — multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete). **Auto-detect SubD creases + feature curves ✅** — dihedral-angle classification (Hubeli-Gross 2000 / Botsch-Kobbelt 2003), Otsu threshold recommendation, polyline chaining, end-to-end preprocess pipeline — `kerf-cad-core/geom/subd_auto_detect.py`; LLM tool `subd_auto_classify`.
- **GK-P architectural geometry** — B-rep→2D tessellate; roof/curtain-wall/corridor generators; wall compound-layer offset; hatch/section-fill.
- **GK-P sketcher** — collinear constraint; ellipse solver entity; G2 continuity.
- **GK-P interop** — 3DM write with Hausdorff read→write→read oracle.
- **T-100 FEM depth** — explicit dynamics (module exists, not yet imported/registered); full nonlinear static (only 1-D bar/truss shipped); k-ε turbulence CFD; coupled FEA-based variation analysis. (Acoustics FEM, EM, harmonic, buckling, PSD, multi-axial fatigue are now shipped.)
- **T-101 CFD depth** — RANS turbulence models; 3-D unstructured meshing; OpenFOAM bridge.
- ~~**AFR topology ordering**~~ — ✅ shipped: `afr_to_dag` + `.feature` emitter + `afr_to_parametric` LLM tool in `kerf-cad-core/afr/dag.py`.
- **Reverse-engineering freeform fit** — freeform NURBS surface fit from segmented point clouds; currently only analytic primitives (plane/sphere/cylinder/cone/torus).
- **AFR topology ordering** — promote the AAG feature classifier output into a fully replay-able parametric DAG (depends on NURBS kernel completeness).
- **PLM configurator layer** — 150%/effectivity BOM, where-used, ECR/ECO workflow, MBSE/SysML traceability.
- **KBE general configurator** — rule-driven design configurator layer on top of the existing standard-specific compliance engines.

### Needs UI / deploy-gated

- **P0-8 deploy-hardening** — realistic seed data + one-command dev loop; test coverage breadth still expanding.
- **P1-7 formboard flatten** ✅ — shipped in T-37: `formboard_flatten.py` + `wiring_formboard_flatten` LLM tool; topological unfold with branch alternation, connector pinouts, bbox; waypoints complete ✅ — every branch traversal (including simple two-node stubs) now emits BranchPoint2D for tap AND tip.
- **P1-8 large-file git** — pointer kind + Phase 1 shipped; deduplication-based free-fork accounting and content-addressed LFS store in progress.
- ~~**G-5 class-A wiring**~~ ✅ frontend wiring shipped — see G-5 row above.
- **Long-tail verticals** — see "Long-tail verticals" list above; all committed, none started.

---

## Deliberately not building

This list is only AI-redundant *authoring/UX interaction paradigms* — not skipped domains or correctness features.

| Not building | Why |
|---|---|
| Visual node programming (Grasshopper / Dynamo / Sverchok) | The LLM writing a parametric script *is* the graph. `.script.py` + SDKs + JSCAD + `.graph` cover the value. |
| Ribbon / toolbar maximalism | The LLM is the command palette — discovery is a chat sentence, not a menu hunt. |
| Macro recorders / scripting-GUI builders | The LLM is the macro author; it writes `.script.py` directly. |
| Gumball / direct-modeling maximalism | Keep a basic gumball; the LLM edits the feature tree. |
| In-app wizards / tutorials / onboarding tours | The chat is the wizard — context-specific guidance on demand. |

---

## How to contribute

Pick a task from [`tasks.md`](./tasks.md) (sized for a single isolated agent run), or open an issue proposing a new long-tail sector line. The roadmap states *why* and *in what order*; `tasks.md` is the *how*. Keep them in sync: when a priority moves here, move the corresponding tasks there.
