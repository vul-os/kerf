---
slug: openplc
competitor: OpenPLC
category: cad-firmware
left: kerf
right: openplc
hero_tagline: "OpenPLC brings IEC 61131-3 logic to open hardware — Kerf connects the logic to the PCB that runs it."
reviewed_at: 2026-05-24
features:
  - domain: D10
    feature: "PLC IEC 61131-3 ladder/ST"
    competitor:
      status: yes
      note: "LD, ST, FBD, SFC, IL — all five IEC 61131-3 languages in OpenPLC Editor (Beremiz-based)"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "ST editor + live Ladder power-flow sim wired in-browser; chat-native ST generation; PLCopen XML (IEC TR 61131-10) import/export"
      evidence: "packages/kerf-plc/"
  - domain: D10
    feature: "PLCopen XML import/export (IEC TR 61131-10)"
    competitor:
      status: yes
      note: "OpenPLC Editor (Beremiz) reads and writes PLCopen XML natively"
      source: "https://github.com/thiagoralves/OpenPLC_Editor"
    kerf:
      status: yes
      note: "Pure-Python PLCopen XML reader/writer (kerf_plc.plcopen); import_plcopen_xml + export_plcopen_xml LLM tools; LadderEditor Import/Export .plc buttons; round-trip test against blinker + conveyor fixtures"
      evidence: "packages/kerf-plc/src/kerf_plc/plcopen/"
  - domain: D10
    feature: "Firmware build/upload/monitor/debug"
    competitor:
      status: yes
      note: "OpenPLC Runtime compiles IEC 61131-3 to C++, deploys to target; web dashboard for monitor"
      source: "https://www.openplcproject.com/runtime"
    kerf:
      status: yes
      note: "FirmwareActions + debug panel wired; build/upload/monitor/debug in-browser"
      evidence: "src/components/FirmwareActions"
  - domain: D10
    feature: "Wiring/harness (WireViz + 3D router)"
    competitor:
      status: no
      note: "OpenPLC has no wiring harness or cable design tooling"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "WiringView with WireViz + 3D harness router wired"
      evidence: "src/components/WiringView"
  - domain: D10
    feature: "NEC power distribution + point-to-point SC"
    competitor:
      status: no
      note: "OpenPLC has no power distribution or short-circuit analysis"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "NEC power distribution + point-to-point short-circuit (backend)"
      evidence: "packages/kerf-electrical/"
  - domain: D10
    feature: "AC load-flow (Ybus / Newton-Raphson)"
    competitor:
      status: no
      note: "OpenPLC has no load-flow or power-systems analysis"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "Full polar-form Newton-Raphson load-flow; 3+5-bus validated (backend)"
      evidence: "packages/kerf-electrical/loadflow.py"
  - domain: D10
    feature: "OTA delivery endpoint (cloud)"
    competitor:
      status: no
      note: "OpenPLC has no OTA delivery; firmware must be flashed manually per device"
      source: "https://github.com/thiagoralves/OpenPLC_Editor"
    kerf:
      status: yes
      note: "POST /firmware/ota/release (Ed25519-signed) + GET /firmware/ota/check; C backends for ESP32/STM32/SAMD"
      evidence: "packages/kerf-firmware/src/kerf_firmware/routes.py"
  - domain: D10
    feature: "Solar PV (system + partial shading)"
    competitor:
      status: no
      note: "OpenPLC has no solar PV or energy modelling capability"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "Single-diode + bypass-diode IV + global MPPT + mismatch loss + partial shading (backend)"
      evidence: "packages/kerf-electrical/solarpv/shading.py"
  - domain: D10
    feature: "Protection coordination (TCC) / arc-flash"
    competitor:
      status: no
      note: "OpenPLC has no protection coordination or arc-flash analysis"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "IEEE C37.112 U1-U5 TCC + IEEE 1584-2018 arc-flash incident energy (backend)"
      evidence: "packages/kerf-electrical/"
  - domain: D6
    feature: "Schematic capture (KiCad round-trip, ERC)"
    competitor:
      status: no
      note: "OpenPLC has no schematic capture or ERC; hardware design is outside its scope"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "Schematic capture + ERC wired; KiCad round-trip import/export"
      evidence: "src/components/SchematicView"
  - domain: D6
    feature: "PCB layout (tscircuit, KiCad round-trip)"
    competitor:
      status: no
      note: "OpenPLC has no PCB layout tooling"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "PCB layout viewer wired (KiCad round-trip + tscircuit); DRC overlay included"
      evidence: "src/components/PCBView"
  - domain: D6
    feature: "EMC (radiated/shielding/limits)"
    competitor:
      status: no
      note: "OpenPLC has no EMC pre-compliance analysis"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "emc_wizard: FCC §15.109 + CISPR 32 closed-form radiated/conducted limits (backend)"
      evidence: "packages/kerf-emc/"
  - domain: D6
    feature: "PDN (DC IR-drop + AC sweep)"
    competitor:
      status: no
      note: "OpenPLC has no PDN or power integrity analysis"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "pdn_wizard: Z(ω) target-Z, DC IR-drop, decap optimiser (backend)"
      evidence: "packages/kerf-si/pdn/ac_impedance.py"
  - domain: D9
    feature: "Controls — classical (Routh/Bode/RL/PID tune)"
    competitor:
      status: partial
      note: "PID function blocks per IEC 61131-3 are supported; no Bode/root-locus/graphical tuning"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "Classical controls: Routh stability, Bode, root locus, PID auto-tune (backend)"
      evidence: "packages/kerf-controls/"
  - domain: D9
    feature: "Controls — state-space / LQR / Kalman"
    competitor:
      status: no
      note: "OpenPLC has no state-space, LQR, or Kalman filter tooling"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "State-space, LQR (CARE), Luenberger observer, discrete ZOH c2d (backend)"
      evidence: "packages/kerf-controls/statespace.py"
  - domain: D1
    feature: "Parametric solid modelling (B-rep)"
    competitor:
      status: no
      note: "OpenPLC has no mechanical CAD or solid modelling capability"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "Full OCCT B-rep, constraint sketcher, sheet metal, assemblies — all in-browser"
      evidence: "src/components/CADView"
  - domain: D7
    feature: "G-code post (Fanuc/GRBL/LinuxCNC/Mach3)"
    competitor:
      status: no
      note: "OpenPLC has no CAM or G-code toolpath capability"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "G-code post for Fanuc, GRBL, LinuxCNC, Mach3; 3-axis toolpaths wired in CAMView"
      evidence: "src/components/CAMView"
  - domain: D14
    feature: "BOM + distributor pricing"
    competitor:
      status: no
      note: "OpenPLC has no BOM management or distributor pricing integration"
      source: "https://www.openplcproject.com/reference"
    kerf:
      status: yes
      note: "BOM management + real-time distributor pricing (Octopart/Mouser/Digi-Key) in-browser"
      evidence: "src/components/BOMView"
