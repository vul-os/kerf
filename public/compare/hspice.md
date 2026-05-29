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

Synopsys HSPICE is one of the two dominant commercial SPICE simulators (alongside Cadence Spectre). It is widely used for sign-off simulation at Intel, IBM, and many US foundries. Its reputation for accuracy — especially for high-speed digital and RF designs — is well-earned over 40 years of development.

Like Cadence Spectre, HSPICE targets production IC teams with commercial foundry access and an EDA budget. Kerf targets a different segment: open PDK flows, academic research, startups, and the broader engineering community that doesn't have access to commercial EDA licenses.

## Where HSPICE is stronger

- **Sign-off accuracy.** HSPICE is the reference simulator for many commercial PDKs. Foundry spice decks are validated against HSPICE, not ngspice. If you are taping out at Intel or IBM, HSPICE accuracy matters.
- **High-frequency / RF models.** HSPICE's RF (HSPICE-RF) module includes shooting-method solvers for periodic steady-state, phase noise, and distortion analysis. Kerf's ngspice bridge does not expose these.
- **Large netlist performance.** HSPICE's multi-threaded solver scales to very large netlists. Kerf is suited for block-level simulations (tens of thousands of transistors), not full-chip transient analysis.

## Where Kerf differs

- **Zero license cost.** HSPICE is one of the most expensive EDA tools. Kerf's entire stack is free and open-source.
- **Sky130 / open PDK workflow.** The sky130 PDK's SPICE decks are validated primarily against ngspice and Xyce. Kerf uses ngspice, the natural fit for open-shuttle tapeouts.
- **Chat-native automation.** Run a full 60-corner PVT sweep with one plain-language command. No Tcl scripting or simulation deck management required.
- **Integrated waveform viewer.** Simulation results open in a first-class viewer inside the project workspace. No CosmosScope license required.

## Honest gaps

- **No RF analysis.** HSPICE-RF's shooting method, PSS, and phase-noise analyses are not available via the ngspice bridge.
- **No commercial foundry sign-off.** If your foundry specifies HSPICE, Kerf cannot substitute.
- **No `.ALTER` scripting passthrough.** HSPICE's `.ALTER` block for multi-corner sweeps in a single netlist run is not exposed.

## Feature matrix

| Feature | Kerf | Synopsys HSPICE |
|---|---|---|
| License | MIT open-core + free ngspice | Proprietary (premium) |
| Solver | ngspice (open-source) | Proprietary (sign-off grade) |
| Transient / AC / DC | Yes | Yes |
| RF / PSS / phase noise | No | Yes (HSPICE-RF) |
| PVT corner sweep | Yes (automated, sky130) | Yes (.ALTER scripted) |
| Monte-Carlo | Yes (engineering model) | Yes (foundry-measured) |
| Commercial foundry sign-off | No | Yes |
| Waveform viewer | Yes (in-app) | Yes (CosmosScope) |
| Chat-native flow | Yes | No |
| Open-source | Yes | No |
| sky130 / open PDK | Yes | Partial |

---
*Last reviewed: 2026-05-29. Synopsys HSPICE information from synopsys.com product pages. Kerf capabilities reflect the current shipped product.*
