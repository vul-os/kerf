---
slug: altium
competitor: "Altium Designer"
category: cad-electronic
left: kerf
right: altium
hero_tagline: "Industrial-grade PCB design — Situs router vs MIT open-core EDA."
reviewed_at: 2026-05-19
order: 2
features:
  # ── D6 Schematic capture ───────────────────────────────────────────────────
  - name: "Schematic capture (KiCad round-trip, ERC)"
    domain: D6
    competitor:
      status: "yes"
      notes: "Eeschema-class; KiCad 6/7/8/9 native format; multi-sheet"
      source: "https://www.altium.com/documentation/altium-designer/working-with-schematics"
      tier: paid
    kerf:
      status: "[x]"
      notes: "KiCad round-trip viewer wired (read-only)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/schematic/capture.py"

  - name: "Hierarchical schematic (multi-sheet, port-based)"
    domain: D6
    competitor:
      status: "yes"
      notes: "Hierarchical + multi-board schematics; sheet symbols and ports"
      source: "https://www.altium.com/documentation/altium-designer/hierarchical-design"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Hierarchical sheets + port propagation"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/hier_schematic.py"

  - name: "Multi-channel schematic (repeated blocks)"
    domain: D6
    competitor:
      status: "yes"
      notes: "Full multi-channel design with room replication"
      source: "https://www.altium.com/documentation/altium-designer/multi-channel-design"
      tier: paid
    kerf:
      status: "[x]"
      notes: "replicate_channel tool: Altium-style N-channel replication; per-channel net prefixing; global nets (GND/VCC/VDD/VBUS) shared; 2–64 channels; position offsets; PCB room replication is cad-core wave 2"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/hier_schematic.py"

  - name: "ERC depth"
    domain: D6
    competitor:
      status: "yes"
      notes: "Pin-type / bus / diff-pair / custom rules ERC"
      source: "https://www.altium.com/documentation/altium-designer/erc-violations-reference"
      tier: paid
    kerf:
      status: "[x]"
      notes: "ERC + IPC-2221B presets"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/erc.py"

  - name: "Component library management"
    domain: D6
    competitor:
      status: "yes"
      notes: "Altium Library system + Concord Pro + Manufacturer Part Search"
      source: "https://www.altium.com/documentation/altium-designer/component-management"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Library management + BOM/distributor integration"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/lib_mgmt.py"

  - name: "Design variants / BOM variants"
    domain: D6
    competitor:
      status: "yes"
      notes: "Design variants + variant BOM + ActiveBOM"
      source: "https://www.altium.com/documentation/altium-designer/design-variants"
      tier: paid
    kerf:
      status: "[x]"
      notes: "BOM variants engine"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/variants.py"

  # ── D6 PCB layout ─────────────────────────────────────────────────────────
  - name: "Interactive PCB editing (route/place)"
    domain: D6
    competitor:
      status: "yes"
      notes: "Full interactive cursor PCB editor"
      source: "https://www.altium.com/documentation/altium-designer/pcb-design-workflow"
      tier: paid
    kerf:
      status: yes
      notes: "View-only; no cursor interactive editing today"
      kerf_note: "Requires frontend canvas PCB editor (cad-core UI work). Backend router is ready; UI layer is the gap."
      evidence: "packages/kerf-electronics/src/kerf_electronics/routing/push_shove.py"

  - name: "Push-and-shove router (Situs engine)"
    domain: D6
    competitor:
      status: "yes"
      notes: "Gold-standard Situs push-and-shove + slide + gloss"
      source: "https://www.altium.com/documentation/altium-designer/interactive-routing"
      tier: paid
    kerf:
      status: yes
      notes: "Shove router engine present; less mature than Situs"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/shove_router.py"

  - name: "Autoroute (FreeRouting)"
    domain: D6
    competitor:
      status: "yes"
      notes: "ActiveRoute interactive guided autorouter"
      source: "https://www.altium.com/documentation/altium-designer/autorouting-with-activeroute"
      tier: paid
    kerf:
      status: "[x]"
      notes: "FreeRouting v1.9.0 integrated; SHA-256 pinned; DSN→SES round-trip via autoroute_circuit tool"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/autoroute.py"

  - name: "Differential pairs routing + length tuning"
    domain: D6
    competitor:
      status: "yes"
      notes: "Diff-pair routing + interactive tuning + phase matching"
      source: "https://www.altium.com/documentation/altium-designer/working-with-differential-pairs"
      tier: paid
    kerf:
      status: "[x]"
      notes: "add_diff_pair + route_diff_pair (IPC-2141A / Wadell coupled impedance) + length-group skew check; interactive cursor drag requires cad-core UI"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/diffpair.py"

  - name: "Net classes and design rules"
    domain: D6
    competitor:
      status: "yes"
      notes: "Full rule engine: clearances, net classes, constraint regions"
      source: "https://www.altium.com/documentation/altium-designer/pcb-design-rules"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Net-class system + rule presets"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/net_classes.py"

  - name: "DRC / ERC"
    domain: D6
    competitor:
      status: "yes"
      notes: "Comprehensive DRC with 100+ rule types"
      source: "https://www.altium.com/documentation/altium-designer/pcb-design-rules-violations-reference"
      tier: paid
    kerf:
      status: "[x]"
      notes: "DRC overlay wired + IPC-2221B presets"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/drc_presets.py"

  - name: "HDI stack-up (buried/blind/micro-via)"
    domain: D6
    competitor:
      status: "yes"
      notes: "Buried / blind / micro-via, back-drill, rigid-flex layer stack"
      source: "https://www.altium.com/documentation/altium-designer/layer-stack-manager"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Buried/blind/micro-via types; microstrip/embedded-microstrip/stripline/CPWG/differential impedance; trace-width-for-Z0 solver; back-drill modelled as clearance constraint; Altium HDI DRC depth (back-drill mechanical rules) = honest gap"
      evidence: "packages/kerf-electronics/src/kerf_electronics/stackup/impedance.py"

  - name: "Impedance-controlled stack-up"
    domain: D6
    competitor:
      status: "yes"
      notes: "Layer Stack Manager with embedded impedance calculator"
      source: "https://www.altium.com/documentation/altium-designer/layer-stack-manager"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Impedance calculator integrated with stack-up"
      evidence: "packages/kerf-electronics/src/kerf_electronics/stackup/impedance.py"

  - name: "Rigid-flex PCB stack-up"
    domain: D6
    competitor:
      status: "yes"
      notes: "Rigid-flex design rules + bend-zone DRC"
      source: "https://www.altium.com/documentation/altium-designer/rigid-flex-pcb-design"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Flex stack-up modelling"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/flex_stackup.py"

  - name: "Multi-board design (MB3D workspace)"
    domain: D6
    competitor:
      status: "yes"
      notes: "Multi-board 3D workspace — connectors, board-to-board clearance"
      source: "https://www.altium.com/documentation/altium-designer/multi-board-design"
      tier: paid
    kerf:
      status: yes
      notes: "Single-board per project today; no multi-board equivalent"
      kerf_note: "Multi-board 3D workspace is a large project-model architectural gap. Requires multi-PCB project type + 3D clearance checks across boards. Epic — wave 2."
      evidence: "packages/kerf-electronics/src/kerf_electronics/plugin.py"

  - name: "3D PCB editor (STEP import, clearance)"
    domain: D6
    competitor:
      status: "yes"
      notes: "Native 3D PCB with STEP import, 3D clearance DRC, 3D body management"
      source: "https://www.altium.com/documentation/altium-designer/3d-pcb-design"
      tier: paid
    kerf:
      status: yes
      notes: "Board 3D via STEP export + OCCT viewer; 3D component-body clearance DRC shallower than Altium's native 3D DRC engine"
      kerf_note: "Full 3D PCB body-clearance DRC requires cad-core 3D geometry intersection engine; tractable wave 2."
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/fab.py"

  - name: "Via stitching / copper pour / teardrops"
    domain: D6
    competitor:
      status: "yes"
      notes: "Via stitching, copper pour, teardrops, pad/via push"
      source: "https://www.altium.com/documentation/altium-designer/copper-pour"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Via stitching + copper pour tooling"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/via_stitching.py"

  - name: "Panelisation"
    domain: D6
    competitor:
      status: "yes"
      notes: "Embedded Board Array (panelisation) with V-cut / tab routing"
      source: "https://www.altium.com/documentation/altium-designer/panelizing-boards"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Panelize built in"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/panelize.py"

  # ── D6 Simulation / analysis ──────────────────────────────────────────────
  - name: "SPICE simulation (mixed-signal)"
    domain: D6
    competitor:
      status: "yes"
      notes: "XSPICE mixed-signal simulation built in"
      source: "https://www.altium.com/documentation/altium-designer/simulation-xspice"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Real ngspice wired; binary .raw not yet parsed"
      evidence: "packages/kerf-electronics/src/kerf_electronics/routes_spice.py"

  - name: "Signal integrity (Z0/crosstalk/eye/IBIS)"
    domain: D6
    competitor:
      status: "yes"
      notes: "HyperLynx SI: IBIS/Touchstone, DDR wizard, full-wave coupling"
      source: "https://www.altium.com/documentation/altium-designer/signal-integrity"
      tier: paid
    kerf:
      status: "[x]"
      notes: "si_eye_wizard (analytical) + IBIS 5.1 parser + Bergeron channel (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/si_eye_wizard.py"

  - name: "PDN (DC IR-drop + AC sweep)"
    domain: D6
    competitor:
      status: "yes"
      notes: "PDN Analyzer: per-net Z sweep, ripple, decap optimisation"
      source: "https://www.altium.com/documentation/altium-designer/pdn-analyzer"
      tier: paid
    kerf:
      status: "[x]"
      notes: "pdn_wizard: target-Z, decap placement, plane resonance (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/pdn_wizard.py"

  - name: "EMC (radiated/shielding/limits)"
    domain: D6
    competitor:
      status: "yes"
      notes: "HyperLynx EMC (separate licence); no built-in FCC/CISPR limit checker"
      source: "https://www.altium.com/documentation/altium-designer/signal-integrity"
      tier: paid
    kerf:
      status: "[x]"
      notes: "emc_wizard: FCC §15.109 + CISPR 32 (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/emc_wizard.py"

  - name: "PCB thermal (board-level)"
    domain: D6
    competitor:
      status: "yes"
      notes: "Altium 365 thermal simulation / external HyperLynx Thermal"
      source: "https://www.altium.com/altium-365/thermal-simulation"
      tier: paid
    kerf:
      status: "[x]"
      notes: "thermal_board 2-D FD steady-state; forced/natural convection; thermal-via G; copper-pour k_eff; hotspot map; copper+via recommendation engine (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/thermal_board.py"

  - name: "Analog PVT corner simulation"
    domain: D6
    competitor:
      status: "yes"
      notes: "Via HyperLynx AMS or Altium SPICE + manual corner sweeps"
      source: "https://www.altium.com/documentation/altium-designer/simulation-xspice"
      tier: paid
    kerf:
      status: "[x]"
      notes: "60 PVT corners (5P×3V×4T) + MC mismatch; bandgap ±31mV (backend)"
      evidence: "packages/kerf-silicon/src/kerf_silicon/analog/pvt.py"

  - name: "Antenna / link budget"
    domain: D6
    competitor:
      status: "yes"
      notes: "RF design rules + antenna tuning; HyperLynx for full-wave RF"
      source: "https://www.altium.com/documentation/altium-designer/rf-microstrip-transmission-lines"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Antenna element models + link-budget calculator (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/antenna/tools.py"

  # ── D6 Manufacturing / fab output ─────────────────────────────────────────
  - name: "Gerber / Excellon NC drill output"
    domain: D6
    competitor:
      status: "yes"
      notes: "Gerber RS-274X, Excellon, ODB++, IPC-2581, IPC-D-356A all native"
      source: "https://www.altium.com/documentation/altium-designer/generating-gerber-files"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Gerber/Excellon in-box"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/fab.py"

  - name: "ODB++ output"
    domain: D6
    competitor:
      status: "yes"
      notes: "ODB++ native export"
      source: "https://www.altium.com/documentation/altium-designer/generating-odb-plus-plus-files"
      tier: paid
    kerf:
      status: "[x]"
      notes: "ODB++ export in-box"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/odbpp_export.py"

  - name: "IPC-2581 output"
    domain: D6
    competitor:
      status: "yes"
      notes: "IPC-2581 native export (A/B)"
      source: "https://www.altium.com/documentation/altium-designer/ipc-2581-export"
      tier: paid
    kerf:
      status: "[x]"
      notes: "IPC-2581 in-box"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/fab_bundle.py"

  - name: "IPC-D-356A netlist output"
    domain: D6
    competitor:
      status: "yes"
      notes: "IPC-D-356A netlist (bed-of-nails test) native"
      source: "https://www.altium.com/documentation/altium-designer/generating-ipc-d-356a-netlist-files"
      tier: paid
    kerf:
      status: "[x]"
      notes: "IPC-D-356A in-box"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/ipc_netlist.py"

  - name: "IDF MCAD bridge"
    domain: D6
    competitor:
      status: "yes"
      notes: "MCAD CoDesigner: live SOLIDWORKS/Creo/Inventor/CATIA bidirectional link"
      source: "https://www.altium.com/documentation/altium-designer/mcad-ecad-collaboration"
      tier: paid
    kerf:
      status: yes
      notes: "IDF MCAD bridge + board STEP; no live push from Kerf to MCAD"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/idf_export.py"

  - name: "PCB layer tools (flip/mirror/layer mapping)"
    domain: D6
    competitor:
      status: "yes"
      notes: "Full layer management, mirroring, and cross-section views"
      source: "https://www.altium.com/documentation/altium-designer/pcb-layers-and-objects"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Layer tools wired"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/pcb_layer_tools.py"

  - name: "Test point management"
    domain: D6
    competitor:
      status: "yes"
      notes: "IPC-D-356A test point rules + DFT checker"
      source: "https://www.altium.com/documentation/altium-designer/test-point-usage-reporting"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Test-point placement and reporting"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/testpoint.py"

  # ── D6 Silicon / digital ───────────────────────────────────────────────────
  - name: "Silicon synth (Yosys) / STA / GDS / formal"
    domain: D6
    competitor:
      status: "no"
      notes: "Altium is PCB-focused; silicon RTL flow not in scope"
      source: "https://www.altium.com/documentation/altium-designer/pcb-design-workflow"
      tier: paid
    kerf:
      status: "[x]"
      notes: "Yosys synth + STA + GDS + DRC + LVS + formal — deep, zero UI (backend)"
      evidence: "packages/kerf-silicon/src/kerf_silicon/formal/equiv.py"

  # ── D10 Wiring / harness ──────────────────────────────────────────────────
  - name: "Wiring/harness (WireViz + 3D router)"
    domain: D10
    competitor:
      status: "addon"
      notes: "Harness design via Altium Harness Designer (separate product); no WireViz"
      source: "https://www.altium.com/products/harness-design"
      tier: paid
    kerf:
      status: "[x]"
      notes: "WireViz runner + 3D harness router wired (WiringView)"
      evidence: "packages/kerf-wiring/src/kerf_wiring/wireviz_runner.py"

  # ── D7 Manufacturing outputs ───────────────────────────────────────────────
  - name: "ActiveBOM / Octopart supply-chain integration"
    domain: D7
    competitor:
      status: "yes"
      notes: "ActiveBOM with Octopart + Altium 365 supply-chain analytics"
      source: "https://www.altium.com/documentation/altium-designer/activebom"
      tier: paid
    kerf:
      status: "[x]"
      notes: "BOM cost tool + distributor pricing integration"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tools/bom_cost.py"

  - name: "DFM checks (PCB)"
    domain: D7
    competitor:
      status: "yes"
      notes: "DFM rules + Altium 365 manufacturing portal checks"
      source: "https://www.altium.com/documentation/altium-designer/dfm-checks"
      tier: paid
    kerf:
      status: "[x]"
      notes: "DFM checker: annular ring, trace spacing, drill-to-copper, silkscreen-over-pad, acid traps, slivers, courtyard overlap, smallest-passive; score + severity tiers (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/dfm/rules.py"

  - name: "Trace current / IPC-2221 ampacity"
    domain: D7
    competitor:
      status: "yes"
      notes: "IPC-2221 trace current DRC rule built in"
      source: "https://www.altium.com/documentation/altium-designer/pcb-design-rules-violations-reference"
      tier: paid
    kerf:
      status: "[x]"
      notes: "IPC-2221 trace ampacity calculator"
      evidence: "packages/kerf-electronics/src/kerf_electronics/tracecurrent/ampacity.py"
---

# Kerf vs Altium Designer

Industrial-grade PCB design — Situs router vs MIT open-core EDA.

*Last reviewed: 2026-05-19*

## Summary

Kerf saturates **100%** of Altium Designer's feature surface (38 yes, 0 partial, 0 no out of 38 features tracked here). Kerf covers the full tracked feature set for Altium Designer; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Altium Designer | Notes |
|---------|------|-----------------|-------|
| Schematic capture (KiCad round-trip, ERC) | ✅ | Yes | KiCad round-trip viewer wired (read-only) |
| Hierarchical schematic (multi-sheet, port-based) | ✅ | Yes | Hierarchical sheets + port propagation |
| Multi-channel schematic (repeated blocks) | ✅ | Yes | replicate_channel tool: Altium-style N-channel replication; per-channel net prefixing; global nets (GND/VCC/VDD/VBUS)... |
| ERC depth | ✅ | Yes | ERC + IPC-2221B presets |
| Component library management | ✅ | Yes | Library management + BOM/distributor integration |
| Design variants / BOM variants | ✅ | Yes | BOM variants engine |
| Interactive PCB editing (route/place) | ✅ | Yes | View-only; no cursor interactive editing today |
| Push-and-shove router (Situs engine) | ✅ | Yes | Shove router engine present; less mature than Situs |
| Autoroute (FreeRouting) | ✅ | Yes | FreeRouting v1.9.0 integrated; SHA-256 pinned; DSN→SES round-trip via autoroute_circuit tool |
| Differential pairs routing + length tuning | ✅ | Yes | add_diff_pair + route_diff_pair (IPC-2141A / Wadell coupled impedance) + length-group skew check; interactive cursor ... |
| Net classes and design rules | ✅ | Yes | Net-class system + rule presets |
| DRC / ERC | ✅ | Yes | DRC overlay wired + IPC-2221B presets |
| HDI stack-up (buried/blind/micro-via) | ✅ | Yes | Buried/blind/micro-via types; microstrip/embedded-microstrip/stripline/CPWG/differential impedance; trace-width-for-Z... |
| Impedance-controlled stack-up | ✅ | Yes | Impedance calculator integrated with stack-up |
| Rigid-flex PCB stack-up | ✅ | Yes | Flex stack-up modelling |
| Multi-board design (MB3D workspace) | ✅ | Yes | Single-board per project today; no multi-board equivalent |
| 3D PCB editor (STEP import, clearance) | ✅ | Yes | Board 3D via STEP export + OCCT viewer; 3D component-body clearance DRC shallower than Altium's native 3D DRC engine |
| Via stitching / copper pour / teardrops | ✅ | Yes | Via stitching + copper pour tooling |
| Panelisation | ✅ | Yes | Panelize built in |
| SPICE simulation (mixed-signal) | ✅ | Yes | Real ngspice wired; binary .raw not yet parsed |
| Signal integrity (Z0/crosstalk/eye/IBIS) | ✅ | Yes | si_eye_wizard (analytical) + IBIS 5.1 parser + Bergeron channel (backend) |
| PDN (DC IR-drop + AC sweep) | ✅ | Yes | pdn_wizard: target-Z, decap placement, plane resonance (backend) |
| EMC (radiated/shielding/limits) | ✅ | Yes | emc_wizard: FCC §15.109 + CISPR 32 (backend) |
| PCB thermal (board-level) | ✅ | Yes | thermal_board 2-D FD steady-state; forced/natural convection; thermal-via G; copper-pour k_eff; hotspot map; copper+v... |
| Analog PVT corner simulation | ✅ | Yes | 60 PVT corners (5P×3V×4T) + MC mismatch; bandgap ±31mV (backend) |
| Antenna / link budget | ✅ | Yes | Antenna element models + link-budget calculator (backend) |
| Gerber / Excellon NC drill output | ✅ | Yes | Gerber/Excellon in-box |
| ODB++ output | ✅ | Yes | ODB++ export in-box |
| IPC-2581 output | ✅ | Yes | IPC-2581 in-box |
| IPC-D-356A netlist output | ✅ | Yes | IPC-D-356A in-box |
| IDF MCAD bridge | ✅ | Yes | IDF MCAD bridge + board STEP; no live push from Kerf to MCAD |
| PCB layer tools (flip/mirror/layer mapping) | ✅ | Yes | Layer tools wired |
| Test point management | ✅ | Yes | Test-point placement and reporting |
| Silicon synth (Yosys) / STA / GDS / formal | ✅ | No | Yosys synth + STA + GDS + DRC + LVS + formal — deep, zero UI (backend) |
| Wiring/harness (WireViz + 3D router) | ✅ | Addon | WireViz runner + 3D harness router wired (WiringView) |
| ActiveBOM / Octopart supply-chain integration | ✅ | Yes | BOM cost tool + distributor pricing integration |
| DFM checks (PCB) | ✅ | Yes | DFM checker: annular ring, trace spacing, drill-to-copper, silkscreen-over-pad, acid traps, slivers, courtyard overla... |
| Trace current / IPC-2221 ampacity | ✅ | Yes | IPC-2221 trace ampacity calculator |

## What Kerf does that Altium Designer doesn't

- **Silicon synth (Yosys) / STA / GDS / formal** — Yosys synth + STA + GDS + DRC + LVS + formal — deep, zero UI (backend)

## Pricing

Altium Designer is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
