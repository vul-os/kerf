---
slug: blender
competitor: "Blender"
category: dcc
left: kerf
right: blender
hero_tagline: "World-class mesh / DCC tool — a different category from B-rep CAD."
reviewed_at: 2026-05-19
order: 1
---

# Kerf vs Blender

Blender is a world-class, GPL-licensed DCC tool: mesh-first modelling, sculpting, animation, rigging, Geometry Nodes, and benchmark-quality rendering via Cycles and Eevee. It is not a B-rep parametric CAD application. If you are evaluating Blender for product engineering, jewelry production, or electronics design work, this page lays out where the two tools overlap, where they diverge, and which is the right fit — or whether both belong in your pipeline.

**These are different categories of tool.** Kerf is a B-rep parametric CAD environment with multi-discipline scope (mechanical, electronics, jewelry, architecture). Blender is a mesh-first DCC and animation platform. The overlap is real, but the primary jobs are different.

## Where Blender is strong

- **Free and open-source under GPL.** Blender is fully free — no subscription, no per-seat cost, no cloud account. The GPL licence means the source code is publicly auditable and community-improvable.
- **Mesh-first modelling with BMesh.** Blender's BMesh half-edge data structure gives fast, flexible mesh editing with N-gon support. For concept sculpting and organic forms it is the benchmark tool.
- **Geometry Nodes — a real visual node DAG.** Geometry Nodes is a genuine procedural, mesh-centric node graph: instance scattering, field-driven deformation, simulation nodes. Not CAD parametric history, but a powerful generative toolset with no equivalent in Kerf yet.
- **Sculpting, dyntopo, and multires.** A full sculpt mode with dynamic topology, multi-resolution sculpting, and 30+ brushes. Kerf has no sculpt mode.
- **Cycles and Eevee render quality.** Cycles is a physically-based path tracer with GPU support. Eevee delivers real-time PBR preview. Kerf's heroShot renderer does not match Cycles quality.
- **Animation and rigging.** Full skeletal animation, NLA editor, shape keys, cloth and fluid simulations, and camera animation — capabilities Kerf has no plans to replicate.
- **Vibrant artist community.** Millions of users, Blender Market, BlenderArtists, and an enormous library of tutorials, add-ons, and asset packs.

## What Blender is not (for engineering use)

- **Not a B-rep CAD kernel.** Blender models are polygon meshes, not boundary-representation solids. No analytically exact planes, cylinders, or spline-trimmed surfaces.
- **No NURBS solids.** Blender has NURBS curve objects but no NURBS surfacing in the engineering sense.
- **No STEP B-rep round-trip.** STEP and IGES transfer B-rep geometry that machines and CAM systems expect. Blender exports mesh formats (glTF, FBX, OBJ); there is no B-rep STEP writer.
- **No GD&T or technical drawings.** Engineering drawings with ASME Y14.5 geometric dimensioning and tolerancing are out of scope for Blender by design.
- **Modifier Stack ≠ parametric feature history.** Blender's Modifier Stack is linear per-object and destructive once applied. It does not maintain persistent face IDs.
- **No electronics, no engineering-calc breadth.** There is no schematic editor, no PCB router, no BOM, no simulation pre-compliance.

## Where Kerf is positioned differently

- **B-rep solids with valid topology and tolerances.** Kerf's OCCT kernel produces exact boundary-representation solids whose faces, edges, and vertices carry stable IDs that downstream features, drawings, and CAM paths can reference reliably.
- **Parametric feature history DAG.** The feature tree (pad, pocket, revolve, loft, fillet, draft) is a persistent directed acyclic graph. Editing an early feature regenerates all downstream geometry.
- **Multi-discipline in one workspace.** Electronics (schematic + PCB + DRC + Gerber), jewelry (ring v4, gemstones v2, settings v3/v4, chain v2), 2D drawings, GD&T, CNC CAM, and architecture (IFC) share one environment.
- **STEP / IGES / 3DM B-rep interop.** Manufacturing and supply-chain tooling expects B-rep geometry in neutral exchange formats. Kerf reads and writes STEP and IGES; Blender cannot.
- **MIT open-core, with a hosted option.** The core is permissively MIT-licensed (Blender is copyleft GPL). A hosted SaaS version runs in the browser; a single binary installs locally.
- **Chat-native workflow.** Describe a change in plain language; the LLM edits the feature tree / JSCAD source directly, backed by live doc-search.

## Honest gaps — where Blender wins

- **Render quality: Cycles path-tracer.** Physically-based path tracing with GPU acceleration, volumetrics, caustics, and subsurface scattering. Kerf's heroShot renderer is not in the same class for photoreal output.
- **Sculpting and organic form development.** Dyntopo, multires, retopology, and a full brush library. Kerf has no sculpt mode and is not building one.
- **Animation, rigging, and simulation.** Skeletal animation, NLA, cloth, fluid, particles — a complete film/game pipeline. Kerf has no plans here.
- **Geometry Nodes visual DAG.** A mature, shipped visual node environment for mesh-centric procedural work. Kerf's parametric DAG engine has landed; the visual node UI bindings are still to come.
- **Community and ecosystem depth.** Millions of users, thousands of add-ons, an enormous asset marketplace, and 30 years of accumulated tutorials.

## Side by side

| Feature | Blender | Kerf |
|---|---|---|
| License | ✅ GPL v2+ (free, copyleft) | ✅ MIT open-core (permissive) |
| Cost | ✅ Free, no subscription | ✅ Free local binary; pay-as-you-go hosted |
| Platform | ✅ Win / macOS / Linux desktop | ✅ Browser + single-binary local |
| Hosted / cloud | ❌ Desktop only | ✅ Hosted SaaS + local install |
| B-rep solid kernel | ⚠️ BMesh half-edge — no B-rep | ✅ OCCT B-rep — exact rational |
| Parametric history (feature DAG) | ⚠️ Linear Modifier Stack — not persistent face-ID DAG | ✅ OCCT feature tree + persistent face IDs |
| Constraint sketcher | ❌ None | ✅ Sketcher v2 — geometric + dimensional constraints |
| STEP / IGES B-rep interop | ❌ Mesh export only (glTF/FBX/OBJ) | ✅ STEP / IGES / 3DM B-rep round-trip |
| Visual node DAG | ✅ Geometry Nodes (mesh-centric) | ⚠️ Parametric DAG landed; visual UI to come |
| Sculpting + dyntopo | ✅ Full sculpt mode — dyntopo, multires, 30+ brushes | ⚠️ Mesh tools + quad remesh; no sculpt mode |
| SubD authoring | ✅ Subdivision Surface modifier + creases | ⚠️ Quad remesh + surfacing; no SubD authoring |
| Path-traced renderer | ✅ Cycles + Eevee (benchmark) | ⚠️ HDRI + ACES + bloom (heroShot.js); no full path tracer |
| Animation / rigging | ✅ Full skeletal, NLA, cloth sim | ❌ No animation or rigging |
| GD&T / tolerances | ❌ None | ✅ ASME Y14.5 datum + tolerance framework |
| 2D technical drawings | ❌ None | ✅ Multi-sheet drawings |
| Electronics / PCB | ❌ Not applicable | ✅ Full EDA — schematic, routing, DRC, Gerber/IPC-2581 |
| CNC CAM | ❌ None | ✅ 3-axis CAM + tool DB; 5-axis 3+2 |
| Chat / LLM editing | ❌ None | ✅ Chat-native — edits feature tree per turn |
| Python scripting | ✅ bpy — full in-process Python API | ✅ kerf-sdk on PyPI — HTTP/JSON-RPC |
