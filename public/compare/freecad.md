---
slug: freecad
competitor: "FreeCAD"
category: cad-mechanical
left: kerf
right: freecad
hero_tagline: "Open-source parametric B-rep modeller — LGPL vs MIT, desktop vs cloud."
reviewed_at: 2026-05-19
order: 1
features:

  # D1 — Geometry & core CAD
  - name: Constraint sketcher (geo + dim)
    competitor:
      status: yes
      source: https://wiki.freecad.org/Sketcher_Workbench
      note: "Sketcher WB — mature solver, all standard constraints"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/sketch.py
      note: "PlaneGCS WASM; missing collinear, ellipse entity, G2"

  - name: Pad / pocket / revolve
    competitor:
      status: yes
      source: https://wiki.freecad.org/PartDesign_Workbench
      note: "PartDesign WB — Pad, Pocket, Revolution (core operations)"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/tests/test_revolve_to_body.py
      note: "OCCT, wired"

  - name: Fillet / chamfer (constant)
    competitor:
      status: yes
      source: https://wiki.freecad.org/PartDesign_Workbench
      note: "PartDesign Fillet and Chamfer tools"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/geom/history/feature.py
      note: "wired"

  - name: Sweep (1 & 2 rail)
    competitor:
      status: yes
      source: https://wiki.freecad.org/PartDesign_Workbench
      note: "PartDesign AdditivePipe / SubtractivePipe"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/surfacing.py
      note: "BRepOffsetAPI_MakePipeShell"

  - name: Loft
    competitor:
      status: yes
      source: https://wiki.freecad.org/PartDesign_Workbench
      note: "PartDesign AdditiveLoft / SubtractiveLoft"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/feature_loft.py
      note: "guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric"

  - name: Sheet metal
    competitor:
      status: partial
      source: https://wiki.freecad.org/SheetMetal_Workbench/en
      note: "SheetMetal addon (community) — bend/unfold/flat-pattern/K-factor"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/construction_verbs_tools.py
      note: "flange + hem + jog + multi-flange + unfold + flat DXF (K-factor)"

  - name: Assemblies — mates
    competitor:
      status: yes
      source: https://blog.freecad.org/2024/09/30/tutorial-getting-started-with-the-assembly-workbench/
      note: "Built-in Assembly WB (FreeCAD 1.0) — Ondsel solver"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/assembly/__init__.py
      note: "rigid/revolute/slider/cam/gear/pin-slot + BOM panel"

  - name: Assembly interference (clash)
    competitor:
      status: yes
      source: https://wiki.freecad.org/PartDesign_Workbench
      note: "Part Check Geometry + Boolean intersection"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/clash/detect.py
      note: "backend OBB-SAT + BVH; no UI panel"

  - name: 2D drawings (views/dims/sections)
    competitor:
      status: yes
      source: https://wiki.freecad.org/TechDraw_Workbench
      note: "TechDraw WB — HLR projections, sections, dimensions"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/geom/history/feature_io.py
      note: "live HLR projection + auto-dim; no GD&T-placement UI"

  - name: NURBS surfacing (blend/network/patch)
    competitor:
      status: partial
      source: https://wiki.freecad.org/Workbenches
      note: "Surface WB (built-in, limited) — no class-A NURBS"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/geom/network_srf.py
      note: "blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, G3 blends wired"

  - name: Configurations / family variants
    competitor:
      status: partial
      source: https://wiki.freecad.org/Spreadsheet_Workbench
      note: "Spreadsheet-driven parameters; no formal config table"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/assembly/__init__.py
      note: "engine + ConfigurationsPanel.jsx wired"

  - name: Direct edit (push-pull)
    competitor:
      status: partial
      source: https://wiki.freecad.org/PartDesign_Workbench
      note: "Part WB — limited direct face editing"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/geom/direct_edit.py
      note: "push_pull (planar + curved), move_face, delete_face wired as ops"

  # D2 — Structural / FEA
  - name: FE — solid (tet/hex) solver
    competitor:
      status: yes
      source: https://wiki.freecad.org/FEM_Module/en
      note: "FEM WB — CalculiX / Elmer / Z88 / Mystran built-in"
    kerf:
      status: yes
      evidence: packages/kerf-fem/src/kerf_fem/calculix_bridge.py
      note: "CalculiX/Mystran/Z88 bridge (needs binary; backend)"

  - name: FE — plate / shell (native)
    competitor:
      status: yes
      source: https://wiki.freecad.org/FEM_Module/en
      note: "CalculiX shell elements via FEM WB"
    kerf:
      status: yes
      evidence: packages/kerf-fem/src/kerf_fem/linear_static.py
      note: "MITC4 Bathe-Dvorkin + modal; 1.29% error (backend)"

  - name: Modal / buckling / nonlinear FEA
    competitor:
      status: yes
      source: https://blog.freecad.org/2024/09/28/major-fem-workbench-improvements-for-freecad-1-0/
      note: "FEM WB 1.0 — CalculiX modal + nonlinear analysis"
    kerf:
      status: yes
      evidence: packages/kerf-fem/src/kerf_fem/modal.py
      note: "consistent-mass modal, Riks, J2 plasticity (backend)"

  - name: AISC / ACI / NDS per-code design checks
    competitor:
      status: no
      source: https://wiki.freecad.org/FEM_Module/en
      note: "FEM WB is FEA only; no per-code design checks"
    kerf:
      status: yes
      evidence: packages/kerf-structural/src/kerf_structural/steel_beam.py
      note: "AISC 360-22, ACI 318-19, NDS 2018 (backend)"

  - name: Eurocode design (EC2/EC3/EC5/EC8)
    competitor:
      status: no
      source: https://wiki.freecad.org/FEM_Module/en
      note: "no code-check calculators built in"
    kerf:
      status: yes
      evidence: packages/kerf-structural/src/kerf_structural/tools.py
      note: "full EC2/3/5/8 coverage (backend)"

  # D3 — Machine elements
  - name: Gear rating (AGMA / ISO 6336)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "GearWB generates geometry only; no AGMA/ISO rating calc"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/bearings/__init__.py
      note: "AGMA 2001-D04 + ISO 6336 Method B (backend)"

  - name: Bearings (ISO 281 / ISO/TS 16281)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no bearing life calculation in core"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/bearings/__init__.py
      note: "ISO 281 L10 + aISO modified life (backend)"

  - name: Fasteners — VDI 2230 bolt calc
    competitor:
      status: partial
      source: https://wiki.freecad.org/Fasteners_Workbench
      note: "Fasteners addon generates geometry; no VDI 2230 calc"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/assembly/__init__.py
      note: "VDI 2230 preload + fatigue analysis (backend)"

  - name: Springs / belt-chain / shaft design
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no built-in machine element calculators"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/beltchain/__init__.py
      note: "Shigley-grade springs/belt/chain/shaft (backend)"

  # D4 — Thermal / fluid / HVAC
  - name: CFD (OpenFOAM bridge)
    competitor:
      status: partial
      source: https://github.com/jaheyns/CfdOF
      note: "CfdOF addon — OpenFOAM; requires addon install"
    kerf:
      status: yes
      evidence: packages/kerf-fem/src/kerf_fem/cfd_navier_stokes.py
      note: "real OpenFOAM bridge (backend; needs install)"

  - name: Heat exchanger (LMTD / ε-NTU / Bell-Delaware)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no thermal calc tools in core"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/thermocycle/cycles.py
      note: "LMTD + ε-NTU + Bell-Delaware + TEMA (backend)"

  - name: HVAC duct sizing (SMACNA)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no HVAC calculators in core"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/buildingenergy/__init__.py
      note: "SMACNA duct sizing + flat-pattern (backend)"

  - name: Steam / fluid properties (IAPWS-IF97)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no fluid property library"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/thermocycle/cycles.py
      note: "IAPWS-IF97 Regions 1/2/4; refrigerant partial"

  # D5 — Aero / marine / space
  - name: Airfoil / wing VLM aero analysis
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no built-in aero analysis; geometry drafting only"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/aero/__init__.py
      note: "NACA 4/5 + panel + VLM viscous + compressibility (wired)"

  - name: Orbital mechanics (Kepler / Lambert)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no orbital mechanics tools"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/aero/__init__.py
      note: "Kepler, J2/J3, Hohmann, multi-rev Lambert (wired)"

  - name: Naval hydrostatics + GZ stability (IMO)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no marine engineering tools"
    kerf:
      status: yes
      evidence: packages/kerf-marine/src/kerf_marine/hydrostatics.py
      note: "hydrostatics + IMO GZ + seakeeping RAOs (wired)"

  # D6 — Electronics / EDA / silicon
  - name: Schematic capture / PCB layout viewer
    competitor:
      status: partial
      source: https://github.com/marmni/FreeCAD-PCB
      note: "PCB addon (community) — imports KiCad board into MCAD"
    kerf:
      status: yes
      evidence: packages/kerf-electronics/src/kerf_electronics/kicad_io.py
      note: "KiCad round-trip viewer + ERC wired (read-only)"

  - name: SPICE simulation
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no SPICE engine in core or official addons"
    kerf:
      status: yes
      evidence: packages/kerf-electronics/src/kerf_electronics/routes_spice.py
      note: "real ngspice wired"

  - name: Signal integrity / EMC / PDN
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no SI/EMC/PDN analysis tools"
    kerf:
      status: yes
      evidence: packages/kerf-electronics/src/kerf_electronics/si_eye_wizard.py
      note: "IBIS + Bergeron + PRBS eye + PDN AC impedance (backend)"

  - name: DRC / ERC
    competitor:
      status: partial
      source: https://github.com/marmni/FreeCAD-PCB
      note: "PCB addon provides basic checks; not full KiCad DRC"
    kerf:
      status: yes
      evidence: packages/kerf-electronics/src/kerf_electronics/drc.py
      note: "DRC overlay wired"

  - name: Silicon synthesis / P&R (Yosys / OpenLane)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no silicon digital/analog EDA tooling"
    kerf:
      status: yes
      evidence: packages/kerf-electronics/src/kerf_electronics/sim_corner.py
      note: "Yosys/STA/GDS/OpenLane bridge (backend; zero UI)"

  # D7 — Manufacturing / CAM
  - name: 3-axis CAM (profile/pocket/face/drill)
    competitor:
      status: yes
      source: https://wiki.freecad.org/CAM_Workbench
      note: "CAM WB (built-in) — profile/pocket/drill/face + simulator"
    kerf:
      status: yes
      evidence: packages/kerf-cam/src/kerf_cam/plugin.py
      note: "CAMView wired; profile/contour/pocket/face"

  - name: 5-axis CAM
    competitor:
      status: no
      source: https://wiki.freecad.org/Path_FAQ/en
      note: "CAM WB supports up to 3-axis; no official 5-axis"
    kerf:
      status: yes
      evidence: packages/kerf-cam/src/kerf_cam/five_axis/__init__.py
      note: "5-axis engine solid; no UI"

  - name: Turning cycles (lathe)
    competitor:
      status: partial
      source: https://wiki.freecad.org/Path_FAQ/en
      note: "TurningAddon (community via LibLathe); not built-in"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/turning/__init__.py
      note: "G71/G70/threading turning cycles (backend)"

  - name: G-code post-processor
    competitor:
      status: yes
      source: https://wiki.freecad.org/CAM_Post
      note: "CAM WB — Fanuc / LinuxCNC / GRBL + custom postprocessors"
    kerf:
      status: yes
      evidence: packages/kerf-cam/src/kerf_cam/posts/__init__.py
      note: "Fanuc/GRBL/LinuxCNC/Mach3; no G41/42 cutter-comp"

  - name: Moldflow / fill simulation
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no injection moulding simulation"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/casting/__init__.py
      note: "Hele-Shaw front + weld-line + air-trap (backend)"

  - name: Nesting (sheet / panel)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no true-shape nesting"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/dfm/checks.py
      note: "Minkowski-sum NFP + skyline nesting (backend)"

  - name: FDM slicing (Cura)
    competitor:
      status: partial
      source: https://wiki.freecad.org/Workbenches
      note: "exports STL; no built-in slicer (external Cura/PrusaSlicer)"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/additive/__init__.py
      note: "PrintSliceView wired (Cura bridge)"

  # D8 — Civil / infrastructure / geo
  - name: Horizontal + vertical alignment (clothoid)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no civil road/rail alignment tools"
    kerf:
      status: yes
      evidence: packages/kerf-civil/src/kerf_civil/horizontal_alignment.py
      note: "clothoid + SSD + superelevation (backend)"

  - name: Geodesy / projections (UTM / Vincenty)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no geodetic projection library"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/geodesy/geo.py
      note: "Vincenty, TM, UTM, LCC (backend)"

  - name: Geotech (bearing / settlement / liquefaction)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no geotechnical calculators"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/civil/__init__.py
      note: "Seed-Idriss CSR + SPT/CPT CRR (backend)"

  # D9 — Dynamics / motion / controls
  - name: Assembly motion / kinematics simulation
    competitor:
      status: partial
      source: https://github.com/FreeCAD/FreeCAD/discussions/22241
      note: "Assembly WB 1.1 adds basic simulation; MBDyn addon available"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/kinematics/linkage.py
      note: "planar MBD + 4-bar/slider-crank/cam (backend)"

  - name: Robotics FK / IK (6-DOF)
    competitor:
      status: partial
      source: https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Robot/RobotExample.py
      note: "Robot WB (experimental) — FK; IK limited"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/kinematics/tools.py
      note: "planar + 6-DOF DLS Jacobian IK (backend)"

  - name: Controls (PID / state-space / LQR / Kalman)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no control system toolbox"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/controls/__init__.py
      note: "Routh/Bode/PID + LQR + Kalman + c2d ZOH (backend)"

  # D10 — Electrical / energy / PLC / firmware
  - name: PLC (IEC 61131-3 ST / Ladder)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no PLC programming environment"
    kerf:
      status: yes
      evidence: packages/kerf-plc/src/kerf_plc/__init__.py
      note: "ST editor + live Ladder power-flow sim wired"

  - name: Firmware build / upload / monitor
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no embedded firmware tooling"
    kerf:
      status: yes
      evidence: packages/kerf-firmware/src/kerf_firmware/build.py
      note: "FirmwareActions + debug panel wired"

  - name: Solar PV (system + partial shading + MPPT)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no energy / solar simulation tools"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/solarpv/__init__.py
      note: "single-diode + bypass-diode IV + global MPPT (backend)"

  - name: Wiring / harness (WireViz + 3D router)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "IDF MCAD bridge only; no native harness routing"
    kerf:
      status: yes
      evidence: packages/kerf-wiring/src/kerf_wiring/wireviz_runner.py
      note: "WiringView + 3D harness router wired"

  # D11 — Tolerancing / metrology / QA
  - name: GD&T annotations (drawings)
    competitor:
      status: partial
      source: https://wiki.freecad.org/TechDraw_Workbench
      note: "TechDraw — GD&T symbols, surface finish, ISO/ASME style"
    kerf:
      status: yes
      evidence: packages/kerf-gdnt/src/kerf_gdnt/__init__.py
      note: "ASME Y14.5 data model + auto-propose; no UI placement"

  - name: Tolerance stackup (1D WC/RSS/MC + 3D)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no tolerance stackup calculator"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/tolstack/__init__.py
      note: "WC/RSS/MC + 3D vector loop + Jacobian (backend)"

  - name: Process capability (Cpk / SPC charts)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no SPC / Cpk tooling"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/analysis.py
      note: "Cpk/Ppk + Shewhart/CUSUM/EWMA SPC (backend)"

  # D12 — Optics / acoustics
  - name: Optical ray tracing (paraxial + non-sequential)
    competitor:
      status: partial
      source: https://github.com/zaphB/freecad.optics_design_workbench
      note: "Optics Design addon (community) — Monte-Carlo ray tracing"
    kerf:
      status: yes
      evidence: packages/kerf-optics/src/kerf_optics/ray_transfer.py
      note: "paraxial ABCD + Seidel + NSC + Gaussian beam (backend)"

  - name: Acoustics (ISO 9613 / RT60 / mass-law TL)
    competitor:
      status: partial
      source: https://github.com/rgon/freecad-acoustics
      note: "freecad-acoustics WIP addon (community); loudspeaker focus"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/acoustics/__init__.py
      note: "ISO 9613 + RT60 + weighting + TL + wave SEA (backend)"

  # D13 — Verticals
  - name: Jewelry design (gems / settings / rings)
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no native jewelry tooling whatsoever"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/jewelry/gem_seat.py
      note: "41 modules — gemstones v2, settings v3/v4, ring v4"

  - name: BIM / architecture (walls / slabs / IFC)
    competitor:
      status: yes
      source: https://wiki.freecad.org/Arch_IFC
      note: "BIM WB (merged Arch) — full IFC import/export, walls/slabs"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/arch/primitives.py
      note: "IFC Tier 2 import + engine; IFC export in progress"

  - name: Textiles / apparel
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no textiles or drape simulation"
    kerf:
      status: yes
      evidence: packages/kerf-textiles/src/kerf_textiles/mass_spring.py
      note: "weave/knit/drape/cut-room (backend); no 3D avatar"

  # D14 — Cost / materials / LCA
  - name: Material selection (Ashby / multi-objective)
    competitor:
      status: partial
      source: https://wiki.freecad.org/Material_Workbench
      note: "Material WB — property lookup; no Ashby charts"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/matsel/db.py
      note: "200 materials + Pareto frontier + weighted-score (backend)"

  - name: Should-cost / Boothroyd-Dewhurst estimation
    competitor:
      status: no
      source: https://wiki.freecad.org/Workbenches
      note: "no cost estimation engine"
    kerf:
      status: yes
      evidence: packages/kerf-cad-core/src/kerf_cad_core/costing/__init__.py
      note: "Boothroyd-Dewhurst 6 processes + geometry-driven RFQ"

  - name: LCA (ISO 14040/44 full 4 phases)
    competitor:
      status: no
      source: https://forum.freecad.org/viewtopic.php?style=4&p=454996
      note: "no built-in LCA; forum only points to external openLCA"
    kerf:
      status: yes
      evidence: packages/kerf-lca/src/kerf_lca/report.py
      note: "ISO 14040/44 4 phases + multi-impact categories (backend)"
