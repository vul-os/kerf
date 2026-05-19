---
slug: autocad
competitor: "AutoCAD"
category: drafting
left: kerf
right: autocad
hero_tagline: "Industry-standard 2D drafting + .dwg ecosystem — different primary jobs."
reviewed_at: 2026-05-19
order: 1
---

# Kerf vs AutoCAD

AutoCAD is a 40+ year incumbent — the tool that defined 2D drafting for architecture, engineering, and construction, and the originator of the .dwg format that is the de-facto exchange standard for 2D documentation. Subscription pricing is ~US$255/mo or ~US$2,030/yr. Kerf is NOT a drafting-first tool and is not positioned as an AutoCAD replacement for production AEC work. AutoCAD owns 2D drafting + .dwg; Kerf is a 3D parametric CAD with drawing export, multi-discipline scope, and a chat-native workflow. They solve different primary problems — the honest comparison is below.

**DWG interchange:** Kerf imports DWG (Tier 1 via libredwg bridge). Kerf does NOT export DWG natively — it writes DXF instead (same .dwg/.dxf family; broadly compatible with AutoCAD and AutoCAD LT).

## Where AutoCAD is strong

- **40+ years as the 2D drafting standard.** AutoCAD invented the drafting command line, dynamic blocks, paper-space/model-space workflows, linetypes, dimension styles, and layer standards that every downstream AEC tool speaks. Its 2D drafting depth is unmatched.
- **.dwg format ownership.** AutoCAD is the native format owner for .dwg — the de-facto exchange format for AEC documentation worldwide. Every tool in the industry can read and write .dwg because AutoCAD established it.
- **Dynamic blocks.** Block definitions with visibility states, action parameters, and stretch/array actions enable re-usable parametric 2D elements that Kerf does not replicate.
- **Paper-space/model-space workflow.** Full paper-space with multi-scale viewports, plot styles, and title-block management — the definitive 2D-to-print workflow.
- **Sheet sets and CAD standards.** Sheet Set Manager coordinates multi-drawing project output; CAD Standards Manager enforces layer, linetypes, and text style compliance across drawings.
- **Express Tools and productivity macros.** 50+ built-in productivity tools (Overkill, Super Hatch, Quick Select, etc.) and deep AutoLISP / .NET API for custom automation.
- **AEC verticals.** Civil 3D, AutoCAD Architecture, AutoCAD MEP, Plant 3D, and AutoCAD Electrical extend the core drafting engine for every AEC sub-discipline.
- **40+ year community and training ecosystem.** Official Autodesk courses, textbooks, YouTube, and a massive certified practitioner base.

## Where Kerf differs

- **MIT open-core, dramatically lower cost.** AutoCAD is ~US$2,030/yr. Kerf is MIT-licensed — free locally on any OS, no Autodesk account, no seat subscription.
- **3D parametric-first.** Kerf's OCCT feature tree (pad, pocket, revolve, loft), constraint sketcher, persistent face IDs, and assembly joints are a parametric CAD environment, not a 3D solid modeller added on top of a drafting engine.
- **Chat-native workflow.** Describe a feature, constraint, or routing change in plain language; the LLM edits the source backed by live doc-search. AutoCAD has a limited AI Assist but no source-level LLM editing.
- **Multi-discipline in one workspace.** Full EDA (schematic + PCB + DRC + Gerber / IPC-2581), jewelry tooling (ring v4, gemstones v2), mechanical CAD, and BIM-adjacent primitives — disciplines AutoCAD covers only through separate vertical products.
- **BYO LLM / BYO key.** Bring your own Anthropic or OpenAI API key; zero billing flows through Kerf. AutoCAD has no configurable LLM.
- **In-box pre-compliance simulation.** SI, EMC, PDN, and PCB thermal analysis wizards ship in-box with no extension gating.
- **Cross-platform.** Runs in the browser or as a single binary on Windows, macOS, and Linux. AutoCAD is Windows-primary (macOS version is feature-restricted).
- **kerf-sdk Python scripting.** HTTP/JSON-RPC from your own machine — a first-class API interface.

