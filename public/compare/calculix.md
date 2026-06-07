---
slug: calculix
competitor: CalculiX
category: cad-sim
left: kerf
right: calculix
hero_tagline: "CalculiX runs the FEM — Kerf wraps it so structural analysis is as easy as describing the load case."
reviewed_at: 2026-05-24
features:
  - domain: D2
    feature: "FE — solid (tet/hex)"
    competitor:
      status: yes
      note: "ccx solver; C3D4/C3D8/C3D10/C3D20 elements, linear + nonlinear"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "CalculiX bridge"
      evidence: "packages/kerf-fem/src/kerf_fem/calculix_bridge.py"

  - domain: D2
    feature: "Modal / buckling / nonlinear"
    competitor:
      status: yes
      note: "FREQUENCY, BUCKLE, *NLGEOM, Riks arc-length steps"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "consistent-mass modal, Riks, J2 plasticity"
      evidence: "packages/kerf-fem/src/kerf_fem/calculix_bridge.py"

  - domain: D2
    feature: "FE — plate / shell (native)"
    competitor:
      status: yes
      note: "S4, S4R, S8, S8R shell elements; *SHELL SECTION"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "MITC4 Bathe-Dvorkin native; shell also via CalculiX bridge"
      evidence: "packages/kerf-fem/src/kerf_fem/plate.py"

  - domain: D2
    feature: "FE — 1D beam / 2D truss (native)"
    competitor:
      status: yes
      note: "B31, B32, T3D2, T3D3; *BEAM SECTION"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "Hermite beam native; validated vs Roark"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/beam/analysis.py"

  - domain: D2
    feature: "AISC 360-22 steel (members)"
    competitor:
      status: no
      note: "solver only — no code-check post-processing"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "full Ch. E/F/H/I, 50-section catalog"
      evidence: "packages/kerf-structural/src/kerf_structural/aisc_member.py"

  - domain: D2
    feature: "ACI 318-19 concrete"
    competitor:
      status: no
      note: "solver only — no RC code-check"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "flexure/shear/PM/dev-length"
      evidence: "packages/kerf-structural/src/kerf_structural/rc_beam.py"

  - domain: D2
    feature: "Eurocode design (EC2/3/5/8)"
    competitor:
      status: no
      note: "solver only — no Eurocode post-processing"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "EC2 concrete + EC3 steel + EC5 timber + EC8 seismic"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/struct/eurocode3.py"

  - domain: D2
    feature: "ASCE 7-22 seismic"
    competitor:
      status: no
      note: "solver only — no seismic code-check"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "ELF + RSA (SRSS+CQC) + Newmark time-history"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/seismic/rsa.py"

  - domain: D2
    feature: "ASCE 7-22 wind (MWFRS+C&C)"
    competitor:
      status: no
      note: "solver only — no wind load generation"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "MWFRS + C&C per ASCE 7-22"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/windload/asce7.py"

  - domain: D2
    feature: "Fatigue (S-N, ε-N, rainflow)"
    competitor:
      status: partial
      note: "stress output only; no built-in S-N cycle counting or damage"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "S-N, ε-N, rainflow counting, Miner's rule"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/fatigue/life.py"

  - domain: D2
    feature: "ASME VIII pressure vessel"
    competitor:
      status: no
      note: "solver only — no ASME VIII code equations"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "ASME VIII Div 1 thickness + nozzle + wind/seismic"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/pressvessel/shell.py"

  - domain: D2
    feature: "Frame stiffness assembly (2D/3D)"
    competitor:
      status: yes
      note: "full 3D beam-column FEM; *STEP STATIC with NLGEOM"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "2D+3D beam-column + ASCE 7 combos + story drift"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/struct/frame.py"

  - domain: D2
    feature: "API 650 tank"
    competitor:
      status: no
      note: "solver only — no API 650 annular/shell design equations"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "API 650 incl. seismic annex E"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/tank/api650.py"

  - domain: D2
    feature: "NDS 2018 timber"
    competitor:
      status: no
      note: "solver only — no NDS code-check"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "full NDS 2018 adjustment factors"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/timber/design.py"

  - domain: D2
    feature: "AISC steel connections"
    competitor:
      status: no
      note: "solver only — no connection design"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "bolts/welds/base-plate, LRFD+ASD"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/steelconn/connections.py"

  - domain: D1
    feature: "Constraint sketcher (geo + dim)"
    competitor:
      status: no
      note: "solver only — no CAD or sketcher"
      source: "http://www.calculix.de/"
    kerf:
      status: yes
      note: "PlaneGCS WASM; geo + dim constraints"
      evidence: "src/components/SketchView.jsx"

  - domain: D1
    feature: "B-rep booleans (general NURBS)"
    competitor:
      status: no
      note: "no geometry kernel; pre-processor must supply mesh"
      source: "http://www.calculix.de/"
    kerf:
      status: yes
      note: "OCCT B-rep booleans"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/boolean.py"

  - domain: D1
    feature: "Assemblies — mates"
    competitor:
      status: no
      note: "no assembly or mate system"
      source: "http://www.calculix.de/"
    kerf:
      status: yes
      note: "coincident/concentric/parallel/+BOM panel"
      evidence: "src/components/AssemblyEditor.jsx"

  - domain: D7
    feature: "3-axis CAM (profile/contour/pocket/face)"
    competitor:
      status: no
      note: "FEA solver only — no CAM capability"
      source: "http://www.calculix.de/"
    kerf:
      status: yes
      note: "CAMView wired; opencamlib backend"
      evidence: "src/components/CAMView.jsx"

  - domain: D4
    feature: "CFD"
    competitor:
      status: no
      note: "structural/thermal FEA only; no fluid solver"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "OpenFOAM bridge (needs install)"
      evidence: "packages/kerf-cfd/src/kerf_cfd/openfoam_bridge.py"

  - domain: D4
    feature: "Thermo cycles (Rankine/Brayton/Otto)"
    competitor:
      status: no
      note: "coupled thermo-mechanical only; no cycle analysis"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "Rankine/Brayton/Otto/Diesel cycle analysis"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/thermocycle/"

  - domain: D14
    feature: "Material selection (Ashby)"
    competitor:
      status: no
      note: "uses material cards for FEA; no Ashby selection logic"
      source: "http://www.dhondt.de/ccx_2.21.pdf"
    kerf:
      status: yes
      note: "200 materials, 14 families, Pareto frontier"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/matsel/multi_objective.py"

  - domain: D14
    feature: "Should-cost (6 processes, Boothroyd-Dewhurst)"
    competitor:
      status: no
      note: "no cost estimation capability"
      source: "http://www.calculix.de/"
    kerf:
      status: yes
      note: "6-process Boothroyd-Dewhurst should-cost"
      evidence: "packages/kerf-costing/src/kerf_costing/tools.py"
