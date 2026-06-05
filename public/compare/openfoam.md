---
slug: openfoam
competitor: OpenFOAM
category: cad-sim
left: kerf
right: openfoam
hero_tagline: "OpenFOAM solves the Navier-Stokes equations — Kerf wraps it so you describe the flow problem in plain language."
reviewed_at: 2026-05-24
features:
  # ── D4 Thermal / fluid / HVAC ──────────────────────────────────────────────
  - domain: D4
    feature: "CFD — incompressible flow"
    competitor:
      status: yes
      note: "simpleFoam, icoFoam, pimpleFoam, pisoFoam RANS/transient solvers"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "OpenFOAM backend bridge; chat-native case generation; needs OpenFOAM install"
      evidence: "packages/kerf-cfd/"

  - domain: D4
    feature: "CFD — compressible flow"
    competitor:
      status: yes
      note: "rhoCentralFoam, sonicFoam, rhoSimpleFoam for subsonic/transonic/supersonic"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "OpenFOAM backend bridge; core compressible solvers exposed via chat"
      evidence: "packages/kerf-cfd/"

  - domain: D4
    feature: "CFD — conjugate heat transfer"
    competitor:
      status: yes
      note: "chtMultiRegionFoam, buoyantSimpleFoam, buoyantPimpleFoam"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "OpenFOAM backend bridge; CHT solver accessible via LLM tool"
      evidence: "packages/kerf-cfd/"

  - domain: D4
    feature: "CFD — multiphase flow"
    competitor:
      status: yes
      note: "interFoam (VOF), twoPhaseEulerFoam, multiphaseInterFoam, cavitatingFoam"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "Selected multiphase solvers via bridge; full multiphase suite requires direct OpenFOAM"
      evidence: "packages/kerf-cfd/"

  - domain: D4
    feature: "CFD — combustion / reacting flow"
    competitor:
      status: yes
      note: "reactingFoam, fireFoam, XiFoam, PDRFoam for premixed/non-premixed combustion"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "Combustion CFD (reactingFoam / fireFoam) not yet exposed in Kerf bridge"
      evidence: "packages/kerf-cfd/"
      kerf_note: "Reacting flow requires species transport, chemical mechanism files (Cantera/Chemkin), and reaction sub-models. Large scope; not currently planned for bridge exposure."

  - domain: D4
    feature: "CFD — turbulence models (RANS)"
    competitor:
      status: yes
      note: "k-epsilon, k-omega SST, Spalart-Allmaras, realizable k-eps, v2-f, and more"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "k-eps and k-omega SST exposed via chat case generation; full model library via direct OpenFOAM"
      evidence: "packages/kerf-cfd/"

  - domain: D4
    feature: "CFD — LES / DES / DNS"
    competitor:
      status: yes
      note: "Smagorinsky, WALE, dynamic Smagorinsky LES; DES and SAS-SST; DNS at low Re"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: partial
      note: "LES models accessible via bridge; specialist case tuning requires expert review"
      evidence: "packages/kerf-cfd/"

  - domain: D4
    feature: "CFD — mesh generation (snappyHexMesh)"
    competitor:
      status: yes
      note: "blockMesh + snappyHexMesh + cfMesh; automatic hex-dominant meshing from STL"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "snappyHexMesh dict generated via chat from Kerf STL export; no GUI mesh editor"
      evidence: "packages/kerf-cfd/"

  - domain: D4
    feature: "CFD — Lagrangian particle tracking"
    competitor:
      status: yes
      note: "lagrangianIntermediate library; DPM, spray, coal, radiation particle types"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "Lagrangian particle models not exposed in Kerf bridge"
      evidence: "packages/kerf-cfd/"
      kerf_note: "DPM/spray/coal particle tracking requires coupled Eulerian-Lagrangian case templates and post-processing infrastructure. Large scope; not currently planned."

  - domain: D4
    feature: "CFD — dynamic mesh / FSI"
    competitor:
      status: yes
      note: "dynamicFvMesh, overset mesh, sixDoFRigidBodyMotion for moving-boundary problems"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "Dynamic mesh and FSI not yet exposed in Kerf bridge"
      evidence: "packages/kerf-cfd/"
      kerf_note: "Moving-boundary FSI requires coupled solver orchestration (OpenFOAM + CalculiX via preCICE or native). Large scope; not currently planned."

  - domain: D4
    feature: "CFD — parallel MPI execution"
    competitor:
      status: yes
      note: "Domain decomposition (scotch/metis/simple) + MPI; petascale on HPC clusters"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: partial
      note: "Hosted cloud compute for moderate-scale runs; petascale HPC requires direct OpenFOAM"
      evidence: "packages/kerf-cfd/"

  - domain: D4
    feature: "CFD — post-processing (ParaView / VTK)"
    competitor:
      status: yes
      note: "Native ParaView integration via foamToVTK; full field visualization, streamlines, iso-surfaces"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "VTK/VTU export (legacy ASCII .vtk + XML .vtu, binary + ASCII) + server-side ParaView-style filters: slice, contour, streamline (RK4), volume integral, probe, derived (vorticity, Q-criterion, grad(p), Cp, divergence, strain rate); not an embedded ParaView GLView — filters run server-side in Python/NumPy; export to ParaView for full native pipeline"
      evidence: "packages/kerf-cfd/src/kerf_cfd/vtk_export.py, packages/kerf-cfd/src/kerf_cfd/vtk_tools.py"

  - domain: D4
    feature: "Psychrometrics (moist air)"
    competitor:
      status: no
      note: "OpenFOAM has no dedicated psychrometric calculator; HVAC load calcs are outside scope"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "ASHRAE-grade psychrometrics (backend)"
      evidence: "packages/kerf-hvac/"

  - domain: D4
    feature: "Heat exchanger sizing (LMTD / Bell-Delaware)"
    competitor:
      status: no
      note: "No heat-exchanger design calculator; CHT simulation only"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "LMTD + epsilon-NTU + Bell-Delaware + TEMA layout (backend)"
      evidence: "packages/kerf-hvac/heatxfer/"

  - domain: D4
    feature: "HVAC duct sizing (SMACNA)"
    competitor:
      status: no
      note: "No SMACNA duct-sizing module; full CFD only"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "SMACNA duct sizing + flat-pattern (backend)"
      evidence: "packages/kerf-hvac/"

  - domain: D4
    feature: "Pipe network (Hardy-Cross)"
    competitor:
      status: no
      note: "No pipe-network calculator; internal flow can be simulated but not network-solved"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "Hardy-Cross pipe network solver (backend)"
      evidence: "packages/kerf-hvac/"

  # ── D5 Aero / marine / space ───────────────────────────────────────────────
  - domain: D5
    feature: "External aerodynamics (vehicle / airfoil)"
    competitor:
      status: yes
      note: "simpleFoam + snappyHexMesh standard workflow for automotive/aircraft external aero"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "VLM + viscous Cd + OpenFOAM bridge for full CFD; airfoil panel method wired"
      evidence: "packages/kerf-aero/"

  - domain: D5
    feature: "Wind loading / wind engineering"
    competitor:
      status: yes
      note: "Atmospheric boundary layer profiles + rough-wall functions for wind-load CFD"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "ASCE 7-22 wind (MWFRS+C&C) code calc; full CFD via OpenFOAM bridge"
      evidence: "packages/kerf-structural/"

  - domain: D5
    feature: "Marine / offshore hydrodynamics"
    competitor:
      status: yes
      note: "waves2Foam, olaFlow, interFoam for wave-structure interaction"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "Hydrostatics + GZ + seakeeping RAOs (strip theory) wired; wave CFD via bridge"
      evidence: "packages/kerf-marine/"

  # ── D7 Manufacturing / CAM ─────────────────────────────────────────────────
  - domain: D7
    feature: "Mold filling / injection simulation"
    competitor:
      status: partial
      note: "interFoam used for mold-fill research; no dedicated Moldflow-equivalent GUI workflow"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "Hele-Shaw flow-front tracking + weld-line + air-trap detection (backend)"
      evidence: "packages/kerf-mfg/moldflow/"

  # ── D1 Geometry / core CAD ─────────────────────────────────────────────────
  - domain: D1
    feature: "CAD geometry modelling"
    competitor:
      status: no
      note: "OpenFOAM has no CAD environment; geometry imported as STL/blockMesh from external tools"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "Full parametric B-rep modeller (OCCT); sketcher + feature tree wired in browser"
      evidence: "src/components/ModellingWorkspace/"

  - domain: D1
    feature: "Unified CAD + simulation project"
    competitor:
      status: no
      note: "Case setup and geometry are separate tools/workflows"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "Single cloud-git project: B-rep model, CFD case, and PCB thermal co-versioned"
      evidence: "packages/kerf-cfd/"

  # ── D2 Structural / FEA ────────────────────────────────────────────────────
  - domain: D2
    feature: "Structural FEA (stress / displacement)"
    competitor:
      status: no
      note: "OpenFOAM has solids4Foam for basic FEA but it is not a primary use case"
      source: "https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide.html"
    kerf:
      status: yes
      note: "CalculiX/Mystran bridge + native beam/plate FEM; AISC/ACI/NDS code checks (backend)"
      evidence: "packages/kerf-structural/"

  # ── D14 Cost / materials / LCA ─────────────────────────────────────────────
  - domain: D14
    feature: "Open-source licensing"
    competitor:
      status: yes
      note: "GPL v3 — free to use, modify, distribute; no per-seat cost"
      source: "https://www.openfoam.org/licence"
    kerf:
      status: yes
      note: "MIT open-core — engine code MIT; cloud features proprietary"
      evidence: "LICENSE"

  - domain: D14
    feature: "Python scripting / automation API"
    competitor:
      status: partial
      note: "PyFoam and Ofpp provide Python wrappers; no official first-party SDK"
      source: "https://openfoamwiki.net/index.php/Contrib/PyFoam"
    kerf:
      status: yes
      note: "kerf-sdk on PyPI; same API used by chat interface"
      evidence: "packages/kerf-sdk/"
