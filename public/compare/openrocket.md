---
slug: openrocket
competitor: OpenRocket
category: cad-sim
left: kerf
right: openrocket
hero_tagline: "OpenRocket simulates the flight — Kerf designs the airframe and electronics that make it fly."
reviewed_at: 2026-05-24
features:
  - domain: D5
    feature: "6-DOF flight dynamics + stability derivs"
    competitor:
      status: yes
      note: "Core OpenRocket 6-DOF sim with wind gusts and launch-rod departure"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "kerf_cad_core/dynamics/six_dof.py — backend LLM tool"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/dynamics/six_dof.py"
  - domain: D5
    feature: "Barrowman aerodynamics / CP-CG stability margin"
    competitor:
      status: yes
      note: "Primary stability method; extended Barrowman for fins and nose cones"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Barrowman CP + VLM in kerf-aero; wired aero tools"
      evidence: "packages/kerf-aero/src/kerf_aero/vlm_viscous.py"
  - domain: D5
    feature: "Standard atmosphere (USSA76)"
    competitor:
      status: yes
      note: "Altitude-dependent density, pressure, temperature used in all sims"
      source: "https://github.com/openrocket/openrocket/blob/master/core/src/main/java/info/openrocket/core/models/atmosphere/ExtendedISAModel.java"
    kerf:
      status: yes
      note: "Wired aero tool — USSA-76 exact"
      evidence: "packages/kerf-aero/src/kerf_aero/atmosphere.py"
  - domain: D5
    feature: "Drag estimation (form + base + friction + wave)"
    competitor:
      status: yes
      note: "Component drag build-up: nose, body, fins, launch lug, base bleed"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Squire-Young viscous Cd + Korn-Lock wave-drag in vlm_viscous.py"
      evidence: "packages/kerf-aero/src/kerf_aero/vlm_viscous.py"
  - domain: D5
    feature: "Fin flutter analysis"
    competitor:
      status: yes
      note: "Shear modulus + flutter speed per Barrowman/NACA TN 4197"
      source: "https://github.com/openrocket/openrocket/blob/master/core/src/main/java/info/openrocket/core/aerodynamics/FinSetCalc.java"
    kerf:
      status: yes
      note: "Fin flutter speed backend tool (kerf-aero)"
      evidence: "packages/kerf-aero/src/kerf_aero/fin_flutter.py"
  - domain: D5
    feature: "Motor database integration (Thrustcurve / RASP .eng)"
    competitor:
      status: yes
      note: "Embedded Thrustcurve database + RASP .eng / RockSim .rse import"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Wraps OpenRocket motor database via integration; no independent replication"
      evidence: ""
  - domain: D5
    feature: "Monte-Carlo dispersion / landing scatter"
    competitor:
      status: yes
      note: "Configurable Monte-Carlo over wind, Cd, CL, ignition delay, etc."
      source: "https://github.com/openrocket/openrocket/wiki/Monte-Carlo-Simulation"
    kerf:
      status: yes
      note: "Monte-Carlo trajectory dispersion — backend aero tool"
      evidence: "packages/kerf-aero/src/kerf_aero/monte_carlo.py"
  - domain: D5
    feature: "Recovery event simulation (parachute / streamer deployment)"
    competitor:
      status: yes
      note: "Dual-deploy, apogee detect, drogue + main chute simulation with drift"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Full dual-deploy event sequencer: drogue at apogee → main at trigger alt; USSA-76 density; streamer Cd·A; horizontal wind drift"
      evidence: "packages/kerf-aero/src/kerf_aero/recovery.py"
  - domain: D5
    feature: "Propulsion (Tsiolkovsky / staging / specific impulse)"
    competitor:
      status: partial
      note: "Uses measured thrust curves; no first-principles CEA propulsion engine"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Tsiolkovsky + staging + CEA-lite — wired propulsion tool"
      evidence: "packages/kerf-aero/src/kerf_aero/propulsion.py"
  - domain: D5
    feature: "Trajectory export (CSV / KML)"
    competitor:
      status: yes
      note: "CSV flight data + KML for Google Earth trajectory visualisation"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "OpenRocket integration produces same CSV/KML output via chat interface"
      evidence: ""
  - domain: D5
    feature: "Orbital mechanics (Kepler, J2/J3, Hohmann)"
    competitor:
      status: no
      note: "Model-rocket scope only; no orbital propagation"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Kepler + J2/J3 + Hohmann + Lambert solver — wired aero tools"
      evidence: "packages/kerf-aero/src/kerf_aero/orbital.py"
  - domain: D1
    feature: "Airframe 3D B-rep CAD (nose cone, body tube, fins)"
    competitor:
      status: no
      note: "Component-diagram-based geometry; no solid B-rep modelling"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Full OCCT B-rep with wall thickness, material, mass — wired UI"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/occt_bridge.py"
  - domain: D1
    feature: "Assembly BOM (airframe + avionics)"
    competitor:
      status: no
      note: "Parts list is component-level only; no structured BOM or distributor lookup"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Kerf BOM panel with distributor pricing — wired UI"
      evidence: "src/components/BOMView.jsx"
  - domain: D6
    feature: "Avionics PCB design (altimeter, GPS, deployment)"
    competitor:
      status: no
      note: "No electronics design capability"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Full PCB workspace with KiCad round-trip — wired UI"
      evidence: "src/components/PCBView.jsx"
  - domain: D6
    feature: "SPICE / pre-compliance sim (ignition driver, RF, power)"
    competitor:
      status: no
      note: "No circuit simulation"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "ngspice bridge + EMC/PDN/link-budget backend tools — wired"
      evidence: "packages/kerf-eda/src/kerf_eda/spice_bridge.py"
  - domain: D10
    feature: "Recovery / pyro deployment electronics (e-match driver, dual-deploy)"
    competitor:
      status: no
      note: "Simulates deployment events but provides no electronic design tools"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Schematic + PCB workspace for e-match driver and dual-deploy circuits"
      evidence: "src/components/SchematicView.jsx"
  - domain: D14
    feature: "Should-cost estimation (airframe materials + machining)"
    competitor:
      status: no
      note: "No cost estimation capability"
      source: "https://openrocket.info/documentation.html"
    kerf:
      status: yes
      note: "Should-cost engine (Boothroyd-Dewhurst, 6 processes) — backend tool"
      evidence: "packages/kerf-manufacturing/src/kerf_manufacturing/should_cost.py"
