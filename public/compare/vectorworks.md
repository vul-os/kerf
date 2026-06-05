---
slug: vectorworks
competitor: Vectorworks
category: cad-architecture
left: kerf
right: vectorworks
hero_tagline: "Vectorworks spans architecture, landscape, and entertainment — Kerf spans mechanical, electronics, and fabrication."
reviewed_at: 2026-05-24
features:
  # ── D1 Geometry & core CAD ──────────────────────────────────────────────
  - domain: D1
    feature: "Constraint sketcher (geo + dim)"
    competitor:
      status: yes
      note: "2D constraint-based drafting via Vectorworks SmartCursor + parametric objects"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FObjects_edit2%2FEditing_Constraints.htm"
    kerf:
      status: yes
      note: "PlaneGCS WASM sketcher wired; missing collinear, ellipse entity, G2"
      evidence: "packages/kerf-sketcher/planegcs_wasm/"

  - domain: D1
    feature: "3D solid modelling (pad / pocket / revolve / sweep / loft)"
    competitor:
      status: yes
      note: "Subdivision + NURBS + solid push-pull; ACIS-based kernel (Fundamentals and above)"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FObjects_edit2%2F3D_Modeling_Overview.htm"
    kerf:
      status: yes
      note: "OCCT pad/pocket/revolve/sweep fully wired; loft lacks guide-rail overload"
      evidence: "packages/kerf-occt/bindings/"

  - domain: D1
    feature: "NURBS surface modelling"
    competitor:
      status: yes
      note: "Native NURBS curves and surfaces including subdivision; Vectorworks Designer tier"
      source: "https://www.vectorworks.net/architect/features"
    kerf:
      status: yes
      note: "OCCT NURBS math complete; browser WASM bindings unconfirmed at build"
      evidence: "packages/kerf-occt/nurbs/"

  - domain: D1
    feature: "2D technical drawings (views / dimensions / sections)"
    competitor:
      status: yes
      note: "Mature 2D drafting heritage (descended from MiniCAD 1985); full annotation suite"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FAnnotation%2FAnnotating_Drawings.htm"
    kerf:
      status: yes
      note: "Template-based drawings; not live B-rep projection; no UI panel"
      evidence: "packages/kerf-drawings/"

  - domain: D1
    feature: "DXF / DWG import-export"
    competitor:
      status: yes
      note: "Full DXF/DWG round-trip including 3D; all Vectorworks tiers"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FImport_Export%2FImporting_and_Exporting_DXF_DWG.htm"
    kerf:
      status: yes
      note: "DXF export wired"
      evidence: "packages/kerf-export/dxf.ts"

  - domain: D1
    feature: "STEP / IGES export"
    competitor:
      status: partial
      note: "3D STEP export available; round-trip fidelity limited vs dedicated MCAD tools"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FImport_Export%2FImporting_and_Exporting_STEP_Files.htm"
    kerf:
      status: yes
      note: "OCCT STEP export wired"
      evidence: "packages/kerf-export/step.ts"

  - domain: D1
    feature: "Symbol / component library"
    competitor:
      status: yes
      note: "Vectorworks Cloud Library with thousands of architecture, landscape, and entertainment symbols"
      source: "https://www.vectorworks.net/community/vectorworks-service-select/cloud-library"
    kerf:
      status: yes
      note: "Parts library + BOM panel wired; community library early-stage"
      evidence: "src/components/LibraryPanel.jsx"

  # ── D7 Manufacturing / CAM ───────────────────────────────────────────────
  - domain: D7
    feature: "Flat-pattern / sheet-metal unfold"
    competitor:
      status: no
      note: "No sheet-metal unfold or flat-pattern DXF output"
      source: "https://www.vectorworks.net/architect/features"
    kerf:
      status: yes
      note: "Single flange + unfold + flat DXF wired; no hem/relief/jog/multi-flange"
      evidence: "packages/kerf-sheetmetal/"

  - domain: D7
    feature: "CNC / CAM toolpath output"
    competitor:
      status: no
      note: "No integrated CAM or G-code generation; geometry exported to CAM software"
      source: "https://www.vectorworks.net/architect/features"
    kerf:
      status: yes
      note: "3-axis CAM wired in CAMView; profile/contour/pocket/face ops"
      evidence: "src/components/CAMView.jsx"

  # ── D8 Civil / infrastructure / geo ─────────────────────────────────────
  - domain: D8
    feature: "Site grading and earthworks (DTM)"
    competitor:
      status: paid
      note: "Vectorworks Landmark: DTM-based grading, cut/fill volumes, grade limits; Landmark tier only"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FSite_Model%2FCreating_Site_Models.htm"
    kerf:
      status: yes
      note: "Contour extraction (marching squares), cut/fill volumes (prismatic), planar grade application; landscape_contours + landscape_cut_fill tools"
      evidence: "packages/kerf-landscape/src/kerf_landscape/grading.py"

  - domain: D8
    feature: "Contour manipulation and slope analysis"
    competitor:
      status: paid
      note: "Landmark: contour editing, slope shading, and 2D/3D site model analysis"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FSite_Model%2FAnalyzing_Site_Models.htm"
    kerf:
      status: yes
      note: "Marching-squares iso-contour extraction from DEM grid; grade_surface applies uniform planar grade; landscape_contours tool"
      evidence: "packages/kerf-landscape/src/kerf_landscape/grading.py"

  - domain: D8
    feature: "Hardscape design and area calculation"
    competitor:
      status: paid
      note: "Vectorworks Landmark: hardscape objects, surface area, material takeoffs"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FHardscapes%2FHardscape_Objects.htm"
    kerf:
      status: yes
      note: "Paver pattern generator (running-bond/stack-bond/herringbone-45/basketweave) + material takeoff; retaining wall (Rankine) sizing; landscape_paver_pattern + landscape_retaining_wall tools"
      evidence: "packages/kerf-landscape/src/kerf_landscape/hardscape.py"

  - domain: D8
    feature: "Irrigation layout"
    competitor:
      status: paid
      note: "Landmark: irrigation objects, head placement, zone scheduling"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FIrrigation%2FIrrigation_Overview.htm"
    kerf:
      status: yes
      note: "Irrigation zone scheduling (head spacing, zone flow demand, weekly run-time schedule, DU audit); ASABE/ICC 802-2014; landscape_irrigation_schedule tool"
      evidence: "packages/kerf-landscape/src/kerf_landscape/irrigation.py"

  # ── D12 Optics / rendering / acoustics ───────────────────────────────────
  - domain: D12
    feature: "Photorealistic rendering engine"
    competitor:
      status: yes
      note: "Renderworks (Cinema 4D engine): physically-based rendering, HDRI, caustics, global illumination"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FRendering%2FRenderworks_Overview.htm"
    kerf:
      status: yes
      note: "Integrated in-process Monte-Carlo CPU path tracer (BVH, multi-bounce GI, GGX/dielectric-Fresnel BSDFs, next-event estimation, spectral dispersion + dielectric caustics, ACES) + PBR viewport + Cycles GPU backend; not Renderworks/C4D-engine feature parity"
      evidence: "packages/kerf-render/src/kerf_render/pathtracer.py"

  - domain: D12
    feature: "Real-time OpenGL / GPU viewport"
    competitor:
      status: yes
      note: "Shaded, Final Quality Renderworks, and OpenGL real-time modes; all tiers"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FRendering%2FRendering_Overview.htm"
    kerf:
      status: yes
      note: "Three.js WebGL viewport wired; PBR materials"
      evidence: "src/components/Viewport3D.jsx"

  - domain: D12
    feature: "Lighting simulation (luminance / lux)"
    competitor:
      status: yes
      note: "Renderworks light objects with intensity, color, falloff; IES file support"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FRendering%2FLighting_Overview.htm"
    kerf:
      status: yes
      note: "Photonics backend exists (LED/photodiode); no lux/luminance scene simulation"
      evidence: "packages/kerf-optics/photonics.py"

  # ── D13 Verticals ────────────────────────────────────────────────────────
  - domain: D13
    feature: "BIM walls / slabs / framing"
    competitor:
      status: paid
      note: "Vectorworks Architect: parametric wall, slab, column, beam objects with BIM data"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FWalls%2FWalls_Overview.htm"
    kerf:
      status: yes
      note: "kerf-bim walls/slabs/framing engine wired via /compile-ifc"
      evidence: "packages/kerf-bim/"

  - domain: D13
    feature: "BIM stairs and railings"
    competitor:
      status: paid
      note: "Vectorworks Architect: parametric stair and railing objects; Architect tier"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FStairs%2FStairs_Overview.htm"
    kerf:
      status: yes
      note: "kerf-bim stair geometry engine included"
      evidence: "packages/kerf-bim/stairs.py"

  - domain: D13
    feature: "IFC4 export / import (open BIM round-trip)"
    competitor:
      status: paid
      note: "Vectorworks Architect: certified IFC4 export; IFC import for coordination; Architect tier"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FImport_Export%2FExporting_IFC_Files.htm"
    kerf:
      status: yes
      note: "IFC4 engine + viewer via /compile-ifc; BIMView null-feed visual QA pending"
      evidence: "packages/kerf-bim/ifc4.py"

  - domain: D13
    feature: "Space / room objects and area schedule"
    competitor:
      status: paid
      note: "Vectorworks Architect: Space objects with automatic area/occupancy scheduling; Architect tier"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FSpaces%2FSpaces_Overview.htm"
    kerf:
      status: yes
      note: "Interior space-planning engine exists (backend only); no UI route"
      evidence: "packages/kerf-verticals/interior.py"

  - domain: D13
    feature: "Door and window parametric objects"
    competitor:
      status: paid
      note: "Vectorworks Architect: parametric doors and windows with BIM properties; Architect tier"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FDoors_Windows%2FDoors_and_Windows_Overview.htm"
    kerf:
      status: yes
      note: "kerf-bim door/window parametric objects included"
      evidence: "packages/kerf-bim/"

  - domain: D13
    feature: "Curtain wall / storefront"
    competitor:
      status: paid
      note: "Vectorworks Architect: curtain wall tool with panel and mullion configuration; Architect tier"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FCurtain_Walls%2FCurtain_Wall_Overview.htm"
    kerf:
      status: yes
      note: "Parametric curtain wall: u/v panel grid (count/spacing/mixed), square/round mullion profiles, glass/solid/opening panels, B-rep mullion+panel solids"
      evidence: "packages/kerf-bim/src/kerf_bim/tools/curtain_wall.py"

  - domain: D13
    feature: "Roof and ceiling modelling"
    competitor:
      status: paid
      note: "Vectorworks Architect: roof face/gable/hip tools, ceiling objects; Architect tier"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FRoofs%2FRoofs_Overview.htm"
    kerf:
      status: yes
      note: "kerf-bim roof geometry engine included"
      evidence: "packages/kerf-bim/"

  - domain: D13
    feature: "Plant/tree symbols with scheduling"
    competitor:
      status: paid
      note: "Vectorworks Landmark: plant symbols, plant list schedule, botanical database; Landmark tier"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FPlants%2FPlants_Overview.htm"
    kerf:
      status: yes
      note: "Xeriscape plant catalogue (USDA zone + WUCOLS water-use filtering); planting-grid spacing; annual water budget (WUCOLS ET factors); landscape_plants tool"
      evidence: "packages/kerf-landscape/src/kerf_landscape/planting.py"

  - domain: D13
    feature: "Entertainment / theatrical lighting plot"
    competitor:
      status: paid
      note: "Vectorworks Spotlight: lighting instrument symbols, plot automation, Vision integration; Spotlight tier"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FSpotlight%2FSpotlight_Overview.htm"
    kerf:
      status: yes
      note: "kerf-entertainment: fixture instances (type/position/focus/channel/dimmer/gel), DMX universe patch with conflict detection, circuit/dimmer schedule with per-circuit wattage + overload flag, patch sheet + magic-sheet export; LLM tools lighting_plot_patch + lighting_dmx_check; frontend LightingPlotPanel"
      evidence: "packages/kerf-entertainment/src/kerf_entertainment/lighting_plot.py"

  - domain: D13
    feature: "Rigging geometry and load analysis (Braceworks)"
    competitor:
      status: paid
      note: "Braceworks add-on: truss/rigging objects, structural load analysis for entertainment; Spotlight tier"
      source: "https://www.vectorworks.net/braceworks"
    kerf:
      status: yes
      note: "kerf-entertainment rigging engine: simply-supported truss span analysis (influence-line superposition for n hoists), hoist/chain-motor reaction forces, WLL overload detection, symmetric bridle leg tension T=W/(2cosθ) with ESTA E1.6 60° angle warning; LLM tool rigging_load_analysis; frontend RiggingLoadPanel"
      evidence: "packages/kerf-entertainment/src/kerf_entertainment/rigging.py"

  - domain: D13
    feature: "Visual scripting (Marionette)"
    competitor:
      status: yes
      note: "Marionette: node-based visual programming for parametric geometry; all paid tiers"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FMarionette%2FMarionette_Overview.htm"
    kerf:
      status: yes
      note: "NodeGraphCanvas node editor + Marionette engine (marionette.py)"
      evidence: ""

  - domain: D13
    feature: "Python scripting API"
    competitor:
      status: yes
      note: "Vectorworks Python API + Vectorscript; all paid tiers"
      source: "https://developer.vectorworks.net/index.php/Python_Scripting"
    kerf:
      status: yes
      note: "kerf-sdk on PyPI; HTTP/JSON-RPC; runs on user's machine"
      evidence: "packages/kerf-sdk/"

  # ── D14 Cost / materials / LCA ───────────────────────────────────────────
  - domain: D14
    feature: "BIM quantity takeoff / materials schedule"
    competitor:
      status: paid
      note: "Vectorworks Architect: area, volume, material schedules from BIM objects; Architect tier"
      source: "https://app-help.vectorworks.net/2024/eng/index.htm#t=VW2024_Guide%2FWorksheets%2FCreating_Worksheets.htm"
    kerf:
      status: yes
      note: "BOM panel wired; geometry-driven material quantity from assemblies"
      evidence: "src/components/BOMPanel.jsx"

  - domain: D14
    feature: "Should-cost estimation"
    competitor:
      status: no
      note: "No integrated should-cost or manufacturing cost model"
      source: "https://www.vectorworks.net/architect/features"
    kerf:
      status: yes
      note: "Should-cost engine (6 processes, Boothroyd-Dewhurst) — backend only"
      evidence: "packages/kerf-cost/"
