# Kerf — Roadmap

*Last verified: 2026-06-04*

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

### 2026-06-03 / 2026-06-04 — Wave 8–12 comprehensive saturation push

Compare-manifest saturation at time of writing: **1235 yes / 29 partial / 1 no** (98.5%).

**Kernel depth**
- Stam exact-limit position + tangents at extraordinary Catmull-Clark vertices via eigenstructure decomposition (`packages/kerf-cad-core/src/kerf_cad_core/subd/stam_limit_tangents.py`).
- Fractional crease decay, DeRose-Kass-Truong 1998 §4: `s_new = max(0, s_old − 1)` per subdivision level, smooth-weight = `1 − clamp(s_L, 0, 1)` (`subd/crease_fractional_decay.py`).
- MatchSrf G3 boundary continuity: curvature-rate continuity match across joined NURBS surfaces (`geom/surface_g3_match.py`).
- Full NURBS analytic surface derivatives (Piegl & Tiller Algorithm A3.6 + rational quotient rule A4.4), Gaussian K and mean H curvature, hardened SSI differential-geometry marcher (`geom/surface_analytic_derivatives.py`).
- B-rep → 2D Hidden-Line Removal projection for technical drawings (`packages/kerf-cad-core/src/kerf_cad_core/drawings/hlr.py`).
- G1 continuity at extraordinary-vertex SubD → NURBS patch conversion (Loop 1987 §4) (`subd/g1_extraordinary_patches.py`).

**SubD / mesh**
- Multires displacement maps on Catmull-Clark limit surface (Krishnamurthy-Levoy 1996) (`subd/multires_displacement.py`).
- SDF CSG smooth-blend (smooth-min) + marching-cubes polygonisation (Lorensen-Cline 1987) (`geom/sdf_csg.py`, `geom/marching_cubes.py`).
- Sculpt brush engine: grab / smooth / inflate / crease / pinch / Smooth-Taubin; Wendland C2 falloff (`mesh_sculpt_brushes.py`).
- `.3dm` write side + Hausdorff round-trip oracle (`imports/rhino3dm_writer.py`).
- LSCM UV unwrap wired as LLM tool; UV-chart hardening (seam cut + shelf bin-pack + distortion stats) (`geom/uv_unwrap_hardening.py`).
- Viewport LOD bridge: `mesh_url` byte-count estimator, camera-debounce LOD planner wired to Renderer.

**Optics / rendering**
- Jensen 1996 spectral photon-map + caustic solver (`packages/kerf-optics/src/kerf_optics/photon_map.py`).
- WebGPU spectral path-tracer (browser, BK7/SF11/water glass scene) (`src/components/render/WebGPUPathTracer.jsx`).
- Theatrical lighting plot + IES LM-63 photometric reader (`packages/kerf-optics/src/kerf_optics/theatrical_lighting.py`).
- Daylight / lux simulation (CIE sky models) + archviz pipeline (`kerf-optics/lux_sim.py`).
- Phoenix-FD-equivalent visual fluid simulation (`kerf-render/fluid_viz.py`).
- Zemax metalens design (Khorasaninejad 2016) + STOP multiphysics (`kerf-optics/metalens.py`, `kerf-optics/stop_multiphysics.py`).

