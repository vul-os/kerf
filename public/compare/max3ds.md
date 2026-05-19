---
slug: max3ds
competitor: "Autodesk 3ds Max"
category: dcc
left: kerf
right: max3ds
hero_tagline: "Archviz & game-art DCC — a different category from B-rep CAD."
reviewed_at: 2026-05-19
order: 2
---

# Kerf vs Autodesk 3ds Max

3ds Max is the industry-standard DCC tool for architectural visualisation, game art, and VFX: mature poly modeling, a rich modifier stack, built-in Arnold rendering, and an unmatched plugin ecosystem (V-Ray, Corona, Forest Pack). It is not a B-rep parametric CAD application. If you are evaluating 3ds Max for product engineering, jewelry production, or electronics design work — or considering it alongside Kerf for a visualisation pipeline — this page lays out where the two tools overlap, where they diverge, and which belongs in your workflow.

**These are different categories of tool.** Kerf is a B-rep parametric CAD environment with multi-discipline scope (mechanical, electronics, jewelry, architecture). 3ds Max is a mesh-first DCC and production rendering platform. The overlap is real — jewelry hero rendering, archviz, and product visualisation — but the primary jobs are different.

## Where 3ds Max is strong

- **Arnold built-in path tracer.** Arnold (GPU/CPU) is a production-grade path tracer built directly into 3ds Max. The photorealistic output quality for archviz, product shots, and film VFX is a primary reason teams choose 3ds Max.
- **V-Ray, Corona, Redshift, Octane plugin ecosystem.** The render plugin ecosystem for 3ds Max is the most mature in the DCC world — V-Ray is the archviz industry standard, Corona is widely used for interiors, Redshift and Octane for film. Kerf has no render plugin API.
- **Mature Edit Poly and Modifier Stack.** Industry-standard Edit Poly modeling with a non-destructive Modifier Stack (TurboSmooth, Chamfer, Bevel, Bend, Bend, etc.) refined over 35+ years. Kerf's feature tree covers engineering operations but not this mesh-modifier depth.
- **Animation, rigging, and simulation.** Full skeletal animation, IK/FK, CAT rig, Biped, morph targets, particle systems, and cloth simulation — a complete animation pipeline. Kerf has no plans to replicate these.
- **Archviz material and plugin libraries.** Chaos Cosmos, Forest Pack, RailClone, and extensive material libraries are purpose-built for architectural visualisation workflows.
- **35+ year community and training.** Extensive tutorials, certification programs, and a large community of archviz and game-art practitioners.

## What 3ds Max is not (for engineering use)

- **Not a B-rep CAD kernel.** 3ds Max models are polygon meshes, not boundary-representation solids. No analytically exact planes, cylinders, or spline-trimmed surfaces.
- **No STEP B-rep round-trip.** STEP and IGES transfer B-rep geometry that machines and CAM systems expect. 3ds Max exports via FBX/DWG; there is no native B-rep STEP writer.
- **No GD&T or technical drawings.** Engineering drawings with ASME Y14.5 geometric dimensioning and tolerancing are out of scope for 3ds Max by design.
- **Modifier Stack ≠ parametric feature history.** 3ds Max's Modifier Stack is linear per-object and destructive once applied. It does not maintain persistent face IDs.
- **No electronics, no engineering-calc breadth.** There is no schematic editor, no PCB router, no BOM, no simulation pre-compliance.

## Where Kerf is positioned differently

- **B-rep solids with valid topology and tolerances.** Kerf's OCCT kernel produces exact boundary-representation solids whose faces, edges, and vertices carry stable IDs for downstream features, drawings, and CAM paths.
- **Parametric feature history DAG.** The feature tree (pad, pocket, revolve, loft, fillet, draft) is a persistent directed acyclic graph. Editing an early feature regenerates all downstream geometry.
- **Multi-discipline in one workspace.** Electronics (schematic + PCB + DRC + Gerber), jewelry (ring v4, gemstones v2, settings v3/v4, chain v2), 2D drawings, GD&T, CNC CAM, and architecture (IFC) share one environment.
- **STEP / IGES / 3DM B-rep interop.** Manufacturing and supply-chain tooling expects B-rep geometry. Kerf reads and writes STEP and IGES; 3ds Max cannot.
- **MIT open-core, with a hosted option.** The core is permissively MIT-licensed (3ds Max is a subscription product at ~$235/mo). A hosted SaaS version runs in the browser; a single binary installs locally on Windows, macOS, and Linux.
- **Chat-native workflow.** Describe a change in plain language; the LLM edits the feature tree directly, backed by live doc-search.

