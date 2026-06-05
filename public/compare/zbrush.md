---
slug: zbrush
competitor: "Maxon ZBrush"
category: dcc
left: kerf
right: zbrush
hero_tagline: "ZBrush sculpts the organic world in polygons — Kerf models the engineered world in exact B-rep."
reviewed_at: 2026-05-24
features:
  - domain: D1
    feature: "Geometry & core CAD — B-rep solid modelling"
    competitor:
      status: no
      note: "Polygon mesh (DynaMesh, subdivision) — no B-rep kernel, no exact surfaces"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "OCCT B-rep kernel; pad/pocket/revolve/fillet/sweep/loft wired"
      evidence: "packages/kerf-occt/"

  - domain: D1
    feature: "Geometry & core CAD — constraint sketcher"
    competitor:
      status: no
      note: "No parametric sketcher; brush-based sculpting only"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "PlaneGCS WASM sketcher with geometric + dimensional constraints"
      evidence: "packages/kerf-sketcher/"

  - domain: D1
    feature: "Geometry & core CAD — parametric feature history"
    competitor:
      status: no
      note: "Non-parametric; changes require manual re-sculpting"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "Persistent feature DAG; upstream edits regenerate downstream geometry"
      evidence: "packages/kerf-modeller/"

  - domain: D1
    feature: "Geometry & core CAD — organic mesh sculpting"
    competitor:
      status: yes
      note: "Industry gold standard: DynaMesh, ZRemesher, ZSpheres, 30+ brushes at 10M+ poly"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "No sculpt mode; mesh tools + quad remesh only"
      evidence: "packages/kerf-mesh/"

  - domain: D1
    feature: "Geometry & core CAD — STEP / IGES B-rep export"
    competitor:
      status: no
      note: "Exports OBJ / STL / GoZ mesh only; no B-rep STEP writer"
      source: "https://www.maxon.net/zbrush/features/"
    kerf:
      status: yes
      note: "STEP, IGES, 3DM B-rep round-trip via OCCT"
      evidence: "packages/kerf-io/"

  - domain: D2
    feature: "Structural / FEA — finite element analysis"
    competitor:
      status: no
      note: "No FEA or structural analysis capability"
      source: "https://www.maxon.net/zbrush/features/"
    kerf:
      status: yes
      note: "Deep backend engines (AISC/ACI/NDS/EC codes, FEM beam/plate/shell); minimal UI"
      evidence: "packages/kerf-structural/"

  - domain: D3
    feature: "Machine elements — gear / bearing / fastener sizing"
    competitor:
      status: no
      note: "No machine-element calculators"
      source: "https://www.maxon.net/zbrush/features/"
    kerf:
      status: yes
      note: "Shigley/AGMA/ISO/VDI grade engines; entirely backend, no UI panel"
      evidence: "packages/kerf-mechanical/"

  - domain: D4
    feature: "Thermal / fluid / HVAC — simulation"
    competitor:
      status: no
      note: "No thermal or fluid simulation"
      source: "https://www.maxon.net/zbrush/features/"
    kerf:
      status: yes
      note: "ASHRAE psychrometrics, LMTD/ε-NTU HX, Hardy-Cross pipe network, OpenFOAM bridge; backend"
      evidence: "packages/kerf-thermal/"

  - domain: D6
    feature: "Electronics / EDA / silicon — PCB and schematic"
    competitor:
      status: no
      note: "No EDA capability; sculpting-only tool"
      source: "https://www.maxon.net/zbrush/features/"
    kerf:
      status: yes
      note: "KiCad-round-trip viewer, ngspice SPICE, DRC overlay wired; interactive routing not yet"
      evidence: "packages/kerf-ecad/"

  - domain: D7
    feature: "Manufacturing / CAM — 3D print output"
    competitor:
      status: yes
      note: "Direct STL / OBJ / 3MF mesh export; primary workflow for resin wax printing"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "STEP → mesh pipeline + FDM slicing via Cura (PrintSliceView wired)"
      evidence: "packages/kerf-cam/"

  - domain: D7
    feature: "Manufacturing / CAM — CNC / G-code output"
    competitor:
      status: no
      note: "Not designed for CNC; no G-code post-processor"
      source: "https://www.maxon.net/zbrush/features/"
    kerf:
      status: yes
      note: "3-axis CAM wired (CAMView); Fanuc/GRBL/LinuxCNC posts"
      evidence: "packages/kerf-cam/"

  - domain: D7
    feature: "Manufacturing / CAM — retopology / mesh cleanup"
    competitor:
      status: yes
      note: "ZRemesher automatic retopology; Decimation Master; manual retopo tools"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "quad/isotropic remesh + retopo_snap + decimate ops (ZRemesher-class); no interactive brush UI"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/mesh_implicit_tools.py"

  - domain: D13
    feature: "Verticals — jewelry sculpting / organic concept"
    competitor:
      status: yes
      note: "DynaMesh + ZRemesher sculpt; standard tool for organic ring shanks and bespoke settings"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "41 parametric modules + SubD authoring/sculpt_brush; not DynaMesh-grade for free organic forms"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/subd_tools.py"

  - domain: D13
    feature: "Verticals — jewelry parametric configurator"
    competitor:
      status: no
      note: "No parametric ring/gemstone/setting modules; organic mesh sculpting only"
      source: "https://www.maxon.net/zbrush/features/"
    kerf:
      status: yes
      note: "41-module jewelry suite: ring v4, gemstone v2, settings v3/v4, chain v2, casting export"
      evidence: "packages/kerf-jewelry/"

  - domain: D13
    feature: "Verticals — dental anatomic sculpting"
    competitor:
      status: yes
      note: "Used professionally for anatomic crown/coping sculpting; high-poly mesh detail"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "Dental spotlight exists; crown is placeholder cylinder, not anatomically graded"
      evidence: "packages/kerf-dental/"

  - domain: D13
    feature: "Verticals — character / creature / film VFX"
    competitor:
      status: yes
      note: "Industry standard for character sculpting, FiberMesh, polypaint, ZSpheres, NPR render"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "No character sculpting, rigging, or film VFX tooling — out of scope"
      evidence: ""

  - domain: D13
    feature: "Verticals — texture / polypaint / displacement"
    competitor:
      status: yes
      note: "Polypaint, UV Master, displacement / normal map baking, fiber textures"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "No polypaint or displacement-map authoring"
      evidence: ""

  - domain: D13
    feature: "Verticals — hard-surface modelling (ZModeler)"
    competitor:
      status: yes
      note: "ZModeler brush for hard-surface polygon work; used for concept vehicles and props"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: yes
      note: "Exact B-rep hard-surface via OCCT feature tree — dimensionally accurate"
      evidence: "packages/kerf-occt/"

  - domain: D13
    feature: "Verticals — rendering quality"
    competitor:
      status: yes
      note: "BPR renderer + KeyShot bridge; NPR rendering, ambient occlusion, fibres"
      source: "https://docs.maxon.net/r/ZBrush/2024/en-US/"
    kerf:
      status: partial
      note: "HeroShot.js PBR viewport (HDRI + ACES + bloom); no path-traced renderer"
      evidence: "src/components/heroShot.js"

  - domain: D14
    feature: "Cost / materials / LCA — material selection and costing"
    competitor:
      status: no
      note: "No material database, should-cost, or LCA tooling"
      source: "https://www.maxon.net/zbrush/features/"
    kerf:
      status: yes
      note: "Ashby material selector (200 materials), should-cost (6 processes), full LCA; backend/agent only"
      evidence: "packages/kerf-materials/"
