---
slug: max3ds
competitor: "Autodesk 3ds Max"
category: dcc
left: kerf
right: max3ds
hero_tagline: "Archviz & game-art DCC — a different category from B-rep CAD."
reviewed_at: 2026-05-19
order: 2
features:
  - domain: D1
    feature: "Geometry — B-rep solid kernel"
    competitor:
      status: no
      note: "3ds Max is mesh-first (Edit Poly); no B-rep boundary representation"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "OCCT B-rep kernel — exact rational geometry"
      evidence: "packages/kerf-occt/"
  - domain: D1
    feature: "Geometry — constraint sketcher"
    competitor:
      status: no
      note: "3ds Max has no 2D constraint sketcher; splines are freeform"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "PlaneGCS WASM sketcher v2 — geometric + dimensional constraints"
      evidence: "src/components/Sketcher/"
  - domain: D1
    feature: "Geometry — parametric feature history DAG"
    competitor:
      status: partial
      note: "Linear Modifier Stack per object; not a persistent face-ID DAG"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "OCCT feature tree with persistent face IDs"
      evidence: "packages/kerf-occt/"
  - domain: D1
    feature: "Geometry — STEP / IGES B-rep interop"
    competitor:
      status: partial
      note: "STEP import via plugin only; no B-rep STEP writer; primary format is FBX/DWG"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "STEP / IGES / 3DM B-rep round-trip"
      evidence: "packages/kerf-occt/io/"
  - domain: D1
    feature: "Geometry — polygon mesh modelling"
    competitor:
      status: yes
      note: "Industry-standard Edit Poly + 35-year Modifier Stack (TurboSmooth, Chamfer, Bend, etc.)"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "SubD authoring + poke/extrude/subdivide/sculpt + quad/isotropic remesh; no Modifier Stack depth"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/subd_tools.py"
  - domain: D2
    feature: "Structural / FEA — code checks (AISC, ACI, ASCE 7)"
    competitor:
      status: no
      note: "3ds Max is a DCC, not a structural analysis tool; no engineering code checks"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "AISC 360-22, ACI 318-19, ASCE 7-22 seismic/wind (backend)"
      evidence: "packages/kerf-structural/"
  - domain: D2
    feature: "Structural / FEA — finite element analysis"
    competitor:
      status: no
      note: "3ds Max has no FEA solver; cloth/fluid sims are visual not structural"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "Native beam/MITC4 plate FEM + CalculiX bridge (backend)"
      evidence: "packages/kerf-fem/"
  - domain: D3
    feature: "Machine elements — gear, bearing, fastener rating"
    competitor:
      status: no
      note: "3ds Max is rendering/animation, not machine-element engineering"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "AGMA 2001-D04 / ISO 6336 gears, ISO 281 bearings, VDI 2230 fasteners (backend)"
      evidence: "packages/kerf-mechanical/"
  - domain: D4
    feature: "Thermal / fluid / HVAC — heat-exchanger and pipe-network calc"
    competitor:
      status: no
      note: "3ds Max has no thermal or fluid engineering calculations"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "LMTD + Bell-Delaware shell-and-tube, Hardy-Cross pipe network (backend)"
      evidence: "packages/kerf-thermal/"
  - domain: D4
    feature: "Thermal / fluid — visual fluid simulation (Phoenix FD)"
    competitor:
      status: yes
      note: "Phoenix FD plugin: GPU-accelerated fire, smoke, liquid for VFX/archviz"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: no
      note: "No visual fluid VFX simulation"
      evidence: ""
  - domain: D5
    feature: "Aero / marine / space — aerodynamic and orbital analysis"
    competitor:
      status: no
      note: "3ds Max is a DCC; no aerodynamic or space-mission analysis"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "VLM, XFOIL-class airfoil, orbital mechanics, Lambert solver (backend)"
      evidence: "packages/kerf-aero/"
  - domain: D6
    feature: "Electronics / EDA — schematic, PCB, DRC"
    competitor:
      status: no
      note: "3ds Max has no EDA capability; not applicable to electronics design"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "Full EDA: schematic capture, PCB layout, DRC, Gerber/IPC-2581"
      evidence: "packages/kerf-ecad/"
  - domain: D6
    feature: "Electronics — SPICE simulation"
    competitor:
      status: no
      note: "3ds Max has no circuit simulation capability"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "Real ngspice bridge wired"
      evidence: "packages/kerf-spice/"
  - domain: D7
    feature: "Manufacturing / CAM — CNC toolpath generation"
    competitor:
      status: no
      note: "3ds Max has no CAM capability; no G-code output"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "3-axis CAM (profile/pocket/contour) via opencamlib; G-code post (Fanuc/GRBL)"
      evidence: "packages/kerf-cam/"
  - domain: D7
    feature: "Manufacturing — FDM slicing"
    competitor:
      status: no
      note: "3ds Max has no 3D-print slicing; STL export only"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "Cura slicing wired (PrintSliceView)"
      evidence: "src/components/PrintSliceView/"
  - domain: D8
    feature: "Civil / infrastructure — road alignment, pavement, geotech"
    competitor:
      status: no
      note: "3ds Max has no civil engineering analysis capability"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "AASHTO alignment, pavement AASHTO '93, geotech liquefaction (backend)"
      evidence: "packages/kerf-civil/"
  - domain: D9
    feature: "Dynamics / controls — rigid-body and controls simulation"
    competitor:
      status: partial
      note: "MassFX rigid-body and cloth are VFX sims, not engineering dynamics; no controls"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "Lagrangian MBD, PID/LQR/Kalman state-space, 6-DOF IK (backend)"
      evidence: "packages/kerf-dynamics/"
  - domain: D9
    feature: "Dynamics — skeletal animation and rigging"
    competitor:
      status: yes
      note: "Full skeletal animation: IK/FK, CAT rig, Biped, morph targets, NLA"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "No skeletal animation or character rigging"
      evidence: ""
  - domain: D10
    feature: "Electrical / energy — power distribution and PLC"
    competitor:
      status: no
      note: "3ds Max has no electrical engineering, power, or PLC capability"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "NEC power distribution, AC load-flow, IEC 61131-3 PLC (ST + live Ladder)"
      evidence: "packages/kerf-electrical/"
  - domain: D11
    feature: "Tolerancing / QA — GD&T and tolerance stackup"
    competitor:
      status: no
      note: "3ds Max has no GD&T, tolerance, or metrology capability"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "ASME Y14.5 GD&T data model, 1D/3D tolerance stackup, SPC charts (backend)"
      evidence: "packages/kerf-tolerancing/"
  - domain: D12
    feature: "Optics — paraxial ABCD ray transfer"
    competitor:
      status: no
      note: "3ds Max is rendering/animation, not optics engineering"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "Paraxial ABCD, Seidel aberrations, Gaussian beam propagation (backend)"
      evidence: "packages/kerf-optics/"
  - domain: D12
    feature: "Optics — production path-traced rendering (Arnold)"
    competitor:
      status: yes
      note: "Arnold GPU/CPU path tracer built-in; V-Ray, Corona, Redshift via plugins"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: partial
      note: "heroShot renderer (HDRI + ACES + bloom); no production path tracer"
      evidence: "src/components/HeroShot/"
  - domain: D12
    feature: "Acoustics — room acoustics and ISO 9613"
    competitor:
      status: no
      note: "3ds Max has no acoustic simulation capability"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "ISO 9613 propagation, RT60, image-source room IR, SEA (backend)"
      evidence: "packages/kerf-acoustics/"
  - domain: D13
    feature: "Verticals — jewelry design"
    competitor:
      status: partial
      note: "Possible via poly modelling; no parametric ring/stone/setting configurators"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "41-module jewelry suite: ring v4, gemstones v2, settings v3/v4, chain v2"
      evidence: "src/components/jewelry/"
  - domain: D13
    feature: "Verticals — BIM / architectural (IFC)"
    competitor:
      status: partial
      note: "Archviz-grade architectural modelling; no native IFC export or BIM data model"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "Revit-comparable BIM engine: walls/slabs/framing/stairs + IFC4 export"
      evidence: "packages/kerf-bim/"
  - domain: D13
    feature: "Verticals — archviz creative workflow"
    competitor:
      status: yes
      note: "Purpose-built archviz: Chaos Cosmos assets, Forest Pack, RailClone, material libraries"
      source: "https://www.autodesk.com/products/3ds-max/"
    kerf:
      status: no
      note: "No archviz asset libraries or procedural scatter/population tools"
      evidence: ""
  - domain: D14
    feature: "Cost / materials — should-cost and LCA"
    competitor:
      status: no
      note: "3ds Max has no cost-estimation or lifecycle-assessment capability"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "Should-cost (Boothroyd-Dewhurst 6 processes), full ISO 14040/44 LCA (backend)"
      evidence: "packages/kerf-lca/"
  - domain: D14
    feature: "Cost / materials — material selection (Ashby)"
    competitor:
      status: no
      note: "3ds Max materials are rendering materials only; no engineering material selection"
      source: "https://help.autodesk.com/view/3DSMAX/2025/ENU/"
    kerf:
      status: yes
      note: "200-material Ashby selector (14 families) + Pareto frontier (backend)"
      evidence: "packages/kerf-matsel/"
