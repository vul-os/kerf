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
      status: no
      note: "Hourly energy simulation not yet implemented; steady-state load calc only"

  # LEED / energy code compliance
  - name: "ASHRAE 90.1 / LEED energy compliance reporting"
    competitor:
      status: yes
      source: https://www.carrier.com/commercial/en/us/software/hvac-system-design/hourly-analysis-program/
      note: "LEED EAp2 / EAc1 reports built-in"
    kerf:
      status: no
      note: "No ASHRAE 90.1 compliance reporting yet"

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

Kerf saturates **75%** of Carrier HAP (Hourly Analysis Program)'s feature surface (6 yes, 0 partial, 2 no out of 8 features tracked here). Honest gaps: 2 features not yet implemented.

## Feature comparison

| Feature | Kerf | Carrier HAP (Hourly Analysis Program) | Notes |
|---------|------|---------------------------------------|-------|
| Cooling / heating load calculation (ASHRAE CLTD/RTS) | ✅ | Yes | ASHRAE CLTD/RTS transient cooling loads shipped |
| AHRI-listed equipment catalogue | ✅ | Yes | 30 representative AHRI-listed models (6 categories, 5 per); real AHRI numbers + certified part-load curves. OEM-compl... |
| SMACNA duct sizing (velocity / equal-friction methods) | ✅ | Yes | ASHRAE velocity method + Darcy-Weisbach + SMACNA minor-loss coefficients |
| Part-load efficiency curves (AHRI-certified) | ✅ | Yes | AHRI-certified part-load curves at 25/50/75/100% load — not normalised illustrative values |
| Annual hourly energy simulation (8760-hour) | 🔴 (no) | Yes | Hourly energy simulation not yet implemented; steady-state load calc only |
| ASHRAE 90.1 / LEED energy compliance reporting | 🔴 (no) | Yes | No ASHRAE 90.1 compliance reporting yet |
| IFC / BIM geometry import | ✅ | No | Full IFC Tier 1+2 import including MEP elements |
| Open-source core / scripting API | ✅ | No | MIT-licensed Python plugin; full JSON-RPC LLM tool surface including hvac.equipment_select |

## What Kerf does that Carrier HAP (Hourly Analysis Program) doesn't

- **IFC / BIM geometry import** — Full IFC Tier 1+2 import including MEP elements
- **Open-source core / scripting API** — MIT-licensed Python plugin; full JSON-RPC LLM tool surface including hvac.equipment_select

## What's honestly outstanding

- **Annual hourly energy simulation (8760-hour)** (Not yet implemented): Hourly energy simulation not yet implemented; steady-state load calc only
- **ASHRAE 90.1 / LEED energy compliance reporting** (Not yet implemented): No ASHRAE 90.1 compliance reporting yet

## Pricing

Carrier HAP (Hourly Analysis Program) is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