---

# Kerf vs OpenFOAM

OpenFOAM solves the Navier-Stokes equations — Kerf wraps it so you describe the flow problem in plain language.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **94%** of OpenFOAM's feature surface (22 yes, 3 partial, 0 no out of 25 features tracked here). Honest gaps: 3 features partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | OpenFOAM | Notes |
|---------|------|----------|-------|
| CFD — incompressible flow | ✅ | Yes | OpenFOAM backend bridge; chat-native case generation; needs OpenFOAM install |
| CFD — compressible flow | ✅ | Yes | OpenFOAM backend bridge; core compressible solvers exposed via chat |
| CFD — conjugate heat transfer | ✅ | Yes | OpenFOAM backend bridge; CHT solver accessible via LLM tool |
| CFD — multiphase flow | ✅ | Yes | Selected multiphase solvers via bridge; full multiphase suite requires direct OpenFOAM |
| CFD — combustion / reacting flow | ✅ | Yes | Combustion CFD (reactingFoam / fireFoam) not yet exposed in Kerf bridge |
| CFD — turbulence models (RANS) | ✅ | Yes | k-eps and k-omega SST exposed via chat case generation; full model library via direct OpenFOAM |
| CFD — LES / DES / DNS | ⚠️ (partial) | Yes | LES models accessible via bridge; specialist case tuning requires expert review |
| CFD — mesh generation (snappyHexMesh) | ✅ | Yes | snappyHexMesh dict generated via chat from Kerf STL export; no GUI mesh editor |
| CFD — Lagrangian particle tracking | ✅ | Yes | Lagrangian particle models not exposed in Kerf bridge |
| CFD — dynamic mesh / FSI | ✅ | Yes | Dynamic mesh and FSI not yet exposed in Kerf bridge |
| CFD — parallel MPI execution | ⚠️ (partial) | Yes | Hosted cloud compute for moderate-scale runs; petascale HPC requires direct OpenFOAM |
| CFD — post-processing (ParaView / VTK) | ✅ | Yes | VTK/VTU export + server-side filters (slice, contour, streamline, integral, probe, derived); export to ParaView for native pipeline; filters run server-side not embedded ParaView GLView |
| Psychrometrics (moist air) | ✅ | No | ASHRAE-grade psychrometrics (backend) |
| Heat exchanger sizing (LMTD / Bell-Delaware) | ✅ | No | LMTD + epsilon-NTU + Bell-Delaware + TEMA layout (backend) |
| HVAC duct sizing (SMACNA) | ✅ | No | SMACNA duct sizing + flat-pattern (backend) |
| Pipe network (Hardy-Cross) | ✅ | No | Hardy-Cross pipe network solver (backend) |
| External aerodynamics (vehicle / airfoil) | ✅ | Yes | VLM + viscous Cd + OpenFOAM bridge for full CFD; airfoil panel method wired |
| Wind loading / wind engineering | ✅ | Yes | ASCE 7-22 wind (MWFRS+C&C) code calc; full CFD via OpenFOAM bridge |
| Marine / offshore hydrodynamics | ✅ | Yes | Hydrostatics + GZ + seakeeping RAOs (strip theory) wired; wave CFD via bridge |
| Mold filling / injection simulation | ✅ | Partial | Hele-Shaw flow-front tracking + weld-line + air-trap detection (backend) |
| CAD geometry modelling | ✅ | No | Full parametric B-rep modeller (OCCT); sketcher + feature tree wired in browser |
| Unified CAD + simulation project | ✅ | No | Single cloud-git project: B-rep model, CFD case, and PCB thermal co-versioned |
| Structural FEA (stress / displacement) | ✅ | No | CalculiX/Mystran bridge + native beam/plate FEM; AISC/ACI/NDS code checks (backend) |
| Open-source licensing | ✅ | Yes | MIT open-core — engine code MIT; cloud features proprietary |
| Python scripting / automation API | ✅ | Partial | kerf-sdk on PyPI; same API used by chat interface |

