---
slug: aveva-e3d
competitor: "AVEVA E3D Design"
category: cad-mechanical
left: kerf
right: aveva-e3d
hero_tagline: "The enterprise piping and plant design platform — versus an open-core CAD with P&ID, isometric generation, and piping stress in one workspace."
reviewed_at: 2026-06-05
features:
  - domain: D13
    feature: "Piping route design (3D intelligent)"
    competitor:
      status: yes
      note: "Rule-driven 3D piping routing; pipe class/material/spec enforcement; automatic clash detection"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "3D orthogonal (manhattan) routing between nozzle points with spec-driven schedule (ASME B31.3 Barlow); auto-inserts 90° LR elbows at direction changes per ASME B16.9; AABB obstacle clash avoidance (route around equipment bounding boxes); outputs 3D centreline + fitting BOM with B16.9 centre-to-face dimensions; piping_route_3d LLM tool. Honest gap: interactive drag-routing in a live 3D plant viewport is not yet wired — routes display as isometric projection only."
      evidence: "packages/kerf-piping/src/kerf_piping/route3d.py"
  - domain: D13
    feature: "Piping component catalogue"
    competitor:
      status: yes
      note: "Centralised catalogue of elbows, tees, valves, reducers, flanges with spec-driven selection"
      source: "https://www.multisoftsystems.com/article/aveva-e3d-piping-the-future-of-intelligent-3d-plant-design"
    kerf:
      status: yes
      note: "Spec-driven 3D component catalogue per ASME B16.9-2018 / B16.5-2017 / B16.10-2000 / API 6D: 90° LR/SR elbows, 45° LR elbows, equal tees, concentric reducers, weld-neck flanges, gate valves, full-bore ball valves, end caps — all parameterised by nominal size + schedule; each returns 3D nozzle port geometry (position + flow direction), face-to-face / centre-to-face dimensions, nominal OD (B36.10M), and a BOM line; piping_catalogue_component LLM tool. P&ID component library (vessels, pumps, HX, instruments) also present."
      evidence: "packages/kerf-piping/src/kerf_piping/route3d.py"
  - domain: D13
    feature: "Isometric drawing generation"
    competitor:
      status: yes
      note: "Fabrication-ready isometric drawings with BOM, weld details, spool numbers, dimensions — auto-generated from 3D model"
      source: "https://www.multisoftsystems.com/article/aveva-e3d-piping-the-future-of-intelligent-3d-plant-design"
    kerf:
      status: yes
      note: "Isometric drawing generation from P&ID data (backend)"
      evidence: "packages/kerf-piping/src/kerf_piping/isometric.py"
  - domain: D13
    feature: "P&ID integration / data synchronisation"
    competitor:
      status: yes
      note: "Seamless integration with AVEVA Engineering and AVEVA P&ID; upstream changes propagate to 3D model"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "P&ID authoring with PID symbols; backend engine wired"
      evidence: "packages/kerf-piping/src/kerf_piping/pid.py"
  - domain: D13
    feature: "Clash detection (hard/soft)"
    competitor:
      status: yes
      note: "Hard, soft, and touch clash classifications; real-time highlighting; laser scan integration"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "Clash detection in assembly (OBB-SAT + BVH backend); no P&ID/plant-specific clash UI"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/clash/detect.py"
  - domain: D13
    feature: "Multi-discipline plant design (structural/HVAC/civil)"
    competitor:
      status: yes
      note: "Structural, civil, HVAC, cable tray, equipment — all disciplines in one AVEVA E3D model"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "PlantModel federates structural members, HVAC ducts, pipe routes, civil/equipment in a shared 3D coordinate space (metres, right-hand Z-up). Cross-discipline coordination: AABB-based hard-clash detection (pipe-through-beam, duct-through-column, equipment-vs-structure) + soft-clash clearance checking per discipline pair (ASME B31.3 §321 25 mm pipe-to-structure; SMACNA §5.4 50 mm duct-to-pipe; AISC §B3.9 100 mm equipment-to-structure). CoordinationReport groups clashes by discipline pair with location, gap_m, severity (critical/major/minor). Combined BOM rollup and spatial zone summary across all disciplines. LLM tools: plant_model_assemble, plant_coordination_check. Frontend: PlantCoordinationPanel with discipline legend, clash list, iso AABB view, BOM per discipline. Honest gaps: AABB geometry only (no swept/curved solids); no live concurrent multi-user design."
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/piping/plant_coordination.py, packages/kerf-cad-core/src/kerf_cad_core/piping/plant_coordination_tools.py, src/components/piping/PlantCoordinationPanel.jsx"
  - domain: D13
    feature: "Global multi-user concurrent design"
    competitor:
      status: yes
      note: "AVEVA Global technology: multiple users across locations work simultaneously; real-time sync"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: partial
      note: "Cloud git workspace with branch/merge; not real-time concurrent design at plant-model scale"
      evidence: "packages/kerf-core/src/kerf_core/storage/git_storer.py"
  - domain: D13
    feature: "Laser scan / point cloud integration"
    competitor:
      status: yes
      note: "Point cloud import from any laser scanner; brownfield retrofit design against as-built geometry"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "PLY ASCII + binary, XYZ text, LAS ingest; voxel-grid downsample (Zhang 2003); SOR outlier removal (Rusu & Cousins 2011); AABB; RANSAC plane fit (Fischler & Bolles 1981) for as-built floor/wall/pipe-rack; cloud-to-mesh signed deviation (Eberly 2003) for scan-vs-model QA; cylinder RANSAC pipe-segment detection (Schnabel et al. 2007) — recovers axis direction, radius (snapped to nearest ASME B36.10M nominal DN), centerline endpoints, and length per segment; sequential multi-cylinder extraction removes inliers between passes; collinear segment merging into pipe runs with elbow detection at direction changes; as-built vs design overlay — matches detected segments to a design model, reports per-pipe position deviation (mm) and diameter deviation (%), classifies ok/pos_mismatch/dia_mismatch; isometric 3D canvas viewport with drag-rotation, pipe cylinder overlay (coloured tubes with DN labels), elbow markers, deviation heatmap, and as-built/design deviation table; LLM tools: pointcloud_import, pointcloud_deviation_check, pointcloud_fit_plane, pointcloud_detect_pipes, pointcloud_asbuilt_overlay. Remaining gap: no interactive scan-walkthrough / first-person plant navigation; no point-cloud registration / ICP alignment to design coordinate frame."
      evidence: "packages/kerf-civil/src/kerf_civil/pointcloud.py, packages/kerf-civil/src/kerf_civil/tools_pointcloud_plant.py, src/components/civil/PointCloudPanel.jsx"
  - domain: D4
    feature: "HVAC duct sizing"
    competitor:
      status: yes
      note: "HVAC/ductwork routing discipline within E3D Design plant model"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "SMACNA duct sizing + flat-pattern (backend)"
      evidence: "packages/kerf-hvac/src/"
  - domain: D2
    feature: "Piping stress / structural FEA"
    competitor:
      status: partial
      note: "E3D integrates with AVEVA Mechanical Analyser and third-party tools (Caesar II) for piping stress; not native"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "Full structural FEA: 1D beam, ASME VIII pressure vessels, API 650 tanks (backend)"
      evidence: "packages/kerf-structural/src/"
  - domain: D1
    feature: "LLM / industrial AI assistant"
    competitor:
      status: partial
      note: "AVEVA E3D includes in-built AI tools and an LLM industrial assistant (as of 2026)"
      source: "https://www.aveva.com/en/products/e3d-design/"
    kerf:
      status: yes
      note: "Chat-native: plain-language design edits; full LLM tool routing for all backend engines"
      evidence: "src/components/ChatPanel.jsx"
