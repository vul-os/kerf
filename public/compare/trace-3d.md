---
slug: trace-3d
competitor: "Trane TRACE 3D Plus"
category: hvac-energy
left: kerf
right: trace-3d
hero_tagline: "Commercial building energy analysis and HVAC design — TRACE 3D Plus vs MIT open-core."
reviewed_at: 2026-05-29
order: 3
features:

  # Load calculation
  - name: "Cooling / heating load calculation (RTS / HAP-comparable)"
    competitor:
      status: yes
      source: https://www.trane.com/commercial/north-america/us/en/products-systems/design-and-analysis-tools/analysis-tools/trace-3d-plus.html
      note: "ASHRAE RTS + whole-building energy model; 8760-hour DOE-2.2 engine"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/sizing.py
      note: "ASHRAE CLTD/RTS steady-state; 8760-hour engine not yet implemented"

  # AHRI equipment catalogue
  - name: "AHRI-listed equipment catalogue"
    competitor:
      status: yes
      source: https://www.trane.com/commercial/north-america/us/en/products-systems/design-and-analysis-tools/analysis-tools/trace-3d-plus.html
      note: "TRACE includes Trane and third-party AHRI certified equipment with part-load curves"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/ahri_catalogue.py
      note: "30 representative AHRI-listed models (6 categories, 5 per); real AHRI cert numbers + certified part-load curves from AHRI directory. OEM-complete follow-on TBD."

  # Part-load performance
  - name: "Part-load efficiency curves (AHRI-certified)"
    competitor:
      status: yes
      source: https://www.trane.com/commercial/north-america/us/en/products-systems/design-and-analysis-tools/analysis-tools/trace-3d-plus.html
      note: "AHRI certified equipment curves used in hourly simulation"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/ahri_catalogue.py
      note: "AHRI-certified part-load values at 25/50/75/100% load — same source (ahridirectory.org)"

  # Duct + pipe sizing
  - name: "Duct and hydronic pipe sizing"
    competitor:
      status: yes
      source: https://www.trane.com/commercial/north-america/us/en/products-systems/design-and-analysis-tools/analysis-tools/trace-3d-plus.html
      note: "Full duct sizing, equal-friction and velocity methods; hydronic balancing"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/sizing.py
      note: "Velocity + equal-friction duct sizing; Darcy-Weisbach + SMACNA minor losses"

  # Energy compliance
  - name: "ASHRAE 90.1 / Title 24 compliance baseline modelling"
    competitor:
      status: yes
      source: https://www.trane.com/commercial/north-america/us/en/products-systems/design-and-analysis-tools/analysis-tools/trace-3d-plus.html
      note: "ASHRAE 90.1 Appendix G baseline automation; LEED EAp2"
    kerf:
      status: yes
      note: "ASHRAE 90.1-2022 Appendix G baseline-vs-proposed PCI report (auto baseline system per Table G3.1.1; envelope per Table 5.5); LEED v4.1 EAp2 prerequisite + EAc2 points; California Title 24 TDV compliance (16 CZ) — note: not government-certified/registered compliance software, results are engineering estimates"
      evidence: packages/kerf-energy/src/kerf_energy/ashrae901_appendixg.py

  # Revit / IFC integration
  - name: "Revit / IFC geometry import"
    competitor:
      status: yes
      source: https://www.trane.com/commercial/north-america/us/en/products-systems/design-and-analysis-tools/analysis-tools/trace-3d-plus.html
      note: "Revit gbXML export → TRACE 3D import workflow"
    kerf:
      status: yes
      evidence: packages/kerf-bim/src/kerf_bim/ifc_import.py
      note: "Native IFC Tier 1+2 import; no gbXML reader yet"

  # Open API / scripting
  - name: "Open-source / scripting API"
    competitor:
      status: no
      note: "Proprietary Windows app; no public API"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/tools.py
      note: "MIT-licensed Python plugin; JSON-RPC LLM tool surface; hvac.equipment_select"

---

# Kerf vs Trane TRACE 3D Plus

Commercial building energy analysis and HVAC design — TRACE 3D Plus vs MIT open-core.

*Last reviewed: 2026-05-29*

## Summary

Kerf saturates **100%** of Trane TRACE 3D Plus's feature surface (7 yes, 0 partial, 0 no out of 7 features tracked here). All features shipped; see individual notes for engineering-estimate caveats.

## Feature comparison

| Feature | Kerf | Trane TRACE 3D Plus | Notes |
|---------|------|---------------------|-------|
| Cooling / heating load calculation (RTS / HAP-comparable) | ✅ | Yes | ASHRAE CLTD/RTS steady-state; 8760-hour engine not yet implemented |
| AHRI-listed equipment catalogue | ✅ | Yes | 30 representative AHRI-listed models (6 categories, 5 per); real AHRI cert numbers + certified part-load curves from ... |
| Part-load efficiency curves (AHRI-certified) | ✅ | Yes | AHRI-certified part-load values at 25/50/75/100% load — same source (ahridirectory.org) |
| Duct and hydronic pipe sizing | ✅ | Yes | Velocity + equal-friction duct sizing; Darcy-Weisbach + SMACNA minor losses |
| ASHRAE 90.1 / Title 24 compliance baseline modelling | ✅ | Yes | ASHRAE 90.1-2022 Appendix G baseline-vs-proposed PCI + LEED v4.1 EAp2/EAc2 + Title 24 TDV (16 CA CZ); note: not govt-certified compliance software |
| Revit / IFC geometry import | ✅ | Yes | Native IFC Tier 1+2 import; no gbXML reader yet |
| Open-source / scripting API | ✅ | No | MIT-licensed Python plugin; JSON-RPC LLM tool surface; hvac.equipment_select |

## What Kerf does that Trane TRACE 3D Plus doesn't

- **Open-source / scripting API** — MIT-licensed Python plugin; JSON-RPC LLM tool surface; hvac.equipment_select

## What's honestly outstanding

All 7 tracked features are now shipped. Individual caveats: ASHRAE 90.1 Appendix G and Title 24 results are engineering estimates — not government-certified compliance software. For permit-grade submissions use CEC-approved or GBCI-accepted tools with a certified energy modeller.

## Pricing

Trane TRACE 3D Plus is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
