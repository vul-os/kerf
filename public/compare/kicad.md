---
slug: kicad
competitor: "KiCad"
category: cad-electronic
left: kerf
right: kicad
hero_tagline: "Open-source EDA suite — GPL vs MIT, deep vs integrated."
reviewed_at: 2026-05-19
order: 1
---

# Kerf vs KiCad

KiCad 10.0 (March 2026) is a free, GPL-licensed, cross-platform EDA suite. It now natively exports IPC-2581 and ODB++, gained an overhauled track-tuning system with time-domain constraints, design variants, a graphical DRC rule editor, and Allegro/PADS/gEDA importers. ngspice is built in. KiCad's depth and community on the pure-PCB side are formidable. Kerf covers much of the same electronics ground and adds a unified mechanical CAD workspace, a simulation triad (Monte-Carlo SPICE corner analysis, 2-D finite-difference thermal, SI/PDN/EMC pre-compliance wizards), chat-native editing, and the kerf-sdk — but does not match KiCad's EDA maturity, library breadth, or community today.

**Simulation honesty note:** Kerf's SI/EMC/PDN wizards use reduced-order analytical models, not full-wave EM solvers. They are useful for early-stage risk assessment; they are NOT a substitute for ANSYS HFSS, Allegro PI/SI, or an accredited compliance test lab.

## Where KiCad is strong

- **GPL-licensed, truly free, no seat restrictions.** KiCad is free for commercial use with no revenue caps, no seat limits, and no cloud-account requirement.
- **Mature, battle-tested EDA workflow.** Decades of development, a large community, and millions of real-world boards validate its PCB workflow. Kerf is newer.
- **Push-and-shove routing (Pcbnew).** The Pcbnew router is a mature, production-tested push-and-shove engine. Kerf's shove router is younger.
- **Vast component libraries.** KiCad's built-in symbol and footprint libraries are enormous and actively maintained by the community. Kerf's libraries are smaller.
- **Differential pair + track tuning (v10).** Mature diff-pair routing and interactive length tuning with time-domain constraints shipped in v10.
- **Native IPC-2581 + ODB++ (v10).** KiCad now exports both advanced fab formats natively.
- **ngspice simulation.** AC/DC/transient SPICE with a built-in plotter — mature and well-integrated.
- **ECAD importer breadth (v10).** Allegro, PADS, gEDA, Eagle importers ship in-box.

## Where Kerf differs

- **MIT open-core vs GPL.** Kerf is permissively MIT-licensed — you can embed it in proprietary commercial products. KiCad's GPL has copyleft implications for products that link against it.
- **Mechanical CAD in the same workspace.** KiCad requires a separate MCAD tool (FreeCAD, SolidWorks, etc.). Kerf ships an OCCT B-rep modeller, constraint sketcher, sheet metal, and CAM in the same workspace.
- **Chat-native workflow.** Describe a routing rule, schematic change, or simulation setup in plain language; the LLM edits the source backed by live doc-search. KiCad has no LLM integration.
- **Monte-Carlo SPICE corner analysis.** `sim_corner` runs min/typ/max parameter sweeps across process corners with yield estimation — beyond KiCad's baseline ngspice.
- **SI / PDN / EMC pre-compliance wizards.** `si_eye_wizard`, `pdn_wizard`, `emc_wizard` (FCC §15.109 + CISPR 32), and `thermal_board` (2-D FD steady-state) — KiCad has no equivalent for these.
- **Jewelry and architecture in the same tool.** Kerf's multi-discipline scope spans electronics, mechanical, jewelry, and BIM-adjacent workflows in one workspace.
- **kerf-sdk Python scripting.** HTTP/JSON-RPC from your own machine — the same interface the LLM uses internally.
- **Hosted SaaS option.** Design in the browser without installing anything locally.

## Honest gaps — where Kerf is behind today

- **EDA maturity and routing polish.** KiCad's EDA workflow is older, more battle-tested, and more widely validated. Kerf's shove router is less mature.
- **Library breadth.** KiCad's symbol and footprint libraries are substantially larger than Kerf's today.
- **ECAD community and learning resources.** The KiCad community is enormous. Kerf's electronics community is early-stage.
- **Differential pair routing.** KiCad's diff-pair + interactive tuning system is more mature than Kerf's current offering.
- **Pure-PCB depth.** For teams whose entire workflow is pure PCB design without mechanical CAD, KiCad's EDA depth and zero-cost model are hard to beat.

## Side by side

| Feature | KiCad | Kerf |
|---|---|---|
| License | ✅ GPL v3 (free, copyleft) | ✅ MIT open-core (permissive) |
| Cost | ✅ Free, no restrictions, no seats | ✅ Free local; pay-as-you-go hosted |
| Platform | ✅ Win / macOS / Linux desktop | ✅ Browser + single-binary local |
| Hierarchical schematic | ✅ Eeschema — dozens of sheets | ✅ Hierarchical + sheet borders |
| ERC | ✅ Mature ERC + exclusions | ✅ ERC + IPC-2221B presets |
| SPICE simulation | ✅ ngspice — AC/DC/transient | ✅ SPICE + model library + Monte-Carlo corner runs |
| Push-and-shove router | ✅ Pcbnew (mature) | ✅ Shove router (younger) |
| Differential pairs / length tune | ✅ Diff-pair + tuner (v10) | ⚠️ Length tuning; diff-pair lighter |
| DRC rules system | ✅ Graphical rule editor (v10) | ✅ DRC + IPC-2221B presets |
| IPC-2581 / ODB++ / Gerber | ✅ Native IPC-2581 + ODB++ (v10) | ✅ Gerber/Excellon/IPC-2581/ODB++ |
| Signal integrity (SI) | ⚠️ External tools recommended | ✅ si_eye_wizard — eye/crosstalk (analytical) |
| EMC pre-compliance | ⚠️ No EMC analysis | ✅ emc_wizard — FCC §15.109 / CISPR 32 |
| PDN analysis | ⚠️ No automated PDN | ✅ pdn_wizard — Z target, decap placement |
| Thermal (board) | ⚠️ Manual θJA calcs | ✅ thermal_board — 2-D FD steady-state |
| Panelisation | ⚠️ KiKit (community plugin) | ✅ Panelize built in |
| ECAD importers | ✅ Allegro / PADS / gEDA / Eagle (v10) | ✅ Eagle / Allegro / PADS / gEDA / KiCad |
| Mechanical CAD (same tool) | ❌ Separate tool required | ✅ Full B-rep, sketcher, sheet metal |
| Chat / LLM editing | ❌ None | ✅ Chat-native — edits circuit source |
| Hosted / cloud option | ❌ Desktop only | ✅ Hosted SaaS + local install |
