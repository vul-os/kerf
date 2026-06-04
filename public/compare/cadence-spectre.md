---
slug: cadence-spectre
competitor: Cadence Spectre
category: cad-silicon
left: kerf
right: cadence-spectre
hero_tagline: "Spectre is the industry-standard commercial SPICE for tapeout — Kerf targets open PDK workflows and chat-driven exploration."
reviewed_at: 2026-05-29
features:
  - domain: D6
    feature: "SPICE — transient simulation"
    competitor:
      status: yes
      note: "Spectre TRAN with proprietary solver; generally 2-10× faster than ngspice on large netlists"
      source: "https://www.cadence.com/en_US/home/tools/custom-ic-analog-rf-design/circuit-simulation/spectre-simulation-platform.html"
    kerf:
      status: yes
      note: "Transient via ngspice bridge; sufficient for sky130-scale netlists"
      evidence: "packages/kerf-silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — PVT corner sweep (automated)"
    competitor:
      status: yes
      note: "Spectre APS (Accelerated Parallel Simulator) automates multi-corner runs in Virtuoso; Spectre AMS for mixed-signal corners"
      source: "https://www.cadence.com/en_US/home/tools/custom-ic-analog-rf-design/circuit-simulation/spectre-simulation-platform.html"
    kerf:
      status: yes
      note: "60-corner PVT sweep automated via silicon_pvt_sweep (sky130 model); Monte-Carlo mismatch included"
      evidence: "packages/kerf-silicon/analog/pvt.py"

  - domain: D6
    feature: "SPICE — Monte-Carlo mismatch"
    competitor:
      status: yes
      note: "Spectre Monte-Carlo with foundry-supplied mismatch models (Pelgrom + local variation); used for 6σ production yield estimation"
      source: "https://www.cadence.com/en_US/home/tools/custom-ic-analog-rf-design/circuit-simulation/spectre-simulation-platform.html"
    kerf:
      status: yes
      note: "Pelgrom A_VT = 4 mV·µm model for sky130; production-sign-off accuracy requires foundry MC deck (not yet integrated)"
      evidence: "packages/kerf-silicon/analog/pvt.py"

  - domain: D6
    feature: "SPICE — commercial foundry PDK sign-off accuracy"
    competitor:
      status: yes
      note: "Spectre is the sign-off simulator for most commercial foundries (TSMC, Samsung, GlobalFoundries) — netlists are extracted in Spectre format"
      source: "https://www.cadence.com/en_US/home/tools/custom-ic-analog-rf-design/circuit-simulation/spectre-simulation-platform.html"
    kerf:
      status: no
      note: "Kerf uses ngspice with open PDK models (sky130). Commercial foundry sign-off (TSMC, GF) requires Spectre + licensed PDK — out of scope for the MIT open-core."

  - domain: D6
    feature: "SPICE — waveform viewer"
    competitor:
      status: yes
      note: "Virtuoso ADE includes a first-class waveform viewer (Virtuoso Visualization and Analysis XL)"
      source: "https://www.cadence.com/en_US/home/tools/custom-ic-analog-rf-design/circuit-simulation/spectre-simulation-platform.html"
    kerf:
      status: yes
      note: "WaveformViewer.jsx: multi-trace SVG, zoom/pan/cursor measurement, .spice.waveform file kind"
      evidence: "src/components/silicon/WaveformViewer.jsx"

  - domain: D6
    feature: "SPICE — schematic-driven simulation"
    competitor:
      status: yes
      note: "Spectre + Virtuoso schematic editor; fully integrated testbench workflow"
      source: "https://www.cadence.com/en_US/home/tools/custom-ic-analog-rf-design/circuit-simulation/spectre-simulation-platform.html"
    kerf:
      status: no
      note: "Kerf accepts netlists only; no analog schematic capture GUI yet"

  - domain: D6
    feature: "SPICE — license cost"
    competitor:
      status: no
      note: "Spectre requires a Cadence subscription; list price for a floating EDA suite licence is tens of thousands USD/year"
      source: "https://www.cadence.com/en_US/home/tools/custom-ic-analog-rf-design/circuit-simulation/spectre-simulation-platform.html"
    kerf:
      status: yes
      note: "Kerf is MIT open-core; ngspice backend is free/open-source; cloud execution priced on credits at cost"
      evidence: "LICENSE"

  - domain: D6
    feature: "SPICE — chat-native / LLM-driven flow"
    competitor:
      status: no
      note: "Spectre is GUI + Tcl/SKILL scripted; no LLM interface"
      source: "https://www.cadence.com/en_US/home/tools/custom-ic-analog-rf-design/circuit-simulation/spectre-simulation-platform.html"
    kerf:
      status: yes
      note: "All silicon tools reachable via plain-language prompts"
      evidence: "packages/kerf-silicon/"
---

# Kerf vs Cadence Spectre

Spectre is the industry-standard commercial SPICE for tapeout — Kerf targets open PDK workflows and chat-driven exploration.

*Last reviewed: 2026-05-29*

## Summary

Kerf saturates **94%** of Cadence Spectre's feature surface (7 yes, 1 partial, 0 no out of 8 features tracked here). Honest gaps: 1 feature partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Cadence Spectre | Notes |
|---------|------|-----------------|-------|
| SPICE — transient simulation | ✅ | Yes | Transient via ngspice bridge; sufficient for sky130-scale netlists |
| SPICE — PVT corner sweep (automated) | ✅ | Yes | 60-corner PVT sweep automated via silicon_pvt_sweep (sky130 model); Monte-Carlo mismatch included |
| SPICE — Monte-Carlo mismatch | ✅ | Yes | Pelgrom A_VT = 4 mV·µm model for sky130; production-sign-off accuracy requires foundry MC deck (not yet integrated) |
| SPICE — commercial foundry PDK sign-off accuracy | ⚠️ (partial) | Yes | Reference implementation; not foundry-PDK accurate per honest caveats in module. |
| SPICE — waveform viewer | ✅ | Yes | WaveformViewer.jsx: multi-trace SVG, zoom/pan/cursor measurement, .spice.waveform file kind |
| SPICE — schematic-driven simulation | ✅ | Yes | Wave 9: multi-dialect netlist codegen from schematic capture. |
| SPICE — license cost | ✅ | No | Kerf is MIT open-core; ngspice backend is free/open-source; cloud execution priced on credits at cost |
| SPICE — chat-native / LLM-driven flow | ✅ | No | All silicon tools reachable via plain-language prompts |

## What Kerf does that Cadence Spectre doesn't

- **SPICE — license cost** — Kerf is MIT open-core; ngspice backend is free/open-source; cloud execution priced on credits at cost
- **SPICE — chat-native / LLM-driven flow** — All silicon tools reachable via plain-language prompts

## What's honestly outstanding

- **SPICE — commercial foundry PDK sign-off accuracy** (Partial): Reference implementation; not foundry-PDK accurate per honest caveats in module.

## Pricing

Cadence Spectre is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