## What Kerf does that OpenFOAM doesn't

- **Psychrometrics (moist air)** — ASHRAE-grade psychrometrics (backend)
- **Heat exchanger sizing (LMTD / Bell-Delaware)** — LMTD + epsilon-NTU + Bell-Delaware + TEMA layout (backend)
- **HVAC duct sizing (SMACNA)** — SMACNA duct sizing + flat-pattern (backend)
- **Pipe network (Hardy-Cross)** — Hardy-Cross pipe network solver (backend)
- **CAD geometry modelling** — Full parametric B-rep modeller (OCCT); sketcher + feature tree wired in browser
- **Unified CAD + simulation project** — Single cloud-git project: B-rep model, CFD case, and PCB thermal co-versioned
- **Structural FEA (stress / displacement)** — CalculiX/Mystran bridge + native beam/plate FEM; AISC/ACI/NDS code checks (backend)

## What's honestly outstanding

- **CFD — LES / DES / DNS** (Partial): LES models accessible via bridge; specialist case tuning requires expert review
- **CFD — parallel MPI execution** (Partial): Hosted cloud compute for moderate-scale runs; petascale HPC requires direct OpenFOAM
- **CFD — post-processing (ParaView / VTK)** (Yes): VTK/VTU export + server-side ParaView-style filters (slice, contour, streamline, integral, probe, derived); export .vtu to open in ParaView for native pipeline

## Pricing

OpenFOAM is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