---

# Kerf vs OpenPLC

OpenPLC brings IEC 61131-3 logic to open hardware — Kerf connects the logic to the PCB that runs it.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of OpenPLC's feature surface (18 yes, 0 partial, 0 no out of 18 features tracked here). Kerf covers the full tracked feature set for OpenPLC; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | OpenPLC | Notes |
|---------|------|---------|-------|
| PLC IEC 61131-3 ladder/ST | ✅ | Yes | ST editor + live Ladder power-flow sim wired in-browser; chat-native ST generation; PLCopen XML (IEC TR 61131-10) imp... |
| PLCopen XML import/export (IEC TR 61131-10) | ✅ | Yes | Pure-Python PLCopen XML reader/writer (kerf_plc.plcopen); import_plcopen_xml + export_plcopen_xml LLM tools; LadderEd... |
| Firmware build/upload/monitor/debug | ✅ | Yes | FirmwareActions + debug panel wired; build/upload/monitor/debug in-browser |
| Wiring/harness (WireViz + 3D router) | ✅ | No | WiringView with WireViz + 3D harness router wired |
| NEC power distribution + point-to-point SC | ✅ | No | NEC power distribution + point-to-point short-circuit (backend) |
| AC load-flow (Ybus / Newton-Raphson) | ✅ | No | Full polar-form Newton-Raphson load-flow; 3+5-bus validated (backend) |
| OTA delivery endpoint (cloud) | ✅ | No | POST /firmware/ota/release (Ed25519-signed) + GET /firmware/ota/check; C backends for ESP32/STM32/SAMD |
| Solar PV (system + partial shading) | ✅ | No | Single-diode + bypass-diode IV + global MPPT + mismatch loss + partial shading (backend) |
| Protection coordination (TCC) / arc-flash | ✅ | No | IEEE C37.112 U1-U5 TCC + IEEE 1584-2018 arc-flash incident energy (backend) |
| Schematic capture (KiCad round-trip, ERC) | ✅ | No | Schematic capture + ERC wired; KiCad round-trip import/export |
| PCB layout (tscircuit, KiCad round-trip) | ✅ | No | PCB layout viewer wired (KiCad round-trip + tscircuit); DRC overlay included |
| EMC (radiated/shielding/limits) | ✅ | No | emc_wizard: FCC §15.109 + CISPR 32 closed-form radiated/conducted limits (backend) |
| PDN (DC IR-drop + AC sweep) | ✅ | No | pdn_wizard: Z(ω) target-Z, DC IR-drop, decap optimiser (backend) |
| Controls — classical (Routh/Bode/RL/PID tune) | ✅ | Partial | Classical controls: Routh stability, Bode, root locus, PID auto-tune (backend) |
| Controls — state-space / LQR / Kalman | ✅ | No | State-space, LQR (CARE), Luenberger observer, discrete ZOH c2d (backend) |
| Parametric solid modelling (B-rep) | ✅ | No | Full OCCT B-rep, constraint sketcher, sheet metal, assemblies — all in-browser |
| G-code post (Fanuc/GRBL/LinuxCNC/Mach3) | ✅ | No | G-code post for Fanuc, GRBL, LinuxCNC, Mach3; 3-axis toolpaths wired in CAMView |
| BOM + distributor pricing | ✅ | No | BOM management + real-time distributor pricing (Octopart/Mouser/Digi-Key) in-browser |

