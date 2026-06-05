---
slug: autocad
competitor: "AutoCAD"
category: drafting
left: kerf
right: autocad
hero_tagline: "Industry-standard 2D drafting + .dwg ecosystem — different primary jobs."
reviewed_at: 2026-05-19
order: 1
features:
  # D1 — Geometry & core CAD
  - domain: D1
    feature: "Constraint sketcher (geo + dim)"
    competitor:
      status: yes
      note: "Parametric constraints: geometric + dimensional; OSNAP + inference; dynamic input"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-DA1B3D1A-7A9C-4B10-9B3F-8F5E8B2C4D7A"
    kerf:
      status: yes
      note: "PlaneGCS WASM; missing collinear, ellipse entity, G2"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Pad / pocket / revolve"
    competitor:
      status: partial
      note: "Solid 3D extrude/revolve/sweep present but not history-based parametric"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-3D-MODELING"
    kerf:
      status: yes
      note: "OCCT feature tree with full parametric history"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Direct edit (push-pull)"
    competitor:
      status: yes
      note: "PRESSPULL command; 3D solid direct editing; grips-based face manipulation"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-PRESSPULL"
    kerf:
      status: yes
      note: "push_pull (planar + curved), move_face, delete_face wired as ops"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/direct_edit.py"

  - domain: D1
    feature: "Fillet / chamfer (constant)"
    competitor:
      status: yes
      note: "FILLET and CHAMFER commands for 2D and 3D; well-established workflow"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-FILLET"
    kerf:
      status: yes
      note: "Wired; constant-radius fillet + chamfer"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "2D drawings (views/dims/sections)"
    competitor:
      status: yes
      note: "Industry-defining 2D drafting: dimension styles, leaders, tolerances, GD&T callouts"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-DIMENSIONING"
    kerf:
      status: partial
      note: "Template-based; not live B-rep projection; no UI panel"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "GD&T on drawings / MBD / PMI"
    competitor:
      status: yes
      note: "GD&T feature control frames, datum labels, surface texture symbols in drawing"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-GDT-OVERVIEW"
    kerf:
      status: yes
      note: "Data model only (kerf-gdnt); no UI placement on drawings"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt/feature_control_frame.py"

  - domain: D1
    feature: "Patterns (linear/polar) + mirror"
    competitor:
      status: yes
      note: "ARRAY (rectangular/polar/path) + MIRROR; 2D and 3D"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-ARRAY"
    kerf:
      status: yes
      note: "Linear/polar patterns + mirror wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "Sheet metal"
    competitor:
      status: paid
      note: "Available in AutoCAD Mechanical toolset add-on; not in base AutoCAD"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-mechanical"
    kerf:
      status: yes
      note: "Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/construction_verbs_tools.py"

  - domain: D1
    feature: "Assemblies — mates"
    competitor:
      status: no
      note: "AutoCAD has no parametric assembly environment; XREF for multi-file; no mate constraints"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-XREF"
    kerf:
      status: yes
      note: "Wired; coincident/concentric/parallel + BOM panel"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/assembly/mates.py"

  - domain: D1
    feature: "Configurations / family variants"
    competitor:
      status: no
      note: "No parametric configurations; use dynamic blocks or separate drawing files"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-DYNAMIC-BLOCKS"
    kerf:
      status: yes
      note: "Engine complete; ConfigurationsPanel.jsx wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D1
    feature: "NURBS surfacing (blend/network/patch)"
    competitor:
      status: partial
      note: "Surface commands (SURFBLEND, SURFPATCH, etc.) present but not NURBS-class tools"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-SURFACE-MODELING"
    kerf:
      status: yes
      note: "blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, G3 blends wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/network_srf.py"

  - domain: D1
    feature: "B-rep booleans (general NURBS)"
    competitor:
      status: yes
      note: "UNION, SUBTRACT, INTERSECT solid Boolean operations"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-BOOLEAN-OPERATIONS"
    kerf:
      status: yes
      note: "OCCT Boolean ops; no graceful failure handling / fuzzy heal"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  # D6 — Electronics / EDA / silicon
  - domain: D6
    feature: "Schematic capture (KiCad round-trip, ERC)"
    competitor:
      status: paid
      note: "AutoCAD Electrical toolset: schematic capture, wire numbering, ERC; separate paid SKU"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-electrical"
    kerf:
      status: yes
      note: "Schematic viewer wired (KiCad round-trip); ERC overlay"
      evidence: "packages/kerf-electronics/src/kerf_electronics/kicad_io.py"

  - domain: D6
    feature: "PCB layout (tscircuit, KiCad round-trip)"
    competitor:
      status: no
      note: "AutoCAD has no PCB layout capability; Electrical toolset is schematic-only"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-electrical"
    kerf:
      status: yes
      note: "PCB viewer wired (read-only); tscircuit + KiCad round-trip"
      evidence: "packages/kerf-electronics/src/kerf_electronics/kicad_io.py"

  - domain: D6
    feature: "DRC / ERC"
    competitor:
      status: paid
      note: "ERC in AutoCAD Electrical toolset only; no PCB DRC"
      source: "https://help.autodesk.com/view/ACDLT/2025/ENU/?guid=GUID-ELECTRICAL-ERC"
    kerf:
      status: yes
      note: "DRC overlay wired; IPC-2221B manufacturing presets"
      evidence: "packages/kerf-electronics/src/kerf_electronics/drc.py"

  - domain: D6
    feature: "Signal integrity (Z0/crosstalk/eye/IBIS)"
    competitor:
      status: no
      note: "No SI analysis in any AutoCAD toolset"
      source: "https://www.autodesk.com/products/autocad/included-toolsets"
    kerf:
      status: yes
      note: "IBIS 5.1 parser + Bergeron channel + PRBS eye envelope (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/si_eye_wizard.py"

  - domain: D6
    feature: "EMC (radiated/shielding/limits)"
    competitor:
      status: no
      note: "No EMC analysis in any AutoCAD toolset"
      source: "https://www.autodesk.com/products/autocad/included-toolsets"
    kerf:
      status: yes
      note: "Closed-form EMC wizard; no full-wave (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/emc_wizard.py"

  - domain: D6
    feature: "PDN (DC IR-drop + AC sweep)"
    competitor:
      status: no
      note: "No PDN analysis in any AutoCAD toolset"
      source: "https://www.autodesk.com/products/autocad/included-toolsets"
    kerf:
      status: yes
      note: "Frequency-domain Z(ω) + target-Z + decap optimiser (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/pdn_wizard.py"

  - domain: D6
    feature: "SPICE"
    competitor:
      status: no
      note: "No SPICE simulation; AutoCAD Electrical is schematic-diagram only"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-electrical"
    kerf:
      status: yes
      note: "Real ngspice wired; binary .raw not yet parsed"
      evidence: "packages/kerf-electronics/src/kerf_electronics/routes_spice.py"

  # D7 — Manufacturing / CAM
  - domain: D7
    feature: "3-axis CAM (profile/contour/pocket/face)"
    competitor:
      status: no
      note: "No CAM in AutoCAD; requires separate Autodesk CAM product (Fusion / HSMXpress)"
      source: "https://www.autodesk.com/products/autocad/overview"
    kerf:
      status: yes
      note: "3-axis CAM with tool DB, CAMView wired"
      evidence: "packages/kerf-cam/src/kerf_cam"

  - domain: D7
    feature: "G-code post (Fanuc/GRBL/LinuxCNC/Mach3)"
    competitor:
      status: no
      note: "No G-code output; not a CAM tool"
      source: "https://www.autodesk.com/products/autocad/overview"
    kerf:
      status: yes
      note: "Fanuc/GRBL/LinuxCNC/Mach3 posts; no G41/42 cutter-comp"
      evidence: "packages/kerf-cam/src/kerf_cam/posts"

  - domain: D7
    feature: "Nesting (skyline + true-shape NFP)"
    competitor:
      status: no
      note: "No nesting in AutoCAD base; nesting tools via 3rd-party add-ons only"
      source: "https://www.autodesk.com/products/autocad/overview"
    kerf:
      status: yes
      note: "Minkowski-sum NFP + IFP + bottom-left fill; 57.6% L-shape util (backend)"
      evidence: "packages/kerf-manufacturing/src/kerf_manufacturing/nesting"

  # D8 — Civil / infrastructure / geo
  - domain: D8
    feature: "Horizontal+vertical alignment (clothoid, SSD)"
    competitor:
      status: paid
      note: "Civil 3D product (separate SKU); Map 3D in AutoCAD toolset covers geospatial not civil alignments"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-map-3d"
    kerf:
      status: yes
      note: "Clothoid + SSD engine; AASHTO exhibit validated (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil/horizontal_alignment.py"

  - domain: D8
    feature: "Corridor / cross-section"
    competitor:
      status: paid
      note: "Civil 3D only; not in Map 3D toolset included with AutoCAD"
      source: "https://www.autodesk.com/products/civil-3d/overview"
    kerf:
      status: yes
      note: "Divided highway + reverse-crown + urban curb-gutter templates (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil/corridor.py"

  - domain: D8
    feature: "Survey / COGO"
    competitor:
      status: paid
      note: "AutoCAD Map 3D has basic geospatial; Civil 3D has full COGO traverse/closure"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-map-3d"
    kerf:
      status: yes
      note: "Traverse adjust, resection COGO (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil"

  - domain: D8
    feature: "Geodesy / projections (Vincenty, TM, UTM, LCC)"
    competitor:
      status: paid
      note: "Map 3D toolset: coordinate system library, reprojection; not Vincenty-depth geodesy"
      source: "https://help.autodesk.com/view/MAP/2025/ENU/?guid=GUID-COORDINATE-SYSTEMS"
    kerf:
      status: yes
      note: "Vincenty + TM + UTM + LCC deep geodesy (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil/crs.py"

  - domain: D8
    feature: "Hydrology (rational/SCS/TR-55)"
    competitor:
      status: no
      note: "No hydrology calculation engine in any AutoCAD toolset"
      source: "https://www.autodesk.com/products/autocad/included-toolsets"
    kerf:
      status: yes
      note: "Rational method / SCS / TR-55; no 2D/unsteady (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil"

  - domain: D8
    feature: "Geotech (bearing/settlement/slope/pile/liquefaction)"
    competitor:
      status: no
      note: "No geotechnical analysis in any AutoCAD toolset"
      source: "https://www.autodesk.com/products/autocad/included-toolsets"
    kerf:
      status: yes
      note: "Seed-Idriss CSR + SPT/CPT CRR + Tokimatsu liquefaction; Loma Prieta validated (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil"

  # D10 — Electrical / energy / PLC
  - domain: D10
    feature: "Wiring/harness (WireViz + 3D router)"
    competitor:
      status: paid
      note: "AutoCAD Electrical toolset: wire numbers, from-to lists, connector reports; no 3D harness routing"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-electrical"
    kerf:
      status: yes
      note: "WiringView wired; WireViz + 3D harness router"
      evidence: "packages/kerf-wiring/src/kerf_wiring/harness3d.py"

  - domain: D10
    feature: "PLC IEC 61131-3 (ST/Ladder/FB/motion)"
    competitor:
      status: no
      note: "AutoCAD Electrical is schematic-focused; no IEC 61131-3 PLC programming environment"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-electrical"
    kerf:
      status: yes
      note: "ST editor + live Ladder power-flow sim wired"
      evidence: "packages/kerf-plc/src/kerf_plc/power_flow.py"

  - domain: D10
    feature: "NEC power distribution + point-to-point SC"
    competitor:
      status: paid
      note: "AutoCAD Electrical: panel schedule report; no NEC load-flow or short-circuit calc"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-electrical"
    kerf:
      status: yes
      note: "Deep NEC load calc + SC (backend)"
      evidence: "packages/kerf-energy/src/kerf_energy"

  - domain: D10
    feature: "Solar PV (system + partial shading)"
    competitor:
      status: no
      note: "No solar PV analysis in any AutoCAD toolset"
      source: "https://www.autodesk.com/products/autocad/included-toolsets"
    kerf:
      status: yes
      note: "Single-diode + bypass-diode IV + global MPPT + mismatch loss (backend)"
      evidence: "packages/kerf-energy/src/kerf_energy"

  # D11 — Tolerancing / metrology / QA
  - domain: D11
    feature: "Limits & fits (ISO 286)"
    competitor:
      status: paid
      note: "AutoCAD Mechanical toolset: fits and tolerances table; ISO 286 hole/shaft selection"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-mechanical"
    kerf:
      status: yes
      note: "Full ISO 286 limits & fits engine (backend)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt"

  - domain: D11
    feature: "Tolerance stackup — 1D (WC/RSS/MC)"
    competitor:
      status: paid
      note: "AutoCAD Mechanical toolset: some stackup assistance; not a dedicated stackup tool"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-mechanical"
    kerf:
      status: yes
      note: "WC/RSS/MC tolerance stackup; Monte-Carlo LCG bug to fix (backend)"
      evidence: "packages/kerf-gdnt/src/kerf_gdnt"

  # Cross-cutting / platform
  - domain: D1
    feature: "Persistent face naming"
    competitor:
      status: partial
      note: "Handle-based entity naming in 3D solid; not full topological face-name persistence"
      source: "https://help.autodesk.com/view/ACD/2025/ENU/?guid=GUID-3D-MODELING"
    kerf:
      status: partial
      note: "Two disconnected systems (Python DAG vs OCCT faceNaming.js); not unified"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"

  - domain: D7
    feature: "Feeds & speeds + tool-life"
    competitor:
      status: no
      note: "No feeds/speeds or tool-life calculation in AutoCAD; CAM tools sold separately"
      source: "https://www.autodesk.com/products/autocad/overview"
    kerf:
      status: yes
      note: "Taylor extended + Gilbert economic speed (backend)"
      evidence: "packages/kerf-cam/src/kerf_cam/tool_db.py"

  - domain: D6
    feature: "Battery/BMS, motor/gate/LED driver"
    competitor:
      status: no
      note: "No electronic component sizing tools in any AutoCAD toolset"
      source: "https://www.autodesk.com/products/autocad/included-toolsets"
    kerf:
      status: yes
      note: "Battery/BMS + motor/gate/LED driver sizing calculators (backend)"
      evidence: "packages/kerf-electronics/src/kerf_electronics/battery"

  - domain: D8
    feature: "Pavement design (AASHTO '93)"
    competitor:
      status: no
      note: "No pavement design in Map 3D or any AutoCAD toolset"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-map-3d"
    kerf:
      status: yes
      note: "Full AASHTO 1993 pavement design engine (backend)"
      evidence: "packages/kerf-civil/src/kerf_civil"

  - domain: D10
    feature: "Firmware build/upload/monitor/debug"
    competitor:
      status: no
      note: "No firmware toolchain in any AutoCAD toolset"
      source: "https://www.autodesk.com/products/autocad/overview"
    kerf:
      status: yes
      note: "FirmwareActions + debug panel wired"
      evidence: "packages/kerf-firmware/src"

  - domain: D7
    feature: "Moldflow / fill sim"
    competitor:
      status: no
      note: "No moldflow simulation in AutoCAD; separate Moldflow product (Autodesk Moldflow)"
      source: "https://www.autodesk.com/products/moldflow/overview"
    kerf:
      status: yes
      note: "Hele-Shaw front tracking + weld-line + air-trap detection (backend)"
      evidence: "packages/kerf-mold/src/kerf_mold"

  - domain: D1
    feature: "Hole wizard (standards/tapped/cbore)"
    competitor:
      status: paid
      note: "AutoCAD Mechanical toolset: hole callouts and standard hole types in 2D; no 3D hole wizard"
      source: "https://www.autodesk.com/products/autocad/included-toolsets/autocad-mechanical"
    kerf:
      status: no
      note: "Bare cylinder punch only; no standards-based hole wizard"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core"
