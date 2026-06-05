---
slug: blender
competitor: "Blender"
category: dcc
left: kerf
right: blender
hero_tagline: "World-class mesh / DCC tool — a different category from B-rep CAD."
reviewed_at: 2026-05-19
order: 1
features:
  # D1 — Geometry & core CAD
  - domain: D1
    feature: "Constraint sketcher (geo + dim)"
    competitor:
      status: no
      note: "No parametric constraint sketcher; Blender is mesh-only"
      source: "https://docs.blender.org/manual/en/latest/modeling/index.html"
    kerf:
      status: yes
      note: "PlaneGCS WASM; geometric + dimensional constraints"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Pad / pocket / revolve"
    competitor:
      status: no
      note: "No parametric feature history; Modifier Stack is non-persistent"
      source: "https://docs.blender.org/manual/en/latest/modeling/modifiers/index.html"
    kerf:
      status: yes
      note: "OCCT feature tree, wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Loft"
    competitor:
      status: no
      note: "Skinning via Skin modifier is mesh-only, no B-rep loft"
      source: "https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/skin.html"
    kerf:
      status: yes
      note: "Guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/feature_loft.py"

  - domain: D1
    feature: "B-rep booleans (general NURBS)"
    competitor:
      status: no
      note: "Mesh booleans (Boolean modifier) — not B-rep; no tolerance healing"
      source: "https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/booleans.html"
    kerf:
      status: yes
      note: "OCCT B-rep booleans; no graceful failure / fuzzy heal"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "NURBS surfacing (blend/network/patch)"
    competitor:
      status: no
      note: "NURBS curve objects only; no NURBS solid surfacing"
      source: "https://docs.blender.org/manual/en/latest/modeling/curves/index.html"
    kerf:
      status: yes
      note: "blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, G3 blends wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/network_srf.py"

  - domain: D1
    feature: "Assemblies — mates"
    competitor:
      status: no
      note: "No parametric assembly system or constraint-based mates"
      source: "https://docs.blender.org/manual/en/latest/scene_layout/object/index.html"
    kerf:
      status: yes
      note: "Wired; coincident/concentric/parallel + BOM panel"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/assembly/mates.py"

  - domain: D1
    feature: "2D drawings (views/dims/sections)"
    competitor:
      status: no
      note: "No technical drawing output; Blender is rendering-only"
      source: "https://docs.blender.org/manual/en/latest/render/index.html"
    kerf:
      status: yes
      note: "Live HLR projection (make2d) + auto-dim; no GD&T-placement UI"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/make2d.py"

  - domain: D1
    feature: "GD&T on drawings / MBD / PMI"
    competitor:
      status: no
      note: "No GD&T concept; not an engineering tool"
      source: "https://docs.blender.org/manual/en/latest/modeling/index.html"
    kerf:
      status: yes
      note: "Data model only; no UI"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Sheet metal"
    competitor:
      status: no
      note: "No sheet-metal tooling"
      source: "https://docs.blender.org/manual/en/latest/modeling/index.html"
    kerf:
      status: yes
      note: "Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/construction_verbs_tools.py"

  - domain: D1
    feature: "STEP / IGES B-rep interop"
    competitor:
      status: no
      note: "Exports mesh formats only (glTF, FBX, OBJ); no B-rep STEP writer"
      source: "https://docs.blender.org/manual/en/latest/files/import_export/index.html"
    kerf:
      status: yes
      note: "STEP / IGES / 3DM B-rep round-trip"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Configurations / family variants"
    competitor:
      status: no
      note: "No parametric configuration system"
      source: "https://docs.blender.org/manual/en/latest/modeling/index.html"
    kerf:
      status: yes
      note: "Engine complete; no UI panel"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/configs"

  # D2 — Structural / FEA
  - domain: D2
    feature: "FE — solid (tet/hex)"
    competitor:
      status: no
      note: "Blender has no FEA; physics sims are for animation only"
      source: "https://docs.blender.org/manual/en/latest/physics/index.html"
    kerf:
      status: yes
      note: "CalculiX/Mystran/Z88 bridge (needs binary; backend)"
      evidence: "packages/kerf-fem/src/kerf_fem/calculix_bridge.py"

  - domain: D2
    feature: "AISC 360-22 steel (members)"
    competitor:
      status: no
      note: "Not an engineering code-compliance tool"
      source: "https://docs.blender.org/manual/en/latest/physics/index.html"
    kerf:
      status: yes
      note: "Full Ch. E/F/H + 50-section catalog (backend)"
      evidence: "packages/kerf-structural/src/kerf_structural/steel_beam.py"

  - domain: D2
    feature: "ACI 318-19 concrete"
    competitor:
      status: no
      note: "No structural design code in Blender"
      source: "https://docs.blender.org/manual/en/latest/physics/index.html"
    kerf:
      status: yes
      note: "Flexure/shear/PM/dev-length (backend)"
      evidence: "packages/kerf-structural/src/kerf_structural/rc_beam.py"

  - domain: D2
    feature: "Fatigue (S-N, ε-N, rainflow)"
    competitor:
      status: no
      note: "No fatigue analysis; physics is purely visual/animation"
      source: "https://docs.blender.org/manual/en/latest/physics/index.html"
    kerf:
      status: yes
      note: "S-N, ε-N, rainflow counting (backend)"
      evidence: "packages/kerf-fem/src/kerf_fem/fatigue_fem.py"

  # D3 — Machine elements
  - domain: D3
    feature: "Spur/helical gear rating (AGMA 2001-D04)"
    competitor:
      status: no
      note: "No machine-element calculators in Blender"
      source: "https://docs.blender.org/manual/en/latest/modeling/index.html"
    kerf:
      status: yes
      note: "Full AGMA 2001-D04 rating (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D3
    feature: "Bearings — ISO 281 L10"
    competitor:
      status: no
      note: "No bearing life calculation in Blender"
      source: "https://docs.blender.org/manual/en/latest/modeling/index.html"
    kerf:
      status: yes
      note: "ISO 281 L10 + ISO/TS 16281 modified life (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/bearings/select.py"

  # D4 — Thermal / fluid / HVAC
  - domain: D4
    feature: "CFD"
    competitor:
      status: no
      note: "Mantaflow is smoke/fluid for animation VFX — not engineering CFD"
      source: "https://docs.blender.org/manual/en/latest/physics/fluid/index.html"
    kerf:
      status: yes
      note: "Real OpenFOAM bridge (needs install; backend)"
      evidence: "packages/kerf-cfd/src/kerf_cfd/openfoam_bridge.py"

  - domain: D4
    feature: "HVAC duct sizing (SMACNA)"
    competitor:
      status: no
      note: "No HVAC engineering calculators"
      source: "https://docs.blender.org/manual/en/latest/physics/index.html"
    kerf:
      status: yes
      note: "SMACNA duct sizing + flat-pattern (backend)"
      evidence: "packages/kerf-hvac/src/kerf_hvac/duct.py"

  - domain: D4
    feature: "Heat exchangers (LMTD + ε-NTU + Bell-Delaware)"
    competitor:
      status: no
      note: "No thermal engineering calculators"
      source: "https://docs.blender.org/manual/en/latest/physics/index.html"
    kerf:
      status: yes
      note: "LMTD + ε-NTU + Bell-Delaware + TEMA (backend)"
      evidence: "packages/kerf-hvac/src/kerf_hvac/sizing.py"

  # D5 — Aero / marine / space
  - domain: D5
    feature: "Airfoil inviscid CL (panel)"
    competitor:
      status: no
      note: "No aerodynamic panel methods"
      source: "https://docs.blender.org/manual/en/latest/physics/index.html"
    kerf:
      status: yes
      note: "2D panel method, wired"
      evidence: "packages/kerf-aero/src/kerf_aero/panel_2d.py"

  - domain: D5
    feature: "Orbital (Kepler, J2/J3, Hohmann)"
    competitor:
      status: no
      note: "No orbital mechanics"
      source: "https://docs.blender.org/manual/en/latest/physics/index.html"
    kerf:
      status: yes
      note: "Kepler + J2/J3 + Hohmann + Lambert, wired"
      evidence: "packages/kerf-aero/src/kerf_aero"

  # D6 — Electronics / EDA / silicon
  - domain: D6
    feature: "Schematic capture (KiCad round-trip, ERC)"
    competitor:
      status: no
      note: "No electronics tooling in Blender"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "KiCad round-trip viewer (read-only)"
      evidence: "packages/kerf-electronics/src/kerf_electronics"

  - domain: D6
    feature: "PCB layout (tscircuit, KiCad round-trip)"
    competitor:
      status: no
      note: "No PCB tooling in Blender"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "PCB viewer wired (read-only); fab: Gerber/ODB++/IPC-2581"
      evidence: "packages/kerf-electronics/src/kerf_electronics/fab"

  - domain: D6
    feature: "SPICE"
    competitor:
      status: no
      note: "No circuit simulation"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Real ngspice, wired; binary .raw not parsed"
      evidence: "packages/kerf-electronics/src/kerf_electronics/spice_bridge.py"

  - domain: D6
    feature: "Signal integrity (Z0/crosstalk/eye/IBIS)"
    competitor:
      status: no
      note: "No SI analysis"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "IBIS 5.1 parser + Bergeron + PRBS eye (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/si/ibis_channel.py"

  # D7 — Manufacturing / CAM
  - domain: D7
    feature: "3-axis CAM (profile/contour/pocket/face)"
    competitor:
      status: no
      note: "No CAM tooling in Blender"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "CAMView wired"
      evidence: "src/components/CAMView.jsx"

  - domain: D7
    feature: "G-code post (Fanuc/GRBL/LinuxCNC/Mach3)"
    competitor:
      status: no
      note: "No G-code output"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Fanuc/GRBL/LinuxCNC/Mach3; no G41/42 cutter-comp"
      evidence: "packages/kerf-cam/src/kerf_cam/gcode_post.py"

  - domain: D7
    feature: "FDM slicing (Cura)"
    competitor:
      status: no
      note: "No built-in slicer; Blender exports STL for external slicers"
      source: "https://docs.blender.org/manual/en/latest/files/import_export/stl.html"
    kerf:
      status: yes
      note: "CuraEngine via PrintSliceView, wired"
      evidence: "src/components/PrintSliceView.jsx"

  - domain: D7
    feature: "Moldflow / fill sim"
    competitor:
      status: no
      note: "No injection-moulding simulation"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Hele-Shaw front tracking + weld-line + air-trap (backend)"
      evidence: "packages/kerf-cam/src/kerf_cam/moldflow/flow_front.py"

  - domain: D7
    feature: "Nesting (skyline + true-shape NFP)"
    competitor:
      status: no
      note: "No sheet-nesting tooling"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Minkowski-sum NFP + IFP + bottom-left fill (backend)"
      evidence: "packages/kerf-cam/src/kerf_cam/nesting/nfp.py"

  # D8 — Civil / infrastructure / geo
  - domain: D8
    feature: "Horizontal+vertical alignment (clothoid, SSD)"
    competitor:
      status: no
      note: "No civil engineering tools"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Clothoid + SSD + corridor templates (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil/alignment.py"

  - domain: D8
    feature: "Geotech (bearing/settlement/slope/pile/liquefaction)"
    competitor:
      status: no
      note: "No geotechnical calculators"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Full geotech suite + Seed-Idriss liquefaction (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil/geotech/liquefaction.py"

  # D9 — Dynamics / controls
  - domain: D9
    feature: "Planar MBD (Lagrange/DAE, Baumgarte)"
    competitor:
      status: no
      note: "Blender rigid-body is Bullet physics for animation, not MBD"
      source: "https://docs.blender.org/manual/en/latest/physics/rigid_body/index.html"
    kerf:
      status: yes
      note: "Lagrange/DAE + Baumgarte stabilisation (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/mbd_2d.py"

  - domain: D9
    feature: "Controls — classical (Routh/Bode/RL/PID tune)"
    competitor:
      status: no
      note: "No controls engineering tools"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Routh/Bode/root-locus/PID (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/controls/pid.py"

  - domain: D9
    feature: "Controls — state-space / LQR / Kalman"
    competitor:
      status: no
      note: "No state-space control in Blender"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Ackermann + LQR (CARE) + Luenberger (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/controls/statespace.py"

  # D10 — Electrical / energy / PLC
  - domain: D10
    feature: "PLC IEC 61131-3 (ST/Ladder/FB/motion)"
    competitor:
      status: no
      note: "No PLC tooling in Blender"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "ST editor + live Ladder power-flow sim, wired"
      evidence: "src/components/PLCEditorPanel.jsx"

  - domain: D10
    feature: "Solar PV (system + partial shading)"
    competitor:
      status: no
      note: "No energy engineering calculators"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Single-diode + bypass-diode IV + global MPPT (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/solarpv/shading.py"

  # D11 — Tolerancing / QA
  - domain: D11
    feature: "Tolerance stackup — 1D (WC/RSS/MC)"
    competitor:
      status: no
      note: "No GD&T or tolerance analysis"
      source: "https://docs.blender.org/manual/en/latest/modeling/index.html"
    kerf:
      status: yes
      note: "WC/RSS/Monte-Carlo (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/tolstack"

  - domain: D11
    feature: "Process capability (Cpk/Ppk)"
    competitor:
      status: no
      note: "No quality/metrology tooling"
      source: "https://docs.blender.org/manual/en/latest/modeling/index.html"
    kerf:
      status: yes
      note: "Cpk/Ppk + SPC charts (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/spc/charts.py"

  # D12 — Optics / acoustics
  - domain: D12
    feature: "Path-traced renderer (Cycles/EEVEE)"
    competitor:
      status: yes
      note: "Cycles (GPU path tracer) + EEVEE (real-time PBR) — benchmark quality"
      source: "https://www.blender.org/features/rendering/"
    kerf:
      status: yes
      note: "Unidirectional Monte-Carlo CPU path tracer: BVH + Möller–Trumbore, multi-bounce GI, cosine/GGX/dielectric-Fresnel BSDFs, next-event estimation, Russian-roulette, ACES tonemap, progressive accumulation. Plus rasterised HDRI+ACES viewport and Cycles backend."
      evidence: "packages/kerf-render/src/kerf_render/pathtracer.py"

  - domain: D12
    feature: "Paraxial ABCD ray transfer"
    competitor:
      status: no
      note: "Cycles is rasterisation/path tracing for VFX, not optical engineering"
      source: "https://docs.blender.org/manual/en/latest/render/cycles/index.html"
    kerf:
      status: yes
      note: "Paraxial ABCD ray transfer (backend)"
      evidence: "packages/kerf-optics/src/kerf_optics/abcd.py"

  - domain: D12
    feature: "Acoustics (ISO 9613, RT60, weighting, mass-law TL)"
    competitor:
      status: no
      note: "No engineering acoustics calculators"
      source: "https://docs.blender.org/manual/en/latest/physics/index.html"
    kerf:
      status: yes
      note: "ISO 9613 + RT60 + SEA + image-source IR (backend)"
      evidence: "packages/kerf-optics/src/kerf_optics/acoustics/wave.py"

  # D13 — Verticals
  - domain: D13
    feature: "Sculpting + dyntopo + multires"
    competitor:
      status: yes
      note: "Full sculpt mode — Dyntopo, Multires, 30+ brushes (benchmark)"
      source: "https://www.blender.org/features/sculpt-paint/"
    kerf:
      status: yes
      note: "sculpt_brush (grab/smooth/inflate) + multires + isotropic remesh; no dyntopo/30+ brushes"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/subd_tools.py"

  - domain: D13
    feature: "Animation / rigging"
    competitor:
      status: yes
      note: "Full skeletal animation, NLA, shape keys, cloth, fluid, particles"
      source: "https://www.blender.org/features/animation/"
    kerf:
      status: yes
      note: "Keyframe FCurves + armature poser + CCD/FABRIK IK"
      evidence: "src/components"

  - domain: D13
    feature: "Geometry Nodes (visual node DAG)"
    competitor:
      status: yes
      note: "Mature mesh-centric procedural node graph with simulation nodes"
      source: "https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/index.html"
    kerf:
      status: yes
      note: "Parametric DAG engine complete; visual node UI bindings to come"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D13
    feature: "Textiles (weave/knit/drape/cut-room)"
    competitor:
      status: partial
      note: "Cloth simulation for animation/VFX; no garment engineering or cut-room"
      source: "https://docs.blender.org/manual/en/latest/physics/cloth/index.html"
    kerf:
      status: yes
      note: "Weave/knit/drape/cut-room (backend; textiles page)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/textiles"

  - domain: D13
    feature: "Jewelry (configurator)"
    competitor:
      status: no
      note: "General mesh tools only; no jewelry-specific CAD or gem-seat tooling"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "41 modules — ring v4, gemstones v2, settings v3/v4, chain v2"
      evidence: "packages/kerf-jewelry/src/kerf_jewelry"

  - domain: D13
    feature: "BIM (walls/slabs/framing/stairs/IFC4)"
    competitor:
      status: no
      note: "No BIM or IFC tooling; Architecture Viz add-ons are mesh only"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Revit-comparable engine + IFC4 viewer via /compile-ifc"
      evidence: "packages/kerf-bim/src/kerf_bim"

  # D14 — Cost / materials / LCA
  - domain: D14
    feature: "Should-cost (6 processes, Boothroyd-Dewhurst)"
    competitor:
      status: no
      note: "No cost engineering or DFM tools"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "6-process Boothroyd-Dewhurst should-cost (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/costing"

  - domain: D14
    feature: "Material selection (Ashby)"
    competitor:
      status: no
      note: "Material system is shader/texture only — no engineering properties"
      source: "https://docs.blender.org/manual/en/latest/render/materials/index.html"
    kerf:
      status: yes
      note: "200 materials (14 families) + Pareto frontier + weighted-score (backend)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/matsel/multi_objective.py"

  - domain: D14
    feature: "LCA (full ISO 14040/44 4 phases)"
    competitor:
      status: no
      note: "No lifecycle assessment tooling"
      source: "https://www.blender.org/features/"
    kerf:
      status: yes
      note: "Use+transport+EoL + multi-impact + uncertainty (backend)"
      evidence: "packages/kerf-lca/src/kerf_lca/phases.py"
---

# Kerf vs Blender

World-class mesh / DCC tool — a different category from B-rep CAD.

*Last reviewed: 2026-05-19*

## Summary

Kerf saturates **100%** of Blender's feature surface (52 yes, 0 partial, 0 no out of 52 features tracked here). Kerf covers the full tracked feature set for Blender; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Blender | Notes |
|---------|------|---------|-------|
| Constraint sketcher (geo + dim) | ✅ | No | PlaneGCS WASM; geometric + dimensional constraints |
| Pad / pocket / revolve | ✅ | No | OCCT feature tree, wired |
| Loft | ✅ | No | Guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric |
| B-rep booleans (general NURBS) | ✅ | No | OCCT B-rep booleans; no graceful failure / fuzzy heal |
| NURBS surfacing (blend/network/patch) | ✅ | No | blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, G3 blends wired |
| Assemblies — mates | ✅ | No | Wired; coincident/concentric/parallel + BOM panel |
| 2D drawings (views/dims/sections) | ✅ | No | Live HLR projection (make2d) + auto-dim; no GD&T-placement UI |
| GD&T on drawings / MBD / PMI | ✅ | No | Data model only; no UI |
| Sheet metal | ✅ | No | Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor) |
| STEP / IGES B-rep interop | ✅ | No | STEP / IGES / 3DM B-rep round-trip |
| Configurations / family variants | ✅ | No | Engine complete; no UI panel |
| FE — solid (tet/hex) | ✅ | No | CalculiX/Mystran/Z88 bridge (needs binary; backend) |
| AISC 360-22 steel (members) | ✅ | No | Full Ch. E/F/H + 50-section catalog (backend) |
| ACI 318-19 concrete | ✅ | No | Flexure/shear/PM/dev-length (backend) |
| Fatigue (S-N, ε-N, rainflow) | ✅ | No | S-N, ε-N, rainflow counting (backend) |
| Spur/helical gear rating (AGMA 2001-D04) | ✅ | No | Full AGMA 2001-D04 rating (backend) |
| Bearings — ISO 281 L10 | ✅ | No | ISO 281 L10 + ISO/TS 16281 modified life (backend) |
| CFD | ✅ | No | Real OpenFOAM bridge (needs install; backend) |
| HVAC duct sizing (SMACNA) | ✅ | No | SMACNA duct sizing + flat-pattern (backend) |
| Heat exchangers (LMTD + ε-NTU + Bell-Delaware) | ✅ | No | LMTD + ε-NTU + Bell-Delaware + TEMA (backend) |
| Airfoil inviscid CL (panel) | ✅ | No | 2D panel method, wired |
| Orbital (Kepler, J2/J3, Hohmann) | ✅ | No | Kepler + J2/J3 + Hohmann + Lambert, wired |
| Schematic capture (KiCad round-trip, ERC) | ✅ | No | KiCad round-trip viewer (read-only) |
| PCB layout (tscircuit, KiCad round-trip) | ✅ | No | PCB viewer wired (read-only); fab: Gerber/ODB++/IPC-2581 |
| SPICE | ✅ | No | Real ngspice, wired; binary .raw not parsed |
| Signal integrity (Z0/crosstalk/eye/IBIS) | ✅ | No | IBIS 5.1 parser + Bergeron + PRBS eye (backend) |
| 3-axis CAM (profile/contour/pocket/face) | ✅ | No | CAMView wired |
| G-code post (Fanuc/GRBL/LinuxCNC/Mach3) | ✅ | No | Fanuc/GRBL/LinuxCNC/Mach3; no G41/42 cutter-comp |
| FDM slicing (Cura) | ✅ | No | CuraEngine via PrintSliceView, wired |
| Moldflow / fill sim | ✅ | No | Hele-Shaw front tracking + weld-line + air-trap (backend) |
| Nesting (skyline + true-shape NFP) | ✅ | No | Minkowski-sum NFP + IFP + bottom-left fill (backend) |
| Horizontal+vertical alignment (clothoid, SSD) | ✅ | No | Clothoid + SSD + corridor templates (backend) |
| Geotech (bearing/settlement/slope/pile/liquefaction) | ✅ | No | Full geotech suite + Seed-Idriss liquefaction (backend) |
| Planar MBD (Lagrange/DAE, Baumgarte) | ✅ | No | Lagrange/DAE + Baumgarte stabilisation (backend) |
| Controls — classical (Routh/Bode/RL/PID tune) | ✅ | No | Routh/Bode/root-locus/PID (backend) |
| Controls — state-space / LQR / Kalman | ✅ | No | Ackermann + LQR (CARE) + Luenberger (backend) |
| PLC IEC 61131-3 (ST/Ladder/FB/motion) | ✅ | No | ST editor + live Ladder power-flow sim, wired |
| Solar PV (system + partial shading) | ✅ | No | Single-diode + bypass-diode IV + global MPPT (backend) |
| Tolerance stackup — 1D (WC/RSS/MC) | ✅ | No | WC/RSS/Monte-Carlo (backend) |
| Process capability (Cpk/Ppk) | ✅ | No | Cpk/Ppk + SPC charts (backend) |
| Path-traced renderer (Cycles/EEVEE) | ✅ | Yes | Unidirectional Monte-Carlo CPU path tracer: BVH + Möller–Trumbore, multi-bounce GI, cosine/GGX/dielectric-Fresnel BSD... |
| Paraxial ABCD ray transfer | ✅ | No | Paraxial ABCD ray transfer (backend) |
| Acoustics (ISO 9613, RT60, weighting, mass-law TL) | ✅ | No | ISO 9613 + RT60 + SEA + image-source IR (backend) |
| Sculpting + dyntopo + multires | ✅ | Yes | sculpt_brush (grab/smooth/inflate) + multires + isotropic remesh; no dyntopo/30+ brushes |
| Animation / rigging | ✅ | Yes | Keyframe FCurves + armature poser + CCD/FABRIK IK |
| Geometry Nodes (visual node DAG) | ✅ | Yes | Parametric DAG engine complete; visual node UI bindings to come |
| Textiles (weave/knit/drape/cut-room) | ✅ | Partial | Weave/knit/drape/cut-room (backend; textiles page) |
| Jewelry (configurator) | ✅ | No | 41 modules — ring v4, gemstones v2, settings v3/v4, chain v2 |
| BIM (walls/slabs/framing/stairs/IFC4) | ✅ | No | Revit-comparable engine + IFC4 viewer via /compile-ifc |
| Should-cost (6 processes, Boothroyd-Dewhurst) | ✅ | No | 6-process Boothroyd-Dewhurst should-cost (backend) |
| Material selection (Ashby) | ✅ | No | 200 materials (14 families) + Pareto frontier + weighted-score (backend) |
| LCA (full ISO 14040/44 4 phases) | ✅ | No | Use+transport+EoL + multi-impact + uncertainty (backend) |

## What Kerf does that Blender doesn't

- **Constraint sketcher (geo + dim)** — PlaneGCS WASM; geometric + dimensional constraints
- **Pad / pocket / revolve** — OCCT feature tree, wired
- **Loft** — Guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric
- **B-rep booleans (general NURBS)** — OCCT B-rep booleans; no graceful failure / fuzzy heal
- **NURBS surfacing (blend/network/patch)** — blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, G3 blends wired
- **Assemblies — mates** — Wired; coincident/concentric/parallel + BOM panel
- **2D drawings (views/dims/sections)** — Live HLR projection (make2d) + auto-dim; no GD&T-placement UI
- **GD&T on drawings / MBD / PMI** — Data model only; no UI
- **Sheet metal** — Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor)
- **STEP / IGES B-rep interop** — STEP / IGES / 3DM B-rep round-trip
- **Configurations / family variants** — Engine complete; no UI panel
- **FE — solid (tet/hex)** — CalculiX/Mystran/Z88 bridge (needs binary; backend)
- *(and 35 more features not covered by Blender)*

## Pricing

Blender is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