**Simulation**
- RANS k-ε (Launder-Spalding 1974) + k-ω SST (Menter 1994) turbulence models + wall functions (`packages/kerf-cfd/src/kerf_cfd/rans_keps.py`, `rans_kw_sst.py`).
- snappyHexMesh-style mesher + ASCE 7-22 wind engineering + Bearman vortex shedding (`kerf-cfd/snappy_mesher.py`, `kerf-cfd/wind_engineering.py`).
- CFD combustion EBU + Lagrangian particles + ALE dynamic mesh / FSI (`kerf-cfd/combustion.py`, `kerf-cfd/fsi.py`).
- Compressible Roe flux + conjugate heat transfer + VOF multiphase + Holtrop-Mennen marine resistance (`kerf-cfd/compressible.py`, `kerf-marine/holtrop_mennen.py`).
- Adams Craig-Bampton flex-body MBD + Pacejka tire (Adams/Car) + Litvin gear/belt (Adams/Machinery) (`packages/kerf-fem/src/kerf_fem/craig_bampton.py`, `kerf-1dsim/pacejka_tire.py`).
- FE-solid tet/hex elements with H8 B-bar + Total-Lagrangian nonlinear static (`kerf-fem/fe_solid.py`).
- Classical controls: TF/Routh-Hurwitz/Bode/Nyquist, PID tuning (Ziegler-Nichols + IMC + Lambda), state-space + LQR + Ackermann (`packages/kerf-1dsim/src/kerf_1dsim/classical_control.py`).
- AC load-flow Newton-Raphson power systems (`kerf-1dsim/ac_loadflow.py`).

**Manufacturing / mold**
- Cimatron mold base library + EDM electrode + wire EDM G-code generation (`packages/kerf-mold/src/kerf_mold/`).
- Parting line detection + cavity-core split (`kerf-mold/parting_line.py`, `kerf-mold/cavity_core_split.py`).
- Moldflow injection-fill simulation: 1.5D Hele-Shaw + Cross-WLF rheology (`kerf-mold/injection_fill.py`).
- FiberSim AFP/ATL fibre-placement paths + laser projection + flat-pattern DXF export (`packages/kerf-composites/src/kerf_composites/fibersim.py`).

**Architecture / BIM / Civil**
- 8760-hr ASHRAE energy simulation + Title 24 (16 CA climate zones) + LEED v4 EAp2 (`packages/kerf-bim/src/kerf_bim/energy_sim.py`).
- HVAC plant simulation: chiller / boiler / VAV + AHRI-certified equipment catalogue (`kerf-hvac/`).
- Civil 3D dynamic TIN (Bowyer-Watson Delaunay) + Manning gravity pipes + Hazen-Williams pressure pipes (Hardy-Cross) (`packages/kerf-civil/src/kerf_civil/tin_terrain.py`, `kerf-civil/pipe_networks.py`).
- Civil parcel subdivision + plan-and-profile sheet generator (`kerf-civil/parcel_subdivision.py`, `kerf-civil/plan_profile.py`).
- Multi-discipline plant federation (`kerf-bim/plant_federation.py`).
- AVEVA piping ASME B16 component catalogue (`kerf-piping/aveva_catalog.py`).

**PLM / packaging**
- ArtiosCAD pre-press tooling + PDF/X-1a output (`packages/kerf-packaging/src/kerf_packaging/artioscad.py`).
- Material yield + cost estimation (`kerf-packaging/material_yield.py`).
- Cimatron quote-to-delivery workflow (ANSI/ISA-95 status state-machine) (`kerf-plm/quote_workflow.py`).
- PLM Configurator + SysML Trace UI panels (`src/components/plm/ConfiguratorPanel.jsx`, `SysMLTracePanel.jsx`).

**AFR / Reverse engineering**
- AAG topology DAG feature-recognition (Han-Pratt-Regli 2000) (`packages/kerf-cad-core/src/kerf_cad_core/afr/topology_dag.py`).
- Persistent face naming (Kripac 1997) for parametric replay (`kerf-cad-core/geom/history/`).
- Freeform NURBS fit pipeline + Hausdorff round-trip oracle (`kerf-cad-core/geom/nurbs_fit_reverse.py`).

**Aerospace**
- CR3BP libration orbits: halo / Lyapunov / Lissajous via Richardson 1980 + Howell 1984 (`packages/kerf-aero/src/kerf_aero/cr3bp_libration.py`).
- Batch least-squares + EKF orbit determination (`kerf-aero/orbit_determination.py`).
- GMAT 3D trajectory viewer (Three.js) (`src/components/aero/GmatTrajectoryViewer.jsx`).
- OpenRocket RASP `.eng` motor DB wired as LLM tool (`kerf-aero/openrocket_motors.py`).

