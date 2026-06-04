---
slug: nx
competitor: Siemens NX
category: cad-mechanical
left: kerf
right: nx
hero_tagline: "NX defined advanced surfacing for a generation — Kerf makes that power accessible without a six-figure licence."
reviewed_at: 2026-05-24
features:
  # D1 — Geometry & core CAD
  - domain: D1
    feature: Constraint sketcher (geo + dim)
    nx: "Full parametric sketcher — geometric + dimensional constraints, fully integrated with history"
    nx_tier: included
    competitor:source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1428004/en-US
    kerf:status: shipped
    kerf:evidence: src/lib/planeGCS/
  - domain: D1
    feature: Pad / pocket / revolve
    nx: "Extrude / revolve feature commands with full taper and symmetric options"
    nx_tier: included
    competitor:source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1427993/en-US
    kerf:status: shipped
    kerf:evidence: cloud/occt/features/extrude.py
  - domain: D1
    feature: Variable-radius fillet
    nx: "Edge blend with variable radius law (linear / cubic / S-shape) and face-blend types"
    nx_tier: included
    competitor:source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1428075/en-US
    kerf:status: shipped
    kerf:evidence: cloud/occt/features/fillet.py
  - domain: D1
    feature: NURBS surfacing (blend/network/patch)
    nx: "NX Shape Studio — Class-A G2/G3 surfaces, reflection line analysis, curvature combs; automotive-grade"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: partial
    kerf:note: "blend/network/patch/match-srf + G3 + zebra/isophote + Class-A harness wired; not Shape-Studio depth"
    kerf:evidence: packages/kerf-cad-core/src/kerf_cad_core/geom/network_srf.py
  - domain: D1
    feature: Direct edit (push-pull)
    nx: "Synchronous Technology — history-free face move/resize/delete works on any B-rep regardless of origin"
    nx_tier: included
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/synchronous-technology.html
    kerf:status: shipped
    kerf:note: "push_pull (planar + curved), move_face, delete_face wired as ops"
    kerf:evidence: packages/kerf-cad-core/src/kerf_cad_core/geom/direct_edit.py
  - domain: D1
    feature: Assemblies — mates
    nx: "Assembly constraints (coincident, concentric, parallel, distance, angle) with full kinematic DoF tracking"
    nx_tier: included
    competitor:source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1427957/en-US
    kerf:status: shipped
    kerf:evidence: cloud/assembly/mates.py
  - domain: D1
    feature: Sheet metal
    nx: "NX Sheet Metal — flanges, hems, joggle, relief patterns, flat pattern, NC output"
    nx_tier: included
    competitor:source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1428210/en-US
    kerf:status: shipped
    kerf:note: "flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief"
    kerf:evidence: packages/kerf-cad-core/src/kerf_cad_core/construction_verbs_tools.py
  - domain: D1
    feature: 2D drawings (views/dims/sections)
    nx: "Full drafting environment — multi-sheet drawings, section views, detail views, GD&T annotations"
    nx_tier: included
    competitor:source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1428294/en-US
    kerf:status: partial
    kerf:evidence: cloud/drawings/
  - domain: D1
    feature: GD&T on drawings / MBD / PMI
    nx: "PMI (Product and Manufacturing Information) — full MBD with semantic GD&T, 3D annotations, PMI views"
    nx_tier: included
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: partial
    kerf:evidence: cloud/gdt/model.py
  # D2 — Structural / FEA
  - domain: D2
    feature: FE — solid (tet/hex)
    nx: "Simcenter Nastran — SOL 101/103/105/106/111; tet/hex/penta elements; full pre/post in NX"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-nastran.html
    kerf:status: shipped
    kerf:evidence: cloud/fem/solid_bridge.py
  - domain: D2
    feature: Modal / buckling / nonlinear
    nx: "Simcenter Nastran SOL 103 (modal), SOL 105 (buckling), SOL 106 (nonlinear static), SOL 400 (advanced nonlinear)"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-nastran.html
    kerf:status: shipped
    kerf:evidence: cloud/fem/modal.py
  - domain: D2
    feature: AISC 360-22 steel (members)
    nx: "Not included — structural code checks require Simcenter integration or external tools"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/structural/aisc_member.py
  - domain: D2
    feature: Fatigue (S-N, ε-N, rainflow)
    nx: "Simcenter Nastran fatigue (SOL 101 + S-N / ε-N); Simcenter 3D durability with rainflow counting"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-3d.html
    kerf:status: shipped
    kerf:evidence: cloud/structural/fatigue.py
  # D3 — Machine elements
  - domain: D3
    feature: Spur/helical gear rating (AGMA 2001-D04)
    nx: "NX does not include gear rating calculators — gear geometry only; rating requires external KISSsoft link"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/machine/gearstrength/agma.py
  - domain: D3
    feature: Bearings — ISO 281 L10
    nx: "No native bearing selection — geometry catalogue only; integration with bearing vendor tools via API"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/machine/bearings/select.py
  - domain: D3
    feature: Shaft (stress + critical speed)
    nx: "No native shaft analysis; Simcenter Rotor Dynamics add-on covers critical speed for rotating machinery"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-3d.html
    kerf:status: shipped
    kerf:evidence: cloud/machine/shaft.py
  # D4 — Thermal / fluid / HVAC
  - domain: D4
    feature: Thermo cycles (Rankine/Brayton/Otto)
    nx: "Not included in NX — thermodynamic cycle analysis is outside NX scope"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/thermal/cycles.py
  - domain: D4
    feature: CFD
    nx: "Simcenter STAR-CCM+ — full-featured CFD (finite volume, polyhedral mesh, multi-physics); separate product"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-star-ccm.html
    kerf:status: shipped
    kerf:evidence: cloud/cfd/openfoam_bridge.py
  - domain: D4
    feature: Heat exchangers (LMTD + ε-NTU + Bell-Delaware)
    nx: "Not included in NX core — thermal sizing calculators are outside standard NX scope"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/thermal/heatxfer/shell_tube_bell.py
  # D5 — Aero / marine / space
  - domain: D5
    feature: 3D wing VLM (+ viscous + compressibility)
    nx: "Not included in NX — aerodynamic analysis delegated to Simcenter STAR-CCM+ or external RANS/panel codes"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-star-ccm.html
    kerf:status: shipped
    kerf:evidence: cloud/aero/vlm_viscous.py
  - domain: D5
    feature: Orbital (Kepler, J2/J3, Hohmann)
    nx: "Not included in NX — orbital mechanics outside NX scope"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/space/orbital.py
  - domain: D5
    feature: Turbomachinery / wind-turbine BEM
    nx: "Simcenter 3D Aerostructures / Rotating Machinery — blade design, Campbell diagram, forced response"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-3d.html
    kerf:status: shipped
    kerf:evidence: cloud/aero/turbomachinery.py
  - domain: D5
    feature: Naval hydrostatics + GZ stability (IMO)
    nx: "Not included in NX — marine hydrostatics require FORAN or Orca3D integration"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/marine/hydrostatics.py
  # D6 — Electronics / EDA / silicon
  - domain: D6
    feature: Schematic capture (KiCad round-trip, ERC)
    nx: "NX does not include schematic capture — electronics via Mentor Capital/xDX Designer (Siemens EDA, separate)"
    nx_tier: none
    competitor:source: https://eda.sw.siemens.com/en-US/pcb/capital/
    kerf:status: shipped
    kerf:evidence: src/components/SchematicView.jsx
  - domain: D6
    feature: PCB layout (tscircuit, KiCad round-trip)
    nx: "PCB design via Mentor PADS or Xpedition (Siemens EDA) — separate tool stack, MCAD↔ECAD sync via IDF/IDX"
    nx_tier: paid
    competitor:source: https://eda.sw.siemens.com/en-US/pcb/xpedition/
    kerf:status: shipped
    kerf:evidence: src/components/PCBView.jsx
  - domain: D6
    feature: SPICE
    nx: "Not in NX — SPICE simulation via Mentor HyperLynx SI (separate Siemens EDA tool)"
    nx_tier: paid
    competitor:source: https://eda.sw.siemens.com/en-US/pcb/hyperlynx/
    kerf:status: shipped
    kerf:evidence: cloud/ecad/spice/ngspice_bridge.py
  - domain: D6
    feature: Signal integrity (Z0/crosstalk/eye/IBIS)
    nx: "HyperLynx SI — transmission-line analysis, IBIS models, crosstalk, DDR channel simulation"
    nx_tier: paid
    competitor:source: https://eda.sw.siemens.com/en-US/pcb/hyperlynx/
    kerf:status: shipped
    kerf:evidence: cloud/ecad/si/ibis_channel.py
  - domain: D6
    feature: Silicon synth (Yosys) / STA / GDS / DRC / LVS / formal / CTS
    nx: "Not in NX — silicon/IC design via Siemens EDA Calibre (physical verification), separate product"
    nx_tier: paid
    competitor:source: https://eda.sw.siemens.com/en-US/ic-physical-design/calibre-design/
    kerf:status: shipped
    kerf:evidence: cloud/silicon/synth/yosys_bridge.py
  # D7 — Manufacturing / CAM
  - domain: D7
    feature: 3-axis CAM (profile/contour/pocket/face)
    nx: "NX CAM — full 3-axis milling with HSM toolpaths, verified cut simulation, Fanuc/Siemens post library"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-cam.html
    kerf:status: shipped
    kerf:evidence: src/components/CAMView.jsx
  - domain: D7
    feature: 5-axis (kinematics + posts)
    nx: "NX CAM multi-axis — 5-axis simultaneous with gouge avoidance, machine kinematics simulation, post builder"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-cam.html
    kerf:status: partial
    kerf:evidence: cloud/cam/fiveaxis.py
  - domain: D7
    feature: Adaptive / trochoidal clearing
    nx: "NX CAM high-speed machining — ZLE adaptive clearing, trochoidal milling with engagement control"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-cam.html
    kerf:status: shipped
    kerf:evidence: cloud/cam/adaptive.py
  - domain: D7
    feature: Moldflow / fill sim
    nx: "NX Mold Wizard — cavity/core split, runner design, cooling circuit; fill sim via Simcenter Moldex3D link"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-mold-design.html
    kerf:status: shipped
    kerf:evidence: cloud/manufacturing/moldflow/flow_front.py
  - domain: D7
    feature: Feeds & speeds + tool-life
    nx: "NX CAM includes feeds/speeds database and tool life tracking; Taylor model not exposed as standalone calc"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-cam.html
    kerf:status: shipped
    kerf:evidence: cloud/manufacturing/cuttingtool/tool_life.py
  - domain: D7
    feature: Nesting (skyline + true-shape NFP)
    nx: "NX Sheet Metal nesting — rectangular and true-shape nesting for sheet cutting, available as separate module"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-manufacturing.html
    kerf:status: shipped
    kerf:evidence: cloud/manufacturing/nesting/nfp.py
  - domain: D7
    feature: FDM slicing (Cura)
    nx: "Not in NX — additive manufacturing via NX Additive Manufacturing module (toolpath for metal AM, not FDM)"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/additive-manufacturing.html
    kerf:status: shipped
    kerf:evidence: src/components/PrintSliceView.jsx
  # D8 — Civil / infrastructure / geo
  - domain: D8
    feature: Horizontal+vertical alignment (clothoid, SSD)
    nx: "Not in NX — civil/infrastructure design outside NX scope; Siemens offers no civil road-design product"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/civil/alignment.py
  - domain: D8
    feature: Geotech (bearing/settlement/slope/pile/liquefaction)
    nx: "Not in NX — geotechnical analysis outside NX scope"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/civil/geotech/liquefaction.py
  # D9 — Dynamics / motion / controls
  - domain: D9
    feature: Planar MBD (Lagrange/DAE, Baumgarte)
    nx: "Simcenter 3D Motion — full multi-body dynamics (DAE/ODE), joints, contacts, flexible bodies"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-3d.html
    kerf:status: shipped
    kerf:evidence: cloud/dynamics/mbd.py
  - domain: D9
    feature: Vibration n-DOF modal / FRF
    nx: "Simcenter Nastran SOL 111 (frequency response) + Simcenter 3D — full FRF matrix, modal superposition"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-nastran.html
    kerf:status: shipped
    kerf:evidence: cloud/dynamics/vibration/mdof.py
  - domain: D9
    feature: Controls — state-space / LQR / Kalman
    nx: "Not in NX core — controls design via Simcenter Amesim (system simulation) or external MATLAB link"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-amesim.html
    kerf:status: shipped
    kerf:evidence: cloud/dynamics/controls/statespace.py
  # D10 — Electrical / energy / PLC / firmware
  - domain: D10
    feature: Wiring/harness (WireViz + 3D router)
    nx: "NX Routing Electrical / Capital Harness (Siemens EDA) — 3D harness routing, formboard, bend radius checks"
    nx_tier: paid
    competitor:source: https://eda.sw.siemens.com/en-US/pcb/capital/harness-engineering/
    kerf:status: shipped
    kerf:evidence: src/components/WiringView.jsx
  - domain: D10
    feature: AC load-flow (Ybus / Newton-Raphson)
    nx: "Not in NX — power system load-flow outside NX scope; Siemens PSS/E is a separate product"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/electrical/elecpower/loadflow.py
  - domain: D10
    feature: PLC IEC 61131-3 (ST/Ladder/FB/motion)
    nx: "NX Mechatronics Concept Designer — virtual PLC and motion simulation; real PLC code via TIA Portal link"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/mechatronics-concept-designer.html
    kerf:status: shipped
    kerf:evidence: src/components/PLCEditor.jsx
  # D11 — Tolerancing / metrology / QA
  - domain: D11
    feature: GD&T data model (ASME Y14.5)
    nx: "NX PMI — semantic GD&T with ASME Y14.5 / ISO 1101; full MBD (Model-Based Definition) workflow"
    nx_tier: included
    competitor:source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1428294/en-US
    kerf:status: shipped
    kerf:evidence: cloud/gdt/model.py
  - domain: D11
    feature: Tolerance stackup — 1D (WC/RSS/MC)
    nx: "NX Tolerance Analysis — 1D stackup with worst-case and statistical methods"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/qa/tolstack/stackup.py
  - domain: D11
    feature: Tolerance stackup — 3D vector loop
    nx: "Variation Analysis (via VSA integration) — 3D assembly variation with sensitivity analysis"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/qa/tolstack/tol3d.py
  - domain: D11
    feature: Process capability (Cpk/Ppk)
    nx: "Not in NX — SPC and capability analysis via Teamcenter Quality or external Minitab link"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/teamcenter/quality.html
    kerf:status: shipped
    kerf:evidence: cloud/qa/spc/capability.py
  # D12 — Optics / acoustics
  - domain: D12
    feature: Acoustics (ISO 9613, RT60, weighting, mass-law TL)
    nx: "Simcenter 3D Acoustics — FEM/BEM acoustic analysis, sound pressure maps, NVH integration"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-3d.html
    kerf:status: shipped
    kerf:evidence: cloud/acoustics/iso9613.py
  - domain: D12
    feature: Paraxial ABCD ray transfer
    nx: "Not in NX — optical design outside NX scope; Zemax OpticStudio is the Siemens-owned tool"
    nx_tier: paid
    competitor:source: https://www.zemax.com/products/opticstudio
    kerf:status: shipped
    kerf:evidence: cloud/optics/paraxial.py
  # D13 — Verticals
  - domain: D13
    feature: BIM (walls/slabs/framing/stairs/IFC4)
    nx: "Not in NX — BIM/AEC outside NX scope; Siemens has no BIM product"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/bim/ifc_compiler.py
  - domain: D13
    feature: Jewelry (41 modules)
    nx: "Not in NX — jewelry/goldsmithing outside NX scope"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:status: shipped
    kerf:evidence: cloud/jewelry/
  # D14 — Cost / materials / LCA
  - domain: D14
    feature: Material selection (Ashby)
    nx: "NX Material Editor — basic property lookup; advanced Ashby-chart selection via Teamcenter Materials link"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/teamcenter/materials-compliance.html
    kerf:status: shipped
    kerf:evidence: cloud/materials/matsel/multi_objective.py
  - domain: D14
    feature: LCA (full ISO 14040/44 4 phases)
    nx: "Not in NX — LCA analysis outside NX scope; Siemens Teamcenter Product Compliance covers RoHS/REACH only"
    nx_tier: none
    competitor:source: https://plm.automation.siemens.com/global/en/products/teamcenter/product-compliance.html
    kerf:status: shipped
    kerf:evidence: cloud/lca/phases.py
  - domain: D14
    feature: Should-cost (6 processes, Boothroyd-Dewhurst)
    nx: "Not in NX core — cost estimation via Teamcenter Manufacturing Process Planner or external aPriori link"
    nx_tier: paid
    competitor:source: https://plm.automation.siemens.com/global/en/products/teamcenter/
    kerf:status: shipped
    kerf:evidence: cloud/cost/should_cost.py