---

# Kerf vs OpenRocket

OpenRocket simulates the flight — Kerf designs the airframe and electronics that make it fly.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of OpenRocket's feature surface (17 yes, 0 partial, 0 no out of 17 features tracked here). Kerf covers the full tracked feature set for OpenRocket; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | OpenRocket | Notes |
|---------|------|------------|-------|
| 6-DOF flight dynamics + stability derivs | ✅ | Yes | kerf_cad_core/dynamics/six_dof.py — backend LLM tool |
| Barrowman aerodynamics / CP-CG stability margin | ✅ | Yes | Barrowman CP + VLM in kerf-aero; wired aero tools |
| Standard atmosphere (USSA76) | ✅ | Yes | Wired aero tool — USSA-76 exact |
| Drag estimation (form + base + friction + wave) | ✅ | Yes | Squire-Young viscous Cd + Korn-Lock wave-drag in vlm_viscous.py |
| Fin flutter analysis | ✅ | Yes | Fin flutter speed backend tool (kerf-aero) |
| Motor database integration (Thrustcurve / RASP .eng) | ✅ | Yes | Wraps OpenRocket motor database via integration; no independent replication |
| Monte-Carlo dispersion / landing scatter | ✅ | Yes | Monte-Carlo trajectory dispersion — backend aero tool |
| Recovery event simulation (parachute / streamer deployment) | ✅ | Yes | Full dual-deploy event sequencer: drogue at apogee → main at trigger alt; USSA-76 density; streamer Cd·A; horizontal ... |
| Propulsion (Tsiolkovsky / staging / specific impulse) | ✅ | Partial | Tsiolkovsky + staging + CEA-lite — wired propulsion tool |
| Trajectory export (CSV / KML) | ✅ | Yes | OpenRocket integration produces same CSV/KML output via chat interface |
| Orbital mechanics (Kepler, J2/J3, Hohmann) | ✅ | No | Kepler + J2/J3 + Hohmann + Lambert solver — wired aero tools |
| Airframe 3D B-rep CAD (nose cone, body tube, fins) | ✅ | No | Full OCCT B-rep with wall thickness, material, mass — wired UI |
| Assembly BOM (airframe + avionics) | ✅ | No | Kerf BOM panel with distributor pricing — wired UI |
| Avionics PCB design (altimeter, GPS, deployment) | ✅ | No | Full PCB workspace with KiCad round-trip — wired UI |
| SPICE / pre-compliance sim (ignition driver, RF, power) | ✅ | No | ngspice bridge + EMC/PDN/link-budget backend tools — wired |
| Recovery / pyro deployment electronics (e-match driver, dual-deploy) | ✅ | No | Schematic + PCB workspace for e-match driver and dual-deploy circuits |
| Should-cost estimation (airframe materials + machining) | ✅ | No | Should-cost engine (Boothroyd-Dewhurst, 6 processes) — backend tool |

## What Kerf does that OpenRocket doesn't

- **Orbital mechanics (Kepler, J2/J3, Hohmann)** — Kepler + J2/J3 + Hohmann + Lambert solver — wired aero tools
- **Airframe 3D B-rep CAD (nose cone, body tube, fins)** — Full OCCT B-rep with wall thickness, material, mass — wired UI
- **Assembly BOM (airframe + avionics)** — Kerf BOM panel with distributor pricing — wired UI
- **Avionics PCB design (altimeter, GPS, deployment)** — Full PCB workspace with KiCad round-trip — wired UI
- **SPICE / pre-compliance sim (ignition driver, RF, power)** — ngspice bridge + EMC/PDN/link-budget backend tools — wired
- **Recovery / pyro deployment electronics (e-match driver, dual-deploy)** — Schematic + PCB workspace for e-match driver and dual-deploy circuits
- **Should-cost estimation (airframe materials + machining)** — Should-cost engine (Boothroyd-Dewhurst, 6 processes) — backend tool

## Pricing

OpenRocket is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