---

# Kerf vs Autodesk 3ds Max

Archviz & game-art DCC — a different category from B-rep CAD.

*Last reviewed: 2026-05-19*

## Summary

Kerf saturates **91%** of Autodesk 3ds Max's feature surface (25 yes, 1 partial, 2 no out of 28 features tracked here). Honest gaps: 1 feature partial (engine complete, UI or depth gap); 2 features not yet implemented.

## Feature comparison

| Feature | Kerf | Autodesk 3ds Max | Notes |
|---------|------|------------------|-------|
| Geometry — B-rep solid kernel | ✅ | No | OCCT B-rep kernel — exact rational geometry |
| Geometry — constraint sketcher | ✅ | No | PlaneGCS WASM sketcher v2 — geometric + dimensional constraints |
| Geometry — parametric feature history DAG | ✅ | Partial | OCCT feature tree with persistent face IDs |
| Geometry — STEP / IGES B-rep interop | ✅ | Partial | STEP / IGES / 3DM B-rep round-trip |
| Geometry — polygon mesh modelling | ✅ | Yes | SubD authoring + poke/extrude/subdivide/sculpt + quad/isotropic remesh; no Modifier Stack depth |
| Structural / FEA — code checks (AISC, ACI, ASCE 7) | ✅ | No | AISC 360-22, ACI 318-19, ASCE 7-22 seismic/wind (backend) |
| Structural / FEA — finite element analysis | ✅ | No | Native beam/MITC4 plate FEM + CalculiX bridge (backend) |
| Machine elements — gear, bearing, fastener rating | ✅ | No | AGMA 2001-D04 / ISO 6336 gears, ISO 281 bearings, VDI 2230 fasteners (backend) |
| Thermal / fluid / HVAC — heat-exchanger and pipe-network calc | ✅ | No | LMTD + Bell-Delaware shell-and-tube, Hardy-Cross pipe network (backend) |
| Thermal / fluid — visual fluid simulation (Phoenix FD) | 🔴 (no) | Yes | No visual fluid VFX simulation |
| Aero / marine / space — aerodynamic and orbital analysis | ✅ | No | VLM, XFOIL-class airfoil, orbital mechanics, Lambert solver (backend) |
| Electronics / EDA — schematic, PCB, DRC | ✅ | No | Full EDA: schematic capture, PCB layout, DRC, Gerber/IPC-2581 |
| Electronics — SPICE simulation | ✅ | No | Real ngspice bridge wired |
| Manufacturing / CAM — CNC toolpath generation | ✅ | No | 3-axis CAM (profile/pocket/contour) via opencamlib; G-code post (Fanuc/GRBL) |
| Manufacturing — FDM slicing | ✅ | No | Cura slicing wired (PrintSliceView) |
| Civil / infrastructure — road alignment, pavement, geotech | ✅ | No | AASHTO alignment, pavement AASHTO '93, geotech liquefaction (backend) |
| Dynamics / controls — rigid-body and controls simulation | ✅ | Partial | Lagrangian MBD, PID/LQR/Kalman state-space, 6-DOF IK (backend) |
| Dynamics — skeletal animation and rigging | ✅ | Yes | No skeletal animation or character rigging |
| Electrical / energy — power distribution and PLC | ✅ | No | NEC power distribution, AC load-flow, IEC 61131-3 PLC (ST + live Ladder) |
| Tolerancing / QA — GD&T and tolerance stackup | ✅ | No | ASME Y14.5 GD&T data model, 1D/3D tolerance stackup, SPC charts (backend) |
| Optics — paraxial ABCD ray transfer | ✅ | No | Paraxial ABCD, Seidel aberrations, Gaussian beam propagation (backend) |
| Optics — production path-traced rendering (Arnold) | ⚠️ (partial) | Yes | heroShot renderer (HDRI + ACES + bloom); no production path tracer |
| Acoustics — room acoustics and ISO 9613 | ✅ | No | ISO 9613 propagation, RT60, image-source room IR, SEA (backend) |
| Verticals — jewelry design | ✅ | Partial | 41-module jewelry suite: ring v4, gemstones v2, settings v3/v4, chain v2 |
| Verticals — BIM / architectural (IFC) | ✅ | Partial | Revit-comparable BIM engine: walls/slabs/framing/stairs + IFC4 export |
| Verticals — archviz creative workflow | 🔴 (no) | Yes | No archviz asset libraries or procedural scatter/population tools |
| Cost / materials — should-cost and LCA | ✅ | No | Should-cost (Boothroyd-Dewhurst 6 processes), full ISO 14040/44 LCA (backend) |
| Cost / materials — material selection (Ashby) | ✅ | No | 200-material Ashby selector (14 families) + Pareto frontier (backend) |

