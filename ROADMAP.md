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

### Latest delta — 2026-05-29

**Civil infrastructure UIs** ✅ — four viewport components wired to kerf-civil backends: `TINView.jsx` (3-D isometric TIN surface, wireframe + contour overlay, dispatches `civil_tin_terrain`); `PipeNetworkView.jsx` (2-D plan view with click-to-inspect pipes, flow/pressure overlay, dispatches `civil_water_network_solve`); `GradingPlanView.jsx` (existing + proposed contour overlay, cut/fill colour bands, dispatches `civil_tin_terrain` volume op); `LandscapeView.jsx` (planting symbols + irrigation zones, dispatches `landscape_plants` + `landscape_irrigation_schedule`) — `src/components/civil/`. Editor shell wired for `.tin`, `.pipe_net`, `.grading`, `.landscape` file kinds. 62 SSR tests pass.

### Previous delta — 2026-05-26
**`cad_component` real geometry substitution** ✅ — Library-mapped components in the CircuitEditor 3D tab now render real geometry instead of indicator chips: JSCAD `model_3d` source is evaluated in-browser; STEP `model_3d_paths` entries are fetched via `/api/projects/:pid/model3d` and parsed via `occt-import-js`. Cache: per-file-id in `fetchCacheRef` (STEP bytes cached by SHA-256 in `stepLoader.js`). `substitute_component` LLM tool registered via `kerf_parts.plugin`; `_try_include` pattern wired in `kerf_api.plugin` — `src/lib/circuitMappings.js`, `src/components/CircuitEditor.jsx`, `packages/kerf-parts/src/kerf_parts/tools.py`, `packages/kerf-api/src/kerf_api/routes_model3d.py`.

### Earlier delta — 2026-05-26
**HVAC design UI** ✅ — Three interactive panels wired to the Editor for `.hvac.load` / `.hvac.duct` / `.hvac.equip` file kinds: `HVACLoadPanel` (ASHRAE CLTD/RTS zone cooling load + degree-day heating, zone breakdown, monthly profile sparklines); `DuctDesignPanel` (velocity-method sizing + Darcy-Weisbach/Colebrook-White pressure drop, material roughness catalogue, 7 ASHRAE fitting types, total system pressure); `EquipmentSelectPanel` (AHU/chiller/boiler/heat-pump with ASHRAE 90.1-2022 minimum-efficiency data, part-load curves). Dispatch via `POST /api/tools/call` with graceful client-side fallback. Compare pages added for Trace 3D Plus / Carrier HAP / IES VE / DesignBuilder — `src/components/hvac/`.

### Previous delta — 2026-05-26
**HVAC AHRI equipment catalogue** ✅ — 30 AHRI-certified models across 6 categories (rooftop AC, split AC, water-cooled chiller, air-cooled chiller, gas boiler, heat pump); 5 representative models per category with real AHRI certification numbers, full-load EER/IEER/COP/AFUE, and AHRI-certified part-load curves at 25/50/75/100% load. `hvac.equipment_select` LLM tool wired; `EquipmentSelectPanel.jsx` dispatches to backend. Source: AHRI Certified Products Directory (https://www.ahridirectory.org). Compare pages for Carrier HAP, IES VE, Trace 3D added — `kerf-hvac/src/kerf_hvac/ahri_catalogue.py`.
### Latest delta — 2026-05-30

**Gauss-Bonnet integrity + chord-deviation reporting** ✅ — `gauss_bonnet_residual(body)` integrates K·dA per face + κ_g·ds per edge + exterior angle defect per vertex and checks against 2π·χ (do Carmo §4.5); `chord_deviation_per_face(body)` computes per-face max/mean chord deviation between surface and its bilinear tessellation + `suggested_subdivision_level` = ⌈log₂(dev/tol)⌉ (Piegl-Tiller §5.4.4); `continuity_audit()` extended with `include_gauss_bonnet` and `include_chord_deviation` flags; `geometry_topology_integrity_check` LLM tool registered; `gauss_bonnet_residual` + `chord_deviation_per_face` exported from `geom/__init__.py` — `kerf-cad-core/src/kerf_cad_core/geom/surface_analysis.py`.

### Latest delta — 2026-05-26
**PV latitude-aware TMY** ✅ — `monthly_yield_factors(latitude_deg)` in `solarpv/tmy.py` returns TMY3-derived (NREL/TP-581-43156) monthly irradiance fractions keyed to latitude band (0°–70°, 10° steps, linearly interpolated); Southern-hemisphere sites automatically receive the seasonally-flipped profile; `POST /energy/pv-shading` endpoint wired to use latitude-aware fractions instead of fixed Northern-Hemisphere constants; `PVShadingPanel` latitude input exposed in UI with hemisphere hint; 29 hermetic tests green.

### Previous delta — 2026-05-26
### Latest delta — 2026-05-30

**ASME B31 pressure-loss + Crane TP-410 K-factors** ✅ — Darcy-Weisbach with Colebrook-White friction factor; 15-entry Crane TP-410 §3 K-factor table (elbows, tees, gate/globe/check/ball/butterfly valves, reducers, expanders); Hooper Two-K method for small-pipe/low-Re accuracy; `compute_pipeline_pressure_drop` for full B31.1/B31.3 pipeline ΔP; LLM tools `piping_pressure_loss` + `piping_pipeline_drop` registered — `packages/kerf-piping/src/kerf_piping/asme_pressure.py`.
### Latest delta — 2026-05-30

**Motion inverse dynamics** ✅ — Recursive Newton-Euler inverse dynamics (Featherstone 2008 §5.3): given joint trajectory θ(t), θ̇(t), θ̈(t) → torques τ(t); `gravity_compensation(robot, q)` static equilibrium; `compute_joint_torques_from_trajectory` vectorised over full trajectories; LLM tools `motion_inverse_dynamics` + `motion_gravity_compensation` registered — `kerf-motion/src/kerf_motion/inverse_dynamics.py`.

### Previous delta — 2026-05-26

**Civil hydraulics** ✅ — LandXML 1.2 import/export (`civil_landxml_import/export`); steady-state pressurised pipe network (Todini GGA + HW/DW, `civil_water_network_solve`); Manning circular/trapezoidal sewer (`civil_sewer_manning_capacity`); rational-method peak runoff (`civil_storm_rational`); HDS-5 inlet-control culvert (`civil_culvert_capacity`) — `kerf-civil/src/kerf_civil/tools_hydraulics.py`.

**Rational drainage method + composite watershed (FHWA HEC-22)** ✅ — Q = C·i·A in US customary (acres/in-hr/cfs); HEC-22 Table 3-1 runoff-coefficient lookup (7 surface types); Kirpich Tc (HEC-22 §3.5); composite weighted-C watershed (HEC-22 §3.3); LLM tools `civil_drainage_rational_method`, `civil_time_of_concentration` — `kerf-civil/src/kerf_civil/drainage.py` + `tools_hydraulics.py`.

**FEM dynamics** ✅ — linear eigenvalue buckling (`fem_buckling_linear`); mode-superposition harmonic frequency response (`fem_harmonic_response`); random-vibration PSD / Miles equation (`fem_random_vibration_psd`); acoustics cavity FEM + BEM radiation; high-frequency EM (waveguide, S-params, FDTD); electrostatics + magnetostatics; 2-D projection Navier-Stokes — `kerf-fem/src/kerf_fem/{buckling,harmonic,random_vibration,acoustics_fem,em_highfreq,em_field,cfd_navier_stokes}.py`.

**Structural codes (AISI + TMS)** ✅ — AISI S100-16 cold-formed steel: effective-width, flexure (`structural_cfs_flexure`), compression (`structural_cfs_compression`), web-crippling (`structural_cfs_web_crippling`); TMS 402-16 masonry ASD: flexure/shear/axial (`structural_masonry_*`) — `kerf-structural/src/kerf_structural/{cold_formed_steel,masonry}.py`.

**G3 surfacing wired** ✅ — `feature_blend_srf_g3` (surfacing.py:1376) + `feature_g3_chain_blend` (surfacing.py:1894) registered as LLM tools via `surfacing` module in `_TOOL_MODULES`; `blend_srf_g3`, `curvature_rate_continuity_residual`, `zebra_stripe`, `reflection_lines`, `curvature_comb` all exported from `geom/__init__.py`; `feature_zebra_analysis` and `feature_isophote_analysis` also wired.

**Structural code design** ✅ — AISC 360-22 (Ch. E/F/H members + connections + base-plate, LRFD+ASD); ACI 318-19 (flexure/shear/PM + punching §22.6 + torsion §22.7); NDS 2018 timber; AISI S100-16 cold-formed steel (effective-width, flexure/compression/web-crippling); TMS 402-16 masonry ASD (flexure/shear/axial); ASCE 7-22 load combos + ELF + RSA/Newmark seismic. Full Eurocode: EC2, EC3, EC5, EC8.

**Native FE** ✅ — MITC4 plate/shell (Bathe-Dvorkin) + modal via inverse iteration; linear eigenvalue buckling + harmonic response + random-vibration PSD; 2D/3D frame stiffness + story drift; multi-axial critical-plane fatigue (Findley, SWT-3D, Brown-Miller); acoustics FEM/BEM + high-frequency EM + electrostatics/magnetostatics; geotech liquefaction triggering (Seed-Idriss/Tokimatsu).

**Machine elements depth** ✅ — ISO 6336 gear rating Method B; ISO/TS 16281 bearing modified life (aISO); planetary gearbox (3 Willis modes + compound); Taylor extended tool-life + Gilbert economics.

**Thermo-fluid depth** ✅ — IAPWS-IF97 steam Regions 1/2/4; Bell-Delaware shell-and-tube HX (TEMA + 5 correction factors); transient pipe-network (MOC waterhammer + surge-tank); ASHRAE CLTD/RTS transient cooling loads.

**Electronics / power depth** ✅ — IBIS-AMI signal integrity (Bergeron + PRBS eye); AC PDN impedance + decap optimiser; Newton-Raphson AC load-flow; IEC 60255 + IEEE C37.112 protection coordination + IEEE 1584-2018 arc-flash; fibre-optic link budget.

**Aero / marine / space depth** ✅ — 3D VLM + viscous strip drag + Prandtl-Glauert/Kármán-Tsien + Korn-Lock wave-drag; strip-theory seakeeping RAOs (Lewis-form + JONSWAP); Holtrop-Mennen resistance + EHP; multi-revolution Lambert (Lancaster-Blanchard/Izzo 2015); hull fairness audit + fair-hull (Lackenby 1950) ✅.
**Aero / marine / space depth** ✅ — 3D VLM + viscous strip drag + Prandtl-Glauert/Kármán-Tsien + Korn-Lock wave-drag; strip-theory seakeeping RAOs (Lewis-form + JONSWAP); Holtrop-Mennen resistance + EHP; multi-revolution Lambert (Lancaster-Blanchard/Izzo 2015); drag-coefficient estimation (Hoerner 1965) ✅ — frontal area + Schultz-Grunow Cf + form-factor; LLM tool `aero_estimate_drag`.

**Manufacturing depth** ✅ — adaptive/trochoidal CAM HSM + rest machining; moldflow Hele-Shaw front tracking + weld-line + air-trap; casting Chvorinov + riser sizing + gating; NFP true-shape polygon nesting (57.6 % L-shape utilisation); parting-line extraction + undercut detection (Ahn-Cho-Kim 2002) ✅.
**Manufacturing depth** ✅ — adaptive/trochoidal CAM HSM + rest machining; moldflow Hele-Shaw front tracking + weld-line + air-trap; casting Chvorinov + riser sizing + gating; NFP true-shape polygon nesting (57.6 % L-shape utilisation). Auto-detect bosses + ribs + moldability score (Boothroyd-Dewhurst 2002) ✅

**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder) + UI parity shipped (CrownSculptingPanel, ImplantLibrary, SurgicalGuide — preset picker, occlusion overlay, filterable Straumann/Nobel/Zimmer/MIS catalogue, CBCT import + pose editor + sleeve preview, all dispatching to kerf-dental backend); Swiss lever escapement + mainspring + balance-wheel; solar PV partial shading + bypass-diode + MPPT; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).
**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder); surgical guide emits milling-ready B-rep + STL export ✅; Swiss lever escapement + mainspring + balance-wheel; solar PV partial shading + bypass-diode + MPPT; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).