**Electronics**
- BSIM4 + PVT corner Monte Carlo + multi-dialect netlist codegen (SPICE foundry parity) (`packages/kerf-electronics/src/kerf_electronics/bsim4.py`).
- Altium MB3D multi-board workspace + inter-board net mapping (`kerf-electronics/multiboard.py`).
- LTspice-equivalent schematic capture GUI + wire router (`src/components/electronics/SchematicCapture.jsx`).
- Interactive PCB editor with push-shove routing + diff-pair tuning (`src/components/electronics/PCBEditor.jsx`, `kerf-electronics/routing/push_shove.py`).
- AC load-flow Newton-Raphson (`kerf-1dsim/ac_loadflow.py`).
- openEMS FDTD geometry export bridge for PCB RF routes (`kerf-electronics/routes_rf.py`).

**Verticals**
- Dental (3Shape-parity depth): crown/bridge, implant planning (Straumann/Nobel/Astra), surgical guide, RPD/denture (Kennedy class), intraoral STL + ICP+Kabsch bite alignment, lab workflow (KaVo articulator JSON), Hu-moment template-matching for AI assist (`packages/kerf-dental/src/kerf_dental/`).
- Apparel / e-textiles: CLO3D avatar body form + smart garment e-textiles + pattern grading (`packages/kerf-textiles/src/kerf_textiles/`, `kerf-apparel/`).
- Woodworking: Mozaik cabinet room layout + cut-list / joinery / grain depth (`packages/kerf-woodworking/src/kerf_woodworking/mozaik.py`).
- Visual scripting: Vectorworks Marionette + MatrixGold scripting engine + Braceworks rigging-load (`src/components/visual_script/NodeGraph.jsx`, `kerf-systems/marionette.py`).
- ZBrush-equivalent: dynamesh + polypaint + HD displacement + character rigging (`kerf-cad-core/mesh_sculpt_brushes.py`, `kerf-cad-core/subd/multires_displacement.py`).
- Animation: keyframe FCurves + armature poser + CCD/FABRIK IK solvers (`kerf-motion/animation.py`, `kerf-motion/ik_solvers.py`).

**Frontend panels**
- `StructuralPanel.jsx` — 24 arch_* LLM tools in 5 tabs (`src/components/arch/StructuralPanel.jsx`).
- `OpticsDesignPanel.jsx` — 42 optics LLM tools in 5 tabs (`src/components/optics/OpticsDesignPanel.jsx`).
- Civil 3D viewport components: `TINView.jsx`, `PipeNetworkView.jsx`, `GradingPlanView.jsx`, `LandscapeView.jsx` (`src/components/civil/`).
- HVAC design panels: `HVACLoadPanel`, `DuctDesignPanel`, `EquipmentSelectPanel` (`src/components/hvac/`).
- Visual node-graph scripting (Dynamo/Grasshopper equivalent) (`src/components/visual_script/NodeGraph.jsx`).
- WebGPU spectral path-tracer page (`src/components/render/WebGPUPathTracer.jsx`).

**Materials**
- Ashby material selection: catalog + performance indices + Pareto front + multi-objective scoring (`packages/kerf-lca/src/kerf_lca/ashby_selection.py`).

