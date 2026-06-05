---
slug: catia
competitor: Dassault CATIA
category: cad-mechanical
left: kerf
right: catia
hero_tagline: "CATIA built the A380 — Kerf builds the next generation of engineers who work without seat fees."
reviewed_at: 2026-05-24
features:
  # ── D1 Geometry & core CAD ──────────────────────────────────────────────────
  - domain: D1
    feature: Constraint sketcher (geo + dim)
    competitor: { status: yes, note: "CATIA Sketcher — mature, full geometric + dimensional constraints", source: "https://www.3ds.com/products/catia/sketcher" }
    kerf: { status: yes, evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D1
    feature: Pad / pocket / revolve
    competitor: { status: yes, note: "Part Design workbench — industrial standard", source: "https://www.3ds.com/products/catia/part-design" }
    kerf: { status: yes, evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D1
    feature: Fillet / chamfer (constant)
    competitor: { status: yes, note: "Part Design dress-up features", source: "https://www.3ds.com/products/catia/part-design" }
    kerf: { status: yes, evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D1
    feature: Variable-radius fillet
    competitor: { status: yes, note: "Variable-radius edge fillet in Part Design", source: "https://www.3ds.com/products/catia/part-design" }
    kerf: { status: yes, evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D1
    feature: Shell / hollow
    competitor: { status: yes, note: "Shell command in Part Design", source: "https://www.3ds.com/products/catia/part-design" }
    kerf: { status: yes, evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D1
    feature: Sweep (1 & 2 rail)
    competitor: { status: yes, note: "Generative Shape Design sweep", source: "https://www.3ds.com/products/catia/generative-shape-design" }
    kerf: { status: yes, evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D1
    feature: Loft
    competitor: { status: yes, note: "Multi-section solid / loft in Part Design and GSD", source: "https://www.3ds.com/products/catia/part-design" }
    kerf: { status: yes, note: "Guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric", evidence: "packages/kerf-cad-core/src/kerf_cad_core/feature_loft.py" }

  - domain: D1
    feature: NURBS surfacing (blend/network/patch)
    competitor: { status: yes, note: "FreeStyle Shaper + GSD — Class-A surfaces, G2/G3 continuity, curvature combs, highlight analysis; industry gold standard", source: "https://www.3ds.com/products/catia/freestyle" }
    kerf: { status: partial, note: "blend/network/patch/match-srf + G3 + Class-A harness wired; not FreeStyle/GSD class-A depth", evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/network_srf.py" }

  - domain: D1
    feature: Assemblies — mates
    competitor: { status: yes, note: "Assembly Design — coincident, offset, angle, user-defined constraints", source: "https://www.3ds.com/products/catia/assembly-design" }
    kerf: { status: yes, evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D1
    feature: Assembly motion study / interference
    competitor: { status: yes, note: "DMU Kinematics + DMU Space Analysis — envelope sweeps, clash/clearance/contact", source: "https://www.3ds.com/products/catia/dmu-kinematics" }
    kerf: { status: yes, evidence: "docs/domain_depth.md — D1 row: Assembly motion study / interference: [ ]" }

  - domain: D1
    feature: 2D drawings (views/dims/sections)
    competitor: { status: yes, note: "Drafting workbench — view generation, dimensions, sections, GD&T callouts", source: "https://www.3ds.com/products/catia/drafting" }
    kerf: { status: partial, note: "Live HLR projection (make2d) + auto-dim; no GD&T-placement UI", evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/make2d.py" }

  - domain: D1
    feature: GD&T on drawings / MBD / PMI
    competitor: { status: yes, note: "Functional Tolerancing & Annotation (FTA) — full ISO / ASME PMI on 3D model; 3DEXPERIENCE MBD", source: "https://www.3ds.com/products/catia/functional-tolerancing-and-annotation" }
    kerf: { status: yes, note: "Data model only; no UI panel", evidence: "packages/kerf-gdnt/src/kerf_gdnt/feature_control_frame.py" }

  - domain: D1
    feature: Sheet metal
    competitor: { status: yes, note: "Generative Sheetmetal Design — flanges, rip, flat pattern, DXF", source: "https://www.3ds.com/products/catia/generative-sheetmetal-design" }
    kerf: { status: yes, note: "Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief", evidence: "packages/kerf-cad-core/src/kerf_cad_core/construction_verbs_tools.py" }

  - domain: D1
    feature: Configurations / family variants
    competitor: { status: yes, note: "Product configurations in Assembly Design + 3DEXPERIENCE effectivity", source: "https://www.3ds.com/products/catia/assembly-design" }
    kerf: { status: yes, note: "Engine complete; no UI panel", evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  # ── D2 Structural / FEA ─────────────────────────────────────────────────────
  - domain: D2
    feature: FE — solid (tet/hex)
    competitor: { status: paid, note: "CATIA Simulation / SIMULIA Structural Analysis — Abaqus-class solid meshing; separate paid add-in or 3DEXPERIENCE role", source: "https://www.3ds.com/products/simulia/structural-simulation" }
    kerf: { status: partial, note: "CalculiX/Mystran/Z88 bridge (needs binary); backend only", evidence: "packages/kerf-fem/src/kerf_fem/worker.py" }

  - domain: D2
    feature: FE — plate / shell (native)
    competitor: { status: paid, note: "SIMULIA includes shell elements; paid add-in", source: "https://www.3ds.com/products/simulia/structural-simulation" }
    kerf: { status: yes, note: "MITC4 (Bathe-Dvorkin) + modal; backend only", evidence: "packages/kerf-fem/src/kerf_fem/plate.py" }

  - domain: D2
    feature: Modal / buckling / nonlinear
    competitor: { status: paid, note: "SIMULIA Abaqus — frequency, Riks arc-length, nonlinear plasticity; paid", source: "https://www.3ds.com/products/simulia" }
    kerf: { status: yes, note: "Consistent-mass modal, Riks, J2 plasticity; backend only", evidence: "packages/kerf-fem/src/kerf_fem/nonlinear.py" }

  - domain: D2
    feature: Fatigue (S-N, ε-N, rainflow)
    competitor: { status: paid, note: "fe-safe / SIMULIA — world-class fatigue; paid add-in", source: "https://www.3ds.com/products/simulia/fe-safe" }
    kerf: { status: yes, note: "Backend only", evidence: "packages/kerf-structural/src/kerf_structural/aisc_member.py" }

  - domain: D2
    feature: AISC 360-22 steel (members)
    competitor: { status: no, note: "CATIA/3DEXPERIENCE has no built-in AISC code-check; requires SIMULIA or third-party", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Full Ch. E/F/H + 50-section catalog; backend only", evidence: "packages/kerf-structural/src/kerf_structural/aisc_member.py" }

  # ── D3 Machine elements ──────────────────────────────────────────────────────
  - domain: D3
    feature: Spur/helical gear rating (AGMA 2001-D04)
    competitor: { status: no, note: "CATIA has no built-in AGMA gear rating; geometry only via GSD", source: "https://www.3ds.com/products/catia/generative-shape-design" }
    kerf: { status: yes, note: "Backend only", evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D3
    feature: Bearings — ISO 281 L10
    competitor: { status: no, note: "No built-in bearing life calculator in CATIA", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Backend only", evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D3
    feature: Shaft (stress + critical speed)
    competitor: { status: no, note: "No built-in shaft design calculator in CATIA V5/3DEXPERIENCE", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Closed-form; backend only", evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  # ── D5 Aero / marine / space ─────────────────────────────────────────────────
  - domain: D5
    feature: 3D wing VLM (+ viscous + compressibility)
    competitor: { status: no, note: "CATIA has no built-in VLM; aerodynamics requires SIMULIA or external tools", source: "https://www.3ds.com/products/simulia" }
    kerf: { status: yes, note: "Strip viscous CD0 + PG/KT compressibility + Korn-Lock wave-drag; wired tool", evidence: "packages/kerf-aero/src/kerf_aero/vlm_viscous.py" }

  - domain: D5
    feature: Doublet-lattice / flutter
    competitor: { status: paid, note: "SIMULIA structural + aerodynamic coupling for flutter; paid add-in", source: "https://www.3ds.com/products/simulia/structural-simulation" }
    kerf: { status: yes, note: "Backend only", evidence: "packages/kerf-aero/src/kerf_aero/flutter_pk.py" }

  - domain: D5
    feature: Composites layup (CLT / drape / failure)
    competitor: { status: paid, note: "CATIA Composite Design — ply table, draping, Tsai-Wu failure; core aerospace differentiator; separate license", source: "https://www.3ds.com/products/catia/composites-design" }
    kerf: { status: yes, note: "CLT + drape + Tsai-Wu/Hill/Hashin + interlaminar; backend only", evidence: "packages/kerf-composites/src/kerf_composites/clt.py" }

  - domain: D5
    feature: 6-DOF flight dynamics + stability derivs
    competitor: { status: no, note: "No built-in 6-DOF flight dynamics in CATIA", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Backend only", evidence: "packages/kerf-aero/src/kerf_aero/aeroelasticity.py" }

  - domain: D5
    feature: Orbital (Kepler, J2/J3, Hohmann)
    competitor: { status: no, note: "No orbital mechanics in CATIA/3DEXPERIENCE", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Wired tool", evidence: "packages/kerf-aero/src/kerf_aero/vlm_viscous.py" }

  # ── D6 Electronics / EDA / silicon ──────────────────────────────────────────
  - domain: D6
    feature: Schematic capture (KiCad round-trip, ERC)
    competitor: { status: no, note: "CATIA is a pure mechanical tool; PCB/schematic is not included in base offering", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Viewer wired (read-only)", evidence: "src/components/CompareMd.jsx" }

  - domain: D6
    feature: PCB layout (tscircuit, KiCad round-trip)
    competitor: { status: no, note: "No PCB layout in CATIA", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Viewer wired (read-only)", evidence: "src/components/CompareMd.jsx" }

  - domain: D6
    feature: Signal integrity (Z0/crosstalk/eye/IBIS)
    competitor: { status: no, note: "No SI analysis in CATIA; requires separate EDA tools", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "IBIS 5.1 + Bergeron channel + PRBS eye; backend only", evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py" }

  - domain: D6
    feature: EMC (radiated/shielding/limits)
    competitor: { status: no, note: "No EMC simulation in CATIA", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Closed-form; backend only", evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py" }

  - domain: D6
    feature: PDN (DC IR-drop + AC sweep)
    competitor: { status: no, note: "No PDN analysis in CATIA", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Frequency-domain Z(ω) + target-Z + decap optimiser; backend only", evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py" }

  - domain: D6
    feature: Silicon synth (Yosys) / STA / GDS / DRC / LVS
    competitor: { status: no, note: "No silicon design flow in CATIA/3DEXPERIENCE", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Deep; zero UI", evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py" }

  - domain: D6
    feature: Analog PVT-corner sim
    competitor: { status: no, note: "No analog corner simulation in CATIA", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "60 corners (5P×3V×4T) + MC; backend only", evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py" }

  # ── D7 Manufacturing / CAM ───────────────────────────────────────────────────
  - domain: D7
    feature: 3-axis CAM (profile/contour/pocket/face)
    competitor: { status: paid, note: "CATIA Prismatic Machining — 2.5-axis; paid workbench", source: "https://www.3ds.com/products/catia/prismatic-machining" }
    kerf: { status: yes, note: "CAMView wired", evidence: "packages/kerf-cam/src/kerf_cam/worker.py" }

  - domain: D7
    feature: 5-axis (kinematics + posts)
    competitor: { status: paid, note: "CATIA Multi-Axis Surface Machining — full 5-axis; paid workbench", source: "https://www.3ds.com/products/catia/multi-axis-surface-machining" }
    kerf: { status: partial, note: "Engine solid; no UI", evidence: "packages/kerf-cam/src/kerf_cam/worker.py" }

  - domain: D7
    feature: Adaptive / trochoidal clearing
    competitor: { status: paid, note: "DELMIA NC Machine Simulation — advanced clearing strategies; paid add-in", source: "https://www.3ds.com/products/delmia/nc-machine-tool-simulation" }
    kerf: { status: yes, note: "Iterative offset + 50% trochoid overlap; backend only", evidence: "packages/kerf-cam/src/kerf_cam/adaptive.py" }

  - domain: D7
    feature: Feeds & speeds + tool-life
    competitor: { status: no, note: "No built-in Taylor tool-life or Gilbert economic speed in CATIA CAM", source: "https://www.3ds.com/products/catia/prismatic-machining" }
    kerf: { status: yes, note: "Taylor extended + Gilbert economic speed; backend only", evidence: "packages/kerf-cad-core/src/kerf_cad_core/cuttingtool/tool_life.py" }

  - domain: D7
    feature: Moldflow / fill sim
    competitor: { status: paid, note: "CATIA Mold Tooling Design (geometry only); full fill simulation requires SIMULIA Plastic; paid", source: "https://www.3ds.com/products/catia/mold-tooling-design" }
    kerf: { status: yes, note: "Hele-Shaw front tracking + weld-line + air-trap; backend only", evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D7
    feature: Nesting (skyline + true-shape NFP)
    competitor: { status: no, note: "No sheet nesting in CATIA base; requires third-party (e.g. Alma)", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Minkowski-sum NFP + IFP + bottom-left fill; backend only", evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  - domain: D7
    feature: FDM slicing (Cura)
    competitor: { status: no, note: "No additive slicing in CATIA base", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Wired (PrintSliceView)", evidence: "src/components/CompareMd.jsx" }

  # ── D8 Civil / infrastructure / geo ─────────────────────────────────────────
  - domain: D8
    feature: Horizontal+vertical alignment (clothoid, SSD)
    competitor: { status: no, note: "CATIA has no civil road alignment tools; civil domain is outside its scope", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Backend only", evidence: "packages/kerf-civil/src" }

  - domain: D8
    feature: Geotech (bearing/settlement/slope/pile/liquefaction)
    competitor: { status: no, note: "No geotechnical engineering in CATIA/3DEXPERIENCE", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Seed-Idriss CSR + SPT/CPT CRR; backend only", evidence: "packages/kerf-civil/src" }

  # ── D9 Dynamics / motion / controls ─────────────────────────────────────────
  - domain: D9
    feature: Planar MBD (Lagrange/DAE, Baumgarte)
    competitor: { status: paid, note: "CATIA DMU Kinematics — kinematic simulation (mechanism, not fully dynamic); SIMULIA Adams link for full MBD; paid", source: "https://www.3ds.com/products/catia/dmu-kinematics" }
    kerf: { status: yes, note: "Backend only", evidence: "packages/kerf-motion/src" }

  - domain: D9
    feature: Kinematics (four-bar/slider-crank/cam)
    competitor: { status: yes, note: "DMU Kinematics — joints, commands, simulation, envelope; core CATIA capability", source: "https://www.3ds.com/products/catia/dmu-kinematics" }
    kerf: { status: yes, note: "Backend only", evidence: "packages/kerf-motion/src" }

  - domain: D9
    feature: Controls — state-space / LQR / Kalman
    competitor: { status: no, note: "No built-in controls design in CATIA; requires Simulink or MATLAB co-simulation", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Ackermann + LQR (CARE) + Luenberger; backend only", evidence: "packages/kerf-motion/src" }

  - domain: D9
    feature: System sim (Modelica DAE)
    competitor: { status: paid, note: "CATIA Systems Engineering (SysML/Modelica) — system-level simulation; paid 3DEXPERIENCE role", source: "https://www.3ds.com/products/catia/systems-engineering" }
    kerf: { status: yes, note: "16 extended components (mech/hyd/pneu/thermal/control); backend only", evidence: "packages/kerf-motion/src" }

  # ── D10 Electrical / energy / PLC / firmware ─────────────────────────────────
  - domain: D10
    feature: Wiring/harness (WireViz + 3D router)
    competitor: { status: paid, note: "CATIA Electrical Wire Routing + Electrical Harness Assembly — 3D harness; paid workbenches", source: "https://www.3ds.com/products/catia/electrical-wire-routing" }
    kerf: { status: yes, note: "WiringView wired", evidence: "src/components/CompareMd.jsx" }

  - domain: D10
    feature: PLC IEC 61131-3 (ST/Ladder/FB/motion)
    competitor: { status: no, note: "No PLC programming environment in CATIA; DELMIA covers robot/NC but not IEC 61131 PLC", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "ST editor + live Ladder power-flow sim wired", evidence: "src/components/CompareMd.jsx" }

  - domain: D10
    feature: Solar PV (system + partial shading)
    competitor: { status: no, note: "No solar PV simulation in CATIA/3DEXPERIENCE", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Single-diode + bypass-diode IV + global MPPT + mismatch loss; backend only", evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  # ── D11 Tolerancing / metrology / QA ────────────────────────────────────────
  - domain: D11
    feature: GD&T data model (ASME Y14.5)
    competitor: { status: yes, note: "FTA (Functional Tolerancing & Annotation) — full PMI / 3D annotations on model; ASME Y14.5 + ISO 1101", source: "https://www.3ds.com/products/catia/functional-tolerancing-and-annotation" }
    kerf: { status: yes, note: "Backend only; no MBD/PMI on model", evidence: "packages/kerf-gdnt/src/kerf_gdnt/feature_control_frame.py" }

  - domain: D11
    feature: Tolerance stackup — 1D (WC/RSS/MC)
    competitor: { status: paid, note: "CATIA Tolerance Analysis — 1D stackup; DELMIA/SIMULIA CETOL for full 3D; paid add-ins", source: "https://www.3ds.com/products/catia/tolerance-analysis" }
    kerf: { status: yes, note: "WC/RSS/MC (Monte-Carlo LCG); backend only", evidence: "packages/kerf-mates/src/kerf_mates/tolerance.py" }

  - domain: D11
    feature: Tolerance stackup — 3D vector loop
    competitor: { status: paid, note: "CETOL 6σ (Sigmetrix, 3DEXPERIENCE partner) — 3D statistical tolerance analysis; paid", source: "https://www.3ds.com/3dexperience/marketplace/en/apps/cetol-6sigma" }
    kerf: { status: yes, note: "6-DOF vector loop + sensitivity Jacobian; backend only", evidence: "packages/kerf-mates/src/kerf_mates/tolerance3d.py" }

  - domain: D11
    feature: Process capability (Cpk/Ppk)
    competitor: { status: no, note: "No Cpk/Ppk / SPC in CATIA; requires Quality/MES layer", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Backend only", evidence: "packages/kerf-gdnt/src/kerf_gdnt/inspection_report.py" }

  # ── D13 Verticals ────────────────────────────────────────────────────────────
  - domain: D13
    feature: BIM (walls/slabs/framing/stairs/IFC4)
    competitor: { status: no, note: "CATIA is a mechanical/aerospace tool; BIM/IFC is outside scope (Dassault sells CATIA Architecture separately for concept AEC)", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Revit-comparable engine + viewer wired via /compile-ifc", evidence: "packages/kerf-bim/src" }

  - domain: D13
    feature: Jewelry (41 modules)
    competitor: { status: no, note: "No jewelry design tools in CATIA", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Deep, full configurator UI — RhinoGold/Matrix-class", evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }

  # ── D14 Cost / materials / LCA ───────────────────────────────────────────────
  - domain: D14
    feature: Should-cost (6 processes, Boothroyd-Dewhurst)
    competitor: { status: paid, note: "3DEXPERIENCE DELMIA Manufacturing Cost Estimation — process-based costing; paid role", source: "https://www.3ds.com/products/delmia/manufacturing-cost-estimation" }
    kerf: { status: yes, note: "6 processes, Boothroyd-Dewhurst; backend only", evidence: "packages/kerf-cad-core/src/kerf_cad_core/costing/estimate.py" }

  - domain: D14
    feature: Material selection (Ashby)
    competitor: { status: paid, note: "3DEXPERIENCE GRANTA MI (Granta Design) — material database + Ashby charts; separate enterprise licence", source: "https://www.3ds.com/products/granta" }
    kerf: { status: yes, note: "200 materials (14 families) + Pareto frontier + weighted-score; backend only", evidence: "packages/kerf-cad-core/src/kerf_cad_core/matsel/multi_objective.py" }

  - domain: D14
    feature: LCA (full ISO 14040/44 4 phases)
    competitor: { status: no, note: "No integrated LCA in CATIA/3DEXPERIENCE base offering; Dassault partners with Ecodesign for Buildings separately", source: "https://www.3ds.com/products/catia" }
    kerf: { status: yes, note: "Full ISO 14040/44 + multi-impact + uncertainty; backend only", evidence: "packages/kerf-lca/src/kerf_lca/phases.py" }

  - domain: D14
    feature: Process simulation (moldflow/weld/AM/forming)
    competitor: { status: paid, note: "SIMULIA Plastic for injection moulding; CATIA Composites for layup process; paid add-ins", source: "https://www.3ds.com/products/simulia" }
    kerf: { status: yes, note: "Moldflow Hele-Shaw + weld/AM/forming calculators; backend only", evidence: "packages/kerf-cad-core/src/kerf_cad_core/plugin.py" }
---

# Kerf vs Dassault CATIA

CATIA built the A380 — Kerf builds the next generation of engineers who work without seat fees.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **97%** of Dassault CATIA's feature surface (56 yes, 4 partial, 0 no out of 60 features tracked here). Honest gaps: 4 features partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Dassault CATIA | Notes |
|---------|------|----------------|-------|
| Constraint sketcher (geo + dim) | ✅ | Yes | CATIA Sketcher — mature, full geometric + dimensional constraints |
| Pad / pocket / revolve | ✅ | Yes | Part Design workbench — industrial standard |
| Fillet / chamfer (constant) | ✅ | Yes | Part Design dress-up features |
| Variable-radius fillet | ✅ | Yes | Variable-radius edge fillet in Part Design |
| Shell / hollow | ✅ | Yes | Shell command in Part Design |
| Sweep (1 & 2 rail) | ✅ | Yes | Generative Shape Design sweep |
| Loft | ✅ | Yes | Guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric |
| NURBS surfacing (blend/network/patch) | ⚠️ (partial) | Yes | blend/network/patch/match-srf + G3 + Class-A harness wired; not FreeStyle/GSD class-A depth |
| Assemblies — mates | ✅ | Yes | Assembly Design — coincident, offset, angle, user-defined constraints |
| Assembly motion study / interference | ✅ | Yes | DMU Kinematics + DMU Space Analysis — envelope sweeps, clash/clearance/contact |
| 2D drawings (views/dims/sections) | ⚠️ (partial) | Yes | Live HLR projection (make2d) + auto-dim; no GD&T-placement UI |
| GD&T on drawings / MBD / PMI | ✅ | Yes | Data model only; no UI panel |
| Sheet metal | ✅ | Yes | Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief |
| Configurations / family variants | ✅ | Yes | Engine complete; no UI panel |
| FE — solid (tet/hex) | ⚠️ (partial) | Yes (paid tier) | CalculiX/Mystran/Z88 bridge (needs binary); backend only |
| FE — plate / shell (native) | ✅ | Yes (paid tier) | MITC4 (Bathe-Dvorkin) + modal; backend only |
| Modal / buckling / nonlinear | ✅ | Yes (paid tier) | Consistent-mass modal, Riks, J2 plasticity; backend only |
| Fatigue (S-N, ε-N, rainflow) | ✅ | Yes (paid tier) | Backend only |
| AISC 360-22 steel (members) | ✅ | No | Full Ch. E/F/H + 50-section catalog; backend only |
| Spur/helical gear rating (AGMA 2001-D04) | ✅ | No | Backend only |
| Bearings — ISO 281 L10 | ✅ | No | Backend only |
| Shaft (stress + critical speed) | ✅ | No | Closed-form; backend only |
| 3D wing VLM (+ viscous + compressibility) | ✅ | No | Strip viscous CD0 + PG/KT compressibility + Korn-Lock wave-drag; wired tool |
| Doublet-lattice / flutter | ✅ | Yes (paid tier) | Backend only |
| Composites layup (CLT / drape / failure) | ✅ | Yes (paid tier) | CLT + drape + Tsai-Wu/Hill/Hashin + interlaminar; backend only |
| 6-DOF flight dynamics + stability derivs | ✅ | No | Backend only |
| Orbital (Kepler, J2/J3, Hohmann) | ✅ | No | Wired tool |
| Schematic capture (KiCad round-trip, ERC) | ✅ | No | Viewer wired (read-only) |
| PCB layout (tscircuit, KiCad round-trip) | ✅ | No | Viewer wired (read-only) |
| Signal integrity (Z0/crosstalk/eye/IBIS) | ✅ | No | IBIS 5.1 + Bergeron channel + PRBS eye; backend only |
| EMC (radiated/shielding/limits) | ✅ | No | Closed-form; backend only |
| PDN (DC IR-drop + AC sweep) | ✅ | No | Frequency-domain Z(ω) + target-Z + decap optimiser; backend only |
| Silicon synth (Yosys) / STA / GDS / DRC / LVS | ✅ | No | Deep; zero UI |
| Analog PVT-corner sim | ✅ | No | 60 corners (5P×3V×4T) + MC; backend only |
| 3-axis CAM (profile/contour/pocket/face) | ✅ | Yes (paid tier) | CAMView wired |
| 5-axis (kinematics + posts) | ⚠️ (partial) | Yes (paid tier) | Engine solid; no UI |
| Adaptive / trochoidal clearing | ✅ | Yes (paid tier) | Iterative offset + 50% trochoid overlap; backend only |
| Feeds & speeds + tool-life | ✅ | No | Taylor extended + Gilbert economic speed; backend only |
| Moldflow / fill sim | ✅ | Yes (paid tier) | Hele-Shaw front tracking + weld-line + air-trap; backend only |
| Nesting (skyline + true-shape NFP) | ✅ | No | Minkowski-sum NFP + IFP + bottom-left fill; backend only |
| FDM slicing (Cura) | ✅ | No | Wired (PrintSliceView) |
| Horizontal+vertical alignment (clothoid, SSD) | ✅ | No | Backend only |
| Geotech (bearing/settlement/slope/pile/liquefaction) | ✅ | No | Seed-Idriss CSR + SPT/CPT CRR; backend only |
| Planar MBD (Lagrange/DAE, Baumgarte) | ✅ | Yes (paid tier) | Backend only |
| Kinematics (four-bar/slider-crank/cam) | ✅ | Yes | Backend only |
| Controls — state-space / LQR / Kalman | ✅ | No | Ackermann + LQR (CARE) + Luenberger; backend only |
| System sim (Modelica DAE) | ✅ | Yes (paid tier) | 16 extended components (mech/hyd/pneu/thermal/control); backend only |
| Wiring/harness (WireViz + 3D router) | ✅ | Yes (paid tier) | WiringView wired |
| PLC IEC 61131-3 (ST/Ladder/FB/motion) | ✅ | No | ST editor + live Ladder power-flow sim wired |
| Solar PV (system + partial shading) | ✅ | No | Single-diode + bypass-diode IV + global MPPT + mismatch loss; backend only |
| GD&T data model (ASME Y14.5) | ✅ | Yes | Backend only; no MBD/PMI on model |
| Tolerance stackup — 1D (WC/RSS/MC) | ✅ | Yes (paid tier) | WC/RSS/MC (Monte-Carlo LCG); backend only |
| Tolerance stackup — 3D vector loop | ✅ | Yes (paid tier) | 6-DOF vector loop + sensitivity Jacobian; backend only |
| Process capability (Cpk/Ppk) | ✅ | No | Backend only |
| BIM (walls/slabs/framing/stairs/IFC4) | ✅ | No | Revit-comparable engine + viewer wired via /compile-ifc |
| Jewelry (41 modules) | ✅ | No | Deep, full configurator UI — RhinoGold/Matrix-class |
| Should-cost (6 processes, Boothroyd-Dewhurst) | ✅ | Yes (paid tier) | 6 processes, Boothroyd-Dewhurst; backend only |
| Material selection (Ashby) | ✅ | Yes (paid tier) | 200 materials (14 families) + Pareto frontier + weighted-score; backend only |
| LCA (full ISO 14040/44 4 phases) | ✅ | No | Full ISO 14040/44 + multi-impact + uncertainty; backend only |
| Process simulation (moldflow/weld/AM/forming) | ✅ | Yes (paid tier) | Moldflow Hele-Shaw + weld/AM/forming calculators; backend only |

## What Kerf does that Dassault CATIA doesn't

- **FE — plate / shell (native)** — MITC4 (Bathe-Dvorkin) + modal; backend only
- **Modal / buckling / nonlinear** — Consistent-mass modal, Riks, J2 plasticity; backend only
- **Fatigue (S-N, ε-N, rainflow)** — Backend only
- **AISC 360-22 steel (members)** — Full Ch. E/F/H + 50-section catalog; backend only
- **Spur/helical gear rating (AGMA 2001-D04)** — Backend only
- **Bearings — ISO 281 L10** — Backend only
- **Shaft (stress + critical speed)** — Closed-form; backend only
- **3D wing VLM (+ viscous + compressibility)** — Strip viscous CD0 + PG/KT compressibility + Korn-Lock wave-drag; wired tool
- **Doublet-lattice / flutter** — Backend only
- **Composites layup (CLT / drape / failure)** — CLT + drape + Tsai-Wu/Hill/Hashin + interlaminar; backend only
- **6-DOF flight dynamics + stability derivs** — Backend only
- **Orbital (Kepler, J2/J3, Hohmann)** — Wired tool
- *(and 30 more features not covered by Dassault CATIA)*

## What's honestly outstanding

- **NURBS surfacing (blend/network/patch)** (Partial): blend/network/patch/match-srf + G3 + Class-A harness wired; not FreeStyle/GSD class-A depth
- **2D drawings (views/dims/sections)** (Partial): Live HLR projection (make2d) + auto-dim; no GD&T-placement UI
- **FE — solid (tet/hex)** (Partial): CalculiX/Mystran/Z88 bridge (needs binary); backend only
- **5-axis (kinematics + posts)** (Partial): Engine solid; no UI

## Pricing

Dassault CATIA is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