---

# Kerf vs CalculiX

CalculiX runs the FEM — Kerf wraps it so structural analysis is as easy as describing the load case.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of CalculiX's feature surface (23 yes, 0 partial, 0 no out of 23 features tracked here). Kerf covers the full tracked feature set for CalculiX; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | CalculiX | Notes |
|---------|------|----------|-------|
| FE — solid (tet/hex) | ✅ | Yes | CalculiX bridge |
| Modal / buckling / nonlinear | ✅ | Yes | consistent-mass modal, Riks, J2 plasticity |
| FE — plate / shell (native) | ✅ | Yes | MITC4 Bathe-Dvorkin native; shell also via CalculiX bridge |
| FE — 1D beam / 2D truss (native) | ✅ | Yes | Hermite beam native; validated vs Roark |
| AISC 360-22 steel (members) | ✅ | No | full Ch. E/F/H/I, 50-section catalog |
| ACI 318-19 concrete | ✅ | No | flexure/shear/PM/dev-length |
| Eurocode design (EC2/3/5/8) | ✅ | No | EC2 concrete + EC3 steel + EC5 timber + EC8 seismic |
| ASCE 7-22 seismic | ✅ | No | ELF + RSA (SRSS+CQC) + Newmark time-history |
| ASCE 7-22 wind (MWFRS+C&C) | ✅ | No | MWFRS + C&C per ASCE 7-22 |
| Fatigue (S-N, ε-N, rainflow) | ✅ | Partial | S-N, ε-N, rainflow counting, Miner's rule |
| ASME VIII pressure vessel | ✅ | No | ASME VIII Div 1 thickness + nozzle + wind/seismic |
| Frame stiffness assembly (2D/3D) | ✅ | Yes | 2D+3D beam-column + ASCE 7 combos + story drift |
| API 650 tank | ✅ | No | API 650 incl. seismic annex E |
| NDS 2018 timber | ✅ | No | full NDS 2018 adjustment factors |
| AISC steel connections | ✅ | No | bolts/welds/base-plate, LRFD+ASD |
| Constraint sketcher (geo + dim) | ✅ | No | PlaneGCS WASM; geo + dim constraints |
| B-rep booleans (general NURBS) | ✅ | No | OCCT B-rep booleans |
| Assemblies — mates | ✅ | No | coincident/concentric/parallel/+BOM panel |
| 3-axis CAM (profile/contour/pocket/face) | ✅ | No | CAMView wired; opencamlib backend |
| CFD | ✅ | No | OpenFOAM bridge (needs install) |
| Thermo cycles (Rankine/Brayton/Otto) | ✅ | No | Rankine/Brayton/Otto/Diesel cycle analysis |
| Material selection (Ashby) | ✅ | No | 200 materials, 14 families, Pareto frontier |
| Should-cost (6 processes, Boothroyd-Dewhurst) | ✅ | No | 6-process Boothroyd-Dewhurst should-cost |

## What Kerf does that CalculiX doesn't

- **AISC 360-22 steel (members)** — full Ch. E/F/H/I, 50-section catalog
- **ACI 318-19 concrete** — flexure/shear/PM/dev-length
- **Eurocode design (EC2/3/5/8)** — EC2 concrete + EC3 steel + EC5 timber + EC8 seismic
- **ASCE 7-22 seismic** — ELF + RSA (SRSS+CQC) + Newmark time-history
- **ASCE 7-22 wind (MWFRS+C&C)** — MWFRS + C&C per ASCE 7-22
- **ASME VIII pressure vessel** — ASME VIII Div 1 thickness + nozzle + wind/seismic
- **API 650 tank** — API 650 incl. seismic annex E
- **NDS 2018 timber** — full NDS 2018 adjustment factors
- **AISC steel connections** — bolts/welds/base-plate, LRFD+ASD
- **Constraint sketcher (geo + dim)** — PlaneGCS WASM; geo + dim constraints
- **B-rep booleans (general NURBS)** — OCCT B-rep booleans
- **Assemblies — mates** — coincident/concentric/parallel/+BOM panel
- *(and 5 more features not covered by CalculiX)*

## Pricing

CalculiX is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