**Motion / dynamic simulation**
- Multi-body dynamics: Featherstone recursive Newton-Euler inverse dynamics, integrator (RK4/semi-implicit Euler), forward + inverse kinematics, joints, contact + friction (`packages/kerf-motion/`).
- Craig-Bampton flexible-body MBD: modal-synthesis reduction for FEA mode shapes; Pacejka Magic Formula tire model (Adams/Car parity); Litvin gear/belt machinery dynamics (Adams/Machinery parity) (`packages/kerf-mates/src/kerf_mates/mbd/`).
- CCD + FABRIK inverse-kinematics solvers + pole-target support (`packages/kerf-cad-core/src/kerf_cad_core/animation/ik_solver.py`).
- Mechanism synthesis: four-bar Burmester graphical synthesis, cam-follower profile generator, gear-train ratio synthesis (`packages/kerf-mates/src/kerf_mates/synthesis/`).
- Animation system: keyframe FCurves with bezier/cubic-Hermite/cyclic interpolation, armature poser with cascading parent matrices (`packages/kerf-cad-core/src/kerf_cad_core/animation/`).

---

### 2026-05-26 / 2026-05-31 — Wave 7A–7D

Key additions from the wave-7 push:

- **Wrapper-module consolidation** — collapsed 8 thin `*_tools.py` wrapper files into their core modules using gated-import pattern; ~1,750 LOC saved.
- **FMI 2.0 model export (.fmu)** — CoSimulation + ModelExchange capability, `modelDescription.xml`, C source wrapper (`kerf-1dsim/fmi_export.py`).
- **Tilted-surface PV irradiance** — Liu-Jordan, Hay-Davies, Perez 1990 5-coefficient models; optimal annual tilt; latitude-aware TMY3 monthly factors (`kerf-energy/pv_irradiance.py`).
- **ASME B31 pressure-loss + Crane TP-410 K-factors** — Darcy-Weisbach + Colebrook-White; Hooper Two-K method; 15-entry K-factor table (`kerf-piping/asme_pressure.py`).
- **Piping wall thickness (ASME B31.1-2022)** — §104.1.2 Eq. 7 sizing, B36.10M schedule recommendation, Table A-1 allowable stress lookup, thermal stress (`kerf-piping/wall_thickness.py`).
- **Motion inverse dynamics** — Featherstone 2008 §5.3 recursive Newton-Euler; gravity compensation; trajectory vectorisation (`kerf-motion/inverse_dynamics.py`).
- **NURBS Fresnel parameterisation** — curvature grows linearly with arc-length (clothoid/Euler spiral law); monotone Fresnel-C drive (`geom/fresnel_parameterize.py`).
- **NURBS surface cross-section** — planar intersection polyline via signed-distance grid walk + bisection refinement (`geom/surface_cross_section.py`).
- **Gauss-Bonnet integrity + chord-deviation** — `gauss_bonnet_residual` + `chord_deviation_per_face`; `subd_verify_gauss_bonnet` LLM tool (`geom/surface_analysis.py`, `geom/subd_gauss_bonnet_check.py`).
- **SubD limit integrals** — exact global area + mean-curvature + Gaussian-curvature integrals over CC limit surface; Gauss-Bonnet 4π oracle for χ=2 sphere (`geom/subd_limit_integrals.py`).
- **Irrigation sprinkler layout** — Hunter/Rain Bird/Toro catalogue; square/triangular/oblong spacing; GPM zone demand (`kerf-landscape/irrigation_design.py`).
- **HVAC AHRI equipment catalogue** — 30 AHRI-certified models across 6 categories with part-load curves (`kerf-hvac/ahri_catalogue.py`).
- **Civil infrastructure UI** — `TINView`, `PipeNetworkView`, `GradingPlanView`, `LandscapeView` viewport components.
- **HVAC design UI** — three panels wired to HVAC backends for `.hvac.load`, `.hvac.duct`, `.hvac.equip` file kinds.
- **PV latitude-aware TMY** — TMY3-derived monthly irradiance fractions, hemisphere flip, 29 hermetic tests (`kerf-energy/solarpv/tmy.py`).
- **Multiple electronics tools** — optocoupler CTR/isolation, Zener TC drift, Zener clamp design, op-amp offset drift, inductor core saturation, MOSFET SOA check, LDO dropout checker, buck converter ripple, EMI filter design, PCB trace/via current (IPC-2221B/2152), wire ampacity derating, fuse I²t verification, NEC voltage-drop and circuit-protection checks (`packages/kerf-electronics/src/kerf_electronics/`).
- **Multiple mold tools** — runner diameter, warpage index, cooling pressure drop, MFR injection-speed check, sprue bushing match, turbulent Re check, core-pin cooling, ejector pin buckling, tunnel gate design, surface finish (SPI A1–D3), color concentrate ratio (`packages/kerf-mold/src/kerf_mold/`).
- **GD&T depth** — GK-P12/P13/P14 SubD Stam limit tangents, G1 extraordinary patches, fractional crease decay; composite tolerance frames (ASME Y14.5-2018 §10.5); datum precedence warnings; circular/total/axial runout checks; composite positional tolerance; dimension chain (WC + RSS); datum shift bonus tolerance (`packages/kerf-cad-core/src/kerf_cad_core/gdt/`, `packages/kerf-gdnt/src/kerf_gdnt/`).
- **Architecture structural tools** — base plate (AISC DG-1), beam deflection (Roark 9e), column load (AISC §E3 + ACI 318-19 §22.4), footing bearing (Meyerhof 1963), slab deflection (Kirchhoff), diaphragm shear (SDPWS-2021), anchor bolt pullout (ACI 318-19 §17.6), bolt shear (AISC §J3), stair stringer (IBC 2021 §1011), slab-on-grade (Westergaard 1948/PCA EB119), opening-in-wall (IBC §2308.4), lintel design (AISC/ACI/TMS), bearing wall axial (ACI §11.5.3/TMS §8.3), pier axial (TMS §8.3/ACI §22.4.2.2), retaining wall stability (Rankine), shear wall OOP (ACI §11.7), punching shear (ACI §22.6), lateral bracing (AISC §F2) (`packages/kerf-cad-core/src/kerf_cad_core/arch/`).
- **BIM additions** — COBie 2.4 deliverable, BCF issue manager + markup/redline, drawing list / multi-sheet manager, BIMcloud-lite element locks, HVAC plant simulation depth (`packages/kerf-bim/`).
- **`cad_component` real geometry substitution** — JSCAD `model_3d` + STEP `model_3d_paths` render real geometry in CircuitEditor 3D tab; per-SHA cache.
- **CAM turning depth** — optimal DOC per pass + roughing-pass count for lathe turning; Sandvik CoroPlus material max DOC ranges (`kerf-cam/turning_depth_calc.py`).

