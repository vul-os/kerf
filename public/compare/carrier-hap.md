---
slug: carrier-hap
competitor: "Carrier HAP (Hourly Analysis Program)"
category: hvac-energy
left: kerf
right: carrier-hap
hero_tagline: "Building energy analysis and HVAC system design — Carrier HAP vs MIT open-core."
reviewed_at: 2026-05-29
order: 1
features:

  # HVAC load calculation
  - name: "Cooling / heating load calculation (ASHRAE CLTD/RTS)"
    competitor:
      status: yes
      source: https://www.carrier.com/commercial/en/us/software/hvac-system-design/hourly-analysis-program/
      note: "Full RTS room-by-room load with ASHRAE HOF 2017 method"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/sizing.py
      note: "ASHRAE CLTD/RTS transient cooling loads shipped"

  # AHRI equipment catalogue
  - name: "AHRI-listed equipment catalogue"
    competitor:
      status: yes
      source: https://www.carrier.com/commercial/en/us/software/hvac-system-design/hourly-analysis-program/
      note: "Integrated AHRI certified product directory with live lookup"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/ahri_catalogue.py
      note: "30 representative AHRI-listed models (6 categories, 5 per); real AHRI numbers + certified part-load curves. OEM-complete follow-on TBD."

  # Duct sizing
  - name: "SMACNA duct sizing (velocity / equal-friction methods)"
    competitor:
      status: yes
      source: https://www.carrier.com/commercial/en/us/software/hvac-system-design/hourly-analysis-program/
      note: "Full duct system design in HAP"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/sizing.py
      note: "ASHRAE velocity method + Darcy-Weisbach + SMACNA minor-loss coefficients"

  # Part-load performance
  - name: "Part-load efficiency curves (AHRI-certified)"
    competitor:
      status: yes
      source: https://www.carrier.com/commercial/en/us/software/hvac-system-design/hourly-analysis-program/
      note: "AHRI certified performance data for HAP equipment library"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/ahri_catalogue.py
      note: "AHRI-certified part-load curves at 25/50/75/100% load — not normalised illustrative values"

  # Energy simulation
  - name: "Annual hourly energy simulation (8760-hour)"
    competitor:
      status: yes
      source: https://www.carrier.com/commercial/en/us/software/hvac-system-design/hourly-analysis-program/
      note: "Full 8760-hour weather-file simulation; DOE-2 based engine"
    kerf:
      status: partial
      note: "8760-hr ASHRAE hourly engine shipped + gbXML/IDF export; not Carrier-HAP DOE-2 commercial-validated"
      evidence: packages/kerf-cad-core/src/kerf_cad_core/buildingenergy/hourly_8760.py

  # LEED / energy code compliance
  - name: "ASHRAE 90.1 / LEED energy compliance reporting"
    competitor:
      status: yes
      source: https://www.carrier.com/commercial/en/us/software/hvac-system-design/hourly-analysis-program/
      note: "LEED EAp2 / EAc1 reports built-in"
    kerf:
      status: partial
      note: "Title 24 (16 CA zones) + LEED v4 EAp2 engine shipped; not commercial-certified compliance reporting"
      evidence: packages/kerf-cad-core/src/kerf_cad_core/buildingenergy/hourly_8760.py

  # IFC / BIM integration
  - name: "IFC / BIM geometry import"
    competitor:
      status: no
      note: "HAP is standalone; no native IFC import"
    kerf:
      status: yes
      evidence: packages/kerf-bim/src/kerf_bim/ifc_import.py
      note: "Full IFC Tier 1+2 import including MEP elements"

  # Open-source / API
  - name: "Open-source core / scripting API"
    competitor:
      status: no
      note: "Proprietary Windows desktop app; no public API"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/tools.py
      note: "MIT-licensed Python plugin; full JSON-RPC LLM tool surface including hvac.equipment_select"

---

# Kerf vs Carrier HAP (Hourly Analysis Program)

Building energy analysis and HVAC system design — Carrier HAP vs MIT open-core.

*Last reviewed: 2026-05-29*

## Summary

Kerf saturates **88%** of Carrier HAP (Hourly Analysis Program)'s feature surface (6 yes, 2 partial, 0 no out of 8 features tracked here). Honest gaps: 2 features partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Carrier HAP (Hourly Analysis Program) | Notes |
|---------|------|---------------------------------------|-------|
| Cooling / heating load calculation (ASHRAE CLTD/RTS) | ✅ | Yes | ASHRAE CLTD/RTS transient cooling loads shipped |
| AHRI-listed equipment catalogue | ✅ | Yes | 30 representative AHRI-listed models (6 categories, 5 per); real AHRI numbers + certified part-load curves. OEM-compl... |
| SMACNA duct sizing (velocity / equal-friction methods) | ✅ | Yes | ASHRAE velocity method + Darcy-Weisbach + SMACNA minor-loss coefficients |
| Part-load efficiency curves (AHRI-certified) | ✅ | Yes | AHRI-certified part-load curves at 25/50/75/100% load — not normalised illustrative values |
| Annual hourly energy simulation (8760-hour) | ⚠️ (partial) | Yes | 8760-hr ASHRAE hourly engine shipped + gbXML/IDF export; not Carrier-HAP DOE-2 commercial-validated |
| ASHRAE 90.1 / LEED energy compliance reporting | ⚠️ (partial) | Yes | Title 24 (16 CA zones) + LEED v4 EAp2 engine shipped; not commercial-certified compliance reporting |
| IFC / BIM geometry import | ✅ | No | Full IFC Tier 1+2 import including MEP elements |
| Open-source core / scripting API | ✅ | No | MIT-licensed Python plugin; full JSON-RPC LLM tool surface including hvac.equipment_select |

## What Kerf does that Carrier HAP (Hourly Analysis Program) doesn't

- **IFC / BIM geometry import** — Full IFC Tier 1+2 import including MEP elements
- **Open-source core / scripting API** — MIT-licensed Python plugin; full JSON-RPC LLM tool surface including hvac.equipment_select

## What's honestly outstanding

- **Annual hourly energy simulation (8760-hour)** (Partial): 8760-hr ASHRAE hourly engine shipped + gbXML/IDF export; not Carrier-HAP DOE-2 commercial-validated
- **ASHRAE 90.1 / LEED energy compliance reporting** (Partial): Title 24 (16 CA zones) + LEED v4 EAp2 engine shipped; not commercial-certified compliance reporting

## Pricing

Carrier HAP (Hourly Analysis Program) is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
