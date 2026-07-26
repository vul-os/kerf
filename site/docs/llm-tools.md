# LLM tools (~150)

Kerf exposes ~150 Python tools the LLM can call. Tools are contributed by
plugins under `packages/kerf-*/src/kerf_*/tools/` and registered into the
shared `ToolRegistry` carried on `PluginContext`. When a chat message arrives,
the LLM decides which tool to call; the chat plugin (`kerf-chat`) dispatches
via asyncio and streams results back.

Which tools are live depends on which plugins are installed in the active
persona — query `GET /health/capabilities` to see the live set.

## How it all works

The tool system follows a **doc-search-first** pattern:

1. The LLM receives a user request (e.g. *"add a fillet to this part"*).
2. It calls `search_kerf_docs("fillet")` — this hits an embedded markdown
   corpus loaded at boot from every plugin that ships an `llm_docs/` folder
   and returns `{path, title, excerpt, score}`.
3. The LLM reads the relevant doc via `read_file` (paths under `/docs/llm/` are
   routed to the corpus, not the project tree).
4. Armed with the right conventions, the LLM calls the low-level tools
   (`read_file`, `edit_file`, `create_file`, etc.) to mutate the JSON directly.

This keeps the tool surface stable — new domain knowledge lives in docs,
not new tool functions.

### Registering a tool

Inside a plugin's `register()` function:

```python
from kerf_core.plugin import ToolSpec

ctx.tools.register(
    name="feature_fillet",
    spec=ToolSpec(
        name="feature_fillet",
        description="Add fillet to specified edges.",
        parameters={
            "type": "object",
            "properties": {
                "part_path": {"type": "string"},
                "edge_ids": {"type": "array", "items": {"type": "string"}},
                "radius":   {"type": "number"},
            },
            "required": ["part_path", "edge_ids", "radius"],
        },
    ),
    handler=run_feature_fillet,
)
```

Write-vs-read filtering is enforced inside the dispatcher by name pattern
(`set_`, `add_`, `create_`, `delete_`, `run_`, `write_`, …) or via an
explicit `write=True` flag on the spec.

### The agent loop

```
User message
    └─▶ LLM decides: search_kerf_docs or direct tool call
            ├─▶ search_kerf_docs → read_file (corpus) → direct tools
            └─▶ direct tool call → agent loop → asyncio dispatch → result
                    └─▶ stream back to LLM
```

The loop never modifies files directly — it always delegates to tools.
All results are JSON with a predictable shape the LLM can reason about.

## Permissions

Every tool is **read** (viewer+) or **write** (editor+). Viewers calling
write tools get `{"error":"...", "code":"FORBIDDEN"}` — never a 500.
Tool errors are always JSON the model can inspect and respond to.

---

## File ops

Basic read/write/manipulate on the project tree. All paths are POSIX-like,
absolute, no trailing slash. The `import_*` tools pull external formats
(STEP, Rhino 3DM, KiCad, OpenSCAD) into native Kerf geometry. Imports
are subject to a 30 s timeout and 50 MB cap per file.

`list_files` · `read_file` · `write_file` · `edit_file` · `create_file` · `delete_file` · `search_code` · `validate_jscad` · `import_step` · `import_3dm` · `import_kicad` · `import_openscad`

### Path conventions

- POSIX: leading `/`, no trailing `/`
- Root is `/` (project root)
- `/docs/llm/*` paths are routed to the authoring corpus (not the project tree)
- Soft-delete: `delete_file` sets `deleted_at`; it does not drop the bytes until purge

---

## Sketching

Sketch entities (lines, arcs, circles, splines, B-splines) and the
constraint solver. Constraints are either geometric (coincident,
parallel, perpendicular, tangent, equal…) or dimensional (distance,
angle, radius…). The sketch doc (`packages/kerf-chat/llm_docs/sketch.md`)
has the full constraint vocabulary and entity ID reference.

`sketch_add_entity` · `sketch_add_constraint` · `sketch_set_constraint_value` · `sketch_delete_entity` · `sketch_trim` · `sketch_extend` · `sketch_carbon_copy` · `sketch_validate` · `sketch_offset_selection` · `sketch_convert_curve_type`