---

### 2026-05-20 / 2026-05-25 — Phase 6 domain-depth (Waves 1–7)

Prior to the current saturation push, the following major capabilities landed:

**Core platform**
- Auth + projects + files + chat (CRUD) — Postgres, JWT, Google OAuth.
- Plugin monorepo (`packages/kerf-*`) — `kerf-core` app factory + entry-point loader; 25+ plugin packages; 1000+ tests.
- Single-binary build + brew/curl install — embedded Vite SPA (~32 MB).
- Auth-optional local mode (`POST /auth/bootstrap-local`).
- Cloud: workshop sharing, billing, LLM pricing, free/paid/BYO buckets + wallet — USD-display, credits at cost.
- Cloud: git (commits/branches/merge/GitHub sync) + git Storer.
- Large-file git handling — pointer kind, Phase 1.
- Diff-based + compressed revisions — 82× shrink.
- Workspaces (orgs), activity timeline, avatars/CDN, collapsible chat.
- E2E Playwright + per-plugin pytest suites.
- Billing-ledger schema on fresh databases.

**Scripting / SDK**
- `.script.py` via `kerf-sdk` — `/v1/rpc` JSON-RPC over the LLM tool registry; API tokens; PyPI publish.
- SDKs: Python, TypeScript, Rust, Go, Lua — same `/v1/rpc` wire format.

