---
slug: onshape
competitor: "Onshape"
category: cad-mechanical
left: kerf
right: onshape
hero_tagline: "Browser-native real-time-collab CAD — closest peer in cloud shape."
reviewed_at: 2026-05-19
order: 4
---

# Kerf vs Onshape

Onshape (PTC) pioneered cloud-native parametric CAD and remains the benchmark for real-time multi-user collaboration in design — the ability for multiple engineers to edit the same model simultaneously in a browser is genuinely unmatched. It introduced version-controlled Documents, FeatureScript for custom parametric features, and a growing App Store for simulation and rendering. Subscriptions start at ~US$1,500/yr (as of May 2026); the free tier allows public documents only. Kerf is the most natural peer comparison: cloud-friendly, browser-first, parametric. The honest picture is below.

## Where Onshape is strong

- **Real-time multi-user collaboration.** Onshape's defining capability: concurrent editing with live cursors and instant conflict resolution, all in the browser. No file locking, no "check out". This is genuinely ahead of any current Kerf collab offering.
- **True cloud-native architecture.** Purpose-built for the cloud from day one — no sync client, no save button, no version-mismatch between team members.
- **Built-in version control (Documents).** Branching, tagging, and history are first-class features baked into the platform — no separate Git integration needed.
- **FeatureScript ecosystem.** FeatureScript is a proprietary DSL, but it has produced a rich library of custom parametric features in the App Store, refined over years of community contribution.
- **Mobile and tablet editing.** Dedicated iOS and Android apps with full model editing — Kerf is a responsive browser experience without a native app.
- **Mature parametric CAD.** Part Studios with a decade of engineering behind them, a polished UI, and battle-tested reliability across complex industrial models.
- **Professional training and certification.** Onshape Learning Center, official certifications, and a large professional user base with extensive community content.

## Where Kerf differs

- **MIT open-core — no subscription, full offline.** Onshape requires a subscription starting at ~US$1,500/yr (as of May 2026); the free tier allows public documents only. Kerf is MIT-licensed — install the binary locally (brew/curl) for free, no account required, no connectivity needed, no revenue cap.
- **Open kernel, not a proprietary DSL.** Onshape extends via FeatureScript, a language PTC controls. Kerf's parametric DAG is backed by the MIT-licensed kernel directly — the extensibility surface is open.
- **Chat-native workflow with BYO LLM.** Describe a feature, constraint, or routing rule in plain language; the model edits the source backed by live doc-search. You can use Kerf's hosted models or bring your own API key — any OpenAI-compatible endpoint. Onshape has no LLM integration we're aware of (as of May 2026).
- **Multi-discipline: mechanical + electronics + jewelry.** Onshape is mechanical CAD. Kerf adds a full EDA stack (hierarchical schematic, shove router, SPICE, DRC, Gerber / IPC-2581) and a jewelry domain (ring v4, gemstones v2 — 30 cuts, settings, chain v2) in the same workspace.
- **620 analytic-oracle verified kernel tests.** The parametric and sketcher kernel ships with a verified test suite — results are checked against OCCT analytic ground truth.
- **kerf-sdk Python scripting (out-of-process).** HTTP/JSON-RPC from your own machine — the same interface the LLM uses internally.

## Honest gaps — where Kerf is behind today

- **Real-time collab maturity.** Onshape's concurrent multi-user editing is a decade in the making. Kerf's cloud collaboration feature is less mature. If live concurrent editing is critical, Onshape is ahead.
- **FeatureScript ecosystem.** Years of community-built FeatureScript features in Onshape's App Store have no Kerf equivalent today.
- **No mobile app.** Onshape's iOS and Android apps support editing on the go; Kerf is a responsive browser only.
- **Simulation ecosystem is smaller.** Neither platform ships first-party FEM, but Onshape's App Store has more mature simulation partner integrations available today.
- **Vendor polish and assembly depth.** Onshape's UI, mating system, and overall product finish reflect ten years of professional refinement. Kerf is younger.
- **Smaller community.** Onshape has a large, professionally-certified user base. Kerf's community is early-stage and growing.

## Side by side

| Feature | Onshape | Kerf |
|---|---|---|
| License | ⚠️ Proprietary SaaS subscription | ✅ MIT open-core |
| Cost | ⚠️ Standard ~US$1,500/yr; Professional ~US$2,100/yr (May 2026) | ✅ Free local; pay-as-you-go hosted |
| Free tier | ⚠️ Public documents only | ✅ Full free local install, private projects included |
| Offline / self-host | ❌ Browser-only; requires connectivity | ✅ Full offline single-binary install |
| Open source | ❌ Proprietary; data on PTC cloud | ✅ MIT — full codebase on GitHub |
| Vendor lock-in | ⚠️ PTC-hosted; export-only escape hatch | ✅ Open format; self-hostable |
| Real-time multi-user collab | ✅ Industry-leading concurrent editing | ⚠️ Cloud collab less mature |
| Version control (branches) | ✅ Built-in branching / tagging in Documents | ✅ file_revisions + cloud git branches |
| Mobile / tablet editing | ✅ iOS / Android apps | ⚠️ Responsive browser; no dedicated mobile app |
| Parametric B-rep | ✅ Mature Part Studios (OCCT underneath) | ✅ OCCT feature tree |
| Constraint sketcher | ✅ Full parametric sketcher | ✅ Sketcher v2 — all major constraints |
| Sheet metal | ✅ Full sheet-metal workspace | ✅ Flange + unfold + flat-pattern DXF |
| Custom parametric features | ✅ FeatureScript (rich App Store ecosystem) | ✅ MIT kernel directly; open DAG |
| Scripting / automation | ⚠️ FeatureScript only; REST API limited | ✅ kerf-sdk on PyPI — HTTP/JSON-RPC |
| BYO LLM / AI | ❌ None | ✅ BYO key or hosted models |
| Chat / LLM editing | ❌ None | ✅ Chat-native — edits source per turn |
| Assembly mates | ✅ Full mate system in Assemblies | ⚠️ Assembly mates (newer) |
| 2D technical drawings | ✅ Drawings workspace | ✅ Multi-sheet drawings |
| Electronics / PCB | ❌ Mechanical CAD only | ✅ Full EDA — schematic, routing, DRC |
| Jewelry tooling | ❌ None | ✅ Ring v4, gemstones v2 (30 cuts), settings, chain v2 |
| App Store / add-ons | ✅ PTC App Store — simulation, rendering, CAM | ⚠️ Early — open-core + plugin API |
| Import / export formats | ✅ STEP, IGES, Parasolid, ACIS, DXF | ✅ STEP/IGES/DXF/IFC/FreeCAD import |
