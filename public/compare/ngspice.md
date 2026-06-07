---
slug: ngspice
competitor: NGSpice
category: cad-silicon
left: kerf
right: ngspice
hero_tagline: "NGSpice is the open-source SPICE engine Kerf uses under the hood — Kerf adds the workflow layer on top."
reviewed_at: 2026-05-29
features:
  - domain: D6
    feature: "SPICE — transient simulation"
    competitor:
      status: yes
      note: "ngspice batch .TRAN via -b flag; supports BSIM3/4/6, HiSIM, PSP models"
      source: "https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml"
    kerf:
      status: yes
      note: "Kerf wraps ngspice -b in a subprocess bridge; .TRAN injected automatically; result serialised to .spice.waveform JSON"
      evidence: "packages/kerf-silicon/src/kerf_silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — AC analysis"
    competitor:
      status: yes
      note: "ngspice .AC with DEC/OCT/LIN sweep"
      source: "https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml"
    kerf:
      status: yes
      note: "AC analysis via ngspice bridge"
      evidence: "packages/kerf-silicon/src/kerf_silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — PVT corner sweep"
    competitor:
      status: partial
      note: "ngspice supports .STEP and shell scripting for corner sweeps; no built-in PVT automation"
      source: "https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml"
    kerf:
      status: yes
      note: "60-corner automated PVT sweep (5P × 3V × 4T) with Monte-Carlo; silicon_pvt_sweep tool"
      evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py"

  - domain: D6
    feature: "SPICE — Monte-Carlo mismatch"
    competitor:
      status: partial
      note: "ngspice supports MC via .PARAM + random() functions; requires manual model setup"
      source: "https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml"
    kerf:
      status: yes
      note: "Pelgrom model Monte-Carlo built into PVT sweep; 50 samples/corner default"
      evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py"

  - domain: D6
    feature: "SPICE — waveform viewer"
    competitor:
      status: partial
      note: "ngspice has a basic built-in plot command; serious use relies on external tools (KiCad, GAW, Xschem)"
      source: "https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml"
    kerf:
      status: yes
      note: "First-class in-app WaveformViewer: multi-trace SVG, zoom/pan, dual cursors (A/B), ΔT measurement"
      evidence: "src/components/silicon/WaveformViewer.jsx"

  - domain: D6
    feature: "SPICE — interactive/GUI workflow"
    competitor:
      status: no
      note: "ngspice is CLI-first; interactive mode exists but is not a GUI application"
      source: "https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml"
    kerf:
      status: yes
      note: "SpiceRunPanel.jsx: netlist editor + analysis selector + Run button; results shown in WaveformViewer"
      evidence: "src/components/silicon/SpiceRunPanel.jsx"

  - domain: D6
    feature: "SPICE — chat-native / LLM flow"
    competitor:
      status: no
      note: "ngspice is a CLI tool with no LLM interface"
      source: "https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml"
    kerf:
      status: yes
      note: "All SPICE analyses reachable via plain-language prompts"
      evidence: "packages/kerf-silicon/"

  - domain: D6
    feature: "SPICE — open-source"
    competitor:
      status: yes
      note: "ngspice is LGPL/BSD — fully open-source"
      source: "https://ngspice.sourceforge.io/"
    kerf:
      status: yes
      note: "Kerf is MIT open-core; ngspice backend installed separately by user (GPL/LGPL)"
      evidence: "LICENSE"
---

# Kerf vs NGSpice

NGSpice is the open-source SPICE engine Kerf uses under the hood — Kerf adds the workflow layer on top.

*Last reviewed: 2026-05-29*

## Summary

Kerf saturates **100%** of NGSpice's feature surface (8 yes, 0 partial, 0 no out of 8 features tracked here). Kerf covers the full tracked feature set for NGSpice; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | NGSpice | Notes |
|---------|------|---------|-------|
| SPICE — transient simulation | ✅ | Yes | Kerf wraps ngspice -b in a subprocess bridge; .TRAN injected automatically; result serialised to .spice.waveform JSON |
| SPICE — AC analysis | ✅ | Yes | AC analysis via ngspice bridge |
| SPICE — PVT corner sweep | ✅ | Partial | 60-corner automated PVT sweep (5P × 3V × 4T) with Monte-Carlo; silicon_pvt_sweep tool |
| SPICE — Monte-Carlo mismatch | ✅ | Partial | Pelgrom model Monte-Carlo built into PVT sweep; 50 samples/corner default |
| SPICE — waveform viewer | ✅ | Partial | First-class in-app WaveformViewer: multi-trace SVG, zoom/pan, dual cursors (A/B), ΔT measurement |
| SPICE — interactive/GUI workflow | ✅ | No | SpiceRunPanel.jsx: netlist editor + analysis selector + Run button; results shown in WaveformViewer |
| SPICE — chat-native / LLM flow | ✅ | No | All SPICE analyses reachable via plain-language prompts |
| SPICE — open-source | ✅ | Yes | Kerf is MIT open-core; ngspice backend installed separately by user (GPL/LGPL) |

## What Kerf does that NGSpice doesn't

- **SPICE — interactive/GUI workflow** — SpiceRunPanel.jsx: netlist editor + analysis selector + Run button; results shown in WaveformViewer
- **SPICE — chat-native / LLM flow** — All SPICE analyses reachable via plain-language prompts

## Pricing

NGSpice is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
