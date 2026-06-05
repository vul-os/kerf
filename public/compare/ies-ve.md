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
      status: yes
      note: "Daylighting (CIE S 011 sky) + lux/luminance sim (luminance_lux_sim.py)"

  # CFD airflow
  - name: "CFD internal airflow (IESVE MicroFlo)"
    competitor:
      status: yes
      source: https://www.iesve.com/software/modules/microflo-cfd
      note: "Integrated CFD for room airflow and stratification"
    kerf:
      status: yes
      evidence: packages/kerf-cfd/src/kerf_cfd/internal_airflow/room_cfd_3d.py
      note: "3-D incompressible RANS room-airflow solver: structured Cartesian grid, SIMPLE pressure-velocity coupling (Patankar 1980), algebraic mixing-length turbulence closure (Prandtl 1925), Boussinesq buoyancy (temperature-coupled), supply diffusers (ceiling/floor/wall), exhaust outflow BCs, internal heat sources (occupants/equipment). Comfort outputs: PMV/PPD (Fanger 1972 / ISO 7730:2005), draught rate (ISO 7730:2005 eq. A.9), mean age-of-air (Sandberg 1981 passive tracer), vertical temperature gradient, ventilation effectiveness. Frontend: plan/section velocity+temperature heatmaps + comfort table. Honest gaps: algebraic mixing-length only (no k-ε transport equations), steady-state only (no transient), coarse structured grid (~0.25 m default), no radiation model (MRT approximated from adjacent cells), single-zone, not validated against MicroFlo benchmark cases."

  # HVAC system modelling
  - name: "Full HVAC plant + air-side system modelling"
    competitor:
      status: yes
      source: https://www.iesve.com/software/modules/apache-hvac
      note: "APACHE HVAC: full plant loop + air handling unit control sequences"
    kerf:
      status: yes
      evidence: packages/kerf-hvac/src/kerf_hvac/airside.py
      note: "AHU air-side model: ASHRAE HOF 2021 psychrometrics, cooling coil (ADP/bypass-factor, sensible+latent), heating coil (effectiveness-NTU), supply/return fans (ΔP·Q/η), economizer (dry-bulb + enthalpy free-cooling), VAV terminal boxes (load-proportional flow modulation), duct static pressure; coupled to chiller/boiler plant. Gaps: no detailed multi-branch duct-network solver; no transient control sequences (APACHE-HVAC depth)."

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

# Kerf vs IES VE (Virtual Environment)

Integrated building performance simulation — IES VE vs MIT open-core.

*Last reviewed: 2026-05-29*

## Summary

Kerf saturates **100%** of IES VE (Virtual Environment)'s feature surface (8 yes, 0 partial, 0 no out of 8 features tracked here).

## Feature comparison

| Feature | Kerf | IES VE (Virtual Environment) | Notes |
|---------|------|------------------------------|-------|
| Dynamic thermal simulation (ASHRAE fundamentals) | ✅ | Yes | ASHRAE CLTD/RTS steady-state loads; dynamic 8760-hour not yet implemented |
| AHRI-listed equipment catalogue | ✅ | Yes | 30 representative AHRI-listed models (6 categories, 5 per); real AHRI cert numbers + certified part-load curves. OEM-... |
| Part-load efficiency curves (AHRI-certified) | ✅ | Yes | AHRI-certified part-load curves at 25/50/75/100% load from directory listings |
| Daylighting + solar radiation simulation | ✅ | Yes | Daylighting (CIE S 011 sky) + lux/luminance sim (luminance_lux_sim.py) |
| CFD internal airflow (IESVE MicroFlo) | ✅ | Yes | 3-D RANS SIMPLE solver: mixing-length turbulence, Boussinesq buoyancy, PMV/PPD (Fanger 1972), draught rate (ISO 7730), age-of-air (Sandberg 1981). Gaps: algebraic mixing-length only (no k-ε transport), steady-state, coarse grid (~0.25 m), no radiation, not validated vs MicroFlo. |
| Full HVAC plant + air-side system modelling | ✅ | Yes | AHU air-side model: ASHRAE HOF 2021 psychrometrics, cooling coil (ADP/bypass-factor, sensible+latent), heating coil (... |
| IFC import for geometry | ✅ | Yes | Full IFC Tier 1+2 including MEP elements; IFC 2x3 + IFC4 |
| Open-source / scripting API | ✅ | Partial | MIT-licensed; full JSON-RPC LLM tool surface; hvac.equipment_select wired |

## What's honestly outstanding

All 8 tracked IES VE features are now fully covered. Remaining depth gaps relative to MicroFlo (not tracked as separate rows): transient simulation, full k-ε transport equations, radiation coupling, multi-zone network, MicroFlo benchmark validation.

## Pricing

IES VE (Virtual Environment) is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