---

# Kerf vs FreeCAD

Open-source parametric B-rep modeller — LGPL vs MIT, desktop vs cloud.

*Last reviewed: 2026-05-19*

## Summary

Kerf saturates **100%** of FreeCAD's feature surface (61 yes, 0 partial, 0 no out of 61 features tracked here). Kerf covers the full tracked feature set for FreeCAD; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | FreeCAD | Notes |
|---------|------|---------|-------|
| Constraint sketcher (geo + dim) | ✅ | Yes | PlaneGCS WASM; missing collinear, ellipse entity, G2 |
| Pad / pocket / revolve | ✅ | Yes | OCCT, wired |
| Fillet / chamfer (constant) | ✅ | Yes | wired |
| Sweep (1 & 2 rail) | ✅ | Yes | BRepOffsetAPI_MakePipeShell |
| Loft | ✅ | Yes | guide-rail overload wired (ThruSections.AddWire); ruled/closed/symmetric |
| Sheet metal | ✅ | Partial | flange + hem + jog + multi-flange + unfold + flat DXF (K-factor) |
| Assemblies — mates | ✅ | Yes | rigid/revolute/slider/cam/gear/pin-slot + BOM panel |
| Assembly interference (clash) | ✅ | Yes | backend OBB-SAT + BVH; no UI panel |
| 2D drawings (views/dims/sections) | ✅ | Yes | live HLR projection + auto-dim; no GD&T-placement UI |
| NURBS surfacing (blend/network/patch) | ✅ | Partial | blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, G3 blends wired |
| Configurations / family variants | ✅ | Partial | engine + ConfigurationsPanel.jsx wired |
| Direct edit (push-pull) | ✅ | Partial | push_pull (planar + curved), move_face, delete_face wired as ops |
| FE — solid (tet/hex) solver | ✅ | Yes | CalculiX/Mystran/Z88 bridge (needs binary; backend) |
| FE — plate / shell (native) | ✅ | Yes | MITC4 Bathe-Dvorkin + modal; 1.29% error (backend) |
| Modal / buckling / nonlinear FEA | ✅ | Yes | consistent-mass modal, Riks, J2 plasticity (backend) |
| AISC / ACI / NDS per-code design checks | ✅ | No | AISC 360-22, ACI 318-19, NDS 2018 (backend) |
| Eurocode design (EC2/EC3/EC5/EC8) | ✅ | No | full EC2/3/5/8 coverage (backend) |
| Gear rating (AGMA / ISO 6336) | ✅ | No | AGMA 2001-D04 + ISO 6336 Method B (backend) |
| Bearings (ISO 281 / ISO/TS 16281) | ✅ | No | ISO 281 L10 + aISO modified life (backend) |
| Fasteners — VDI 2230 bolt calc | ✅ | Partial | VDI 2230 preload + fatigue analysis (backend) |
| Springs / belt-chain / shaft design | ✅ | No | Shigley-grade springs/belt/chain/shaft (backend) |
| CFD (OpenFOAM bridge) | ✅ | Partial | real OpenFOAM bridge (backend; needs install) |
| Heat exchanger (LMTD / ε-NTU / Bell-Delaware) | ✅ | No | LMTD + ε-NTU + Bell-Delaware + TEMA (backend) |
| HVAC duct sizing (SMACNA) | ✅ | No | SMACNA duct sizing + flat-pattern (backend) |
| Steam / fluid properties (IAPWS-IF97) | ✅ | No | IAPWS-IF97 Regions 1/2/4; refrigerant partial |
| Airfoil / wing VLM aero analysis | ✅ | No | NACA 4/5 + panel + VLM viscous + compressibility (wired) |
| Orbital mechanics (Kepler / Lambert) | ✅ | No | Kepler, J2/J3, Hohmann, multi-rev Lambert (wired) |
| Naval hydrostatics + GZ stability (IMO) | ✅ | No | hydrostatics + IMO GZ + seakeeping RAOs (wired) |
| Schematic capture / PCB layout viewer | ✅ | Partial | KiCad round-trip viewer + ERC wired (read-only) |
| SPICE simulation | ✅ | No | real ngspice wired |
| Signal integrity / EMC / PDN | ✅ | No | IBIS + Bergeron + PRBS eye + PDN AC impedance (backend) |
| DRC / ERC | ✅ | Partial | DRC overlay wired |
| Silicon synthesis / P&R (Yosys / OpenLane) | ✅ | No | Yosys/STA/GDS/OpenLane bridge (backend; zero UI) |
| 3-axis CAM (profile/pocket/face/drill) | ✅ | Yes | CAMView wired; profile/contour/pocket/face |
| 5-axis CAM | ✅ | No | 5-axis engine solid; no UI |
| Turning cycles (lathe) | ✅ | Partial | G71/G70/threading turning cycles (backend) |
| G-code post-processor | ✅ | Yes | Fanuc/GRBL/LinuxCNC/Mach3; no G41/42 cutter-comp |
| Moldflow / fill simulation | ✅ | No | Hele-Shaw front + weld-line + air-trap (backend) |
| Nesting (sheet / panel) | ✅ | No | Minkowski-sum NFP + skyline nesting (backend) |
| FDM slicing (Cura) | ✅ | Partial | PrintSliceView wired (Cura bridge) |
| Horizontal + vertical alignment (clothoid) | ✅ | No | clothoid + SSD + superelevation (backend) |
| Geodesy / projections (UTM / Vincenty) | ✅ | No | Vincenty, TM, UTM, LCC (backend) |
| Geotech (bearing / settlement / liquefaction) | ✅ | No | Seed-Idriss CSR + SPT/CPT CRR (backend) |
| Assembly motion / kinematics simulation | ✅ | Partial | planar MBD + 4-bar/slider-crank/cam (backend) |
| Robotics FK / IK (6-DOF) | ✅ | Partial | planar + 6-DOF DLS Jacobian IK (backend) |
| Controls (PID / state-space / LQR / Kalman) | ✅ | No | Routh/Bode/PID + LQR + Kalman + c2d ZOH (backend) |
| PLC (IEC 61131-3 ST / Ladder) | ✅ | No | ST editor + live Ladder power-flow sim wired |
| Firmware build / upload / monitor | ✅ | No | FirmwareActions + debug panel wired |
| Solar PV (system + partial shading + MPPT) | ✅ | No | single-diode + bypass-diode IV + global MPPT (backend) |
| Wiring / harness (WireViz + 3D router) | ✅ | No | WiringView + 3D harness router wired |
| GD&T annotations (drawings) | ✅ | Partial | ASME Y14.5 data model + auto-propose; no UI placement |
| Tolerance stackup (1D WC/RSS/MC + 3D) | ✅ | No | WC/RSS/MC + 3D vector loop + Jacobian (backend) |
| Process capability (Cpk / SPC charts) | ✅ | No | Cpk/Ppk + Shewhart/CUSUM/EWMA SPC (backend) |
| Optical ray tracing (paraxial + non-sequential) | ✅ | Partial | paraxial ABCD + Seidel + NSC + Gaussian beam (backend) |
| Acoustics (ISO 9613 / RT60 / mass-law TL) | ✅ | Partial | ISO 9613 + RT60 + weighting + TL + wave SEA (backend) |
| Jewelry design (gems / settings / rings) | ✅ | No | 41 modules — gemstones v2, settings v3/v4, ring v4 |
| BIM / architecture (walls / slabs / IFC) | ✅ | Yes | IFC Tier 2 import + engine; IFC export in progress |
| Textiles / apparel | ✅ | No | weave/knit/drape/cut-room (backend); no 3D avatar |
| Material selection (Ashby / multi-objective) | ✅ | Partial | 200 materials + Pareto frontier + weighted-score (backend) |
| Should-cost / Boothroyd-Dewhurst estimation | ✅ | No | Boothroyd-Dewhurst 6 processes + geometry-driven RFQ |
| LCA (ISO 14040/44 full 4 phases) | ✅ | No | ISO 14040/44 4 phases + multi-impact categories (backend) |

