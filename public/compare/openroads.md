---
slug: openroads
competitor: "Bentley OpenRoads Designer"
category: bim
left: kerf
right: openroads
hero_tagline: "Civil infrastructure & roadway design — compared honestly against MIT open-core."
reviewed_at: 2026-06-05
features:
  - domain: D14
    feature: "Horizontal + vertical alignment (clothoid transitions)"
    competitor:
      status: yes
      note: "Object-oriented coordinate geometry; intelligent alignment updates"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: yes
      note: "Horizontal (line/arc/spiral-clothoid) + vertical (tangent/parabolic) alignment + station-at"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/civil/alignment_tools.py"

  - domain: D14
    feature: "Digital terrain model (LiDAR / survey → DTM)"
    competitor:
      status: yes
      note: "DTM from LiDAR, survey; dynamic contours"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: yes
      note: "Dynamic TIN (Bowyer-Watson Delaunay) + breaklines/boundary + volume-between"
      evidence: "packages/kerf-civil/src/kerf_civil/tin.py"

  - domain: D14
    feature: "Point cloud / survey import (LAS)"
    competitor:
      status: yes
      note: "LiDAR + survey data ingestion into terrain"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: yes
      note: "LAS/XYZ/PLY ingest + voxel downsample + PMF ground classification → TIN"
      evidence: "packages/kerf-civil/src/kerf_civil/pointcloud.py"

  - domain: D14
    feature: "Drainage / storm sewer (inlets, pipes, HGL/EGL)"
    competitor:
      status: yes
      note: "Stormwater conveyance: inlets, pipes, detention; integrated hydraulics"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: yes
      note: "Gravity pipe network (Manning HGL/EGL + structure headloss + topological solve, ASCE MOP 36)"
      evidence: "packages/kerf-civil/src/kerf_civil/hydraulics_gravity.py"

  - domain: D14
    feature: "Pressure / water distribution networks"
    competitor:
      status: yes
      note: "Integrated water analysis tools"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: yes
      note: "Hardy-Cross / Global-Gradient water network solve + minor losses + pumps"
      evidence: "packages/kerf-civil/src/kerf_civil/hydraulics_pressure.py"

  - domain: D14
    feature: "Superelevation"
    competitor:
      status: yes
      note: "Automated superelevation per design standards"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: yes
      note: "Superelevation calculation per AASHTO method"
      evidence: "packages/kerf-civil/src/kerf_civil/superelevation.py"

  - domain: D14
    feature: "Plan & profile sheet production"
    competitor:
      status: yes
      note: "Automated plan/profile sheet generation along corridors"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: yes
      note: "Automated plan+profile sheet set (station grid, profile band, match lines; AASHTO/FHWA)"
      evidence: "packages/kerf-civil/src/kerf_civil/sheets.py"

  - domain: D14
    feature: "Parcels / right-of-way / subdivision"
    competitor:
      status: yes
      note: "Parcel and ROW geometry"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: yes
      note: "Parcel subdivision (Sutherland-Hodgman clip, ROW dedication, setback insets)"
      evidence: "packages/kerf-civil/src/kerf_civil/parcels.py"

  - domain: D14
    feature: "Corridor modeling (templates / cross-sections)"
    competitor:
      status: yes
      note: "Template-driven corridor with dynamic cross-sections along alignment"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: partial
      note: "Alignment + profile + sheets shipped; no template-driven 3D corridor cross-section modeller"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/civil/alignment_tools.py"

  - domain: D14
    feature: "Utilities / multi-discipline coordination"
    competitor:
      status: yes
      note: "Survey + drainage + utilities + roadway in one application"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: partial
      note: "Drainage + water networks + roadway geometry; no dedicated dry-utility (power/comms) modeller"
      evidence: "packages/kerf-civil/src/kerf_civil/hydraulics_gravity.py"

  - domain: D1
    feature: "Open-source core / chat-native"
    competitor:
      status: no
      note: "Proprietary commercial license; no LLM interface"
      source: "https://www.bentley.com/software/openroads-designer/"
    kerf:
      status: yes
      note: "MIT open-core; chat-native civil design + JSON-RPC LLM tools + kerf-sdk"
      evidence: "packages/kerf-sdk/src/kerf/"
---

# Kerf vs Bentley OpenRoads Designer

Civil infrastructure & roadway design — compared honestly against MIT open-core.

*Last reviewed: 2026-06-05*

## Summary

Kerf saturates **91%** of Bentley OpenRoads Designer's feature surface (9 yes, 2 partial, 0 no out of 11 features tracked here). Honest gaps: 2 features partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Bentley OpenRoads Designer | Notes |
|---------|------|----------------------------|-------|
| Horizontal + vertical alignment (clothoid transitions) | ✅ | Yes | Horizontal (line/arc/spiral-clothoid) + vertical (tangent/parabolic) alignment + station-at |
| Digital terrain model (LiDAR / survey → DTM) | ✅ | Yes | Dynamic TIN (Bowyer-Watson Delaunay) + breaklines/boundary + volume-between |
| Point cloud / survey import (LAS) | ✅ | Yes | LAS/XYZ/PLY ingest + voxel downsample + PMF ground classification → TIN |
| Drainage / storm sewer (inlets, pipes, HGL/EGL) | ✅ | Yes | Gravity pipe network (Manning HGL/EGL + structure headloss + topological solve, ASCE MOP 36) |
| Pressure / water distribution networks | ✅ | Yes | Hardy-Cross / Global-Gradient water network solve + minor losses + pumps |
| Superelevation | ✅ | Yes | Superelevation calculation per AASHTO method |
| Plan & profile sheet production | ✅ | Yes | Automated plan+profile sheet set (station grid, profile band, match lines; AASHTO/FHWA) |
| Parcels / right-of-way / subdivision | ✅ | Yes | Parcel subdivision (Sutherland-Hodgman clip, ROW dedication, setback insets) |
| Corridor modeling (templates / cross-sections) | ⚠️ (partial) | Yes | Alignment + profile + sheets shipped; no template-driven 3D corridor cross-section modeller |
| Utilities / multi-discipline coordination | ⚠️ (partial) | Yes | Drainage + water networks + roadway geometry; no dedicated dry-utility (power/comms) modeller |
| Open-source core / chat-native | ✅ | No | MIT open-core; chat-native civil design + JSON-RPC LLM tools + kerf-sdk |

## What Kerf does that Bentley OpenRoads Designer doesn't

- **Open-source core / chat-native** — MIT open-core; chat-native civil design + JSON-RPC LLM tools + kerf-sdk

## What's honestly outstanding

- **Corridor modeling (templates / cross-sections)** (Partial): Alignment + profile + sheets shipped; no template-driven 3D corridor cross-section modeller
- **Utilities / multi-discipline coordination** (Partial): Drainage + water networks + roadway geometry; no dedicated dry-utility (power/comms) modeller

## Pricing

Bentley OpenRoads Designer is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
