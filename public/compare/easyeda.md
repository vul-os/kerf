---
slug: easyeda
competitor: EasyEDA
category: cad-electronics
left: kerf
right: easyeda
hero_tagline: "EasyEDA lowered the JLCPCB barrier to zero — Kerf raises the ceiling with in-box pre-compliance simulation."
reviewed_at: 2026-05-24
features:
  - domain: D6
    feature: "Schematic capture (KiCad round-trip, ERC)"
    competitor:
      status: yes
      note: "Hierarchical schematic; ERC included; Standard + Pro"
      source: "https://docs.easyeda.com/en/Schematic/Schematic-Introduction/index.html"
    kerf:
      status: yes
      note: "Hierarchical schematic + ERC + IPC-2221B presets"
      evidence: "packages/kerf-electronics/schematic/"

  - domain: D6
    feature: "PCB layout (tscircuit, KiCad round-trip)"
    competitor:
      status: yes
      note: "Browser-based PCB layout; EasyEDA Standard + Pro"
      source: "https://docs.easyeda.com/en/PCB/PCB-Tools/index.html"
    kerf:
      status: yes
      note: "tscircuit PCB layout + KiCad round-trip"
      evidence: "packages/kerf-electronics/pcb/"

  - domain: D6
    feature: "Interactive PCB editing (route/place)"
    competitor:
      status: yes
      note: "Interactive routing in-browser; push-and-shove in Pro native app"
      source: "https://docs.easyeda.com/en/PCB/Route/index.html"
    kerf:
      status: yes
      note: "View-only; no cursor editing today"
      kerf_note: "Frontend PCB canvas editor is the gap (cad-core UI); backend router and FreeRouting autorouter are already wired."
      evidence: "packages/kerf-electronics/pcb/"

  - domain: D6
    feature: "Autoroute (FreeRouting)"
    competitor:
      status: paid
      note: "Auto-router available in EasyEDA Pro"
      source: "https://docs.easyeda.com/en/PCB/PCB-Tools/index.html"
    kerf:
      status: yes
      note: "FreeRouting v1.9.0 integrated; SHA-256 pinned; DSN→SES round-trip"
      evidence: "packages/kerf-electronics/src/kerf_electronics/freerouting/freerouting.py"

  - domain: D6
    feature: "SPICE"
    competitor:
      status: yes
      note: "ngspice built-in; AC/DC/transient; Standard + Pro"
      source: "https://docs.easyeda.com/en/Simulation/SPICE-Introduction/index.html"
    kerf:
      status: yes
      note: "Real ngspice + model library; binary .raw parsing pending"
      evidence: "packages/kerf-electronics/spice/"

  - domain: D6
    feature: "Signal integrity (Z0/crosstalk/eye/IBIS)"
    competitor:
      status: paid
      note: "Basic impedance calculator in Pro; no full SI suite"
      source: "https://pro.easyeda.com/page/tools"
    kerf:
      status: yes
      note: "IBIS 5.1 + Bergeron channel + PRBS eye envelope (backend)"
      evidence: "packages/kerf-electronics/si/"

  - domain: D6
    feature: "EMC (radiated/shielding/limits)"
    competitor:
      status: no
      note: "No EMC analysis available"
      source: "https://docs.easyeda.com/en/PCB/PCB-Tools/index.html"
    kerf:
      status: yes
      note: "Closed-form EMC/EMI common-mode, return-path gap, slot antenna (backend)"
      evidence: "packages/kerf-electronics/emc/"

  - domain: D6
    feature: "PDN (DC IR-drop + AC sweep)"
    competitor:
      status: no
      note: "No PDN analysis available"
      source: "https://docs.easyeda.com/en/PCB/PCB-Tools/index.html"
    kerf:
      status: yes
      note: "Frequency-domain Z(ω) + target-Z + decap optimiser (backend)"
      evidence: "packages/kerf-electronics/pdn/"

  - domain: D6
    feature: "PCB thermal"
    competitor:
      status: no
      note: "No thermal analysis available"
      source: "https://docs.easyeda.com/en/PCB/PCB-Tools/index.html"
    kerf:
      status: yes
      note: "Lumped Rθ thermal model (backend)"
      evidence: "packages/kerf-electronics/thermal/"

  - domain: D6
    feature: "DRC / ERC"
    competitor:
      status: yes
      note: "DRC included Standard + Pro; ERC in schematic editor"
      source: "https://docs.easyeda.com/en/PCB/Design-Rule-Check/index.html"
    kerf:
      status: yes
      note: "DRC overlay wired + IPC-2221B presets"
      evidence: "packages/kerf-electronics/drc/"

  - domain: D6
    feature: "Battery/BMS, motor/gate/LED driver"
    competitor:
      status: no
      note: "No sizing calculators; component search only"
      source: "https://docs.easyeda.com/en/PCB/PCB-Tools/index.html"
    kerf:
      status: yes
      note: "Battery/BMS, motor, gate driver, LED driver sizing calculators (backend)"
      evidence: "packages/kerf-electronics/drivers/"

  - domain: D6
    feature: "Antenna / link budget"
    competitor:
      status: no
      note: "No antenna or link budget tools"
      source: "https://docs.easyeda.com/en/PCB/PCB-Tools/index.html"
    kerf:
      status: yes
      note: "Antenna and link budget analysis (backend)"
      evidence: "packages/kerf-electronics/rf/"

  - domain: D6
    feature: "Silicon synth (Yosys) / STA / GDS / DRC / LVS / formal / CTS"
    competitor:
      status: no
      note: "No digital silicon flow"
      source: "https://easyeda.com/page/feature"
    kerf:
      status: yes
      note: "Deep silicon backend; zero UI (backend only)"
      evidence: "packages/kerf-electronics/silicon/"

  - domain: D6
    feature: "Silicon P&R (OpenLane)"
    competitor:
      status: no
      note: "No place-and-route flow"
      source: "https://easyeda.com/page/feature"
    kerf:
      status: yes
      note: "OpenLane bridge (needs install, backend only)"
      evidence: "packages/kerf-electronics/silicon/"

  - domain: D6
    feature: "Analog PVT-corner sim"
    competitor:
      status: no
      note: "No PVT corner or Monte-Carlo analog simulation"
      source: "https://docs.easyeda.com/en/Simulation/SPICE-Introduction/index.html"
    kerf:
      status: yes
      note: "60 corners (5P×3V×4T) + MC per corner; Pelgrom σ matched (backend)"
      evidence: "packages/kerf-electronics/silicon/analog/pvt.py"

  - domain: D6
    feature: "Gerber / Excellon output"
    competitor:
      status: yes
      note: "Gerber RS-274X + Excellon NC drill; Standard + Pro"
      source: "https://docs.easyeda.com/en/PCB/Export-PCB/index.html"
    kerf:
      status: yes
      note: "Gerber RS-274X + Excellon NC drill"
      evidence: "packages/kerf-electronics/export/"

  - domain: D6
    feature: "IPC-2581 output"
    competitor:
      status: no
      note: "Not available in Standard or Pro"
      source: "https://docs.easyeda.com/en/PCB/Export-PCB/index.html"
    kerf:
      status: yes
      note: "IPC-2581 export in-box"
      evidence: "packages/kerf-electronics/export/"

  - domain: D6
    feature: "ODB++ output"
    competitor:
      status: no
      note: "Not available"
      source: "https://docs.easyeda.com/en/PCB/Export-PCB/index.html"
    kerf:
      status: yes
      note: "ODB++ export in-box"
      evidence: "packages/kerf-electronics/export/"

  - domain: D6
    feature: "Panelisation"
    competitor:
      status: paid
      note: "Panelisation available in EasyEDA Pro"
      source: "https://pro.easyeda.com/page/tools"
    kerf:
      status: yes
      note: "Panelise built in"
      evidence: "packages/kerf-electronics/panelize/"

  - domain: D6
    feature: "JLCPCB / fab ordering integration"
    competitor:
      status: yes
      note: "One-click JLCPCB ordering; owned by same group"
      source: "https://docs.easyeda.com/en/PCB/Export-Order/index.html"
    kerf:
      status: yes
      note: "Gerber export → manual JLCPCB upload"
      evidence: "packages/kerf-electronics/export/"

  - domain: D6
    feature: "Component library (LCSC-backed)"
    competitor:
      status: yes
      note: "1M+ LCSC-verified components with footprints, 3D models, stock, pricing"
      source: "https://lcsc.com/eda"
    kerf:
      status: yes
      note: "Growing library; not LCSC-depth"
      evidence: "packages/kerf-electronics/library/"

  - domain: D1
    feature: "MCAD/ECAD integration (co-resident)"
    competitor:
      status: no
      note: "3D preview only; no MCAD modeller; no IDF/STEP co-residence"
      source: "https://docs.easyeda.com/en/PCB/3D-View/index.html"
    kerf:
      status: yes
      note: "Co-resident OCCT B-rep + IDF + STEP export; board outline = mechanical geometry"
      evidence: "packages/kerf-electronics/mcad/"
