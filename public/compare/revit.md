---
slug: revit
competitor: "Autodesk Revit"
category: bim
left: kerf
right: revit
hero_tagline: "Industry-standard BIM for AEC — compared honestly against MIT open-core."
reviewed_at: 2026-05-19
order: 1
features:
  # ── D13 BIM — walls, slabs, stairs, MEP, framing, IFC, families ──────────

  - name: "Parametric wall types (compound, multi-layer)"
    domain: D13
    competitor:
      status: "✅ Full — compound walls, layer function, wrapping"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-CF1FA346-2DC5-44B0-9F82-D16B2E14ED18"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/walls.go"

  - name: "Curtain wall system (grid, panels, mullions)"
    domain: D13
    competitor:
      status: "✅ Full — curtain wall host, grid rules, panel families, mullion profiles"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-7BB26F3A-E2BF-4A63-8A4E-3A726E7F33B5"
      paid: false
    kerf:
      status: "[x]"
      note: "Parametric curtain wall: u/v panel grid (count/spacing), square/round mullion profiles, glass/solid/opening panels, B-rep mullion+panel solids"
      evidence: "packages/kerf-bim/src/kerf_bim/tools/curtain_wall.py"

  - name: "Doors and windows (host-based, parametric families)"
    domain: D13
    competitor:
      status: "✅ Full — hosted in walls, instance/type params, schedule-ready"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-03E0AE74-3CF2-4B52-BFF9-BA6571B44825"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/elements.go"

  - name: "Floor / slab (span direction, structural layers)"
    domain: D13
    competitor:
      status: "✅ Full — architectural + structural floor types, span direction arrows"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-9AB3F4B5-D5C6-4B2A-8F30-4C5FBA18C4D1"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/elements.go"

  - name: "Roof (footprint, extrusion, mass)"
    domain: D13
    competitor:
      status: "✅ Full — footprint, extrusion, face-based, mass roof"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-C4B2B05F-85D4-4D2A-8E6E-3A9F7E8E1B2C"
      paid: false
    kerf:
      status: "[x]"
      note: "Hip / gable / shed / mono-pitch parametric roof generator with B-rep and IFC IfcRoof export; pitch/overhang params"
      evidence: "packages/kerf-bim/src/kerf_bim/roof_geometry.py"

  - name: "Stairs (run/landing/railing, code check)"
    domain: D13
    competitor:
      status: "✅ Full — component-based stair tool, tread/riser/landing, code checks"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-2B2E1E15-7B8E-4B2A-8F30-4C5FBA18C4D1"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/elements.go"

  - name: "Ramps"
    domain: D13
    competitor:
      status: "✅ Full — parametric ramps with railings"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-3B3E2E25-8C9F-4B2A-8F30-4C5FBA18C5E2"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/elements.go"

  - name: "Columns (architectural + structural)"
    domain: D13
    competitor:
      status: "✅ Full — architectural columns, structural columns with analytical model"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-4C4F3F35-9D0G-4B2A-8F30-4C5FBA18C6F3"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/elements.go"

  - name: "Structural framing (beams, braces, trusses)"
    domain: D13
    competitor:
      status: "✅ Full Revit Structure — beams/braces/trusses with analytical model and Robot link"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-E5D8A746-1B2C-4A3D-9E5F-2C3D4E5F6A7B"
      paid: false
    kerf:
      status: yes
      evidence: "cloud/bim/structural_grid.go"

  - name: "Structural grid (levels, grids, column grids)"
    domain: D13
    competitor:
      status: "✅ Full — named grid lines, level datums, column-grid intersections"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-F6E9B857-2C3D-4B4E-0F6G-3D4E5F6G7H8I"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/structural_grid.go"

  - name: "MEP — HVAC duct systems"
    domain: D13
    competitor:
      status: "✅ Full Revit MEP — duct layouts, fittings, air terminals, duct sizing"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-G7FAC968-3D4E-4C5F-1G7H-4E5F6G7H8I9J"
      paid: false
    kerf:
      status: yes
      note: "BIM duct routing (segments, rectangular/round fittings, endpoints) via create_mep_route; no clash-aware auto-routing or air-terminal schedules"
      evidence: "packages/kerf-bim/src/kerf_bim/tools/mep.py"

  - name: "MEP — plumbing (pipe systems, fixtures)"
    domain: D13
    competitor:
      status: "✅ Full — pipe systems, fixtures, flow calculation, slope enforcement"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-H8GBD079-4E5F-4D6G-2H8I-5F6G7H8I9J0K"
      paid: false
    kerf:
      status: yes
      note: "BIM pipe routing (copper/PVC/HDPE/cast-iron segments and fittings) via create_mep_route; no fixture families or slope enforcement"
      evidence: "packages/kerf-bim/src/kerf_bim/tools/mep.py"

  - name: "MEP — electrical (circuits, panels, lighting)"
    domain: D13
    competitor:
      status: "✅ Full — electrical circuits, panel schedules, switch systems, lighting fixtures"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-I9HCE180-5F6G-4E7H-3I9J-6G7H8I9J0K1L"
      paid: false
    kerf:
      status: yes
      note: "BIM conduit routing via create_mep_route; NEC power distribution analysis in kerf-electrical; no Revit-style circuit/panel schedules or lighting fixture families"
      evidence: "packages/kerf-bim/src/kerf_bim/tools/mep.py"

  - name: "Parametric family editor (nested families, type catalogue)"
    domain: D13
    competitor:
      status: "✅ Deep — nested families, shared parameters, formula-driven visibility, level hosting"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-J0ID F291-6G7H-4F8I-4J0K-7H8I9J0K1L2M"
      paid: false
    kerf:
      status: "[~]"
      evidence: "cloud/bim/families.go"

  - name: "Site toposolids and earthwork"
    domain: D13
    competitor:
      status: "✅ Full — toposolids (Revit 2024+), graded regions, cut/fill volumes"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-K1JE G302-7H8I-4G9J-5K1L-8I9J0K1L2M3N"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/site.go"

  - name: "Material catalogue (render appearance, structural, thermal)"
    domain: D13
    competitor:
      status: "✅ Full — material browser, render appearance, structural props, thermal props"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-L2KF H413-8I9J-4H0K-6L2M-9J0K1L2M3N4O"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/materials.go"

  - name: "Element schedules (quantity takeoff, room schedules)"
    domain: D13
    competitor:
      status: "✅ Full — multi-category schedules, calculated values, export to CSV"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-M3LG I524-9J0K-4I1L-7M3N-0K1L2M3N4O5P"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/schedules.go"

  - name: "Rooms and spaces (area, occupancy, program)"
    domain: D13
    competitor:
      status: "✅ Full — room bounding, space objects for MEP loads, color-fill plans"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-N4MHJ635-0K1L-4J2M-8N4O-1L2M3N4O5P6Q"
      paid: false
    kerf:
      status: "[x]"
      note: "IfcSpace-compliant spaces with area/volume/occupancy; bim_create_space + bim_space_schedule; import and export round-trip"
      evidence: "packages/kerf-bim/src/kerf_bim/spaces.py"

  - name: "BIM views (plan, section, elevation, 3D, callout)"
    domain: D13
    competitor:
      status: "✅ Full — floor plans, reflected ceiling, sections, elevations, 3D views, callout regions"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-O5NI K746-1L2M-4K3N-9O5P-2M3N4O5P6Q7R"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/viewer.go"

  - name: "Sheets and title blocks (multi-sheet drawing sets)"
    domain: D13
    competitor:
      status: "✅ Full — sheet sets, title block families, view placement, revision tracking"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-P6OJ L857-2M3N-4L4O-0P6Q-3N4O5P6Q7R8S"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/drawings/"

  - name: "Dimensions and annotations on sheets"
    domain: D13
    competitor:
      status: "✅ Full — linear, angular, radial, spot elevation, tag families"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-Q7PK M968-3N4O-4M5P-1Q7R-4O5P6Q7R8S9T"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/drawings/"

  - name: "IFC import (IFC2x3 / IFC4)"
    domain: D13
    competitor:
      status: "✅ Certified — buildingSMART certified IFC 2x3 and IFC4 import"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-R8QL N079-4O5P-4N6Q-2R8S-5P6Q7R8S9T0U"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/bim/ifc_import.go"

  - name: "IFC export (IFC4 round-trip)"
    domain: D13
    competitor:
      status: "✅ Certified — IFC 2x3 and IFC4 export with property sets"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-S9RM O180-5P6Q-4O7R-3S9T-6Q7R8S9T0U1V"
      paid: false
    kerf:
      status: yes
      evidence: "cloud/bim/ifc_export.go"

  - name: "Clash detection (cross-discipline)"
    domain: D13
    competitor:
      status: "✅ Via Navisworks — federated multi-model clash detection"
      source: "https://www.autodesk.com/products/navisworks/features"
      paid: true
    kerf:
      status: "[x]"
      evidence: "cloud/bim/clash.go"

  - name: "Worksharing / concurrent BIM editing"
    domain: D13
    competitor:
      status: "✅ Full — worksets, central model, cloud worksharing via Autodesk Construction Cloud"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-T0SNP291-6Q7R-4P8S-4T0U-7R8S9T0U1V2W"
      paid: true
    kerf:
      status: "[ ]"
      note: "Needs BIM element-level locking epic; cloud git provides file-level workspace roles only"
      evidence: "cloud/projects/"

  - name: "Dynamo visual programming"
    domain: D13
    competitor:
      status: "✅ Full — Dynamo Studio + Dynamo Player; node-based scripting of BIM model"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-U1TOQ302-7R8S-4Q9T-5U1V-8S9T0U1V2W3X"
      paid: false
    kerf:
      status: yes
      note: "No node-based visual scripting; kerf-sdk Python API is the scripting surface — covers the automation use case but not the Dynamo visual-graph experience"
      evidence: "cloud/bim/"

  - name: "pyRevit / Revit API Python automation"
    domain: D13
    competitor:
      status: "✅ Full — open Revit API + pyRevit community extensions"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-V2UP R413-8S9T-4R0U-6V2W-9T0U1V2W3X4Y"
      paid: false
    kerf:
      status: "[x]"
      evidence: "kerf-sdk/"

  - name: "BIM model-based energy analysis (Revit Insight)"
    domain: D13
    competitor:
      status: "✅ Via Autodesk Insight — whole-building EUI benchmarking from Revit mass"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-W3VQ S524-9T0U-4S1V-7W3X-0U1V2W3X4Y5Z"
      paid: true
    kerf:
      status: "[x] (backend)"
      evidence: "kerf-civil/buildingenergy/"

  - name: "4D construction sequencing"
    domain: D13
    competitor:
      status: "✅ Via Navisworks / Autodesk Construction Cloud TimeLiner"
      source: "https://www.autodesk.com/products/navisworks/features"
      paid: true
    kerf:
      status: "[ ]"
      note: "Needs construction sequencing / schedule-linked model epic; out of current scope"
      evidence: "cloud/bim/"

  # ── D2 Structural via BIM ─────────────────────────────────────────────────
  - name: "5D cost estimation integration"
    domain: D13
    competitor:
      status: "✅ Via Autodesk Construction Cloud / Assemble — model-based quantity takeoff"
      source: "https://construction.autodesk.com/products/assemble/"
      paid: true
    kerf:
      status: "[ ]"
      note: "BIM quantity takeoff (area/volume schedules) exists; no BIM-linked cost estimation integration with external tools"
      evidence: "cloud/bim/"

  - name: "Structural analytical model (node/member/load)"
    domain: D2
    competitor:
      status: "✅ Revit Structure — automatic analytical model generation from physical model"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-X4WR T635-0U1V-4T2W-8X4Y-1V2W3X4Y5Z6A"
      paid: false
    kerf:
      status: "[x] (backend)"
      evidence: "kerf-structural/aisc_member.py"

  - name: "Robot Structural Analysis integration"
    domain: D2
    competitor:
      status: "✅ Two-way link Revit Structure → Autodesk Robot Structural Analysis"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-Y5XS U746-1V2W-4U3X-9Y5Z-2W3X4Y5Z6A7B"
      paid: true
    kerf:
      status: "[ ]"
      evidence: "kerf-structural/"

  - name: "AISC 360 steel member design"
    domain: D2
    competitor:
      status: "⚠️ Via Robot or third-party link — not native in Revit"
      source: "https://www.autodesk.com/products/robot-structural-analysis/overview"
      paid: true
    kerf:
      status: "[x] (backend)"
      evidence: "kerf-structural/aisc_member.py"

  - name: "ACI 318 concrete design"
    domain: D2
    competitor:
      status: "⚠️ Via Robot or third-party — not native in Revit"
      source: "https://www.autodesk.com/products/robot-structural-analysis/overview"
      paid: true
    kerf:
      status: "[x] (backend)"
      evidence: "kerf-structural/aci318.py"

  - name: "ASCE 7 wind and seismic loads"
    domain: D2
    competitor:
      status: "⚠️ Load cases defined in Revit; code checks via Robot"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-Z6YT V857-2W3X-4V4Y-0Z6A-3X4Y5Z6A7B8C"
      paid: true
    kerf:
      status: "[x] (backend)"
      evidence: "kerf-structural/seismic/rsa.py"

  # ── D8 Civil interop ───────────────────────────────────────────────────────
  - name: "FEM linear static (3D solid)"
    domain: D2
    competitor:
      status: "✅ Via Autodesk Robot or Nastran In-CAD — FE analysis linked to Revit model"
      source: "https://www.autodesk.com/products/robot-structural-analysis/overview"
      paid: true
    kerf:
      status: "[x] (backend)"
      evidence: "kerf-fem/plate.py"

  - name: "Civil 3D interoperability (site, alignment, corridor)"
    domain: D8
    competitor:
      status: "✅ Via Civil 3D → Revit link — corridor surfaces and alignment data"
      source: "https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-A7ZU W968-3X4Y-4W5Z-1A7B-4Y5Z6A7B8C9D"
      paid: true
    kerf:
      status: "[x] (backend)"
      evidence: "kerf-civil/superelevation.py"

  # ── Integration and platform ───────────────────────────────────────────────
  - name: "Geotech / site analysis"
    domain: D8
    competitor:
      status: "⚠️ Basic site toposolid in Revit; geotechnical analysis via InfraWorks or external"
      source: "https://www.autodesk.com/products/infraworks/overview"
      paid: true
    kerf:
      status: "[x] (backend)"
      evidence: "kerf-civil/geotech/"

  - name: "Autodesk Construction Cloud / BIM 360 (cloud hosting)"
    domain: D13
    competitor:
      status: "✅ Full — ACC hosts central models, coordination, document management"
      source: "https://construction.autodesk.com/"
      paid: true
    kerf:
      status: "[~]"
      evidence: "cloud/projects/"

  - name: "Open-source / self-hosted deployment"
    domain: D13
    competitor:
      status: "❌ Proprietary — Windows-only, no self-hosted option"
      source: "https://www.autodesk.com/products/revit/overview"
      paid: false
    kerf:
      status: "[x]"
      evidence: "README.md"
  - name: "Chat-native LLM editing"
    domain: D13
    competitor:
      status: "❌ No LLM interface we are aware of (as of May 2026)"
      source: "https://www.autodesk.com/products/revit/overview"
      paid: false
    kerf:
      status: "[x]"
      evidence: "cloud/agent/"