---

## Features

OCCT-style timeline operations — pad, pocket, revolve, fillet, chamfer,
sweep, blend, draft, rib, mirror, helix, multi-transform, push-pull,
and surface/curve operations. Features are stored as JSON nodes in
`.feature` files; each node carries a `type`, a set of references to
sketch geometry or existing features, and domain-specific parameters.

> **Kernel note for tool authors**: the feature tools above edit the JSON
> feature tree and trigger server-side evaluation. The actual geometry
> evaluation (B-rep topology, booleans, fillets, face naming) happens inside
> `kerf-cad-core/geom/` — a pure-Python library that is *not* exposed as LLM
> tools. Do not add `ctx.tools.register(...)` calls that wrap kernel internals
> directly; the correct pattern is a feature-node tool that the evaluator
> dispatches through the `FeatureDAG`. See `docs/architecture.md §Pure-Python
> geometry kernel` for what the kernel owns.

`feature_pad` · `feature_pocket` · `feature_revolve` · `feature_fillet` · `feature_chamfer` · `feature_shell` · `feature_sweep1` · `feature_sweep2` · `feature_network_srf` · `feature_blend_srf` · `feature_draft` · `feature_rib` · `feature_mirror` · `feature_helix` · `feature_multi_transform` · `push_pull` · `rotate_face` · `surface_continuity` · `curve_project_to_surface` · `curve_intersect` · `curve_blend` · `curve_match` · `curve_offset_3d` · `polyline_to_nurbs` · `simplify_curve`

### Editing features

Features live in `.feature` files as a JSON array. To add a fillet:
1. `read_file` the `.feature` to find the edge IDs and current node list
2. `edit_file` to push a `{type:"fillet", edge_ids:[…], radius:3}` node
The feature tree is evaluated in order; later features can reference earlier
results by their output node ID.

---

## Mesh + SubD + 3DM

Polygonal modeling, subdivision surfaces, and Rhino 3DM interchange.
Mesh tools cover the full repair-decimate-smooth cycle. SubD tools
build NURBS-quality subdivision geometry. 3DM tools handle bidirectional
Rhino file exchange.

`mesh_validate` · `mesh_decimate` · `mesh_smooth` · `mesh_repair` · `mesh_fill_holes` · `mesh_remesh` · `surface_from_points` · `create_subd` · `subdivide_subd` · `extrude_face_subd` · `bevel_edge_subd` · `set_edge_crease` · `import_3dm` · `export_3dm`

---

## Assembly + Mates

Component placement, rigid groups, and mechanical mates. Assemblies
are hierarchical — an assembly can contain sub-assemblies and parts.
Components reference external part files by path. Mates constrain DOFs
between component origins (coincident, parallel, distance, angle, gear,
rack-pinion, cam…). After any structural change, call `solve_assembly`
to recompute positions.

`assembly_add_external_component` · `assembly_add_component` · `add_mate` · `delete_mate` · `list_mates` · `solve_assembly` · `bulk_refresh_external_refs` · `lock_assembly`

### Hierarchy rules

- An assembly can contain `assembly` or `part` components
- Rigid groups lock relative positions within a group
- `lock_assembly` prevents any degree of freedom from solving
- `bulk_refresh_external_refs` relinks all out-of-date component paths

---

## Equations + Configurations + Graph

Parametric equations, named configurations, and the solver graph.
Equations drive dimensions across parts and features. Configurations
bundle equation snapshots for what-if studies. The graph API exposes
nodes and edges for the solver dependency DAG — useful for driving
complex parametric interdependencies.

`read_equations` · `set_equation` · `add_configuration` · `set_active_config` · `create_graph` · `add_graph_node` · `connect_graph_nodes` · `set_graph_param` · `evaluate_graph`

### Equations vs. graph

Equations are the high-level API (human-readable key → value). The graph
is the low-level DAG: nodes are parameters or operations, edges carry
dependencies. `evaluate_graph` runs the solver on the full DAG and returns
updated parameter values.

---

## Architecture / BIM

