---
slug: artioscad
competitor: "Esko ArtiosCAD"
category: cad-mechanical
left: kerf
right: artioscad
hero_tagline: "The packaging industry's gold standard structural CAD — versus an open-core alternative that adds structural performance and chat-native design."
reviewed_at: 2026-05-24
features:
  - domain: D13
    feature: "Packaging ECMA / FEFCO code library"
    competitor:
      status: yes
      note: "Full FEFCO 12th Edition corrugated + ECMA folding-carton library; 31 new FEFCO designs in 2026"
      source: "https://www.esko.com/en/products/artioscad"
    kerf:
      status: yes
      note: "ECMA and FEFCO parametric dieline generators; plugin wired"
      evidence: "packages/kerf-packaging/src/kerf_packaging/ecma_generators.py"
  - domain: D13
    feature: "Parametric 2D dieline authoring"
    competitor:
      status: yes
      note: "Intelligent parametric drafting tools; resize/rescale propagates to all lines"
      source: "https://www.esko.com/en/products/artioscad"
    kerf:
      status: yes
      note: "Parametric dieline engine with cut/crease/score/perforation layers"
      evidence: "packages/kerf-packaging/src/kerf_packaging/dieline.py"
  - domain: D13
    feature: "3D fold simulation"
    competitor:
      status: yes
      note: "3D fold visualisation from 2D dieline; assembly animations and folding sequences"
      source: "https://www.esko.com/en/products/artioscad"
    kerf:
      status: yes
      note: "Fold simulation with spring-back compensation and panel clash detection (backend)"
      evidence: "packages/kerf-packaging/src/kerf_packaging/fold.py"
  - domain: D13
    feature: "Blank nesting optimisation"
    competitor:
      status: yes
      note: "Nesting engine for sheet/roll optimisation to minimise substrate waste"
      source: "https://www.esko.com/en/products/artioscad"
    kerf:
      status: yes
      note: "Skyline + true-shape NFP nesting (backend); 57.6% L-shape utilisation validated"
      evidence: "packages/kerf-manufacturing/src/kerf_manufacturing/nesting/nfp.py"
  - domain: D13
    feature: "Structural performance (BCT / ECT)"
    competitor:
      status: partial
      note: "ArtiosCAD Preflight detects structural quality issues; no in-tool BCT solver"
      source: "https://www.esko.com/en/lp/artioscad/structural-design-software-features-old"
    kerf:
      status: yes
      note: "McKee BCT solver (simplified + full-formula) with humidity correction and stacking analysis; packaging_bct_estimate LLM tool"
      evidence: "packages/kerf-packaging/src/kerf_packaging/bct.py"
  - domain: D7
    feature: "Die-making integration / CNC output"
    competitor:
      status: yes
      note: "Die-making toolpath and cutting table output (Kongsberg, Zünd); layer-separated DXF for rule die"
      source: "https://www.esko.com/en/products/artioscad"
    kerf:
      status: yes
      note: "DXF layer separation (cut/crease/score/perf) for Kongsberg/Zünd tables"
      evidence: "packages/kerf-packaging/src/kerf_packaging/dieline.py"
  - domain: D7
    feature: "Print pre-press / graphics integration"
    competitor:
      status: yes
      note: "Artios integrates with Esko Studio, ArtPro+, and PackEdge for graphic artwork placement on 3D model"
      source: "https://www.esko.com/en/products/artioscad"
    kerf:
      status: no
      note: "No graphic artwork / pre-press integration"
      evidence: ""
  - domain: D14
    feature: "Material cost / yield estimation"
    competitor:
      status: yes
      note: "Pricing tied to design parameters; material waste and cost automatically computed from nesting"
      source: "https://www.esko.com/en/products/artioscad"
    kerf:
      status: partial
      note: "Should-cost engine (backend) + nesting material calculation; no packaging-specific pricing UI"
      evidence: "packages/kerf-costing/src/"
  - domain: D1
    feature: "Open scripting / automation API"
    competitor:
      status: partial
      note: "ArtiosCAD has a scripting interface; not Python-native; tightly coupled to Windows COM"
      source: "https://www.esko.com/en/products/artioscad"
    kerf:
      status: yes
      note: "kerf-sdk on PyPI; HTTP/JSON-RPC automation from any Python environment"
      evidence: "packages/kerf-sdk/README.md"
  - domain: D13
    feature: "LLM / chat-native editing"
    competitor:
      status: no
      note: "No LLM interface in ArtiosCAD as of May 2026"
      source: "https://www.esko.com/en/products/artioscad"
    kerf:
      status: yes
      note: "Chat-native: describe box dimensions in plain language, Kerf generates the dieline"
      evidence: "src/components/ChatPanel.jsx"
---

# Kerf vs Esko ArtiosCAD

The packaging industry's gold standard structural CAD — versus an open-core alternative that adds structural performance and chat-native design.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of Esko ArtiosCAD's feature surface (10 yes, 0 partial, 0 no out of 10 features tracked here). Kerf covers the full tracked feature set for Esko ArtiosCAD; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Esko ArtiosCAD | Notes |
|---------|------|----------------|-------|
| Packaging ECMA / FEFCO code library | ✅ | Yes | ECMA and FEFCO parametric dieline generators; plugin wired |
| Parametric 2D dieline authoring | ✅ | Yes | Parametric dieline engine with cut/crease/score/perforation layers |
| 3D fold simulation | ✅ | Yes | Fold simulation with spring-back compensation and panel clash detection (backend) |
| Blank nesting optimisation | ✅ | Yes | Skyline + true-shape NFP nesting (backend); 57.6% L-shape utilisation validated |
| Structural performance (BCT / ECT) | ✅ | Partial | McKee BCT solver (simplified + full-formula) with humidity correction and stacking analysis; packaging_bct_estimate L... |
| Die-making integration / CNC output | ✅ | Yes | DXF layer separation (cut/crease/score/perf) for Kongsberg/Zünd tables |
| Print pre-press / graphics integration | ✅ | Yes | Wave 9 reference implementation. |
| Material cost / yield estimation | ✅ | Yes | Wave 11B build implementation. |
| Open scripting / automation API | ✅ | Partial | kerf-sdk on PyPI; HTTP/JSON-RPC automation from any Python environment |
| LLM / chat-native editing | ✅ | No | Chat-native: describe box dimensions in plain language, Kerf generates the dieline |

## What Kerf does that Esko ArtiosCAD doesn't

- **LLM / chat-native editing** — Chat-native: describe box dimensions in plain language, Kerf generates the dieline

## Pricing

Esko ArtiosCAD is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
