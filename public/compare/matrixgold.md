---
slug: matrixgold
competitor: "MatrixGold"
category: jewelry-nurbs
left: kerf
right: matrixgold
hero_tagline: "Industry-standard jewelry CAD — Grasshopper-based goldsmith depth vs MIT open-core."
reviewed_at: 2026-05-19
order: 2
---

# Kerf vs MatrixGold

MatrixGold (Gemvision / Stuller) is the industry-standard professional jewelry CAD suite. It runs as a deeply integrated Rhino + Grasshopper plugin and has been the benchmark for goldsmith tooling — ring builders, stone-setting wizards, pavé engines, wax-mill paths, supplier catalogs — for well over a decade. Kerf's jewelry vertical (40 modules) covers the same core scope — ring v4, settings v3/v4, gemstones v2, chain v2, gem-seat v2, gem-cert, casting export, full cost panel, PBR render — and extends into retail-workflow features (appraisal, repair estimator, mount_finder) that are typically outside MatrixGold's scope. The honest gap is years of goldsmith-specific UI polish, the Grasshopper ecosystem, and established casthouse partnerships.

## Where MatrixGold is strong

- **15+ years of goldsmith-specific UI polish.** MatrixGold has been shaped by professional goldsmiths, diamond dealers, and casthouses. Every interaction in its setting wizards, stone placement, and ring builders reflects decades of hands-on goldsmith feedback.
- **Grasshopper-powered parametric jewelry.** Running on Rhino + Grasshopper, MatrixGold inherits both the class-leading NURBS kernel and the Grasshopper visual scripting ecosystem — enabling custom parametric jewelry components that Kerf cannot match without code.
- **Comprehensive setting wizards.** Prong, bezel, pavé, channel, halo, bar, and more — with goldsmith-tuned defaults, catalog integration, and automated stone seating that has been battle-tested in production.
- **Supplier catalog integration.** Direct access to supplier-provided stone catalogs and findings — ordering integration that Kerf does not currently offer.
- **Wax-mill toolpaths.** Purpose-built wax-carving mill-path generation for DLP/SLA and wax milling — a production casting workflow Kerf only partially covers.
- **Casthouse partnerships and community.** MatrixGold has established relationships with casthouses worldwide and a large community of professional jewelers.

## Where Kerf differs

- **MIT open-core, free to use.** MatrixGold requires a per-seat cost (several thousand USD) plus a Rhino base licence. Kerf's full jewelry workflow is MIT-licensed and free locally — ring v4, settings v3/v4, gemstones v2 (30 cuts), chain v2, 31 ring templates, and the full retail module suite at no seat charge.
- **Retail workflow features MatrixGold does not include.** Appraisal module, repair estimator, mount_finder, full cost/quote panel — workflow features designed for the jewelry retail counter that are out of scope for MatrixGold.
- **Mechanical + electronics in the same workspace.** Kerf ships an OCCT B-rep modeller, PCB schematic, layout, and EDA workflow alongside the jewelry tools — no additional tool or licence required for product electronics embedded in jewelry (smart rings, NFC pendants, etc.).
- **Chat-native workflow and BYO LLM.** Describe a setting change, ring modification, or rendering tweak in plain language; the LLM edits the source backed by live doc-search. MatrixGold has no LLM integration.
- **Milgrain, filigree, granulation, enamel, laser marking.** These decorative/surface modules ship in-box in Kerf — MatrixGold typically relies on manual mesh techniques or third-party add-ons.
- **CAM included in-box.** 3-axis CAM + 5-axis 3+2 ship with Kerf's core product — no RhinoCAM plugin required.
- **Cross-platform, browser + local binary.** MatrixGold is Windows-only. Kerf runs in the browser (hosted SaaS) or as a single binary on Windows, macOS, and Linux.
- **kerf-sdk Python scripting.** Automate jewelry templates and feature trees from Python over HTTP/JSON-RPC on your own machine.

## Honest gaps — where Kerf is behind today