## Honest gaps — where Kerf is behind today

- **2D drafting depth.** AutoCAD's 2D drafting toolset — dynamic blocks, paper-space viewports, dimension styles, Express Tools, sheet sets, CAD standards — is irreplaceable for production 2D documentation work. Kerf is 3D-first; its 2D drawing output is multi-sheet but not a full AutoCAD drafting environment.
- **No AutoLISP / VBA / .NET API.** AutoCAD's deep scripting ecosystem (AutoLISP, .NET API, VBA macros, Express Tools) is a different paradigm from Kerf's HTTP/JSON-RPC SDK.
- **No .dwg export.** Kerf writes DXF, not native .dwg. For workflows that require round-trip .dwg editing in AutoCAD or AutoCAD LT, this is a real limitation.
- **No AEC vertical tools.** Civil 3D, AutoCAD Architecture, AutoCAD MEP, Plant 3D, and AutoCAD Electrical workflows are not available in Kerf.
- **No paper-space / model-space.** Kerf's multi-sheet drawings use view projection from 3D models; it does not replicate AutoCAD's paper-space multi-scale viewport workflow.
- **No sheet sets.** AutoCAD's Sheet Set Manager for coordinating multi-drawing project output has no Kerf equivalent.
- **Command-line driven power-user workflow.** AutoCAD's keyboard-driven command line is the paradigm for power users. Kerf replaces it with chat, which is a different model not all users will prefer.

## Side by side

| Feature | AutoCAD | Kerf |
|---|---|---|
| License | ⚠️ Proprietary subscription | ✅ MIT open-core |
| Cost | ⚠️ ~US$255/mo or ~US$2,030/yr | ✅ Free local; pay-as-you-go hosted |
| Platform | ⚠️ Windows primary; macOS (feature-restricted) | ✅ Browser + Win/macOS/Linux binary |
| Design intent | ✅ 2D drafting-first with 3D modelling | ✅ 3D parametric-first with drawing export |
| 2D drafting depth | ✅ Industry-defining: dynamic blocks, paper-space, dimension styles | ⚠️ Drawing views + dimensions; 2D is not primary |
| 3D parametric modeling | ⚠️ Solid/surface 3D; not competitive with Inventor/Fusion | ✅ OCCT feature tree — full parametric history |
| Constraint sketcher | ⚠️ Basic 2D constraints | ✅ Sketcher v2 — full parametric constraints |
| Dynamic blocks | ✅ Full dynamic blocks | ❌ Not available |
| Paper-space / viewports | ✅ Full paper-space multi-scale viewports | ⚠️ Drawing sheets with view projection |
| Sheet sets | ✅ Sheet Set Manager | ❌ Not available |
| .dwg native read | ✅ Native format owner | ✅ DWG import Tier 1 (libredwg bridge) |
| .dwg native write | ✅ Native | ⚠️ Writes DXF (not native DWG) |
| STEP / IGES / IFC | ✅ STEP / IGES; IFC via Architecture vertical | ✅ STEP / IGES / IFC import + STEP export |
| AutoLISP / .NET / VBA | ✅ Deep automation ecosystem | ❌ Different paradigm (HTTP/JSON-RPC SDK) |
| Python scripting | ⚠️ pyautocad (community); no official PyPI SDK | ✅ kerf-sdk on PyPI — HTTP/JSON-RPC |
| Chat / LLM workflow | ⚠️ AI Assist (limited; not source-level) | ✅ Chat-native — edits feature-tree source |
| Electronics / PCB | ❌ No PCB design | ✅ Full EDA — schematic, routing, DRC, Gerber |
| Jewelry tooling | ❌ None | ✅ 40-module jewelry suite |
| CAM / fabrication | ❌ No CAM | ✅ 3-axis CAM + tool DB; 5-axis 3+2 |
| Civil 3D / AEC verticals | ✅ Full civil infrastructure + MEP + Plant 3D | ❌ Not available |
| BYO LLM / key | ❌ No configurable LLM | ✅ BYO key (kerf_byo) |
| Open source | ❌ Proprietary | ✅ MIT — full codebase on GitHub |