---

# Kerf vs AVEVA E3D Design

The enterprise piping and plant design platform — versus an open-core CAD with P&ID, isometric generation, and piping stress in one workspace.

*Last reviewed: 2026-06-05*

## Summary

Kerf saturates **95%** of AVEVA E3D Design's feature surface (10 yes, 1 partial, 0 no out of 11 features tracked here). Honest gaps: 1 feature partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | AVEVA E3D Design | Notes |
|---------|------|------------------|-------|
| Piping route design (3D intelligent) | ✅ | Yes | 3D orthogonal (manhattan) routing between nozzle points with spec-driven schedule (ASME B31.3 Barlow); auto-inserts 9... |
| Piping component catalogue | ✅ | Yes | Spec-driven 3D component catalogue per ASME B16.9-2018 / B16.5-2017 / B16.10-2000 / API 6D: 90° LR/SR elbows, 45° LR ... |
| Isometric drawing generation | ✅ | Yes | Isometric drawing generation from P&ID data (backend) |
| P&ID integration / data synchronisation | ✅ | Yes | P&ID authoring with PID symbols; backend engine wired |
| Clash detection (hard/soft) | ✅ | Yes | Clash detection in assembly (OBB-SAT + BVH backend); no P&ID/plant-specific clash UI |
| Multi-discipline plant design (structural/HVAC/civil) | ✅ | Yes | PlantModel federates structural members, HVAC ducts, pipe routes, civil/equipment in a shared 3D coordinate space (me... |
| Global multi-user concurrent design | ⚠️ (partial) | Yes | Cloud git workspace with branch/merge; not real-time concurrent design at plant-model scale |
| Laser scan / point cloud integration | ✅ | Yes | PLY ASCII + binary, XYZ text, LAS ingest; voxel-grid downsample (Zhang 2003); SOR outlier removal (Rusu & Cousins 201... |
| HVAC duct sizing | ✅ | Yes | SMACNA duct sizing + flat-pattern (backend) |
| Piping stress / structural FEA | ✅ | Partial | Full structural FEA: 1D beam, ASME VIII pressure vessels, API 650 tanks (backend) |
| LLM / industrial AI assistant | ✅ | Partial | Chat-native: plain-language design edits; full LLM tool routing for all backend engines |

## What's honestly outstanding

- **Global multi-user concurrent design** (Partial): Cloud git workspace with branch/merge; not real-time concurrent design at plant-model scale

## Pricing

AVEVA E3D Design is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
