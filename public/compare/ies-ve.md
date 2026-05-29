---
slug: ies-ve
competitor: "IES VE (Virtual Environment)"
category: hvac-energy
left: kerf
right: ies-ve
hero_tagline: "Integrated building performance simulation — IES VE vs MIT open-core."
reviewed_at: 2026-05-29
order: 2
features:

  # Thermal load calculation
  - name: "Dynamic thermal simulation (ASHRAE fundamentals)"
    competitor:
      status: yes
      source: https://www.iesve.com/software/virtual-environment
      note: "APACHE / APACHESIM dynamic simulation; ASHRAE HB methods; CIBSE TM54"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/sizing.py
      note: "ASHRAE CLTD/RTS steady-state loads; dynamic 8760-hour not yet implemented"

  # AHRI equipment catalogue
  - name: "AHRI-listed equipment catalogue"
    competitor:
      status: yes
      source: https://www.iesve.com/software/virtual-environment
      note: "MacroFlo / HVAC systems library with manufacturer-supplied performance data"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/ahri_catalogue.py
      note: "30 representative AHRI-listed models (6 categories, 5 per); real AHRI cert numbers + certified part-load curves. OEM-complete follow-on TBD."

  # Part-load performance
  - name: "Part-load efficiency curves (AHRI-certified)"
    competitor:
      status: yes
      source: https://www.iesve.com/software/virtual-environment
      note: "Manufacturer-supplied COP/EER curves with hourly interpolation"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/ahri_catalogue.py
      note: "AHRI-certified part-load curves at 25/50/75/100% load from directory listings"

  # Daylighting + solar
  - name: "Daylighting + solar radiation simulation"
    competitor:
      status: yes
      source: https://www.iesve.com/software/virtual-environment
      note: "Radiance integration; climate-based daylight; LEED v4 IEQ; BREEAM"
    kerf:
      status: no
      note: "No daylighting simulation yet"

  # CFD airflow
  - name: "CFD internal airflow (IESVE MicroFlo)"
    competitor:
      status: yes
      source: https://www.iesve.com/software/modules/microflo-cfd
      note: "Integrated CFD for room airflow and stratification"
    kerf:
      status: partial
      evidence: packages/kerf-fem/src/kerf_fem/cfd_navier_stokes.py
      note: "2-D projection Navier-Stokes shipped; full 3-D room CFD not yet wired"

  # HVAC system modelling
  - name: "Full HVAC plant + air-side system modelling"
    competitor:
      status: yes
      source: https://www.iesve.com/software/modules/apache-hvac
      note: "APACHE HVAC: full plant loop + air handling unit control sequences"
    kerf:
      status: no
      note: "Equipment selection + duct sizing only; no full plant loop simulation"

  # IFC / BIM
  - name: "IFC import for geometry"
    competitor:
      status: yes
      source: https://www.iesve.com/software/virtual-environment
      note: "IFC 2x3 and IFC4 import for building geometry"
    kerf:
      status: yes
      evidence: packages/kerf-bim/src/kerf_bim/ifc_import.py
      note: "Full IFC Tier 1+2 including MEP elements; IFC 2x3 + IFC4"

  # Open API
  - name: "Open-source / scripting API"
    competitor:
      status: partial
      note: "VE-API (proprietary COM/Python bindings for automation; not open-source)"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/tools.py
      note: "MIT-licensed; full JSON-RPC LLM tool surface; hvac.equipment_select wired"

---

## Summary

IES VE is a comprehensive integrated building performance simulation platform covering
thermal loads, daylighting, CFD, and full HVAC plant modelling.  It is widely used for
LEED, BREEAM, and Part L compliance submissions.

Kerf now ships an AHRI-listed equipment catalogue (30 models across 6 categories) with
real AHRI certification numbers and certified part-load efficiency curves, closing the
previous gap where only ASHRAE 90.1 minimum-efficiency values were used.  The primary
remaining gaps versus IES VE are hourly dynamic simulation, daylighting, and full
HVAC plant loop modelling.

### Where IES VE leads

- **Dynamic simulation.** APACHE engine; 8760-hour building physics; CIBSE TM54 operational energy.
- **Daylighting + solar.** Radiance-based climate daylight; LEED IEQ; BREEAM compliance.
- **CFD integration.** MicroFlo room airflow with boundary conditions from the thermal model.
- **Full HVAC plant.** APACHE HVAC models AHU control sequences, chiller plants, and thermal stores.

### Where Kerf leads

- **Open-source MIT core.** No per-seat license; CI-testable; LLM-native tool surface.
- **AHRI-certified equipment.** Real directory data, not normalised curves.
- **BIM + multi-domain.** Same tool handles structural FEA, PCB, HVAC, and civil in one project.
- **Scripting SDK.** Python kerf-sdk + `/v1/rpc` for programmatic parametric studies.
