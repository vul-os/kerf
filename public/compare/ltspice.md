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
      evidence: "packages/kerf-silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — AC small-signal analysis"
    competitor:
      status: yes
      note: "LTspice .AC with frequency sweep; Bode, Nyquist, Nichols plots"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "AC analysis via ngspice bridge (.AC directive)"
      evidence: "packages/kerf-silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — DC operating-point / sweep"
    competitor:
      status: yes
      note: "LTspice .DC sweep and .OP operating-point"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "DC sweep via ngspice bridge"
      evidence: "packages/kerf-silicon/bridges/ngspice_bridge.py"

  - domain: D6
    feature: "SPICE — PVT corner sweep (60 corners)"
    competitor:
      status: partial
      note: "LTspice supports .STEP for parametric sweeps but has no built-in PVT corner automation; each corner requires a manual .STEP or separate run"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "60-corner PVT sweep (5P × 3V × 4T) with Monte-Carlo mismatch via silicon_pvt_sweep tool; Pelgrom-matched sky130 model"
      evidence: "packages/kerf-silicon/analog/pvt.py"

  - domain: D6
    feature: "SPICE — Monte-Carlo mismatch"
    competitor:
      status: partial
      note: "LTspice .MC command available but undocumented/limited; Analog Devices component libraries include some mismatch models"
      source: "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"
    kerf:
      status: yes
      note: "Pelgrom model Monte-Carlo (A_VT = 4 mV·µm) per corner; 50 samples/corner default, configurable"
      evidence: "packages/kerf-silicon/analog/pvt.py"

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
      status: no
      note: "Kerf accepts netlists directly; no schematic GUI for SPICE (circuit.tsx is for PCB-level schematics)"

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
      evidence: "packages/kerf-silicon/analog/pvt.py"
---

# Kerf vs LTspice

LTspice (from Analog Devices) is the dominant free SPICE simulator for analog and mixed-signal IC design. It is fast, well-documented, and ships with a large library of Analog Devices component models. Almost every analog designer has used it.

Kerf does not try to replace LTspice's schematic GUI. Instead, Kerf wraps the open-source ngspice engine in a chat-native, cloud-integrated workflow, adds automated PVT-corner sweeps, and gives simulation results a first-class viewer inside the project workspace.

## Where LTspice is stronger

- **Schematic capture.** LTspice has a mature schematic GUI. Kerf works with netlists directly; schematic capture for SPICE is not yet wired.
- **Component library.** LTspice ships with thousands of Analog Devices SPICE models (op-amps, regulators, discretes). Kerf relies on sky130 open PDK models and user-supplied netlists.
- **Solver speed for SMPS.** LTspice's solver is tuned for switching power supply transients with large time-constant ratios. Ngspice is competent but slower on these workloads.
- **FFT post-processing.** LTspice can compute FFTs of waveforms in the viewer. Kerf's WaveformViewer does not yet include post-processing.

## Where Kerf differs

- **PVT corner automation.** LTspice has no built-in 60-corner sweep. Kerf's `silicon_pvt_sweep` runs all 60 corners (5P × 3V × 4T) with Monte-Carlo mismatch in a single call, returning structured statistics (mean, 3σ, 5σ) per corner.
- **Chat-native workflow.** Describe what you want to simulate in plain language. The LLM translates to tool calls, backed by doc-search that prevents API hallucination.
- **Waveform as a project artifact.** Simulation results are saved as `.spice.waveform` files inside the project, versioned in git, and shareable.
- **Unified workspace.** The netlist that feeds the SPICE sim lives in the same project as the PCB, the mechanical enclosure, and the BOM. LTspice is a standalone tool.

## Honest gaps — where Kerf is behind today

- **No schematic GUI for SPICE.** Users must write or paste netlists. LTspice's point-and-click schematic is friendlier for exploration.
- **Smaller model library.** Kerf does not ship SPICE models for commercial components. The user must source their own or use generic sky130 PDK devices.
- **No convergence tuning.** LTspice exposes many solver options (`.OPTIONS RELTOL`, `.OPTIONS CHGTOL` etc). Kerf passes the netlist to ngspice without exposing these controls in the UI yet.

## Feature matrix

| Feature | Kerf | LTspice |
|---|---|---|
| License | MIT open-core | Freeware (proprietary) |
| Engine | ngspice (GPL) | Proprietary solver |
| Platform | Cloud + self-host | Windows / macOS |
| Transient (.TRAN) | Yes | Yes |
| AC sweep (.AC) | Yes | Yes |
| DC sweep (.DC) | Yes | Yes |
| PVT corner sweep (60 corners) | Yes (automated) | Manual .STEP only |
| Monte-Carlo mismatch | Yes (Pelgrom sky130) | Limited |
| Waveform viewer (interactive) | Yes (.spice.waveform) | Yes (native) |
| Dual cursors + ΔT measurement | Yes | Yes |
| FFT post-processing | No | Yes |
| Schematic capture GUI | No | Yes |
| Chat-native / LLM flow | Yes | No |
| Project git integration | Yes | No |
| sky130 / open PDK support | Yes | Partial |

---
*Last reviewed: 2026-05-29. LTspice information sourced from Analog Devices product page. Kerf capabilities reflect the current shipped product.*
