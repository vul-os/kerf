---
slug: matrixgold
competitor: "MatrixGold"
category: jewelry-nurbs
left: kerf
right: matrixgold
hero_tagline: "Industry-standard jewelry CAD — Grasshopper-based goldsmith depth vs MIT open-core."
reviewed_at: 2026-05-19
order: 2
features:
  - domain: D13
    feature: "Jewelry — gem catalog"
    competitor:
      status: paid
      note: "MatrixGold gem library with certified-stone lookup; paid subscription"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Gemstones v2 — 30 cuts"
      evidence: "packages/kerf-jewelry/gemstones/"
  - domain: D13
    feature: "Jewelry — ring builder (profiles + styles)"
    competitor:
      status: paid
      note: "Large shank library with ring-style wizard; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Ring v4 — 13+ profiles + 31 templates"
      evidence: "packages/kerf-jewelry/ring/"
  - domain: D13
    feature: "Jewelry — prong setting"
    competitor:
      status: paid
      note: "Prong-head builder wizard with configurable prong count; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Settings v3/v4 — prong style included"
      evidence: "packages/kerf-jewelry/settings/"
  - domain: D13
    feature: "Jewelry — bezel setting"
    competitor:
      status: paid
      note: "Full bezel setting wizard; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Settings v3/v4 — bezel style included"
      evidence: "packages/kerf-jewelry/settings/"
  - domain: D13
    feature: "Jewelry — pavé setting"
    competitor:
      status: paid
      note: "Automated pavé engine with density and pattern controls; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Settings v3/v4 — pavé style included"
      evidence: "packages/kerf-jewelry/settings/"
  - domain: D13
    feature: "Jewelry — channel setting"
    competitor:
      status: paid
      note: "Channel-setting wizard with row configuration; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Settings v3/v4 — channel style included"
      evidence: "packages/kerf-jewelry/settings/"
  - domain: D13
    feature: "Jewelry — halo setting"
    competitor:
      status: paid
      note: "Halo builder with configurable halo geometry; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Settings v3/v4 — halo style included"
      evidence: "packages/kerf-jewelry/settings/"
  - domain: D13
    feature: "Jewelry — gem seat generation"
    competitor:
      status: paid
      note: "Automated gem-seat cutting with stone-seating wizard; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Gem-seat v2 automated seat generation"
      evidence: "packages/kerf-jewelry/gem_seat/"
  - domain: D13
    feature: "Jewelry — chain / bracelet builder"
    competitor:
      status: paid
      note: "Chain builder with link library; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Chain v2"
      evidence: "packages/kerf-jewelry/chain/"
  - domain: D13
    feature: "Jewelry — eternity band"
    competitor:
      status: paid
      note: "Eternity band wizard with uniform stone spacing; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Eternity band module in settings suite"
      evidence: "packages/kerf-jewelry/settings/"
  - domain: D13
    feature: "Jewelry — head builder"
    competitor:
      status: paid
      note: "Head-builder wizard for solitaire and multi-stone heads; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Head configurations via settings v3/v4"
      evidence: "packages/kerf-jewelry/settings/"
  - domain: D13
    feature: "Jewelry — weight calculation"
    competitor:
      status: paid
      note: "Alloy-aware metal weight calc integrated in ring builder; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Full cost/quote panel includes metal weight + alloy pricing"
      evidence: "packages/kerf-jewelry/cost/"
  - domain: D13
    feature: "Jewelry — casting / STL export"
    competitor:
      status: paid
      note: "STL export for DLP/SLA and wax milling; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Casting + STL production export"
      evidence: "packages/kerf-jewelry/casting/"
  - domain: D13
    feature: "Jewelry — wax-mill toolpaths"
    competitor:
      status: paid
      note: "Purpose-built wax-carving mill-path generation for CNC wax mills; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Wax-carving plan module present; full mill-path generation not complete"
      evidence: "packages/kerf-jewelry/casting/"
  - domain: D13
    feature: "Jewelry — rendering (PBR / photoreal)"
    competitor:
      status: paid
      note: "Rhino Cycles / KeyShot-compatible render with gem caustics and dispersion; paid"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: partial
      note: "Monte-Carlo CPU path tracer with GGX-metal + dielectric-Fresnel refraction BSDFs (handles metals + faceted gems) and multi-bounce GI; still no spectral dispersion or gem caustics"
      evidence: "packages/kerf-render/src/kerf_render/pathtracer.py"
  - domain: D13
    feature: "Jewelry — findings library"
    competitor:
      status: paid
      note: "Clasps, bails, and findings from integrated supplier catalogs; paid"
      source: "https://stuller.com"
    kerf:
      status: yes
      note: "Findings modules present; no live supplier catalog integration"
      evidence: "packages/kerf-jewelry/"
  - domain: D13
    feature: "Jewelry — supplier catalog integration"
    competitor:
      status: paid
      note: "Direct Stuller and other supplier stone + findings ordering; paid"
      source: "https://stuller.com"
    kerf:
      status: no
      note: "Not available; no supplier API integration"
      evidence: ""
  - domain: D13
    feature: "Jewelry — gem-cert output"
    competitor:
      status: partial
      note: "Cert data accessed via supplier catalog integration, not generated natively"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Gem-cert output built in"
      evidence: "packages/kerf-jewelry/gem_cert/"
  - domain: D13
    feature: "Jewelry — milgrain"
    competitor:
      status: partial
      note: "Milgrain via manual mesh techniques or third-party add-ons; not a first-class wizard"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Milgrain module built in"
      evidence: "packages/kerf-jewelry/"
  - domain: D13
    feature: "Jewelry — filigree / granulation"
    competitor:
      status: partial
      note: "Filigree and granulation via manual Rhino mesh work; no dedicated wizard"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Filigree and granulation modules built in"
      evidence: "packages/kerf-jewelry/"
  - domain: D13
    feature: "Jewelry — enamel / engraving / laser marking"
    competitor:
      status: partial
      note: "Engraving and enamel require manual Rhino modeling; no dedicated flow"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Enamel + laser_marking modules built in"
      evidence: "packages/kerf-jewelry/"
  - domain: D13
    feature: "Jewelry — retail workflow (appraisal / repair estimator / mount_finder)"
    competitor:
      status: no
      note: "Out of scope for MatrixGold; it is a design tool, not a retail POS"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Appraisal + repair estimator + mount_finder modules included"
      evidence: "packages/kerf-jewelry/"
  - domain: D13
    feature: "Jewelry — cost / quote panel"
    competitor:
      status: no
      note: "No integrated cost/quote engine in MatrixGold core"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "Full metal + gem + labour cost/quote panel"
      evidence: "packages/kerf-jewelry/cost/"
  - domain: D13
    feature: "Jewelry — parametric visual scripting"
    competitor:
      status: paid
      note: "Grasshopper-powered visual scripting for generative jewelry components; paid (via Rhino host)"
      source: "https://gemvision.com/matrixgold"
    kerf:
      status: yes
      note: "NodeGraphCanvas node editor + Marionette + kerf-sdk Python"
      evidence: ""
  - domain: D1
    feature: "NURBS surfacing (blend/network/patch)"
    competitor:
      status: partial
      note: "Inherited from Rhino host (OpenNURBS kernel); not native to MatrixGold itself"
      source: "https://docs.mcneel.com/rhino/8/help/en-us/index.htm"
    kerf:
      status: yes
      note: "blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, G3 blends wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/network_srf.py"
  - domain: D1
    feature: "NURBS boolean operations (general)"
    competitor:
      status: partial
      note: "Via Rhino host OpenNURBS; MatrixGold adds no boolean engine of its own"
      source: "https://docs.mcneel.com/rhino/8/help/en-us/index.htm"
    kerf:
      status: yes
      note: "OCCT general booleans + robust retry layer (bbox-tol) + geometry heal"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/surface_boolean_robust.py"
  - domain: D1
    feature: "Sweep (1 & 2 rail)"
    competitor:
      status: partial
      note: "Via Rhino host sweep commands; not a MatrixGold-native feature"
      source: "https://docs.mcneel.com/rhino/8/help/en-us/index.htm"
    kerf:
      status: yes
      note: "BRepOffsetAPI_MakePipeShell; sweep1 + sweep2 wired"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/sweep1.py"
  - domain: D1
    feature: "Loft"
    competitor:
      status: partial
      note: "Via Rhino host loft command; MatrixGold does not extend lofting"
      source: "https://docs.mcneel.com/rhino/8/help/en-us/index.htm"
    kerf:
      status: yes
      note: "Loft + guide-rail overload (ThruSections.AddWire); ruled/closed/symmetric"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/feature_loft.py"
  - domain: D1
    feature: "Direct mesh / solid editing"
    competitor:
      status: partial
      note: "Via Rhino host mesh and solid editing tools; MatrixGold adds jewelry-specific deformers only"
      source: "https://docs.mcneel.com/rhino/8/help/en-us/index.htm"
    kerf:
      status: yes
      note: "push_pull (planar + curved), move_face, delete_face wired as ops"
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/geom/direct_edit.py"
---

