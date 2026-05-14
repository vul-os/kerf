# FreeCAD Tier 1 import (design doc)

**Status:** planned · breakout from the ROADMAP "Import: FreeCAD" row.
**Owner:** TBD (sonnet agents per task).
**ROADMAP row:** see `📋 Import: FreeCAD` plus the `📋 next` sub-rows below it.

## Why

FreeCAD users are Kerf's most natural audience — open-source-friendly,
parametric-CAD-trained, often Python-comfortable. They've self-selected
against proprietary CAD; they're already comfortable with command-line and
script-driven workflows. They are also the largest single segment of
mechanical-CAD users we can pull in.

The kernel alignment is the strategic gift: both FreeCAD and Kerf evaluate
on OpenCascade. The `.FCStd` archive ships the evaluated TopoDS BRep
alongside the feature tree. We can lift the BRep losslessly into a Kerf
`.feature` file *without re-executing the recompute graph*. That makes a
useful import shippable in days, not months.

This document specifies **Tier 1**: the smallest useful import. Tier 2/3
defer the harder parts (full Sketcher constraint translation, Spreadsheet
→ `.equations`, TechDraw, Python-macro migration) — listed in
[Deferred to Tier 2 / 3](#deferred-to-tier-2--3) so the slice is honest.

## Capability scope after Tier 1 ships

After Tier 1 a user can:

1. Upload a `.FCStd` (single or multi-Body Part document).
2. Get a Kerf project with one `.feature` file per Body, one `.sketch` file
   per backing Sketch, and an `.assembly` if the source had multiple Bodies.
3. Each `.feature` file contains:
   - A first node `import_brep` that lifts the evaluated solid losslessly
     (content-hashed STEP-equivalent BRep stored as a blob).
   - Read-only metadata nodes describing the FreeCAD feature tree
     (Pad/Pocket/Fillet/etc.) — captured for documentation + future Tier 2
     re-evaluation, **not** executed by the OCCT worker.
   - The geometry the user sees is the imported BRep, not a re-evaluation.
4. Each `.sketch` file contains the FreeCAD sketch's entities (points,
   lines, arcs, circles) and the constraints we can translate cleanly
   (see [Sketch constraint mapping](#sketch-constraint-mapping)).
   Untranslatable constraints become `// imported_from_freecad: <name>`
   comments and the affected entities are marked `construction: true`.
5. Downstream edits (adding a fillet, drilling a hole, dropping the body
   into an assembly) work normally on top of the imported solid.

**Out of Tier 1**: re-executing the FreeCAD feature tree (Tier 2), full
Sketcher constraint round-trip (Tier 2), Spreadsheets → `.equations`
(Tier 2), TechDraw → `.drawing` (Tier 2), Python macros (Tier 3).

## `.FCStd` file format reference

`.FCStd` is a **zip archive**. Verified against the FreeCAD source tree
([`src/App/Document.cpp`](https://github.com/FreeCAD/FreeCAD/blob/main/src/App/Document.cpp))
and several real-world saves. Contents:

| Path inside zip                  | Contents                                                                 |
|----------------------------------|--------------------------------------------------------------------------|
| `Document.xml`                   | The DocumentObject graph — every feature, its type, its property table, references to other features by name. The canonical feature tree. |
| `GuiDocument.xml`                | View-state: visibility, colours, transparency, active body. Not needed for Tier 1. |
| `PartShape*.brp`                 | One file per Part feature carrying an evaluated BRep blob (OpenCascade ASCII BRep format — `BRepTools::Write`/`Read` round-trips it). Filename is referenced from `Document.xml` via the `FileIncluded` property. |
| `Sketch*.brp`                    | Some Sketcher features cache their last-evaluated wire here. Mostly redundant — the Sketcher constraint table in `Document.xml` is the source of truth. |
| `thumbnails/Thumbnail.png`       | Project preview. Stash on the project record for the Workshop card. |
| `*.diff`                         | Sketch / spreadsheet undo history. Ignored in Tier 1. |

`Document.xml` shape (abbreviated, real-world `.FCStd` from FreeCAD 0.21):

```xml
<Document SchemaVersion="4" ProgramVersion="0.21R3">
  <Objects Count="3">
    <Object type="PartDesign::Body"      name="Body"/>
    <Object type="Sketcher::SketchObject" name="Sketch"/>
    <Object type="PartDesign::Pad"       name="Pad"/>
  </Objects>
  <ObjectData Count="3">
    <Object name="Sketch">
      <Properties Count="N">
        <Property name="Geometry">
          <GeometryList count="4">
            <Geometry type="Part::GeomLineSegment">
              <Start x="0"  y="0"  z="0"/>
              <End   x="10" y="0"  z="0"/>
            </Geometry>
            …
          </GeometryList>
        </Property>
        <Property name="Constraints">
          <ConstraintList count="6">
            <Constrain Name="Horizontal" Type="6" First="0" FirstPos="0"/>
            <Constrain Name="DistanceX"  Type="8" First="0" FirstPos="1"
                       SecondPos="2" Value="10"/>
            …
          </ConstraintList>
        </Property>
      </Properties>
    </Object>
    <Object name="Pad">
      <Properties Count="M">
        <Property name="Profile"><Link value="Sketch"/></Property>
        <Property name="Length"><Float value="10"/></Property>
        <Property name="Shape"><FileIncluded file="PartShape1.brp"/></Property>
        …
      </Properties>
    </Object>
  </ObjectData>
</Document>
```

Key observations:

- **Feature graph by name.** `<Link value="Sketch"/>` is a name-based
  reference. Cross-document refs (`<<Body>>.Sketch.Constraints.foo`) appear
  in spreadsheet contexts (Tier 2).
- **BRep blobs are referenced, not inlined.** The `FileIncluded` element
  names a sibling file in the zip. That's our Tier 1 input.
- **Constraint enum is numeric.** `Type="6"` = Horizontal, `Type="8"` =
  DistanceX, etc. The numeric enum is defined in
  [`src/Mod/Sketcher/App/Constraint.h`](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Sketcher/App/Constraint.h)
  — a fixed list of ~20 values. We hand-curate the mapping table; no
  introspection needed.

## Parser choice: pure-Python, no FreeCAD install

Two viable parsers:

| Approach | Pros | Cons |
|---|---|---|
| **FreeCAD Python module** (`import FreeCAD`) | Authoritative — same code FreeCAD uses to load. Handles every quirk. | Heavy install (~200MB), requires FreeCAD's Qt + Coin3D deps on the worker, blocks our single-binary OSS install story, FreeCAD versions drift the API. |
| **Pure-Python**: `zipfile` + `xml.etree` + `pythonOCC.BRepTools.Read` for the BRep blobs | No FreeCAD install. Self-contained. Tracks the format directly, not the Python API. | We own the format-drift risk (mitigate by pinning a FreeCAD version range + adding regression fixtures). Some exotic features (Python-scripted ones) won't parse. |

**We pick pure-Python.** Reasons:

1. **OSS local-install story.** A FreeCAD dependency forces us to ship or
   require FreeCAD alongside Kerf — kills the single-binary brew/curl
   install pitch for users who never wanted FreeCAD.
2. **Cloud-tier image bloat.** `kerf-imports` would balloon by ~200MB. The
   plugin currently advertises `imports.freecad` gated on `pythonOCC`
   alone; staying on pythonOCC keeps the gate honest.
3. **Format stability.** `Document.xml` schema bumps maybe once per
   FreeCAD major. The Python API churns more.
4. **Tier 1 doesn't need recompute.** We're lifting the cached BRep, not
   re-running features. The Python API's main value (calling
   `Pad.execute()`) is exactly what we *don't* want in Tier 1.

The pythonOCC `BRepTools_Read` / `BRep_Builder` pair reads the BRep blobs
directly. `kerf-imports` already advertises `imports.freecad` gated on
pythonOCC availability — no new dependency.

**Tier 2 reconsideration.** If we later want to re-execute the FreeCAD
recompute graph for live parametric edits, we revisit the FreeCAD Python
module then (or write our own recompute engine). Tier 1 doesn't force the
call.

## BRep-lift vs re-eval (honest tradeoff)

| Aspect | Tier 1: BRep-lift | Tier 2: re-eval |
|---|---|---|
| Geometry fidelity | **Lossless** — same BRep FreeCAD evaluated. | Same kernel, but recompute may differ on edge cases. |
| Implementation cost | Days (parse XML + load BRep). | Weeks-to-months (port FreeCAD's recompute order + per-feature handlers). |
| Edits to imported features | Read-only metadata. User edits *downstream* of the import freely. | Full parametric: tweak the Pad's height and the body re-evaluates. |
| Sketch edits | Edit the `.sketch` file but the imported body does not reflow — sketches are import-time snapshots. | Sketch edits flow through. |
| When the user knows? | Surfaced explicitly: each imported feature node carries `read_only: true` + a `freecad_ref: { type, name }` field and the FeatureView marks it. | N/A in Tier 1. |

The honest framing for users: **"Tier 1 gives you the part. To re-edit the
original FreeCAD features, drop down to Kerf-native equivalents on top of
the imported body."** The LLM is well-placed to do this conversion in chat
("delete the imported Pad and rebuild as a Kerf pad with height = …").

## Per-FreeCAD-construct mapping

### PartDesign features → `.feature` nodes

| FreeCAD type             | Kerf `.feature` op           | Tier 1 behaviour                                                  |
|--------------------------|------------------------------|-------------------------------------------------------------------|
| `PartDesign::Body`       | One `.feature` file          | One file per Body, named after the Body label.                    |
| `PartDesign::Pad`        | `pad` (metadata)             | Metadata node + sketch ref; geometry comes from BRep-lift.        |
| `PartDesign::Pocket`     | `pocket` (metadata)          | "                                                                 |
| `PartDesign::Revolution` | `revolve` (metadata)         | "                                                                 |
| `PartDesign::Hole`       | `hole` (metadata)            | "                                                                 |
| `PartDesign::Fillet`     | `fillet` (metadata)          | Edge refs preserved as FreeCAD edge names; flagged "rebind needed".|
| `PartDesign::Chamfer`    | `chamfer` (metadata)         | "                                                                 |
| `PartDesign::Draft`      | `feature_draft` (metadata)   | "                                                                 |
| `PartDesign::Thickness`  | `shell` (metadata)           | Face refs preserved.                                              |
| `PartDesign::LinearPattern` | `linear_pattern`          | Direction + count + spacing copied.                               |
| `PartDesign::PolarPattern`  | `polar_pattern`           | Axis + count + angle copied.                                      |
| `PartDesign::Mirrored`   | `mirror_pattern`             | Plane copied.                                                     |
| `PartDesign::MultiTransform` | `feature_multi_transform`| Sub-transforms walked.                                            |
| `PartDesign::Helix`      | `feature_helix` (metadata)   | "                                                                 |
| `PartDesign::Rib`        | `feature_rib` (metadata)     | "                                                                 |
| `PartDesign::AdditiveLoft` / `SubtractiveLoft` | `loft`     | Profile list copied; geometry from BRep-lift.                     |
| `PartDesign::AdditivePipe` / `SubtractivePipe` | `sweep1`   | Spine + profile copied; geometry from BRep-lift.                  |
| `Part::Boolean*`         | `import_brep` only           | Drop the bool tree; lift the result. Booleans are recoverable in chat. |

**The metadata-only flag.** Every imported feature node carries:

```json
{
  "id": "freecad-pad-1",
  "op": "pad",
  "sketch_path": "/Sketch.sketch",
  "height": 10,
  "direction": "up",
  "read_only": true,
  "freecad_ref": { "type": "PartDesign::Pad", "name": "Pad", "doc": "Body" }
}
```

The OCCT worker `switch (node.op)` already runs `pad` happily — but the
worker treats `read_only: true` as "skip this node, the cached BRep from
the prior `import_brep` is the body". `import_brep` is a new node op (T2).

### Sketcher → `.sketch`

See [Sketch constraint mapping](#sketch-constraint-mapping).

### Part workbench features → `.feature` with `import_brep` only

`Part::Box`, `Part::Cylinder`, `Part::Cut`, etc. — drop the feature tree,
keep the BRep lift. The Part workbench is the "loose" lineage in FreeCAD
(non-parametric body-less geometry); we don't try to preserve the tree.

### Multi-Body documents → `.assembly`

If `Document.xml` declares multiple `PartDesign::Body` objects, we create
an `.assembly` file at the project root with one Component per Body.
Each Body becomes its own `.feature` file as above. The transforms come
from the `Placement` property on each Body.

Single-body documents skip the assembly file.

### Spreadsheet → deferred to Tier 2

`Spreadsheet::Sheet` objects exist in `Document.xml` but we don't translate
them in Tier 1. Affected sketch dimensions (those that reference cells via
`<<Spreadsheet>>.A1`) are imported with their *current numeric value*, with
a comment `// freecad_ref: <<Spreadsheet>>.A1`.

### Materials / TechDraw / FEM / Path / BIM → out of Tier 1

Materials: a follow-up tool can map. TechDraw, FEM, Path, BIM: explicitly
out of scope. Show a warning per unsupported workbench.

## Sketch constraint mapping

FreeCAD's Sketcher constraint enum
([`Sketcher::ConstraintType`](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Sketcher/App/Constraint.h)):

| FreeCAD enum            | Kerf constraint type     | Notes |
|-------------------------|--------------------------|-------|
| `Coincident` (1)        | `coincident`             | Direct map. |
| `Horizontal` (2)        | `h`                      | Lines only. Point-pair horizontal maps to `distance_y = 0`. |
| `Vertical` (3)          | `v`                      | "                                                          |
| `Parallel` (4)          | `parallel`               | Direct.                                                    |
| `Tangent` (5)           | `tangent`                | Direct (line↔arc, line↔circle, arc↔arc, etc).              |
| `Distance` (6)          | `distance`               | Point-pair. Distance from a point to a line (FreeCAD `DistanceP_L`) is not directly representable — emit `point_on_line` if value ≈ 0, else drop with warning. |
| `DistanceX` (7)         | `distance_x`             | Direct.                                                    |
| `DistanceY` (8)         | `distance_y`             | Direct.                                                    |
| `Angle` (9)             | `angle`                  | Direct (line↔line). Point-line-point angle: drop with warning. |
| `Perpendicular` (10)    | `perpendicular`          | Direct.                                                    |
| `Radius` (11)           | `radius`                 | Direct.                                                    |
| `Equal` (12)            | `equal_length` / `equal_radius` | Branch on entity type at translate time.            |
| `PointOnObject` (13)    | `point_on_line` / `point_on_arc` | Branch on host type.                                |
| `Symmetric` (14)        | `symmetric`              | Direct.                                                    |
| `InternalAlignment` (15)| (drop)                   | FreeCAD-internal (ellipse/bspline internals). Mark affected entities `construction: true`. |
| `SnellsLaw` (16)        | (drop)                   | Out of Kerf vocabulary. Warn.                              |
| `Block` (17)            | `block` (+ `coordinate_x`/`coordinate_y` at solved value) | Direct. |
| `Diameter` (18)         | `diameter`               | Direct.                                                    |
| `Weight` (19)           | (drop)                   | B-spline weights — out of Kerf v1 sketch. Warn. Affected b-spline marked construction. |

### Known gaps

- **Construction-line carry-over.** FreeCAD's `construction = true` flag on
  individual geometry maps directly to Kerf's `construction: true`.
- **External geometry (linked from other sketches/bodies).** FreeCAD allows
  a sketch to reference geometry from a Body's faces/edges. Kerf's
  face-anchored sketch plane (`{ "type": "face", "file_id": ..., "face_id": ... }`)
  covers the plane reference; in-sketch references to non-plane geometry
  (e.g. "tangent to that edge of the body") are not in v1 sketch. Drop with
  warning; the user re-creates in Kerf.
- **B-spline / ellipse internal alignments.** B-splines/ellipses come over
  as construction geometry only (with a warning) — extruding them is not
  meaningful without the internal alignment.
- **Spreadsheet-driven dimensions.** Carried at numeric value, with a
  comment. Tier 2 adds `${equation_name}` rewriting.

### Failure-mode reporting

The import returns a `warnings` array: one entry per dropped/degraded
constraint, addressed to the LLM so the chat surface can talk the user
through them ("FreeCAD sketch had a Snell's-Law constraint between the
sun-ray and the lens — Kerf doesn't have that vocabulary, I've dropped it.
You can rebuild as …").

## Library Parts handling

A FreeCAD project's bodies could naturally land as **Library Parts**
(`kind='part'`) if the user picks "Import as library" rather than "Import
as project". Tier 1 ships the project import only; the library mode is a
small flag flip in T7 (the LLM tool).

Library mode differences:
- Created files land under the user's workspace Library, not a new project.
- Each Body becomes one `.part` file (which in turn references its
  `.feature` + `.sketch` siblings).
- Metadata fields (description, license) are seeded from `Document.xml`'s
  `Comment` / `License` properties when present.

## LLM tool spec: `import_freecad_project`

```python
import_freecad_project_spec = ToolSpec(
    name="import_freecad_project",
    description=(
        "Import a FreeCAD .FCStd file into a new (or existing) Kerf project. "
        "Creates one .feature file per PartDesign::Body, one .sketch per "
        "Sketcher::SketchObject, an .assembly if there is more than one body, "
        "and lifts the cached BRep blobs from the archive losslessly. "
        "The imported feature-tree metadata is read-only — geometry is the "
        "lifted BRep, not a recompute. Returns the list of created files + "
        "translation warnings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "UUID of the target Kerf project. Required for project-import mode."
            },
            "file_blob_id_or_storage_key": {
                "type": "string",
                "description": "Blob ID or storage key for the uploaded .FCStd file."
            },
            "import_folder": {
                "type": "string",
                "description": "Path inside the project. Defaults to /freecad_import."
            },
            "mode": {
                "type": "string",
                "enum": ["project", "library"],
                "default": "project"
            }
        },
        "required": ["project_id", "file_blob_id_or_storage_key"],
    },
)
```

Return shape:

```json
{
  "created_files": [
    { "file_id": "<uuid>", "name": "Body.feature", "kind": "feature", "freecad_name": "Body" },
    { "file_id": "<uuid>", "name": "Sketch.sketch", "kind": "sketch", "freecad_name": "Sketch" },
    { "file_id": "<uuid>", "name": "main.assembly", "kind": "assembly" }
  ],
  "stats": {
    "bodies": 1,
    "sketches": 1,
    "features_lifted": 3,
    "brep_blobs_lifted": 1,
    "constraints_translated": 8,
    "constraints_dropped": 1
  },
  "warnings": [
    "sketch 'Sketch': dropped Snell's-Law constraint #5 — not in Kerf vocabulary"
  ],
  "import_folder": "/freecad_import"
}
```

Pyworker route `POST /import-freecad-project` carries the heavy work
(parsing + BRep lifting via pythonOCC). The LLM tool is a thin wrapper:
fetch blob, call pyworker, walk the response, insert files in PG. Same
shape as `import_3dm` (see `packages/kerf-imports/src/kerf_imports/tools/import_3dm.py`).

The existing `POST /import-freecad` route (stub in `freecad.py`) is
**rewritten** as `/import-freecad-project` — the stub's return shape
(`{geometry_json, warnings}`) is replaced by the structured response above.

## Project layout

Default import lands files like:

```
/freecad_import/
  ├── Body.feature           # one per PartDesign::Body
  ├── Sketch.sketch          # one per Sketcher::SketchObject
  ├── Sketch001.sketch
  ├── main.assembly          # only if >1 Body
  └── _brep/                 # opaque BRep blob references (content-hashed)
      └── <sha256>.brp       # via Kerf's blob storage / content_sha256 mechanism
```

The `_brep/` directory is conceptual — actual storage is via Kerf's blob
store, content-hash addressed. The `import_brep` node references blobs by
`storage_key` or `content_sha256`. This matches the pre-tessellation /
`derived_artifacts` pattern.

## New OCCT worker node: `import_brep`

Worker handler additions in `src/lib/occtWorker.js` (frontend code change,
**not** in this design doc's scope of edits — but specified here for T2):

```js
// Tier-1 leaf op: read a BRep blob from blob storage, return TopoDS_Shape.
case 'import_brep': {
  const blob = await fetchBlob(node.content_sha256 || node.storage_key)
  const stream = new oc.std__istringstream(blob)
  const shape = new oc.TopoDS_Shape()
  const builder = new oc.BRep_Builder()
  oc.BRepTools.Read_2(shape, stream, builder)
  return shape
}
```

The `read_only: true` flag on metadata nodes is honoured by the dispatcher
— it returns the prior body unchanged.

## Tests

Fixtures (committed under `packages/kerf-imports/tests/fixtures/freecad/`):

1. `single_pad.FCStd` — one Body, one Sketch (rectangle), one Pad.
   ~5KB. Generated once via FreeCAD CLI (`freecadcmd build_fixture.py`)
   and committed; build script also committed for reproducibility.
2. `pad_and_pocket.FCStd` — single Body, Pad + Pocket + Fillet.
3. `two_bodies.FCStd` — two bodies → exercises assembly creation.
4. `sketch_constraints.FCStd` — sketch with every constraint type in the
   mapping table; exercises the constraint translator end-to-end.
5. `unsupported_constraints.FCStd` — sketch with SnellsLaw + Weight +
   InternalAlignment; tests warning-emission paths.

Test layout (pytest, in `packages/kerf-imports/tests/`):

- `test_import_freecad_parser.py` — pure-Python parser unit tests.
- `test_import_freecad_brep.py` — BRep-lift round-trips through pythonOCC.
- `test_import_freecad_sketch.py` — constraint translation table.
- `test_import_freecad_tool.py` — LLM tool wrapper (uses pyworker mock).
- `test_import_freecad_e2e.py` — end-to-end: upload single_pad.FCStd via
  test harness, assert project has the expected files + geometry hash.

## Task breakout (sized for one sonnet agent each)

Each task is ~1 sonnet-agent-day. Dependencies listed.

### T1: `.FCStd` parser plumbing

Produce a pure-Python parser that walks the zip + `Document.xml` and emits
an in-memory representation:

```python
@dataclass
class FCStdDocument:
    program_version: str  # e.g. "0.21R3"
    objects: list[FCObject]  # in declaration order

@dataclass
class FCObject:
    name: str               # e.g. "Pad"
    type_: str              # e.g. "PartDesign::Pad"
    properties: dict[str, FCValue]
```

Where `FCValue` covers the property primitives (Float, Int, Bool, String,
Link, LinkList, Placement, FileIncluded, GeometryList, ConstraintList,
…). Includes the BRep-blob byte loader (return bytes for any
`FileIncluded` property).

**Lives at** `packages/kerf-imports/src/kerf_imports/freecad/parser.py`
(new `freecad/` sub-package — the existing single-file `freecad.py` is
deleted and re-exposed via a thin shim).

**Tests:** unit tests against `single_pad.FCStd` + `sketch_constraints.FCStd`.

**Deps:** none.

### T2: BRep-lift + `import_brep` worker op

In Python: load the BRep blob via `BRepTools_Read` + verify it's a valid
TopoDS_Shape, content-hash it, return `(sha256, bytes)`.

In the worker (`src/lib/occtWorker.js`): add the `import_brep` op case.
Add the `read_only: true` skip in the main dispatcher.

The worker change is the **only frontend touch in this task** — the design
doc carves it out so the rest of the work is pure-Python.

**Tests:** vitest for the worker (BRep round-trip through `BRepTools.Read_2`
on a fixture blob); pytest for the BRep-bytes hashing helper.

**Deps:** T1 (uses the parser's `FileIncluded` byte loader).

### T3: Sketch translator (Sketcher → `.sketch`)

Translate `Geometry` + `Constraints` property lists into a Kerf `.sketch`
JSON object. Covers every row of the constraint mapping table; emits
warnings for drops.

**Lives at** `packages/kerf-imports/src/kerf_imports/freecad/sketch.py`.

**Tests:** `test_import_freecad_sketch.py` — one assertion per constraint
row + the warning-emission paths.

**Deps:** T1.

### T4: PartDesign feature-tree metadata capture

Walk the document's PartDesign features, emit `.feature` JSON with the
`import_brep` node first + the read-only metadata nodes after, with the
`freecad_ref` provenance field on each.

**Lives at** `packages/kerf-imports/src/kerf_imports/freecad/features.py`.

**Tests:** `test_import_freecad_parser.py` round-trip on `pad_and_pocket.FCStd`.

**Deps:** T1, T2 (uses the BRep-lift output to build `import_brep` node),
T3 (sketch-path references).

### T5: Multi-Body `.FCStd` → `.assembly`

Detect multi-Body documents, emit an `.assembly` with one Component per
Body. `Placement` properties translate to the 4×4 transform.

**Lives at** `packages/kerf-imports/src/kerf_imports/freecad/assembly.py`.

**Tests:** `test_import_freecad_assembly.py` against `two_bodies.FCStd`.

**Deps:** T1, T4 (assembly references each body's `.feature` file_id).

### T6: Pyworker route `POST /import-freecad-project`

Stand up the FastAPI route in `freecad.py` (rewriting the existing stub).
Accepts an `.FCStd` upload, runs T1+T3+T4+T5 in sequence, returns the
structured response.

**Deps:** T1, T3, T4, T5.

### T7: LLM tool `import_freecad_project`

`packages/kerf-imports/src/kerf_imports/tools/import_freecad.py`. Same
shape as `import_3dm.py`: fetch blob, call pyworker, walk response, insert
files in PG. Handle `mode: "library"` flag (Library mode is +1 conditional
branch on the folder-resolution step).

**Tests:** `test_import_freecad_tool.py` — mock pyworker, assert files
land in PG.

**Deps:** T6.

### T8: Integration test + fixtures

Build the five `.FCStd` fixtures via a `freecadcmd` build script
(committed under `packages/kerf-imports/tests/fixtures/freecad/build.py`
+ pre-built `.FCStd` files committed). Wire an end-to-end test that
uploads each fixture and asserts the project file tree + geometry hash.

**Deps:** T7. Can be parallelised with T7 if the test harness is mocked
against the expected response shape.

### T9 (optional): Frontend "Import FreeCAD" picker

`src/components/ImportPicker.jsx` (or wherever the existing Rhino-3dm /
KiCad imports live) — file-type pattern + drop on `.FCStd` + project-
creation flow that invokes the LLM tool. Honest framing of the read-only
metadata for the user.

**Lives at** `src/components/ImportFreecadDialog.jsx` (or extend the
existing import dialog).

**Deps:** T7. Out of plugin scope — flip to a separate ROADMAP row if it
slips. **Not** included in the Tier 1 critical path; the LLM tool alone
gives the chat-driven path.

### Dependency graph

```
T1 (parser) ──┬─→ T2 (BRep-lift) ──┐
              ├─→ T3 (sketch)    ──┼─→ T6 (route) ──→ T7 (tool) ──→ T8 (e2e)
              ├─→ T4 (features) ──┘                                  │
              └─→ T5 (assembly) ─────────────────────────────────────┘
                                                                     │
                                                                     ↓
                                                                T9 (UI, optional)
```

Total: **8 tasks** on the critical path, **9 with optional UI**. T2+T3
parallelisable once T1 lands. T4+T5 parallelisable once T2+T3 land. T6
serializes. T8+T9 parallelisable after T7.

### Estimated effort

| Tier 1 critical path | Sonnet-agent-days |
|----------------------|:---:|
| T1 parser            | 1   |
| T2 BRep-lift         | 1   |
| T3 sketch translator | 1.5 |
| T4 feature metadata  | 1   |
| T5 assembly          | 0.5 |
| T6 pyworker route    | 0.5 |
| T7 LLM tool          | 1   |
| T8 e2e + fixtures    | 1   |
| **Subtotal**         | **7.5** |
| T9 frontend UI (optional) | 1.5 |
| **With UI**          | **9** |

With T2+T3 and T4+T5 parallelised across distinct agents, **wall-clock**
is ~4-5 days from project kickoff to merged Tier 1.

## Deferred to Tier 2 / 3

Explicitly **not** in Tier 1 (recorded so a future planning pass knows
what's punted):

### Tier 2 (next slice)

- **Re-execute FreeCAD feature graph.** Allow Kerf to recompute the Pad
  when its sketch changes (instead of carrying the read-only BRep). Either
  port FreeCAD's recompute to pythonOCC handlers per feature, or shell
  out to `freecadcmd` for re-evaluation. Multi-week.
- **Spreadsheet → `.equations`.** Walk `Spreadsheet::Sheet` cells, emit
  `.equations` entries. Rewrite sketch-dimension placeholders from
  `<<Spreadsheet>>.A1` to `${a1}`. Name-mangle collisions across
  spreadsheets.
- **TechDraw → `.drawing`.** Read TechDraw pages + views; emit Kerf
  `.drawing` files with projections + dimensions + viewports. Dimension
  styles + leaders lossy in v1.
- **Materials Library bridge.** FreeCAD material card files (`.FCMat`)
  → Kerf Materials Library entries. Direct field mapping (no big work
  but no v1 demand yet).
- **Persistent edge / face names.** FreeCAD's named-edge references
  (e.g. fillet on "Edge17") survive its recompute by spatial matching.
  Kerf's TopExp-order ids are renumber-on-edit. To make imported
  feature-tree edits live (Tier 2 re-eval needs this), we need the
  Phase 4 persistent-naming layer first.

### Tier 3 (organic / strategic)

- **Python-macro migration.** `freecad_macro_assist(file)` — LLM-driven
  walk-through that explains a FreeCAD `.FCMacro` and drafts a kerf-sdk
  equivalent. Positioning, not feature-completeness. Mentioned in the
  ROADMAP body as "your Python knowledge transfers; we don't auto-port
  your macros".

### Out of scope (every tier)

- **Workbenches with no Kerf equivalent**: Surface, Mesh, Robot, Ship,
  Reverse Engineering, Points. Show "not yet supported" warning on
  import.
- **Workbenches with a Kerf equivalent users migrate to**: FEM (Kerf
  FEM), Path (Kerf CAM), BIM/Arch (Kerf Architecture project type).
  These get a "open this in Kerf's X tool" suggestion, not a translator.
- **Round-trip export back to `.FCStd`.** Imports are one-shot; we don't
  build a `.FCStd` writer. Users export via `.step` (mechanical).
- **`Part::Compound` / loose Part-workbench geometry.** Lift the BRep
  only; don't try to preserve the loose-feature tree.

## Open questions to resolve before implementation

1. **FreeCAD version pinning.** Which `.FCStd` schema versions do we
   guarantee? Proposal: pin to **SchemaVersion 4** (FreeCAD 0.19+).
   Older saves get a "please re-save in FreeCAD 0.19 or newer" warning.
2. **BRep storage**: blob-storage content-hashed (same as the
   `derived_artifacts` pattern) or inline in the file content? Proposal:
   blob-storage, referenced by `content_sha256` in the `import_brep`
   node — keeps `.feature` JSON small + dedups across imports.
3. **Fixture build hermeticity.** Building `.FCStd` fixtures requires
   FreeCAD in CI. Proposal: commit the pre-built `.FCStd` files **and**
   the build script — CI doesn't rebuild; the script is for human
   reproducibility when fixtures need updating. Same pattern as
   `Resistor_SMD.pretty/` for KiCad.
4. **Worker handling of `import_brep` + `read_only` metadata.** Confirm
   the `read_only: true` flag is the right idiom (vs a new node `op`
   namespace like `freecad_pad`). Proposal: `read_only: true` keeps the
   op vocabulary unified — the user can drop `read_only: false` once
   Tier 2 lands and the same node re-evaluates.
5. **Edge / face name preservation.** Imported fillet/chamfer nodes
   reference FreeCAD edge names (e.g. `Edge17`) but the lifted BRep
   exposes Kerf TopExp ids. For Tier 1, keep the FreeCAD names as opaque
   strings in `freecad_ref.edge_names` — they don't drive evaluation
   (the node is read-only) but they document the user's intent for
   Tier 2.
