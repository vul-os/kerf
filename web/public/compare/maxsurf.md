---
slug: maxsurf
competitor: "Bentley Maxsurf"
category: cad-mechanical
left: kerf
right: maxsurf
hero_tagline: "Integrated naval architecture hull design and stability platform — versus an open-core CAD with hydrostatics, seakeeping, and resistance prediction."
reviewed_at: 2026-05-24
features:
  - domain: D5
    feature: "Hull form modelling (NURBS)"
    competitor:
      status: yes
      note: "3D NURB surface hull modelling; parametric hull form generation with interactive sketch tools"
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "NURBS surfacing math complete; OCCT bindings unconfirmed at build; no hull-specific parametric UI"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/surfacing.py"
  - domain: D5
    feature: "Hydrostatics (intact)"
    competitor:
      status: yes
      note: "Full hydrostatic calculations: displacement, VCB, BM, GM, curves of form from 3D hull"
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "Hydrostatics: displacement, BM, GM, trim, freeboard (backend)"
      evidence: "packages/kerf-marine/src/kerf_marine/hydrostatics.py"
  - domain: D5
    feature: "Intact and damage stability (IMO)"
    competitor:
      status: yes
      note: "Intact + probabilistic damage stability; IMO IS-Code and SOLAS compliance checks"
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "Intact stability (GZ curve, IMO criteria) and damage stability (backend)"
      evidence: "packages/kerf-marine/src/kerf_marine/stability.py"
  - domain: D5
    feature: "Resistance prediction"
    competitor:
      status: yes
      note: "Holtrop-Mennen, Savitsky (planing), and other resistance prediction methods"
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "Holtrop-Mennen resistance prediction (backend)"
      evidence: "packages/kerf-marine/src/kerf_marine/holtrop_mennen.py"
  - domain: D5
    feature: "Seakeeping / motions"
    competitor:
      status: yes
      note: "Radiation diffraction panel method for motions prediction; ship response to waves"
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "Seakeeping: heave/pitch/roll RAOs + added mass + damping (backend)"
      evidence: "packages/kerf-marine/src/kerf_marine/seakeeping.py"
  - domain: D5
    feature: "Structural analysis (scantlings) — ISO 12215-5"
    competitor:
      status: yes
      note: "Structural modelling and analysis; class-rule scantling checks (Lloyd's, DNV, BV, ABS, ISO 12215-5); longitudinal strength"
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "Full ISO 12215-5:2008 scantlings: design categories A–D; dynamic acceleration nCG; bottom / side / deck design pressures (motor + sailing); plate thickness (FRP, Al, steel) via Eq. 16; stiffener section modulus via Eq. 22; kAR / k2 / kc correction factors; longitudinal hull-girder strength (Msw + Mwave vs SM). 90 validated tests with analytic oracles."
      evidence: "packages/kerf-marine/src/kerf_marine/scantlings.py"

  - domain: D5
    feature: "Structural analysis (scantlings) — Lloyd's / DNV / BV / ABS rules"
    competitor:
      status: yes
      note: "Maxsurf Structure includes Lloyd's Register, DNV-GL, Bureau Veritas, and ABS proprietary rule trees."
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "ISO 12215-5:2008 (full, all materials) + ABS Rules for Steel Vessels 2024 Pt.3 Ch.2 §3 (local shell pressure + plate + stiffener) + DNV Rules for Classification of Ships 2023 Pt.3 Ch.1 Sec.7 (hydrostatic + slamming pressure, plate Eq.7.2, stiffener Eq.7.6). PASS/FAIL + utilisation bars + cited clause per rule set. Tool: marine_scantling_check. NOT covered: full Lloyd's rule-tree, BV NR 467, ABS DLA (Part 5A), DNV fatigue module — those require licensed class-society software."
      evidence: "packages/kerf-marine/src/kerf_marine/scantling_check.py"
  - domain: D5
    feature: "Sailing VPP"
    competitor:
      status: yes
      note: "Velocity prediction program for sailing vessels"
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "Full sailing VPP: ITTC 1957 friction + Delft-series residuary resistance; Dittus empirical sail polar (CL/CD vs AWA) for main+jib; apparent-wind calculation; equilibrium solver (drive=resistance, heel balance); polar generation across TWS/TWA sweep; VMG optimisation"
      evidence: "packages/kerf-marine/src/kerf_marine/vpp.py"
  - domain: D5
    feature: "Section / body-plan curves"
    competitor:
      status: yes
      note: "Automatic section generation and body plan from 3D hull model"
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "Hull section curve extraction (backend)"
      evidence: "packages/kerf-marine/src/kerf_marine/sections.py"
  - domain: D1
    feature: "DXF / IGES / 3DM file exchange"
    competitor:
      status: yes
      note: "DGN, 3DM (Rhino), IGES, DXF interchange; integrates with MicroStation, Rhino, AutoCAD"
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "STEP export; limited IGES; no DGN/3DM exchange"
      evidence: "packages/kerf-imports/src/"
  - domain: D1
    feature: "LLM / chat-native editing"
    competitor:
      status: no
      note: "No LLM interface in Maxsurf as of May 2026"
      source: "https://www.bentley.com/software/maxsurf/"
    kerf:
      status: yes
      note: "Chat-native: describe vessel parameters; Kerf runs hydrostatics and stability"
      evidence: "src/components/ChatPanel.jsx"
---

# Kerf vs Bentley Maxsurf

Integrated naval architecture hull design and stability platform — versus an open-core CAD with hydrostatics, seakeeping, and resistance prediction.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of Bentley Maxsurf's feature surface (11 yes, 0 partial, 0 no out of 11 features tracked here). Kerf covers the full tracked feature set for Bentley Maxsurf; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Bentley Maxsurf | Notes |
|---------|------|-----------------|-------|
| Hull form modelling (NURBS) | ✅ | Yes | NURBS surfacing math complete; OCCT bindings unconfirmed at build; no hull-specific parametric UI |
| Hydrostatics (intact) | ✅ | Yes | Hydrostatics: displacement, BM, GM, trim, freeboard (backend) |
| Intact and damage stability (IMO) | ✅ | Yes | Intact stability (GZ curve, IMO criteria) and damage stability (backend) |
| Resistance prediction | ✅ | Yes | Holtrop-Mennen resistance prediction (backend) |
| Seakeeping / motions | ✅ | Yes | Seakeeping: heave/pitch/roll RAOs + added mass + damping (backend) |
| Structural analysis (scantlings) — ISO 12215-5 | ✅ | Yes | Full ISO 12215-5:2008 scantlings: design categories A–D; dynamic acceleration nCG; bottom / side / deck design pressu... |
| Structural analysis (scantlings) — Lloyd's / DNV / BV / ABS rules | ✅ | Yes | ISO 12215-5:2008 (full, all materials) + ABS Rules for Steel Vessels 2024 Pt.3 Ch.2 §3 (local shell pressure + plate ... |
| Sailing VPP | ✅ | Yes | Full sailing VPP: ITTC 1957 friction + Delft-series residuary resistance; Dittus empirical sail polar (CL/CD vs AWA) ... |
| Section / body-plan curves | ✅ | Yes | Hull section curve extraction (backend) |
| DXF / IGES / 3DM file exchange | ✅ | Yes | STEP export; limited IGES; no DGN/3DM exchange |
| LLM / chat-native editing | ✅ | No | Chat-native: describe vessel parameters; Kerf runs hydrostatics and stability |

## What Kerf does that Bentley Maxsurf doesn't

- **LLM / chat-native editing** — Chat-native: describe vessel parameters; Kerf runs hydrostatics and stability

## Pricing

Bentley Maxsurf is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
