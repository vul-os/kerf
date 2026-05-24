---
slug: altium
competitor: "Altium Designer"
category: cad-electronic
left: kerf
right: altium
hero_tagline: "Industrial-grade PCB design — Situs router vs MIT open-core EDA."
reviewed_at: 2026-05-19
order: 2
---

# Kerf vs Altium Designer

Altium Designer is the commercial ECAD benchmark: industry-leading push-and-shove interactive routing (Situs engine), ActiveRoute autorouter, hierarchical and multi-board schematics, a mature rules system, HDI/RF stack-up tooling, 3D PCB editor, MCAD CoDesigner (SOLIDWORKS / CREO / Inventor / CATIA), signal-integrity via HyperLynx / Touchstone I/O, and a cloud-collaboration overlay in Altium 365. It is Windows-only, subscription-priced (~$8,000–$10,000+ USD/seat/yr, as of May 2026), and widely considered the gold standard for serious PCB engineering work. Kerf does not match Altium's interactive routing polish or HDI/RF depth. Where Kerf differs: open-core MIT, multi-discipline (mech + jewelry + ECAD), chat-driven editing, BYO LLM, integrated simulation pre-compliance suite, IPC-2581 + IPC-D-356A + IDF exports, and a significantly lower price of entry.

## Where Altium is strong

- **Gold-standard Situs push-and-shove router.** Altium's interactive routing engine is the industry reference for complex PCB layout — push, slide, and gloss algorithms that handle dense HDI boards with confidence. Kerf's shove router is less mature.
- **Comprehensive HDI/RF tooling.** Buried/blind/micro-via, back-drill, rigid-flex, layer-stack manager with impedance calculation, and full RF design rules — a complete stack for high-density and high-frequency boards.
- **HyperLynx SI integration.** IBIS/Touchstone I/O, DDR wizard, and back-annotation of signal-integrity results from HyperLynx into Altium's layout environment.
- **PDN Analyzer.** Per-net impedance sweep, ripple analysis, and decoupling capacitor optimisation — a mature tool integrated into the layout flow.
- **Multi-board design (MB3D workspace).** Design, place, and check multiple interconnected PCBs in a single 3D workspace — a capability Kerf does not have today.
- **MCAD CoDesigner.** A live bidirectional ECAD↔MCAD link with SOLIDWORKS, Creo, Inventor, and CATIA — synchronising component placement, board outline, and keepouts without an intermediate file.
- **Production-hardened 30+ year lineage.** Altium has been refined through decades of demanding PCB projects across aerospace, automotive, and medical device manufacturing.
- **Altium 365 cloud collaboration.** A cloud overlay for concurrent multi-user access, design review, and supply chain visibility — though it adds cost on top of the base subscription.

## Where Kerf differs

- **MIT open-core, dramatically lower cost.** Altium is ~$8,000–$10,000+/seat/yr (as of May 2026). Kerf is MIT-licensed — free locally with pay-as-you-go cloud compute. No seat fee, no annual renewal, no commercial-use restriction.
- **Cross-platform.** Kerf runs in the browser (hosted SaaS) or as a single local binary on Windows, macOS, and Linux. Altium is Windows-only.
- **Mechanical CAD in the same workspace.** Altium requires a separate MCAD tool for enclosure and product design. Kerf ships an OCCT B-rep modeller, constraint sketcher, sheet metal, 3-axis CAM, and 5-axis 3+2 CAM in the same workspace as the PCB editor.
- **Chat-native workflow and BYO LLM.** Describe a routing rule, schematic change, or simulation setup in plain language; the LLM edits the source backed by live doc-search. Bring your own Anthropic or OpenAI API key. Altium has no LLM integration we're aware of (as of May 2026).
- **In-box pre-compliance simulation suite.** `si_eye_wizard` (SI + eye diagram), `pdn_wizard` (per-net impedance, decap optimisation), `emc_wizard` (FCC §15.109 + CISPR 32), and `thermal_board` (2-D FD steady-state) — all in-box without an HyperLynx licence.
- **IPC-D-356A netlist and IDF exports in-box.** Kerf includes IPC-D-356A netlist output and IDF MCAD bridge without add-in.
- **40-module jewelry domain.** Ring v4, gemstones v2, settings v3/v4, chain v2, and casting export — an entire vertical Altium has no scope for.
- **kerf-sdk Python scripting.** Automate over HTTP/JSON-RPC from your own machine — the same interface the LLM uses internally.