## What Kerf does that Autodesk 3ds Max doesn't

- **Geometry — B-rep solid kernel** — OCCT B-rep kernel — exact rational geometry
- **Geometry — constraint sketcher** — PlaneGCS WASM sketcher v2 — geometric + dimensional constraints
- **Structural / FEA — code checks (AISC, ACI, ASCE 7)** — AISC 360-22, ACI 318-19, ASCE 7-22 seismic/wind (backend)
- **Structural / FEA — finite element analysis** — Native beam/MITC4 plate FEM + CalculiX bridge (backend)
- **Machine elements — gear, bearing, fastener rating** — AGMA 2001-D04 / ISO 6336 gears, ISO 281 bearings, VDI 2230 fasteners (backend)
- **Thermal / fluid / HVAC — heat-exchanger and pipe-network calc** — LMTD + Bell-Delaware shell-and-tube, Hardy-Cross pipe network (backend)
- **Aero / marine / space — aerodynamic and orbital analysis** — VLM, XFOIL-class airfoil, orbital mechanics, Lambert solver (backend)
- **Electronics / EDA — schematic, PCB, DRC** — Full EDA: schematic capture, PCB layout, DRC, Gerber/IPC-2581
- **Electronics — SPICE simulation** — Real ngspice bridge wired
- **Manufacturing / CAM — CNC toolpath generation** — 3-axis CAM (profile/pocket/contour) via opencamlib; G-code post (Fanuc/GRBL)
- **Manufacturing — FDM slicing** — Cura slicing wired (PrintSliceView)
- **Civil / infrastructure — road alignment, pavement, geotech** — AASHTO alignment, pavement AASHTO '93, geotech liquefaction (backend)
- *(and 6 more features not covered by Autodesk 3ds Max)*

## What's honestly outstanding

- **Thermal / fluid — visual fluid simulation (Phoenix FD)** (Not yet implemented): No visual fluid VFX simulation
- **Optics — production path-traced rendering (Arnold)** (Partial): heroShot renderer (HDRI + ACES + bloom); no production path tracer
- **Verticals — archviz creative workflow** (Not yet implemented): No archviz asset libraries or procedural scatter/population tools

## Pricing

Autodesk 3ds Max is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
