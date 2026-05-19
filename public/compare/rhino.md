---
slug: rhino
competitor: "Rhino"
category: jewelry-nurbs
left: kerf
right: rhino
hero_tagline: "NURBS & jewelry CAD — class-leading kernel vs MIT open-core."
reviewed_at: 2026-05-19
order: 1
---

# Kerf vs Rhino

Rhino 8 — with the RhinoGold / Matrix lineage now consolidated into MatrixGold / CrossGems — is the professional reference for jewelry CAD and freeform NURBS design. It is a perpetual one-time licence (about US$995, not a subscription) with the industry-standard NURBS kernel and Grasshopper. Kerf has a strong, free jewelry foundation and integrated B-rep, electronics, and CAM — but Rhino's NURBS depth, Grasshopper ecosystem, and goldsmith-proven plugins are well ahead today. An honest look at both.

## Where Rhino is strong

- **Class-leading NURBS kernel.** Rhino's surface engine is the industry reference for freeform work — jewelry, industrial design, naval architecture, aerospace — with production-proven G0–G3 continuity tools.
- **Grasshopper visual scripting.** The gold standard for parametric 3D, with thousands of components spanning structural optimisation, pattern generation, and more. Kerf has no equivalent.
- **Deeply refined jewelry plugins.** MatrixGold / RhinoGold bring years of goldsmith-driven UX: ring builders, stone-setting and pavé wizards, sizing, wax-mill paths, and supplier catalogs.
- **Perpetual licence, no subscription.** A one-time purchase that does not expire — a genuine ownership advantage over subscription CAD tools.
- **SubD and ShrinkWrap.** Rhino 8's SubD (with creases) and ShrinkWrap give fast organic modelling and mesh-recovery workflows Kerf does not match.
- **Advanced rendering ecosystem.** Built-in Cycles plus V-Ray, Enscape, and KeyShot for photoreal jewelry renders with accurate caustics and gem dispersion.
- **RhinoCommon / Python automation.** rhinoscriptsyntax and RhinoCommon expose essentially every kernel operation for scripting.

## Where Kerf differs

- **MIT open-core, free to use.** Rhino is ~US$995 per seat and the jewelry plugins add more. Kerf's full jewelry workflow — ring v4, settings v3/v4, gemstones v2, chain v2, 31 templates — is MIT-licensed and free locally.
- **Chat-native workflow.** Describe a change in plain language and the LLM edits the feature tree / JSCAD source with doc-search backing — no visual programming required.
- **Integrated B-rep, electronics, drawings.** An OCCT parametric feature tree, a full EDA stack, multi-sheet drawings, and ASME Y14.5 GD&T are in the same workspace — disciplines Rhino needs separate plugins or tools for.
- **Hosted option or local pip install.** Sign up and design in the browser, or `pip install kerf` locally — no platform-specific installer, no licence dongle.
- **CAM built in.** 3-axis CAM with a tool database and 5-axis 3+2 ship in-box, where Rhino relies on the RhinoCAM plugin.
- **kerf-sdk Python scripting.** Automate jewelry templates and feature trees from any Python script over HTTP/JSON-RPC on your own machine.

## Honest gaps — where Kerf is behind today

- **NURBS surfacing is early.** NURBS Phase 4 (trim-by-curve, G3 combs) is functional but nowhere near Rhino's depth. blendSrf / networkSrf / sweep2-class freeform tools are roadmap, not shipped.
- **No Grasshopper equivalent.** Kerf has no visual parametric environment; chat + the Python SDK fill part of that space but not all of it.
- **SubD depth is newer.** Kerf now ships SubD authoring with creases, but Rhino 8's SubD tools are more mature and deeply integrated with the NURBS surfacing workflow.
- **Render quality is narrower.** Kerf's Cycles backend and in-browser path tracer provide photoreal output, but Rhino's plugin ecosystem (V-Ray, Enscape, KeyShot) provides caustics, accurate gem dispersion, and archviz lighting quality that Kerf's render path does not match today.
- **Jewelry plugin depth.** MatrixGold / RhinoGold have supplier catalogs, wax-path generation, and sizing refinements Kerf is still building toward.
- **Smaller community.** Rhino has decades of training, forums, and Food4Rhino plugins; Kerf's ecosystem is early-stage.

## Side by side

| Feature | Rhino | Kerf |
|---|---|---|
| License | ⚠️ Proprietary; perpetual one-time buy | ✅ MIT open-core |
| Cost | ⚠️ ~US$995 full / ~$595 upgrade; +plugin cost | ✅ Free local; pay-as-you-go hosted |
| Subscription | ✅ Perpetual licence, no renewal | ✅ No seat subscription |
| Platform | ⚠️ Windows + macOS desktop | ✅ Browser + single-binary local |
| NURBS surfacing | ✅ Class-leading kernel (G0–G3) | ⚠️ NURBS Phase 4 — trim-by-curve, G3 combs (early) |
| SubD modelling | ✅ SubD with creases (Rhino 8) | ✅ SubD authoring with creases; quad remesh |
| Parametric solids (B-rep) | ⚠️ Via Grasshopper / plugins | ✅ OCCT feature tree — pad/pocket/revolve/loft |
| Mesh repair / ShrinkWrap | ✅ ShrinkWrap, mesh tools | ⚠️ Quad remesh; no ShrinkWrap equivalent |
| Visual node scripting | ✅ Grasshopper — industry standard | ❌ No visual node environment |
| Plugin marketplace | ✅ Thousands of GH components / Food4Rhino | ⚠️ Plugin API early-stage |
| Python / scripting | ✅ rhinoscriptsyntax / RhinoCommon | ✅ kerf-sdk on PyPI — HTTP/JSON-RPC |
| Ring design | ✅ MatrixGold / RhinoGold ring builders | ✅ Ring v4 + 31-template library |
| Gemstones / cuts | ✅ Extensive gem libraries | ✅ Gemstones v2 — 30 cuts |
| Settings / pavé / channel | ✅ Mature stone-setting wizards | ✅ Settings v3/v4 + gem-seat v2 |
| Chain / findings | ✅ Dedicated chain + findings tools | ✅ Chain v2 + findings + decorative |
| Casting / wax-mill export | ✅ STL + wax-mill paths, supplier catalogs | ⚠️ Casting export; no supplier catalogs / wax paths |
| Photoreal rendering | ✅ Cycles + V-Ray/Enscape/KeyShot; caustics | ⚠️ Cycles backend + browser path tracer (no caustics) |
| 2D drawings / GD&T | ⚠️ Layout + annotation plugins | ✅ Multi-sheet drawings + ASME Y14.5 GD&T |
| CNC CAM | ⚠️ Via RhinoCAM plugin | ✅ 3-axis CAM + tool DB; 5-axis 3+2 |
| Electronics | ❌ Separate tool required | ✅ Full EDA stack in same workspace |
| Chat / LLM editing | ❌ None | ✅ Chat-native — edits source per turn |
| Hosted / cloud | ❌ Desktop only | ✅ Hosted SaaS + local install |