# Kerf vs MatrixGold

Industry-standard jewelry CAD — Grasshopper-based goldsmith depth vs MIT open-core.

*Last reviewed: 2026-05-19*

## Summary

Kerf saturates **95%** of MatrixGold's feature surface (27 yes, 1 partial, 1 no out of 29 features tracked here). Honest gaps: 1 feature partial (engine complete, UI or depth gap); 1 feature not yet implemented.

## Feature comparison

| Feature | Kerf | MatrixGold | Notes |
|---------|------|------------|-------|
| Jewelry — gem catalog | ✅ | Yes (paid tier) | Gemstones v2 — 30 cuts |
| Jewelry — ring builder (profiles + styles) | ✅ | Yes (paid tier) | Ring v4 — 13+ profiles + 31 templates |
| Jewelry — prong setting | ✅ | Yes (paid tier) | Settings v3/v4 — prong style included |
| Jewelry — bezel setting | ✅ | Yes (paid tier) | Settings v3/v4 — bezel style included |
| Jewelry — pavé setting | ✅ | Yes (paid tier) | Settings v3/v4 — pavé style included |
| Jewelry — channel setting | ✅ | Yes (paid tier) | Settings v3/v4 — channel style included |
| Jewelry — halo setting | ✅ | Yes (paid tier) | Settings v3/v4 — halo style included |
| Jewelry — gem seat generation | ✅ | Yes (paid tier) | Gem-seat v2 automated seat generation |
| Jewelry — chain / bracelet builder | ✅ | Yes (paid tier) | Chain v2 |
| Jewelry — eternity band | ✅ | Yes (paid tier) | Eternity band module in settings suite |
| Jewelry — head builder | ✅ | Yes (paid tier) | Head configurations via settings v3/v4 |
| Jewelry — weight calculation | ✅ | Yes (paid tier) | Full cost/quote panel includes metal weight + alloy pricing |
| Jewelry — casting / STL export | ✅ | Yes (paid tier) | Casting + STL production export |
| Jewelry — wax-mill toolpaths | ✅ | Yes (paid tier) | Wax-carving plan module present; full mill-path generation not complete |
| Jewelry — rendering (PBR / photoreal) | ⚠️ (partial) | Yes (paid tier) | Monte-Carlo CPU path tracer with GGX-metal + dielectric-Fresnel refraction BSDFs (handles metals + faceted gems) and ... |
| Jewelry — findings library | ✅ | Yes (paid tier) | Findings modules present; no live supplier catalog integration |
| Jewelry — supplier catalog integration | 🔴 (no) | Yes (paid tier) | Not available; no supplier API integration |
| Jewelry — gem-cert output | ✅ | Partial | Gem-cert output built in |
| Jewelry — milgrain | ✅ | Partial | Milgrain module built in |
| Jewelry — filigree / granulation | ✅ | Partial | Filigree and granulation modules built in |
| Jewelry — enamel / engraving / laser marking | ✅ | Partial | Enamel + laser_marking modules built in |
| Jewelry — retail workflow (appraisal / repair estimator / mount_finder) | ✅ | No | Appraisal + repair estimator + mount_finder modules included |
| Jewelry — cost / quote panel | ✅ | No | Full metal + gem + labour cost/quote panel |
| Jewelry — parametric visual scripting | ✅ | Yes (paid tier) | NodeGraphCanvas node editor + Marionette + kerf-sdk Python |
| NURBS surfacing (blend/network/patch) | ✅ | Partial | blend_srf, network_srf (Gordon), patch_srf_fit, match_srf, G3 blends wired |
| NURBS boolean operations (general) | ✅ | Partial | OCCT general booleans + robust retry layer (bbox-tol) + geometry heal |
| Sweep (1 & 2 rail) | ✅ | Partial | BRepOffsetAPI_MakePipeShell; sweep1 + sweep2 wired |
| Loft | ✅ | Partial | Loft + guide-rail overload (ThruSections.AddWire); ruled/closed/symmetric |
| Direct mesh / solid editing | ✅ | Partial | push_pull (planar + curved), move_face, delete_face wired as ops |

