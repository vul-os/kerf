# What's New

Recent features shipped to Kerf. See [ROADMAP.md](https://github.com/imranp/kerf/blob/main/ROADMAP.md) for the full list and status of every item.

## Sprint — May 2026 (Massive Feature Wave)

### Sketcher / Mechanical
6 new constraints (horizontal/vertical distance, symmetric, block, equal angle, parallel). Arc/circle edge projection for external geometry. Multi-loop holes in extrude/pocket. 3D backdrop overlay. Carbon-copy sketches with validation. [sketch.md](backend/llm_docs/sketch.md)

### Features — PartDesign / FreeCAD Parity
Helix (variable-pitch), tapered Draft, Mirror, Multi-Transform, and Rib features shipped. ~10 new curve operations (offset, extend, blend, trim, intersect, project, section, split, isotrim, swap). [feature.md](backend/llm_docs/feature.md) · [curve_ops.md](backend/llm_docs/curve_ops.md)

### Surface Modeling — Rhino Parity
SubD (Catmull-Clark subdivision surfaces). Full 3DM import/export. Mesh tools: remesh, decimate, smooth, repair, fill-holes, surface-from-points. Render-quality output via Blender Cycles. Parametric `.graph` (Grasshopper-equivalent). [subd.md](backend/llm_docs/subd.md) · [import_3dm.md](backend/llm_docs/import_3dm.md) · [mesh.md](backend/llm_docs/mesh.md) · [render.md](backend/llm_docs/render.md) · [graph.md](backend/llm_docs/graph.md)

### Drawings — Draft Workbench
Hatch patterns, leader lines, rich text, and dimension chains — full drafting completeness. Draft workbench (2D CAD) for technical drawings. [drawing.md](backend/llm_docs/drawing.md) · [draft.md](backend/llm_docs/draft.md)

### Architecture — Revit Parity
IFC compiler (`POST /compile-ifc` → IFC4 via IfcOpenShell). `.family.json` parametric components, `.schedule.json` query DSL, `.view.json` saved views, `.sheet.json` print layouts. Categories + hosted references, type vs instance params, phasing + view filters. Stairs, railings, MEP routing (`.duct`/`.pipe`/`.conduit`), curtain wall, sheet revisions. [bim.md](backend/llm_docs/bim.md) · [family.md](backend/llm_docs/family.md) · [schedule.md](backend/llm_docs/schedule.md) · [view.md](backend/llm_docs/view.md) · [sheet.md](backend/llm_docs/sheet.md) · [stairs.md](backend/llm_docs/stairs.md) · [railings.md](backend/llm_docs/railings.md) · [mep.md](backend/llm_docs/mep.md) · [curtain_wall.md](backend/llm_docs/curtain_wall.md) · [sheet_revisions.md](backend/llm_docs/sheet_revisions.md)

### Electronics — KiCad Parity
Manual trace routing, copper pours/ground planes, full layer stack. PCB DRC, ERC (electrical rules check), net classes. Length tuning + diff-pair match, via stitching + teardrops. Push-pull (shove) router. Hierarchical schematics, buses + differential pairs. Per-pad mask/paste overrides. [circuit.md](backend/llm_docs/circuit.md) · [pcb_layers.md](backend/llm_docs/pcb_layers.md) · [pcb_drc.md](backend/llm_docs/pcb_drc.md) · [erc.md](backend/llm_docs/erc.md) · [net_classes.md](backend/llm_docs/net_classes.md) · [length_tuning.md](backend/llm_docs/length_tuning.md) · [via_stitching.md](backend/llm_docs/via_stitching.md) · [shove_router.md](backend/llm_docs/shove_router.md) · [hier_schematic.md](backend/llm_docs/hier_schematic.md) · [buses.md](backend/llm_docs/buses.md) · [pad_overrides.md](backend/llm_docs/pad_overrides.md)

### Workshop / Library / Cloud
Workshop + Library endpoints ported. Cloud git → S3 Storer (stateless serverless). Large-file `.step-ref` Phase 1 (JSON pointer + object storage). GitHub OAuth. AES-GCM encrypt utility. [library.md](backend/llm_docs/library.md) · [derived_cache.md](backend/llm_docs/derived_cache.md)

### Inspection / Misc
Model comparison tool. Distributor catalog ported. Configurable layers + display modes. [inspection.md](backend/llm_docs/inspection.md) · [distributors.md](backend/llm_docs/distributors.md) · [workspace.md](backend/llm_docs/workspace.md)
