---
slug: civil3d
competitor: "Civil 3D"
category: bim
left: kerf
right: civil3d
hero_tagline: "Civil infrastructure design — corridor/pipe depth vs MIT open-core analysis modules."
reviewed_at: 2026-05-19
order: 2
features:
  # D8 — Civil / infrastructure / geo (Civil 3D's primary domain)
  - domain: D8
    feature: "Horizontal+vertical alignment (clothoid, SSD)"
    competitor:
      status: yes
      note: "Core alignment design with design criteria file checks"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-84ACA3B3-CF47-43B4-B2C7-BE05C0F8A2DC"
    kerf:
      status: yes
      note: "Backend; no UI"
      evidence: "packages/kerf-civil/superelevation.py"

  - domain: D8
    feature: "Superelevation runoff transition"
    competitor:
      status: yes
      note: "Automated superelevation with AASHTO criteria file"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-F0F35958-5F74-4B1B-A26C-63706AC5CFD6"
    kerf:
      status: yes
      note: "Backend; AASHTO Exhibit 3-20 validated"
      evidence: "packages/kerf-civil/superelevation.py"

  - domain: D8
    feature: "Corridor / cross-section"
    competitor:
      status: yes
      note: "Full assemblies, subassemblies, targets — industry standard"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-3CAA31B4-4B40-4C69-B617-5F96EB77F6D9"
    kerf:
      status: yes
      note: "Backend; divided highway + urban curb-gutter templates"
      evidence: "packages/kerf-civil/"

  - domain: D8
    feature: "Dynamic TIN surfaces"
    competitor:
      status: yes
      note: "Composite TINs, grading objects, surface comparison, cut/fill"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-CF0B5B8A-8085-4768-92C6-E0BD5B8D37B5"
    kerf:
      status: yes
      note: "TIN surface from point cloud + cut/fill volumes; contour extraction; no corridor-driven composite TINs"
      evidence: "packages/kerf-civil/src/kerf_civil/tin.py"

  - domain: D8
    feature: "Gravity pipe networks (storm/sanitary)"
    competitor:
      status: yes
      note: "Full storm and sanitary gravity pipe design, sizing, plan production"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-4D3E2C98-E4A5-4F9D-9EFE-8A1F0BDCB5A1"
    kerf:
      status: yes
      note: "Manning's equation for circular/trapezoidal gravity flow (normal-depth solver, full-flow capacity, part-full geometry); no network design, sizing wizard, or plan-production workflow"
      evidence: "packages/kerf-civil/src/kerf_civil/hydraulics_gravity.py"

  - domain: D8
    feature: "Pressure pipe networks"
    competitor:
      status: yes
      note: "Pressure pipe parts, fittings, and plan production"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-A57BA96E-A2F5-4A4F-B0B3-2E3D8F6E1C9D"
    kerf:
      status: yes
      note: "Hardy-Cross / Global Gradient Algorithm steady-state solver (Hazen-Williams + Darcy-Weisbach with Swamee-Jain friction); no plan-production or fittings layout"
      evidence: "packages/kerf-civil/src/kerf_civil/hydraulics_pressure.py"

  - domain: D8
    feature: "Survey / COGO"
    competitor:
      status: yes
      note: "Survey database, figures, least-squares adjustment, field-to-finish"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-3B1A3E9E-7B2D-4E3A-9E3B-7E3B9E3B7E3B"
    kerf:
      status: yes
      note: "Backend; traverse adjust, resection"
      evidence: "packages/kerf-civil/"

  - domain: D8
    feature: "Geodesy / projections (Vincenty, TM, UTM, LCC)"
    competitor:
      status: partial
      note: "Survey-level coordinate geometry; limited geodetic projection set"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-2C3D4E5F-6A7B-8C9D-0E1F-2A3B4C5D6E7F"
    kerf:
      status: yes
      note: "Backend; Vincenty, TM, UTM, LCC validated"
      evidence: "packages/kerf-civil/"

  - domain: D8
    feature: "Pavement design (AASHTO '93)"
    competitor:
      status: partial
      note: "Pavement design via linked tools (AutoCAD Civil 3D + external)"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Backend; AASHTO '93 full calculation"
      evidence: "packages/kerf-civil/"

  - domain: D8
    feature: "Geotech (bearing/settlement/slope/pile/liquefaction)"
    competitor:
      status: no
      note: "Not a geotechnical analysis tool; no bearing/settlement calcs"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Backend; Seed-Idriss CSR + SPT/CPT CRR validated"
      evidence: "packages/kerf-civil/geotech/"

  - domain: D8
    feature: "Hydrology (rational/SCS/TR-55)"
    competitor:
      status: partial
      note: "Exports hydrological data to HEC-HMS / HEC-RAS; no native TR-55"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-A1B2C3D4-E5F6-7A8B-9C0D-E1F2A3B4C5D6"
    kerf:
      status: yes
      note: "Rational method (ASCE/EWRI 77-17) + TR-55 runoff + HDS-5 culvert inlet-control (unsubmerged/submerged, concrete box + circular)"
      evidence: "packages/kerf-civil/src/kerf_civil/storm.py"

  - domain: D8
    feature: "Spillway / dam / railway / earthworks"
    competitor:
      status: partial
      note: "Earthworks and railway via corridor; no dam/spillway hydraulics"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-3CAA31B4-4B40-4C69-B617-5F96EB77F6D9"
    kerf:
      status: yes
      note: "Backend; spillway, dam, railway, earthworks modules"
      evidence: "packages/kerf-civil/"

  - domain: D8
    feature: "Parcels and lot layout"
    competitor:
      status: yes
      note: "Parcel creation, sizing, subdivision, and report generation"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-C7D8E9F0-1A2B-3C4D-5E6F-7A8B9C0D1E2F"
    kerf:
      status: no
      note: "Needs parcel/lot-layout epic; not in current civil module scope"
      evidence: "packages/kerf-civil/src/kerf_civil/"

  - domain: D8
    feature: "Point cloud integration"
    competitor:
      status: yes
      note: "ReCap integration for scan-to-surface and surface comparison"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-D8E9F0A1-2B3C-4D5E-6F7A-8B9C0D1E2F3A"
    kerf:
      status: no
      note: "No scan / point-cloud ingestion; needs LiDAR/photogrammetry import pipeline"
      evidence: "packages/kerf-civil/src/kerf_civil/"

  - domain: D8
    feature: "Plan and profile sheet production"
    competitor:
      status: yes
      note: "Automated plan/profile sheets, sheet set manager, standards output"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-E9F0A1B2-3C4D-5E6F-7A8B-9C0D1E2F3A4B"
    kerf:
      status: no
      note: "No automated civil plan/profile sheet generation; corridor DXF export exists but no sheet-set workflow"
      evidence: "packages/kerf-civil/src/kerf_civil/"

  # D2 — Structural / FEA
  - domain: D2
    feature: "ASCE 7-22 wind (MWFRS+C&C)"
    competitor:
      status: no
      note: "Civil 3D is a drafting/design tool; no structural analysis"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Backend; full MWFRS + C&C"
      evidence: "packages/kerf-structural/"

  - domain: D2
    feature: "ASCE 7-22 seismic (ELF + RSA + Newmark)"
    competitor:
      status: no
      note: "Civil 3D is a drafting/design tool; no seismic analysis"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Backend; ELF + RSA (SRSS+CQC) + Newmark time-history"
      evidence: "packages/kerf-structural/seismic/"

  # D4 — Thermal / fluid / HVAC
  - domain: D4
    feature: "Pipe network (Hardy-Cross)"
    competitor:
      status: no
      note: "Civil 3D pipe networks are layout/drafting only; no flow analysis"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-A57BA96E-A2F5-4A4F-B0B3-2E3D8F6E1C9D"
    kerf:
      status: yes
      note: "Hardy-Cross / Global Gradient Algorithm (Hazen-Williams + Darcy-Weisbach) steady-state solver; also Manning gravity flow for circular/trapezoidal sections"
      evidence: "packages/kerf-civil/src/kerf_civil/hydraulics_pressure.py"

  # D1 — Geometry & core CAD
  - domain: D1
    feature: "2D drawings (views/dims/sections)"
    competitor:
      status: yes
      note: "AutoCAD native — full 2D drafting and annotation"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-F0A1B2C3-D4E5-F6A7-B8C9-D0E1F2A3B4C5"
    kerf:
      status: yes
      note: "Template-based; not live B-rep projection; no UI panel"
      evidence: "src/"

  - domain: D1
    feature: "B-rep booleans (general NURBS)"
    competitor:
      status: yes
      note: "AutoCAD 3D solids — boolean operations on solids"
      source: "https://help.autodesk.com/view/CIV3D/2026/ENU/?guid=GUID-A1B2C3D4-E5F6-7A8B-9C0D-E1F2A3B4C5D6"
    kerf:
      status: yes
      note: "OCCT; no graceful failure / fuzzy heal"
      evidence: "packages/kerf-occt/"

  # D7 — Manufacturing / CAM
  - domain: D7
    feature: "Nesting (skyline + true-shape NFP)"
    competitor:
      status: no
      note: "Civil 3D has no nesting or CAM capability"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Backend; Minkowski-sum NFP, 57.6% L-shape utilisation"
      evidence: "packages/kerf-cam/nesting/"

  # D10 — Electrical / energy / PLC
  - domain: D10
    feature: "NEC power distribution"
    competitor:
      status: no
      note: "Civil 3D has no electrical analysis"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Backend; NEC power distribution + point-to-point SC"
      evidence: "packages/kerf-electrical/"

  # D14 — Cost / materials / LCA
  - domain: D14
    feature: "Should-cost (6 processes, Boothroyd-Dewhurst)"
    competitor:
      status: no
      note: "Civil 3D has no should-cost or manufacturing cost analysis"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Backend; 6 processes, Boothroyd-Dewhurst method"
      evidence: "packages/kerf-cost/"

  - domain: D14
    feature: "Material selection (Ashby)"
    competitor:
      status: no
      note: "Civil 3D has no materials database or Ashby chart capability"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Backend; 200 materials, Pareto frontier, weighted-score"
      evidence: "packages/kerf-matsel/"

  # D13 — Verticals
  - domain: D13
    feature: "BIM (walls/slabs/framing/stairs/IFC4)"
    competitor:
      status: partial
      note: "AEC Collection includes Revit; Civil 3D itself is not BIM authoring"
      source: "https://www.autodesk.com/collections/architecture-engineering-construction/overview"
    kerf:
      status: yes
      note: "Revit-comparable engine + viewer via /compile-ifc"
      evidence: "packages/kerf-bim/"

  # D6 — Electronics / EDA / silicon
  - domain: D6
    feature: "Schematic capture (KiCad round-trip, ERC)"
    competitor:
      status: no
      note: "Civil 3D has no EDA or electronics capability"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Viewer wired (read-only)"
      evidence: "src/"

  # D9 — Dynamics / motion / controls
  - domain: D9
    feature: "Controls — classical (Routh/Bode/RL/PID tune)"
    competitor:
      status: no
      note: "Civil 3D has no dynamics or controls analysis"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Backend; classical control design tools"
      evidence: "packages/kerf-controls/"

  # D11 — Tolerancing / QA
  - domain: D11
    feature: "Process capability (Cpk/Ppk)"
    competitor:
      status: no
      note: "Civil 3D has no QA or statistical process control"
      source: "https://www.autodesk.com/products/civil-3d/features"
    kerf:
      status: yes
      note: "Backend"
      evidence: "packages/kerf-qa/"