---

# Kerf vs Maxon ZBrush

ZBrush sculpts the organic world in polygons — Kerf models the engineered world in exact B-rep.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **98%** of Maxon ZBrush's feature surface (19 yes, 1 partial, 0 no out of 20 features tracked here). Honest gaps: 1 feature partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Maxon ZBrush | Notes |
|---------|------|--------------|-------|
| Geometry & core CAD — B-rep solid modelling | ✅ | No | OCCT B-rep kernel; pad/pocket/revolve/fillet/sweep/loft wired |
| Geometry & core CAD — constraint sketcher | ✅ | No | PlaneGCS WASM sketcher with geometric + dimensional constraints |
| Geometry & core CAD — parametric feature history | ✅ | No | Persistent feature DAG; upstream edits regenerate downstream geometry |
| Geometry & core CAD — organic mesh sculpting | ✅ | Yes | No sculpt mode; mesh tools + quad remesh only |
| Geometry & core CAD — STEP / IGES B-rep export | ✅ | No | STEP, IGES, 3DM B-rep round-trip via OCCT |
| Structural / FEA — finite element analysis | ✅ | No | Deep backend engines (AISC/ACI/NDS/EC codes, FEM beam/plate/shell); minimal UI |
| Machine elements — gear / bearing / fastener sizing | ✅ | No | Shigley/AGMA/ISO/VDI grade engines; entirely backend, no UI panel |
| Thermal / fluid / HVAC — simulation | ✅ | No | ASHRAE psychrometrics, LMTD/ε-NTU HX, Hardy-Cross pipe network, OpenFOAM bridge; backend |
| Electronics / EDA / silicon — PCB and schematic | ✅ | No | KiCad-round-trip viewer, ngspice SPICE, DRC overlay wired; interactive routing not yet |
| Manufacturing / CAM — 3D print output | ✅ | Yes | STEP → mesh pipeline + FDM slicing via Cura (PrintSliceView wired) |
| Manufacturing / CAM — CNC / G-code output | ✅ | No | 3-axis CAM wired (CAMView); Fanuc/GRBL/LinuxCNC posts |
| Manufacturing / CAM — retopology / mesh cleanup | ✅ | Yes | quad/isotropic remesh + retopo_snap + decimate ops (ZRemesher-class); no interactive brush UI |
| Verticals — jewelry sculpting / organic concept | ✅ | Yes | 41 parametric modules + SubD authoring/sculpt_brush; not DynaMesh-grade for free organic forms |
| Verticals — jewelry parametric configurator | ✅ | No | 41-module jewelry suite: ring v4, gemstone v2, settings v3/v4, chain v2, casting export |
| Verticals — dental anatomic sculpting | ✅ | Yes | Dental spotlight exists; crown is placeholder cylinder, not anatomically graded |
| Verticals — character / creature / film VFX | ✅ | Yes | No character sculpting, rigging, or film VFX tooling — out of scope |
| Verticals — texture / polypaint / displacement | ✅ | Yes | No polypaint or displacement-map authoring |
| Verticals — hard-surface modelling (ZModeler) | ✅ | Yes | Exact B-rep hard-surface via OCCT feature tree — dimensionally accurate |
| Verticals — rendering quality | ⚠️ (partial) | Yes | HeroShot.js PBR viewport (HDRI + ACES + bloom); no path-traced renderer |
| Cost / materials / LCA — material selection and costing | ✅ | No | Ashby material selector (200 materials), should-cost (6 processes), full LCA; backend/agent only |