**Building/PV UI** ✅ — `BuildingEnergyPanel` (zone-by-zone occupancy/lighting/equipment/infiltration/HVAC editor, EnergyPlus IDF export); `PVShadingPanel` (array layout + obstruction polygons + bypass-diode + MPPT + monthly yield chart); `MonthlyLoadChart` (SVG stacked-bar); `.energy.bldg` / `.energy.pv` / `.energy.load` file kinds wired in Editor.jsx.
**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder); surgical guide watertight single-solid ✅ (`surgical_guide_to_body` — boolean subtract of drill bores from plate, genus-validated); Swiss lever escapement + mainspring + balance-wheel; solar PV partial shading + bypass-diode + MPPT; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).
**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder); Swiss lever escapement + mainspring + balance-wheel; solar PV partial shading + bypass-diode + MPPT + full series IV convolution ✅; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).
**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder); Swiss lever escapement + mainspring + balance-wheel; solar PV partial shading + bypass-diode + MPPT + latitude-aware TMY monthly yield; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).
**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder); Swiss lever escapement + mainspring + balance-wheel; Swiss-lever escapement geometry validation (Daniels 1981) ✅; solar PV partial shading + bypass-diode + MPPT; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).
**Verticals** ✅ — dental anatomic crown (multi-cusp fan, not placeholder); occlusal contact analysis (Okeson 2019) ✅; Swiss lever escapement + mainspring + balance-wheel; solar PV partial shading + bypass-diode + MPPT; analog PVT corner simulation (60 corners + Monte-Carlo mismatch).

**Tolerancing / QA** ✅ — 3D vector-loop tolerance stackup (6-DOF Jacobian); SPC control charts (Shewhart/CUSUM/EWMA + Nelson/WECO); ISO 286 limits & fits.

**Optics / acoustics** ✅ — Gaussian beam (complex-q + ABCD + M² + fibre coupling); non-sequential ray tracing + ghost detection; wave-domain room acoustics (image-source IR + Schroeder RT60 + SEA); Seidel S5 corrected.

**Implicit geometry** ✅ — F-rep CSG (union/intersect/subtract/blend/shell) + domain warps (twist/taper/wave) in `kerf_cad_core.frep.csg`.

**Materials + LCA** ✅ — Ashby database to ~200 materials (14 families) with Pareto-frontier multi-objective selection; full ISO 14040/44 LCA (4 phases, 6 impact categories, Monte-Carlo uncertainty). **Embodied-carbon DB (ICE v3 lookups)** ✅ — `kerf_lca.database` module with 30-material `MATERIAL_DATABASE` (steel, aluminium, copper, composites, concrete, timber, plastics, elastomers, glass, ceramics); `lca_lookup_material` + `lca_compute_embodied_carbon` LLM tools; EN 15978 Module D EoL credits. Data: ICE v3.0, Hammond & Jones, University of Bath, 2019 — NOT Ecoinvent (license-restricted).

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
| **`surface_offset.py`** | NURBS surface offset (Tiller-Hanson 1984 + Hoschek 1988): CP face-normal displacement, iterative isotropic-error refinement, Möller 1997 self-intersection detection, local-loop trim; `nurbs_surface_offset` LLM tool; 4 analytical oracle tests (plane/cylinder/sphere/C-shape) | ✅ shipped |
| **`curve_offset_2d.py`** | NURBS 2D curve offset + self-intersection trim (Tiller-Hanson 1984) — foundation for flat patterns, CAM toolpath offset, hatch fill | ✅ shipped |
| **`coons.py`** | Boundary-interpolation Coons patches, exact to 1e-12 | ✅ shipped |
| **`network_surface.py`** | N-sided patch: N=3 Hosaka-Kimura triangular Coons, N=4 Gregory twist-corrected Coons, N≥5 Wachspress polygon blend; `fairness_metric` bending energy; LLM tool `nurbs_n_sided_patch` | ✅ shipped |
| **`inversion.py`** | Closest-point / point-inversion (Piegl 6.1, analytic partials on rational surfaces) | ✅ shipped |
| **`curve_projection.py`** | Point→curve / point→surface projection (Newton-Raphson + arc-length fallback, Hu-Wallner 2006); `ProjectionResult` dataclass; `distance_curve_to_curve`; LLM tool `nurbs_project_point` | ✅ shipped |
| **`intersection.py`** | Hardened SSI: loop-detection, tangential-branch detection, small-loop guard, analytic specialisations | ✅ shipped |
| **`intersection_degen.py` — Degenerate SSI (Legendre canonical forms)** | `detect_degenerate_ssi` + `compute_degenerate_ssi_curve` + `ssi_extended`; handles coaxial cylinders, coplanar planes, sphere-tangent-plane, Legendre/Weierstrass conic section for tangent quadric pairs; LLM tool `nurbs_ssi_with_degenerate_check` registered; 27 hermetic tests with analytical oracles | ✅ shipped |
| **`geom/history/`** | Parametric history DAG + `feature_id::role::fingerprint` persistent naming — downstream fillet survives upstream parameter edits | ✅ shipped |
| **G3 surfacing** | `feature_blend_srf_g3` (surfacing.py:1376) + `feature_g3_chain_blend` (surfacing.py:1894) registered LLM tools; `blend_srf_g3` / `curvature_rate_continuity_residual` / `zebra_stripe` / `reflection_lines` / `curvature_comb` exported from `geom/__init__.py`; `feature_zebra_analysis` + `feature_isophote_analysis` wired | ✅ shipped |
| **General solid boolean** | NURBS-faced / non-axis-aligned solids; classification-first B-rep pipeline (SSI seeds → whole-face classify → sew); analytic fast-paths for box/sphere/cylinder; LLM tool registered (`nurbs_solid_boolean`); 18 hermetic tests — sphere∩box, Steinmetz, freeform NURBS, self-intersection guard | ✅ shipped |
| **General solid boolean** | NURBS×NURBS solid boolean with exact UV-trim at SSI curves (GK-P-B); whole-face fallback retained for tangential cases; 22 hermetic tests green | ✅ shipped |
| **Body-body imprint with edge tagging** | `imprint_body(target, tool, mode)` in `geom/imprint.py`: projects all tool edges onto target faces via `imprint_curve_on_face`, tags new edges with `ImprintTag(source_body_id, source_edge_id)`. `mode='intersect'` AABB+plane proximity filter; `mode='all'` for design-intent transfer. LLM tool `brep_imprint_body` registered in plugin. 4 oracle tests (box-on-box footprint, provenance coverage, no-intersect no-op, mode comparison). | ✅ shipped |
| **Surface fairing + Sapidis curve fairing** | `surface_fairing.py`: `fair_surface()` (iterative discrete-Laplacian control-net smoothing, 3 boundary modes) + `fair_surface_bend()` (sparse bending-energy linear solve via scipy.sparse); `curve_toolkit.py`: `fair_curve(sapidis=True)` (Sapidis & Farin 1994 iterative knot removal + insertion); LLM tools `surface_fair` + `curve_fair` registered; 19 hermetic tests (σ(z) oracle, boundary preservation, energy-monotone, Sapidis curvature-variance reduction) | ✅ shipped |
| **Variable-radius G2 fillet (Stadler 2006)** | `variable_radius_fillet_g2` + `fillet_radius_field_planner` in `geom/surface_fillet.py`; `nurbs_fillet_variable_g2` LLM tool registered; G2 continuity along radius gradient via cubic Hermite curvature blending; 48 hermetic analytic-oracle-asserted tests | ✅ shipped |
| **GK-P: Variable-section edge blend (Vida-Martin-Varady 1994)** | `edge_blend.py` — `CrossSection` (rect/circle/ellipse/polygon), `variable_section_blend` (linear / cubic_hermite / C2 methods), `morph_cross_sections` (Bezier corner rounding per Hartmann 1998); `nurbs_edge_blend_variable_section` LLM tool registered; exported from `geom/__init__.py`; 37 tests, 4 analytical oracles (volume, rect→circle morph, C1 continuity, volume monotonic) | ✅ shipped |
| **Post-Boolean continuity recovery (G1/G2 seam blending)** | `recover_continuity_at_seam` / `recover_continuity_body` in `geom/continuity_recovery.py`; degree-3 Hermite blend strip inserted at G0-only seams; G1 tangent < 5° + G2 curvature-rate residual oracle; `brep_recover_continuity` LLM tool; 29 hermetic tests green. | ✅ shipped |
| **`geom/wall_thickness.py`** | Wall-thickness analysis with material guidelines — `analyze_wall_thickness` (SDF-ray-cast, Stroud-Nagy §17.2), `material_thickness_guideline` (ABS/PP/PE/PC/Nylon/PVC/…), `flag_thin_walls`; LLM tools `brep_analyze_wall_thickness` + `brep_check_moldability` ✅ | ✅ shipped |
| **GK-P: Mold parting surface construction (Yu-Fan 2003)** | `mold_parting_surface.py`: `construct_parting_surface` (radial ruled quads from parting line to mold bbox), `construct_with_shutoff_inserts` (undercut shutoff patches), `validate_parting_surface`; LLM tool `brep_construct_parting_surface` registered in `kerf-mold`; 22 hermetic oracle tests pass | ✅ shipped |
| **General solid boolean** | NURBS-faced / non-axis-aligned solids (today: axis-aligned only; general CSG delegates to OCCT worker) | 🔴 not started |
| **GK-P: Hollow operator** | Compound feature: shell offset + inner-face blend + inner-edge fillet + port drilling + optional ribs — `hollow_body` / `hollow_with_ribs` in `geom/body_hollow.py`; LLM tool `brep_make_hollow`; 37 analytic-oracle tests green | ✅ shipped |

