---
slug: shapr3d
competitor: "Shapr3D"
category: cad-mechanical
left: kerf
right: shapr3d
hero_tagline: "Direct + history-based modeling on iPad/desktop — compared honestly against MIT open-core."
reviewed_at: 2026-06-05
features:
  - domain: D1
    feature: "Constraint sketcher (geometric + dimensional)"
    competitor:
      status: yes
      note: "Fully/under-defined sketches; dimensional + geometric constraints (5.590)"
      source: "https://support.shapr3d.com/hc/en-us/articles/13444210101788"
    kerf:
      status: yes
      note: "PlaneGCS WASM constraint sketcher (geometric + dimensional)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/sketch.py"

  - domain: D1
    feature: "3D solid modeling (extrude/pocket/revolve/sweep/loft)"
    competitor:
      status: yes
      note: "Extrude (to-geometry), revolve, sweep, loft (start/end continuity)"
      source: "https://www.shapr3d.com/product/3d-modeling"
    kerf:
      status: yes
      note: "OCCT pad/pocket/revolve/sweep/loft (guide-rail, ruled/closed/symmetric)"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/feature_loft.py"

  - domain: D1
    feature: "Fillet / chamfer (variable, continuity blends)"
    competitor:
      status: yes
      note: "Fillet with Y-shape blends, tangent edges, overflow, G1/G2 continuity"
      source: "https://support.shapr3d.com/hc/en-us/articles/13444210101788"
    kerf:
      status: yes
      note: "Edge fillet + variable chamfer + G1/G2/G3 surface blend chains"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/fillet_solid.py"

  - domain: D1
    feature: "Direct modeling (move/offset face & edge)"
    competitor:
      status: yes
      note: "Core experience: select + move/offset faces/edges; edit imported geometry"
      source: "https://support.shapr3d.com/hc/en-us/articles/14030415438748"
    kerf:
      status: yes
      note: "push_pull (planar + curved) + move_face + offset_face + delete_face direct-edit ops"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/direct_edit.py"

  - domain: D1
    feature: "History-based parametric (feature tree + design intent)"
    competitor:
      status: yes
      note: "History-Based Parametric Modeling (out of beta 5.590, Apr 2024)"
      source: "https://www.shapr3d.com/content-library/shapr3d-history-based-parametric-modeling"
    kerf:
      status: yes
      note: "Parametric history DAG with persistent face naming (Kripac 1997) for stable replay"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/history/persistent_naming.py"

  - domain: D1
    feature: "Variables + expressions (parametric dimensions)"
    competitor:
      status: yes
      note: "Parametric design with variables and expressions"
      source: "https://support.shapr3d.com/hc/en-us/articles/18763796906396"
    kerf:
      status: yes
      note: "Global parameters / equations (.equations, mathjs) drive dimensions"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/sketch.py"

  - domain: D8
    feature: "STEP / IGES neutral import"
    competitor:
      status: yes
      note: "Import STEP, IGES, SLDPRT and other native formats"
      source: "https://www.shapr3d.com/product/3d-modeling"
    kerf:
      status: yes
      note: "STEP (AP203/214/242) + IGES 5.3 import"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/io/step_reader.py"

  - domain: D8
    feature: "STEP / STL / 3MF export"
    competitor:
      status: yes
      note: "Export X_T, STEP, STL, 3MF, DWG/DXF"
      source: "https://www.shapr3d.com/product/3d-modeling"
    kerf:
      status: yes
      note: "STEP + STL + 3MF + DXF export"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/io/step_writer.py"

  - domain: D8
    feature: "Parasolid (X_T) export"
    competitor:
      status: yes
      note: "Native Parasolid X_T export for downstream CAD"
      source: "https://www.shapr3d.com/product/3d-modeling"
    kerf:
      status: no
      note: "No Parasolid X_T export (requires licensed Parasolid kernel); STEP/IGES are the neutral path"
      evidence: ""

  - domain: D11
    feature: "2D drawings from 3D model"
    competitor:
      status: yes
      note: "DWG/DXF 2D documentation export"
      source: "https://www.shapr3d.com/product/3d-modeling"
    kerf:
      status: yes
      note: "HLR drawing sheets (views/sections/details/title-block) + DXF"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/drawings/"

  - domain: D1
    feature: "Open-source core / chat-native"
    competitor:
      status: no
      note: "Proprietary subscription; no LLM interface"
      source: "https://www.shapr3d.com/product/3d-modeling"
    kerf:
      status: yes
      note: "MIT open-core; chat-native modeling + JSON-RPC LLM tools + kerf-sdk"
      evidence: "packages/kerf-sdk/src/kerf/"
---

# Kerf vs Shapr3D

Direct + history-based modeling on iPad/desktop — compared honestly against MIT open-core.

*Last reviewed: 2026-06-05*

## Summary

Kerf saturates **91%** of Shapr3D's feature surface (10 yes, 0 partial, 1 no out of 11 features tracked here). Honest gaps: 1 feature not yet implemented.

## Feature comparison

| Feature | Kerf | Shapr3D | Notes |
|---------|------|---------|-------|
| Constraint sketcher (geometric + dimensional) | ✅ | Yes | PlaneGCS WASM constraint sketcher (geometric + dimensional) |
| 3D solid modeling (extrude/pocket/revolve/sweep/loft) | ✅ | Yes | OCCT pad/pocket/revolve/sweep/loft (guide-rail, ruled/closed/symmetric) |
| Fillet / chamfer (variable, continuity blends) | ✅ | Yes | Edge fillet + variable chamfer + G1/G2/G3 surface blend chains |
| Direct modeling (move/offset face & edge) | ✅ | Yes | push_pull (planar + curved) + move_face + offset_face + delete_face direct-edit ops |
| History-based parametric (feature tree + design intent) | ✅ | Yes | Parametric history DAG with persistent face naming (Kripac 1997) for stable replay |
| Variables + expressions (parametric dimensions) | ✅ | Yes | Global parameters / equations (.equations, mathjs) drive dimensions |
| STEP / IGES neutral import | ✅ | Yes | STEP (AP203/214/242) + IGES 5.3 import |
| STEP / STL / 3MF export | ✅ | Yes | STEP + STL + 3MF + DXF export |
| Parasolid (X_T) export | 🔴 (no) | Yes | No Parasolid X_T export (requires licensed Parasolid kernel); STEP/IGES are the neutral path |
| 2D drawings from 3D model | ✅ | Yes | HLR drawing sheets (views/sections/details/title-block) + DXF |
| Open-source core / chat-native | ✅ | No | MIT open-core; chat-native modeling + JSON-RPC LLM tools + kerf-sdk |

## What Kerf does that Shapr3D doesn't

- **Open-source core / chat-native** — MIT open-core; chat-native modeling + JSON-RPC LLM tools + kerf-sdk

## What's honestly outstanding

- **Parasolid (X_T) export** (Not yet implemented): No Parasolid X_T export (requires licensed Parasolid kernel); STEP/IGES are the neutral path

## Pricing

Shapr3D is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