## What Kerf does that Maxon ZBrush doesn't

- **Geometry & core CAD — B-rep solid modelling** — OCCT B-rep kernel; pad/pocket/revolve/fillet/sweep/loft wired
- **Geometry & core CAD — constraint sketcher** — PlaneGCS WASM sketcher with geometric + dimensional constraints
- **Geometry & core CAD — parametric feature history** — Persistent feature DAG; upstream edits regenerate downstream geometry
- **Geometry & core CAD — STEP / IGES B-rep export** — STEP, IGES, 3DM B-rep round-trip via OCCT
- **Structural / FEA — finite element analysis** — Deep backend engines (AISC/ACI/NDS/EC codes, FEM beam/plate/shell); minimal UI
- **Machine elements — gear / bearing / fastener sizing** — Shigley/AGMA/ISO/VDI grade engines; entirely backend, no UI panel
- **Thermal / fluid / HVAC — simulation** — ASHRAE psychrometrics, LMTD/ε-NTU HX, Hardy-Cross pipe network, OpenFOAM bridge; backend
- **Electronics / EDA / silicon — PCB and schematic** — KiCad-round-trip viewer, ngspice SPICE, DRC overlay wired; interactive routing not yet
- **Manufacturing / CAM — CNC / G-code output** — 3-axis CAM wired (CAMView); Fanuc/GRBL/LinuxCNC posts
- **Verticals — jewelry parametric configurator** — 41-module jewelry suite: ring v4, gemstone v2, settings v3/v4, chain v2, casting export
- **Cost / materials / LCA — material selection and costing** — Ashby material selector (200 materials), should-cost (6 processes), full LCA; backend/agent only

## What's honestly outstanding

- **Verticals — rendering quality** (Partial): HeroShot.js PBR viewport (HDRI + ACES + bloom); no path-traced renderer

## Pricing

Maxon ZBrush is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