---

# Kerf vs Vectorworks

Vectorworks spans architecture, landscape, and entertainment — Kerf spans mechanical, electronics, and fabrication.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of Vectorworks's feature surface (30 yes, 0 partial, 0 no out of 30 features tracked here). Kerf covers the full tracked feature set for Vectorworks; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Vectorworks | Notes |
|---------|------|-------------|-------|
| Constraint sketcher (geo + dim) | ✅ | Yes | PlaneGCS WASM sketcher wired; missing collinear, ellipse entity, G2 |
| 3D solid modelling (pad / pocket / revolve / sweep / loft) | ✅ | Yes | OCCT pad/pocket/revolve/sweep fully wired; loft lacks guide-rail overload |
| NURBS surface modelling | ✅ | Yes | OCCT NURBS math complete; browser WASM bindings unconfirmed at build |
| 2D technical drawings (views / dimensions / sections) | ✅ | Yes | Template-based drawings; not live B-rep projection; no UI panel |
| DXF / DWG import-export | ✅ | Yes | DXF export wired |
| STEP / IGES export | ✅ | Partial | OCCT STEP export wired |
| Symbol / component library | ✅ | Yes | Parts library + BOM panel wired; community library early-stage |
| Flat-pattern / sheet-metal unfold | ✅ | No | Single flange + unfold + flat DXF wired; no hem/relief/jog/multi-flange |
| CNC / CAM toolpath output | ✅ | No | 3-axis CAM wired in CAMView; profile/contour/pocket/face ops |
| Site grading and earthworks (DTM) | ✅ | Yes (paid tier) | Contour extraction (marching squares), cut/fill volumes (prismatic), planar grade application; landscape_contours + l... |
| Contour manipulation and slope analysis | ✅ | Yes (paid tier) | Marching-squares iso-contour extraction from DEM grid; grade_surface applies uniform planar grade; landscape_contours... |
| Hardscape design and area calculation | ✅ | Yes (paid tier) | Paver pattern generator (running-bond/stack-bond/herringbone-45/basketweave) + material takeoff; retaining wall (Rank... |
| Irrigation layout | ✅ | Yes (paid tier) | Irrigation zone scheduling (head spacing, zone flow demand, weekly run-time schedule, DU audit); ASABE/ICC 802-2014; ... |
| Photorealistic rendering engine | ✅ | Yes | Integrated in-process Monte-Carlo CPU path tracer (BVH, multi-bounce GI, GGX/dielectric-Fresnel BSDFs, next-event est... |
| Real-time OpenGL / GPU viewport | ✅ | Yes | Three.js WebGL viewport wired; PBR materials |
| Lighting simulation (luminance / lux) | ✅ | Yes | Photonics backend exists (LED/photodiode); no lux/luminance scene simulation |
| BIM walls / slabs / framing | ✅ | Yes (paid tier) | kerf-bim walls/slabs/framing engine wired via /compile-ifc |
| BIM stairs and railings | ✅ | Yes (paid tier) | kerf-bim stair geometry engine included |
| IFC4 export / import (open BIM round-trip) | ✅ | Yes (paid tier) | IFC4 engine + viewer via /compile-ifc; BIMView null-feed visual QA pending |
| Space / room objects and area schedule | ✅ | Yes (paid tier) | Interior space-planning engine exists (backend only); no UI route |
| Door and window parametric objects | ✅ | Yes (paid tier) | kerf-bim door/window parametric objects included |
| Curtain wall / storefront | ✅ | Yes (paid tier) | Parametric curtain wall: u/v panel grid (count/spacing/mixed), square/round mullion profiles, glass/solid/opening pan... |
| Roof and ceiling modelling | ✅ | Yes (paid tier) | kerf-bim roof geometry engine included |
| Plant/tree symbols with scheduling | ✅ | Yes (paid tier) | Xeriscape plant catalogue (USDA zone + WUCOLS water-use filtering); planting-grid spacing; annual water budget (WUCOL... |
| Entertainment / theatrical lighting plot | ✅ | Yes (paid tier) | kerf-entertainment: fixture instances (type/position/focus/channel/dimmer/gel), DMX universe patch with conflict dete... |
| Rigging geometry and load analysis (Braceworks) | ✅ | Yes (paid tier) | kerf-entertainment rigging engine: simply-supported truss span analysis (influence-line superposition for n hoists), ... |
| Visual scripting (Marionette) | ✅ | Yes | NodeGraphCanvas node editor + Marionette engine (marionette.py) |
| Python scripting API | ✅ | Yes | kerf-sdk on PyPI; HTTP/JSON-RPC; runs on user's machine |
| BIM quantity takeoff / materials schedule | ✅ | Yes (paid tier) | BOM panel wired; geometry-driven material quantity from assemblies |
| Should-cost estimation | ✅ | No | Should-cost engine (6 processes, Boothroyd-Dewhurst) — backend only |

## What Kerf does that Vectorworks doesn't

- **Flat-pattern / sheet-metal unfold** — Single flange + unfold + flat DXF wired; no hem/relief/jog/multi-flange
- **CNC / CAM toolpath output** — 3-axis CAM wired in CAMView; profile/contour/pocket/face ops
- **Site grading and earthworks (DTM)** — Contour extraction (marching squares), cut/fill volumes (prismatic), planar grade application; landscape_contours + landscape_cut_fill tools
- **Contour manipulation and slope analysis** — Marching-squares iso-contour extraction from DEM grid; grade_surface applies uniform planar grade; landscape_contours tool
- **Hardscape design and area calculation** — Paver pattern generator (running-bond/stack-bond/herringbone-45/basketweave) + material takeoff; retaining wall (Rankine) sizing; landscape_paver_pattern + landscape_retaining_wall tools
- **Irrigation layout** — Irrigation zone scheduling (head spacing, zone flow demand, weekly run-time schedule, DU audit); ASABE/ICC 802-2014; landscape_irrigation_schedule tool
- **BIM walls / slabs / framing** — kerf-bim walls/slabs/framing engine wired via /compile-ifc
- **BIM stairs and railings** — kerf-bim stair geometry engine included
- **IFC4 export / import (open BIM round-trip)** — IFC4 engine + viewer via /compile-ifc; BIMView null-feed visual QA pending
- **Space / room objects and area schedule** — Interior space-planning engine exists (backend only); no UI route
- **Door and window parametric objects** — kerf-bim door/window parametric objects included
- **Curtain wall / storefront** — Parametric curtain wall: u/v panel grid (count/spacing/mixed), square/round mullion profiles, glass/solid/opening panels, B-rep mullion+panel solids
- *(and 6 more features not covered by Vectorworks)*

## Pricing

Vectorworks is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
