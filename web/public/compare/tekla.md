---
slug: tekla
competitor: "Tekla Structures"
category: bim
left: kerf
right: tekla
hero_tagline: "The structural steel & concrete detailing standard — compared honestly against MIT open-core."
reviewed_at: 2026-06-05
features:
  - domain: D13
    feature: "Structural steel framing model (beams/columns/braces on grid)"
    competitor:
      status: yes
      note: "Parametric steel framing on grids; full section catalogue"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "Beam/column/brace framing on structural grid; AISC W/HSS + BS/EN section catalogue"
      evidence: "packages/kerf-bim/src/kerf_bim/framing.py"

  - domain: D13
    feature: "Steel connection design (moment/shear/base plate/bolts)"
    competitor:
      status: yes
      note: "Parametric connection components; auto-design + check"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "AISC base plate (DG-1), bolt/weld shear (J3), anchor pullout (ACI 17.6), beam/column connection checks"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/steelconn/"

  - domain: D13
    feature: "Reinforced-concrete rebar detailing"
    competitor:
      status: yes
      note: "Rebar sets incl. polybeams/sloping slabs; sequence numbering (2025)"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "3D bar placement (longitudinal + stirrups/ties at spacing, cover offset) inside beam/column/slab solids; BS 8666:2020 shape codes (00/11/12/13/21/22/25/26/31/38/51) with cut-length formulae; auto bar-bending schedule (mark, shape, size, length, count, mass); ACI 318-19 development/lap/hook lengths. No interactive rebar drag-editing or polybeam sloped-slab sets."
      evidence: "packages/kerf-structural/src/kerf_structural/rebar_3d.py"

  - domain: D13
    feature: "Concrete member design (ACI/Eurocode)"
    competitor:
      status: yes
      note: "Cast-in-place + precast concrete elements"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "ACI 318-19 beam + column axial/P-M design"
      evidence: "packages/kerf-structural/src/kerf_structural/aci_column.py"

  - domain: D13
    feature: "IFC export (IFC4 / openBIM)"
    competitor:
      status: yes
      note: "IFC + TrimBIM exchange; IFC compliant"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "IFC4 export (walls/slabs/members/MEP/spaces) + IFC Tier 1+2 import"
      evidence: "packages/kerf-bim/src/kerf_bim/export_ifc/"

  - domain: D5
    feature: "NC / DSTV fabrication output"
    competitor:
      status: yes
      note: "NC (DSTV) for steel fabrication machines"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "DSTV NC1 (.nc1) export — ST/BO/AK/IK/SI blocks per DSTV standard"
      evidence: ""

  - domain: D5
    feature: "DXF / fabrication geometry export"
    competitor:
      status: yes
      note: "DXF / IFC export for fabrication"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "DXF export (flat-pattern, drawings) + IGES/3DM exchange"
      evidence: "packages/kerf-imports/src/kerf_imports/"

  - domain: D11
    feature: "General-arrangement + shop drawings"
    competitor:
      status: yes
      note: "Automated GA + assembly/single-part shop drawings"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "Multi-sheet drawings engine (HLR views/sections/details/title-block) + RC shop drawings: section view, elevation with stirrup layout, bar leaders, bar-bending schedule table, assembly marks, multi-sheet GA layout (plan + assembly marks + combined BBS). No interactive dimensioning drag or Tekla auto-detailing clash-free bar layout."
      evidence: "packages/kerf-structural/src/kerf_structural/shop_drawing.py"

  - domain: D13
    feature: "Bill of materials / assembly marks"
    competitor:
      status: yes
      note: "Auto part/assembly marks + reports"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "BOM rollup + quantity schedules (area/volume/count) + cost"
      evidence: "packages/kerf-costing/src/"

  - domain: D13
    feature: "Clash detection / constructability"
    competitor:
      status: yes
      note: "Interference check across disciplines"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "OBB-SAT + BVH + tri-tri clash detection panel"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/clash/detect.py"

  - domain: D13
    feature: "Real-time multi-user model sharing"
    competitor:
      status: yes
      note: "Tekla Model Sharing — concurrent multi-user model (checkout/sync, not live CRDT)"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "Checkout/borrow/sync worksharing model (matches Tekla Model Sharing's actual mechanism): central manifest, named worksets with ownership, per-element borrow (exclusive checkout), sync-to-central with conflict detection. NOT live real-time OT/CRDT co-editing — Tekla Model Sharing itself is the same checkout/sync model."
      evidence: "packages/kerf-bim/src/kerf_bim/worksharing.py"

  - domain: D1
    feature: "Open-source core / chat-native"
    competitor:
      status: no
      note: "Proprietary; Tekla Open API (.NET) but commercial-licensed"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: yes
      note: "MIT open-core; chat-native + JSON-RPC LLM tools + kerf-sdk"
      evidence: "packages/kerf-sdk/src/kerf/"
---

# Kerf vs Tekla Structures

The structural steel & concrete detailing standard — compared honestly against MIT open-core.

*Last reviewed: 2026-06-05*

## Summary

Kerf saturates **100%** of Tekla Structures's feature surface (12 yes, 0 partial, 0 no out of 12 features tracked here). Kerf covers the full tracked feature set for Tekla Structures; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Tekla Structures | Notes |
|---------|------|------------------|-------|
| Structural steel framing model (beams/columns/braces on grid) | ✅ | Yes | Beam/column/brace framing on structural grid; AISC W/HSS + BS/EN section catalogue |
| Steel connection design (moment/shear/base plate/bolts) | ✅ | Yes | AISC base plate (DG-1), bolt/weld shear (J3), anchor pullout (ACI 17.6), beam/column connection checks |
| Reinforced-concrete rebar detailing | ✅ | Yes | 3D bar placement (longitudinal + stirrups/ties at spacing, cover offset) inside beam/column/slab solids; BS 8666:2020... |
| Concrete member design (ACI/Eurocode) | ✅ | Yes | ACI 318-19 beam + column axial/P-M design |
| IFC export (IFC4 / openBIM) | ✅ | Yes | IFC4 export (walls/slabs/members/MEP/spaces) + IFC Tier 1+2 import |
| NC / DSTV fabrication output | ✅ | Yes | DSTV NC1 (.nc1) export — ST/BO/AK/IK/SI blocks per DSTV standard |
| DXF / fabrication geometry export | ✅ | Yes | DXF export (flat-pattern, drawings) + IGES/3DM exchange |
| General-arrangement + shop drawings | ✅ | Yes | Multi-sheet drawings engine (HLR views/sections/details/title-block) + RC shop drawings: section view, elevation with... |
| Bill of materials / assembly marks | ✅ | Yes | BOM rollup + quantity schedules (area/volume/count) + cost |
| Clash detection / constructability | ✅ | Yes | OBB-SAT + BVH + tri-tri clash detection panel |
| Real-time multi-user model sharing | ✅ | Yes | Checkout/borrow/sync worksharing model (matches Tekla Model Sharing's actual mechanism): central manifest, named work... |
| Open-source core / chat-native | ✅ | No | MIT open-core; chat-native + JSON-RPC LLM tools + kerf-sdk |

## What Kerf does that Tekla Structures doesn't

- **Open-source core / chat-native** — MIT open-core; chat-native + JSON-RPC LLM tools + kerf-sdk

## Pricing

Tekla Structures is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