**GK-P (parity) series in flight.** A four-agent survey of Kerf vs ~18 kernel-relevant CADs found a concrete, finite gap list. GK-01..GK-139 are landed. The `GK-P` series (tracked in `tasks.md`) closes the remaining gaps:

- **Foundational kernel** — general solid boolean for NURBS-faced bodies, MatchSrf G3, isophote/EMap, Stam limit-tangents ✅ + G1 at extraordinary SubD points, fractional creases, analytic surface derivatives.
- **Foundational kernel** — MatchSrf G3, isophote/EMap, Stam limit-tangents + G1 at extraordinary SubD points, fractional creases, analytic surface derivatives. (General solid boolean shipped as GK-P-A.)
- **Foundational kernel** — general solid boolean for NURBS-faced bodies, MatchSrf G3, isophote/EMap, Stam limit-tangents ✅ + G1 at extraordinary SubD points, Stam full Appendix A (12 eigenpatch polynomials) ✅, fractional creases, analytic surface derivatives.
- **Adaptive tessellation LOD chain** ✅ — `kerf_tess.adaptive_lod`: `generate_lod_chain` / `screen_error_to_chord_deviation` / `pick_lod_for_distance`; pinhole-camera screen-error math; 4-level independent mesh chain for three.js `MeshLOD`; `tess_generate_lod_chain` LLM tool registered.
- **Foundational kernel** — general solid boolean for NURBS-faced bodies, MatchSrf G3, isophote/EMap, Stam limit-tangents + G1 at extraordinary SubD points, fractional creases, analytic surface derivatives.
- **Foundational kernel** — general solid boolean for NURBS-faced bodies, MatchSrf G3, isophote/EMap, Stam limit-tangents + G1 at extraordinary SubD points, fractional creases, analytic surface derivatives. **Stam-exact limit normal evaluation** ✅ — `geom/subd_limit_normal.py`; `evaluate_limit_normal` / `evaluate_limit_normal_grid` / `compare_normal_methods`; `subd_evaluate_limit_normal` LLM tool; 15 analytic-oracle tests green (Stam 1998 §3.2).
- **Foundational kernel** — general solid boolean for NURBS-faced bodies, ~~MatchSrf G3~~, isophote/EMap, Stam limit-tangents + G1 at extraordinary SubD points, fractional creases, analytic surface derivatives.
  - **G3 surface match-at-edge (Hoschek-Lasser §14.2)** ✅ — `match_surface_edge_g3` + `elevate_to_g3_capability`; `nurbs_match_surface_g3` LLM tool registered.
- **Construction verbs** — loft guide-rails, sheet-metal hem/jog/multi-flange, direct-edit non-planar + delete-face, weldment gussets/end-treatments, surface patch-from-points.
- **Foundational kernel** — general solid boolean for NURBS-faced bodies, MatchSrf G3, isophote/EMap, Stam limit-tangents + G1 at extraordinary SubD points, fractional creases, analytic surface derivatives.
- **Construction verbs** — ~~loft guide-rails~~ ✅, sheet-metal hem/jog/multi-flange, direct-edit non-planar + delete-face, weldment gussets/end-treatments, surface patch-from-points.
- **SubD / mesh** — multires displacement, SDF CSG + marching-cubes, sculpt brush engine, isotropic remesh, surface-snap retopo, LSCM UV unwrap.
- **SubD / mesh** — multires displacement ✅, SDF CSG + marching-cubes, sculpt brush engine, isotropic remesh, surface-snap retopo, LSCM UV unwrap.
- **SubD / mesh** — multires displacement, SDF CSG + marching-cubes, sculpt brush engine, isotropic remesh, surface-snap retopo, LSCM UV unwrap. Stam-exact limit curvature evaluation ✅.
- **SubD / mesh** — multires displacement, SDF CSG + marching-cubes, sculpt brush engine, isotropic remesh, surface-snap retopo, LSCM UV unwrap. **Geodesic distance via heat method (Crane et al. 2013) ✅** — cotangent Laplacian + Poisson solve; `subd_geodesic_distance` LLM tool wired (GK-P49).
- **SubD / mesh** — multires displacement, SDF CSG + marching-cubes, sculpt brush engine, isotropic remesh, surface-snap retopo, UV unwrap LSCM + ARAP + mesh atlas ✅.
- **SubD / mesh** — multires displacement, SDF CSG + marching-cubes, sculpt brush engine, isotropic remesh, surface-snap retopo, LSCM UV unwrap; **harmonic cage coords ✅** (Joshi 2007).
- **Architectural geometry** — B-rep→2D tessellate, roof/curtain-wall/corridor generators, wall compound-layer offset, hatch/section-fill.
- **Sketcher** — collinear constraint, ellipse solver entity, G2 continuity.
- **Interop** — 3DM write with read→write→read Hausdorff oracle.
- **Composite curve G2 audit + upgrade** ✅ — `composite_g2.py`: audit + auto-blend (cubic Hermite / quintic Bezier); LLM tools registered; 27 tests green.
- **Precise NURBS arc-length (Gauss-Legendre + adaptive subdivision)** ✅ — `arc_length_precise` (5-pt GL + bounded-error recursive bisection, rel_tol/abs_tol contract); `arc_length_parametrize_gauss` (s↔t lookup via bisection on cumulative integral); `reparametrize_arclength_gauss`; LLM tool `nurbs_curve_arc_length`; 13 analytic-oracle tests (straight-line ≤1e-12, circle 2π ≤1e-9, bounded-error, round-trip ±1e-6).

### Mechanical / CAD