**Parametric core**
- Equations / global parameters — `.equations`, mathjs.
- Configurations / variants — per-file param overrides, BOM rollup.
- Materials database — `.material` kind, 200+ seeded materials.
- Two coexisting kernels — `.jscad` (mesh) + `.feature` (OCCT BRep), shared `.sketch` / `.assembly` / `.drawing`.
- Pure-Python B-rep + NURBS kernel — validated `Body` topology, tolerant booleans, G1/G2/G3 fillets, closest-point, hardened SSI, parametric history DAG with persistent face naming.

**Geometry kernel**

The pure-Python kernel (`packages/kerf-cad-core/src/kerf_cad_core/geom/`) matches Rhino/Blender-class construction depth with an analytic foundation. Key modules:

| Module | Capability |
|---|---|
| `brep.py` | Radial-edge B-rep topology; nine Euler operators; Euler-Poincaré invariant |
| `boolean.py` | Tolerant pure-Python solid booleans (cut/fuse/common) + general NURBS×NURBS path |
| `fillet_solid.py` / `chamfer.py` | G1/G2 surface blend; edge fillet; variable chamfer; G3 blend chains |
| `surface_analytic_derivatives.py` | Piegl-Tiller A3.6/A4.4 analytic derivatives; curvature; SSI marcher |
| `subd/` | CC subdivision; Stam limit tangents; G1 extraordinary patches; fractional creases; Loop/Doo-Sabin/Modified-Butterfly variants; SubD→NURBS (Loop-Schaefer 2008); sculpt brushes; multires displacement; feature-curve extraction; geodesic heat method; mirror symmetry; deformation cage (Ju 2005) |
| `sdf_csg.py` / `marching_cubes.py` | SDF CSG smooth-blend + Lorensen-Cline 1987 polygonisation |
| `loft_guide_rails.py` | Guide-rail loft (Rhino-parity); closed_v=True periodic skinning (P&T §9.4.5) |
| `sheetmetal_features.py` | Flat-pattern (K-factor, DIN 6935); hem/jog/multi-flange (Suchy §6) |
| `uv_unwrap_hardening.py` | LSCM UV; seam-cut chart pack; shelf bin-packing; distortion stats |
| `surface_g3_match.py` | MatchSrf G3 boundary continuity |
| `subd_limit_integrals.py` | Exact CC limit area + curvature integrals; Gauss-Bonnet verifier |
| `curve_fit_g2.py` | Degree-5 G2 end-condition B-spline curve fit (P&T §9.4) |
| `nurbs_fit_reverse.py` | Freeform NURBS fit from point cloud + Hausdorff oracle |
| `drawings/hlr.py` | B-rep → 2D Hidden-Line Removal for technical drawings |

Full list of 139+ GK modules in `packages/kerf-cad-core/src/kerf_cad_core/geom/`.

**Mechanical / CAD**
- Assembly: motion interference sweep over multi-body timeline; LOD planner + lazy-load.
- GD&T suite: runout (circular/total/axial), datum shift, composite tolerance frames, dimension chain stack-up, datum reference frame validator, feature-of-size DOF, datum precedence consistency.
- CAM: turning depth calculator, milling toolpath, G-code post-processor, lathe cycle simulation.
- Sheet metal: flat-pattern, hem/jog/multi-flange, DXF export.
- Wiring harness: 3D auto-routing (voxel A*), formboard flatten, NEC ampacity + voltage-drop checks.
- FEM: linear static + modal + buckling + harmonic + PSD + acoustics + EM + fatigue + explicit dynamics + 3-D nonlinear static (H8 B-bar, Total-Lagrangian, J2 plasticity, arc-length) + coupled-field probabilistic (LHS + Karhunen-Loève).

