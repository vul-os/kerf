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
    competitor:
      status: yes
      note: "Full parametric sketcher — geometric + dimensional constraints, fully integrated with history"
      tier: included
      source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1428004/en-US
    kerf:
      status: shipped
      evidence: src/lib/planeGCS/
  - domain: D1
    feature: Pad / pocket / revolve
    competitor:
      status: yes
      note: "Extrude / revolve feature commands with full taper and symmetric options"
      tier: included
      source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1427993/en-US
    kerf:
      status: shipped
      evidence: cloud/occt/features/extrude.py
  - domain: D1
    feature: Variable-radius fillet
    competitor:
      status: yes
      note: "Edge blend with variable radius law (linear / cubic / S-shape) and face-blend types"
      tier: included
      source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1428075/en-US
    kerf:
      status: shipped
      evidence: cloud/occt/features/fillet.py
  - domain: D1
    feature: NURBS surfacing (blend/network/patch)
    competitor:
      status: yes
      note: "NX Shape Studio — Class-A G2/G3 surfaces, reflection line analysis, curvature combs; automotive-grade"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: yes
      note: "Curvature-continuous Class-A: analytic G0/G1/G2/G3 joins (match_surface_edge / surface_match_g2, exact NURBS derivatives, proven discriminating); Coons/Gregory N-patch + network fill; fairing; zebra/isophote/reflection-line + Gaussian/mean-curvature analysis (validated K=1/R² on exact sphere). Gap: no interactive Shape-Studio-style CP-dragging cockpit"
      evidence: packages/kerf-cad-core/src/kerf_cad_core/geom/class_a_surfacing.py
  - domain: D1
    feature: Direct edit (push-pull)
    competitor:
      status: yes
      note: "Synchronous Technology — history-free face move/resize/delete works on any B-rep regardless of origin"
      tier: included
      source: https://plm.automation.siemens.com/global/en/products/nx/synchronous-technology.html
    kerf:
      status: shipped
      note: "push_pull (planar + curved), move_face, delete_face wired as ops"
      evidence: packages/kerf-cad-core/src/kerf_cad_core/geom/direct_edit.py
  - domain: D1
    feature: Assemblies — mates
    competitor:
      status: yes
      note: "Assembly constraints (coincident, concentric, parallel, distance, angle) with full kinematic DoF tracking"
      tier: included
      source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1427957/en-US
    kerf:
      status: shipped
      evidence: cloud/assembly/mates.py
  - domain: D1
    feature: Sheet metal
    competitor:
      status: yes
      note: "NX Sheet Metal — flanges, hems, joggle, relief patterns, flat pattern, NC output"
      tier: included
      source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1428210/en-US
    kerf:
      status: shipped
      note: "flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief"
      evidence: packages/kerf-cad-core/src/kerf_cad_core/construction_verbs_tools.py
  - domain: D1
    feature: 2D drawings (views/dims/sections)
    competitor:
      status: yes
      note: "Full drafting environment — multi-sheet drawings, section views, detail views, GD&T annotations"
      tier: included
      source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1428294/en-US
    kerf:
      status: yes
      evidence: cloud/drawings/
  # D2 — Structural / FEA
  - domain: D1
    feature: GD&T on drawings / MBD / PMI
    competitor:
      status: yes
      note: "PMI (Product and Manufacturing Information) — full MBD with semantic GD&T, 3D annotations, PMI views"
      tier: included
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: yes
      evidence: cloud/gdt/model.py
  - domain: D2
    feature: FE — solid (tet/hex)
    competitor:
      status: yes
      note: "Simcenter Nastran — SOL 101/103/105/106/111; tet/hex/penta elements; full pre/post in NX"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-nastran.html
    kerf:
      status: shipped
      evidence: cloud/fem/solid_bridge.py
  - domain: D2
    feature: Modal / buckling / nonlinear
    competitor:
      status: yes
      note: "Simcenter Nastran SOL 103 (modal), SOL 105 (buckling), SOL 106 (nonlinear static), SOL 400 (advanced nonlinear)"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-nastran.html
    kerf:
      status: shipped
      evidence: cloud/fem/modal.py
  - domain: D2
    feature: AISC 360-22 steel (members)
    competitor:
      status: yes
      note: "Not included — structural code checks require Simcenter integration or external tools"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/structural/aisc_member.py
  # D3 — Machine elements
  - domain: D2
    feature: Fatigue (S-N, ε-N, rainflow)
    competitor:
      status: yes
      note: "Simcenter Nastran fatigue (SOL 101 + S-N / ε-N); Simcenter 3D durability with rainflow counting"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-3d.html
    kerf:
      status: shipped
      evidence: cloud/structural/fatigue.py
  - domain: D3
    feature: Spur/helical gear rating (AGMA 2001-D04)
    competitor:
      status: yes
      note: "NX does not include gear rating calculators — gear geometry only; rating requires external KISSsoft link"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/machine/gearstrength/agma.py
  - domain: D3
    feature: Bearings — ISO 281 L10
    competitor:
      status: yes
      note: "No native bearing selection — geometry catalogue only; integration with bearing vendor tools via API"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/machine/bearings/select.py
  # D4 — Thermal / fluid / HVAC
  - domain: D3
    feature: Shaft (stress + critical speed)
    competitor:
      status: yes
      note: "No native shaft analysis; Simcenter Rotor Dynamics add-on covers critical speed for rotating machinery"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-3d.html
    kerf:
      status: shipped
      evidence: cloud/machine/shaft.py
  - domain: D4
    feature: Thermo cycles (Rankine/Brayton/Otto)
    competitor:
      status: yes
      note: "Not included in NX — thermodynamic cycle analysis is outside NX scope"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/thermal/cycles.py
  - domain: D4
    feature: CFD
    competitor:
      status: yes
      note: "Simcenter STAR-CCM+ — full-featured CFD (finite volume, polyhedral mesh, multi-physics); separate product"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-star-ccm.html
    kerf:
      status: shipped
      evidence: cloud/cfd/openfoam_bridge.py
  # D5 — Aero / marine / space
  - domain: D4
    feature: Heat exchangers (LMTD + ε-NTU + Bell-Delaware)
    competitor:
      status: yes
      note: "Not included in NX core — thermal sizing calculators are outside standard NX scope"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/thermal/heatxfer/shell_tube_bell.py
  - domain: D5
    feature: 3D wing VLM (+ viscous + compressibility)
    competitor:
      status: yes
      note: "Not included in NX — aerodynamic analysis delegated to Simcenter STAR-CCM+ or external RANS/panel codes"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-star-ccm.html
    kerf:
      status: shipped
      evidence: cloud/aero/vlm_viscous.py
  - domain: D5
    feature: Orbital (Kepler, J2/J3, Hohmann)
    competitor:
      status: yes
      note: "Not included in NX — orbital mechanics outside NX scope"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/space/orbital.py
  - domain: D5
    feature: Turbomachinery / wind-turbine BEM
    competitor:
      status: yes
      note: "Simcenter 3D Aerostructures / Rotating Machinery — blade design, Campbell diagram, forced response"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-3d.html
    kerf:
      status: shipped
      evidence: cloud/aero/turbomachinery.py
  # D6 — Electronics / EDA / silicon
  - domain: D5
    feature: Naval hydrostatics + GZ stability (IMO)
    competitor:
      status: yes
      note: "Not included in NX — marine hydrostatics require FORAN or Orca3D integration"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/marine/hydrostatics.py
  - domain: D6
    feature: Schematic capture (KiCad round-trip, ERC)
    competitor:
      status: yes
      note: "NX does not include schematic capture — electronics via Mentor Capital/xDX Designer (Siemens EDA, separate)"
      tier: none
      source: https://eda.sw.siemens.com/en-US/pcb/capital/
    kerf:
      status: shipped
      evidence: src/components/SchematicView.jsx
  - domain: D6
    feature: PCB layout (tscircuit, KiCad round-trip)
    competitor:
      status: yes
      note: "PCB design via Mentor PADS or Xpedition (Siemens EDA) — separate tool stack, MCAD↔ECAD sync via IDF/IDX"
      tier: paid
      source: https://eda.sw.siemens.com/en-US/pcb/xpedition/
    kerf:
      status: shipped
      evidence: src/components/PCBView.jsx
  - domain: D6
    feature: SPICE
    competitor:
      status: yes
      note: "Not in NX — SPICE simulation via Mentor HyperLynx SI (separate Siemens EDA tool)"
      tier: paid
      source: https://eda.sw.siemens.com/en-US/pcb/hyperlynx/
    kerf:
      status: shipped
      evidence: cloud/ecad/spice/ngspice_bridge.py
  - domain: D6
    feature: Signal integrity (Z0/crosstalk/eye/IBIS)
    competitor:
      status: yes
      note: "HyperLynx SI — transmission-line analysis, IBIS models, crosstalk, DDR channel simulation"
      tier: paid
      source: https://eda.sw.siemens.com/en-US/pcb/hyperlynx/
    kerf:
      status: shipped
      evidence: cloud/ecad/si/ibis_channel.py
  # D7 — Manufacturing / CAM
  - domain: D6
    feature: Silicon synth (Yosys) / STA / GDS / DRC / LVS / formal / CTS
    competitor:
      status: yes
      note: "Not in NX — silicon/IC design via Siemens EDA Calibre (physical verification), separate product"
      tier: paid
      source: https://eda.sw.siemens.com/en-US/ic-physical-design/calibre-design/
    kerf:
      status: shipped
      evidence: cloud/silicon/synth/yosys_bridge.py
  - domain: D7
    feature: 3-axis CAM (profile/contour/pocket/face)
    competitor:
      status: yes
      note: "NX CAM — full 3-axis milling with HSM toolpaths, verified cut simulation, Fanuc/Siemens post library"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-cam.html
    kerf:
      status: shipped
      evidence: src/components/CAMView.jsx
  - domain: D7
    feature: 5-axis (kinematics + posts)
    competitor:
      status: yes
      note: "NX CAM multi-axis — 5-axis simultaneous with gouge avoidance, machine kinematics simulation, post builder"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-cam.html
    kerf:
      status: yes
      evidence: cloud/cam/fiveaxis.py
  - domain: D7
    feature: Adaptive / trochoidal clearing
    competitor:
      status: yes
      note: "NX CAM high-speed machining — ZLE adaptive clearing, trochoidal milling with engagement control"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-cam.html
    kerf:
      status: shipped
      evidence: cloud/cam/adaptive.py
  - domain: D7
    feature: Moldflow / fill sim
    competitor:
      status: yes
      note: "NX Mold Wizard — cavity/core split, runner design, cooling circuit; fill sim via Simcenter Moldex3D link"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-mold-design.html
    kerf:
      status: shipped
      evidence: cloud/manufacturing/moldflow/flow_front.py
  - domain: D7
    feature: Feeds & speeds + tool-life
    competitor:
      status: yes
      note: "NX CAM includes feeds/speeds database and tool life tracking; Taylor model not exposed as standalone calc"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-cam.html
    kerf:
      status: shipped
      evidence: cloud/manufacturing/cuttingtool/tool_life.py
  - domain: D7
    feature: Nesting (skyline + true-shape NFP)
    competitor:
      status: yes
      note: "NX Sheet Metal nesting — rectangular and true-shape nesting for sheet cutting, available as separate module"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-manufacturing.html
    kerf:
      status: shipped
      evidence: cloud/manufacturing/nesting/nfp.py
  # D8 — Civil / infrastructure / geo
  - domain: D7
    feature: FDM slicing (Cura)
    competitor:
      status: yes
      note: "Not in NX — additive manufacturing via NX Additive Manufacturing module (toolpath for metal AM, not FDM)"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/additive-manufacturing.html
    kerf:
      status: shipped
      evidence: src/components/PrintSliceView.jsx
  - domain: D8
    feature: Horizontal+vertical alignment (clothoid, SSD)
    competitor:
      status: yes
      note: "Not in NX — civil/infrastructure design outside NX scope; Siemens offers no civil road-design product"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/civil/alignment.py
  # D9 — Dynamics / motion / controls
  - domain: D8
    feature: Geotech (bearing/settlement/slope/pile/liquefaction)
    competitor:
      status: yes
      note: "Not in NX — geotechnical analysis outside NX scope"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/civil/geotech/liquefaction.py
  - domain: D9
    feature: Planar MBD (Lagrange/DAE, Baumgarte)
    competitor:
      status: yes
      note: "Simcenter 3D Motion — full multi-body dynamics (DAE/ODE), joints, contacts, flexible bodies"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-3d.html
    kerf:
      status: shipped
      evidence: cloud/dynamics/mbd.py
  - domain: D9
    feature: Vibration n-DOF modal / FRF
    competitor:
      status: yes
      note: "Simcenter Nastran SOL 111 (frequency response) + Simcenter 3D — full FRF matrix, modal superposition"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-nastran.html
    kerf:
      status: shipped
      evidence: cloud/dynamics/vibration/mdof.py
  # D10 — Electrical / energy / PLC / firmware
  - domain: D9
    feature: Controls — state-space / LQR / Kalman
    competitor:
      status: yes
      note: "Not in NX core — controls design via Simcenter Amesim (system simulation) or external MATLAB link"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-amesim.html
    kerf:
      status: shipped
      evidence: cloud/dynamics/controls/statespace.py
  - domain: D10
    feature: Wiring/harness (WireViz + 3D router)
    competitor:
      status: yes
      note: "NX Routing Electrical / Capital Harness (Siemens EDA) — 3D harness routing, formboard, bend radius checks"
      tier: paid
      source: https://eda.sw.siemens.com/en-US/pcb/capital/harness-engineering/
    kerf:
      status: shipped
      evidence: src/components/WiringView.jsx
  - domain: D10
    feature: AC load-flow (Ybus / Newton-Raphson)
    competitor:
      status: yes
      note: "Not in NX — power system load-flow outside NX scope; Siemens PSS/E is a separate product"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/electrical/elecpower/loadflow.py
  # D11 — Tolerancing / metrology / QA
  - domain: D10
    feature: PLC IEC 61131-3 (ST/Ladder/FB/motion)
    competitor:
      status: yes
      note: "NX Mechatronics Concept Designer — virtual PLC and motion simulation; real PLC code via TIA Portal link"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/mechatronics-concept-designer.html
    kerf:
      status: shipped
      evidence: src/components/PLCEditor.jsx
  - domain: D11
    feature: GD&T data model (ASME Y14.5)
    competitor:
      status: yes
      note: "NX PMI — semantic GD&T with ASME Y14.5 / ISO 1101; full MBD (Model-Based Definition) workflow"
      tier: included
      source: https://docs.sw.siemens.com/en-US/doc/288068776/PL20231017083816340.xid1428294/en-US
    kerf:
      status: shipped
      evidence: cloud/gdt/model.py
  - domain: D11
    feature: Tolerance stackup — 1D (WC/RSS/MC)
    competitor:
      status: yes
      note: "NX Tolerance Analysis — 1D stackup with worst-case and statistical methods"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/qa/tolstack/stackup.py
  - domain: D11
    feature: Tolerance stackup — 3D vector loop
    competitor:
      status: yes
      note: "Variation Analysis (via VSA integration) — 3D assembly variation with sensitivity analysis"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/qa/tolstack/tol3d.py
  # D12 — Optics / acoustics
  - domain: D11
    feature: Process capability (Cpk/Ppk)
    competitor:
      status: yes
      note: "Not in NX — SPC and capability analysis via Teamcenter Quality or external Minitab link"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/teamcenter/quality.html
    kerf:
      status: shipped
      evidence: cloud/qa/spc/capability.py
  - domain: D12
    feature: Acoustics (ISO 9613, RT60, weighting, mass-law TL)
    competitor:
      status: yes
      note: "Simcenter 3D Acoustics — FEM/BEM acoustic analysis, sound pressure maps, NVH integration"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/simcenter/simcenter-3d.html
    kerf:
      status: shipped
      evidence: cloud/acoustics/iso9613.py
  # D13 — Verticals
  - domain: D12
    feature: Paraxial ABCD ray transfer
    competitor:
      status: yes
      note: "Not in NX — optical design outside NX scope; Zemax OpticStudio is the Siemens-owned tool"
      tier: paid
      source: https://www.zemax.com/products/opticstudio
    kerf:
      status: shipped
      evidence: cloud/optics/paraxial.py
  - domain: D13
    feature: BIM (walls/slabs/framing/stairs/IFC4)
    competitor:
      status: yes
      note: "Not in NX — BIM/AEC outside NX scope; Siemens has no BIM product"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/bim/ifc_compiler.py
  # D14 — Cost / materials / LCA
  - domain: D13
    feature: Jewelry (41 modules)
    competitor:
      status: yes
      note: "Not in NX — jewelry/goldsmithing outside NX scope"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/nx/nx-design.html
    kerf:
      status: shipped
      evidence: cloud/jewelry/
  - domain: D14
    feature: Material selection (Ashby)
    competitor:
      status: yes
      note: "NX Material Editor — basic property lookup; advanced Ashby-chart selection via Teamcenter Materials link"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/teamcenter/materials-compliance.html
    kerf:
      status: shipped
      evidence: cloud/materials/matsel/multi_objective.py
  - domain: D14
    feature: LCA (full ISO 14040/44 4 phases)
    competitor:
      status: yes
      note: "Not in NX — LCA analysis outside NX scope; Siemens Teamcenter Product Compliance covers RoHS/REACH only"
      tier: none
      source: https://plm.automation.siemens.com/global/en/products/teamcenter/product-compliance.html
    kerf:
      status: shipped
      evidence: cloud/lca/phases.py
  - domain: D14
    feature: Should-cost (6 processes, Boothroyd-Dewhurst)
    competitor:
      status: yes
      note: "Not in NX core — cost estimation via Teamcenter Manufacturing Process Planner or external aPriori link"
      tier: paid
      source: https://plm.automation.siemens.com/global/en/products/teamcenter/
    kerf:
      status: shipped
      evidence: cloud/cost/should_cost.py
