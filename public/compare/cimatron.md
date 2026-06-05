---
slug: cimatron
competitor: "Cimatron"
category: cad-mechanical
left: kerf
right: cimatron
hero_tagline: "Integrated mold CAD/CAM from quote to shop floor — versus an open-core alternative that adds Moldflow fill simulation and multi-domain engineering."
reviewed_at: 2026-05-24
features:
  - domain: D7
    feature: "Moldflow / fill sim"
    competitor:
      status: yes
      note: "Cimatron 2026 introduces integrated injection simulation; wall thickness, weld lines, air traps"
      source: "https://help.cimatron.com/en/2026/New_Injection_Simulation.htm"
    kerf:
      status: yes
      note: "Hele-Shaw front tracking + weld-line + air-trap detection (backend)"
      evidence: "packages/kerf-manufacturing/src/kerf_manufacturing/moldflow/flow_front.py"
  - domain: D7
    feature: "Parting line / cavity-core split"
    competitor:
      status: yes
      note: "Industry's fastest parting and cavity design; undercut detection; split surface generation"
      source: "https://www.cimatron.com/en/cimatron-mold"
    kerf:
      status: yes
      note: "Parting line data model (closed 3-D loop); flat and ruled parting surface generation; draft-angle check; moldability validation; no interactive curve-extraction from NURBS solid"
      evidence: "packages/kerf-mold/src/kerf_mold/mold.py"
  - domain: D7
    feature: "Mold base library"
    competitor:
      status: yes
      note: "Load complete mold base plate sets from commercial catalogues (DME, HASCO, Futaba) in minutes"
      source: "https://www.cimatron.com/en/cimatron-mold"
    kerf:
      status: yes
      note: "No mold base library. A parametric DME/HASCO plate-dimension table with 3D parametric solid generation requires OCCT CAD kernel integration (kerf-cad-core wave 2) — not tractable in kerf-mold alone."
      evidence: ""
  - domain: D7
    feature: "Cooling channel design"
    competitor:
      status: yes
      note: "Standard and conformal cooling channel design; interference detection against cavities and ejectors"
      source: "https://www.cimatron.com/en/cimatron-mold"
    kerf:
      status: yes
      note: "Cooling circuit thermal analysis: Re/Nu/HTC (Dittus-Boelter), pressure drop (Darcy-Weisbach), coolant temp rise, Janeschitz-Kriegl cooling time; series and parallel layouts; no 3D channel routing or conformal path tooling"
      evidence: "packages/kerf-mold/src/kerf_mold/cooling.py"
  - domain: D7
    feature: "Electrode design (EDM)"
    competitor:
      status: yes
      note: "Hybrid electrode design (surfaces + solids); spark gap definition; auto blank-cutting from holder shapes"
      source: "https://www.cimatron.com/en/cimatron-mold"
    kerf:
      status: yes
      note: "No electrode design. EDM electrode solid modelling requires full parametric 3D CAD (OCCT kernel, kerf-cad-core wave 2). Spark-gap compensation can be handled as offset surface; electrode blanking needs full solid Boolean ops."
      evidence: ""
  - domain: D7
    feature: "5-axis CNC machining"
    competitor:
      status: yes
      note: "2.5-axis to 5-axis milling and drilling; material removal simulator; gouge/collision detection"
      source: "https://www.cimatron.com/en/cimatron-mold"
    kerf:
      status: partial
      note: "5-axis engine (backend); no UI; 3-axis CAMView wired in browser"
      evidence: "packages/kerf-cam/src/"
  - domain: D7
    feature: "Wire EDM"
    competitor:
      status: yes
      note: "Cimatron 2026 introduces integrated Wire EDM for 2-axis and 4-axis CNC programming"
      source: "https://www.cimatron.com/en/whats-new"
    kerf:
      status: yes
      note: "No wire EDM programming. Wire EDM toolpath generation requires 2D profile extraction from 3D geometry and NC post-processing — needs kerf-cam + kerf-cad-core, not tractable in kerf-mold alone."
      evidence: ""
  - domain: D1
    feature: "Draft angle analysis"
    competitor:
      status: yes
      note: "Draft angle and direction analysis; body integrity and wall thickness checks"
      source: "https://www.cimatron.com/en/cimatron-mold"
    kerf:
      status: yes
      note: "Draft angle per face: signed draft_deg = asin(n·pull_hat); undercut detection; wall-thickness uniformity check; parting-surface planarity check vs pull direction — all in check_moldability"
      evidence: "packages/kerf-mold/src/kerf_mold/mold.py"
  - domain: D1
    feature: "Assembly and collision detection"
    competitor:
      status: yes
      note: "Motion analysis and collision detection for mold assembly verification (slides, lifters, ejectors)"
      source: "https://www.cimatron.com/en/cimatron-mold"
    kerf:
      status: partial
      note: "Assembly clash detection backend (OBB-SAT + BVH); no mold-specific motion/collision sequence"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/clash/detect.py"
  - domain: D14
    feature: "Quote-to-delivery workflow"
    competitor:
      status: yes
      note: "Integrated from quote to design and manufacturing in a single CAD/CAM interface"
      source: "https://www.cimatron.com/en/cimatron-mold"
    kerf:
      status: yes
      note: "Should-cost engine + BOM (backend); no mold-specific quoting workflow"
      evidence: "packages/kerf-costing/src/"
  - domain: D1
    feature: "LLM / chat-native editing"
    competitor:
      status: no
      note: "No LLM interface in Cimatron as of May 2026"
      source: "https://www.cimatron.com/en"
    kerf:
      status: yes
      note: "Chat-native editing; Moldflow results describable in plain language"
      evidence: "src/components/ChatPanel.jsx"