**Simulation / manufacturing**
- CFD: RANS k-ε + k-ω SST + wall functions; 3-D tet mesher; OpenFOAM export bridge; combustion EBU; Lagrangian particles; ALE/FSI; snappyHexMesh-style mesher; ASCE 7-22 wind engineering; Bearman vortex shedding; compressible Roe flux; conjugate HT; VOF multiphase; Holtrop-Mennen marine resistance.
- Mold: Hele-Shaw fill simulation + Cross-WLF rheology; runner optimisation; warpage index; cooling (pressure drop, turbulent Re, core-pin design); ejector-pin buckling; tunnel gate; sprue bushing match; surface finish (SPI A1–D3); parting-line detection + cavity-core split; Cimatron quote-to-delivery.
- Manufacturing: tolerance stack-up; CMM path planning; process-capability (Cpk/Ppk); DFM checklist.

**Electronics**
- PCB editor with push-shove routing + diff-pair tuning.
- BSIM4 + PVT corner MC + multi-dialect netlist codegen (SPICE foundry parity).
- Altium MB3D multi-board workspace + inter-board net mapping.
- LTspice-equivalent schematic capture GUI.
- openEMS FDTD XML bridge for RF routes (single straight-trace).
- Component analysis: MOSFET SOA, LDO dropout, buck ripple, EMI filter, zener clamp/TC, optocoupler CTR, op-amp offset drift, inductor saturation, PCB trace/via current, fuse I²t, NEC wire ampacity + voltage drop + circuit protection.
- ECAD import: KiCad, Altium, Allegro, PADS, gEDA, Eagle.

**Architecture / BIM**
- Full structural tool suite: 18 arch_* tools (beam, slab, wind, footing, connections, walls) per AISC 360-22, ACI 318-19, ASCE 7-22, TMS 402-22, IBC 2021.
- 8760-hr ASHRAE energy sim + Title 24 (16 CA zones) + LEED v4 EAp2.
- HVAC: AHRI catalogue, plant simulation (chiller/boiler/VAV), duct sizing, equipment selection.
- BIM: COBie 2.4, BCF issue manager, drawing-list manager, BIMcloud-lite element locks, IFC import, AVEVA piping ASME B16 catalogue, multi-discipline plant federation.
- Civil: dynamic TIN (Bowyer-Watson Delaunay), Manning gravity pipes, Hazen-Williams pressure pipes (Hardy-Cross), parcel subdivision, plan-and-profile sheets.

**Aerospace / composites**
- CR3BP libration orbits (halo / Lyapunov / Lissajous); batch LS + EKF orbit determination; GMAT 3D trajectory viewer.
- OpenRocket RASP `.eng` motor DB.
- FiberSim AFP/ATL fibre-placement paths + laser projection + flat-pattern DXF.
- Structural analysis hooks (FEM tet/hex solid).

**Library / parts / BOM**
- Parts library + BOM + distributor pricing — Octopart + DigiKey + Mouser price look-up, BOM rollup.
- `substitute_component` LLM tool — library-mapped real geometry in 3D tab.
- Ashby material selection: catalog + performance indices + Pareto front.

**Frontend / UX**
- `StructuralPanel.jsx`, `OpticsDesignPanel.jsx`, `HVACLoadPanel`, `DuctDesignPanel`, `EquipmentSelectPanel`.
- Civil 3D viewports: `TINView`, `PipeNetworkView`, `GradingPlanView`, `LandscapeView`.
- Visual node-graph scripting (Dynamo/Grasshopper equivalent): `src/components/visual_script/NodeGraph.jsx`.
- PLM Configurator + SysML Trace UI panels.
- WebGPU spectral path-tracer page.
- GMAT 3D trajectory viewer (Three.js).
- PCB interactive editor + schematic capture.
- Class-A continuity viewport toggle (zebra stripes + G2/G3 per-edge audit panel).

---

## In flight / soon