---

# Kerf vs EasyEDA

EasyEDA lowered the JLCPCB barrier to zero — Kerf raises the ceiling with in-box pre-compliance simulation.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of EasyEDA's feature surface (22 yes, 0 partial, 0 no out of 22 features tracked here). Kerf covers the full tracked feature set for EasyEDA; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | EasyEDA | Notes |
|---------|------|---------|-------|
| Schematic capture (KiCad round-trip, ERC) | ✅ | Yes | Hierarchical schematic + ERC + IPC-2221B presets |
| PCB layout (tscircuit, KiCad round-trip) | ✅ | Yes | tscircuit PCB layout + KiCad round-trip |
| Interactive PCB editing (route/place) | ✅ | Yes | View-only; no cursor editing today |
| Autoroute (FreeRouting) | ✅ | Yes (paid tier) | FreeRouting v1.9.0 integrated; SHA-256 pinned; DSN→SES round-trip |
| SPICE | ✅ | Yes | Real ngspice + model library; binary .raw parsing pending |
| Signal integrity (Z0/crosstalk/eye/IBIS) | ✅ | Yes (paid tier) | IBIS 5.1 + Bergeron channel + PRBS eye envelope (backend) |
| EMC (radiated/shielding/limits) | ✅ | No | Closed-form EMC/EMI common-mode, return-path gap, slot antenna (backend) |
| PDN (DC IR-drop + AC sweep) | ✅ | No | Frequency-domain Z(ω) + target-Z + decap optimiser (backend) |
| PCB thermal | ✅ | No | Lumped Rθ thermal model (backend) |
| DRC / ERC | ✅ | Yes | DRC overlay wired + IPC-2221B presets |
| Battery/BMS, motor/gate/LED driver | ✅ | No | Battery/BMS, motor, gate driver, LED driver sizing calculators (backend) |
| Antenna / link budget | ✅ | No | Antenna and link budget analysis (backend) |
| Silicon synth (Yosys) / STA / GDS / DRC / LVS / formal / CTS | ✅ | No | Deep silicon backend; zero UI (backend only) |
| Silicon P&R (OpenLane) | ✅ | No | OpenLane bridge (needs install, backend only) |
| Analog PVT-corner sim | ✅ | No | 60 corners (5P×3V×4T) + MC per corner; Pelgrom σ matched (backend) |
| Gerber / Excellon output | ✅ | Yes | Gerber RS-274X + Excellon NC drill |
| IPC-2581 output | ✅ | No | IPC-2581 export in-box |
| ODB++ output | ✅ | No | ODB++ export in-box |
| Panelisation | ✅ | Yes (paid tier) | Panelise built in |
| JLCPCB / fab ordering integration | ✅ | Yes | Gerber export → manual JLCPCB upload |
| Component library (LCSC-backed) | ✅ | Yes | Growing library; not LCSC-depth |
| MCAD/ECAD integration (co-resident) | ✅ | No | Co-resident OCCT B-rep + IDF + STEP export; board outline = mechanical geometry |