Full architectural workflow: elements, categories, hosts, families,
types, schedules, views, sheets, revisions, phases, stairs, railings,
MEP routing, and curtain walls. BIM docs cover IFC import/export, element
category taxonomy, host/hosted element relationships, and family-building
conventions.

`create_bim` · `read_bim` · `compile_bim_to_ifc` · `read_ifc` · `set_element_category` · `set_element_host` · `unset_element_host` · `move_element` · `find_hosted` · `validate_bim_categories` · `create_family` · `add_family_param` · `add_family_type` · `instantiate_family` · `update_instance` · `bulk_set_type_param` · `apply_type_to_instance` · `clone_type` · `delete_type` · `create_schedule` · `update_schedule_filter` · `run_schedule` · `create_view` · `set_view_filters` · `add_view_annotation` · `run_view` · `create_sheet` · `add_viewport_to_sheet` · `remove_viewport` · `add_revision_cloud` · `add_sheet_revision` · `set_active_sheet_revision` · `list_sheet_revisions` · `update_title_block_field` · `set_phase` · `add_view_filter` · `remove_view_filter` · `create_stair` · `add_stair_flight` · `add_stair_landing` · `validate_stair` · `create_railing` · `railing_from_stair` · `set_baluster_spacing` · `validate_railing` · `create_mep_route` · `add_mep_segment` · `add_mep_fitting` · `auto_route_mep` · `compute_route_pressure_drop` · `create_curtain_wall` · `set_curtain_wall_division` · `set_curtain_wall_panel_type` · `set_curtain_wall_mullion_type` · `validate_curtain_wall`

---

## Electronics — schematic

ERC, probes, buses, sub-sheets, hierarchical labels, and flattening.
The circuit doc (`packages/kerf-chat/llm_docs/circuit.md`) covers tscircuit
JSX patterns and selector syntax for schematic elements.

`add_probe` · `remove_probe` · `rename_probe` · `run_erc` · `add_bus` · `expand_bus` · `add_differential_pair` · `list_differential_pairs` · `add_sub_sheet` · `remove_sub_sheet` · `add_global_label` · `add_hierarchical_label` · `flatten_hierarchy` · `validate_hierarchy`

---

## Electronics — PCB

Routing, copper pours, DRC, layers, net classes, length tuning,
via stitching, pad overrides, and shove router. Full parameter reference
in the PCB docs. DRC runs rule checks on the board; `set_drc_rule` lets
you define custom clearance, width, and via rules per net class.

`route_trace_segments` · `delete_trace` · `split_trace` · `merge_traces` · `move_trace_vertex` · `add_copper_pour` · `delete_copper_pour` · `set_pour_net` · `set_pour_clearance` · `run_pcb_drc` · `set_drc_rule` · `add_pcb_layer` · `remove_pcb_layer` · `set_pcb_layer_visibility` · `set_pcb_layer_color` · `reorder_pcb_layers` · `set_board_layer_count` · `assign_to_layer` · `define_net_class` · `assign_net_to_class` · `remove_net_class` · `list_net_classes` · `get_effective_net_rules` · `set_trace_target_length` · `tune_trace_to_target` · `match_diff_pair` · `report_diff_pair_skew` · `add_via_stitching` · `apply_teardrops` · `remove_via_stitching` · `set_pad_mask_override` · `set_pad_paste_override` · `clear_pad_overrides` · `route_with_shove` · `autoroute_circuit`

### Net class workflow

1. `define_net_class("Power", width_mils=40, clearance_mils=12)`
2. `assign_net_to_class("VCC", "Power")` for each power net
3. `get_effective_net_rules` to verify the rules applied correctly
4. `tune_trace_to_target` or `set_trace_target_length` for length matching

---

## Analysis

FEA, simulation, RF, topology optimization, tolerance analysis, and
inspection. Jobs are submitted asynchronously; status tools poll for
completion. `compare_models` diffs two version of the same part.

`fem_run` · `fem_job_status` · `run_simulation` · `sim_job_status` · `run_rf_study` · `rf_job_status` · `import_touchstone` · `topo_run` · `tolerance_stack` · `tolerance_monte_carlo` · `compare_models`

---

## CAM