## Honest gaps — where 3ds Max wins

- **Render quality.** Arnold, V-Ray, Corona, Redshift — production path-traced output with caustics, volumetrics, dispersion, and motion blur. Kerf's heroShot renderer (HDRI + ACES + bloom) is not in the same class for production archviz or VFX.
- **Poly modeling and Modifier Stack depth.** Edit Poly + 35 years of mesh modifiers give 3ds Max an unmatched mesh-first modeling capability. Kerf covers engineering operations but not this breadth.
- **Animation and rigging.** Skeletal animation, NLA, cloth, particles — a complete film/game pipeline. Kerf has no plans here.
- **Render plugin ecosystem.** The V-Ray/Corona/Redshift/Octane plugin ecosystem has no Kerf counterpart. Kerf has no render plugin API.
- **Archviz material libraries and production workflows.** Purpose-built archviz tools (Chaos Cosmos, Forest Pack, RailClone) and established production workflows for interior and exterior visualisation.
- **Community and ecosystem depth.** 35+ years of accumulated tutorials, add-ons, and asset packs for archviz and game art.

## Side by side

| Feature | 3ds Max | Kerf |
|---|---|---|
| License | ⚠️ Autodesk subscription | ✅ MIT open-core |
| Cost | ⚠️ ~$235/mo or ~$1,875/yr | ✅ Free local binary; pay-as-you-go hosted |
| Platform | ⚠️ Windows desktop only | ✅ Browser + Win/macOS/Linux binary |
| Hosted / cloud | ❌ Desktop only | ✅ Hosted SaaS + local install |
| B-rep solid kernel | ⚠️ Mesh-first (Edit Poly) — no B-rep | ✅ OCCT B-rep — exact rational geometry |
| Parametric history | ⚠️ Linear Modifier Stack — not persistent face-ID DAG | ✅ OCCT feature tree + persistent face IDs |
| Constraint sketcher | ❌ None | ✅ Sketcher v2 — geometric + dimensional constraints |
| STEP / IGES B-rep interop | ⚠️ Via FBX/DWG; STEP plugin import only | ✅ STEP / IGES / 3DM B-rep round-trip |
| Built-in renderer | ✅ Arnold (GPU/CPU path tracer) | ⚠️ HDRI + ACES + bloom (heroShot); no path tracer |
| Third-party render plugins | ✅ V-Ray, Corona, Redshift, Octane | ❌ No render plugin API yet |
| Caustics / GI / dispersion | ✅ Production caustics via Arnold/V-Ray/Corona | ⚠️ In progress (jewelry use case) |
| PBR materials | ✅ Physical Material + Slate editor | ⚠️ PBR material library in progress |
| Archviz material libraries | ✅ Chaos Cosmos, Forest Pack, etc. | ❌ None |
| Edit Poly / Modifier Stack | ✅ Industry-standard mesh modeling | ⚠️ Mesh tools + quad remesh; no Modifier Stack |
| Animation / rigging | ✅ Full skeletal, IK/FK, CAT, particles | ❌ None |
| GD&T / tolerances | ❌ None | ✅ ASME Y14.5 datum + tolerance framework |
| 2D technical drawings | ❌ None | ✅ Multi-sheet drawings |
| Electronics / PCB | ❌ Not applicable | ✅ Full EDA — schematic, routing, DRC, Gerber/IPC-2581 |
| CNC CAM | ❌ None | ✅ 3-axis CAM + tool DB; 5-axis 3+2 |
| Chat / LLM editing | ❌ None | ✅ Chat-native — edits feature tree per turn |
| Scripting | ✅ MAXScript + Python 3 API | ✅ kerf-sdk on PyPI — HTTP/JSON-RPC |
