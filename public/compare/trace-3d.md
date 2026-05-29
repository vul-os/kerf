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
      status: no
      note: "No ASHRAE 90.1 compliance reporting yet"

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

## Summary

Trane TRACE 3D Plus is a full-featured commercial building energy simulation tool
closely tied to the Trane equipment line but supporting third-party AHRI certified
equipment.  It is widely used for ASHRAE 90.1 Appendix G baseline modelling and
LEED energy compliance submissions.

Kerf now ships a curated AHRI-listed equipment catalogue with real AHRI certification
numbers and certified part-load curves (`hvac.equipment_select` LLM tool), matching
the key data source used by TRACE's equipment library.  Primary gaps remain in
8760-hour simulation and ASHRAE 90.1 compliance automation.

### Where TRACE 3D Plus leads

- **Hourly energy simulation.** 8760-hour DOE-2.2 engine; utility bills; demand charges.
- **ASHRAE 90.1 compliance.** Appendix G baseline automation; LEED EAp2/EAc1; Title 24.
- **Trane equipment integration.** Deep manufacturer data for Trane chillers, RTUs, and AHUs.
- **System selection.** Automated system type comparison across multiple HVAC configurations.

### Where Kerf leads

- **AHRI-certified equipment catalogue.** Real directory data wired to the LLM (`hvac.equipment_select`); multi-manufacturer across 6 categories.
- **Open-source MIT core.** No Windows-only license; version-controlled; CI-testable.
- **Multi-domain.** HVAC in the same project as structural, electrical, and BIM — no file exports.
- **LLM-native.** Every HVAC tool callable via chat or Python SDK without a GUI.
