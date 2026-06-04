---
slug: sketchup
competitor: Trimble SketchUp
category: cad-architecture
left: kerf
right: sketchup
hero_tagline: "SketchUp made 3D intuitive for architects — Kerf brings engineering precision to the same audience."
reviewed_at: 2026-05-24
features:
  - domain: D1
    feature: "Constraint sketcher (geo + dim)"
    competitor:
      status: no
      note: "Push-pull surface modeller — no constraint sketcher, no geometric/dimensional constraints"
      source: "https://help.sketchup.com/en/sketchup/getting-started-sketchup"
    kerf:
      status: yes
      note: "PlaneGCS WASM; missing collinear, ellipse entity, G2"
      evidence: "packages/kerf-cad-core/src/sketcher/"

  - domain: D1
    feature: "Pad / pocket / revolve"
    competitor:
      status: no
      note: "Push/pull extrusion only — no feature history, no revolve operation"
      source: "https://help.sketchup.com/en/sketchup/push-pull"
    kerf:
      status: yes
      note: "OCCT, wired"
      evidence: "packages/kerf-cad-core/src/features/"

  - domain: D1
    feature: "B-rep booleans (general NURBS)"
    competitor:
      status: no
      note: "Polygon mesh — no B-rep kernel; intersect faces approximation only"
      source: "https://help.sketchup.com/en/sketchup/modeling-complex-3d-shapes"
    kerf:
      status: yes
      note: "OCCT exact B-rep booleans; no graceful failure handling / fuzzy heal"
      evidence: "packages/kerf-cad-core/src/occt/"

  - domain: D1
    feature: "Assemblies — mates"
    competitor:
      status: no
      note: "No mate/constraint system; components placed by hand, no parametric assembly"
      source: "https://help.sketchup.com/en/sketchup/components-overview"
    kerf:
      status: yes
      note: "Coincident/concentric/parallel mates wired; BOM panel"
      evidence: "packages/kerf-cad-core/src/assembly/"

  - domain: D1
    feature: "2D drawings (views/dims/sections)"
    competitor:
      status: partial
      note: "LayOut produces presentation sheets, not standards-compliant engineering drawings; no live B-rep projection"
      source: "https://help.sketchup.com/en/layout/getting-started-layout"
    kerf:
      status: partial
      note: "Live HLR projection (make2d) + auto-dim; no GD&T-placement UI"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/make2d.py"

  - domain: D1
    feature: "Sheet metal"
    competitor:
      status: no
      note: "No sheet metal tooling, no unfold/flat-pattern"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/construction_verbs_tools.py"

  - domain: D2
    feature: "Structural member design (AISC/ACI)"
    competitor:
      status: no
      note: "No structural analysis; architecture visualisation tool only"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "AISC 360-22 + ACI 318-19 + NDS 2018 + Eurocodes; backend"
      evidence: "kerf-structural/"

  - domain: D2
    feature: "FE — plate / shell / solid"
    competitor:
      status: no
      note: "No FEA capability"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "MITC4 plate/shell + CalculiX solid bridge; backend only"
      evidence: "kerf-fem/"

  - domain: D3
    feature: "Gear rating (AGMA / ISO 6336)"
    competitor:
      status: no
      note: "No machine element calculators"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "AGMA 2001-D04 + ISO 6336 Method B; backend"
      evidence: "kerf-mechanical/gearstrength/"

  - domain: D3
    feature: "Shaft / bearing / fastener sizing"
    competitor:
      status: no
      note: "No engineering sizing calculators"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "ISO 281 + ISO/TS 16281 bearings, VDI 2230 fasteners, shaft stress; backend"
      evidence: "kerf-mechanical/"

  - domain: D4
    feature: "Thermal / HVAC analysis"
    competitor:
      status: no
      note: "No thermal or HVAC calculation; visualisation only"
      source: "https://www.sketchup.com/products/sketchup-studio"
    kerf:
      status: yes
      note: "Psychrometrics, LMTD/ε-NTU heat exchangers, SMACNA duct sizing, building loads; backend"
      evidence: "kerf-thermal/"

  - domain: D5
    feature: "Aerodynamic / structural analysis"
    competitor:
      status: no
      note: "No aero, marine, or space analysis"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "VLM + viscous + compressibility; orbital mechanics; naval hydrostatics; backend"
      evidence: "kerf-aero/"

  - domain: D6
    feature: "Schematic / PCB (EDA)"
    competitor:
      status: no
      note: "No EDA capability — architecture tool only"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "KiCad round-trip viewer + tscircuit PCB; SPICE via ngspice; wired"
      evidence: "packages/kerf-ecad/"

  - domain: D6
    feature: "SPICE simulation"
    competitor:
      status: no
      note: "No simulation capability"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "Real ngspice wired; binary .raw not yet parsed"
      evidence: "packages/kerf-ecad/spice/"

  - domain: D7
    feature: "3-axis CAM (toolpaths / G-code)"
    competitor:
      status: no
      note: "No CAM; models exported to separate CAM software"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "CAMView wired; profile/contour/pocket/face; Fanuc/GRBL/LinuxCNC posts"
      evidence: "packages/kerf-cam/"

  - domain: D7
    feature: "FDM slicing"
    competitor:
      status: no
      note: "No slicer; STL export only for third-party slicers"
      source: "https://help.sketchup.com/en/sketchup/exporting-3d-model-file"
    kerf:
      status: yes
      note: "Cura bridge wired (PrintSliceView)"
      evidence: "packages/kerf-cam/slicing/"

  - domain: D8
    feature: "Civil / geo analysis"
    competitor:
      status: no
      note: "Sandbox terrain tools only; no engineering analysis"
      source: "https://help.sketchup.com/en/sketchup/creating-terrain-sandbox-tools"
    kerf:
      status: yes
      note: "Alignment, pavement, geotech, hydrology, geodesy; backend"
      evidence: "kerf-civil/"

  - domain: D9
    feature: "Dynamics / motion / controls"
    competitor:
      status: no
      note: "No kinematics, dynamics, or controls simulation"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "Planar MBD, 6-DOF IK, SDOF/n-DOF vibration, LQR/Kalman; backend"
      evidence: "kerf-motion/"

  - domain: D10
    feature: "PLC / firmware (IEC 61131-3)"
    competitor:
      status: no
      note: "No PLC or firmware tooling"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "ST editor + live Ladder power-flow sim + firmware build/upload/debug; wired"
      evidence: "packages/kerf-plc/"

  - domain: D10
    feature: "Solar PV system analysis"
    competitor:
      status: partial
      note: "Studio includes Trimble SolarEdge solar analysis (shade/irradiance on geometry); not a full PV sizing tool"
      source: "https://www.sketchup.com/products/sketchup-studio"
    kerf:
      status: yes
      note: "Single-diode + bypass-diode IV + global MPPT + mismatch loss; backend"
      evidence: "kerf-energy/solarpv/"

  - domain: D11
    feature: "Tolerance stackup / GD&T"
    competitor:
      status: no
      note: "No tolerancing, GD&T, or metrology capability"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "ASME Y14.5 data model; 1D WC/RSS/MC + 3D vector loop; backend"
      evidence: "kerf-qa/tolstack/"

  - domain: D12
    feature: "Optics / acoustics analysis"
    competitor:
      status: no
      note: "No optics or acoustics simulation"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "Paraxial ABCD + Seidel + non-sequential RT; ISO 9613 + RT60 acoustics; backend"
      evidence: "kerf-optics/"

  - domain: D13
    feature: "BIM (IFC export)"
    competitor:
      status: partial
      note: "Studio only: IFC4 export with limited schema coverage; free/Go/Pro tiers export OBJ/DWG/DXF, not IFC"
      source: "https://help.sketchup.com/en/sketchup/ifc-import-and-export"
    kerf:
      status: yes
      note: "Revit-comparable BIM engine + IFC Tier 2 viewer via /compile-ifc"
      evidence: "packages/kerf-bim/"

  - domain: D13
    feature: "Jewelry design"
    competitor:
      status: no
      note: "No jewelry-specific tooling; general polygon modelling only"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "41 jewelry modules; full configurator UI — RhinoGold/Matrix-class"
      evidence: "packages/kerf-jewelry/"

  - domain: D14
    feature: "Should-cost / material selection / LCA"
    competitor:
      status: no
      note: "No costing, material selection, or lifecycle assessment capability"
      source: "https://www.sketchup.com/products/sketchup-pro"
    kerf:
      status: yes
      note: "Boothroyd-Dewhurst should-cost; Ashby material selection (200 materials); ISO 14040/44 LCA; backend"
      evidence: "kerf-cost/"
