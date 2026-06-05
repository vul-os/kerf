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
      status: partial
      note: "Rebar detailing engine (bar schedule, development length) shipped; not full Tekla rebar-set / polybeam UI depth"
      evidence: "packages/kerf-structural/src/kerf_structural/rebar_detailing.py"

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
      status: no
      note: "No DSTV NC1 fabrication export for steel CNC machines yet"
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
      status: partial
      note: "Multi-sheet drawings (HLR views/sections/details/title-block) + shop drawings; not Tekla auto-detailing depth"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/drawings/"

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
      note: "Tekla Model Sharing — concurrent multi-user model"
      source: "https://www.tekla.com/products/tekla-structures"
    kerf:
      status: partial
      note: "Cloud git workspace (branch/merge/roles); not real-time element-level concurrent editing"
      evidence: "packages/kerf-cloud/"

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

Kerf saturates **79%** of Tekla Structures's feature surface (8 yes, 3 partial, 1 no out of 12 features tracked here). Honest gaps: 3 features partial (engine complete, UI or depth gap); 1 feature not yet implemented.

## Feature comparison

| Feature | Kerf | Tekla Structures | Notes |
|---------|------|------------------|-------|
| Structural steel framing model (beams/columns/braces on grid) | ✅ | Yes | Beam/column/brace framing on structural grid; AISC W/HSS + BS/EN section catalogue |
| Steel connection design (moment/shear/base plate/bolts) | ✅ | Yes | AISC base plate (DG-1), bolt/weld shear (J3), anchor pullout (ACI 17.6), beam/column connection checks |
| Reinforced-concrete rebar detailing | ⚠️ (partial) | Yes | Rebar detailing engine (bar schedule, development length) shipped; not full Tekla rebar-set / polybeam UI depth |
| Concrete member design (ACI/Eurocode) | ✅ | Yes | ACI 318-19 beam + column axial/P-M design |
| IFC export (IFC4 / openBIM) | ✅ | Yes | IFC4 export (walls/slabs/members/MEP/spaces) + IFC Tier 1+2 import |
| NC / DSTV fabrication output | 🔴 (no) | Yes | No DSTV NC1 fabrication export for steel CNC machines yet |
| DXF / fabrication geometry export | ✅ | Yes | DXF export (flat-pattern, drawings) + IGES/3DM exchange |
| General-arrangement + shop drawings | ⚠️ (partial) | Yes | Multi-sheet drawings (HLR views/sections/details/title-block) + shop drawings; not Tekla auto-detailing depth |
| Bill of materials / assembly marks | ✅ | Yes | BOM rollup + quantity schedules (area/volume/count) + cost |
| Clash detection / constructability | ✅ | Yes | OBB-SAT + BVH + tri-tri clash detection panel |
| Real-time multi-user model sharing | ⚠️ (partial) | Yes | Cloud git workspace (branch/merge/roles); not real-time element-level concurrent editing |
| Open-source core / chat-native | ✅ | No | MIT open-core; chat-native + JSON-RPC LLM tools + kerf-sdk |

## What Kerf does that Tekla Structures doesn't

- **Open-source core / chat-native** — MIT open-core; chat-native + JSON-RPC LLM tools + kerf-sdk

## What's honestly outstanding

- **Reinforced-concrete rebar detailing** (Partial): Rebar detailing engine (bar schedule, development length) shipped; not full Tekla rebar-set / polybeam UI depth
- **NC / DSTV fabrication output** (Not yet implemented): No DSTV NC1 fabrication export for steel CNC machines yet
- **General-arrangement + shop drawings** (Partial): Multi-sheet drawings (HLR views/sections/details/title-block) + shop drawings; not Tekla auto-detailing depth
- **Real-time multi-user model sharing** (Partial): Cloud git workspace (branch/merge/roles); not real-time element-level concurrent editing

## Pricing

Tekla Structures is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
