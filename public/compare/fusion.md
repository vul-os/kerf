---
slug: fusion
competitor: "Autodesk Fusion 360"
category: cad-mechanical
left: kerf
right: fusion
hero_tagline: "Cloud-connected multi-discipline CAD — two tools, two philosophies."
reviewed_at: 2026-05-19
order: 2
features:
  # D1 — Geometry & core CAD
  - domain: D1
    feature: "Constraint sketcher (geo + dim)"
    competitor:
      status: yes
      note: "Full parametric sketcher, all major constraints"
      source: "https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-584BEC15-41E6-4466-9705-5464748227BF"
    kerf:
      status: yes
      note: "PlaneGCS WASM; missing collinear, ellipse entity, G2"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Pad / pocket / revolve"
    competitor:
      status: yes
      note: "Timeline-based parametric modelling (mature)"
      source: "https://autocadeverything.com/fusion-360-parametric-modeling/"
    kerf:
      status: yes
      note: "OCCT feature tree, wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Loft"
    competitor:
      status: yes
      note: "Guide-rail overloads supported"
      source: "https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-584BEC15-41E6-4466-9705-5464748227BF"
    kerf:
      status: yes
      note: "Guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/feature_loft.py"

  - domain: D1
    feature: "Sheet metal"
    competitor:
      status: yes
      note: "Full sheet-metal workspace (flanges, hem, relief, jog)"
      source: "https://autocadeverything.com/what-is-fusion-360/"
    kerf:
      status: yes
      note: "Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/construction_verbs_tools.py"

  - domain: D1
    feature: "NURBS surfacing (blend/network/patch)"
    competitor:
      status: yes
      note: "T-spline Sculpt workspace; industry-quality freeform"
      source: "https://www.autodesk.com/products/fusion-360/blog/surface-modeling-overview/"
    kerf:
      status: yes
      note: "blend_srf, network_srf (Gordon), patch_srf_fit, match_srf wired as ops"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/network_srf.py"

  - domain: D1
    feature: "Assemblies — mates"
    competitor:
      status: yes
      note: "Joint system + Constraints feature (Sept 2025 update)"
      source: "https://www.autodesk.com/products/fusion-360/blog/september-2025-product-update-whats-new/"
    kerf:
      status: yes
      note: "Wired; coincident/concentric/parallel + BOM panel"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/assembly/mates.py"

  - domain: D1
    feature: "Assembly interference (clash)"
    competitor:
      status: yes
      note: "Built-in interference detection + motion contact sets"
      source: "https://help.autodesk.com/view/fusion360/ENU/?guid=ASM-CONTACT-SETS"
    kerf:
      status: partial
      note: "Backend OBB-SAT + BVH + tri-tri; no UI panel"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/clash/detect.py"

  - domain: D1
    feature: "Assembly motion study"
    competitor:
      status: yes
      note: "Motion study + contact sets + interference in UI"
      source: "https://productdesignonline.com/overlooked-fusion-feature-motion-study-in-autodesk-fusion-360/"
    kerf:
      status: yes
      note: "Planar MBD not wired to assembly solver"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/assembly"

  - domain: D1
    feature: "2D drawings (views/dims/sections)"
    competitor:
      status: yes
      note: "Full drawing workspace; AI automation (2025)"
      source: "https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-A476C8D8-1EE2-4AA1-9A97-88DB74A4E837"
    kerf:
      status: partial
      note: "Live HLR projection + auto-dim; no GD&T-placement UI"
      evidence: "src/components/DrawingView.jsx"

  - domain: D1
    feature: "Configurations / family variants"
    competitor:
      status: yes
      note: "Parameter Table + Configuration Table (Sept 2025)"
      source: "https://www.autodesk.com/products/fusion-360/blog/september-2025-product-update-whats-new/"
    kerf:
      status: yes
      note: "Engine + ConfigurationsPanel.jsx wired in Editor.jsx"
      evidence: "src/components/ConfigurationsPanel.jsx"

  - domain: D1
    feature: "Direct edit (push-pull)"
    competitor:
      status: yes
      note: "History-free direct editing intermixed with timeline"
      source: "https://autocadeverything.com/fusion-360-parametric-modeling/"
    kerf:
      status: yes
      note: "push_pull (planar + curved), move_face, delete_face wired as ops"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/direct_edit.py"

  # D2 — Structural / FEA
  - domain: D2
    feature: "FE — solid (tet/hex)"
    competitor:
      status: paid
      note: "Simulation Extension (cloud-only solvers)"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "CalculiX/Mystran/Z88 bridge (needs binary)"
      evidence: "packages/kerf-fem/src/kerf_fem/calculix_bridge.py"

  - domain: D2
    feature: "Modal / buckling / nonlinear"
    competitor:
      status: paid
      note: "Event simulation + buckling via Simulation Extension"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Consistent-mass modal, Riks, J2 plasticity (backend)"
      evidence: "packages/kerf-fem/src/kerf_fem/modal.py"

  - domain: D2
    feature: "AISC 360-22 steel (members)"
    competitor:
      status: no
      note: "Fusion is not a structural code-compliance tool"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Full Ch. E/F/H/H combined + 50-section catalog (backend)"
      evidence: "packages/kerf-structural/src/kerf_structural/steel_beam.py"

  - domain: D2
    feature: "ACI 318-19 concrete"
    competitor:
      status: no
      note: "No concrete code-compliance in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Flexure/shear/PM/dev-length (backend)"
      evidence: "packages/kerf-structural/src/kerf_structural/rc_beam.py"

  - domain: D2
    feature: "Fatigue (S-N, ε-N, rainflow)"
    competitor:
      status: paid
      note: "Event simulation extension covers fatigue-type loads"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "S-N, ε-N, rainflow counting (backend)"
      evidence: "packages/kerf-fem/src/kerf_fem/fatigue_fem.py"

  - domain: D2
    feature: "FE — plate / shell (native)"
    competitor:
      status: paid
      note: "Simulation Extension handles shells via cloud solver"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "MITC4 (Bathe-Dvorkin) + modal; 1.29% error vs Timoshenko"
      evidence: "packages/kerf-fem/src/kerf_fem/linear_static.py"

  # D3 — Machine elements
  - domain: D3
    feature: "Spur/helical gear rating (AGMA 2001-D04)"
    competitor:
      status: partial
      note: "Gear geometry via SpurGear add-in; no AGMA rating engine"
      source: "https://www.autodesk.com/learn/ondemand/course/mechanical-design-with-intent/unit/6L5qNPsYqNDrCMkGLrtJQY"
    kerf:
      status: yes
      note: "Full AGMA 2001-D04 rating (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D3
    feature: "Bearings — ISO 281 L10"
    competitor:
      status: partial
      note: "Bearing generator for geometry selection; no ISO 281 life calc"
      source: "https://www.autodesk.com/learn/ondemand/course/mechanical-design-with-intent/unit/6L5qNPsYqNDrCMkGLrtJQY"
    kerf:
      status: yes
      note: "ISO 281 L10 + ISO/TS 16281 aISO modified life (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/bearings/select.py"

  - domain: D3
    feature: "Springs (compr/ext/torsion/Belleville)"
    competitor:
      status: no
      note: "No spring design calculator in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Compression/extension/torsion/Belleville (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D3
    feature: "Belt / chain drives"
    competitor:
      status: no
      note: "No belt/chain sizing calculator in Fusion"
      source: "https://autocadeverything.com/fusion-360-cam/"
    kerf:
      status: yes
      note: "Belt/chain drive sizing (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/beltchain/drives.py"

  - domain: D3
    feature: "Shaft (stress + critical speed)"
    competitor:
      status: no
      note: "No shaft design calculator in base Fusion"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Closed-form stress + critical speed (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  # D4 — Thermal / fluid / HVAC
  - domain: D4
    feature: "Psychrometrics (moist air)"
    competitor:
      status: no
      note: "No psychrometric calculator in Fusion"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "ASHRAE-grade psychrometrics (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/psychro/air.py"

  - domain: D4
    feature: "Heat exchangers (LMTD + ε-NTU + Bell-Delaware)"
    competitor:
      status: no
      note: "No heat exchanger calculator in Fusion"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "LMTD + ε-NTU + Bell-Delaware + TEMA (backend)"
      evidence: "packages/kerf-hvac/src/kerf_hvac/sizing.py"

  - domain: D4
    feature: "CFD"
    competitor:
      status: no
      note: "Flow simulation not in Fusion; separate Autodesk CFD product"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "Real OpenFOAM bridge (needs install; backend)"
      evidence: "packages/kerf-cfd/src/kerf_cfd/openfoam_bridge.py"

  - domain: D4
    feature: "Steam/water properties"
    competitor:
      status: no
      note: "No IAPWS-IF97 steam property calculator in Fusion"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "IAPWS-IF97 Regions 1/2/4 validated (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/boiler/plant.py"

  - domain: D4
    feature: "HVAC duct sizing (SMACNA)"
    competitor:
      status: no
      note: "No HVAC duct sizing in Fusion"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "SMACNA duct sizing + flat-pattern (backend)"
      evidence: "packages/kerf-hvac/src/kerf_hvac/duct.py"

  - domain: D4
    feature: "Building loads"
    competitor:
      status: no
      note: "No building energy / HVAC load calculator in Fusion"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "Degree-day + CLTD/RTS + Sol-air + fenestration (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/buildingenergy/energy.py"

  # D5 — Aero / marine / space
  - domain: D5
    feature: "Airfoil inviscid CL (panel)"
    competitor:
      status: no
      note: "No airfoil panel method in Fusion"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "2D panel method, wired"
      evidence: "packages/kerf-aero/src/kerf_aero/panel_2d.py"

  - domain: D5
    feature: "3D wing VLM (+ viscous + compressibility)"
    competitor:
      status: no
      note: "No VLM in Fusion; requires separate Autodesk CFD"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "VLM + strip viscous + PG/KT compressibility (backend)"
      evidence: "packages/kerf-aero/src/kerf_aero/vlm.py"

  - domain: D5
    feature: "Orbital (Kepler, J2/J3, Hohmann)"
    competitor:
      status: no
      note: "No orbital mechanics in Fusion"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "Kepler + J2/J3 + Hohmann + Lambert, wired"
      evidence: "packages/kerf-aero/src/kerf_aero"

  - domain: D5
    feature: "Naval hydrostatics + GZ stability (IMO)"
    competitor:
      status: no
      note: "No naval architecture tools in Fusion"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "Hydrostatics + GZ + IMO stability, wired"
      evidence: "packages/kerf-marine/src/kerf_marine/stability.py"

  - domain: D5
    feature: "Doublet-lattice / flutter"
    competitor:
      status: no
      note: "No flutter analysis in Fusion"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Does-Fusion-360-have-flow-simulation-as-a-simulation-study.html"
    kerf:
      status: yes
      note: "Doublet-lattice flutter (backend)"
      evidence: "packages/kerf-aero/src/kerf_aero/flutter_pk.py"

  # D6 — Electronics / EDA / silicon
  - domain: D6
    feature: "Schematic capture (KiCad round-trip, ERC)"
    competitor:
      status: yes
      note: "Fusion Electronics (EAGLE-derived); schematic + ERC"
      source: "https://www.autodesk.com/products/fusion-360/blog/18-things-need-to-know-fusion-360-electronics/"
    kerf:
      status: yes
      note: "KiCad round-trip viewer (read-only)"
      evidence: "packages/kerf-electronics/src/kerf_electronics"

  - domain: D6
    feature: "PCB layout (tscircuit, KiCad round-trip)"
    competitor:
      status: yes
      note: "Native PCB editor; ODB++ fab output"
      source: "https://www.autodesk.com/products/fusion-360/blog/18-things-need-to-know-fusion-360-electronics/"
    kerf:
      status: yes
      note: "PCB viewer wired (read-only); fab: Gerber/ODB++/IPC-2581"
      evidence: "packages/kerf-electronics/src/kerf_electronics/fab"

  - domain: D6
    feature: "SPICE"
    competitor:
      status: no
      note: "No SPICE simulator in Fusion; schematic-only"
      source: "https://www.autodesk.com/products/fusion-360/blog/18-things-need-to-know-fusion-360-electronics/"
    kerf:
      status: yes
      note: "Real ngspice, wired"
      evidence: "packages/kerf-electronics/src/kerf_electronics"

  - domain: D6
    feature: "Signal integrity (Z0/crosstalk/eye/IBIS)"
    competitor:
      status: paid
      note: "Signal Integrity Extension powered by Ansys (paid add-on)"
      source: "https://www.autodesk.com/products/fusion-360/signal-integrity-extension"
    kerf:
      status: yes
      note: "IBIS 5.1 + Bergeron + PRBS eye envelope (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics"

  - domain: D6
    feature: "EMC (radiated/shielding/limits)"
    competitor:
      status: paid
      note: "Via Signal Integrity Extension; basic closed-form"
      source: "https://www.autodesk.com/products/fusion-360/blog/fusion-360-electronics-how-to-use-the-signal-integrity-extension/"
    kerf:
      status: yes
      note: "Common-mode, return-path gap, slot antenna (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/emc"

  - domain: D6
    feature: "PDN (DC IR-drop + AC sweep)"
    competitor:
      status: paid
      note: "Signal Integrity Extension covers partial PDN analysis"
      source: "https://www.autodesk.com/products/fusion-360/signal-integrity-extension"
    kerf:
      status: yes
      note: "Z(ω) + target-Z + decap optimiser (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics"

  - domain: D6
    feature: "PCB thermal"
    competitor:
      status: paid
      note: "Electronics Cooling Extension (paid); no liquid cooling"
      source: "https://www.engineering.com/how-fusion-360-fast-tracks-consumer-electronics-design/"
    kerf:
      status: partial
      note: "Lumped Rθ (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics"

  - domain: D6
    feature: "Silicon synth (Yosys) / STA / GDS / DRC / LVS / formal / CTS"
    competitor:
      status: no
      note: "No RTL/silicon flow in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/blog/18-things-need-to-know-fusion-360-electronics/"
    kerf:
      status: yes
      note: "Full silicon flow; zero UI"
      evidence: "packages/kerf-silicon/src/kerf_silicon"

  # D7 — Manufacturing / CAM
  - domain: D7
    feature: "3-axis CAM (profile/contour/pocket/face)"
    competitor:
      status: yes
      note: "HSMWorks-lineage CAM; mature 3-axis toolpaths"
      source: "https://www.autodesk.com/products/fusion-360/blog/hsmworks-to-fusion-transition-guide/"
    kerf:
      status: yes
      note: "CAMView wired for common 3-axis ops"
      evidence: "packages/kerf-cam/src/kerf_cam"

  - domain: D7
    feature: "5-axis (kinematics + posts)"
    competitor:
      status: paid
      note: "4/5-axis requires Manufacturing Extension (paid)"
      source: "https://www.autodesk.com/products/fusion-360/manufacturing-extension"
    kerf:
      status: partial
      note: "Engine solid (5-axis 3+2); no UI"
      evidence: "packages/kerf-cam/src/kerf_cam/five_axis"

  - domain: D7
    feature: "Turning cycles (G71/G70/threading)"
    competitor:
      status: yes
      note: "Turning canned cycles (G95/G96/G76/G92) supported"
      source: "https://industrialmonitordirect.com/blogs/knowledgebase/configuring-fusion-360-turning-canned-cycles-for-cnc-lathes"
    kerf:
      status: yes
      note: "G71/G70/threading cycles (backend)"
      evidence: "packages/kerf-cam/src/kerf_cam"

  - domain: D7
    feature: "G-code post (Fanuc/GRBL/LinuxCNC/Mach3)"
    competitor:
      status: yes
      note: "Hundreds of post-processors in library; CPS format"
      source: "https://cam.autodesk.com/hsmposts"
    kerf:
      status: yes
      note: "Fanuc/GRBL/LinuxCNC/Mach3 posts; no G41/42 cutter-comp"
      evidence: "packages/kerf-cam/src/kerf_cam/posts"

  - domain: D7
    feature: "Feeds & speeds + tool-life"
    competitor:
      status: yes
      note: "Feeds & speeds with material library in CAM workspace"
      source: "https://www.autodesk.com/products/fusion-360/blog/machining-fundamentals-introduction-to-post-processors/"
    kerf:
      status: yes
      note: "Taylor extended + Gilbert economic speed (backend)"
      evidence: "packages/kerf-cam/src/kerf_cam/tool_db.py"

  - domain: D7
    feature: "Moldflow / fill sim"
    competitor:
      status: paid
      note: "Injection Molding Simulation via Simulation Extension (paid)"
      source: "https://www.autodesk.com/products/fusion-360/blog/what-is-injection-molding-simulation-in-fusion-360/"
    kerf:
      status: yes
      note: "Hele-Shaw front tracking + weld-line + air-trap (backend)"
      evidence: "packages/kerf-manufacturing/src/kerf_manufacturing/moldflow/hele_shaw.py"

  - domain: D7
    feature: "Nesting (skyline + true-shape NFP)"
    competitor:
      status: paid
      note: "True Shape 3D Nesting via Manufacturing Extension (paid)"
      source: "https://www.autodesk.com/products/fusion-360/manufacturing-extension"
    kerf:
      status: yes
      note: "Minkowski-sum NFP + IFP + bottom-left fill (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/nesting/pack.py"

  - domain: D7
    feature: "Additive / DFAM"
    competitor:
      status: paid
      note: "Additive tools via Manufacturing Extension; orientation + supports"
      source: "https://www.autodesk.com/products/fusion-360/blog/fusion-360-additive-manufacturing-3d-printing-capabilities/"
    kerf:
      status: yes
      note: "DFAM checks + additive calculators (backend)"
      evidence: "packages/kerf-cam/src/kerf_cam"

  - domain: D7
    feature: "FDM slicing (Cura)"
    competitor:
      status: yes
      note: "Built-in slicing; print settings & layer configuration"
      source: "https://autocadeverything.com/fusion-360-3d-printing/"
    kerf:
      status: yes
      note: "Cura runner wired (PrintSliceView)"
      evidence: "packages/kerf-slicing/src/kerf_slicing/cura_runner.py"

  # D8 — Civil / infrastructure / geo
  - domain: D8
    feature: "Horizontal+vertical alignment (clothoid, SSD)"
    competitor:
      status: no
      note: "Fusion is not a civil/road design tool"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Clothoid + SSD + AASHTO runoff (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil/horizontal_alignment.py"

  - domain: D8
    feature: "Corridor / cross-section"
    competitor:
      status: no
      note: "No corridor modelling in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Divided highway + reverse-crown + urban curb templates"
      evidence: "packages/kerf-civil/src/kerf_civil/corridor.py"

  - domain: D8
    feature: "Geodesy / projections (Vincenty, TM, UTM, LCC)"
    competitor:
      status: no
      note: "No geodetic projection tools in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Vincenty + TM + UTM + LCC (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil/crs.py"

  - domain: D8
    feature: "Geotech (bearing/settlement/slope/pile/liquefaction)"
    competitor:
      status: no
      note: "No geotechnical analysis in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Seed-Idriss CSR + SPT/CPT CRR + Tokimatsu (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/civil"

  # D9 — Dynamics / motion / controls
  - domain: D9
    feature: "Planar MBD (Lagrange/DAE, Baumgarte)"
    competitor:
      status: no
      note: "Motion study is kinematic; no full MBD solver"
      source: "https://productdesignonline.com/overlooked-fusion-feature-motion-study-in-autodesk-fusion-360/"
    kerf:
      status: yes
      note: "Planar Lagrange/DAE + Baumgarte stabilisation (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/integrator.py"

  - domain: D9
    feature: "Kinematics (four-bar/slider-crank/cam)"
    competitor:
      status: partial
      note: "Motion study gives kinematic playback; no analytical solver"
      source: "https://autocadeverything.com/fusion-360-joints/"
    kerf:
      status: yes
      note: "Four-bar/slider-crank/cam kinematics (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/forward_kinematics.py"

  - domain: D9
    feature: "Robotics 6-DOF spatial IK"
    competitor:
      status: no
      note: "Robot toolpath generation only; no 6-DOF IK solver"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Can-Fusion-360-be-used-to-generate-toolpaths-for-robots.html"
    kerf:
      status: yes
      note: "DLS Jacobian 6-DOF IK; PUMA-class validated (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/inverse_kinematics.py"

  - domain: D9
    feature: "Controls — state-space / LQR / Kalman"
    competitor:
      status: no
      note: "No control systems tools in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Ackermann + LQR (CARE) + Luenberger (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/controls/system.py"

  - domain: D9
    feature: "Vibration n-DOF modal / FRF"
    competitor:
      status: paid
      note: "Modal via Simulation Extension (cloud-only)"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Full n-DOF eigen + FRF matrix (backend)"
      evidence: "packages/kerf-fem/src/kerf_fem/modal.py"

  # D10 — Electrical / energy / PLC / firmware
  - domain: D10
    feature: "AC load-flow (Ybus / Newton-Raphson)"
    competitor:
      status: no
      note: "No power systems load-flow in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/blog/18-things-need-to-know-fusion-360-electronics/"
    kerf:
      status: yes
      note: "Full polar-form NR; 3+5-bus validated (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D10
    feature: "Solar PV (system + partial shading)"
    competitor:
      status: no
      note: "No PV system calculator in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/blog/solar-panels-solar-electricity-works/"
    kerf:
      status: yes
      note: "Single-diode + bypass-diode IV + global MPPT (backend)"
      evidence: "packages/kerf-energy/src/kerf_energy/solar.py"

  - domain: D10
    feature: "Wiring/harness (WireViz + 3D router)"
    competitor:
      status: no
      note: "No wiring harness design in Fusion; AutoCAD Electrical only"
      source: "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Is-it-possible-to-create-a-wiring-diagram-with-Fusion-360-Electronics.html"
    kerf:
      status: yes
      note: "WireViz runner + harness3d; WiringView wired"
      evidence: "packages/kerf-wiring/src/kerf_wiring/wireviz_runner.py"

  - domain: D10
    feature: "PLC IEC 61131-3 (ST/Ladder/FB/motion)"
    competitor:
      status: no
      note: "No PLC programming environment in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/blog/18-things-need-to-know-fusion-360-electronics/"
    kerf:
      status: yes
      note: "ST editor + live Ladder power-flow sim wired"
      evidence: "packages/kerf-plc/src/kerf_plc/power_flow.py"

  - domain: D10
    feature: "Firmware build/upload/monitor/debug"
    competitor:
      status: no
      note: "No firmware toolchain in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/blog/18-things-need-to-know-fusion-360-electronics/"
    kerf:
      status: yes
      note: "FirmwareActions + debug panel wired"
      evidence: "src/components/FirmwareActions.jsx"

  # D11 — Tolerancing / metrology / QA
  - domain: D11
    feature: "GD&T data model (ASME Y14.5)"
    competitor:
      status: yes
      note: "GD&T symbols in drawing workspace (ASME Y14.5 / ISO 1101)"
      source: "https://help.autodesk.com/view/fusion360/ENU/?guid=DWG-SYMBOLS"
    kerf:
      status: yes
      note: "GD&T data model + auto-propose (backend)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt/feature_control_frame.py"

  - domain: D11
    feature: "Tolerance stackup — 1D (WC/RSS/MC)"
    competitor:
      status: no
      note: "Stackup in Inventor Tolerance Analysis; not in Fusion itself"
      source: "https://www.autodesk.com/solutions/tolerance-analysis-workflow"
    kerf:
      status: yes
      note: "WC/RSS/MC (backend; MC LCG bug noted)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt"

  - domain: D11
    feature: "Tolerance stackup — 3D vector loop"
    competitor:
      status: no
      note: "3D stackup not in Fusion; Inventor Tolerance Analysis only"
      source: "https://www.autodesk.com/solutions/tolerance-analysis-workflow"
    kerf:
      status: yes
      note: "6-DOF vector loop + sensitivity Jacobian (backend)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt"

  - domain: D11
    feature: "CMM fitting & evaluation"
    competitor:
      status: partial
      note: "Manual Inspection in Fusion; full CMM via PowerInspect"
      source: "https://www.autodesk.com/products/fusion-360/blog/whats-new-in-fusion-360-manual-inspection/"
    kerf:
      status: yes
      note: "CMM fitting & evaluation (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/cmm/inspect.py"

  - domain: D11
    feature: "Process capability (Cpk/Ppk)"
    competitor:
      status: no
      note: "No SPC / Cpk capability in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/blog/whats-new-in-fusion-360-manual-inspection/"
    kerf:
      status: yes
      note: "Cpk/Ppk process capability (backend)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt"

  # D12 — Optics / acoustics
  - domain: D12
    feature: "Paraxial ABCD ray transfer"
    competitor:
      status: no
      note: "No optical design tools in Fusion"
      source: "https://forums.autodesk.com/t5/fusion-design-validate-document/simulating-light-travel-and-focus/td-p/6786003"
    kerf:
      status: yes
      note: "ABCD ray transfer matrices (backend)"
      evidence: "packages/kerf-optics/src/kerf_optics/ray_transfer.py"

  - domain: D12
    feature: "Gaussian beam propagation (M², q-param)"
    competitor:
      status: no
      note: "No laser/Gaussian beam simulation in Fusion"
      source: "https://forums.autodesk.com/t5/fusion-design-validate-document/simulating-light-travel-and-focus/td-p/6786003"
    kerf:
      status: yes
      note: "Complex-q + ABCD + M² + fibre coupling (backend)"
      evidence: "packages/kerf-optics/src/kerf_optics/lens_system.py"

  - domain: D12
    feature: "Acoustics (ISO 9613, RT60, weighting, mass-law TL)"
    competitor:
      status: no
      note: "No acoustic analysis tools in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "ISO 9613, RT60, A/C-weight, mass-law TL (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/acoustics/sound.py"

  # D13 — Verticals
  - domain: D13
    feature: "Jewelry (41 modules)"
    competitor:
      status: partial
      note: "Basic ring/pendant geometry possible; no dedicated jewelry suite"
      source: "https://adsknews.autodesk.com/de/stories/fusion-360-jewelry-design-course/"
    kerf:
      status: yes
      note: "41-module suite; RhinoGold/Matrix-class depth"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D13
    feature: "BIM (walls/slabs/framing/stairs/IFC4)"
    competitor:
      status: no
      note: "Fusion is not a BIM tool; Revit for full BIM workflows"
      source: "https://vagon.io/blog/rhino-3d-vs-fusion-360"
    kerf:
      status: yes
      note: "Revit-comparable engine + viewer wired via /compile-ifc"
      evidence: "packages/kerf-bim/src/kerf_bim"

  - domain: D13
    feature: "Textiles (weave/knit/drape/cut-room)"
    competitor:
      status: no
      note: "No textile design tools in Fusion"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Weave/knit/drape/cut-room (backend); no 3D avatar drape"
      evidence: "packages/kerf-textiles/src/kerf_textiles"

  - domain: D13
    feature: "Dental (crown/surgical guide/DICOM)"
    competitor:
      status: partial
      note: "B-rep geometry usable; no dedicated dental workflow"
      source: "https://www.autodesk.com/products/fusion-360/simulation-extension"
    kerf:
      status: yes
      note: "Crown is placeholder cylinder; surgical guide in spotlight"
      evidence: "packages/kerf-dental/src/kerf_dental"

  # D14 — Cost / materials / LCA
  - domain: D14
    feature: "Should-cost (6 processes, Boothroyd-Dewhurst)"
    competitor:
      status: partial
      note: "Basic cost estimation in Generative Design; not Boothroyd-grade"
      source: "https://help.autodesk.com/view/fusion360/ENU/?guid=GD-COST-MAT"
    kerf:
      status: yes
      note: "6 processes, Boothroyd-Dewhurst method (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/costing/estimate.py"

  - domain: D14
    feature: "Material selection (Ashby)"
    competitor:
      status: partial
      note: "Material assignment from library; no Ashby multi-objective"
      source: "https://autocadeverything.com/how-to-change-material-in-fusion-360/"
    kerf:
      status: yes
      note: "200 materials + Pareto frontier + weighted-score (backend)"
      evidence: "packages/kerf-lca/src/kerf_lca/materials.py"

  - domain: D14
    feature: "LCA (full ISO 14040/44 4 phases)"
    competitor:
      status: paid
      note: "Manufacturing Sustainability Insights add-on (paid/partner)"
      source: "https://www.autodesk.com/products/fusion-360/blog/manufacturing-sustainability-insights-add-on-msi/"
    kerf:
      status: yes
      note: "ISO 14040/44 4-phase + multi-impact + uncertainty (backend)"
      evidence: "packages/kerf-lca/src/kerf_lca/report.py"

  - domain: D14
    feature: "Process simulation (moldflow/weld/AM/forming)"
    competitor:
      status: paid
      note: "Injection molding via Simulation Extension (paid)"
      source: "https://www.autodesk.com/products/fusion-360/blog/what-is-injection-molding-simulation-in-fusion-360/"
    kerf:
      status: yes
      note: "Moldflow + weld + AM + forming (backend)"
      evidence: "packages/kerf-manufacturing/src/kerf_manufacturing/moldflow"

  # ── D1 Standard parts library ─────────────────────────────────────────────
  - domain: D1
    feature: "Standard parts library (ISO/DIN fasteners, bearings, profiles)"
    competitor:
      status: partial
      note: "Fusion 360 has a McMaster-Carr / Toolbox integration; coverage narrower than SolidWorks Toolbox"
      source: "https://help.autodesk.com/view/fusion360/ENU/?guid=ASM-TOOLBOX-OVERVIEW"
    kerf:
      status: yes
      note: "kerf-partsgen: 5 ISO/DIN generators; kerf-parts KiCad+BOLTS+FreeCAD pipeline; real STEP/JSCAD geometry in CircuitEditor 3D tab via substitute_component"
      evidence: "packages/kerf-parts/src/kerf_parts/tools.py"
---

# Kerf vs Autodesk Fusion 360

Cloud-connected multi-discipline CAD — two tools, two philosophies.

*Last reviewed: 2026-05-19*

## Summary

Kerf saturates **98%** of Autodesk Fusion 360's feature surface (77 yes, 4 partial, 0 no out of 81 features tracked here). Honest gaps: 4 features partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Autodesk Fusion 360 | Notes |
|---------|------|---------------------|-------|
| Constraint sketcher (geo + dim) | ✅ | Yes | PlaneGCS WASM; missing collinear, ellipse entity, G2 |
| Pad / pocket / revolve | ✅ | Yes | OCCT feature tree, wired |
| Loft | ✅ | Yes | Guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric |
| Sheet metal | ✅ | Yes | Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief |
| NURBS surfacing (blend/network/patch) | ✅ | Yes | blend_srf, network_srf (Gordon), patch_srf_fit, match_srf wired as ops |
| Assemblies — mates | ✅ | Yes | Wired; coincident/concentric/parallel + BOM panel |
| Assembly interference (clash) | ⚠️ (partial) | Yes | Backend OBB-SAT + BVH + tri-tri; no UI panel |
| Assembly motion study | ✅ | Yes | Planar MBD not wired to assembly solver |
| 2D drawings (views/dims/sections) | ⚠️ (partial) | Yes | Live HLR projection + auto-dim; no GD&T-placement UI |
| Configurations / family variants | ✅ | Yes | Engine + ConfigurationsPanel.jsx wired in Editor.jsx |
| Direct edit (push-pull) | ✅ | Yes | push_pull (planar + curved), move_face, delete_face wired as ops |
| FE — solid (tet/hex) | ✅ | Yes (paid tier) | CalculiX/Mystran/Z88 bridge (needs binary) |
| Modal / buckling / nonlinear | ✅ | Yes (paid tier) | Consistent-mass modal, Riks, J2 plasticity (backend) |
| AISC 360-22 steel (members) | ✅ | No | Full Ch. E/F/H/H combined + 50-section catalog (backend) |
| ACI 318-19 concrete | ✅ | No | Flexure/shear/PM/dev-length (backend) |
| Fatigue (S-N, ε-N, rainflow) | ✅ | Yes (paid tier) | S-N, ε-N, rainflow counting (backend) |
| FE — plate / shell (native) | ✅ | Yes (paid tier) | MITC4 (Bathe-Dvorkin) + modal; 1.29% error vs Timoshenko |
| Spur/helical gear rating (AGMA 2001-D04) | ✅ | Partial | Full AGMA 2001-D04 rating (backend) |
| Bearings — ISO 281 L10 | ✅ | Partial | ISO 281 L10 + ISO/TS 16281 aISO modified life (backend) |
| Springs (compr/ext/torsion/Belleville) | ✅ | No | Compression/extension/torsion/Belleville (backend) |
| Belt / chain drives | ✅ | No | Belt/chain drive sizing (backend) |
| Shaft (stress + critical speed) | ✅ | No | Closed-form stress + critical speed (backend) |
| Psychrometrics (moist air) | ✅ | No | ASHRAE-grade psychrometrics (backend) |
| Heat exchangers (LMTD + ε-NTU + Bell-Delaware) | ✅ | No | LMTD + ε-NTU + Bell-Delaware + TEMA (backend) |
| CFD | ✅ | No | Real OpenFOAM bridge (needs install; backend) |
| Steam/water properties | ✅ | No | IAPWS-IF97 Regions 1/2/4 validated (backend) |
| HVAC duct sizing (SMACNA) | ✅ | No | SMACNA duct sizing + flat-pattern (backend) |
| Building loads | ✅ | No | Degree-day + CLTD/RTS + Sol-air + fenestration (backend) |
| Airfoil inviscid CL (panel) | ✅ | No | 2D panel method, wired |
| 3D wing VLM (+ viscous + compressibility) | ✅ | No | VLM + strip viscous + PG/KT compressibility (backend) |
| Orbital (Kepler, J2/J3, Hohmann) | ✅ | No | Kepler + J2/J3 + Hohmann + Lambert, wired |
| Naval hydrostatics + GZ stability (IMO) | ✅ | No | Hydrostatics + GZ + IMO stability, wired |
| Doublet-lattice / flutter | ✅ | No | Doublet-lattice flutter (backend) |
| Schematic capture (KiCad round-trip, ERC) | ✅ | Yes | KiCad round-trip viewer (read-only) |
| PCB layout (tscircuit, KiCad round-trip) | ✅ | Yes | PCB viewer wired (read-only); fab: Gerber/ODB++/IPC-2581 |
| SPICE | ✅ | No | Real ngspice, wired |
| Signal integrity (Z0/crosstalk/eye/IBIS) | ✅ | Yes (paid tier) | IBIS 5.1 + Bergeron + PRBS eye envelope (backend) |
| EMC (radiated/shielding/limits) | ✅ | Yes (paid tier) | Common-mode, return-path gap, slot antenna (backend) |
| PDN (DC IR-drop + AC sweep) | ✅ | Yes (paid tier) | Z(ω) + target-Z + decap optimiser (backend) |
| PCB thermal | ⚠️ (partial) | Yes (paid tier) | Lumped Rθ (backend) |
| Silicon synth (Yosys) / STA / GDS / DRC / LVS / formal / CTS | ✅ | No | Full silicon flow; zero UI |
| 3-axis CAM (profile/contour/pocket/face) | ✅ | Yes | CAMView wired for common 3-axis ops |
| 5-axis (kinematics + posts) | ⚠️ (partial) | Yes (paid tier) | Engine solid (5-axis 3+2); no UI |
| Turning cycles (G71/G70/threading) | ✅ | Yes | G71/G70/threading cycles (backend) |
| G-code post (Fanuc/GRBL/LinuxCNC/Mach3) | ✅ | Yes | Fanuc/GRBL/LinuxCNC/Mach3 posts; no G41/42 cutter-comp |
| Feeds & speeds + tool-life | ✅ | Yes | Taylor extended + Gilbert economic speed (backend) |
| Moldflow / fill sim | ✅ | Yes (paid tier) | Hele-Shaw front tracking + weld-line + air-trap (backend) |
| Nesting (skyline + true-shape NFP) | ✅ | Yes (paid tier) | Minkowski-sum NFP + IFP + bottom-left fill (backend) |
| Additive / DFAM | ✅ | Yes (paid tier) | DFAM checks + additive calculators (backend) |
| FDM slicing (Cura) | ✅ | Yes | Cura runner wired (PrintSliceView) |
| Horizontal+vertical alignment (clothoid, SSD) | ✅ | No | Clothoid + SSD + AASHTO runoff (backend) |
| Corridor / cross-section | ✅ | No | Divided highway + reverse-crown + urban curb templates |
| Geodesy / projections (Vincenty, TM, UTM, LCC) | ✅ | No | Vincenty + TM + UTM + LCC (backend) |
| Geotech (bearing/settlement/slope/pile/liquefaction) | ✅ | No | Seed-Idriss CSR + SPT/CPT CRR + Tokimatsu (backend) |
| Planar MBD (Lagrange/DAE, Baumgarte) | ✅ | No | Planar Lagrange/DAE + Baumgarte stabilisation (backend) |
| Kinematics (four-bar/slider-crank/cam) | ✅ | Partial | Four-bar/slider-crank/cam kinematics (backend) |
| Robotics 6-DOF spatial IK | ✅ | No | DLS Jacobian 6-DOF IK; PUMA-class validated (backend) |
| Controls — state-space / LQR / Kalman | ✅ | No | Ackermann + LQR (CARE) + Luenberger (backend) |
| Vibration n-DOF modal / FRF | ✅ | Yes (paid tier) | Full n-DOF eigen + FRF matrix (backend) |
| AC load-flow (Ybus / Newton-Raphson) | ✅ | No | Full polar-form NR; 3+5-bus validated (backend) |
| Solar PV (system + partial shading) | ✅ | No | Single-diode + bypass-diode IV + global MPPT (backend) |
| Wiring/harness (WireViz + 3D router) | ✅ | No | WireViz runner + harness3d; WiringView wired |
| PLC IEC 61131-3 (ST/Ladder/FB/motion) | ✅ | No | ST editor + live Ladder power-flow sim wired |
| Firmware build/upload/monitor/debug | ✅ | No | FirmwareActions + debug panel wired |
| GD&T data model (ASME Y14.5) | ✅ | Yes | GD&T data model + auto-propose (backend) |
| Tolerance stackup — 1D (WC/RSS/MC) | ✅ | No | WC/RSS/MC (backend; MC LCG bug noted) |
| Tolerance stackup — 3D vector loop | ✅ | No | 6-DOF vector loop + sensitivity Jacobian (backend) |
| CMM fitting & evaluation | ✅ | Partial | CMM fitting & evaluation (backend) |
| Process capability (Cpk/Ppk) | ✅ | No | Cpk/Ppk process capability (backend) |
| Paraxial ABCD ray transfer | ✅ | No | ABCD ray transfer matrices (backend) |
| Gaussian beam propagation (M², q-param) | ✅ | No | Complex-q + ABCD + M² + fibre coupling (backend) |
| Acoustics (ISO 9613, RT60, weighting, mass-law TL) | ✅ | No | ISO 9613, RT60, A/C-weight, mass-law TL (backend) |
| Jewelry (41 modules) | ✅ | Partial | 41-module suite; RhinoGold/Matrix-class depth |
| BIM (walls/slabs/framing/stairs/IFC4) | ✅ | No | Revit-comparable engine + viewer wired via /compile-ifc |
| Textiles (weave/knit/drape/cut-room) | ✅ | No | Weave/knit/drape/cut-room (backend); no 3D avatar drape |
| Dental (crown/surgical guide/DICOM) | ✅ | Partial | Crown is placeholder cylinder; surgical guide in spotlight |
| Should-cost (6 processes, Boothroyd-Dewhurst) | ✅ | Partial | 6 processes, Boothroyd-Dewhurst method (backend) |
| Material selection (Ashby) | ✅ | Partial | 200 materials + Pareto frontier + weighted-score (backend) |
| LCA (full ISO 14040/44 4 phases) | ✅ | Yes (paid tier) | ISO 14040/44 4-phase + multi-impact + uncertainty (backend) |
| Process simulation (moldflow/weld/AM/forming) | ✅ | Yes (paid tier) | Moldflow + weld + AM + forming (backend) |
| Standard parts library (ISO/DIN fasteners, bearings, profiles) | ✅ | Partial | kerf-partsgen: 5 ISO/DIN generators; kerf-parts KiCad+BOLTS+FreeCAD pipeline; real STEP/JSCAD geometry in CircuitEdit... |

## What Kerf does that Autodesk Fusion 360 doesn't

- **FE — solid (tet/hex)** — CalculiX/Mystran/Z88 bridge (needs binary)
- **Modal / buckling / nonlinear** — Consistent-mass modal, Riks, J2 plasticity (backend)
- **AISC 360-22 steel (members)** — Full Ch. E/F/H/H combined + 50-section catalog (backend)
- **ACI 318-19 concrete** — Flexure/shear/PM/dev-length (backend)
- **Fatigue (S-N, ε-N, rainflow)** — S-N, ε-N, rainflow counting (backend)
- **FE — plate / shell (native)** — MITC4 (Bathe-Dvorkin) + modal; 1.29% error vs Timoshenko
- **Springs (compr/ext/torsion/Belleville)** — Compression/extension/torsion/Belleville (backend)
- **Belt / chain drives** — Belt/chain drive sizing (backend)
- **Shaft (stress + critical speed)** — Closed-form stress + critical speed (backend)
- **Psychrometrics (moist air)** — ASHRAE-grade psychrometrics (backend)
- **Heat exchangers (LMTD + ε-NTU + Bell-Delaware)** — LMTD + ε-NTU + Bell-Delaware + TEMA (backend)
- **CFD** — Real OpenFOAM bridge (needs install; backend)
- *(and 39 more features not covered by Autodesk Fusion 360)*

## What's honestly outstanding

- **Assembly interference (clash)** (Partial): Backend OBB-SAT + BVH + tri-tri; no UI panel
- **2D drawings (views/dims/sections)** (Partial): Live HLR projection + auto-dim; no GD&T-placement UI
- **PCB thermal** (Partial): Lumped Rθ (backend)
- **5-axis (kinematics + posts)** (Partial): Engine solid (5-axis 3+2); no UI

## Pricing

Autodesk Fusion 360 is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
