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

Esko ArtiosCAD is the structural packaging industry's dominant platform — with well over 30,000 users worldwide in corrugated, folding carton, and point-of-purchase display production. It ships the complete FEFCO 12th Edition corrugated library (400+ styles), parametric dieline authoring, 3D fold simulation, blank nesting, and deep integration with Esko's prepress ecosystem (Studio, ArtPro+). It is the de-facto standard in packaging converters and CPG structural teams. Kerf is the open-core alternative: same ECMA/FEFCO dieline generation, fold simulation, and nesting — plus structural performance analysis, chat-native design, and a Python scripting API.

## Where ArtiosCAD is strong

- **Prepress ecosystem integration.** ArtiosCAD sits inside the Esko universe — artwork placement on 3D structural models, direct round-trip to ArtPro+ and PackEdge, folding-sequence animations for brand approval. There is no open-source equivalent.
- **Rule die and cutting table workflows.** ArtiosCAD's die-making tools and stock post processors for Kongsberg and Zünd tables are deeply production-proven in converter shops worldwide.
- **FEFCO 12th Edition library completeness.** ArtiosCAD ships the complete FEFCO corrugated catalogue — 400+ parametric styles. Kerf covers the most common styles; the long tail of specialist styles is not yet there.
- **Enterprise project management.** ArtiosCAD Enterprise Browser (server edition) tracks linked documents, design reuse, and project dependencies across large teams — purpose-built for converter operations.
- **Preflight quality checking.** ArtiosCAD Preflight detects structural design issues (minimum glue area, panel clearances, grain direction violations) before production — patent-pending technology.

## Where Kerf differs

- **MIT open-core.** ArtiosCAD is proprietary; licensing is enterprise-priced (not publicly listed). Kerf is MIT-licensed — free locally, hosted credits from $9/mo.
- **Structural performance (BCT).** Kerf's BCT solver implements the McKee (1963) formula — both simplified (BCT = k·ECT·√(b·h)) and full formula (α=0.492, β=0.508 exponents) — with humidity-correction factors (dry/normal/humid/wet) derived from TAPPI guidance and stacking analysis with configurable safety factors. ArtiosCAD does not solve BCT natively (it leans on Esko's separate Taurus simulation for this).
- **Chat-native.** Describe a box in plain language: "A telescoping retail box for a 300 × 200 × 50 mm product in E-flute" and Kerf generates the ECMA dieline, nests blanks on a 1200 × 2400 mm sheet, and quotes material cost. ArtiosCAD has no LLM interface.
- **Python automation API.** kerf-sdk on PyPI enables scripted dieline generation and nesting for automated packaging specification workflows. ArtiosCAD's scripting is Windows COM — not portable.
- **Multi-domain workspace.** Packaging engineers designing integrated rigid-flex electronics for smart packaging can combine Kerf's dieline tools with its PCB schematic layer and firmware IDE in one project.

## Honest gaps — where Kerf is behind today

- **Prepress / artwork integration.** No graphic overlay, no 3D mockup with brand artwork, no pre-press round-trip. For artwork-structural-print convergence, ArtiosCAD + Esko Studio is unmatched.
- **FEFCO long-tail styles.** ArtiosCAD's 400+ FEFCO/ECMA library dwarfs Kerf's current coverage of common styles.
- **BCT browser UI.** BCT estimation is implemented in the backend and exposed as the ``packaging_bct_estimate`` LLM tool; a dedicated browser panel with visual stacking analysis is a frontend roadmap item.
- **Converter-shop workflow.** ArtiosCAD has 30 years of workflow depth in converter operations — job tracking, delivery specification, die registration. Kerf has none of this.

## Side by side

| Feature | Kerf | Esko ArtiosCAD |
|---|---|---|
| License | MIT open-core | Proprietary (enterprise pricing) |
| Primary focus | Multi-domain engineering CAD | Structural packaging CAD |
| ECMA / FEFCO library | Common styles | Full FEFCO 12th Ed. (400+ styles) |
| 3D fold simulation | Yes (backend) | Yes |
| Blank nesting | Yes (backend) | Yes |
| BCT structural analysis | McKee solver + humidity + stacking | Not native (third-party Taurus) |
| Prepress / artwork | No | Full Esko ecosystem |
| CNC / cutting table output | DXF layer-separated | Full post processors |
| Chat / LLM editing | Chat-native | None |
| Python scripting | kerf-sdk on PyPI | Windows COM only |
| Open source | Yes (MIT) | No |

---
*Last reviewed: 2026-05-24. Competitor information sourced from public Esko/ArtiosCAD product pages. Kerf capabilities reflect the current shipped product.*