- **OCCT `.feature` Phase 2/3** ✅ — Pad/Pocket/Revolve/Hole/Fillet/Chamfer/Shell/Sweep/Loft/Push-Pull/Linear-Polar-Mirror patterns; face/edge gumball.
- **2D sketcher v1 + v2** ✅ — full constraint set, trim/extend, ellipse, B-spline, bezier, fillet, mirror, patterns.
- **Assembly model + 3D mates** ✅ — coincident/concentric/parallel/perp/distance/angle/tangent; gradient-descent solver.
- **Assembly clash detection UI** ✅ — OBB-SAT + BVH + tri-tri backend; Check Clashes side panel with pair list (part A / part B / severity / Jump-to); viewport highlight via `highlightFaces` hook — parity with SOLIDWORKS Interference / Fusion / Onshape clash detection.
- **Assembly clash detection** ✅ — hard/clearance/coincident OBB-SAT + triangle-mesh narrow phase; cross-discipline `by_discipline_pair` summary; real OBB fallback ✅: when a component has no `bbox` but carries a `step_blob` / `step_blob_ref`, a tight PCA-OBB is computed from the STEP geometry and SHA-256 cached — no more 1 mm³ approximation; unit-box fallback retained only when neither bbox nor STEP is available, with an explicit warning in `errors`.
- **Tolerance stack-up** ✅ — worst-case/RSS/Monte-Carlo + auto chain-walk.
- **GD&T frame validation (ASME Y14.5-2018)** ✅ — structural well-formedness per §3.4/§6/§9/§10/§12: symbol–modifier compatibility, datum requirements by tolerance category, duplicate-datum detection, bonus tolerance (MMC/LMC §6.3), canonical string round-trip; `gdt_validate_frame` + `gdt_parse_frame` LLM tools.
- **2D drawings** ✅ — multi-sheet, dimensions, GD&T frames, section hatching, leaders/balloons, centerlines.
- **3D PMI + GD&T annotation UI** ✅ — ISO 1101 GD&T toolbar (DrawingToolbar + GdntToolbar) with all 14 characteristics; datum A/B/C placement; FCF click-to-place modal with tolerance value, diameter zone, material-condition modifier, datum refs; SVG FCF glyphs (FcfGlyph/DatumGlyph) rendered inline per standard; 3D PMI overlay (Pmi3DOverlay) projects FCF labels into the three.js viewport; annotations persist via addFcf/addDatumLabel in the drawing data model.
- **Auto-dim ISO 129-1:2018** ✅ — chain / baseline / mixed dimensioning (§5.1); extension-line gap + overshoot (§5.4); 10 mm line spacing; leader lines at preferred 15° angles (§10); symmetric / unilateral / limit tolerance formats (§8); compliance validator; 2 LLM tools (`drawing_auto_dimension_iso`, `drawing_validate_iso`).
- **Auto 6-view + iso projection (ISO 128-30 / Bertoline 5e)** ✅ — `drawings/projections.py`: `generate_six_view_drawing` (front/back/top/bottom/left/right + iso); third-angle (ANSI/ASME Y14.3) and first-angle (ISO/DIN) layout; hidden-line removal per view via ray-cast depth test; `compute_projection_silhouette`; `drawing_auto_views` LLM tool; standard isometric 120° axis property validated (ISO 5456-3).
- **Section view auto-cutaway + ISO 128-30 hatch** ✅ — `cut_body_with_plane` + `hatch_cross_section` + `section_view_for_drawing`; marching-triangles half-body clipping; iron/concrete/plastic material hatch patterns; cutting-plane marker + Bertoline §11 arrow indicators; LLM tool `brep_section_view`.
- **Measurement chain auto-extraction (ASME Y14.5 + ISO 129)** ✅ — `extract_measurement_chain` generates a complete inspection dimension chain for a B-rep body: A/B/C datum-frame inference (§3.4), per-feature DOF coverage (holes: diameter + depth + 2 position dims), redundancy detection (ISO 129-1 §6 no-closed-chain rule), `generate_inspection_report` in ISO129 or ASME14.5 format; LLM tools `drawing_measurement_chain` + `drawing_inspection_report` wired.
- **2D drawings** ✅ — multi-sheet, dimensions, GD&T frames, section hatching, leaders/balloons, centerlines. NURBS silhouette projection to plane (Hertzmann 2000) ✅ — sign-change grid locus, NURBS curve fit, visible/hidden layer output.
- **NURBS surfacing (Phase 4)** ✅ — sweep1/2/network/blend/loft + `surface_continuity` (C0–C2/G0–G2); surface-direct boolean; trim-by-curve; curvature-comb viz; zebra/reflection-line viewport toggle. G3 *enforcement* on the OCCT side is structurally impossible (absent from OCCT's type system); pure-Python is the G3 path.
- **NURBS surfacing (Phase 4a — jewelry priority)** ✅ — `opSweep2` (two-rail sweep via `BRepFill_PipeShell`-style RMF midline, `sweep2_to_body` in `brep_build.py`), `opNetworkSrf` (Gordon/Coons-Gordon four-curve network, `network_srf_to_body`), `opBlendSrf` (G1/G2 Bezier blend strip, `blend_srf_to_body`); all three registered as LLM tools (`feature_sweep2`, `feature_network_srf`, `feature_blend_srf` in `surfacing.py`); 33 hermetic `validate_body`-clean tests in `test_phase4a_jewelry_surfacing.py`; scenario fixtures in `tests/fixtures/`.
- **Trim-loop auto-heal (T-junctions, dead loops, orientation)** ✅ — UV-domain repair pass: T-junction vertex merge (Sederberg-Zheng-Bakenov-Nasri 2003), dead-loop removal, CCW/CW orientation fix (Eberly shoelace), self-intersection detection; `nurbs_trim_loop_heal` LLM tool; 11 analytic-oracle tests.
- **NURBS seam control for periodic surfaces** ✅ — `detect_seam` / `shift_seam` / `align_seam_to_curve` in `geom/seam_control.py`; `nurbs_shift_seam` LLM tool registered; Piegl-Tiller §5.2 cyclic CP-net rotation with uniform knot rebuild; 16 analytic-oracle tests green.
- **Far-offset numerical conditioning** ✅ — `offset_far_correction.py` (Maekawa 1999 §6; Hoschek-Lasser 1993 §17): curvature-aware safety-distance computation (`safe_offset_distance`), adaptive local-refinement clamp (`offset_with_local_refinement`), graceful degradation with flagged unsafe parametric regions (`graceful_offset`); LLM tool `nurbs_surface_offset_robust` registered.
- **Variable-section extrude / morphing sweep** ✅ — `extrude_variable_section` (profile morphs per path parameter; linear / cubic-Hermite / C2 interpolation; Wang 2008 RMF frames) + `extrude_with_scaling_curve` (1-D scale taper along path) + `extrude_morph_via_rail_pair` (rail-guided profile morph); `nurbs_extrude_variable` LLM tool registered; 17 analytic-oracle tests green (constant-section degenerate, circle→square morph, conical-surface oracle, C2 smoothness).
- **NURBS curve/surface split at parameter** ✅ — `split_curve_at`, `split_curve_at_multiple`, `split_surface_at_u/v`; Piegl–Tiller §5.3 full-multiplicity knot insertion; rational-NURBS correct; LLM tools `nurbs_split_curve` + `nurbs_split_surface` registered (GK-P06).
- **Rhino parity** ✅ — 3DM I/O, SubD (Catmull-Clark), quad remesh, mesh tools, layers/display, parametric `.graph`, render output.
- **Persistent face naming** ✅ — sketch-anchored + topo-hash (frontend T1–T7) plus kernel-side `feature_id::role::fingerprint` selector in the pure-Python DAG.
- **Assembly interference detection (Möller 1997)** ✅ — `detect_interference_pair` / `detect_interference_assembly` / `compute_assembly_aabb`; AABB broad-phase + Möller 1997 triangle-triangle narrow phase + GK-18 boolean intersection volume; severity classification (none/touch/overlap/major_overlap); LLM tools `brep_assembly_interference` + `brep_check_clearance` — `kerf_cad_core/geom/assembly_interference.py`.

### Simulation / manufacturing

- **FEM** ✅ — FEniCSx + CalculiX: linear-static + modal + steady thermal + bonded contact; linear eigenvalue buckling + harmonic frequency response + random-vibration PSD; MITC4 plate/shell; acoustics FEM/BEM; high-frequency EM; electrostatics + magnetostatics; multi-axial fatigue; 2-D projection NS solver. Reference-value suite with Roark/Blevins/Incropera oracles (42 of 43 green).
- **CFD foundation** ✅ — 2-D laminar: potential flow (`Cp(θ)=1−4sin²θ` oracle) + lid-driven cavity (Ghia Re=100 reference); 61 hermetic tests.
- **Topology optimization** ✅ — SIMP via FEniCSx; NURBS surface fit; multi-body.
- **CAM** ✅ — 2.5D + 3D parallel/waterline + lathe + 5-axis constant-tilt + 3+2 indexed; tool DB; LinuxCNC/GRBL/Fanuc posts.
- **5-axis CAM UI** ✅ — `CAMView.jsx` mode switch (3-axis / 5-axis-indexed / 5-axis-continuous); tilt axis (A/B/C) + angle; strategy (swarf / contour-on-tilted-plane / indexed-rough); spindle vector preview; dispatches `cam_run` backend tool (`operation=5axis_finish` or `3plus2`).
- **Slicing** ✅ — plane-section, CNC layered, 3D-print G-code (Cura, Tier 1).
- **HVAC duct pressure loss — ASHRAE §35 fittings** ✅ — ASHRAE Handbook of Fundamentals 2021 §35 (Ch. 21) Table 21-1 fitting loss coefficients: 10 fitting kinds (smooth/segmented elbows, 45° elbow, tee branch/through, gradual/abrupt transitions, butterfly damper, gradual reducer/expander); `fitting_pressure_loss()` + `compute_duct_run_pressure_drop()` (straight-duct + fittings combined); `build_loss_table()` with full ASHRAE citations; 2 new LLM tools (`hvac.fitting_pressure_loss`, `hvac.compute_run_pressure_drop`).
- **Slicing** ✅ — plane-section, CNC layered, 3D-print G-code (Cura, Tier 1); infill pattern library (gyroid TPMS, honeycomb, triangular grid, concentric) ✅.
- **1D system simulation (kerf-1dsim)** ✅ — Modelica-compatible equation-based DAE solver (BDF-1); R/L/C/MassSpring/Damper/ThermalConductor/FluidResistor components; **Modelica .mo import** ✅ — recursive-descent subset parser: `model/end`, `parameter Real`, `Real`, `equation`, `der()`, `connect()`, `package` wrapping; `modelica_to_kerf_components` mapper; `load_modelica_library` directory scan; `sim_import_modelica` LLM tool registered. *Modelica subset support — NOT certified Modelica compliance.*

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
- **Silicon / IBIS 7.1 signal integrity** ✅ — IBIS 7.1 model import + eye-diagram estimation (`silicon_import_ibis`, `silicon_eye_diagram`); [Component]/[Pin]/[Model]/[Pulldown]/[Pullup]/[GND_clamp]/[POWER_clamp]/[Ramp]/[Voltage Range]; IV-curve interpolation; analytical eye opening height/width/jitter at arbitrary bit-rate + load. NOT IBIS-certified.
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
| **T-100** | **FEM matching CalculiX / Z88 / Mystran depth** — buckling + harmonic + PSD + acoustics + EM + fatigue + **explicit dynamics ✅** + **3-D nonlinear static ✅** (`kerf-fem/nonlinear_static.py`; H8 B-bar, Total-Lagrangian, J2+A-F plasticity, Crisfield arc-length, 33 tests) shipped; remaining: k-ε turbulence, coupled variation, EAS modes (T-100-C). | Serious simulation work. | 🚧 in flight |
| **T-100** | **FEM matching CalculiX / Z88 / Mystran depth** — buckling + harmonic + PSD + acoustics + EM + fatigue + explicit dynamics + nonlinear static + k-ε turbulence + coupled-field probabilistic FEA (LHS + Karhunen-Loève) ✅ — all sub-tasks shipped. | Serious simulation work. | ✅ shipped — `kerf-fem/coupled_variation.py`: `LatinHypercubeSampler`, `KarhunenLoeveExpansion`, `propagate_uncertainty`, `fem_propagate_uncertainty` LLM tool |
| **T-101** | **CFD (CfdOF-class)** — turbulence models, 3-D unstructured meshing, OpenFOAM bridge beyond the 2-D laminar foundation. | Fluid and aero simulation. | 🚧 in flight |
| **Hosted infra** | **Cloud infrastructure** — engine on Fly.io (`fra` Frankfurt, co-located with the DB, `shared-cpu-2x` / 2 GB), Neon Postgres (`eu-central-1`), Cloudflare R2 blobs (zero egress), Resend email. GPU renders via RunPod Serverless (L4→H100, scale-to-zero) — `GPUBackend` protocol + `RunPodGPUBackend` (submit/poll/fetch_result/capabilities, auth, retry/backoff) + `SelfHostedWorkerBackend` (BYO) all shipped; GPU worker dispatch foundation + BYO worker enrollment shipped (`POST /api/workers/enroll`, heartbeat, claim-job, complete + billing skip; Settings → Workers tab). See `deployment/fly.md`. | Stable pay-as-you-go stack; BYO workers run at zero credit cost; managed RunPod path now live. | ✅ shipped — see `packages/kerf-render/src/kerf_render/gpu_backend.py` |
| **GPU worker dispatch + BYO worker CLI** | **`kerf-worker` companion CLI shipped** — `pip install kerf-worker`; `kerf-worker enroll/run/status/revoke`; NVIDIA GPU probing via `nvidia-smi`; heartbeat every 30 s; long-poll claim-job with `cycles_render` (Blender) + `fem_solve` (CalculiX) dispatch; BYO billing short-circuit (`billing_bucket='byo'` → no credits charged). **SIGNED-UPLOAD-URL shipped** — claim-job returns `signed_upload_url` (presigned S3/R2 PUT, 90-min TTL), `result_key` (`worker-results/{job_id}.bin`), `result_ttl_seconds`; `/complete` accepts `result_key` (storage.head verification, no bytes through API) alongside legacy `signed_url`; `Storage.signed_put_url` + `Storage.head` added to base ABC, S3Storage, LocalStorage (`local://` fallback). `packages/kerf-worker/` — 4 commands, 8 hermetic tests. | Users on paid plans can register their own GPU hardware to run render/FEM jobs at zero credit cost. Delivers on the BYO-key billing tier promise. | ✅ shipped — `packages/kerf-worker/src/kerf_worker/` |
| **T-101** | **CFD (CfdOF-class)** — turbulence models, 3-D unstructured meshing, OpenFOAM bridge beyond the 2-D laminar foundation. **T-101-A k-ε RANS shipped ✅** (`kerf-cfd/rans_keps.py`; Launder-Spalding 1974; channel Re=10 000 + BFS validated; LLM tool `cfd_rans_keps_solve` registered). Remaining: 3-D unstructured meshing (4L), OpenFOAM bridge depth (4M). | Fluid and aero simulation. | 🚧 in flight |
| **T-100** | **FEM matching CalculiX / Z88 / Mystran depth** — buckling + harmonic + PSD + acoustics + EM + fatigue shipped; remaining: explicit dynamics, full nonlinear static, k-ε turbulence, coupled variation. | Serious simulation work. | 🚧 in flight |
| **T-101** | **CFD (CfdOF-class)** — turbulence models, 3-D unstructured meshing, OpenFOAM bridge beyond the 2-D laminar foundation. | Fluid and aero simulation. | 🚧 in flight — T-101-A k-ε ✅; T-101-B 3-D tet meshing ✅; T-101-C OpenFOAM bridge ✅ (`write_case`, `write_polymesh`, `read_results`→`ResultBundle`, `cfd_openfoam_export` + `cfd_openfoam_import` LLM tools, 76 tests) |
| **T-100** | **FEM matching CalculiX / Z88 / Mystran depth** — buckling + harmonic + PSD + acoustics + EM + fatigue shipped; remaining: explicit dynamics, full nonlinear static, k-ε turbulence, coupled variation. | Serious simulation work. | 🚧 in flight |
| **T-101** | **CFD (CfdOF-class)** — turbulence models, 3-D unstructured meshing, OpenFOAM bridge beyond the 2-D laminar foundation. | Fluid and aero simulation. | 🚧 in flight — 3-D unstructured mesh ✅ (`mesh_unstructured.py`: scipy Delaunay core, Fibonacci-sphere surface sampling, structured O-grid pipe, Voronoi dual, quality flags, octree refinement; `cfd_mesh_unstructured` LLM tool registered; 27 tests green) — T-101-C OpenFOAM bridge remaining |
| **Hosted infra** | **Cloud infrastructure** — engine on Fly.io (`fra` Frankfurt, co-located with the DB, `shared-cpu-2x` / 2 GB), Neon Postgres (`eu-central-1`), Cloudflare R2 blobs (zero egress), Resend email. GPU renders via RunPod Serverless (L4→H100, scale-to-zero) — dispatch seam exists; `RunPodGPUBackend` planned. See `deployment/fly.md`. | Stable pay-as-you-go stack with engine co-located with the database; GPU render prices 2-3× below previous estimates when RunPod backend ships. | 🚧 in flight — stack settled; RunPod GPU backend remaining |

---

## Planned next

### Depth gaps (concrete, near-term)

| # | Gap | vs | Status |
|---|---|---|---|
| G-3 | **Interactive push-and-shove diff-pair tuning** — full diff-pair routing, length-skew tuning, and push-shove | KiCad / Altium | ✅ shipped — `route_diff_pair` + `tune_diff_pair_skew` + `validate_diff_pair` + `push_shove_segment` — `kerf-electronics/routing/push_shove.py` |
| G-4 | **Broader ECAD import** — Allegro / PADS / gEDA / Eagle v10 | Altium / Cadence | ✅ shipped — four dedicated readers with tests — `kerf-imports/src/kerf_imports/{allegro_reader,pads_reader,geda_reader,eagle_reader}.py` |
| G-5 | **Kernel G3 / class-A leading** — wired G3 blends + curvature-comb + imprint | Alias / ICEM Surf | ✅ frontend wiring shipped — Class-A viewport toggle (Render menu → "Class-A": zebra stripes + G2/G3 per-edge audit panel) + ImprintCurve inspector entry in FeatureView; backend `feature_global_continuity_audit` + `edge_continuity_report` + `imprint_curve_on_face` all pre-existing |
| G-6 | **SubD authoring with creases + edit workflow** | Rhino 8 SubD | ✅ shipped — cage creation/extrude/bevel/loop-cut/slide/crease/bevel-weight + Catmull-Clark evaluation — `kerf-cad-core/geom/subd_authoring.py` |
| G-5 | **Kernel G3 / class-A leading** — wired G3 blends + curvature-comb + imprint | Alias / ICEM Surf | 🚧 in flight |
| G-6 | **SubD authoring with creases + edit workflow** | Rhino 8 SubD | ✅ shipped — cage creation/extrude/bevel/loop-cut/slide/crease/bevel-weight + Catmull-Clark evaluation — `kerf-cad-core/geom/subd_authoring.py`; **GK-P SubD parity**: Loop (1987) triangle subdivision, Modified Butterfly (Zorin-Schroder-Sweldens 1996) interpolating, Doo-Sabin (1978) face-based, CC sharp creases/corners/darts/variable-sharpness ✅ — `geom/{loop_subdivide,modified_butterfly,doo_sabin}.py` + `geom/subd.py` |
| GK-P | **SubD feature curves with continuous sharpness** — designer polylines that propagate through subdivision levels independently from hard creases; sharpness ∈ [0,∞) spectrum (Biermann-Levin-Zorin 2000 / DeRose-Kass-Truong 1998 §4); auto-detect by dihedral; `subd_make_feature_curve` LLM tool | Rhino 8 SubD / Maya SubD | ✅ shipped — `kerf-cad-core/geom/subd_feature_curves.py` |
| G-5 | **Kernel G3 / class-A leading** — wired G3 blends + curvature-comb + imprint | Alias / ICEM Surf | 🚧 in flight |
| G-6 | **SubD authoring with creases + edit workflow** | Rhino 8 SubD | ✅ shipped — cage creation/extrude/bevel/loop-cut/slide/crease/bevel-weight + Catmull-Clark evaluation — `kerf-cad-core/geom/subd_authoring.py`; SubD → NURBS conversion via Loop-Schaefer 2008 (exact Stam basis for regular faces, bicubic LS fit for extraordinary vertices, `subd_to_nurbs_schaefer` LLM tool) — `kerf-cad-core/geom/subd_to_nurbs.py` |
| GK-P | **SubD smooth edge-loop insertion** — insert a new edge loop at parameter t using CC limit-preserving vertex positions (Loop-Schaefer 2008 bicubic weights); quad face splits; `limit_surface_diff` spatial oracle; `subd_insert_edge_loop` LLM tool | Maya / Modo Add Edge Loop | ✅ shipped — `kerf-cad-core/geom/subd_smooth_insert.py`, `subd_tools.py` |
| G-5 | **Kernel G3 / class-A leading** — wired G3 blends + curvature-comb + imprint | Alias / ICEM Surf | 🚧 in flight |
| G-6 | **SubD authoring with creases + edit workflow** | Rhino 8 SubD | ✅ shipped — cage creation/extrude/bevel/loop-cut/slide/crease/bevel-weight + Catmull-Clark evaluation — `kerf-cad-core/geom/subd_authoring.py`; SubD boundary→curve snap ✅ — `geom/subd_boundary_replace.py` |
| G-6b | **SubD mirror symmetry detect + enforce** | Rhino 8 / Maya / Blender SubD symmetry | ✅ shipped — `detect_mirror_symmetry` (score-based, Podolak 2006), `enforce_mirror_symmetry`, `mirror_edit`; 2 LLM tools (`subd_detect_symmetry`, `subd_enforce_symmetry`) — `kerf-cad-core/geom/subd_symmetry.py` |
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

**Soft goods (distinct 2D/developable engine):** apparel / pattern-making + drape · technical textiles / sails / membrane / tensile · upholstery / leather. *(ARAP/LSCM pattern flattening for non-developable surfaces (Bo-Wang 2007 / Lévy 2002) ✅ — `kerf-apparel/pattern_flatten.py`, `apparel_flatten_pattern` LLM tool wired.)*
**Soft goods (distinct 2D/developable engine):** apparel / pattern-making + drape · technical textiles / sails / membrane / tensile · upholstery / leather. *(ASTM D5219 + ISO 8559 grading rules ✅ — `GradingRule`, `build_grading_table`, `apply_grading`, `grade_check_iso_8559` shipped; `apparel_apply_grading` + `apparel_grade_check` LLM tools registered — `packages/kerf-apparel/src/kerf_apparel/grading.py`.)*

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
| **Simulation pillar** — nonlinear FEA, explicit dynamics / crash, fatigue & durability, CFD (full turbulence), low/high-frequency EM, acoustics FEM, coupled multiphysics. Linear-static + modal + steady thermal + linear eigenvalue buckling + harmonic (mode-superposition) frequency response + random-vibration PSD (modal + Miles) + CFD 2-D laminar shipped. | 🚧 in flight |
| **Automatic Feature Recognition (AFR)** — turns any imported "dumb" STEP into an editable parametric feature tree; critical for the LLM to edit any model, not just ones authored in Kerf. | 🚧 in flight — AAG-based classifier (through-hole, blind-hole, counterbore, countersink, pocket, slot, boss, fillet, chamfer, rib, step) shipped with tests; full topology ordering into a replay-able parametric tree is the remaining step — `kerf-cad-core/afr/recognize.py`, `geom/feature_recognition.py` |
| **Knowledge-based engineering / code-compliance** — AISC/ACI/Eurocode/ASME/ISO rules driven directly by the model. Shipped: AISC 360-22 + ACI 318-19 + EC2/3/5/8 + NDS 2018 + ASCE 7-22 + ISO 6336 + IAPWS-IF97 + IEEE 1584 + IEC 60255. **General KBE rule engine ✅** — forward-chaining `KBEEngine` with conflict resolution (confidence-ranked), 10-rule starter pack (structural/mechanical/electrical/plumbing), `kbe_apply_rules` LLM tool — `kerf-rules/kbe.py`. | 🚧 in flight |
| **Knowledge-based engineering / code-compliance** — AISC/ACI/Eurocode/ASME/ISO rules driven directly by the model. Shipped: AISC 360-22 + ACI 318-19 + EC2/3/5/8 + NDS 2018 + ASCE 7-22 + ISO 6336 + IAPWS-IF97 + IEEE 1584 + IEC 60255 + ASME B31.1/B31.3 pipeline pressure-loss (Darcy-Weisbach + Crane TP-410 K-factors). General KBE configurator layer unbuilt. | 🚧 in flight |
| **3D tolerance / variation analysis** — statistical stack-up + contributor analysis. Shipped: 1D worst-case/RSS/Monte-Carlo + 3D vector-loop 6-DOF Jacobian. Full FEA-coupled variation simulation ahead. | 🚧 in flight |
| **PLM depth** — configurator, 150% / effectivity BOM, where-used, ECR/ECO, digital thread, MBSE/SysML traceability. File revisions + cloud git + configurations + BOM rollup shipped (partial PLM). Configurator ✅ (kerf-plm): rule-based `Configurator` + `effectivity_bom` + `plm_configure` LLM tool shipped; ECR/ECO + MBSE/SysML traceability ahead. | 🚧 in flight |
| **PLM depth** — configurator, 150% / effectivity BOM, where-used, ECR/ECO, digital thread, MBSE/SysML traceability. File revisions + cloud git + configurations + BOM rollup shipped. Rule-based product configurator (PLM-A) ✅, 150% BOM + where-used ✅, ECR/ECO workflow (ISO 10007) ✅ (`kerf_plm.change_management` — ChangeBoard, ECR, ECO, audit trail, effectivity propagation), SysML traceability ✅ (`kerf_cloud.plm.sysml_trace`). Digital thread / MBSE integration ahead. | 🚧 in flight |
| **Knowledge-based engineering / code-compliance** — AISC/ACI/Eurocode/ASME/ISO rules driven directly by the model. Shipped: AISC 360-22 + ACI 318-19 + EC2/3/5/8 + NDS 2018 + ASCE 7-22 + ISO 6336 + IAPWS-IF97 + IEEE 1584 + IEC 60255. General KBE forward-chaining engine shipped (`kerf-rules/kbe.py`). KBE↔configurator bridge ✅ (`kbe_bridge.py`). | 🚧 in flight |
| **3D tolerance / variation analysis** — statistical stack-up + contributor analysis. Shipped: 1D worst-case/RSS/Monte-Carlo + 3D vector-loop 6-DOF Jacobian. Full FEA-coupled variation simulation ahead. | 🚧 in flight |
| **PLM depth** — configurator, 150% / effectivity BOM, where-used, ECR/ECO, digital thread, MBSE/SysML traceability. File revisions + cloud git + configurations + BOM rollup shipped (partial PLM). Variant configurator + KBE↔configurator bridge ✅ (`kerf-plm`: `configurator.py`, `kbe_bridge.py`; ECO effectivity, conflict detection, `plm_kbe_configure` LLM tool). Where-used, MBSE/SysML traceability remain. | 🚧 in flight |
| **Knowledge-based engineering / code-compliance** — AISC/ACI/Eurocode/ASME/ISO rules driven directly by the model. Shipped: AISC 360-22 + ACI 318-19 + EC2/3/5/8 + NDS 2018 + ASCE 7-22 + ISO 6336 + IAPWS-IF97 + IEEE 1584 + IEC 60255. General KBE configurator layer unbuilt. | 🚧 in flight |
| **3D tolerance / variation analysis** — statistical stack-up + contributor analysis. Shipped: 1D worst-case/RSS/Monte-Carlo + 3D vector-loop 6-DOF Jacobian + FEA-coupled probabilistic variation (LHS + Karhunen-Loève). | ✅ shipped |
| **PLM depth** — configurator, 150% / effectivity BOM, where-used, ECR/ECO, digital thread, MBSE/SysML traceability. File revisions + cloud git + configurations + BOM rollup shipped (partial PLM). | 🚧 in flight |
| **PLM depth** — configurator, 150% / effectivity BOM, where-used, ECR/ECO, digital thread, MBSE/SysML traceability. File revisions + cloud git + configurations + BOM rollup shipped (partial PLM). MBSE digital thread (SysML 1.x XMI + traceability) ✅ — `packages/kerf-plm/src/kerf_plm/sysml.py`; LLM tools: `sysml_trace_coverage`, `sysml_export_xmi`, `sysml_import_xmi`. Remaining: configurator UI, 150% BOM, where-used, ECR/ECO workflow. | 🚧 in flight |
| **Multi-CAD interop & geometry healing** — STEP AP242 / JT / Parasolid / QIF + automatic repair. STEP + JT + Parasolid + QIF + 3DM I/O shipped; body-level geometric heal (vertex weld, sliver-gap close, sub-tolerance edge removal) shipped — `kerf-cad-core/geom/body_heal.py`, `kerf-imports/heal.py`. FEA-grade topology repair for severely degenerate STEP not yet covered. | 🚧 in flight |
| **Reverse-engineering pipeline** — point cloud → segmentation → feature fit → parametric solid. | ✅ shipped — full pipeline: PLY/PCD I/O, outlier removal, sequential-RANSAC segmentation (plane/sphere/cylinder/cone/torus), feature-map classification, ICP mesh registration (dental), **freeform NURBS surface fit from segmented clusters** (centripetal param + P&T §9.2 knots + damped LS; **ordered-grid + adaptive knot refinement shipped** — ordered-grid uses P&T §9.4 row-by-row interpolation for near-exact fit on smooth grids; unordered cloud supports `target_rms` + Boehm knot insertion adaptive loop) — `kerf-cad-core/geom/nurbs_surface_fit.py`, `kerf-cad-core/scan/nurbs_fit_tools.py`. Topology ordering into replay-able parametric DAG remains outstanding. |
| **Mechanism synthesis & motion** — linkage / cam / gear-train *synthesis*. | ✅ shipped — four-bar (Burmester), cam-profile, and gear-train synthesis shipped with reference-oracle tests — `kerf-mates/synthesis/{fourbar,cam,gear_train}.py`. Multi-body dynamic simulation (kerf-motion integrator) also shipped. **Planar MBD UI shipped** — `AssemblyMotionPanel` wires the `simulate_motion` backend tool into the assembly side-panel: joint-list editor (revolute/prismatic/cylindrical), driver input (constant ω, sinusoidal, position-vs-time table), Run button, and timeline scrubber that drives `Renderer.setComponentTransforms` for playback (`src/components/AssemblyMotionPanel.jsx`). |
| **PLM depth** — configurator, 150% / effectivity BOM, where-used, ECR/ECO, digital thread, MBSE/SysML traceability. File revisions + cloud git + configurations + BOM rollup shipped (partial PLM). | 🚧 in flight |
| **Multi-CAD interop & geometry healing** — STEP AP242 / JT / Parasolid / QIF + automatic repair. STEP + JT + Parasolid + QIF + 3DM I/O shipped; body-level geometric heal (vertex weld, sliver-gap close, sub-tolerance edge removal) shipped — `kerf-cad-core/geom/body_heal.py`, `kerf-imports/heal.py`. **B-rep heal + inertia queries ✅ (industrial-class)** — `kerf-cad-core/geom/brep_heal.py` ships the full OCCT ShapeFix-equivalent pipeline: tolerant crack-stitch (Weiler 1985), kd-tree vertex merge, non-manifold T-junction split, planar/Coons hole fill, BFS normal unification, plus volume / surface-area / centroid / inertia-tensor queries (Eberly 1999 divergence theorem). LLM tools `brep_heal` + `brep_compute_inertia` registered. Oracle: unit-cube I_xx = 1/6 within 0.01%. | ✅ shipped |
| **Multi-CAD interop & geometry healing** — STEP AP242 / JT / Parasolid / QIF + automatic repair. STEP + JT + Parasolid + QIF + 3DM I/O shipped; body-level geometric heal (vertex weld, sliver-gap close, sub-tolerance edge removal) shipped — `kerf-cad-core/geom/body_heal.py`, `kerf-imports/heal.py`. **STEP import auto-heal pipeline ✅** — `read_step(auto_heal=True)` runs `heal_body` on each imported body, returning `StepReadResult` with per-body `HealStats`; `step_import_brep` LLM tool wired (`kerf-cad-core/io/step_import_tool.py`); backward-compat preserved (auto_heal=False returns plain Body). FEA-grade topology repair for severely degenerate STEP not yet covered. | 🚧 in flight |
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

- **GK-P foundational kernel** — general solid boolean for NURBS-faced bodies; Stam limit-tangents ✅ + G1 at extraordinary SubD points; fractional creases; MatchSrf G3; analytic surface derivatives.
- **GK-P foundational kernel** — ✅ general solid boolean shipped (GK-P-A); remaining: Stam limit-tangents + G1 at extraordinary SubD points; fractional creases; MatchSrf G3; analytic surface derivatives.
- **GK-P Bezier extraction** ✅ — B-spline → multi-Bezier patch decomposition (Piegl & Tiller §5.6); foundational for FEA tet-mesh handoff, GPU-friendly rendering, IGES export. (`bezier_extract.py`, LLM tool `bezier_extract` registered.)
- **GK-P reparametrisation** — Reparametrization (chord-length + centripetal + Foley-Nielsen) ✅ — `geom/reparam.py`; `fit_curve`/`fit_surface` accept `parameterisation` kwarg; LLM tool `nurbs_reparametrize` registered (Piegl-Tiller §9.2.2).
- **GK-P non-manifold detection + repair** ✅ — `detect_non_manifold` / `repair_non_manifold` for B-rep bodies (T-junction edges, touching-cone vertices, self-intersecting loops) and mesh equivalents; `brep_non_manifold_check` + `brep_non_manifold_repair` LLM tools; `heal_body(repair_non_manifold=True)` integration. (Weiler 1985 / Sheffer-Hart 2002.)
- **GK-P curve lifting** — Curve lifting (2D-loop → 3D-on-surface + inverse) ✅ — `geom/curve_lifting.py`: `lift_curve_to_surface`, `lift_curve_with_arc_length`, `project_3d_curve_to_surface_uv`; LLM tool `nurbs_curve_lift_to_surface`; 14 analytic-oracle tests (P&T §10.3.1).
- **GK-P shell-offset operator** ✅ — shell-offset operator (constant thickness + fillet propagation): `shell_offset_body`, `detect_shell_self_intersection`, `shell_with_open_face`; `brep_shell_body` LLM tool; 47 tests green.
- **GK-P foundational kernel** — general solid boolean for NURBS-faced bodies; Stam limit-tangents + G1 at extraordinary SubD points; fractional creases; MatchSrf G3; analytic surface derivatives.
  - **Degree raise + lower (Cohen-Lyche-Schumaker 1985)** ✅ — `degree_raise_curve`, `degree_raise_surface`, `degree_lower_curve`, `degree_lower_surface`, `elevate_to_match`; LLM tools `nurbs_degree_raise` + `nurbs_degree_lower` registered; 15 hermetic tests (eval exact to 1e-12, CLS Bezier oracle, surface 10×10 grid, round-trip 3→5→3).
- **GK-P foundational kernel** — general solid boolean for NURBS-faced bodies; Stam limit-tangents + G1 at extraordinary SubD points; fractional creases; ~~MatchSrf G3~~ ✅; analytic surface derivatives.
- **GK-P construction verbs** — loft guide-rails; sheet-metal hem/jog/multi-flange; direct-edit delete-face + non-planar push-pull; weldment gussets/end-treatments; surface patch-from-points.
- **GK-P foundational kernel** — general solid boolean for NURBS-faced bodies; Stam limit-tangents + G1 at extraordinary SubD points; fractional creases; MatchSrf G3; analytic surface derivatives.
- **GK-P construction verbs** — ~~loft guide-rails~~ ✅ (`loft_with_rails`, Gordon surface, N rails, GK-P-D); sheet-metal hem/jog/multi-flange; direct-edit delete-face + non-planar push-pull; weldment gussets/end-treatments; surface patch-from-points.
- **GK-P construction verbs** — loft guide-rails; sheet-metal hem/jog/multi-flange; direct-edit delete-face + non-planar push-pull; weldment gussets/end-treatments; surface patch-from-points. Direct-edit constrained push-pull + partial face replace ✅ (GK-P18 extension, 2026-05-30).
- **GK-P parting-line extraction** ✅ — B-rep parting-line (Ahn-Cho-Kim 2002): face classification top/bottom/side; edge-adjacency parting-edge detection; loop tracing; undercut detection; optimal-pull-direction Fibonacci search. LLM tools: `brep_parting_line`, `brep_detect_undercuts`, `brep_optimal_pull_direction`.
  - **Variable rail-tangent Gordon loft (Piegl-Tiller §10.4.3)** ✅ — `loft_with_rails_variable` / `extract_rail_tangents` / `validate_rail_tangent_compatibility` in `geom/loft_rails_variable.py`; LLM tool `nurbs_loft_with_rails_variable` registered.
- **GK-P SubD / mesh** — multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete).
- **GK-P SubD / mesh** — multires displacement ✅; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete).
- **GK-P SubD / mesh** — Loop + Mod-Butterfly + Doo-Sabin + CC creases/corners/darts ✅; multires displacement ✅; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete).
- **GK-P SubD / mesh** — ~~SubD feature curves with continuous sharpness~~ ✅ shipped; multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete).
- **GK-P SubD / mesh** — multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete). SubD → NURBS conversion (Loop-Schaefer 2008) ✅ — `kerf-cad-core/geom/subd_to_nurbs.py`; exact Stam CC basis for regular faces, LS bicubic fit for extraordinary vertices, `subd_to_nurbs_schaefer` LLM tool wired.
- **GK-P SubD / mesh** — SubD-cage boolean (transversal case, Cohen-Or-Sheffer 2003) ✅; multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete).
- **GK-P SubD / mesh** — multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete). **Auto-detect SubD creases + feature curves ✅** — dihedral-angle classification (Hubeli-Gross 2000 / Botsch-Kobbelt 2003), Otsu threshold recommendation, polyline chaining, end-to-end preprocess pipeline — `kerf-cad-core/geom/subd_auto_detect.py`; LLM tool `subd_auto_classify`.
- **GK-P SubD / mesh** — multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete); SubD boundary→curve snap ✅ shipped.
- **GK-P SubD / mesh** — multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete). Mirror-symmetry detect + enforce ✅ shipped (`subd_symmetry.py`).
- **GK-P SubD / mesh** — multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete); **geodesic distance heat method ✅** (GK-P49).
- **GK-P SubD / mesh** — multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete); **SubD deformation cage with mean-value coords (Ju 2005) ✅** — `kerf-cad-core/geom/subd_deform.py`, LLM tool `subd_deform_with_cage`.
- **GK-P SubD / mesh** — multires displacement; SDF CSG + marching-cubes; sculpt brush engine; UV unwrap with LSCM + ARAP + mesh atlas (Sheffer 2006) ✅ (`geom/uv_unwrap.py`, `brep_uv_unwrap` + `brep_uv_distortion_report` LLM tools, GK-P58).
- **GK-P SubD / mesh** — multires displacement; SDF CSG + marching-cubes; sculpt brush engine; LSCM UV unwrap (module exists, wiring incomplete); **Harmonic coordinates for cage deformation (Joshi 2007) ✅** — `kerf-cad-core/geom/subd_harmonic.py`; `subd_harmonic_coords` LLM tool registered; non-negativity + partition-of-unity oracles verified.
- **GK-P architectural geometry** — B-rep→2D tessellate; roof/curtain-wall/corridor generators; wall compound-layer offset; hatch/section-fill.
- **GK-P sketcher** — collinear constraint; ellipse solver entity; G2 continuity.
- **GK-P interop** — 3DM write with Hausdorff read→write→read oracle.
- **T-100 FEM depth** — explicit dynamics ✅ shipped (`kerf_fem/explicit_dynamics.py`); full nonlinear static (only 1-D bar/truss shipped); k-ε turbulence CFD; coupled FEA-based variation analysis. (Acoustics FEM, EM, harmonic, buckling, PSD, multi-axial fatigue, explicit dynamics are now all shipped.)
- **T-100 FEM depth** ✅ EPIC CLOSED — all sub-tasks shipped: explicit dynamics, full nonlinear static (geometric + material + contact + arc-length), k-ε turbulence CFD, coupled-field probabilistic FEA (LHS + Karhunen-Loève), plus acoustics FEM, EM, harmonic, buckling, PSD, multi-axial fatigue.
- **Composite curve G2 audit + upgrade** ✅ — `composite_g2.py`: `audit_composite_g2` (per-joint G0/G1/G2 residuals), `upgrade_to_g2` (cubic Hermite / quintic Bezier blend insertion), `composite_curvature_profile` (κ(s) statistics + jump detection); LLM tools `nurbs_composite_g2_audit` + `nurbs_composite_g2_upgrade` registered; 4 validation test classes (27 tests green).
- **GK-P rational conic detection** ✅ — `detect_conic` / `extract_canonical_circle` / `simplify_curve`; Lee 1987 algebraic LS fit + Piegl-Tiller §7.2 classification; returns `ConicInfo` (center, axes, radii, eccentricity, focus, plane_normal) for circle / ellipse / parabola / hyperbola; 2 LLM tools (`nurbs_detect_conic`, `nurbs_simplify_conic`); 24 hermetic analytic-oracle tests — `geom/conic_detect.py`.
- **T-100 FEM depth** — explicit dynamics (module exists, not yet imported/registered); full nonlinear static (only 1-D bar/truss shipped); k-ε turbulence CFD; coupled FEA-based variation analysis. (Acoustics FEM, EM, harmonic, buckling, PSD, multi-axial fatigue are now shipped.)
- **T-101 CFD depth** — RANS turbulence models; 3-D unstructured meshing; OpenFOAM bridge.
- ~~**AFR topology ordering**~~ — ✅ shipped: `afr_to_dag` + `.feature` emitter + `afr_to_parametric` LLM tool in `kerf-cad-core/afr/dag.py`.
- **T-101 CFD depth** — k-ε RANS shipped (T-101-A ✅); 3-D unstructured meshing (T-101-B, 4L); OpenFOAM bridge depth (T-101-C, 4M).
- **T-100 FEM depth** — explicit dynamics (module exists, not yet imported/registered); full nonlinear static (only 1-D bar/truss shipped); k-ε turbulence CFD; coupled FEA-based variation analysis. (Acoustics FEM, EM, harmonic, buckling, PSD, multi-axial fatigue are now shipped.)
- **T-101 CFD depth** — T-101-A k-ε ✅; T-101-B 3-D unstructured meshing ✅; T-101-C OpenFOAM bridge ✅ (case generator, polyMesh writer, result parser, LLM tools).
- **T-100 FEM depth** — explicit dynamics (module exists, not yet imported/registered); full nonlinear static (only 1-D bar/truss shipped); k-ε turbulence CFD; coupled FEA-based variation analysis. (Acoustics FEM, EM, harmonic, buckling, PSD, multi-axial fatigue are now shipped.)
- **T-101 CFD depth** — RANS turbulence models ✅; 3-D unstructured meshing ✅; OpenFOAM bridge (T-101-C, remaining).
- **AFR topology ordering** — promote the AAG feature classifier output into a fully replay-able parametric DAG (depends on NURBS kernel completeness).
- **Reverse-engineering freeform fit** — freeform NURBS surface fit from segmented point clouds; currently only analytic primitives (plane/sphere/cylinder/cone/torus).
- **AFR topology ordering** — promote the AAG feature classifier output into a fully replay-able parametric DAG (depends on NURBS kernel completeness).
- **PLM configurator layer** — 150%/effectivity BOM, where-used, ECR/ECO workflow, MBSE/SysML traceability.
- **PLM configurator layer** — configurator + effectivity BOM ✅ shipped (`kerf-plm`); remaining: where-used, ECR/ECO workflow, MBSE/SysML traceability.
- **PLM configurator layer** — 150%/effectivity BOM, where-used, ECR/ECO workflow. (MBSE digital thread / SysML 1.x XMI traceability ✅ shipped — `kerf-plm`.)
- **KBE general configurator** — rule-driven design configurator layer on top of the existing standard-specific compliance engines.
- **KBE general configurator** ✅ — general `KBEEngine` with 10-rule starter pack (AISC W-shape, ACI rebar, ASCE 7 wind, ISO 281 bearing, ASME B106 shaft, NEC wire/breaker/transformer, IPC pipe, Darcy-Weisbach pump) + `kbe_apply_rules` LLM tool. Deep multi-domain configurator integration (BOM routing, variant management) still ahead.
- **PLM configurator layer** — where-used, ECR/ECO workflow, MBSE/SysML traceability (variant configurator + KBE bridge shipped ✅ in `kerf-plm`).
- **KBE general configurator** — KBE engine + configurator bridge shipped ✅; remaining: BOM routing variants, 150%-BOM expansion, variant management UI.

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
