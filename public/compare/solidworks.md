---
slug: solidworks
competitor: "SOLIDWORKS"
category: cad-mechanical
left: kerf
right: solidworks
hero_tagline: "30 years of Parasolid-kernel polish — compared honestly against MIT open-core."
reviewed_at: 2026-05-19
order: 3
---

# Kerf vs SOLIDWORKS

SOLIDWORKS (Dassault Systèmes) is the dominant professional mechanical CAD platform with 30+ years of refinement, millions of seats, and the Parasolid kernel under the hood. Standard licence ~US$4,000 perpetual + ~$1,500/yr maintenance; subscription "SOLIDWORKS Connected" ~$2,200/yr. Windows-only native desktop; 3DExperience cloud overlay is a separate purchase. Kerf will not out-SOLIDWORKS SOLIDWORKS on assembly motion, FEM, or add-in breadth — that is an honest statement. Where Kerf differs is MIT open-core licensing, no Windows-only constraint, chat-native editing, no per-seat fee, and a multi-discipline workspace that unifies mechanical, electronics, and jewelry design without additional add-ins or subscriptions.

## Where SOLIDWORKS is strong

- **Parasolid kernel and modeling depth.** SOLIDWORKS runs on the Parasolid B-rep kernel — the same engine used by Siemens NX and Solid Edge. Decades of production hardening across millions of real-world files give it a reliability track record that newer kernels have not yet accumulated.
- **Full assembly and motion simulation.** A complete mate system (coincident, concentric, gear, cam, screw, slot), interference detection, motion analysis with contacts, and mass-property roll-up across large assemblies — mature and production-proven.
- **FEM and CFD via add-ins.** SOLIDWORKS Simulation (static, thermal, fatigue, drop-test) and Flow Simulation (CFD) are integrated add-ins that have been tuned by real engineering teams for years.
- **Weldments and structural framework.** Structural-member profiles, weldment cut lists, gussets, and end treatments give fabricators a workflow purpose-built for structural steel and tubing.
- **NURBS surfacing (Premium / SurfaceWorks).** Class-A surface modelling tools for consumer products and automotive styling are mature in SOLIDWORKS Premium.
- **Large assembly handling.** Lightweight component mode, SpeedPak, and large assembly performance settings are well-tested workflows for thousand-part assemblies.
- **Vast add-in and VAR ecosystem.** Thousands of third-party add-ins — CAM (CAMWorks, HSMWorks), PDM (SOLIDWORKS PDM), rendering (KeyShot), ERP connectors — and a global network of certified resellers.
- **Market standard and hiring pool.** SOLIDWORKS proficiency is a near-universal requirement on mechanical engineering job descriptions.

## Where Kerf differs

- **MIT open-core, no seat fee.** The full feature set is MIT-licensed and free to install locally. No $4,000 seat, no annual maintenance contract, no add-in stacking, no commercial-use restriction.
- **Chat-native workflow and BYO LLM.** Describe a feature, sketch constraint, or assembly change in plain English; the model edits the feature-tree source backed by live doc-search. Bring your own Anthropic or compatible API key with zero billing routed through Kerf.
- **CAM included in-box.** 3-axis CAM with tool DB and 5-axis 3+2 ship as part of the core product — no CAMWorks or HSMWorks add-in required.
- **Cross-platform, browser + local binary.** Runs in the browser (hosted SaaS) or as a single local binary on Windows, macOS, and Linux. No Parallels, no dedicated Windows box.
- **Full ECAD in one workspace — no add-in.** Hierarchical schematic, PCB layout, shove router, SPICE, IPC fab output, and the full pre-compliance simulation suite (SI, EMC, PDN, thermal) are built into the same workspace as the B-rep modeller, with no separate ECAD licence.
- **40-module jewelry domain.** Ring v4, gemstones v2 (30 cuts), settings v3/v4, gem-seat v2, chain v2, findings, casting export, full cost panel, and PBR gem/metal viewport materials — a professional jewelry vertical that has no SOLIDWORKS counterpart.
- **Cloud git built in.** Every project gets fine-grained file revision history (undo) plus deliberate cloud-git commits with GitHub sync — no PDM server setup, no extra subscription.
- **kerf-sdk Python scripting.** Automate B-rep, PCB, and jewelry workflows from a Python script on your own machine over HTTP/JSON-RPC.

