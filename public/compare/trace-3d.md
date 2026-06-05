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
      status: partial
      note: "Title 24 (16 CA zones) + LEED v4 EAp2 + 8760-hr engine shipped; not ASHRAE 90.1 App-G commercial baseline automation"
      evidence: packages/kerf-cad-core/src/kerf_cad_core/buildingenergy/hourly_8760.py

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

Kerf saturates **93%** of Trane TRACE 3D Plus's feature surface (6 yes, 1 partial, 0 no out of 7 features tracked here). Honest gaps: 1 feature partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Trane TRACE 3D Plus | Notes |
|---------|------|---------------------|-------|
| Cooling / heating load calculation (RTS / HAP-comparable) | ✅ | Yes | ASHRAE CLTD/RTS steady-state; 8760-hour engine not yet implemented |
| AHRI-listed equipment catalogue | ✅ | Yes | 30 representative AHRI-listed models (6 categories, 5 per); real AHRI cert numbers + certified part-load curves from ... |
| Part-load efficiency curves (AHRI-certified) | ✅ | Yes | AHRI-certified part-load values at 25/50/75/100% load — same source (ahridirectory.org) |
| Duct and hydronic pipe sizing | ✅ | Yes | Velocity + equal-friction duct sizing; Darcy-Weisbach + SMACNA minor losses |
| ASHRAE 90.1 / Title 24 compliance baseline modelling | ⚠️ (partial) | Yes | Title 24 (16 CA zones) + LEED v4 EAp2 + 8760-hr engine shipped; not ASHRAE 90.1 App-G commercial baseline automation |
| Revit / IFC geometry import | ✅ | Yes | Native IFC Tier 1+2 import; no gbXML reader yet |
| Open-source / scripting API | ✅ | No | MIT-licensed Python plugin; JSON-RPC LLM tool surface; hvac.equipment_select |

## What Kerf does that Trane TRACE 3D Plus doesn't

- **Open-source / scripting API** — MIT-licensed Python plugin; JSON-RPC LLM tool surface; hvac.equipment_select

## What's honestly outstanding

- **ASHRAE 90.1 / Title 24 compliance baseline modelling** (Partial): Title 24 (16 CA zones) + LEED v4 EAp2 + 8760-hr engine shipped; not ASHRAE 90.1 App-G commercial baseline automation

## Pricing

Trane TRACE 3D Plus is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
