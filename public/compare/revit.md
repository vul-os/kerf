---
slug: revit
competitor: "Autodesk Revit"
category: bim
left: kerf
right: revit
hero_tagline: "Industry-standard BIM for AEC — compared honestly against MIT open-core."
reviewed_at: 2026-05-19
order: 1
---

# Kerf vs Revit

Revit is the dominant BIM platform for architecture, engineering, and construction — a deep parametric family system, full MEP, Revit Structure, mature IFC interoperability, Navisworks clash coordination, and Autodesk Docs cloud worksharing, at roughly US$2,910/yr per seat on Windows (as of May 2026). Kerf now ships parametric family authoring, expanded BIM elements (walls, doors, windows, slabs, stairs, ramps), site toposolids, a material catalogue, and cross-discipline clash detection — but full MEP, worksharing at AEC project scale, and Navisworks-class coordination are still ahead of Kerf. **Kerf is not a full BIM platform today**, and this page says so plainly.

## Where Revit is strong

- **Deep parametric BIM family system.** Revit's family editor — including nested families, hosting rules, instance vs type params, and per-element scheduling — is considerably deeper than Kerf's parametric family authoring, which covers type/instance params and formulas but not nested families or level-based hosting.
- **Vast content library.** The Autodesk Content Library plus a large third-party market supply parametric families for nearly every product category. Kerf's built-in catalog is functional but substantially smaller.
- **Full MEP and structural disciplines.** HVAC, electrical, plumbing, and MEP fabrication detailing, plus Revit Structure with Robot structural analysis — entire disciplines Kerf does not yet address.
- **Navisworks clash detection and coordination.** Revit models feed directly into Navisworks for federated, multi-discipline clash detection and 4D/5D construction sequencing.
- **Mature, certified IFC round-trip.** Years of IFC 2x3 / 4 import and export refinement backed by buildingSMART certification.
- **BIM 360 / Autodesk Docs worksharing.** Worksets enable concurrent BIM model editing by large project teams, with cloud-hosted model coordination through Autodesk Construction Cloud.
- **pyRevit + Dynamo automation.** The Revit API — accessible from pyRevit (Python) and Dynamo (visual programming) — covers virtually every internal BIM object for scripted workflows.
- **Industry-standard AEC ecosystem.** Decades of vendor support, certified training, structural analysis integrations (Robot, ETABS, Tekla), and an established pipeline to cost estimation, scheduling, and facilities management platforms.

## Where Kerf differs

- **MIT open-core, dramatically lower cost.** Revit is ~US$2,910/yr per seat and Windows-only (as of May 2026). Kerf is MIT-licensed with a free local install via brew or curl on macOS/Linux/Windows, and pay-as-you-go hosted cloud — no per-seat subscription, no Autodesk account.
- **Chat-native workflow.** Describe a building element, layout change, or parametric constraint in plain language; the LLM edits the model source directly, backed by live doc-search.
- **Mechanical + electronics in the same workspace.** Teams designing smart buildings, IoT devices, or electronic enclosures can work on PCB layout and mechanical B-rep without leaving Kerf — disciplines that require separate tools in a Revit-centred workflow.
- **Multi-discipline under one licence.** Architectural, mechanical, electronics, and jewelry workflows share one workspace and one SDK interface — no per-discipline seat stacking.
- **Mechanical-grade documentation.** ASME Y14.5 GD&T and multi-sheet drawings serve product-fabrication work alongside architectural output in the same tool.
- **kerf-sdk Python scripting.** Automate drawing generation, BOM export, and model manipulation from Python on your own machine via HTTP/JSON-RPC.

## Honest gaps — where Kerf is behind today

- **Not a BIM platform today.** For multi-discipline AEC firms — structural, MEP, and architectural teams on one federated model — Revit's depth is the appropriate choice.
- **No MEP or building services.** HVAC, plumbing, and electrical systems modelling are absent. Revit MEP is far ahead.
- **Family authoring is shallower.** Kerf now ships parametric family authoring (type/instance params, formulas, scheduling metadata) but Revit's nested families, formula-driven visibility rules, and level-based hosting are deeper.
- **Clash detection is newer.** Kerf ships cross-discipline clash detection but Navisworks-scale federated coordination is more mature in Revit's ecosystem.
- **IFC export is in progress.** Kerf imports IFC at Tier 2 but full certified IFC export for round-trip openBIM interoperability is not yet complete.
- **No 4D/5D construction sequencing.** Revit feeds Navisworks and Autodesk Construction Cloud for schedule-linked 4D walkthroughs and cost-linked 5D models.
- **No BIM-grade worksharing.** Kerf has general workspace member roles, not concurrent BIM model worksharing at the scale of a large AEC project team.

## Side by side

| Feature | Revit | Kerf |
|---|---|---|
| License | ⚠️ Proprietary subscription | ✅ MIT open-core |
| Cost | ⚠️ ~US$2,910/yr single-user (May 2026) | ✅ Free local; pay-as-you-go hosted |
| Platform | ⚠️ Windows only | ✅ Browser + Win/macOS/Linux binary |
| Parametric family system | ✅ Deep family editor + shared params | ✅ Parametric .family.json — type/instance params, formulas |
| Family library | ✅ Autodesk Content Library + vast third-party | ⚠️ Built-in parametric family catalog (smaller) |
| Walls / doors / windows / slabs | ✅ Full parametric building elements | ✅ Parametric walls/doors/windows/slabs/stairs/ramps |
| Structural grid / framing | ✅ Revit Structure + Robot structural analysis | ⚠️ Structural grid + steel framing; no analysis parity |
| Site / earthwork | ✅ Toposolids, site tools | ✅ Site toposolids + earthwork volumes |
| MEP (HVAC / plumbing / electrical) | ✅ Full Revit MEP + fabrication detailing | ❌ Not yet |
| Clash detection | ✅ Navisworks federated coordination | ⚠️ Cross-discipline clash detection (newer) |
| Multi-user worksharing | ✅ Worksets + BIM 360 concurrent editing | ⚠️ General workspace roles, not BIM worksharing |
| 4D / 5D sequencing | ✅ Via Navisworks / Autodesk Construction Cloud | ❌ Not yet |
| IFC import | ✅ Certified IFC 2x3 / 4 | ✅ IFC Tier 2 import |
| IFC export | ✅ Certified IFC 2x3 / 4 export | ⚠️ In progress |
| Sheets / views | ✅ Full sheet-set management | ✅ Multi-sheet drawings |
| GD&T / tolerancing | ⚠️ Not a mechanical-tolerance tool | ✅ ASME Y14.5 GD&T (mechanical side) |
| Electronics (same tool) | ❌ Separate tool required | ✅ Full EDA stack in same workspace |
| Chat / LLM editing | ❌ No LLM interface we're aware of (as of May 2026) | ✅ Chat-native — edits source per turn |
| Scripting / automation | ✅ pyRevit + Dynamo + Revit API | ✅ kerf-sdk on PyPI — HTTP/JSON-RPC |
| AEC plugin ecosystem | ✅ Vast Autodesk App Store | ⚠️ Plugin API early-stage |