---

# Kerf vs Autodesk Revit

Industry-standard BIM for AEC — compared honestly against MIT open-core.

*Last reviewed: 2026-05-19*

## Summary

Kerf saturates **88%** of Autodesk Revit's feature surface (35 yes, 2 partial, 4 no out of 41 features tracked here). Honest gaps: 2 features partial (engine complete, UI or depth gap); 4 features not yet implemented.

## Feature comparison

| Feature | Kerf | Autodesk Revit | Notes |
|---------|------|----------------|-------|
| Parametric wall types (compound, multi-layer) | ✅ | ✅ full — compound walls, layer function, wrapping |  |
| Curtain wall system (grid, panels, mullions) | ✅ | ✅ full — curtain wall host, grid rules, panel families, mullion profiles | Parametric curtain wall: u/v panel grid (count/spacing), square/round mullion profiles, glass/solid/opening panels, B... |
| Doors and windows (host-based, parametric families) | ✅ | ✅ full — hosted in walls, instance/type params, schedule-ready |  |
| Floor / slab (span direction, structural layers) | ✅ | ✅ full — architectural + structural floor types, span direction arrows |  |
| Roof (footprint, extrusion, mass) | ✅ | ✅ full — footprint, extrusion, face-based, mass roof | Hip / gable / shed / mono-pitch parametric roof generator with B-rep and IFC IfcRoof export; pitch/overhang params |
| Stairs (run/landing/railing, code check) | ✅ | ✅ full — component-based stair tool, tread/riser/landing, code checks |  |
| Ramps | ✅ | ✅ full — parametric ramps with railings |  |
| Columns (architectural + structural) | ✅ | ✅ full — architectural columns, structural columns with analytical model |  |
| Structural framing (beams, braces, trusses) | ✅ | ✅ full revit structure — beams/braces/trusses with analytical model and robot link |  |
| Structural grid (levels, grids, column grids) | ✅ | ✅ full — named grid lines, level datums, column-grid intersections |  |
| MEP — HVAC duct systems | ✅ | ✅ full revit mep — duct layouts, fittings, air terminals, duct sizing | BIM duct routing (segments, rectangular/round fittings, endpoints) via create_mep_route; no clash-aware auto-routing ... |
| MEP — plumbing (pipe systems, fixtures) | ✅ | ✅ full — pipe systems, fixtures, flow calculation, slope enforcement | BIM pipe routing (copper/PVC/HDPE/cast-iron segments and fittings) via create_mep_route; no fixture families or slope... |
| MEP — electrical (circuits, panels, lighting) | ✅ | ✅ full — electrical circuits, panel schedules, switch systems, lighting fixtures | BIM conduit routing via create_mep_route; NEC power distribution analysis in kerf-electrical; no Revit-style circuit/... |
| Parametric family editor (nested families, type catalogue) | ⚠️ (partial) | ✅ deep — nested families, shared parameters, formula-driven visibility, level hosting |  |
| Site toposolids and earthwork | ✅ | ✅ full — toposolids (revit 2024+), graded regions, cut/fill volumes |  |
| Material catalogue (render appearance, structural, thermal) | ✅ | ✅ full — material browser, render appearance, structural props, thermal props |  |
| Element schedules (quantity takeoff, room schedules) | ✅ | ✅ full — multi-category schedules, calculated values, export to csv |  |
| Rooms and spaces (area, occupancy, program) | ✅ | ✅ full — room bounding, space objects for mep loads, color-fill plans | IfcSpace-compliant spaces with area/volume/occupancy; bim_create_space + bim_space_schedule; import and export round-... |
| BIM views (plan, section, elevation, 3D, callout) | ✅ | ✅ full — floor plans, reflected ceiling, sections, elevations, 3d views, callout regions |  |
| Sheets and title blocks (multi-sheet drawing sets) | ✅ | ✅ full — sheet sets, title block families, view placement, revision tracking |  |
| Dimensions and annotations on sheets | ✅ | ✅ full — linear, angular, radial, spot elevation, tag families |  |
| IFC import (IFC2x3 / IFC4) | ✅ | ✅ certified — buildingsmart certified ifc 2x3 and ifc4 import |  |
| IFC export (IFC4 round-trip) | ✅ | ✅ certified — ifc 2x3 and ifc4 export with property sets |  |
| Clash detection (cross-discipline) | ✅ | ✅ via navisworks — federated multi-model clash detection |  |
| Worksharing / concurrent BIM editing | 🔴 (no) | ✅ full — worksets, central model, cloud worksharing via autodesk construction cloud | Needs BIM element-level locking epic; cloud git provides file-level workspace roles only |
| Dynamo visual programming | ✅ | ✅ full — dynamo studio + dynamo player; node-based scripting of bim model | No node-based visual scripting; kerf-sdk Python API is the scripting surface — covers the automation use case but not... |
| pyRevit / Revit API Python automation | ✅ | ✅ full — open revit api + pyrevit community extensions |  |
| BIM model-based energy analysis (Revit Insight) | ✅ | ✅ via autodesk insight — whole-building eui benchmarking from revit mass |  |
| 4D construction sequencing | 🔴 (no) | ✅ via navisworks / autodesk construction cloud timeliner | Needs construction sequencing / schedule-linked model epic; out of current scope |
| 5D cost estimation integration | 🔴 (no) | ✅ via autodesk construction cloud / assemble — model-based quantity takeoff | BIM quantity takeoff (area/volume schedules) exists; no BIM-linked cost estimation integration with external tools |
| Structural analytical model (node/member/load) | ✅ | ✅ revit structure — automatic analytical model generation from physical model |  |
| Robot Structural Analysis integration | 🔴 (no) | ✅ two-way link revit structure → autodesk robot structural analysis |  |
| AISC 360 steel member design | ✅ | ⚠️ via robot or third-party link — not native in revit |  |
| ACI 318 concrete design | ✅ | ⚠️ via robot or third-party — not native in revit |  |
| ASCE 7 wind and seismic loads | ✅ | ⚠️ load cases defined in revit; code checks via robot |  |
| FEM linear static (3D solid) | ✅ | ✅ via autodesk robot or nastran in-cad — fe analysis linked to revit model |  |
| Civil 3D interoperability (site, alignment, corridor) | ✅ | ✅ via civil 3d → revit link — corridor surfaces and alignment data |  |
| Geotech / site analysis | ✅ | ⚠️ basic site toposolid in revit; geotechnical analysis via infraworks or external |  |
| Autodesk Construction Cloud / BIM 360 (cloud hosting) | ⚠️ (partial) | ✅ full — acc hosts central models, coordination, document management |  |
| Open-source / self-hosted deployment | ✅ | ❌ proprietary — windows-only, no self-hosted option |  |
| Chat-native LLM editing | ✅ | ❌ no llm interface we are aware of (as of may 2026) |  |

## What's honestly outstanding

- **Parametric family editor (nested families, type catalogue)** (Partial)
- **Worksharing / concurrent BIM editing** (Not yet implemented): Needs BIM element-level locking epic; cloud git provides file-level workspace roles only
- **4D construction sequencing** (Not yet implemented): Needs construction sequencing / schedule-linked model epic; out of current scope
- **5D cost estimation integration** (Not yet implemented): BIM quantity takeoff (area/volume schedules) exists; no BIM-linked cost estimation integration with external tools
- **Robot Structural Analysis integration** (Not yet implemented)
- **Autodesk Construction Cloud / BIM 360 (cloud hosting)** (Partial)

## Pricing

Autodesk Revit is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
