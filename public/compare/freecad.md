---
slug: freecad
competitor: "FreeCAD"
category: cad-mechanical
left: kerf
right: freecad
hero_tagline: "Open-source parametric B-rep modeller — LGPL vs MIT, desktop vs cloud."
reviewed_at: 2026-05-19
order: 1
---

# Kerf vs FreeCAD

FreeCAD reached 1.0 in November 2024 after ~20 years of development: a genuinely mature, LGPL, desktop parametric CAD package with a built-in Assembly workbench, FEM (CalculiX/Elmer/Z88/Mystran), a rewritten CAM ecosystem, and hundreds of community workbenches. Kerf is far younger and narrower in ecosystem — but adds a chat-native workflow, an MIT open-core licence, a hosted option, and integrated electronics and jewelry in one workspace. Below is an honest look at both.

## Where FreeCAD is strong

- **Mature, proven parametric modelling.** The Part Design and Sketcher workbenches have been refined for roughly two decades. FreeCAD 1.0 largely resolved the long-standing topological-naming problem for Sketcher and Part Design.
- **Built-in Assembly workbench.** FreeCAD 1.0 ships a first-party Assembly workbench with a modern constraint solver — no longer a third-party add-on. Kerf's assembly mates are newer and less battle-tested.
- **Real FEM simulation.** The FEM workbench drives CalculiX, Elmer, Z88, and Mystran for structural (static, modal, buckling) and thermal analysis — a depth Kerf has not yet matched.
- **Hundreds of community workbenches.** SheetMetal, Path/CAM, Arch/BIM, FEM, Render, and many more. If a specialised workflow exists, there is usually a workbench for it.
- **Deep, in-process Python API.** FreeCAD's scripting surface covers virtually every internal object type, with an enormous body of macros and documentation.
- **Completely free, fully offline.** No subscription, no account, no cloud dependency — Windows, macOS, and Linux desktop.
- **Broad, certified interoperability.** STEP, IGES, DXF, IFC, STL, OBJ, and BREP import/export are well-exercised across a huge user base.

## Where Kerf differs

- **Chat-native workflow.** Every design turn can be driven by a chat message; the model edits the underlying source (feature tree / JSCAD) directly, backed by live doc-search so it does not invent API surface.
- **Electronics + mechanical in one workspace.** Kerf includes a full EDA stack — schematic, routing, DRC, Gerber / IPC-2581 fab pack — alongside B-rep CAD. FreeCAD offers only an IDF MCAD bridge to an external EDA tool.
- **MIT open-core, with a hosted option.** The core is permissively MIT-licensed (FreeCAD is copyleft LGPL). A hosted SaaS version runs in the browser; a single binary installs locally via brew or curl.
- **kerf-sdk on PyPI.** Python scripting over HTTP/JSON-RPC from your own machine — the same interface the LLM uses internally, so scripts are first-class and out-of-process rather than an embedded console.
- **Jewelry built in.** Gemstones v2 (30 cuts), settings v3/v4, gem-seat v2, ring v4, chain v2, findings, casting export, and a 31-template library — a domain FreeCAD has no native tooling for.
- **GD&T to ASME Y14.5.** A full datum and tolerance framework, where FreeCAD's TechDraw offers comparatively basic annotation.
- **Every project is a real git repo.** Projects are cloneable git repositories with large-file handling, near-free forks, optional GitHub or GitLab mirror, and CLI sync.
- **Full mechanical joint system.** Rigid, revolute, slider, cam, gear, and pin-slot joints are all available, bringing Kerf's assembly depth much closer to FreeCAD's built-in Assembly workbench.

## Honest gaps — where Kerf is behind today

- **FEM depth is narrower.** Kerf ships linear static, thermal, and nonlinear plasticity FEM, but FreeCAD's workbench (CalculiX/Elmer/Z88/Mystran) covers more solver types, boundary conditions, and multi-physics coupling. CFD (OpenFOAM via CfdOF) is not in Kerf at all.
- **Far smaller ecosystem.** FreeCAD has hundreds of community workbenches and ~20 years of accumulated tooling. Kerf's plugin API is early-stage.
- **Less community and documentation.** FreeCAD has a decade-old forum, wiki, and YouTube ecosystem. Kerf is young and the documentation is still growing.
- **No IFC export.** FreeCAD exports IFC. Kerf imports IFC at Tier 2 but does not yet export IFC.

## Side by side

| Feature | FreeCAD | Kerf |
|---|---|---|
| License | ✅ LGPL v2.1+ (free, copyleft) | ✅ MIT open-core (permissive) |
| Cost | ✅ Free, no subscription | ✅ Free local binary; pay-as-you-go hosted |
| Platform | ✅ Win / macOS / Linux desktop | ✅ Browser + single-binary local |
| Hosted / cloud | ❌ Desktop only | ✅ Hosted SaaS + local install |
| Maturity | ✅ 1.0 in 2024, ~20 yr history | ⚠️ Early-stage, < 2 yr public |
| Parametric B-rep | ✅ Part Design WB (OCCT) | ✅ OCCT feature tree — pad/pocket/revolve/loft |
| Constraint sketcher | ✅ Sketcher WB (mature solver) | ✅ Sketcher v2 — all major constraints |
| Topological naming | ✅ Largely fixed in 1.0 | ✅ Persistent face names (Phase 4) |
| NURBS surfacing | ⚠️ Surface WB (limited) | ⚠️ NURBS Phase 4 (early) |
| Sheet metal | ✅ SheetMetal WB (community) | ✅ Flange + unfold + flat-pattern DXF |
| Assembly / mates | ✅ Built-in Assembly WB (1.0, new solver) | ✅ Full joint system — rigid/revolute/slider/cam/gear/pin-slot |
| 2D technical drawings | ✅ TechDraw WB | ✅ Multi-sheet drawings |
| GD&T | ⚠️ TechDraw annotations (basic) | ✅ ASME Y14.5 datum + tolerance framework |
| CNC CAM | ✅ CAM/Path WB (rewritten in 1.1) | ✅ 3-axis CAM + tool DB; 5-axis 3+2 |
| Slicing / 3D print | ⚠️ Via external slicer | ✅ Slicing Tier 1 built in |
| FEM (structural / thermal) | ✅ FEM WB — CalculiX / Elmer / Z88 / Mystran | ⚠️ Linear static + thermal; not full parity |
| CFD | ⚠️ CfdOF add-on (OpenFOAM) | ❌ Not yet |
| Electronics / PCB | ⚠️ IDF MCAD bridge only | ✅ Full EDA — schematic, routing, DRC, Gerber/IPC-2581 |
| Jewelry | ❌ No native jewelry tooling | ✅ Gemstones v2, settings v3/v4, ring v4, chain v2 |
| Architecture / BIM | ✅ Arch + BIM WB, IFC import/export | ⚠️ IFC Tier 2 import; IFC export in progress |
| Python scripting | ✅ Deep in-process macro/console API | ✅ kerf-sdk on PyPI — HTTP/JSON-RPC |
| Chat / LLM editing | ❌ None | ✅ Chat-native — edits source per turn |
| Plugin ecosystem | ✅ Hundreds of community workbenches | ⚠️ Early — open-core + plugin API |
| Import formats | ✅ STEP/IGES/DXF/IFC/STL/OBJ/BREP | ✅ STEP/IGES/IFC/DXF/DWG/FreeCAD import |