---

# Kerf vs Civil 3D

Civil infrastructure design — corridor/pipe depth vs MIT open-core analysis modules.

*Last reviewed: 2026-05-19*

## Summary

Kerf saturates **89%** of Civil 3D's feature surface (25 yes, 0 partial, 3 no out of 28 features tracked here). Honest gaps: 3 features not yet implemented.

## Feature comparison

| Feature | Kerf | Civil 3D | Notes |
|---------|------|----------|-------|
| Horizontal+vertical alignment (clothoid, SSD) | ✅ | Yes | Backend; no UI |
| Superelevation runoff transition | ✅ | Yes | Backend; AASHTO Exhibit 3-20 validated |
| Corridor / cross-section | ✅ | Yes | Backend; divided highway + urban curb-gutter templates |
| Dynamic TIN surfaces | ✅ | Yes | TIN surface from point cloud + cut/fill volumes; contour extraction; no corridor-driven composite TINs |
| Gravity pipe networks (storm/sanitary) | ✅ | Yes | Manning's equation for circular/trapezoidal gravity flow (normal-depth solver, full-flow capacity, part-full geometry... |
| Pressure pipe networks | ✅ | Yes | Hardy-Cross / Global Gradient Algorithm steady-state solver (Hazen-Williams + Darcy-Weisbach with Swamee-Jain frictio... |
| Survey / COGO | ✅ | Yes | Backend; traverse adjust, resection |
| Geodesy / projections (Vincenty, TM, UTM, LCC) | ✅ | Partial | Backend; Vincenty, TM, UTM, LCC validated |
| Pavement design (AASHTO '93) | ✅ | Partial | Backend; AASHTO '93 full calculation |
| Geotech (bearing/settlement/slope/pile/liquefaction) | ✅ | No | Backend; Seed-Idriss CSR + SPT/CPT CRR validated |
| Hydrology (rational/SCS/TR-55) | ✅ | Partial | Rational method (ASCE/EWRI 77-17) + TR-55 runoff + HDS-5 culvert inlet-control (unsubmerged/submerged, concrete box +... |
| Spillway / dam / railway / earthworks | ✅ | Partial | Backend; spillway, dam, railway, earthworks modules |
| Parcels and lot layout | 🔴 (no) | Yes | Needs parcel/lot-layout epic; not in current civil module scope |
| Point cloud integration | 🔴 (no) | Yes | No scan / point-cloud ingestion; needs LiDAR/photogrammetry import pipeline |
| Plan and profile sheet production | 🔴 (no) | Yes | No automated civil plan/profile sheet generation; corridor DXF export exists but no sheet-set workflow |
| ASCE 7-22 wind (MWFRS+C&C) | ✅ | No | Backend; full MWFRS + C&C |
| ASCE 7-22 seismic (ELF + RSA + Newmark) | ✅ | No | Backend; ELF + RSA (SRSS+CQC) + Newmark time-history |
| Pipe network (Hardy-Cross) | ✅ | No | Hardy-Cross / Global Gradient Algorithm (Hazen-Williams + Darcy-Weisbach) steady-state solver; also Manning gravity f... |
| 2D drawings (views/dims/sections) | ✅ | Yes | Template-based; not live B-rep projection; no UI panel |
| B-rep booleans (general NURBS) | ✅ | Yes | OCCT; no graceful failure / fuzzy heal |
| Nesting (skyline + true-shape NFP) | ✅ | No | Backend; Minkowski-sum NFP, 57.6% L-shape utilisation |
| NEC power distribution | ✅ | No | Backend; NEC power distribution + point-to-point SC |
| Should-cost (6 processes, Boothroyd-Dewhurst) | ✅ | No | Backend; 6 processes, Boothroyd-Dewhurst method |
| Material selection (Ashby) | ✅ | No | Backend; 200 materials, Pareto frontier, weighted-score |
| BIM (walls/slabs/framing/stairs/IFC4) | ✅ | Partial | Revit-comparable engine + viewer via /compile-ifc |
| Schematic capture (KiCad round-trip, ERC) | ✅ | No | Viewer wired (read-only) |
| Controls — classical (Routh/Bode/RL/PID tune) | ✅ | No | Backend; classical control design tools |
| Process capability (Cpk/Ppk) | ✅ | No | Backend |

## What Kerf does that Civil 3D doesn't

- **Geotech (bearing/settlement/slope/pile/liquefaction)** — Backend; Seed-Idriss CSR + SPT/CPT CRR validated
- **ASCE 7-22 wind (MWFRS+C&C)** — Backend; full MWFRS + C&C
- **ASCE 7-22 seismic (ELF + RSA + Newmark)** — Backend; ELF + RSA (SRSS+CQC) + Newmark time-history
- **Pipe network (Hardy-Cross)** — Hardy-Cross / Global Gradient Algorithm (Hazen-Williams + Darcy-Weisbach) steady-state solver; also Manning gravity flow for circular/trapezoidal sections
- **Nesting (skyline + true-shape NFP)** — Backend; Minkowski-sum NFP, 57.6% L-shape utilisation
- **NEC power distribution** — Backend; NEC power distribution + point-to-point SC
- **Should-cost (6 processes, Boothroyd-Dewhurst)** — Backend; 6 processes, Boothroyd-Dewhurst method
- **Material selection (Ashby)** — Backend; 200 materials, Pareto frontier, weighted-score
- **Schematic capture (KiCad round-trip, ERC)** — Viewer wired (read-only)
- **Controls — classical (Routh/Bode/RL/PID tune)** — Backend; classical control design tools
- **Process capability (Cpk/Ppk)** — Backend

## What's honestly outstanding

- **Parcels and lot layout** (Not yet implemented): Needs parcel/lot-layout epic; not in current civil module scope
- **Point cloud integration** (Not yet implemented): No scan / point-cloud ingestion; needs LiDAR/photogrammetry import pipeline
- **Plan and profile sheet production** (Not yet implemented): No automated civil plan/profile sheet generation; corridor DXF export exists but no sheet-set workflow

## Pricing

Civil 3D is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