## Honest gaps — where Kerf is behind today

- **Interactive routing maturity.** Altium's Situs engine is the gold standard. Kerf's shove router handles most boards well but is younger and less battle-tested on dense HDI layouts.
- **HDI depth.** Altium's HDI rule depth, buried/blind/micro-via checking, and back-drill tooling are more mature than Kerf's current offering.
- **Multi-board projects.** Altium's MB3D workspace has no Kerf equivalent today.
- **MCAD CoDesigner live link.** Altium's live bidirectional SOLIDWORKS/Creo/Inventor link is more polished than Kerf's IDF MCAD bridge (no live push from Kerf to MCAD today).
- **HyperLynx SI depth.** Altium's HyperLynx integration provides full-wave-coupled SI analysis that Kerf's analytical wizard models do not replicate. For compliance-lab-grade SI work, HyperLynx is more appropriate.
- **Production tooling maturity.** 30+ years of refining Altium's DRC, design rules, and output generators means the production flow is extremely hardened. Kerf is newer.
- **Community and learning resources.** The Altium Designer user community is very large. Kerf's is early-stage.

## Side by side

| Feature | Altium Designer | Kerf |
|---|---|---|
| License | ⚠️ Proprietary subscription | ✅ MIT open-core |
| Cost | ⚠️ ~$8,000–$10,000+ USD/seat/yr (May 2026) | ✅ Free local; pay-as-you-go hosted |
| Platform | ⚠️ Windows only | ✅ Browser + Win/macOS/Linux binary |
| Push-and-shove router | ✅ Situs — gold-standard | ⚠️ Shove router (less mature) |
| ActiveRoute autorouter | ✅ Interactive guided autorouting | ✅ FreeRouting integrated |
| Differential pairs | ✅ Diff-pair routing + tuning (mature) | ⚠️ Length tuning; diff-pair lighter |
| HDI stackup & via types | ✅ Buried / blind / micro-via, back-drill | ⚠️ Via types; HDI rule depth lighter |
| Multi-board (MB3D) | ✅ Multi-board design workspace | ❌ Single-board per project today |
| 3D PCB editor | ✅ Native 3D PCB — STEP import, clearance | ⚠️ Board 3D view; shallower |
| ERC depth | ✅ Pin-type / bus / diff / custom rules | ✅ ERC + IPC-2221B presets |
| SPICE simulation | ✅ Mixed-signal XSPICE | ✅ SPICE + model library |
| Signal integrity (SI) | ✅ HyperLynx SI; IBIS/Touchstone | ✅ si_eye_wizard (analytical) |
| PDN analysis | ✅ PDN Analyzer | ✅ pdn_wizard — Z target, decap placement |
| EMC pre-compliance | ⚠️ Via external HyperLynx EMC | ✅ emc_wizard — FCC §15.109 / CISPR 32 |
| Thermal (board) | ⚠️ Via Altium 365 Sim / external | ✅ thermal_board — 2-D FD steady-state |
| MCAD CoDesigner | ✅ SOLIDWORKS / CREO / Inventor / CATIA | ⚠️ IDF MCAD bridge + board STEP |
| Mechanical CAD (same tool) | ❌ External MCAD required | ✅ Full B-rep, sketcher, sheet metal, CAM |
| IPC-2581 / ODB++ / Gerber | ✅ Full fab suite | ✅ Gerber/Excellon/IPC-2581/ODB++ |
| IPC-D-356A netlist | ✅ Full fab suite | ✅ IPC-D-356A in-box |
| Chat / LLM editing | ❌ None known (as of May 2026) | ✅ Chat-native — edits circuit source |
| Jewelry / architecture | ❌ Not applicable | ✅ 40-module jewelry + BIM-adjacent in-box |
| Cloud collaboration | ⚠️ Altium 365 (separate SaaS subscription) | ✅ Integrated hosted SaaS; cloud git built-in |