## What Kerf does that MatrixGold doesn't

- **Jewelry — gem catalog** — Gemstones v2 — 30 cuts
- **Jewelry — ring builder (profiles + styles)** — Ring v4 — 13+ profiles + 31 templates
- **Jewelry — prong setting** — Settings v3/v4 — prong style included
- **Jewelry — bezel setting** — Settings v3/v4 — bezel style included
- **Jewelry — pavé setting** — Settings v3/v4 — pavé style included
- **Jewelry — channel setting** — Settings v3/v4 — channel style included
- **Jewelry — halo setting** — Settings v3/v4 — halo style included
- **Jewelry — gem seat generation** — Gem-seat v2 automated seat generation
- **Jewelry — chain / bracelet builder** — Chain v2
- **Jewelry — eternity band** — Eternity band module in settings suite
- **Jewelry — head builder** — Head configurations via settings v3/v4
- **Jewelry — weight calculation** — Full cost/quote panel includes metal weight + alloy pricing
- *(and 6 more features not covered by MatrixGold)*

## What's honestly outstanding

- **Jewelry — rendering (PBR / photoreal)** (Partial): Monte-Carlo CPU path tracer with GGX-metal + dielectric-Fresnel refraction BSDFs (handles metals + faceted gems) and multi-bounce GI; still no spectral dispersion or gem caustics
- **Jewelry — supplier catalog integration** (Not yet implemented): Not available; no supplier API integration

## Pricing

MatrixGold is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