- **P0-8 testing / seeding / deploy-hardening** — broad test suites + realistic seed data + one-command local/dev loops.
- **P1-8 Git-as-substrate with automatic large-file handling** — every project a stock-`git clone`-able repo; near-instant forks via shared content-addressed storage.
- **P1-9 Unified `pip install kerf` client** — cloud-default, easy optional self-host.
- **T-101 CFD depth** — LES/DES/DNS, parallel MPI execution, ParaView/VTK post-processing bridge, marine hydrodynamics at depth.
- **Koyeb migration (T-400..T-410)** — Fly.io GPU fleet killed; Koyeb code complete; T-405 DNS/secrets/deploy cutover needs user action.
- **Large-assembly DMU** — LOD heuristics use synthetic estimates; wiring to real tessellated part geometry would sharpen tier boundaries.
- **OCCT Phase 4 NURBS surfacing** — long-tail; only remaining major kernel item.

---

## Genuinely outstanding

Items verified against `public/compare-manifest.json` as `partial` or `no` with no shipped backend:

**Partial (29 items)**
- `solidworks` — Moldflow injection fill simulation (1235-record manifest shows partial; Hele-Shaw 1.5D shipped, full 3D not)
- `solidworks` — Material selection Ashby / multi-objective (catalog + indices shipped; UI multi-criteria not fully wired)
- `aveva-e3d` — Piping component catalogue (ASME B16 catalogue partial; full E3D spec depth pending)
- `aveva-e3d` — Multi-discipline plant design structural/HVAC/civil (federation shipped; deep E3D-style concurrent authoring pending)
- `aveva-e3d` — Global multi-user concurrent design
- `cimatron` — Quote-to-delivery workflow (ISA-95 state machine shipped; full ERP bridge pending)
- `fibersim` — Laminate weight / cost estimation
- `maxsurf` — Structural scantlings (Lloyd's / DNV / BV / ABS rules)
- `mozaik` — Woodworking cut-list / joinery / grain (cabinet layout shipped; full cut-list optimiser pending)
- `cadence-spectre` / `hspice` — SPICE commercial foundry PDK sign-off accuracy
- `adams` — FEA load export bridge
- `openfoam` — CFD LES/DES/DNS, parallel MPI, ParaView/VTK post-processing, marine hydrodynamics
- `zemax` — Tolerancing (NEST / Monte Carlo)

**No (1 item)**
- `matrixgold` — Jewelry supplier catalog integration

---

## Code health

Incremental refactors recorded here for traceability.

| Date | Change | LOC saved |
|---|---|---|
| 2026-06-01 | Consolidated `geom/sweep1.py` + `geom/sweep2.py` + `geom/sweep_n.py` into a single `sweep1.py` with unified `sweep_along_rails` dispatcher; backward-compat wrappers kept; deleted 2 source files + 1 test file. | ~300 LOC |
| 2026-06-01 | Collapsed 8 thin `*_tools.py` wrapper files (assembly_interference_tools, face_planarity_tools, brep_connect_inspector_tools, offset_far_tools, network_surface_tools, topology_euler_check_tools, vertex_degree_check_tools, bolt_shear_aisc_tools) into their core modules using gated-import pattern. | ~1,750 LOC |

---

## Deliberately not building

This list is only AI-redundant *authoring/UX interaction paradigms* — not skipped domains or correctness features.

| Not building | Why |
|---|---|
| Ribbon / toolbar maximalism | The LLM is the command palette — discovery is a chat sentence, not a menu hunt. |
| Macro recorders / scripting-GUI builders | The LLM is the macro author; it writes `.script.py` directly. |
| Gumball / direct-modeling maximalism | Keep a basic gumball; the LLM edits the feature tree. |
| In-app wizards / tutorials / onboarding tours | The chat is the wizard — context-specific guidance on demand. |

---

## How to contribute

Pick a task from [`tasks.md`](./tasks.md) (sized for a single isolated agent run), or open an issue proposing a new long-tail sector line. The roadmap states *why* and *in what order*; `tasks.md` is the *how*. Keep them in sync: when a priority moves here, move the corresponding tasks there.