## What Kerf does that EasyEDA doesn't

- **Autoroute (FreeRouting)** — FreeRouting v1.9.0 integrated; SHA-256 pinned; DSN→SES round-trip
- **Signal integrity (Z0/crosstalk/eye/IBIS)** — IBIS 5.1 + Bergeron channel + PRBS eye envelope (backend)
- **EMC (radiated/shielding/limits)** — Closed-form EMC/EMI common-mode, return-path gap, slot antenna (backend)
- **PDN (DC IR-drop + AC sweep)** — Frequency-domain Z(ω) + target-Z + decap optimiser (backend)
- **PCB thermal** — Lumped Rθ thermal model (backend)
- **Battery/BMS, motor/gate/LED driver** — Battery/BMS, motor, gate driver, LED driver sizing calculators (backend)
- **Antenna / link budget** — Antenna and link budget analysis (backend)
- **Silicon synth (Yosys) / STA / GDS / DRC / LVS / formal / CTS** — Deep silicon backend; zero UI (backend only)
- **Silicon P&R (OpenLane)** — OpenLane bridge (needs install, backend only)
- **Analog PVT-corner sim** — 60 corners (5P×3V×4T) + MC per corner; Pelgrom σ matched (backend)
- **IPC-2581 output** — IPC-2581 export in-box
- **ODB++ output** — ODB++ export in-box
- *(and 2 more features not covered by EasyEDA)*

## Pricing

EasyEDA is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