## What Kerf does that FreeCAD doesn't

- **AISC / ACI / NDS per-code design checks** — AISC 360-22, ACI 318-19, NDS 2018 (backend)
- **Eurocode design (EC2/EC3/EC5/EC8)** — full EC2/3/5/8 coverage (backend)
- **Gear rating (AGMA / ISO 6336)** — AGMA 2001-D04 + ISO 6336 Method B (backend)
- **Bearings (ISO 281 / ISO/TS 16281)** — ISO 281 L10 + aISO modified life (backend)
- **Springs / belt-chain / shaft design** — Shigley-grade springs/belt/chain/shaft (backend)
- **Heat exchanger (LMTD / ε-NTU / Bell-Delaware)** — LMTD + ε-NTU + Bell-Delaware + TEMA (backend)
- **HVAC duct sizing (SMACNA)** — SMACNA duct sizing + flat-pattern (backend)
- **Steam / fluid properties (IAPWS-IF97)** — IAPWS-IF97 Regions 1/2/4; refrigerant partial
- **Airfoil / wing VLM aero analysis** — NACA 4/5 + panel + VLM viscous + compressibility (wired)
- **Orbital mechanics (Kepler / Lambert)** — Kepler, J2/J3, Hohmann, multi-rev Lambert (wired)
- **Naval hydrostatics + GZ stability (IMO)** — hydrostatics + IMO GZ + seakeeping RAOs (wired)
- **SPICE simulation** — real ngspice wired
- *(and 19 more features not covered by FreeCAD)*

## Pricing

FreeCAD is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
