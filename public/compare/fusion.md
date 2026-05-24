---
slug: fusion
competitor: "Autodesk Fusion 360"
category: cad-mechanical
left: kerf
right: fusion
hero_tagline: "Cloud-connected multi-discipline CAD — two tools, two philosophies."
reviewed_at: 2026-05-19
order: 2
---

# Kerf vs Autodesk Fusion 360

Fusion 360 pioneered the idea of integrated CAD / CAM / CAE / PCB in a single cloud-connected workspace and has millions of users behind it. Kerf is the tool most similar to Fusion in shape — both cover multi-discipline engineering in one environment with cloud collaboration. Commercial use is ~US$680/yr (as of May 2026); a restricted free personal tier exists (non-commercial, <US$1,000 annual revenue, as of May 2026). The differences are in philosophy: Fusion is a closed subscription product with a polished decade-long track record; Kerf is MIT open-core, chat-native, and subscription-free. Below is an honest look at both.

## Where Fusion 360 is strong

- **Cloud-native + desktop in one.** Fusion is designed cloud-first — every project auto-saves to Autodesk's cloud, multi-user collaboration is baked in, and the same tool runs on Windows and macOS as a native desktop app.
- **HSMWorks-lineage CAM.** The CAM workspace inherits HSMWorks' industry-tested toolpath engine with verified simulation, a broad post-processor library, and years of in-the-field machining validation. Kerf's CAM is younger.
- **Cloud generative design.** Automated topology exploration across load cases using cloud compute — a flagship capability for lightweighting and lattice design. Kerf has no equivalent we're aware of today.
- **T-spline sculpt workflow.** The Sculpt workspace gives direct freeform surface modelling with T-spline subdivision and crease support. Kerf's early NURBS Phase 4 does not match.
- **Assembly motion study and interference detection.** Fusion provides motion studies, contact sets, and interference detection on top of its joint system. Kerf now matches the joint type set but does not yet ship motion study.
- **FEM multi-physics depth.** Linear static and thermal FEM (extension / cloud-metered) with a mature solver validation record.
- **Eagle PCB integration.** Fusion Electronics is the direct successor to Autodesk EAGLE, with a native ECAD↔MCAD live link.
- **Decades of vendor polish and community.** Millions of users, an extensive official learning platform, and integration with the wider Autodesk portfolio.

## Where Kerf differs

- **MIT open-core, no subscription.** Fusion charges ~US$680/yr (as of May 2026); its free tier is non-commercial only. Kerf's full feature set is MIT-licensed — free locally with no revenue restriction, no seat fee, and no feature-gating.
- **BYO LLM / BYO key.** Bring your own Anthropic or OpenAI API key and zero billing flows through Kerf — the `kerf_byo` tier routes all inference to your own account. Fusion has no configurable LLM we're aware of (as of May 2026).
- **Chat-native workflow.** Describe a feature, constraint, routing rule, or simulation check in plain language; the LLM edits the feature-tree source backed by live doc-search. Fusion has no comparable LLM integration we're aware of (as of May 2026).
- **True offline, fully open codebase.** `pip install 'kerf[server]'` + `kerf serve` with BYO Postgres — no Autodesk account, no limited-offline caveat. The full codebase is on GitHub under MIT.
- **Pre-compliance electronics simulation — in-box.** Signal integrity, EMC/EMI, PDN, and PCB thermal are all included without extension or cloud-metering. Fusion gates these behind paid extensions.
- **Richer in-box electronics fab output.** Gerber / Excellon / IPC-2581 / ODB++ / IPC-D-356A netlist and DRC with IPC-2221B A/B/C manufacturing presets — beyond Fusion Electronics' base fab pack.
- **40-module jewelry domain.** Ring v4, gemstones v2 (30 cuts), settings v3/v4, gem-seat v2, chain v2, findings, casting export, a 31-template library, and PBR gem/metal viewport materials — a complete professional jewelry vertical.
- **620 analytic-oracle kernel tests.** Every core geometric operation is regression-tested against closed-form analytic references.
- **kerf-sdk Python scripting.** Automate over HTTP/JSON-RPC from your own machine — the same interface the LLM uses internally.