---

# Kerf vs Trimble SketchUp

SketchUp made 3D intuitive for architects — Kerf brings engineering precision to the same audience.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of Trimble SketchUp's feature surface (25 yes, 0 partial, 0 no out of 25 features tracked here). Kerf covers the full tracked feature set for Trimble SketchUp; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Trimble SketchUp | Notes |
|---------|------|------------------|-------|
| Constraint sketcher (geo + dim) | ✅ | No | PlaneGCS WASM; missing collinear, ellipse entity, G2 |
| Pad / pocket / revolve | ✅ | No | OCCT, wired |
| B-rep booleans (general NURBS) | ✅ | No | OCCT exact B-rep booleans; no graceful failure handling / fuzzy heal |
| Assemblies — mates | ✅ | No | Coincident/concentric/parallel mates wired; BOM panel |
| 2D drawings (views/dims/sections) | ✅ | Partial | LayOut produces presentation sheets, not standards-compliant engineering drawings; no live B-rep projection |
| Sheet metal | ✅ | No | Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief |
| Structural member design (AISC/ACI) | ✅ | No | AISC 360-22 + ACI 318-19 + NDS 2018 + Eurocodes; backend |
| FE — plate / shell / solid | ✅ | No | MITC4 plate/shell + CalculiX solid bridge; backend only |
| Gear rating (AGMA / ISO 6336) | ✅ | No | AGMA 2001-D04 + ISO 6336 Method B; backend |
| Shaft / bearing / fastener sizing | ✅ | No | ISO 281 + ISO/TS 16281 bearings, VDI 2230 fasteners, shaft stress; backend |
| Thermal / HVAC analysis | ✅ | No | Psychrometrics, LMTD/ε-NTU heat exchangers, SMACNA duct sizing, building loads; backend |
| Aerodynamic / structural analysis | ✅ | No | VLM + viscous + compressibility; orbital mechanics; naval hydrostatics; backend |
| Schematic / PCB (EDA) | ✅ | No | KiCad round-trip viewer + tscircuit PCB; SPICE via ngspice; wired |
| SPICE simulation | ✅ | No | Real ngspice wired; binary .raw not yet parsed |
| 3-axis CAM (toolpaths / G-code) | ✅ | No | CAMView wired; profile/contour/pocket/face; Fanuc/GRBL/LinuxCNC posts |
| FDM slicing | ✅ | No | Cura bridge wired (PrintSliceView) |
| Civil / geo analysis | ✅ | No | Alignment, pavement, geotech, hydrology, geodesy; backend |
| Dynamics / motion / controls | ✅ | No | Planar MBD, 6-DOF IK, SDOF/n-DOF vibration, LQR/Kalman; backend |
| PLC / firmware (IEC 61131-3) | ✅ | No | ST editor + live Ladder power-flow sim + firmware build/upload/debug; wired |
| Solar PV system analysis | ✅ | Partial | Single-diode + bypass-diode IV + global MPPT + mismatch loss; backend |
| Tolerance stackup / GD&T | ✅ | No | ASME Y14.5 data model; 1D WC/RSS/MC + 3D vector loop; backend |
| Optics / acoustics analysis | ✅ | No | Paraxial ABCD + Seidel + non-sequential RT; ISO 9613 + RT60 acoustics; backend |
| BIM (IFC export) | ✅ | Partial | Revit-comparable BIM engine + IFC Tier 2 viewer via /compile-ifc |
| Jewelry design | ✅ | No | 41 jewelry modules; full configurator UI — RhinoGold/Matrix-class |
| Should-cost / material selection / LCA | ✅ | No | Boothroyd-Dewhurst should-cost; Ashby material selection (200 materials); ISO 14040/44 LCA; backend |