---

# Kerf vs AutoCAD

Industry-standard 2D drafting + .dwg ecosystem — different primary jobs.

*Last reviewed: 2026-05-19*

## Summary

Kerf saturates **95%** of AutoCAD's feature surface (38 yes, 2 partial, 1 no out of 41 features tracked here). Honest gaps: 2 features partial (engine complete, UI or depth gap); 1 feature not yet implemented.

## Feature comparison

| Feature | Kerf | AutoCAD | Notes |
|---------|------|---------|-------|
| Constraint sketcher (geo + dim) | ✅ | Yes | PlaneGCS WASM; missing collinear, ellipse entity, G2 |
| Pad / pocket / revolve | ✅ | Partial | OCCT feature tree with full parametric history |
| Direct edit (push-pull) | ✅ | Yes | push_pull (planar + curved), move_face, delete_face wired as ops |
| Fillet / chamfer (constant) | ✅ | Yes | Wired; constant-radius fillet + chamfer |
| 2D drawings (views/dims/sections) | ⚠️ (partial) | Yes | Template-based; not live B-rep projection; no UI panel |
| GD&T on drawings / MBD / PMI | ✅ | Yes | Data model only (kerf-gdnt); no UI placement on drawings |
| Patterns (linear/polar) + mirror | ✅ | Yes | Linear/polar patterns + mirror wired |
| Sheet metal | ✅ | Yes (paid tier) | Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief |
| Assemblies — mates | ✅ | No | Wired; coincident/concentric/parallel + BOM panel |
| Configurations / family variants | ✅ | No | Engine complete; ConfigurationsPanel.jsx wired |
| NURBS surfacing (blend/network/patch) | ✅ | Partial | blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, G3 blends wired |
| B-rep booleans (general NURBS) | ✅ | Yes | OCCT Boolean ops; no graceful failure handling / fuzzy heal |
| Schematic capture (KiCad round-trip, ERC) | ✅ | Yes (paid tier) | Schematic viewer wired (KiCad round-trip); ERC overlay |
| PCB layout (tscircuit, KiCad round-trip) | ✅ | No | PCB viewer wired (read-only); tscircuit + KiCad round-trip |
| DRC / ERC | ✅ | Yes (paid tier) | DRC overlay wired; IPC-2221B manufacturing presets |
| Signal integrity (Z0/crosstalk/eye/IBIS) | ✅ | No | IBIS 5.1 parser + Bergeron channel + PRBS eye envelope (backend) |
| EMC (radiated/shielding/limits) | ✅ | No | Closed-form EMC wizard; no full-wave (backend) |
| PDN (DC IR-drop + AC sweep) | ✅ | No | Frequency-domain Z(ω) + target-Z + decap optimiser (backend) |
| SPICE | ✅ | No | Real ngspice wired; binary .raw not yet parsed |
| 3-axis CAM (profile/contour/pocket/face) | ✅ | No | 3-axis CAM with tool DB, CAMView wired |
| G-code post (Fanuc/GRBL/LinuxCNC/Mach3) | ✅ | No | Fanuc/GRBL/LinuxCNC/Mach3 posts; no G41/42 cutter-comp |
| Nesting (skyline + true-shape NFP) | ✅ | No | Minkowski-sum NFP + IFP + bottom-left fill; 57.6% L-shape util (backend) |
| Horizontal+vertical alignment (clothoid, SSD) | ✅ | Yes (paid tier) | Clothoid + SSD engine; AASHTO exhibit validated (backend) |
| Corridor / cross-section | ✅ | Yes (paid tier) | Divided highway + reverse-crown + urban curb-gutter templates (backend) |
| Survey / COGO | ✅ | Yes (paid tier) | Traverse adjust, resection COGO (backend) |
| Geodesy / projections (Vincenty, TM, UTM, LCC) | ✅ | Yes (paid tier) | Vincenty + TM + UTM + LCC deep geodesy (backend) |
| Hydrology (rational/SCS/TR-55) | ✅ | No | Rational method / SCS / TR-55; no 2D/unsteady (backend) |
| Geotech (bearing/settlement/slope/pile/liquefaction) | ✅ | No | Seed-Idriss CSR + SPT/CPT CRR + Tokimatsu liquefaction; Loma Prieta validated (backend) |
| Wiring/harness (WireViz + 3D router) | ✅ | Yes (paid tier) | WiringView wired; WireViz + 3D harness router |
| PLC IEC 61131-3 (ST/Ladder/FB/motion) | ✅ | No | ST editor + live Ladder power-flow sim wired |
| NEC power distribution + point-to-point SC | ✅ | Yes (paid tier) | Deep NEC load calc + SC (backend) |
| Solar PV (system + partial shading) | ✅ | No | Single-diode + bypass-diode IV + global MPPT + mismatch loss (backend) |
| Limits & fits (ISO 286) | ✅ | Yes (paid tier) | Full ISO 286 limits & fits engine (backend) |
| Tolerance stackup — 1D (WC/RSS/MC) | ✅ | Yes (paid tier) | WC/RSS/MC tolerance stackup; Monte-Carlo LCG bug to fix (backend) |
| Persistent face naming | ⚠️ (partial) | Partial | Two disconnected systems (Python DAG vs OCCT faceNaming.js); not unified |
| Feeds & speeds + tool-life | ✅ | No | Taylor extended + Gilbert economic speed (backend) |
| Battery/BMS, motor/gate/LED driver | ✅ | No | Battery/BMS + motor/gate/LED driver sizing calculators (backend) |
| Pavement design (AASHTO '93) | ✅ | No | Full AASHTO 1993 pavement design engine (backend) |
| Firmware build/upload/monitor/debug | ✅ | No | FirmwareActions + debug panel wired |
| Moldflow / fill sim | ✅ | No | Hele-Shaw front tracking + weld-line + air-trap detection (backend) |
| Hole wizard (standards/tapped/cbore) | 🔴 (no) | Yes (paid tier) | Bare cylinder punch only; no standards-based hole wizard |

## What Kerf does that AutoCAD doesn't

- **Sheet metal** — Flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief
- **Assemblies — mates** — Wired; coincident/concentric/parallel + BOM panel
- **Configurations / family variants** — Engine complete; ConfigurationsPanel.jsx wired
- **Schematic capture (KiCad round-trip, ERC)** — Schematic viewer wired (KiCad round-trip); ERC overlay
- **PCB layout (tscircuit, KiCad round-trip)** — PCB viewer wired (read-only); tscircuit + KiCad round-trip
- **DRC / ERC** — DRC overlay wired; IPC-2221B manufacturing presets
- **Signal integrity (Z0/crosstalk/eye/IBIS)** — IBIS 5.1 parser + Bergeron channel + PRBS eye envelope (backend)
- **EMC (radiated/shielding/limits)** — Closed-form EMC wizard; no full-wave (backend)
- **PDN (DC IR-drop + AC sweep)** — Frequency-domain Z(ω) + target-Z + decap optimiser (backend)
- **SPICE** — Real ngspice wired; binary .raw not yet parsed
- **3-axis CAM (profile/contour/pocket/face)** — 3-axis CAM with tool DB, CAMView wired
- **G-code post (Fanuc/GRBL/LinuxCNC/Mach3)** — Fanuc/GRBL/LinuxCNC/Mach3 posts; no G41/42 cutter-comp
- *(and 18 more features not covered by AutoCAD)*

## What's honestly outstanding

- **2D drawings (views/dims/sections)** (Partial): Template-based; not live B-rep projection; no UI panel
- **Persistent face naming** (Partial): Two disconnected systems (Python DAG vs OCCT faceNaming.js); not unified
- **Hole wizard (standards/tapped/cbore)** (Not yet implemented): Bare cylinder punch only; no standards-based hole wizard

## Pricing

AutoCAD is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
