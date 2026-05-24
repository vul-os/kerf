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
      status: partial
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
      status: partial
      note: "Not yet implemented. These are large proprietary class-society rule trees (vessels > 24 m). ISO 12215-5 covers the open-standard tractable core for small craft."
      kerf_note: "Lloyd's / DNV / BV / ABS rules require licensed class-society agreements and significant rule-tree encoding. Deferred post-ISO-12215 shipping."
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
      status: partial
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

Maxsurf (now part of Bentley Systems) is the integrated naval architecture suite trusted by ship designers and yards worldwide for hull modelling, hydrostatics, stability, resistance prediction, seakeeping, and structural analysis. It operates from a single parametric 3D NURBS hull model that feeds all downstream analyses — intact and damage stability to IMO criteria, Holtrop-Mennen resistance, radiation-diffraction seakeeping, and longitudinal strength. Maxsurf is cross-discipline for the maritime domain. Kerf approaches naval architecture as an engineering engine: hydrostatics, stability, seakeeping, resistance prediction, and structural FEA — all from a Python API or chat prompt — but without Maxsurf's parametric hull modelling UI.

## Where Maxsurf is strong

- **Parametric hull form modelling.** Maxsurf's NURBS surface modeller with hull form wizards and interactive sketch tools is purpose-built for hull design — with automatic section generation, body plans, and fairness analysis. Kerf has NURBS mathematics but no hull-specific parametric modelling UI.
- **Single model → all analyses.** Changes to the hull form propagate immediately to hydrostatics, stability curves, resistance, and seakeeping — all from one parametric 3D model. Kerf's engines are wired separately.
- **Damage stability (probabilistic).** Full probabilistic damage stability to IMO SOLAS requirements — a regulatory requirement for most commercial vessels. Kerf's damage stability is simpler.
- **Sailing VPP.** Maxsurf includes an integrated velocity prediction programme for sailing vessels. Kerf has no sailing VPP.
- **Proprietary class rules (Lloyd's, DNV, BV, ABS).** Maxsurf Structure includes the full proprietary rule trees for vessels above the ISO 12215-5 scope. Kerf ships ISO 12215-5 (small craft ≤ 24 m) but not the licensed multi-society rule trees.
- **CAD interoperability.** Maxsurf reads and writes 3DM (Rhino), DGN (MicroStation), IGES, and DXF — the formats of the naval architecture supply chain. Kerf supports STEP and limited IGES.

## Where Kerf differs

- **MIT open-core.** Maxsurf is proprietary, subscription-priced (Bentley licensing). Kerf is MIT-licensed — free locally.
- **Sailing VPP.** Kerf includes a full velocity prediction programme: ITTC 1957 frictional resistance, Delft-series residuary resistance, empirical sail polar (CL/CD vs AWA for main+jib), apparent-wind model, equilibrium solver, and polar generation across TWS/TWA sweeps with VMG optimisation.
- **Multi-domain workspace.** Combine Kerf's marine engineering with structural FEA, thermal analysis, composites, and electronics in one project — typical for fast patrol vessels, autonomous surface vehicles, and naval platforms. Maxsurf is maritime-only.
- **ISO 12215-5 scantlings in the chat.** Full ISO 12215-5:2008 design-pressure → plate thickness → stiffener section modulus → longitudinal strength pipeline, usable as a single LLM tool call. Enter hull dimensions, get a structured JSON scantlings report.
- **Chat-native.** Describe vessel parameters in plain language; Kerf runs hydrostatics, stability, resistance, seakeeping, and scantlings in one conversation. Maxsurf has no LLM interface.
- **Python scripting.** kerf-sdk on PyPI for automated hull analysis workflows. Maxsurf scripting is limited.

## Honest gaps — where Kerf is behind today

- **No parametric hull form modeller.** The core of Maxsurf — NURBS hull modelling with fairness and section generation — is absent in Kerf.
- **No Lloyd's / DNV / BV / ABS rules.** ISO 12215-5 (small craft ≤ 24 m) is shipped. Proprietary multi-society rule trees for commercial vessels are not licensed.
- **Damage stability depth.** Maxsurf's probabilistic damage stability is more comprehensive than Kerf's implementation.
- **No marine UI.** Kerf's entire marine engineering capability is backend/LLM-tool; there is no interactive naval architecture panel in the browser.

## Side by side

| Feature | Kerf | Bentley Maxsurf |
|---|---|---|
| License | MIT open-core | Proprietary (Bentley subscription) |
| Primary focus | Multi-domain engineering CAD | Naval architecture |
| Hull form modelling (NURBS) | Partial (no hull UI) | Yes (purpose-built) |
| Hydrostatics | Yes (backend) | Yes |
| Intact + damage stability | Yes (backend) | Yes (IMO SOLAS probabilistic) |
| Resistance prediction | Yes (Holtrop-Mennen, backend) | Yes |
| Seakeeping / RAOs | Yes (backend) | Yes (radiation diffraction) |
| Sailing VPP | Yes (ITTC+Delft+sail polar, backend) | Yes |
| Structural / scantlings — ISO 12215-5 | Yes (shipped 2026-05-24) | Yes |
| Structural / scantlings — Lloyd's/DNV/BV/ABS | No (proprietary rules) | Yes |
| Marine UI | None (backend only) | Full integrated GUI |
| Chat / LLM editing | Chat-native | None |
| Open source | Yes (MIT) | No |

---
*Last reviewed: 2026-05-24. Competitor information sourced from Bentley Maxsurf product pages. Kerf capabilities reflect the current shipped product.*