## Honest gaps — where Kerf is behind today

- **Assembly motion study.** Kerf now matches SOLIDWORKS' joint type set (including gear, cam, pin-slot), but motion analysis, contact sets, and interference detection are not yet shipped in Kerf.
- **FEM multi-physics depth and CFD.** Kerf ships linear static, thermal, and nonlinear plasticity FEM, but SOLIDWORKS Simulation (fatigue, frequency, buckling) and Flow Simulation (CFD) are significantly more mature. CFD is not in Kerf.
- **NURBS surfacing depth.** SOLIDWORKS Premium's surfacing tools are significantly ahead of Kerf's NURBS Phase 4, which is early and scope-limited.
- **Weldments workspace.** SOLIDWORKS' structural member profiles, weldment cut lists, and gussets are a fabrication workflow Kerf does not replicate.
- **Large assembly tooling.** Lightweight components, SpeedPak, and large-assembly performance settings have no Kerf equivalent today.
- **SOLIDWORKS API depth.** The SOLIDWORKS COM API has 20+ years of depth covering every feature, mate, and drawing entity. Kerf's kerf-sdk is younger.
- **Add-in and VAR ecosystem.** Thousands of certified third-party add-ins and a global VAR network are irreplaceable near-term.

## Side by side

| Feature | SOLIDWORKS | Kerf |
|---|---|---|
| License | ⚠️ Proprietary perpetual + maintenance or subscription | ✅ MIT open-core |
| Cost | ⚠️ ~US$4,000 perpetual + ~$1,500/yr; or ~$2,200/yr Connected | ✅ Free local; pay-as-you-go hosted |
| Platform | ⚠️ Windows only | ✅ Browser + Win/macOS/Linux binary |
| Offline / self-host | ✅ Full offline (perpetual) | ✅ pip install 'kerf[server]' + kerf serve |
| Parametric B-rep | ✅ Parasolid feature tree | ✅ OCCT feature tree |
| Constraint sketcher | ✅ Full parametric sketcher | ✅ Sketcher v2 — all major constraints |
| Sheet metal | ✅ Full — flange, mitre, flat pattern | ✅ Flange + unfold + flat-pattern DXF |
| NURBS surfacing | ✅ SurfaceWorks-class (Premium) | ⚠️ NURBS Phase 4 (early) |
| Assembly / mates | ✅ Full mate system — gear / cam / screw | ✅ Full joint system — rigid/revolute/slider/cam/gear/pin-slot |
| Motion study | ✅ Motion analysis, interference | ❌ Not yet |
| Large assembly mode | ✅ SpeedPak, lightweight components | ⚠️ LOD mesh swapping (configurable) |
| 2D drawings | ✅ Full drawing environment | ✅ Multi-sheet drawings |
| GD&T | ✅ ASME / ISO GD&T with DimXpert | ✅ ASME Y14.5 datum + tolerance framework |
| CNC CAM (3-axis) | ⚠️ Requires CAMWorks / HSMWorks add-in | ✅ 3-axis CAM + tool DB (in-box) |
| Multi-axis CAM | ⚠️ Add-in required (extra cost) | ✅ 5-axis CAM 3+2 (in-box) |
| FEM / structural | ✅ SW Simulation (add-in) | ⚠️ Linear static + thermal; not full parity |
| CFD | ✅ Flow Simulation (add-in) | ❌ Not yet |
| Electronics / PCB | ⚠️ SOLIDWORKS PCB (Altium-derived, add-in) | ✅ Full hierarchical schematic + PCB layout in-box |
| SI / EMC / PDN / thermal | ❌ External tools required | ✅ si_eye_wizard + emc_wizard + pdn_wizard + thermal_board in-box |
| Jewelry tooling | ❌ None | ✅ 40-module jewelry suite |
| Chat / LLM editing | ❌ None | ✅ Chat-native + BYO API key |
| Scripting / API | ✅ SOLIDWORKS API (COM/VBA/C#) | ✅ kerf-sdk on PyPI — HTTP/JSON-RPC |
| Multi-user cloud edit | ⚠️ 3DExperience (separate SaaS) | ✅ Cloud hosted + cloud-git sync |
| Open source | ❌ Proprietary | ✅ MIT — full codebase on GitHub |