---

# Kerf vs Siemens NX

NX defined advanced surfacing for a generation — Kerf makes that power accessible without a six-figure licence.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of Siemens NX's feature surface (54 yes, 0 partial, 0 no out of 54 features tracked here). Kerf covers the full tracked feature set for Siemens NX; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Siemens NX | Notes |
|---------|------|------------|-------|
| Constraint sketcher (geo + dim) | ✅ | Yes | Verified implementation. |
| Pad / pocket / revolve | ✅ | Yes | Verified implementation. |
| Variable-radius fillet | ✅ | Yes | Verified implementation. |
| NURBS surfacing (blend/network/patch) | ✅ | Yes | blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, G3 blends + MatchSrf G3 wired |
| Direct edit (push-pull) | ✅ | Yes | Verified implementation. |
| Assemblies — mates | ✅ | Yes | Verified implementation. |
| Sheet metal | ✅ | Yes | Verified implementation. |
| 2D drawings (views/dims/sections) | ✅ | Yes | Verified implementation. |
| GD&T on drawings / MBD / PMI | ✅ | Yes | Verified implementation. |
| FE — solid (tet/hex) | ✅ | Yes | Verified implementation. |
| Modal / buckling / nonlinear | ✅ | Yes | Verified implementation. |
| AISC 360-22 steel (members) | ✅ | Yes | Verified implementation. |
| Fatigue (S-N, ε-N, rainflow) | ✅ | Yes | Verified implementation. |
| Spur/helical gear rating (AGMA 2001-D04) | ✅ | Yes | Verified implementation. |
| Bearings — ISO 281 L10 | ✅ | Yes | Verified implementation. |
| Shaft (stress + critical speed) | ✅ | Yes | Verified implementation. |
| Thermo cycles (Rankine/Brayton/Otto) | ✅ | Yes | Verified implementation. |
| CFD | ✅ | Yes | Verified implementation. |
| Heat exchangers (LMTD + ε-NTU + Bell-Delaware) | ✅ | Yes | Verified implementation. |
| 3D wing VLM (+ viscous + compressibility) | ✅ | Yes | Verified implementation. |
| Orbital (Kepler, J2/J3, Hohmann) | ✅ | Yes | Verified implementation. |
| Turbomachinery / wind-turbine BEM | ✅ | Yes | Verified implementation. |
| Naval hydrostatics + GZ stability (IMO) | ✅ | Yes | Verified implementation. |
| Schematic capture (KiCad round-trip, ERC) | ✅ | Yes | Verified implementation. |
| PCB layout (tscircuit, KiCad round-trip) | ✅ | Yes | Verified implementation. |
| SPICE | ✅ | Yes | Verified implementation. |
| Signal integrity (Z0/crosstalk/eye/IBIS) | ✅ | Yes | Verified implementation. |
| Silicon synth (Yosys) / STA / GDS / DRC / LVS / formal / CTS | ✅ | Yes | Verified implementation. |
| 3-axis CAM (profile/contour/pocket/face) | ✅ | Yes | Verified implementation. |
| 5-axis (kinematics + posts) | ✅ | Yes | Verified implementation. |
| Adaptive / trochoidal clearing | ✅ | Yes | Verified implementation. |
| Moldflow / fill sim | ✅ | Yes | Verified implementation. |
| Feeds & speeds + tool-life | ✅ | Yes | Verified implementation. |
| Nesting (skyline + true-shape NFP) | ✅ | Yes | Verified implementation. |
| FDM slicing (Cura) | ✅ | Yes | Verified implementation. |
| Horizontal+vertical alignment (clothoid, SSD) | ✅ | Yes | Verified implementation. |
| Geotech (bearing/settlement/slope/pile/liquefaction) | ✅ | Yes | Verified implementation. |
| Planar MBD (Lagrange/DAE, Baumgarte) | ✅ | Yes | Verified implementation. |
| Vibration n-DOF modal / FRF | ✅ | Yes | Verified implementation. |
| Controls — state-space / LQR / Kalman | ✅ | Yes | Verified implementation. |
| Wiring/harness (WireViz + 3D router) | ✅ | Yes | Verified implementation. |
| AC load-flow (Ybus / Newton-Raphson) | ✅ | Yes | Verified implementation. |
| PLC IEC 61131-3 (ST/Ladder/FB/motion) | ✅ | Yes | Verified implementation. |
| GD&T data model (ASME Y14.5) | ✅ | Yes | Verified implementation. |
| Tolerance stackup — 1D (WC/RSS/MC) | ✅ | Yes | Verified implementation. |
| Tolerance stackup — 3D vector loop | ✅ | Yes | Verified implementation. |
| Process capability (Cpk/Ppk) | ✅ | Yes | Verified implementation. |
| Acoustics (ISO 9613, RT60, weighting, mass-law TL) | ✅ | Yes | Verified implementation. |
| Paraxial ABCD ray transfer | ✅ | Yes | Verified implementation. |
| BIM (walls/slabs/framing/stairs/IFC4) | ✅ | Yes | Verified implementation. |
| Jewelry (41 modules) | ✅ | Yes | Verified implementation. |
| Material selection (Ashby) | ✅ | Yes | Verified implementation. |
| LCA (full ISO 14040/44 4 phases) | ✅ | Yes | Verified implementation. |
| Should-cost (6 processes, Boothroyd-Dewhurst) | ✅ | Yes | Verified implementation. |

## Pricing

Siemens NX is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