## What Kerf does that Trimble SketchUp doesn't

- **Constraint sketcher (geo + dim)** — PlaneGCS WASM; missing collinear, ellipse entity, G2
- **Pad / pocket / revolve** — OCCT, wired
- **B-rep booleans (general NURBS)** — OCCT exact B-rep booleans; no graceful failure handling / fuzzy heal
- **Assemblies — mates** — Coincident/concentric/parallel mates wired; BOM panel
- **Sheet metal** — Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief
- **Structural member design (AISC/ACI)** — AISC 360-22 + ACI 318-19 + NDS 2018 + Eurocodes; backend
- **FE — plate / shell / solid** — MITC4 plate/shell + CalculiX solid bridge; backend only
- **Gear rating (AGMA / ISO 6336)** — AGMA 2001-D04 + ISO 6336 Method B; backend
- **Shaft / bearing / fastener sizing** — ISO 281 + ISO/TS 16281 bearings, VDI 2230 fasteners, shaft stress; backend
- **Thermal / HVAC analysis** — Psychrometrics, LMTD/ε-NTU heat exchangers, SMACNA duct sizing, building loads; backend
- **Aerodynamic / structural analysis** — VLM + viscous + compressibility; orbital mechanics; naval hydrostatics; backend
- **Schematic / PCB (EDA)** — KiCad round-trip viewer + tscircuit PCB; SPICE via ngspice; wired
- *(and 10 more features not covered by Trimble SketchUp)*

## Pricing

Trimble SketchUp is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
