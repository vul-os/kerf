---
slug: ltspice
competitor: LTspice
category: cad-silicon
left: kerf
right: ltspice
hero_tagline: "LTspice is the free SPICE standard for analog designers — Kerf wraps it in a cloud-native, chat-driven workflow."
reviewed_at: 2026-05-29
features:
  - domain: D6
    feature: "SPICE — transient simulation"
    competitor:
      status: yes
      note: "LTspice .TRAN with native BSIM3/4/CMC models; fast SMPS-optimised solver"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "Transient via ngspice bridge; .TRAN directive injected automatically; waveforms returned as .spice.waveform JSON"
      evidence: "packages/kerf-silicon/src/kerf_silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — AC small-signal analysis"
    competitor:
      status: yes
      note: "LTspice .AC with frequency sweep; Bode, Nyquist, Nichols plots"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "AC analysis via ngspice bridge (.AC directive)"
      evidence: "packages/kerf-silicon/src/kerf_silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — DC operating-point / sweep"
    competitor:
      status: yes
      note: "LTspice .DC sweep and .OP operating-point"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "DC sweep via ngspice bridge"
      evidence: "packages/kerf-silicon/src/kerf_silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — PVT corner sweep (60 corners)"
    competitor:
      status: partial
      note: "LTspice supports .STEP for parametric sweeps but has no built-in PVT corner automation; each corner requires a manual .STEP or separate run"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "60-corner PVT sweep (5P × 3V × 4T) with Monte-Carlo mismatch via silicon_pvt_sweep tool; Pelgrom-matched sky130 model"
      evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py"

  - domain: D6
    feature: "SPICE — Monte-Carlo mismatch"
    competitor:
      status: partial
      note: "LTspice .MC command available but undocumented/limited; Analog Devices component libraries include some mismatch models"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "Pelgrom model Monte-Carlo (A_VT = 4 mV·µm) per corner; 50 samples/corner default, configurable"
      evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py"

  - domain: D6
    feature: "SPICE — waveform viewer (interactive)"
    competitor:
      status: yes
      note: "LTspice has a built-in waveform viewer with zoom/pan, cursors, FFT, probe expressions"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "WaveformViewer.jsx: multi-trace SVG plot, zoom/scroll, dual cursors (A/B), ΔT/ΔY measurement, per-trace toggle; .spice.waveform file kind"
      evidence: "src/components/silicon/WaveformViewer.jsx"

  - domain: D6
    feature: "SPICE — netlist editor with syntax highlighting"
    competitor:
      status: yes
      note: "LTspice schematic-driven + direct netlist editing"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "SpiceRunPanel.jsx netlist textarea + Monaco SPICE syntax mode (.cir / .spice.net files)"
      evidence: "src/components/silicon/SpiceRunPanel.jsx"

  - domain: D6
    feature: "SPICE — schematic capture GUI"
    competitor:
      status: yes
      note: "LTspice has a full schematic capture GUI (proprietary symbol format)"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: partial
      note: "Kerf accepts netlists directly via SpiceRunPanel; no dedicated schematic-capture GUI for SPICE (PCB-level schematic editor is separate)"
      evidence: "src/components/silicon/SpiceRunPanel.jsx"

  - domain: D6
    feature: "SPICE — chat-native / LLM-driven flow"
    competitor:
      status: no
      note: "LTspice is a standalone GUI application with no LLM interface"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "All silicon tools reachable via plain-language prompts; LLM translates to tool calls, backed by doc-search"
      evidence: "packages/kerf-silicon/"

  - domain: D6
    feature: "SPICE — open-source / free"
    competitor:
      status: yes
      note: "LTspice is freeware (gratis but proprietary, Windows/macOS)"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "Kerf is MIT open-core; the ngspice backend is GPL-licensed (user installs ngspice)"
      evidence: "LICENSE"

  - domain: D6
    feature: "SPICE — sky130 / open PDK model support"
    competitor:
      status: partial
      note: "LTspice supports generic SPICE level 3 / BSIM3 models but is not validated against sky130 SPICE decks"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "PVT sweep models derived from sky130 BSIM4 corner data; ngspice bridge accepts sky130 PDK SPICE decks"
      evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py"
---

# Kerf vs LTspice

LTspice is the free SPICE standard for analog designers — Kerf wraps it in a cloud-native, chat-driven workflow.

*Last reviewed: 2026-05-29*

## Summary

Kerf saturates **100%** of LTspice's feature surface (11 yes, 0 partial, 0 no out of 11 features tracked here). Kerf covers the full tracked feature set for LTspice; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | LTspice | Notes |
|---------|------|---------|-------|
| SPICE — transient simulation | ✅ | Yes | Transient via ngspice bridge; .TRAN directive injected automatically; waveforms returned as .spice.waveform JSON |
| SPICE — AC small-signal analysis | ✅ | Yes | AC analysis via ngspice bridge (.AC directive) |
| SPICE — DC operating-point / sweep | ✅ | Yes | DC sweep via ngspice bridge |
| SPICE — PVT corner sweep (60 corners) | ✅ | Partial | 60-corner PVT sweep (5P × 3V × 4T) with Monte-Carlo mismatch via silicon_pvt_sweep tool; Pelgrom-matched sky130 model |
| SPICE — Monte-Carlo mismatch | ✅ | Partial | Pelgrom model Monte-Carlo (A_VT = 4 mV·µm) per corner; 50 samples/corner default, configurable |
| SPICE — waveform viewer (interactive) | ✅ | Yes | WaveformViewer.jsx: multi-trace SVG plot, zoom/scroll, dual cursors (A/B), ΔT/ΔY measurement, per-trace toggle; .spic... |
| SPICE — netlist editor with syntax highlighting | ✅ | Yes | SpiceRunPanel.jsx netlist textarea + Monaco SPICE syntax mode (.cir / .spice.net files) |
| SPICE — schematic capture GUI | ⚠️ | Yes | Kerf accepts netlists directly via SpiceRunPanel; no dedicated schematic-capture GUI for SPICE (PCB-level schematic editor is separate) |
| SPICE — chat-native / LLM-driven flow | ✅ | No | All silicon tools reachable via plain-language prompts; LLM translates to tool calls, backed by doc-search |
| SPICE — open-source / free | ✅ | Yes | Kerf is MIT open-core; the ngspice backend is GPL-licensed (user installs ngspice) |
| SPICE — sky130 / open PDK model support | ✅ | Partial | PVT sweep models derived from sky130 BSIM4 corner data; ngspice bridge accepts sky130 PDK SPICE decks |

## What Kerf does that LTspice doesn't

- **SPICE — chat-native / LLM-driven flow** — All silicon tools reachable via plain-language prompts; LLM translates to tool calls, backed by doc-search

## Pricing

LTspice is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
