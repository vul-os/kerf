# Mechanical workflow

End-to-end guide for a machined part: sketch → extrude → fillet/chamfer
(parametric) → tolerance stack → DFM check → fab quote → CAM stock + G-code
post → drawings.

---

## 1. Sketch

Create a `.sketch` file (kind `sketch`) and add geometry using the sketch
tools:

```
sketch_add_entity     — line / arc / circle / spline / ellipse
sketch_add_constraint — coincident / parallel / perpendicular / tangent /
                         equal / symmetric / distance / angle / radius / …
sketch_set_constraint_value
sketch_validate       — check: fully constrained? any redundant constraints?
```

Sketches are stored as JSON arrays of entity + constraint objects. The solver
is `planegcs` (the same constraint solver as FreeCAD's Sketcher). A fully
constrained sketch has zero degrees of freedom.

**Tip**: drive dimensions from equations. In `equations.toml`-style files:

```
set_equation "base_width_mm" = 40
```

Then in the sketch, set the horizontal distance constraint value to
`"$base_width_mm"`. Changing the equation re-evaluates the sketch and every
downstream feature.

---

## 2. Extrude (pad)

Add a pad feature to the `.feature` file:

```
search_kerf_docs("feature pad")
→ read /docs/llm/feature.md
→ edit_file to append:
  { "type": "pad", "sketch_ref": "sketch_0", "depth": 20, "symmetric": false }
```

The feature tree is evaluated by the `.feature` evaluator in `kerf-cad-core`
which dispatches through `FeatureDAG.regenerate()`. Only invalidated nodes
re-evaluate.

Other base operations: `feature_pocket`, `feature_revolve`, `feature_helix`,
`feature_sweep1` (one guide rail), `feature_sweep2` (two guide rails),
`feature_network_srf`, `feature_rib`.

---

## 3. Fillets and chamfers (parametric)

```
feature_fillet   — rolling-ball fillet on B-rep edges; references edges by
                   their persistent face ID (e.g. "pad_0::edge:0")
feature_chamfer  — planar or variable chamfer
feature_shell    — hollow the solid to a wall thickness
feature_draft    — apply draft angle for casting / moulding
```

**Persistent face naming** (`kerf_cad_core.geom.history.persistent_naming`):
face and edge IDs use the pattern `feature_id::role::fingerprint`. Roles are
structural labels like `face:+X`, `face:cap_bottom`, `face:boundary:0`. A
fillet referencing `pad_0::face:+Z` continues to resolve correctly after the
pad depth changes, because the role is geometry-position-based, not
index-based.

Practically: edit a `depth` parameter on a pad and fillets on the top face
survive the re-evaluation.

---

## 4. GD&T tolerance stack

`kerf_cad_core.tolstack` and `kerf_cad_core.gdt` implement the tolerance
framework.

At the file level, `.tolerance` files store dimension chains:

```json
{
  "version": 1,
  "tolerances": [
    { "id": "t1", "nominal": 40.0, "plus": 0.05, "minus": -0.05, "distribution": "normal" },
    { "id": "t2", "nominal": 20.0, "plus": 0.02, "minus": -0.02, "distribution": "normal" }
  ]
}
```

Run a stack-up analysis:

```
POST /api/projects/{pid}/files/{fid}/tolerance/run
{ "method": "monte_carlo", "samples": 100000, "rss_k": 3.0 }
```

Returns: `{ "mean": …, "std_dev": …, "cpk": …, "yield_pct": …, "histogram": […] }`.

The LLM tool `tolerance_stack` and `tolerance_monte_carlo` do the same thing
from the chat interface.

**GD&T callouts** (`kerf_cad_core.gdt_callouts`): generates ISO 1101 / ASME
Y14.5 callout strings from tolerance specs for use in drawings.

---

## 5. DFM check

`kerf_cad_core.dfm.checks` provides pure-Python DFM checks. Run via the LLM
tool `run_validation` with the `.feature` file, or directly from a test:

```python
from kerf_cad_core.dfm.checks import dfm_audit

issues = dfm_audit(mesh_or_solid, process="cnc", pull_direction=[0, 0, 1])
# Returns: [{"kind": "thin_wall", "position": […], "severity": "error",
#            "value": 0.8, "suggestion": "Increase wall to ≥1.5 mm"}]
```

DFM checks include: thin-wall detection, undercut analysis, draft angle
adequacy, re-entrant cavity detection, and inaccessible-face analysis for the
given pull direction.

References: Boothroyd et al. *Product Design for Manufacture and Assembly*,
3rd ed.

---

## 6. Fabrication quote

`kerf_cad_core.quoting.fab_quote` generates a one-click fabrication quote from
the part's geometry summary.

```python
from kerf_cad_core.quoting.fab_quote import (
    analyze_part, viable_processes, cost_per_process, recommend, quote_report
)

part = analyze_part(geometry_summary)       # PartGeometry dataclass
procs = viable_processes(part)              # CNC / casting / injection / sheet_metal / 3d_print / forging
quotes = cost_per_process(part, procs, quantity=50)
rec = recommend(quotes)
print(quote_report(part, quotes, rec))
```

The LLM surfaces this via `search_kerf_docs("fab quote")`. All values in mm /
cm³ / USD. The function never raises — errors appear in the `"ok": false` field.

---

## 7. CAM stock setup

`kerf_cad_core.cam_wizard.stock_setup` provides the CAM setup wizard:

```python
from kerf_cad_core.cam_wizard.stock_setup import (
    recommend_stock, recommend_orientation, fixture_suggestion, setup_sheet
)

stock = recommend_stock(part_aabb, material="aluminium_6061", surplus_mm=3)
# → { "stock_size": [45, 45, 25], "stock_type": "rect_bar", "waste_pct": 12.3, ... }

orientation = recommend_orientation(part_geometry_summary)
fixture = fixture_suggestion(orientation, stock["stock_size"], features_to_machine)
sheet = setup_sheet(stock, orientation, fixture)
```

`recommend_stock` selects the nearest standard EN/ISO rectangular bar, round
bar, or billet. `fixture_suggestion` returns a clamping method (vise, soft-jaw,
fixture plate, vacuum, magnetic) with clamp positions.

---

## 8. G-code post-processing

CAM jobs are run asynchronously via `kerf-cam`:

```
POST /api/projects/{pid}/files/{fid}/cam
{ "strategy": "2d_contour", "tool_diameter_mm": 6, "doc_mm": 2 }

GET  /api/projects/{pid}/files/{fid}/cam/status
→ { "status": "done", "result": { "gcode_key": "…" } }
```

The LLM tools `cam_run` and `cam_job_status` do the same from the chat
interface. `kerf_cam.posts` contains post-processors for common controllers
(Fanuc, Heidenhain, Siemens 840D, LinuxCNC). 5-axis indexed (3+2) posts live
in `kerf_cam.five_axis`.

Feed/speed recommendations come from `kerf_cad_core.cncfeeds` (based on
material, tool geometry, and operation type — references *Machinery's Handbook
30th ed.*).

Tool database: `kerf_cam.tool_db` stores standard cutting tools (end mills,
drills, reamers, taps) with geometry and recommended feeds.

---

## 9. Manufacturing drawings

See [drawings.md](./drawings.md) for the full drawing workflow. Quick summary:

1. `create_drawing` (LLM tool) seeds a `.drawing` file with standard views
   (front, top, right, isometric) linked to the `.feature` geometry.
2. Add GD&T callouts with `add_dimension_chain_to_drawing`, leaders with
   `add_leader_to_drawing`, section hatches with `add_hatch_to_drawing`.
3. The drawing re-renders automatically when the feature geometry changes.

Drawing generation uses `kerf_cad_core.drawings` (orthographic projection,
hidden-line removal, dimension placement) and `kerf_cad_core.gdt_callouts`
for GD&T annotation strings.

---

## Parametric roundtrip

The whole chain is parametric. Changing a single equation value:

```
set_equation "base_width_mm" = 45   # was 40
```

triggers:
1. Sketch solver re-runs; the horizontal distance constraint updates to 45 mm.
2. `FeatureDAG.regenerate()` re-evaluates pad, fillet (persistent names survive),
   shell.
3. DFM checks re-run with the new geometry.
4. The drawing views re-render.
5. The BOM quantity/cost figures update.

No manual re-triggering needed. This is what `docs/architecture.md §
Pure-Python geometry kernel` refers to as "edit a dimension and your fillets
survive."

---

## Module map

| Module | Location | Purpose |
|--------|----------|---------|
| `tolstack/` | `kerf_cad_core/tolstack/` | Worst-case, RSS, Monte Carlo stack-up |
| `gdt/` | `kerf_cad_core/gdt/` | GD&T tolerance schema |
| `gdt_callouts/` | `kerf_cad_core/gdt_callouts/` | ISO 1101 callout string generation |
| `tolfits/` | `kerf_cad_core/tolfits/` | ISO 286 fit/tolerance class lookup |
| `dfm/checks.py` | `kerf_cad_core/dfm/` | Pure-Python DFM geometry checks |
| `quoting/fab_quote.py` | `kerf_cad_core/quoting/` | Multi-process fabrication quote |
| `costing/` | `kerf_cad_core/costing/` | Per-process cost estimation |
| `cam_wizard/stock_setup.py` | `kerf_cad_core/cam_wizard/` | Stock selection + fixture suggestion |
| `cncfeeds/` | `kerf_cad_core/cncfeeds/` | Feed/speed recommendations |
| `gcode/` | `kerf_cad_core/gcode/` | G-code generation utilities |
| `geom/history/` | `kerf_cad_core/geom/history/` | Parametric feature DAG + persistent naming |
| `drawings/` | `kerf_cad_core/drawings/` | Orthographic projection + hidden line |
| `procsim/` | `kerf_cad_core/procsim/` | Process simulation (timing, cycle time) |

---

See also: [parametric.md](./parametric.md) · [drawings.md](./drawings.md) · [llm-tools.md](./llm-tools.md) · [capabilities.md](./capabilities.md)
