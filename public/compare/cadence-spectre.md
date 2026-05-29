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

Cadence Spectre is the industry-standard commercial SPICE simulator. It is the sign-off simulator for production tapeout at TSMC, Samsung, GlobalFoundries, and most other commercial foundries. Every serious mixed-signal IC team uses it. It is proprietary and expensive.

Kerf targets a different audience: designers working on open PDK flows (sky130, GF180), students, startups, and research teams who cannot afford or do not need commercial EDA licenses. The comparison below is honest about where Spectre wins decisively.

## Where Spectre is stronger

- **Commercial foundry sign-off.** Spectre is the required simulator for TSMC/GF/Samsung PDK sign-off. Foundry-supplied SPICE decks are in Spectre format. Kerf cannot replace this.
- **Solver performance.** Spectre's proprietary solver is significantly faster than ngspice on large commercial netlists. Kerf is fine for sky130-scale cells; it is not competitive at 100k-transistor blocks.
- **Monte-Carlo accuracy.** Commercial foundries supply Spectre-format MC decks with measured silicon statistics. Kerf's Pelgrom model is an engineering approximation, not silicon-measured data.
- **Virtuoso integration.** Spectre + Virtuoso is a complete environment: schematic capture, layout, DRC/LVS, parasitic extraction, and simulation all flow seamlessly. Kerf has individual capabilities but not this level of integration.

## Where Kerf differs

- **Zero license cost.** The entire Kerf + ngspice stack is free and open-source. The cost difference to Spectre is measured in five figures per year.
- **Open PDK focus.** Kerf is the right tool for sky130 and GF180 open-shuttle designs (Efabless, Tiny Tapeout). Spectre is overkill and inaccessible for these projects.
- **Chat-native workflow.** Describe the simulation in plain language. No Tcl/SKILL scripting knowledge required.
- **PVT automation.** 60-corner automated sweep in one call, with Monte-Carlo statistics per corner. Spectre can do this but requires scripting through Virtuoso ADE or a shell loop.

## Honest gaps

- **No commercial PDK sign-off.** If you need to tape out at TSMC, you need Spectre. Kerf is not a replacement.
- **No Virtuoso-grade schematic integration.** Kerf accepts netlists; Spectre is point-and-click schematic-driven.

## Feature matrix

| Feature | Kerf | Cadence Spectre |
|---|---|---|
| License | MIT open-core + free ngspice | Proprietary (tens of k$/year) |
| Solver | ngspice (open) | Proprietary (faster) |
| Transient | Yes | Yes |
| AC / DC / Noise | Yes | Yes |
| PVT corner sweep | Yes (automated, sky130) | Yes (Virtuoso ADE) |
| Monte-Carlo | Yes (engineering model) | Yes (foundry-measured) |
| Commercial foundry sign-off | No | Yes |
| Waveform viewer | Yes (in-app) | Yes (Virtuoso VX) |
| Schematic capture | No | Yes (Virtuoso) |
| Chat-native flow | Yes | No |
| Open-source | Yes | No |

---
*Last reviewed: 2026-05-29. Cadence Spectre information from cadence.com product pages. Kerf capabilities reflect the current shipped product.*
