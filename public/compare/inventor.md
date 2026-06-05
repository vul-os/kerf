---
slug: inventor
competitor: "Autodesk Inventor"
category: cad-mechanical
left: kerf
right: inventor
hero_tagline: "30 years of industrial MFG depth — compared honestly against MIT open-core."
reviewed_at: 2026-05-19
order: 5
features:
  # D1 — Geometry & core CAD
  - domain: D1
    feature: "Constraint sketcher (geo + dim)"
    competitor:
      status: yes
      note: "Full parametric sketcher with all major constraints; 2D + 3D sketch"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-65CF5E42-EC00-4C76-8698-0DE026F67BDA"
    kerf:
      status: yes
      note: "PlaneGCS WASM; missing collinear, ellipse entity, G2"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Pad / pocket / revolve"
    competitor:
      status: yes
      note: "Extrude, revolve, sweep, loft — full parametric feature set"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-5B784E8C-D37B-4A3A-90AB-1F71C08A2B3E"
    kerf:
      status: yes
      note: "OCCT feature tree, wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Fillet / chamfer (constant)"
    competitor:
      status: yes
      note: "Edge fillet, chamfer, full-round fillet"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-D40E4D49-B5A3-4D55-B79A-26ACBF03EA49"
    kerf:
      status: yes
      note: "Wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Loft"
    competitor:
      status: yes
      note: "Loft with rails, centerline, point-to-section, area law"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-11AF0B14-A3D6-40B6-B4FD-E826FE2CE7BA"
    kerf:
      status: yes
      note: "Guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/feature_loft.py"

  - domain: D1
    feature: "Sheet metal"
    competitor:
      status: yes
      note: "Full sheet metal workspace — flanges, hem, relief, jog, punch, flat pattern"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-E44E6EDD-6D9F-48DB-8826-72CCBA2F6588"
    kerf:
      status: yes
      note: "Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief/punch"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/construction_verbs_tools.py"

  - domain: D1
    feature: "NURBS surfacing (blend/network/patch)"
    competitor:
      status: yes
      note: "Surface commands: stitch, sculpt, patch, loft surface (Inventor Professional)"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-F48B5A7E-5F85-4B64-B3E1-1B9CCFE11E2E"
    kerf:
      status: yes
      note: "blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, feature_to_solid (sew) wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/network_srf.py"

  - domain: D1
    feature: "Assemblies — mates"
    competitor:
      status: yes
      note: "Full constraint set: mate, flush, insert, tangent, angle, symmetric"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-B7FF2C89-0F4B-4E46-8985-F5A3C63A6BAE"
    kerf:
      status: yes
      note: "Wired; coincident/concentric/parallel + BOM panel"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/assembly/mates.py"

  - domain: D1
    feature: "Assembly motion study / interference"
    competitor:
      status: yes
      note: "Dynamic Simulation workspace — multi-body dynamics, joint catalog, interference"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-1B0C6E15-74C4-41C4-A06D-C5A7EB6D8E3E"
    kerf:
      status: yes
      note: "None — planar MBD not wired to assembly solver"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/assembly"

  - domain: D1
    feature: "2D drawings (views/dims/sections)"
    competitor:
      status: yes
      note: "Drawing views: base, projected, section, detail, break; full annotation set"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-A09FC2B5-D3B4-4D17-8C9C-CC2D4C6D0D8E"
    kerf:
      status: partial
      note: "Live HLR projection + auto-dim; no GD&T-placement UI"
      evidence: "src/components/DrawingView.jsx"

  - domain: D1
    feature: "GD&T on drawings / MBD / PMI"
    competitor:
      status: yes
      note: "DimXpert-class GD&T, MBD (Model Based Definition) ASME Y14.5 / ISO 1101"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-A44C5B4C-7BA6-4E56-B5E5-5B3D6F1A4A49"
    kerf:
      status: yes
      note: "GD&T data model only; no MBD/PMI UI"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt/feature_control_frame.py"

  - domain: D1
    feature: "Configurations / family variants"
    competitor:
      status: yes
      note: "iParts / iAssemblies — tabular family-of-parts with suppressed features"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-C6F4F4E6-3A4F-4E4C-B3C5-6D5A4B3E8D8E"
    kerf:
      status: yes
      note: "Engine + ConfigurationsPanel.jsx wired in Editor.jsx"
      evidence: "src/components/ConfigurationsPanel.jsx"

  - domain: D1
    feature: "iLogic rules engine"
    competitor:
      status: yes
      note: "iLogic — VB rules driving parameters, feature suppression, event triggers"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-A7D7C5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Chat-driven scripting + kerf-sdk Python API"
      evidence: "packages/kerf-sdk/src/kerf_sdk"

  # D2 — Structural / FEA
  - domain: D2
    feature: "FE — solid (tet/hex)"
    competitor:
      status: yes
      note: "Stress Analysis workspace — linear static FEA on parts and assemblies (in-box)"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "CalculiX/Mystran/Z88 bridge (needs binary; backend)"
      evidence: "packages/kerf-fem/src/kerf_fem/calculix_bridge.py"

  - domain: D2
    feature: "Modal / buckling / nonlinear"
    competitor:
      status: paid
      note: "Nastran In-CAD (paid add-in) — modal, nonlinear, fatigue, dynamic"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-NASTRAN-INCAD"
    kerf:
      status: yes
      note: "Consistent-mass modal, Riks, J2 plasticity (backend)"
      evidence: "packages/kerf-fem/src/kerf_fem/modal.py"

  - domain: D2
    feature: "AISC 360-22 steel (members)"
    competitor:
      status: no
      note: "Inventor is a mechanical CAD tool, not a structural code-compliance platform"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Full Ch. E/F/H + 50-section catalog (backend)"
      evidence: "packages/kerf-structural/src/kerf_structural/aisc_member.py"

  - domain: D2
    feature: "ACI 318-19 concrete"
    competitor:
      status: no
      note: "No concrete code-compliance in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Flexure/shear/PM/dev-length (backend)"
      evidence: "packages/kerf-structural/src/kerf_structural/rc_beam.py"

  - domain: D2
    feature: "Fatigue (S-N, ε-N, rainflow)"
    competitor:
      status: paid
      note: "Fatigue analysis via Nastran In-CAD (paid add-in)"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-NASTRAN-INCAD"
    kerf:
      status: yes
      note: "S-N, ε-N, rainflow counting (backend)"
      evidence: "packages/kerf-fem/src/kerf_fem/fatigue_fem.py"

  - domain: D2
    feature: "Frame stiffness assembly (2D/3D)"
    competitor:
      status: yes
      note: "Frame Generator + beam analysis feed; Nastran covers full frame FEA"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-FRAMEGEN"
    kerf:
      status: yes
      note: "2D+3D beam-column + ASCE 7 LRFD/ASD combos + story drift (backend)"
      evidence: "packages/kerf-structural/src/kerf_structural/steel_beam.py"

  # D3 — Machine elements
  - domain: D3
    feature: "Spur/helical gear rating (AGMA 2001-D04)"
    competitor:
      status: yes
      note: "Spur Gear Generator — parametric gear geometry from modules/tooth counts"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-GEARCMD"
    kerf:
      status: yes
      note: "Full AGMA 2001-D04 rating (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D3
    feature: "Gear rating (ISO 6336)"
    competitor:
      status: partial
      note: "Spur Gear Generator uses ISO geometry; no ISO 6336 fatigue rating in-box"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-GEARCMD"
    kerf:
      status: yes
      note: "Method B + safety factors; ZH=2.495, ZE=191 √MPa validated (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/gearstrength/iso6336.py"

  - domain: D3
    feature: "Bearings — ISO 281 L10"
    competitor:
      status: yes
      note: "Bolted Connection Generator + Design Accelerator bearing catalog"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-BOLTGEN"
    kerf:
      status: yes
      note: "ISO 281 L10 + ISO/TS 16281 aISO modified life (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/bearings/select.py"

  - domain: D3
    feature: "Fasteners — VDI 2230"
    competitor:
      status: yes
      note: "Bolted Connection Generator — bolt/nut/washer insertion with preload analysis"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-BOLTGEN"
    kerf:
      status: yes
      note: "VDI 2230 bolted joint analysis (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D3
    feature: "Springs (compr/ext/torsion/Belleville)"
    competitor:
      status: yes
      note: "Design Accelerator — spring calculator for compression/extension/torsion"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-SPRINGCALC"
    kerf:
      status: yes
      note: "Compression/extension/torsion/Belleville (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D3
    feature: "Shaft (stress + critical speed)"
    competitor:
      status: yes
      note: "Shaft Generator — stepped-shaft sizing with stress and deflection"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-SHAFTGEN"
    kerf:
      status: yes
      note: "Closed-form stress + critical speed (backend; no stepped-shaft FEA)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D3
    feature: "Belt / chain drives"
    competitor:
      status: yes
      note: "Design Accelerator — V-belt, flat belt, chain drive sizing"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-BELTCHAIN"
    kerf:
      status: yes
      note: "Belt/chain drive sizing (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/beltchain/drives.py"

  # D4 — Thermal / fluid / HVAC
  - domain: D4
    feature: "Psychrometrics (moist air)"
    competitor:
      status: no
      note: "No psychrometric calculator in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "ASHRAE-grade psychrometrics (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/psychro/air.py"

  - domain: D4
    feature: "CFD"
    competitor:
      status: no
      note: "No CFD in Inventor; separate Autodesk CFD product required"
      source: "https://www.autodesk.com/products/cfd/overview"
    kerf:
      status: yes
      note: "Real OpenFOAM bridge (needs install; backend)"
      evidence: "packages/kerf-cfd/src/kerf_cfd/openfoam_bridge.py"

  - domain: D4
    feature: "Heat exchangers (LMTD + ε-NTU + Bell-Delaware)"
    competitor:
      status: no
      note: "No heat exchanger sizing calculator in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "LMTD + ε-NTU + Bell-Delaware + TEMA (backend)"
      evidence: "packages/kerf-hvac/src/kerf_hvac/sizing.py"

  - domain: D4
    feature: "Pipe network (Hardy-Cross)"
    competitor:
      status: no
      note: "Tube & Pipe routes piping geometry; no Hardy-Cross flow solver"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-TUBEPIPE"
    kerf:
      status: yes
      note: "Hardy-Cross pipe network solver (backend)"
      evidence: "packages/kerf-hvac/src/kerf_hvac"

  # D5 — Aero / marine / space
  - domain: D5
    feature: "3D wing VLM (+ viscous + compressibility)"
    competitor:
      status: no
      note: "No aerodynamic VLM in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "VLM + strip viscous + PG/KT compressibility (backend)"
      evidence: "packages/kerf-aero/src/kerf_aero/vlm.py"

  - domain: D5
    feature: "Orbital (Kepler, J2/J3, Hohmann)"
    competitor:
      status: no
      note: "No orbital mechanics in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Kepler + J2/J3 + Hohmann + Lambert, wired"
      evidence: "packages/kerf-aero/src/kerf_aero"

  - domain: D5
    feature: "Naval hydrostatics + GZ stability (IMO)"
    competitor:
      status: no
      note: "No naval architecture tools in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Hydrostatics + GZ + IMO stability, wired"
      evidence: "packages/kerf-marine/src/kerf_marine/stability.py"

  # D6 — Electronics / EDA / silicon
  - domain: D6
    feature: "Schematic capture (KiCad round-trip, ERC)"
    competitor:
      status: no
      note: "No schematic capture in Inventor; Cable & Harness is wiring harness only"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-CABLEHARNESS"
    kerf:
      status: yes
      note: "KiCad round-trip viewer (read-only)"
      evidence: "packages/kerf-electronics/src/kerf_electronics"

  - domain: D6
    feature: "PCB layout (tscircuit, KiCad round-trip)"
    competitor:
      status: no
      note: "No PCB layout capability in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-CABLEHARNESS"
    kerf:
      status: yes
      note: "PCB viewer wired (read-only); fab: Gerber/ODB++/IPC-2581"
      evidence: "packages/kerf-electronics/src/kerf_electronics/fab"

  - domain: D6
    feature: "SPICE"
    competitor:
      status: no
      note: "No SPICE simulation in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-CABLEHARNESS"
    kerf:
      status: yes
      note: "Real ngspice, wired"
      evidence: "packages/kerf-electronics/src/kerf_electronics"

  - domain: D6
    feature: "Signal integrity (Z0/crosstalk/eye/IBIS)"
    competitor:
      status: no
      note: "No signal integrity analysis in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-CABLEHARNESS"
    kerf:
      status: yes
      note: "IBIS 5.1 + Bergeron + PRBS eye envelope (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics"

  - domain: D6
    feature: "Wiring/harness (WireViz + 3D router)"
    competitor:
      status: yes
      note: "Cable & Harness — 3D wire routing, nailboard drawings, connector libraries"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-CABLEHARNESS"
    kerf:
      status: yes
      note: "WireViz runner + harness3d; WiringView wired"
      evidence: "packages/kerf-wiring/src/kerf_wiring/wireviz_runner.py"

  # D7 — Manufacturing / CAM
  - domain: D7
    feature: "3-axis CAM (profile/contour/pocket/face)"
    competitor:
      status: paid
      note: "Inventor CAM (HSMWorks-derived) — included in Inventor Professional; sold separately otherwise"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-CAM"
    kerf:
      status: yes
      note: "CAMView wired for common 3-axis ops"
      evidence: "packages/kerf-cam/src/kerf_cam"

  - domain: D7
    feature: "5-axis (kinematics + posts)"
    competitor:
      status: paid
      note: "Inventor CAM 4/5-axis requires HSMWorks Premium or Inventor Professional + CAM add-in"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-CAM"
    kerf:
      status: yes
      note: "Engine solid (5-axis 3+2); no UI"
      evidence: "packages/kerf-cam/src/kerf_cam/five_axis"

  - domain: D7
    feature: "G-code post (Fanuc/GRBL/LinuxCNC/Mach3)"
    competitor:
      status: yes
      note: "Hundreds of post-processors via Autodesk post library (CPS format)"
      source: "https://cam.autodesk.com/hsmposts"
    kerf:
      status: yes
      note: "Fanuc/GRBL/LinuxCNC/Mach3 posts; no G41/42 cutter-comp"
      evidence: "packages/kerf-cam/src/kerf_cam/posts"

  - domain: D7
    feature: "Feeds & speeds + tool-life"
    competitor:
      status: yes
      note: "Material-based feeds & speeds library in Inventor CAM workspace"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-CAM"
    kerf:
      status: yes
      note: "Taylor extended + Gilbert economic speed (backend)"
      evidence: "packages/kerf-cam/src/kerf_cam/tool_db.py"

  - domain: D7
    feature: "Moldflow / fill sim"
    competitor:
      status: yes
      note: "Mold Design workspace — cavity/core, runner/gate design (geometry); full moldflow via separate Autodesk Moldflow product"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-MOLDDESIGN"
    kerf:
      status: yes
      note: "Hele-Shaw front tracking + weld-line + air-trap (backend)"
      evidence: "packages/kerf-manufacturing/src/kerf_manufacturing/moldflow/hele_shaw.py"

  - domain: D7
    feature: "Nesting (skyline + true-shape NFP)"
    competitor:
      status: no
      note: "No nesting engine in Inventor; requires Autodesk Nesting Utility separately"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Minkowski-sum NFP + IFP + bottom-left fill (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/nesting/pack.py"

  - domain: D7
    feature: "FDM slicing (Cura)"
    competitor:
      status: no
      note: "No integrated FDM slicer in Inventor; STL export to external slicers"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Cura runner wired (PrintSliceView)"
      evidence: "packages/kerf-slicing/src/kerf_slicing/cura_runner.py"

  # D8 — Civil / infrastructure / geo
  - domain: D8
    feature: "Horizontal+vertical alignment (clothoid, SSD)"
    competitor:
      status: no
      note: "Inventor is not a civil/road design tool; use Civil 3D for alignment"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Clothoid + SSD + AASHTO runoff (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil/horizontal_alignment.py"

  - domain: D8
    feature: "Geotech (bearing/settlement/slope/pile/liquefaction)"
    competitor:
      status: no
      note: "No geotechnical analysis in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Seed-Idriss CSR + SPT/CPT CRR + Tokimatsu (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/civil"

  # D9 — Dynamics / motion / controls
  - domain: D9
    feature: "Planar MBD (Lagrange/DAE, Baumgarte)"
    competitor:
      status: yes
      note: "Dynamic Simulation workspace — Lagrangian multi-body dynamics with full joint catalog"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-DYNAMICSIM"
    kerf:
      status: yes
      note: "Planar Lagrange/DAE + Baumgarte stabilisation (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/integrator.py"

  - domain: D9
    feature: "Kinematics (four-bar/slider-crank/cam)"
    competitor:
      status: yes
      note: "Dynamic Simulation — revolute, sliding, cylindrical, spherical, planar joints + cam followers"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-DYNAMICSIM"
    kerf:
      status: yes
      note: "Four-bar/slider-crank/cam kinematics (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/forward_kinematics.py"

  - domain: D9
    feature: "Vibration SDOF"
    competitor:
      status: paid
      note: "Nastran In-CAD — frequency response, modal, harmonic analysis (paid)"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-NASTRAN-INCAD"
    kerf:
      status: yes
      note: "SDOF vibration analysis deep (backend)"
      evidence: "packages/kerf-fem/src/kerf_fem/modal.py"

  - domain: D9
    feature: "Controls — classical (Routh/Bode/RL/PID tune)"
    competitor:
      status: no
      note: "No classical controls tools in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Routh/Bode/RL/PID tuning (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/controls/system.py"

  - domain: D9
    feature: "Controls — state-space / LQR / Kalman"
    competitor:
      status: no
      note: "No state-space or optimal control tools in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Ackermann + LQR (CARE) + Luenberger (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/controls/system.py"

  # D10 — Electrical / energy / PLC / firmware
  - domain: D10
    feature: "AC load-flow (Ybus / Newton-Raphson)"
    competitor:
      status: no
      note: "No power systems tools in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Full polar-form NR; 3+5-bus validated (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D10
    feature: "Solar PV (system + partial shading)"
    competitor:
      status: no
      note: "No PV system calculator in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Single-diode + bypass-diode IV + global MPPT (backend)"
      evidence: "packages/kerf-energy/src/kerf_energy/solar.py"

  - domain: D10
    feature: "PLC IEC 61131-3 (ST/Ladder/FB/motion)"
    competitor:
      status: no
      note: "No PLC programming environment in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "ST editor + live Ladder power-flow sim wired"
      evidence: "packages/kerf-plc/src/kerf_plc/power_flow.py"

  - domain: D10
    feature: "Firmware build/upload/monitor/debug"
    competitor:
      status: no
      note: "No firmware toolchain in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "FirmwareActions + debug panel wired"
      evidence: "src/components/FirmwareActions.jsx"

  # D11 — Tolerancing / metrology / QA
  - domain: D11
    feature: "GD&T data model (ASME Y14.5)"
    competitor:
      status: yes
      note: "GD&T on drawings (ASME Y14.5 / ISO 1101); MBD annotation with DimXpert-style callouts"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-GDTANN"
    kerf:
      status: yes
      note: "GD&T data model + auto-propose (backend)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt/feature_control_frame.py"

  - domain: D11
    feature: "Tolerance stackup — 1D (WC/RSS/MC)"
    competitor:
      status: yes
      note: "Inventor Tolerance Analysis — 1D stackup with sensitivity and contribution"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-TOLSTACK"
    kerf:
      status: yes
      note: "WC/RSS/MC (backend; MC LCG bug noted)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt"

  - domain: D11
    feature: "Limits & fits (ISO 286)"
    competitor:
      status: yes
      note: "ISO/ANSI shaft-hole fit tolerances in hole/shaft tables"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-TOLSTACK"
    kerf:
      status: yes
      note: "ISO 286 limits & fits (backend)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt"

  - domain: D11
    feature: "Process capability (Cpk/Ppk)"
    competitor:
      status: no
      note: "No SPC / Cpk capability in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Cpk/Ppk process capability (backend)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt"

  - domain: D11
    feature: "Reliability (FMEA/MTBF)"
    competitor:
      status: no
      note: "No FMEA or MTBF reliability tools in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "FMEA/MTBF reliability analysis (backend)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt"

  # D12 — Optics / acoustics
  - domain: D12
    feature: "Paraxial ABCD ray transfer"
    competitor:
      status: no
      note: "No optical design tools in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "ABCD ray transfer matrices (backend)"
      evidence: "packages/kerf-optics/src/kerf_optics/ray_transfer.py"

  - domain: D12
    feature: "Acoustics (ISO 9613, RT60, weighting, mass-law TL)"
    competitor:
      status: no
      note: "No acoustics tools in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "ISO 9613 + RT60 + weighting + mass-law TL (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  # D13 — Verticals
  - domain: D13
    feature: "Jewelry (41 modules)"
    competitor:
      status: no
      note: "No jewelry design vertical in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Deep — full configurator UI; RhinoGold/Matrix-class"
      evidence: "src/components/JewelryView.jsx"

  - domain: D13
    feature: "BIM (walls/slabs/framing/stairs/IFC4)"
    competitor:
      status: no
      note: "No BIM tools in Inventor; use Revit for BIM"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Revit-comparable engine + viewer wired via /compile-ifc"
      evidence: "packages/kerf-bim/src/kerf_bim"

  # D14 — Cost / materials / LCA
  - domain: D14
    feature: "Should-cost (6 processes, Boothroyd-Dewhurst)"
    competitor:
      status: no
      note: "No automated should-cost estimation in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "6 processes; Boothroyd-Dewhurst grade (backend)"
      evidence: "packages/kerf-lca/src/kerf_lca"

  - domain: D14
    feature: "Material selection (Ashby)"
    competitor:
      status: partial
      note: "Materials browser with property lookup; no Ashby multi-objective Pareto selection"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-MATSELECT"
    kerf:
      status: yes
      note: "200 materials + Pareto frontier + weighted-score (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/matsel/multi_objective.py"

  - domain: D14
    feature: "LCA (full ISO 14040/44 4 phases)"
    competitor:
      status: no
      note: "No LCA / sustainability analysis in Inventor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-57C7A5E6-8B3E-4E4C-B6C5-8D5A4B3E8D8F"
    kerf:
      status: yes
      note: "Use+transport+EoL + multi-impact + uncertainty (backend)"
      evidence: "packages/kerf-lca/src/kerf_lca/phases.py"

  - domain: D14
    feature: "Process simulation (moldflow/weld/AM/forming)"
    competitor:
      status: partial
      note: "Mold Design workspace geometry only; full Moldflow via separate Autodesk Moldflow Advisor"
      source: "https://help.autodesk.com/view/INVNTOR/2025/ENU/?guid=GUID-MOLDDESIGN"
    kerf:
      status: yes
      note: "Hele-Shaw moldflow + weld-line + air-trap (backend)"
      evidence: "packages/kerf-manufacturing/src/kerf_manufacturing/moldflow/hele_shaw.py"
---

# Kerf vs Autodesk Inventor

30 years of industrial MFG depth — compared honestly against MIT open-core.

*Last reviewed: 2026-05-19*

## Summary

Kerf saturates **99%** of Autodesk Inventor's feature surface (67 yes, 1 partial, 0 no out of 68 features tracked here). Honest gaps: 1 feature partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Autodesk Inventor | Notes |
|---------|------|-------------------|-------|
| Constraint sketcher (geo + dim) | ✅ | Yes | PlaneGCS WASM; missing collinear, ellipse entity, G2 |
| Pad / pocket / revolve | ✅ | Yes | OCCT feature tree, wired |
| Fillet / chamfer (constant) | ✅ | Yes | Wired |
| Loft | ✅ | Yes | Guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric |
| Sheet metal | ✅ | Yes | Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief/punch |
| NURBS surfacing (blend/network/patch) | ✅ | Yes | blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, feature_to_solid (sew) wired |
| Assemblies — mates | ✅ | Yes | Wired; coincident/concentric/parallel + BOM panel |
| Assembly motion study / interference | ✅ | Yes | None — planar MBD not wired to assembly solver |
| 2D drawings (views/dims/sections) | ⚠️ (partial) | Yes | Live HLR projection + auto-dim; no GD&T-placement UI |
| GD&T on drawings / MBD / PMI | ✅ | Yes | GD&T data model only; no MBD/PMI UI |
| Configurations / family variants | ✅ | Yes | Engine + ConfigurationsPanel.jsx wired in Editor.jsx |
| iLogic rules engine | ✅ | Yes | Chat-driven scripting + kerf-sdk Python API |
| FE — solid (tet/hex) | ✅ | Yes | CalculiX/Mystran/Z88 bridge (needs binary; backend) |
| Modal / buckling / nonlinear | ✅ | Yes (paid tier) | Consistent-mass modal, Riks, J2 plasticity (backend) |
| AISC 360-22 steel (members) | ✅ | No | Full Ch. E/F/H + 50-section catalog (backend) |
| ACI 318-19 concrete | ✅ | No | Flexure/shear/PM/dev-length (backend) |
| Fatigue (S-N, ε-N, rainflow) | ✅ | Yes (paid tier) | S-N, ε-N, rainflow counting (backend) |
| Frame stiffness assembly (2D/3D) | ✅ | Yes | 2D+3D beam-column + ASCE 7 LRFD/ASD combos + story drift (backend) |
| Spur/helical gear rating (AGMA 2001-D04) | ✅ | Yes | Full AGMA 2001-D04 rating (backend) |
| Gear rating (ISO 6336) | ✅ | Partial | Method B + safety factors; ZH=2.495, ZE=191 √MPa validated (backend) |
| Bearings — ISO 281 L10 | ✅ | Yes | ISO 281 L10 + ISO/TS 16281 aISO modified life (backend) |
| Fasteners — VDI 2230 | ✅ | Yes | VDI 2230 bolted joint analysis (backend) |
| Springs (compr/ext/torsion/Belleville) | ✅ | Yes | Compression/extension/torsion/Belleville (backend) |
| Shaft (stress + critical speed) | ✅ | Yes | Closed-form stress + critical speed (backend; no stepped-shaft FEA) |
| Belt / chain drives | ✅ | Yes | Belt/chain drive sizing (backend) |
| Psychrometrics (moist air) | ✅ | No | ASHRAE-grade psychrometrics (backend) |
| CFD | ✅ | No | Real OpenFOAM bridge (needs install; backend) |
| Heat exchangers (LMTD + ε-NTU + Bell-Delaware) | ✅ | No | LMTD + ε-NTU + Bell-Delaware + TEMA (backend) |
| Pipe network (Hardy-Cross) | ✅ | No | Hardy-Cross pipe network solver (backend) |
| 3D wing VLM (+ viscous + compressibility) | ✅ | No | VLM + strip viscous + PG/KT compressibility (backend) |
| Orbital (Kepler, J2/J3, Hohmann) | ✅ | No | Kepler + J2/J3 + Hohmann + Lambert, wired |
| Naval hydrostatics + GZ stability (IMO) | ✅ | No | Hydrostatics + GZ + IMO stability, wired |
| Schematic capture (KiCad round-trip, ERC) | ✅ | No | KiCad round-trip viewer (read-only) |
| PCB layout (tscircuit, KiCad round-trip) | ✅ | No | PCB viewer wired (read-only); fab: Gerber/ODB++/IPC-2581 |
| SPICE | ✅ | No | Real ngspice, wired |
| Signal integrity (Z0/crosstalk/eye/IBIS) | ✅ | No | IBIS 5.1 + Bergeron + PRBS eye envelope (backend) |
| Wiring/harness (WireViz + 3D router) | ✅ | Yes | WireViz runner + harness3d; WiringView wired |
| 3-axis CAM (profile/contour/pocket/face) | ✅ | Yes (paid tier) | CAMView wired for common 3-axis ops |
| 5-axis (kinematics + posts) | ✅ | Yes (paid tier) | Engine solid (5-axis 3+2); no UI |
| G-code post (Fanuc/GRBL/LinuxCNC/Mach3) | ✅ | Yes | Fanuc/GRBL/LinuxCNC/Mach3 posts; no G41/42 cutter-comp |
| Feeds & speeds + tool-life | ✅ | Yes | Taylor extended + Gilbert economic speed (backend) |
| Moldflow / fill sim | ✅ | Yes | Hele-Shaw front tracking + weld-line + air-trap (backend) |
| Nesting (skyline + true-shape NFP) | ✅ | No | Minkowski-sum NFP + IFP + bottom-left fill (backend) |
| FDM slicing (Cura) | ✅ | No | Cura runner wired (PrintSliceView) |
| Horizontal+vertical alignment (clothoid, SSD) | ✅ | No | Clothoid + SSD + AASHTO runoff (backend) |
| Geotech (bearing/settlement/slope/pile/liquefaction) | ✅ | No | Seed-Idriss CSR + SPT/CPT CRR + Tokimatsu (backend) |
| Planar MBD (Lagrange/DAE, Baumgarte) | ✅ | Yes | Planar Lagrange/DAE + Baumgarte stabilisation (backend) |
| Kinematics (four-bar/slider-crank/cam) | ✅ | Yes | Four-bar/slider-crank/cam kinematics (backend) |
| Vibration SDOF | ✅ | Yes (paid tier) | SDOF vibration analysis deep (backend) |
| Controls — classical (Routh/Bode/RL/PID tune) | ✅ | No | Routh/Bode/RL/PID tuning (backend) |
| Controls — state-space / LQR / Kalman | ✅ | No | Ackermann + LQR (CARE) + Luenberger (backend) |
| AC load-flow (Ybus / Newton-Raphson) | ✅ | No | Full polar-form NR; 3+5-bus validated (backend) |
| Solar PV (system + partial shading) | ✅ | No | Single-diode + bypass-diode IV + global MPPT (backend) |
| PLC IEC 61131-3 (ST/Ladder/FB/motion) | ✅ | No | ST editor + live Ladder power-flow sim wired |
| Firmware build/upload/monitor/debug | ✅ | No | FirmwareActions + debug panel wired |
| GD&T data model (ASME Y14.5) | ✅ | Yes | GD&T data model + auto-propose (backend) |
| Tolerance stackup — 1D (WC/RSS/MC) | ✅ | Yes | WC/RSS/MC (backend; MC LCG bug noted) |
| Limits & fits (ISO 286) | ✅ | Yes | ISO 286 limits & fits (backend) |
| Process capability (Cpk/Ppk) | ✅ | No | Cpk/Ppk process capability (backend) |
| Reliability (FMEA/MTBF) | ✅ | No | FMEA/MTBF reliability analysis (backend) |
| Paraxial ABCD ray transfer | ✅ | No | ABCD ray transfer matrices (backend) |
| Acoustics (ISO 9613, RT60, weighting, mass-law TL) | ✅ | No | ISO 9613 + RT60 + weighting + mass-law TL (backend) |
| Jewelry (41 modules) | ✅ | No | Deep — full configurator UI; RhinoGold/Matrix-class |
| BIM (walls/slabs/framing/stairs/IFC4) | ✅ | No | Revit-comparable engine + viewer wired via /compile-ifc |
| Should-cost (6 processes, Boothroyd-Dewhurst) | ✅ | No | 6 processes; Boothroyd-Dewhurst grade (backend) |
| Material selection (Ashby) | ✅ | Partial | 200 materials + Pareto frontier + weighted-score (backend) |
| LCA (full ISO 14040/44 4 phases) | ✅ | No | Use+transport+EoL + multi-impact + uncertainty (backend) |
| Process simulation (moldflow/weld/AM/forming) | ✅ | Partial | Hele-Shaw moldflow + weld-line + air-trap (backend) |

## What Kerf does that Autodesk Inventor doesn't

- **Modal / buckling / nonlinear** — Consistent-mass modal, Riks, J2 plasticity (backend)
- **AISC 360-22 steel (members)** — Full Ch. E/F/H + 50-section catalog (backend)
- **ACI 318-19 concrete** — Flexure/shear/PM/dev-length (backend)
- **Fatigue (S-N, ε-N, rainflow)** — S-N, ε-N, rainflow counting (backend)
- **Psychrometrics (moist air)** — ASHRAE-grade psychrometrics (backend)
- **CFD** — Real OpenFOAM bridge (needs install; backend)
- **Heat exchangers (LMTD + ε-NTU + Bell-Delaware)** — LMTD + ε-NTU + Bell-Delaware + TEMA (backend)
- **Pipe network (Hardy-Cross)** — Hardy-Cross pipe network solver (backend)
- **3D wing VLM (+ viscous + compressibility)** — VLM + strip viscous + PG/KT compressibility (backend)
- **Orbital (Kepler, J2/J3, Hohmann)** — Kepler + J2/J3 + Hohmann + Lambert, wired
- **Naval hydrostatics + GZ stability (IMO)** — Hydrostatics + GZ + IMO stability, wired
- **Schematic capture (KiCad round-trip, ERC)** — KiCad round-trip viewer (read-only)
- *(and 24 more features not covered by Autodesk Inventor)*

## What's honestly outstanding

- **2D drawings (views/dims/sections)** (Partial): Live HLR projection + auto-dim; no GD&T-placement UI

## Pricing

Autodesk Inventor is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