CNC machining operations. Jobs run asynchronously; check status with
the `_status` tool. `cam_run` submits a job and returns a job handle;
`cam_job_status` returns current state (queued / running / done / error).

`cam_run` · `cam_job_status`

---

## Materials + Distributors

Material lookup by name or property, and assignment to parts.
`find_material_by_name` does a fuzzy search across the material library.
Distributor stock lookups go through the API routes and are not part
of the core tool set.

`read_material` · `find_material_by_name` · `set_part_material`

---

## Render

Ray-traced renders with camera, lighting, and material overrides.
Render jobs are async; poll with `run_render` and check status.
Camera, lights, and material overrides can be set before running.

`create_render` · `set_render_camera` · `add_render_light` · `set_render_material_override` · `run_render`

---

## Layers / Canvas

Layer management and display modes. Layers group objects for visibility,
color, and rendering control. `assign_to_layer` places objects on canvas
layers; `switch_display_mode` changes the viewport shading (wireframe,
shaded, rendered, x-ray…).

`create_layer` · `delete_layer` · `set_layer_visibility` · `set_layer_color` · `assign_to_layer` · `switch_display_mode`

---

## 2D Draft

Drawing creation and 2D entity manipulation. Drafts are the base geometry
for detail views and DXF export. Linear patterns, offsets, and fillet
corners build up draft geometry from primitive shapes.

`create_draft` · `add_draft_entity` · `offset_draft_entity` · `fillet_draft_corner` · `pattern_linear_draft` · `export_draft_dxf`

---

## Drawings — drafting depth

Hatches, leaders, chain dimensions, and rich text annotations for
completed drawings. These operate on drawing viewports after the drawing
structure is set up with `create_drawing`.

`add_hatch_to_drawing` · `add_leader_to_drawing` · `add_dimension_chain_to_drawing` · `add_rich_text_to_drawing`

---

## Revisions

Version history and restore. Every mutable file is soft-deleted first
(`deleted_at` timestamp); revisions let you walk and restore that history
without losing the audit trail.

`list_revisions` · `restore_revision`

---

## Misc

Scaffolding seeds, validation, autorouting, BOM generation, and doc
search. Scaffolding tools emit properly-shaped JSON/TSX with version
fields and defaults — the LLM then edits via the standard file ops.
This avoids the LLM having to guess the schema for a new file.

`search_kerf_docs` · `run_validation` · `autoroute_circuit` · `duplicate_object` · `delete_object` · `create_part` · `create_sketch` · `create_feature` · `create_circuit` · `create_drawing` · `generate_bom`

---

## Authoring corpus

`search_kerf_docs` hits the embedded markdown corpus loaded at boot from
every plugin's `llm_docs/` folder — guides that document conventions for
sketch constraints, feature parameters, assembly mates, PCB routing, BIM
categories, and more. After searching, the LLM reads the relevant doc then
edits the file's JSON directly.

Plugins contributing the corpus today: `kerf-chat`, `kerf-imports`,
`kerf-bim`, `kerf-electronics`, `kerf-render`.

## When to use which tool — usage patterns

### Geometry edits

- *"Make this 6 mm thick"* → `read_file` the `.feature`, then `edit_file`
  with a tight substring pair on the pad's `depth` field.
- *"Add a fillet to the top edge"* → `search_kerf_docs("fillet feature")`
  → `read_file('/docs/llm/feature.md')` → `read_file` the feature →
  `edit_file` to append a fillet node.
- *"Sweep this profile along this rail"* → `search_kerf_docs("sweep")`
  → read the sweep section → `edit_file` to add a `feature_sweep1` node.

### Assembly operations

- *"Insert two of bracket.jscad's wall Object"* → `search_kerf_docs("assembly add component")`
  → `read_file('/docs/llm/assembly.md')` → `read_file` bracket to get
  Object ids → `edit_file` the assembly's `components` array.
- *"Mate these two faces with a distance of 5 mm"* → `add_mate` with
  type `distance`, references to the two faces, and `distance=5`.
- *"Refresh all external references after moving a part"* → `bulk_refresh_external_refs`.

### Schematic / PCB