## Honest gaps — where Kerf is behind today

- **CAM fidelity and validation.** Fusion's CAM has years of in-the-field toolpath validation and the HSMWorks pedigree. Kerf's CAM is younger and less hardened.
- **Assembly motion study.** Kerf now matches Fusion's joint type set, but motion studies, contact sets, and interference detection are not yet shipped.
- **FEM multi-physics coverage.** Kerf ships linear static, thermal, and nonlinear plasticity FEM; Fusion's multi-physics cloud solvers cover more boundary conditions and load types. CFD is not in Kerf.
- **No generative design.** Fusion's cloud topology optimisation across load cases is a flagship that has no Kerf counterpart today.
- **No T-spline freeform / Sculpt.** Fusion's Sculpt workspace for organic freeform modelling has no Kerf counterpart. NURBS Phase 4 is early and scope-limited.
- **Direct modelling is limited.** Fusion's ability to intermix direct editing with the parametric timeline is more capable than Kerf's current feature-tree-primary approach.
- **Smaller community, fewer tutorials.** Fusion has millions of users and a mature learning platform. Kerf is early-stage.

## Side by side

| Feature | Fusion 360 | Kerf |
|---|---|---|
| License | ⚠️ Proprietary subscription | ✅ MIT open-core |
| Cost | ⚠️ ~US$680/yr (May 2026); startup ~$150/3yr (May 2026) | ✅ Free local; pay-as-you-go hosted |
| Free tier | ⚠️ Personal-use only (<US$1k rev, May 2026) | ✅ Full free local install, no revenue cap |
| BYO LLM / model key | ❌ No | ✅ BYO key (kerf_byo bucket) |
| Offline / self-host | ⚠️ Limited offline; many features cloud-tied | ✅ Full offline: pip install 'kerf[server]' |
| OS support | ✅ Windows + macOS | ✅ Browser + Win/macOS/Linux binary |
| Parametric B-rep | ✅ Timeline-based modelling (mature) | ✅ OCCT feature tree |
| Constraint sketcher | ✅ Full parametric sketcher | ✅ Sketcher v2 — all major constraints |
| Sheet metal | ✅ Full sheet-metal workspace | ✅ Flange + unfold + flat-pattern DXF |
| Freeform / T-spline sculpt | ✅ Sculpt workspace (industry-quality) | ⚠️ NURBS Phase 4 (early) |
| Assembly joints | ✅ Full joint system | ✅ Full joint system — rigid/revolute/slider/cam/gear/pin-slot |
| Motion study | ✅ Motion + contact sets + interference | ❌ Not yet |
| CAM (3-axis) | ✅ HSMWorks-lineage CAM (mature) | ✅ 3-axis CAM + tool DB |
| Multi-axis CAM | ✅ 4/5-axis (paid extension) | ✅ 5-axis CAM 3+2 |
| Generative design | ✅ Cloud topology optimisation | ❌ Roadmap |
| FEM (static / thermal) | ✅ Built-in (extension / cloud-metered) | ⚠️ Linear static + thermal; not full parity |
| SI pre-compliance | ⚠️ Via paid Fusion extension | ✅ In-box — transmission-line, via stub, diff pair |
| EMC / EMI analysis | ⚠️ Extension-gated; basic | ✅ Common-mode, return-path gap, slot antenna |
| PDN analysis | ⚠️ Extension-gated | ✅ Decap placement, target impedance, plane resonance |
| Thermal (PCB) | ⚠️ Extension-gated cooling analysis | ✅ Copper pour, via thermal relief, hot-spot |
| 2D drawings | ✅ Full drawing + annotations | ✅ Multi-sheet drawings |
| Electronics (schematic + PCB) | ✅ Fusion Electronics (EAGLE-derived) | ✅ Hierarchical schematic + PCB layout |
| Jewelry tooling | ❌ None | ✅ 40-module jewelry suite |
| Chat / LLM editing | ❌ None | ✅ Chat-native + doc-search backed |
| Scripting / API | ✅ Fusion API (Python / C++) | ✅ kerf-sdk on PyPI — HTTP/JSON-RPC |
| Open source | ❌ Proprietary | ✅ MIT — full codebase on GitHub |
