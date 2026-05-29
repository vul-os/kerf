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
      evidence: "packages/kerf-silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — AC analysis"
    competitor:
      status: yes
      note: "ngspice .AC with DEC/OCT/LIN sweep"
      source: "https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml"
    kerf:
      status: yes
      note: "AC analysis via ngspice bridge"
      evidence: "packages/kerf-silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — PVT corner sweep"
    competitor:
      status: partial
      note: "ngspice supports .STEP and shell scripting for corner sweeps; no built-in PVT automation"
      source: "https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml"
    kerf:
      status: yes
      note: "60-corner automated PVT sweep (5P × 3V × 4T) with Monte-Carlo; silicon_pvt_sweep tool"
      evidence: "packages/kerf-silicon/analog/pvt.py"

  - domain: D6
    feature: "SPICE — Monte-Carlo mismatch"
    competitor:
      status: partial
      note: "ngspice supports MC via .PARAM + random() functions; requires manual model setup"
      source: "https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml"
    kerf:
      status: yes
      note: "Pelgrom model Monte-Carlo built into PVT sweep; 50 samples/corner default"
      evidence: "packages/kerf-silicon/analog/pvt.py"

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

NGSpice is not a competitor to Kerf — it is the open-source SPICE engine that Kerf uses under the hood. Kerf's `ngspice_bridge.py` invokes ngspice in batch mode (`ngspice -b`) and parses the output into structured waveform data. This page explains what ngspice provides natively and what the Kerf layer adds on top.

## What ngspice provides natively

NGSpice is a comprehensive open-source SPICE simulator derived from Berkeley SPICE 3f5 + Cider + Xspice. It supports:

- All standard SPICE analyses: `.TRAN`, `.AC`, `.DC`, `.OP`, `.NOISE`, `.DISTO`, `.SENS`, `.TF`
- BSIM3v3, BSIM4, BSIM-CMG, HiSIM2, PSP, EKV device models
- Verilog-A model support via OpenVAF/ADMS
- Mixed analog/digital simulation (Xspice digital blocks)
- Python scripting via the `ngspice` Python library

## What Kerf adds

- **Project integration.** Netlists and waveform results live in the project workspace alongside PCB files, mechanical models, and firmware.
- **Automated PVT sweep.** A single chat command or tool call runs all 60 sky130 corners with Monte-Carlo mismatch. With raw ngspice you'd write a shell loop over 60 netlists.
- **In-app waveform viewer.** WaveformViewer.jsx renders multi-trace plots with zoom/pan and dual cursors directly in the browser. No external GAW or Python matplotlib step.
- **Chat-native flow.** Describe the simulation in plain language; the LLM writes or modifies the netlist and selects the analysis type.

## Honest gaps

- **No Verilog-A / Xspice passthrough.** Kerf's bridge calls ngspice in batch mode on a plain netlist. Xspice digital blocks and Verilog-A compiled models are not yet tested end-to-end through the bridge.
- **No convergence control.** `.OPTIONS RELTOL`, `.OPTIONS CHGTOL`, and other solver knobs are not yet exposed in SpiceRunPanel.

## Feature matrix

| Feature | Kerf | NGSpice (standalone) |
|---|---|---|
| License | MIT (Kerf) + LGPL (ngspice) | LGPL/BSD |
| Interface | GUI + chat + Python SDK | CLI / interactive shell |
| Transient (.TRAN) | Yes | Yes |
| AC sweep (.AC) | Yes | Yes |
| DC sweep (.DC) | Yes | Yes |
| Noise (.NOISE) | Via netlist passthrough | Yes |
| PVT corner sweep | Yes (automated, 60 corners) | Manual scripting |
| Monte-Carlo | Yes (Pelgrom sky130) | Manual .PARAM |
| Waveform viewer | Yes (in-app) | Basic plot / external tool |
| Dual cursors + measurement | Yes | External tool only |
| Schematic-to-netlist GUI | No | Via Xschem / KiCad |
| Chat-native flow | Yes | No |
| Project git integration | Yes | No |

---
*Last reviewed: 2026-05-29. NGSpice information from ngspice.sourceforge.io manual. Kerf capabilities reflect the current shipped product.*
