---
slug: hspice
competitor: Synopsys HSPICE
category: cad-silicon
left: kerf
right: hspice
hero_tagline: "HSPICE is the gold-standard sign-off SPICE — Kerf targets open-PDK workflows without a six-figure EDA budget."
reviewed_at: 2026-05-29
features:
  - domain: D6
    feature: "SPICE — transient simulation"
    competitor:
      status: yes
      note: "HSPICE .TRAN with multi-threading; considered the most accurate SPICE solver for production sign-off"
      source: "https://www.synopsys.com/implementation-and-signoff/ams-simulation/hspice.html"
    kerf:
      status: yes
      note: "Transient via ngspice bridge; suitable for sky130/open-PDK scale netlists"
      evidence: "packages/kerf-silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — PVT corner sweep"
    competitor:
      status: yes
      note: "HSPICE supports .ALTER and .TEMP sweeps for multi-corner analysis; integrated with Synopsys CustomSim for parallel corners"
      source: "https://www.synopsys.com/implementation-and-signoff/ams-simulation/hspice.html"
    kerf:
      status: yes
      note: "60-corner automated sweep (5P × 3V × 4T) with Monte-Carlo via silicon_pvt_sweep"
      evidence: "packages/kerf-silicon/analog/pvt.py"

  - domain: D6
    feature: "SPICE — Monte-Carlo mismatch"
    competitor:
      status: yes
      note: "HSPICE Monte-Carlo with .MC directive and foundry-supplied mismatch models; used for production yield sign-off"
      source: "https://www.synopsys.com/implementation-and-signoff/ams-simulation/hspice.html"
    kerf:
      status: yes
      note: "Pelgrom model (A_VT = 4 mV·µm, sky130) Monte-Carlo; not a foundry-certified MC deck"
      evidence: "packages/kerf-silicon/analog/pvt.py"

  - domain: D6
    feature: "SPICE — commercial foundry sign-off accuracy"
    competitor:
      status: yes
      note: "HSPICE is the sign-off simulator for Intel, IBM, and many foundries; PDKs ship in HSPICE format"
      source: "https://www.synopsys.com/implementation-and-signoff/ams-simulation/hspice.html"
    kerf:
      status: no
      note: "Kerf uses ngspice + open PDK models. Commercial foundry sign-off (Intel, IBM) requires HSPICE + licensed PDK — outside the scope of the MIT open-core."

  - domain: D6
    feature: "SPICE — waveform viewer"
    competitor:
      status: yes
      note: "HSPICE ships with CosmosScope waveform viewer; also integrates with Synopsys Custom WaveView"
      source: "https://www.synopsys.com/implementation-and-signoff/ams-simulation/hspice.html"
    kerf:
      status: yes
      note: "WaveformViewer.jsx: multi-trace SVG, zoom/pan, dual cursors (A/B), ΔT measurement"
      evidence: "src/components/silicon/WaveformViewer.jsx"

  - domain: D6
    feature: "SPICE — license cost"
    competitor:
      status: no
      note: "HSPICE is a premium commercial license; list price is in the range of $10k–$50k/year depending on configuration"
      source: "https://www.synopsys.com/implementation-and-signoff/ams-simulation/hspice.html"
    kerf:
      status: yes
      note: "Kerf is MIT open-core; ngspice backend is free; cloud execution priced at cost"
      evidence: "LICENSE"

  - domain: D6
    feature: "SPICE — chat-native / LLM-driven flow"
    competitor:
      status: no
      note: "HSPICE is CLI + Tcl scripted; no LLM interface"
      source: "https://www.synopsys.com/implementation-and-signoff/ams-simulation/hspice.html"
    kerf:
      status: yes
      note: "All silicon SPICE tools reachable via plain-language prompts"
      evidence: "packages/kerf-silicon/"

  - domain: D6
    feature: "SPICE — open PDK / sky130 workflow"
    competitor:
      status: partial
      note: "HSPICE can read sky130 SPICE models but sky130 PDK is designed and tested primarily against ngspice and Xyce"
      source: "https://github.com/google/skywater-pdk"
    kerf:
      status: yes
      note: "PVT sweep models are sky130-calibrated; ngspice bridge accepts sky130 PDK decks natively"
      evidence: "packages/kerf-silicon/analog/pvt.py"
---

# Kerf vs Synopsys HSPICE

HSPICE is the gold-standard sign-off SPICE — Kerf targets open-PDK workflows without a six-figure EDA budget.

*Last reviewed: 2026-05-29*

## Summary

Kerf saturates **88%** of Synopsys HSPICE's feature surface (7 yes, 0 partial, 1 no out of 8 features tracked here). Honest gaps: 1 feature not yet implemented.

## Feature comparison

| Feature | Kerf | Synopsys HSPICE | Notes |
|---------|------|-----------------|-------|
| SPICE — transient simulation | ✅ | Yes | Transient via ngspice bridge; suitable for sky130/open-PDK scale netlists |
| SPICE — PVT corner sweep | ✅ | Yes | 60-corner automated sweep (5P × 3V × 4T) with Monte-Carlo via silicon_pvt_sweep |
| SPICE — Monte-Carlo mismatch | ✅ | Yes | Pelgrom model (A_VT = 4 mV·µm, sky130) Monte-Carlo; not a foundry-certified MC deck |
| SPICE — commercial foundry sign-off accuracy | 🔴 (no) | Yes | Kerf uses ngspice + open PDK models. Commercial foundry sign-off (Intel, IBM) requires HSPICE + licensed PDK — outsid... |
| SPICE — waveform viewer | ✅ | Yes | WaveformViewer.jsx: multi-trace SVG, zoom/pan, dual cursors (A/B), ΔT measurement |
| SPICE — license cost | ✅ | No | Kerf is MIT open-core; ngspice backend is free; cloud execution priced at cost |
| SPICE — chat-native / LLM-driven flow | ✅ | No | All silicon SPICE tools reachable via plain-language prompts |
| SPICE — open PDK / sky130 workflow | ✅ | Partial | PVT sweep models are sky130-calibrated; ngspice bridge accepts sky130 PDK decks natively |

## What Kerf does that Synopsys HSPICE doesn't

- **SPICE — license cost** — Kerf is MIT open-core; ngspice backend is free; cloud execution priced at cost
- **SPICE — chat-native / LLM-driven flow** — All silicon SPICE tools reachable via plain-language prompts

## What's honestly outstanding

- **SPICE — commercial foundry sign-off accuracy** (Not yet implemented): Kerf uses ngspice + open PDK models. Commercial foundry sign-off (Intel, IBM) requires HSPICE + licensed PDK — outside the scope of the MIT open-core.

## Pricing

Synopsys HSPICE is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
