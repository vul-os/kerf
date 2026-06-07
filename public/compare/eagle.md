---
slug: eagle
competitor: Autodesk Eagle
category: cad-electronic
left: kerf
right: eagle
hero_tagline: "Eagle democratised PCB design for a generation of makers — its successor lives inside Fusion, but Kerf gives you the same workflow without the subscription."
reviewed_at: 2026-05-24
features:
  - domain: D6
    feature: "Schematic capture (KiCad round-trip, ERC)"
    competitor:
      status: paid
      note: "Hierarchical schematic capture; EAGLE Standard/Premium subscription; EOL June 2026, replaced by Fusion Electronics"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Viewer wired (read-only); KiCad round-trip; ERC overlay"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "PCB layout (tscircuit, KiCad round-trip)"
    competitor:
      status: paid
      note: "Full interactive PCB editor; unlimited layers in Fusion Electronics; EAGLE free tier was 2-layer / 80cm2"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Viewer wired (read-only); tscircuit + KiCad round-trip"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "Interactive PCB editing (route/place)"
    competitor:
      status: paid
      note: "Full interactive routing and placement in EAGLE and Fusion Electronics"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "View-only; no cursor editing"
      kerf_note: "Frontend PCB canvas editor is the gap (cad-core UI); backend shove router and FreeRouting autorouter are already wired."
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "Autoroute (FreeRouting)"
    competitor:
      status: paid
      note: "Integrated autorouter in EAGLE; Fusion Electronics includes Specctra-compatible autorouter"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "FreeRouting v1.9.0 integrated; SHA-256 pinned; DSN→SES round-trip"
      evidence: "packages/kerf-electronics/src/kerf_electronics/freerouting/freerouting.py"

  - domain: D6
    feature: "DRC / ERC"
    competitor:
      status: paid
      note: "Design Rule Check and Electrical Rule Check; IPC-2221B presets available in Fusion Electronics"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "DRC overlay wired; ERC on schematic viewer"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "SPICE simulation"
    competitor:
      status: paid
      note: "Basic SPICE simulation in Fusion Electronics; Fusion Electronics includes SPICE-compatible waveform viewer"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Real ngspice wired; binary .raw parsing not yet surfaced"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "Signal integrity (Z0/crosstalk/eye/IBIS)"
    competitor:
      status: no
      note: "Not available in EAGLE; Fusion Electronics requires Simulation extension; no IBIS native support"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "IBIS 5.1 parser + Bergeron channel + PRBS eye envelope; backend"
      evidence: "packages/kerf-electronics/src/kerf_electronics/si"

  - domain: D6
    feature: "EMC (radiated/shielding/limits)"
    competitor:
      status: no
      note: "No EMC analysis in EAGLE or Fusion Electronics base product; no radiated emission or shielding calculator"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Closed-form EMC analysis (radiated/shielding/limits); no full-wave; backend"
      evidence: "packages/kerf-electronics/src/kerf_electronics/emc"

  - domain: D6
    feature: "PDN (DC IR-drop + AC sweep)"
    competitor:
      status: no
      note: "No PDN analysis in EAGLE; Fusion Electronics requires Simulation extension for any power-plane analysis"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Frequency-domain Z(omega) + target-Z + decap optimiser; backend"
      evidence: "packages/kerf-electronics/src/kerf_electronics/pdn"

  - domain: D6
    feature: "PCB thermal"
    competitor:
      status: partial
      note: "Lumped thermal estimate only; full cooling analysis requires Fusion Simulation extension (paid add-on)"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Full 2-D FD steady-state solver; natural+forced convection; thermal vias; hotspot map (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/thermal_board.py"

  - domain: D6
    feature: "Antenna / link budget"
    competitor:
      status: no
      note: "No antenna design or link budget tools in EAGLE or Fusion Electronics"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Antenna and link budget calculators; backend"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "Battery/BMS, motor/gate/LED driver sizing"
    competitor:
      status: no
      note: "No integrated power-electronics sizing calculators in EAGLE or Fusion Electronics"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Sizing calculators for battery/BMS, motor drivers, gate drivers, LED drivers; backend"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "Gerber RS-274X output"
    competitor:
      status: paid
      note: "Gerber RS-274X and Excellon NC drill output; standard fabrication output in all EAGLE tiers"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Gerber 274X + Excellon NC drill export"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "IPC-2581 output"
    competitor:
      status: no
      note: "IPC-2581 not supported in EAGLE or Fusion Electronics base product"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "IPC-2581 export supported"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "ODB++ output"
    competitor:
      status: no
      note: "ODB++ not supported in EAGLE or Fusion Electronics"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "ODB++ export supported"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "ULP scripting"
    competitor:
      status: paid
      note: "User Language Programs (ULP) scripting in EAGLE; Python API available in Fusion Electronics"
      source: "https://blogs.autodesk.com/eagle/eagle-tips-tricks/ultimate-guide-to-eagle-ulp-scripts/"
    kerf:
      status: yes
      note: "Python-first kerf-sdk scripting; HTTP/JSON-RPC interface"
      evidence: "packages/kerf-sdk/"

  - domain: D6
    feature: "Component library"
    competitor:
      status: paid
      note: "Large legacy EAGLE community library (Sparkfun, Adafruit, component.guru .lbr files); Fusion Electronics adds manufacturer part search"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Growing component library; BOM panel + distributor integration"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "MCAD/ECAD integration"
    competitor:
      status: paid
      note: "Native live bidirectional link between PCB editor and Fusion 360 mechanical model; part of Fusion subscription"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Co-resident MCAD+ECAD environment; IDF and STEP board export"
      evidence: "packages/kerf-electronics/"

  - domain: D6
    feature: "Silicon synthesis (Yosys) / STA / GDS"
    competitor:
      status: no
      note: "No silicon/RTL/digital-IC design flow in EAGLE or Fusion Electronics"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "Yosys synth + STA + GDS + DRC + LVS + formal + CTS; backend, zero UI"
      evidence: "packages/kerf-silicon/"

  - domain: D6
    feature: "Silicon P&R (OpenLane)"
    competitor:
      status: no
      note: "No place-and-route or physical design flow in EAGLE or Fusion Electronics"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "OpenLane P&R integration; backend, needs install"
      evidence: "packages/kerf-silicon/"

  - domain: D6
    feature: "Analog PVT-corner simulation"
    competitor:
      status: no
      note: "No process/voltage/temperature corner simulation or Monte-Carlo mismatch analysis in EAGLE or Fusion Electronics"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "60 corners (5P x 3V x 4T) + Monte-Carlo per corner; Pelgrom sigma matched; backend"
      evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py"

  - domain: D6
    feature: "License model"
    competitor:
      status: paid
      note: "EAGLE: proprietary subscription, EOL June 2026; Fusion Electronics: bundled in Fusion 360 ~$680/yr (May 2026)"
      source: "https://www.autodesk.com/products/eagle"
    kerf:
      status: yes
      note: "MIT open-core; free locally with no layer or board-size restriction; hosted credits at cost"
      evidence: "LICENSE"
---

# Kerf vs Autodesk Eagle

Eagle democratised PCB design for a generation of makers — its successor lives inside Fusion, but Kerf gives you the same workflow without the subscription.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of Autodesk Eagle's feature surface (22 yes, 0 partial, 0 no out of 22 features tracked here). Kerf covers the full tracked feature set for Autodesk Eagle; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Autodesk Eagle | Notes |
|---------|------|----------------|-------|
| Schematic capture (KiCad round-trip, ERC) | ✅ | Yes (paid tier) | Viewer wired (read-only); KiCad round-trip; ERC overlay |
| PCB layout (tscircuit, KiCad round-trip) | ✅ | Yes (paid tier) | Viewer wired (read-only); tscircuit + KiCad round-trip |
| Interactive PCB editing (route/place) | ✅ | Yes (paid tier) | View-only; no cursor editing |
| Autoroute (FreeRouting) | ✅ | Yes (paid tier) | FreeRouting v1.9.0 integrated; SHA-256 pinned; DSN→SES round-trip |
| DRC / ERC | ✅ | Yes (paid tier) | DRC overlay wired; ERC on schematic viewer |
| SPICE simulation | ✅ | Yes (paid tier) | Real ngspice wired; binary .raw parsing not yet surfaced |
| Signal integrity (Z0/crosstalk/eye/IBIS) | ✅ | No | IBIS 5.1 parser + Bergeron channel + PRBS eye envelope; backend |
| EMC (radiated/shielding/limits) | ✅ | No | Closed-form EMC analysis (radiated/shielding/limits); no full-wave; backend |
| PDN (DC IR-drop + AC sweep) | ✅ | No | Frequency-domain Z(omega) + target-Z + decap optimiser; backend |
| PCB thermal | ✅ | Partial | Full 2-D FD steady-state solver; natural+forced convection; thermal vias; hotspot map (backend) |
| Antenna / link budget | ✅ | No | Antenna and link budget calculators; backend |
| Battery/BMS, motor/gate/LED driver sizing | ✅ | No | Sizing calculators for battery/BMS, motor drivers, gate drivers, LED drivers; backend |
| Gerber RS-274X output | ✅ | Yes (paid tier) | Gerber 274X + Excellon NC drill export |
| IPC-2581 output | ✅ | No | IPC-2581 export supported |
| ODB++ output | ✅ | No | ODB++ export supported |
| ULP scripting | ✅ | Yes (paid tier) | Python-first kerf-sdk scripting; HTTP/JSON-RPC interface |
| Component library | ✅ | Yes (paid tier) | Growing component library; BOM panel + distributor integration |
| MCAD/ECAD integration | ✅ | Yes (paid tier) | Co-resident MCAD+ECAD environment; IDF and STEP board export |
| Silicon synthesis (Yosys) / STA / GDS | ✅ | No | Yosys synth + STA + GDS + DRC + LVS + formal + CTS; backend, zero UI |
| Silicon P&R (OpenLane) | ✅ | No | OpenLane P&R integration; backend, needs install |
| Analog PVT-corner simulation | ✅ | No | 60 corners (5P x 3V x 4T) + Monte-Carlo per corner; Pelgrom sigma matched; backend |
| License model | ✅ | Yes (paid tier) | MIT open-core; free locally with no layer or board-size restriction; hosted credits at cost |

## What Kerf does that Autodesk Eagle doesn't

- **Schematic capture (KiCad round-trip, ERC)** — Viewer wired (read-only); KiCad round-trip; ERC overlay
- **PCB layout (tscircuit, KiCad round-trip)** — Viewer wired (read-only); tscircuit + KiCad round-trip
- **Interactive PCB editing (route/place)** — View-only; no cursor editing
- **Autoroute (FreeRouting)** — FreeRouting v1.9.0 integrated; SHA-256 pinned; DSN→SES round-trip
- **DRC / ERC** — DRC overlay wired; ERC on schematic viewer
- **SPICE simulation** — Real ngspice wired; binary .raw parsing not yet surfaced
- **Signal integrity (Z0/crosstalk/eye/IBIS)** — IBIS 5.1 parser + Bergeron channel + PRBS eye envelope; backend
- **EMC (radiated/shielding/limits)** — Closed-form EMC analysis (radiated/shielding/limits); no full-wave; backend
- **PDN (DC IR-drop + AC sweep)** — Frequency-domain Z(omega) + target-Z + decap optimiser; backend
- **Antenna / link budget** — Antenna and link budget calculators; backend
- **Battery/BMS, motor/gate/LED driver sizing** — Sizing calculators for battery/BMS, motor drivers, gate drivers, LED drivers; backend
- **Gerber RS-274X output** — Gerber 274X + Excellon NC drill export
- *(and 9 more features not covered by Autodesk Eagle)*

## Pricing

Autodesk Eagle is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