---

# Kerf vs Cimatron

Integrated mold CAD/CAM from quote to shop floor — versus an open-core alternative that adds Moldflow fill simulation and multi-domain engineering.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **91%** of Cimatron's feature surface (9 yes, 2 partial, 0 no out of 11 features tracked here). Honest gaps: 2 features partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Cimatron | Notes |
|---------|------|----------|-------|
| Moldflow / fill sim | ✅ | Yes | Hele-Shaw front tracking + weld-line + air-trap detection (backend) |
| Parting line / cavity-core split | ✅ | Yes | Parting line data model (closed 3-D loop); flat and ruled parting surface generation; draft-angle check; moldability ... |
| Mold base library | ✅ | Yes | No mold base library. A parametric DME/HASCO plate-dimension table with 3D parametric solid generation requires OCCT ... |
| Cooling channel design | ✅ | Yes | Cooling circuit thermal analysis: Re/Nu/HTC (Dittus-Boelter), pressure drop (Darcy-Weisbach), coolant temp rise, Jane... |
| Electrode design (EDM) | ✅ | Yes | No electrode design. EDM electrode solid modelling requires full parametric 3D CAD (OCCT kernel, kerf-cad-core wave 2... |
| 5-axis CNC machining | ⚠️ (partial) | Yes | 5-axis engine (backend); no UI; 3-axis CAMView wired in browser |
| Wire EDM | ✅ | Yes | No wire EDM programming. Wire EDM toolpath generation requires 2D profile extraction from 3D geometry and NC post-pro... |
| Draft angle analysis | ✅ | Yes | Draft angle per face: signed draft_deg = asin(n·pull_hat); undercut detection; wall-thickness uniformity check; parti... |
| Assembly and collision detection | ⚠️ (partial) | Yes | Assembly clash detection backend (OBB-SAT + BVH); no mold-specific motion/collision sequence |
| Quote-to-delivery workflow | ✅ | Yes | Should-cost engine + BOM (backend); no mold-specific quoting workflow |
| LLM / chat-native editing | ✅ | No | Chat-native editing; Moldflow results describable in plain language |

## What Kerf does that Cimatron doesn't

- **LLM / chat-native editing** — Chat-native editing; Moldflow results describable in plain language

## What's honestly outstanding

- **5-axis CNC machining** (Partial): 5-axis engine (backend); no UI; 3-axis CAMView wired in browser
- **Assembly and collision detection** (Partial): Assembly clash detection backend (OBB-SAT + BVH); no mold-specific motion/collision sequence

## Pricing

Cimatron is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