- **Goldsmith UX polish.** MatrixGold's workflows reflect 15+ years of professional goldsmith feedback. Kerf's jewelry UI is functional but younger and less refined for production shop use.
- **Wax-mill toolpath generation.** MatrixGold ships full wax-carving mill-path generation. Kerf has a wax-carving plan module but not full mill-path generation.
- **Supplier catalog integration.** MatrixGold's direct ties to stone and findings supplier catalogs have no current Kerf equivalent.
- **Grasshopper visual scripting.** For complex parametric custom components (e.g., generative pavé layouts, algorithmic filigree), MatrixGold's Grasshopper base provides a visual programming environment Kerf cannot match without code.
- **Gem dispersion / caustics rendering.** MatrixGold / Rhino's rendering pipeline supports accurate gem caustics and dispersion. Kerf's PBR materials and faceting render do not currently match this quality.
- **Casthouse ecosystem.** Established casthouse partnerships, certification programs, and community support are significant practical advantages for production shop workflows.

## Side by side

| Feature | MatrixGold | Kerf |
|---|---|---|
| License | ⚠️ Proprietary; per-seat subscription or perpetual | ✅ MIT open-core |
| Cost | ⚠️ Several thousand USD per seat; Rhino base required | ✅ Free local; pay-as-you-go hosted |
| Platform | ⚠️ Windows only | ✅ Browser + Win/macOS/Linux binary |
| Hosted / browser option | ❌ Desktop only | ✅ Hosted SaaS + local install |
| Goldsmith UX polish | ✅ 15+ years of jewelry-specific refinement | ⚠️ Functional, younger UX |
| Setting styles (prong/bezel/pavé/channel/halo) | ✅ Prong, bezel, pavé, channel, halo, and more | ✅ Settings v3 — 14+ styles |
| Gem seat / seat generation | ✅ Automated seat generation | ✅ Gem-seat v2 |
| Gemstone catalog | ✅ Extensive incl. certified stones | ✅ Gemstones v2 — 30 cuts |
| Gem-cert generation | ⚠️ Via supplier integrations | ✅ Gem-cert output built in |
| Faceting render / caustics | ✅ Photoreal gem dispersion / caustics | ⚠️ Faceting render; no caustics |
| PBR materials | ✅ Rich precious-metal + gem materials | ✅ PBR materials for metals and gems |
| Ring builders (profiles / styles) | ✅ Large shank library + styles | ✅ Ring v4 — 13+ profiles + 31 templates |
| Chain / bracelet | ✅ Chain builder with link library | ✅ Chain v2 |
| Findings library | ✅ Clasps, bails, findings from supplier catalogs | ⚠️ Findings modules; no supplier catalog |
| Supplier catalog integration | ✅ Direct supplier / casthouse links | ❌ Not available |
| Casting / STL export | ✅ STL + DLP/SLA + wax-mill paths | ✅ Casting / STL production export |
| Wax-mill toolpaths | ✅ Full wax-mill path generation | ⚠️ Wax-carving plan; no full mill-path |
| Milgrain / filigree / granulation | ⚠️ Manual techniques / add-ons | ✅ Built in |
| Enamel / engraving / laser marking | ⚠️ Manual / separate flow | ✅ Enamel + laser_marking modules |
| Retail workflow (appraisal / repair / mount_finder) | ❌ Out of scope | ✅ Appraisal + repair + mount_finder in-box |
| Cost / quote panel | ❌ Not core MatrixGold | ✅ Full quote / cost panel built in |
| Parametric B-rep CAD (OCCT) | ⚠️ Via Rhino plugins | ✅ OCCT feature tree — pad/pocket/loft |
| Electronics / PCB | ❌ Separate tool required | ✅ Full EDA stack in same workspace |
| Chat / LLM editing | ❌ None | ✅ Chat-native + BYO API key |
| Visual scripting | ✅ Grasshopper — mature ecosystem | ❌ No visual node environment |