- *"Run ERC on this sheet"* → `run_erc` on the open schematic.
- *"Add a differential pair to USB+ and USB-"* → `add_differential_pair`
  with the two net names.
- *"Route net N$5 between these two pads"* → `route_trace_segments` or
  `autoroute_circuit`.
- *"Set all power traces to 40 mils"* → `define_net_class` (or update
  existing) + `assign_net_to_class`.

### BIM / Architecture

- *"Set all door instances to category Door"* → `set_element_category`
  with a filter for door instances.
- *"Host this wall to the floor below it"* → `set_element_host` with
  the wall and floor references.
- *"Create a 2nd floor stair"* → `create_stair` → `add_stair_flight` →
  `add_stair_landing` → `validate_stair`.
- *"Auto-route this MEP route"* → `create_mep_route` → `auto_route_mep`
  → `compute_route_pressure_drop` to validate sizing.
- *"Build a curtain wall with 150 mm mullions"* → `create_curtain_wall`
  → `set_curtain_wall_division` → `set_curtain_wall_mullion_type`
  → `validate_curtain_wall`.
- *"Add a revision cloud to sheet A3"* → `set_active_sheet_revision` →
  `add_revision_cloud` on the sheet.

### Drawings

- *"Create a 3-view drawing of the assembly"* → `create_file` with
  `kind='drawing'` and `{}` content (frontend hydrates defaults), or
  `search_kerf_docs("drawing standard views")` → seed via `write_file`.
- *"Add a section hatch to this view"* → `add_hatch_to_drawing`.

### History and recovery

- *"What did this file look like an hour ago?"* → `list_revisions`, then
  `restore_revision` if the user confirms.
- *"Restore to version 3"* → `restore_revision` with the revision ID.

## Where things live

- **Tool registry contract**: `packages/kerf-core/src/kerf_core/plugin.py` (`ToolRegistry`, `ToolSpec`)
- **Implementations**: each plugin's `tools/` subpackage
- **Authoring corpus**: each plugin's `llm_docs/` folder
- **Wire schema**: `docs/v1-rpc.md` + the per-plugin `llm_docs/`

Adding a tool = write the handler in the right plugin + one
`ctx.tools.register(...)` call inside that plugin's `register()` function.
Adding an authoring doc = drop the `.md` into the right plugin's `llm_docs/`
folder + restart the server.

### Plugin → tool surface

| Plugin            | Tool modules (under `tools/`)                                              |
|-------------------|---------------------------------------------------------------------------|
| `kerf-api`        | `file_ops`, `object_ops`, `scaffold`, `revisions`, `configurations`, `equations`, `validation` |
| `kerf-chat`       | `docs` (search_kerf_docs)                                                  |
| `kerf-cad-core`   | **library only — no `@register` LLM tools**. The `geom/` sub-package is a pure-Python B-rep/NURBS kernel (topology, Euler operators, validated booleans, G1/G2 fillets, closest-point, SSI, parametric feature DAG with persistent face naming). Other plugins (`kerf-imports`, `kerf-electronics`, etc.) import from it directly; the LLM never calls into it via the tool registry. |
| `kerf-imports`    | `import_3dm`, `subd`, `mesh`, `curve_ops`, `draft`, `inspection`, `graph`, `feature_helix`, `drawings` |
| `kerf-bim`        | `bim`, `bim_categories`, `family`, `schedule`, `view`, `sheet`, `stairs`, `railings`, `mep`, `curtain_wall` |
| `kerf-electronics`| `erc`, `buses`, `net_classes`, `length_tuning`, `via_stitching`, `shove_router`, `pad_overrides`, `hier_schematic`, `routing`, `pour`, `pcb_drc`, `pcb_layer_tools`, `autoroute`, `rf`, `spice` |
| `kerf-fem`        | `fem`, `sim`                                                               |
| `kerf-cam`        | `cam`                                                                      |
| `kerf-topo`       | `topo`                                                                     |
| `kerf-mates`      | `assembly`, `mates`, `tolerance`                                           |
| `kerf-render`     | `render`                                                                   |
| `kerf-pub`        | DMTAP-PUB Workshop publish/fetch/resolve/submit tools — MIT, mounted unconditionally on every node |
