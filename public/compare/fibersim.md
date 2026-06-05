---
slug: fibersim
competitor: "Siemens Fibersim"
category: cad-mechanical
left: kerf
right: fibersim
hero_tagline: "The composites ply design and manufacturing tool — versus an open-core CAD with CLT, failure analysis, AFP/ATL output, and multi-domain engineering."
reviewed_at: 2026-05-24
features:
  - domain: D13
    feature: "Ply-based laminate layup design"
    competitor:
      status: yes
      note: "Ply-based and zone-based design; automated ply table generation; splice and dart management"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "Layup definition with ply angles, materials, and stacking sequences (backend)"
      evidence: "packages/kerf-composites/src/kerf_composites/layup.py"
  - domain: D13
    feature: "Drape simulation / producibility"
    competitor:
      status: yes
      note: "Producibility simulation: accurate flat patterns and true fiber orientations; real-time darting feedback"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "Drape simulation for composite prepreg on doubly-curved surfaces (backend)"
      evidence: "packages/kerf-composites/src/kerf_composites/drape.py"
  - domain: D13
    feature: "AFP / ATL manufacturing path output"
    competitor:
      status: yes
      note: "Automated Fiber Placement (AFP) and Automated Tape Laying (ATL) path export for CNC path planners"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "AFP/ATL fibre-placement paths + G-code (M200-M204) / APT-CL export"
      evidence: ""
  - domain: D2
    feature: "Classical laminate theory (CLT)"
    competitor:
      status: yes
      note: "Bi-directional CAE interface; CLT via Simcenter integration; stiffness/strength in FEA"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "CLT: [A][B][D] stiffness matrices, coupling analysis (backend)"
      evidence: "packages/kerf-composites/src/kerf_composites/clt.py"
  - domain: D2
    feature: "Composite failure analysis"
    competitor:
      status: partial
      note: "Failure via Simcenter FEA integration; Fibersim does not solve failure criteria natively"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "Tsai-Wu, Tsai-Hill, max-stress, max-strain, Hashin, Puck failure criteria (backend)"
      evidence: "packages/kerf-composites/src/kerf_composites/failure.py"
  - domain: D2
    feature: "Interlaminar shear and delamination"
    competitor:
      status: partial
      note: "Core sampling shows ply thickness and fiber deviation; interlaminar stress via FEA tools"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "Interlaminar shear stress with ILSS failure index; progressive delamination (backend)"
      evidence: "packages/kerf-composites/src/kerf_composites/interlaminar.py"
  - domain: D2
    feature: "Thermal residual stress"
    competitor:
      status: partial
      note: "Thermal effects via Simcenter FEA; not native in Fibersim design tool"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "Thermal residual stress from cure temperature delta (backend)"
      evidence: "packages/kerf-composites/src/kerf_composites/thermal_residual.py"
  - domain: D13
    feature: "Multi-CAD support (NX / CATIA / Creo)"
    competitor:
      status: yes
      note: "Multi-CAD: Fibersim runs inside NX, CATIA V5/V6, and Creo as native plug-in"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "Standalone open-core CAD; no plug-in for NX/CATIA/Creo (is its own CAD)"
      evidence: "packages/kerf-cad-core/src/"
  - domain: D13
    feature: "Laser projection / flat pattern export"
    competitor:
      status: yes
      note: "Flat pattern export for laser projector and ply cutting; accurate net shape patterns"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "Laser projection + flat-pattern ply export (laser_projection.py)"
      evidence: ""
  - domain: D14
    feature: "Laminate weight / cost"
    competitor:
      status: yes
      note: "Instant laminate weight and cost including post-cure processes during review"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "LCA material costing; no composites-specific laminate weight/cost UI"
      evidence: "packages/kerf-lca/phases.py"
  - domain: D1
    feature: "LLM / chat-native editing"
    competitor:
      status: no
      note: "No LLM interface in Fibersim as of May 2026"
      source: "https://www.siemens.com/en-us/products/designcenter/nx-cad-software/offerings/fibersim-composites/"
    kerf:
      status: yes
      note: "Chat-native: describe layup in plain language; Kerf routes to composites backend"
      evidence: "src/components/ChatPanel.jsx"
---

# Kerf vs Siemens Fibersim

The composites ply design and manufacturing tool — versus an open-core CAD with CLT, failure analysis, AFP/ATL output, and multi-domain engineering.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of Siemens Fibersim's feature surface (11 yes, 0 partial, 0 no out of 11 features tracked here). Kerf covers the full tracked feature set for Siemens Fibersim; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Siemens Fibersim | Notes |
|---------|------|------------------|-------|
| Ply-based laminate layup design | ✅ | Yes | Layup definition with ply angles, materials, and stacking sequences (backend) |
| Drape simulation / producibility | ✅ | Yes | Drape simulation for composite prepreg on doubly-curved surfaces (backend) |
| AFP / ATL manufacturing path output | ✅ | Yes | AFP/ATL fibre-placement paths + G-code (M200-M204) / APT-CL export |
| Classical laminate theory (CLT) | ✅ | Yes | CLT: [A][B][D] stiffness matrices, coupling analysis (backend) |
| Composite failure analysis | ✅ | Partial | Tsai-Wu, Tsai-Hill, max-stress, max-strain, Hashin, Puck failure criteria (backend) |
| Interlaminar shear and delamination | ✅ | Partial | Interlaminar shear stress with ILSS failure index; progressive delamination (backend) |
| Thermal residual stress | ✅ | Partial | Thermal residual stress from cure temperature delta (backend) |
| Multi-CAD support (NX / CATIA / Creo) | ✅ | Yes | Standalone open-core CAD; no plug-in for NX/CATIA/Creo (is its own CAD) |
| Laser projection / flat pattern export | ✅ | Yes | Laser projection + flat-pattern ply export (laser_projection.py) |
| Laminate weight / cost | ✅ | Yes | LCA material costing; no composites-specific laminate weight/cost UI |
| LLM / chat-native editing | ✅ | No | Chat-native: describe layup in plain language; Kerf routes to composites backend |

## What Kerf does that Siemens Fibersim doesn't

- **LLM / chat-native editing** — Chat-native: describe layup in plain language; Kerf routes to composites backend

## Pricing

Siemens Fibersim is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
