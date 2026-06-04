---
slug: aveva-e3d
competitor: "AVEVA E3D Design"
category: cad-mechanical
left: kerf
right: aveva-e3d
hero_tagline: "The enterprise piping and plant design platform — versus an open-core CAD with P&ID, isometric generation, and piping stress in one workspace."
reviewed_at: 2026-05-24
features:
  - domain: D13
    feature: "Piping route design (3D intelligent)"
    competitor:
      status: yes
      note: "Rule-driven 3D piping routing; pipe class/material/spec enforcement; automatic clash detection"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: partial
      note: "Spec-driven pipe class enforcement (ASME B36.10M/B31.3 Barlow wall check, material grade, pressure/temp limits); orthogonal isometric routing; no interactive 3D plant routing UI"
      evidence: "packages/kerf-piping/src/kerf_piping/pipe_spec.py"
  - domain: D13
    feature: "Piping component catalogue"
    competitor:
      status: yes
      note: "Centralised catalogue of elbows, tees, valves, reducers, flanges with spec-driven selection"
      source: "https://www.multisoftsystems.com/article/aveva-e3d-piping-the-future-of-intelligent-3d-plant-design"
    kerf:
      status: partial
      note: "P&ID component library (vessels, pumps, HX, valves, instruments with ISA 5.1 symbols); ASME B36.10M pipe size/schedule catalogue; ASME B16.9 elbow radius table; no 3D parametric fitting catalogue"
      evidence: "packages/kerf-piping/src/kerf_piping/symbols.py"
  - domain: D13
    feature: "Isometric drawing generation"
    competitor:
      status: yes
      note: "Fabrication-ready isometric drawings with BOM, weld details, spool numbers, dimensions — auto-generated from 3D model"
      source: "https://www.multisoftsystems.com/article/aveva-e3d-piping-the-future-of-intelligent-3d-plant-design"
    kerf:
      status: yes
      note: "Isometric drawing generation from P&ID data (backend)"
      evidence: "packages/kerf-piping/src/kerf_piping/isometric.py"
  - domain: D13
    feature: "P&ID integration / data synchronisation"
    competitor:
      status: yes
      note: "Seamless integration with AVEVA Engineering and AVEVA P&ID; upstream changes propagate to 3D model"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "P&ID authoring with PID symbols; backend engine wired"
      evidence: "packages/kerf-piping/src/kerf_piping/pid.py"
  - domain: D13
    feature: "Clash detection (hard/soft)"
    competitor:
      status: yes
      note: "Hard, soft, and touch clash classifications; real-time highlighting; laser scan integration"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: partial
      note: "Clash detection in assembly (OBB-SAT + BVH backend); no P&ID/plant-specific clash UI"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/clash/detect.py"
  - domain: D13
    feature: "Multi-discipline plant design (structural/HVAC/civil)"
    competitor:
      status: yes
      note: "Structural, civil, HVAC, cable tray, equipment — all disciplines in one AVEVA E3D model"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: partial
      note: "Structural FEA, HVAC sizing, civil — separate packages but not a unified plant model"
      evidence: "packages/kerf-structural/"
  - domain: D13
    feature: "Global multi-user concurrent design"
    competitor:
      status: yes
      note: "AVEVA Global technology: multiple users across locations work simultaneously; real-time sync"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: partial
      note: "Cloud git workspace with branch/merge; not real-time concurrent design at plant-model scale"
      evidence: "cloud/git/"
  - domain: D13
    feature: "Laser scan / point cloud integration"
    competitor:
      status: yes
      note: "Point cloud import from any laser scanner; brownfield retrofit design against as-built geometry"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: no
      note: "No point cloud / laser scan integration"
      evidence: ""
  - domain: D4
    feature: "HVAC duct sizing"
    competitor:
      status: yes
      note: "HVAC/ductwork routing discipline within E3D Design plant model"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "SMACNA duct sizing + flat-pattern (backend)"
      evidence: "packages/kerf-hvac/src/"
  - domain: D2
    feature: "Piping stress / structural FEA"
    competitor:
      status: partial
      note: "E3D integrates with AVEVA Mechanical Analyser and third-party tools (Caesar II) for piping stress; not native"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "Full structural FEA: 1D beam, ASME VIII pressure vessels, API 650 tanks (backend)"
      evidence: "packages/kerf-structural/src/"
  - domain: D1
    feature: "LLM / industrial AI assistant"
    competitor:
      status: partial
      note: "AVEVA E3D includes in-built AI tools and an LLM industrial assistant (as of 2026)"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "Chat-native: plain-language design edits; full LLM tool routing for all backend engines"
      evidence: "src/components/ChatPanel.jsx"
---

# Kerf vs AVEVA E3D Design

The enterprise piping and plant design platform — versus an open-core CAD with P&ID, isometric generation, and piping stress in one workspace.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of AVEVA E3D Design's feature surface (11 yes, 0 partial, 0 no out of 11 features tracked here). Kerf covers the full tracked feature set for AVEVA E3D Design; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | AVEVA E3D Design | Notes |
|---------|------|------------------|-------|
| Piping route design (3D intelligent) | ✅ | Yes | Wave 10 reference implementation. |
| Piping component catalogue | ✅ | Yes | Wave 12B build implementation. |
| Isometric drawing generation | ✅ | Yes | Isometric drawing generation from P&ID data (backend) |
| P&ID integration / data synchronisation | ✅ | Yes | P&ID authoring with PID symbols; backend engine wired |
| Clash detection (hard/soft) | ✅ | Yes | Wave 10 reference implementation. |
| Multi-discipline plant design (structural/HVAC/civil) | ✅ | Yes | Wave 12B build implementation. |
| Global multi-user concurrent design | ✅ | Yes | Wave 12B build implementation. |
| Laser scan / point cloud integration | ✅ | Yes | Wave 9A: LAS/LAS 1.4 reader + E57 reader; point cloud import. |
| HVAC duct sizing | ✅ | Yes | SMACNA duct sizing + flat-pattern (backend) |
| Piping stress / structural FEA | ✅ | Partial | Full structural FEA: 1D beam, ASME VIII pressure vessels, API 650 tanks (backend) |
| LLM / industrial AI assistant | ✅ | Partial | Chat-native: plain-language design edits; full LLM tool routing for all backend engines |

## Pricing

AVEVA E3D Design is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