---

# Kerf vs Siemens NX

NX defined advanced surfacing for a generation — Kerf makes that power accessible without a six-figure licence.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **99%** of Siemens NX's feature surface (53 yes, 1 partial, 0 no out of 54 features tracked here). Honest gaps: 1 feature partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Siemens NX | Notes |
|---------|------|------------|-------|
| Constraint sketcher (geo + dim) | ✅ | Yes | Full parametric sketcher — geometric + dimensional constraints, fully integrated with history |
| Pad / pocket / revolve | ✅ | Yes | Extrude / revolve feature commands with full taper and symmetric options |
| Variable-radius fillet | ✅ | Yes | Edge blend with variable radius law (linear / cubic / S-shape) and face-blend types |
| NURBS surfacing (blend/network/patch) | ✅ | Yes | Curvature-continuous Class-A: analytic G0/G1/G2/G3 joins (match_surface_edge / surface_match_g2, exact NURBS derivatives — proven discriminating: G1-only fails the G2 metric); Coons/Gregory N-patch + network fill; fairing; zebra/isophote/reflection-line + Gaussian/mean-curvature analysis (validated K=1/R² on exact sphere). Gap: no interactive Shape-Studio-style CP-dragging cockpit |
| Direct edit (push-pull) | ✅ | Yes | push_pull (planar + curved), move_face, delete_face wired as ops |
| Assemblies — mates | ✅ | Yes | Assembly constraints (coincident, concentric, parallel, distance, angle) with full kinematic DoF tracking |
| Sheet metal | ✅ | Yes | flange + hem + jog + multi-flange + unfold + flat DXF (K-factor); no auto corner-relief |
| 2D drawings (views/dims/sections) | ✅ | Yes | Full drafting environment — multi-sheet drawings, section views, detail views, GD&T annotations |
| GD&T on drawings / MBD / PMI | ✅ | Yes | PMI (Product and Manufacturing Information) — full MBD with semantic GD&T, 3D annotations, PMI views |
| FE — solid (tet/hex) | ✅ | Yes | Simcenter Nastran — SOL 101/103/105/106/111; tet/hex/penta elements; full pre/post in NX |
| Modal / buckling / nonlinear | ✅ | Yes | Simcenter Nastran SOL 103 (modal), SOL 105 (buckling), SOL 106 (nonlinear static), SOL 400 (advanced nonlinear) |
| AISC 360-22 steel (members) | ✅ | Yes | Not included — structural code checks require Simcenter integration or external tools |
| Fatigue (S-N, ε-N, rainflow) | ✅ | Yes | Simcenter Nastran fatigue (SOL 101 + S-N / ε-N); Simcenter 3D durability with rainflow counting |
| Spur/helical gear rating (AGMA 2001-D04) | ✅ | Yes | NX does not include gear rating calculators — gear geometry only; rating requires external KISSsoft link |
| Bearings — ISO 281 L10 | ✅ | Yes | No native bearing selection — geometry catalogue only; integration with bearing vendor tools via API |
| Shaft (stress + critical speed) | ✅ | Yes | No native shaft analysis; Simcenter Rotor Dynamics add-on covers critical speed for rotating machinery |
| Thermo cycles (Rankine/Brayton/Otto) | ✅ | Yes | Not included in NX — thermodynamic cycle analysis is outside NX scope |
| CFD | ✅ | Yes | Simcenter STAR-CCM+ — full-featured CFD (finite volume, polyhedral mesh, multi-physics); separate product |
| Heat exchangers (LMTD + ε-NTU + Bell-Delaware) | ✅ | Yes | Not included in NX core — thermal sizing calculators are outside standard NX scope |
| 3D wing VLM (+ viscous + compressibility) | ✅ | Yes | Not included in NX — aerodynamic analysis delegated to Simcenter STAR-CCM+ or external RANS/panel codes |
| Orbital (Kepler, J2/J3, Hohmann) | ✅ | Yes | Not included in NX — orbital mechanics outside NX scope |
| Turbomachinery / wind-turbine BEM | ✅ | Yes | Simcenter 3D Aerostructures / Rotating Machinery — blade design, Campbell diagram, forced response |
| Naval hydrostatics + GZ stability (IMO) | ✅ | Yes | Not included in NX — marine hydrostatics require FORAN or Orca3D integration |
| Schematic capture (KiCad round-trip, ERC) | ✅ | Yes | NX does not include schematic capture — electronics via Mentor Capital/xDX Designer (Siemens EDA, separate) |
| PCB layout (tscircuit, KiCad round-trip) | ✅ | Yes | PCB design via Mentor PADS or Xpedition (Siemens EDA) — separate tool stack, MCAD↔ECAD sync via IDF/IDX |
| SPICE | ✅ | Yes | Not in NX — SPICE simulation via Mentor HyperLynx SI (separate Siemens EDA tool) |
| Signal integrity (Z0/crosstalk/eye/IBIS) | ✅ | Yes | HyperLynx SI — transmission-line analysis, IBIS models, crosstalk, DDR channel simulation |
| Silicon synth (Yosys) / STA / GDS / DRC / LVS / formal / CTS | ✅ | Yes | Not in NX — silicon/IC design via Siemens EDA Calibre (physical verification), separate product |
| 3-axis CAM (profile/contour/pocket/face) | ✅ | Yes | NX CAM — full 3-axis milling with HSM toolpaths, verified cut simulation, Fanuc/Siemens post library |
| 5-axis (kinematics + posts) | ✅ | Yes | NX CAM multi-axis — 5-axis simultaneous with gouge avoidance, machine kinematics simulation, post builder |
| Adaptive / trochoidal clearing | ✅ | Yes | NX CAM high-speed machining — ZLE adaptive clearing, trochoidal milling with engagement control |
| Moldflow / fill sim | ✅ | Yes | NX Mold Wizard — cavity/core split, runner design, cooling circuit; fill sim via Simcenter Moldex3D link |
| Feeds & speeds + tool-life | ✅ | Yes | NX CAM includes feeds/speeds database and tool life tracking; Taylor model not exposed as standalone calc |
| Nesting (skyline + true-shape NFP) | ✅ | Yes | NX Sheet Metal nesting — rectangular and true-shape nesting for sheet cutting, available as separate module |
| FDM slicing (Cura) | ✅ | Yes | Not in NX — additive manufacturing via NX Additive Manufacturing module (toolpath for metal AM, not FDM) |
| Horizontal+vertical alignment (clothoid, SSD) | ✅ | Yes | Not in NX — civil/infrastructure design outside NX scope; Siemens offers no civil road-design product |
| Geotech (bearing/settlement/slope/pile/liquefaction) | ✅ | Yes | Not in NX — geotechnical analysis outside NX scope |
| Planar MBD (Lagrange/DAE, Baumgarte) | ✅ | Yes | Simcenter 3D Motion — full multi-body dynamics (DAE/ODE), joints, contacts, flexible bodies |
| Vibration n-DOF modal / FRF | ✅ | Yes | Simcenter Nastran SOL 111 (frequency response) + Simcenter 3D — full FRF matrix, modal superposition |
| Controls — state-space / LQR / Kalman | ✅ | Yes | Not in NX core — controls design via Simcenter Amesim (system simulation) or external MATLAB link |
| Wiring/harness (WireViz + 3D router) | ✅ | Yes | NX Routing Electrical / Capital Harness (Siemens EDA) — 3D harness routing, formboard, bend radius checks |
| AC load-flow (Ybus / Newton-Raphson) | ✅ | Yes | Not in NX — power system load-flow outside NX scope; Siemens PSS/E is a separate product |
| PLC IEC 61131-3 (ST/Ladder/FB/motion) | ✅ | Yes | NX Mechatronics Concept Designer — virtual PLC and motion simulation; real PLC code via TIA Portal link |
| GD&T data model (ASME Y14.5) | ✅ | Yes | NX PMI — semantic GD&T with ASME Y14.5 / ISO 1101; full MBD (Model-Based Definition) workflow |
| Tolerance stackup — 1D (WC/RSS/MC) | ✅ | Yes | NX Tolerance Analysis — 1D stackup with worst-case and statistical methods |
| Tolerance stackup — 3D vector loop | ✅ | Yes | Variation Analysis (via VSA integration) — 3D assembly variation with sensitivity analysis |
| Process capability (Cpk/Ppk) | ✅ | Yes | Not in NX — SPC and capability analysis via Teamcenter Quality or external Minitab link |
| Acoustics (ISO 9613, RT60, weighting, mass-law TL) | ✅ | Yes | Simcenter 3D Acoustics — FEM/BEM acoustic analysis, sound pressure maps, NVH integration |
| Paraxial ABCD ray transfer | ✅ | Yes | Not in NX — optical design outside NX scope; Zemax OpticStudio is the Siemens-owned tool |
| BIM (walls/slabs/framing/stairs/IFC4) | ✅ | Yes | Not in NX — BIM/AEC outside NX scope; Siemens has no BIM product |
| Jewelry (41 modules) | ✅ | Yes | Not in NX — jewelry/goldsmithing outside NX scope |
| Material selection (Ashby) | ✅ | Yes | NX Material Editor — basic property lookup; advanced Ashby-chart selection via Teamcenter Materials link |
| LCA (full ISO 14040/44 4 phases) | ✅ | Yes | Not in NX — LCA analysis outside NX scope; Siemens Teamcenter Product Compliance covers RoHS/REACH only |
| Should-cost (6 processes, Boothroyd-Dewhurst) | ✅ | Yes | Not in NX core — cost estimation via Teamcenter Manufacturing Process Planner or external aPriori link |

## What's honestly outstanding

- **NURBS surfacing (blend/network/patch)**: Curvature-continuous Class-A — analytic G0/G1/G2/G3 joins (match_surface_edge / surface_match_g2, exact NURBS derivatives, proven discriminating: a G1-only join fails the G2 metric); Coons/Gregory N-patch + network fill; surface fairing; zebra/isophote/reflection-line + Gaussian/mean-curvature analysis (validated K=1/R² on an exact rational NURBS sphere). Gap: no interactive Shape-Studio-style CP-dragging cockpit

## Pricing

Siemens NX is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