## What Kerf does that OpenPLC doesn't

- **Wiring/harness (WireViz + 3D router)** — WiringView with WireViz + 3D harness router wired
- **NEC power distribution + point-to-point SC** — NEC power distribution + point-to-point short-circuit (backend)
- **AC load-flow (Ybus / Newton-Raphson)** — Full polar-form Newton-Raphson load-flow; 3+5-bus validated (backend)
- **OTA delivery endpoint (cloud)** — POST /firmware/ota/release (Ed25519-signed) + GET /firmware/ota/check; C backends for ESP32/STM32/SAMD
- **Solar PV (system + partial shading)** — Single-diode + bypass-diode IV + global MPPT + mismatch loss + partial shading (backend)
- **Protection coordination (TCC) / arc-flash** — IEEE C37.112 U1-U5 TCC + IEEE 1584-2018 arc-flash incident energy (backend)
- **Schematic capture (KiCad round-trip, ERC)** — Schematic capture + ERC wired; KiCad round-trip import/export
- **PCB layout (tscircuit, KiCad round-trip)** — PCB layout viewer wired (KiCad round-trip + tscircuit); DRC overlay included
- **EMC (radiated/shielding/limits)** — emc_wizard: FCC §15.109 + CISPR 32 closed-form radiated/conducted limits (backend)
- **PDN (DC IR-drop + AC sweep)** — pdn_wizard: Z(ω) target-Z, DC IR-drop, decap optimiser (backend)
- **Controls — state-space / LQR / Kalman** — State-space, LQR (CARE), Luenberger observer, discrete ZOH c2d (backend)
- **Parametric solid modelling (B-rep)** — Full OCCT B-rep, constraint sketcher, sheet metal, assemblies — all in-browser
- *(and 2 more features not covered by OpenPLC)*

## Pricing

OpenPLC is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
