# Importing from external CAD tools

Kerf supports import from popular CAD/EDA tools. The goal is a working starting point — not a lossless round-trip. Iterate from there via chat, script, or direct edit.

All imports produce native Kerf file types. Large binary assets (STEP, STL, meshes) use the `.step-ref` pointer system to avoid bloating git history.

## Import patterns

Every format supports three import paths:

- **UI:** Drag the file onto the file tree, or click "+ New" → "Import…"
- **LLM tool:** Ask the assistant to import — it calls `kerf-sdk` under the hood
- **REST:** `POST /import-<format>` via `kerf-pyworker` (cloud or local)

Large files are processed asynchronously. Check the job status at `GET /import-jobs/<id>`.

## OpenSCAD

**Status: shipped**

Browser-side parser at `src/lib/openscadToJscad.js` with 18 vitest tests. Drag-drop `.scad` onto the file tree → creates `.jscad`.

**How to import:**
- Drag a `.scad` file onto the file tree
- Or click "+ New" → "Import OpenSCAD…" and select a file

**What translates:**
- Primitives: `cube`, `sphere`, `cylinder`, `polyhedron`
- Transforms: `translate`, `rotate`, `scale`
- Booleans: `union`, `difference`, `intersection`
- Variables, `module` and `function` definitions, `for` loops

**What doesn't translate:**
- `surface()` — height-map meshes
- `include<>` / `use<>` — external file references
- `import()` of STL/DXF
- Advanced: `hull()`, `minkowski()`, `offset()`, `projection()`
- Customizer hints (`// [min:max:step]`)

**Escape hatch:** Render to STL in OpenSCAD, then import as `.step` (lossy — no parametric model).

## KiCad

**Status: shipped (Tier 1), in-flight (Tier 2)**

pyworker `/import-kicad` parses `.kicad_sch` / `.kicad_pcb` → `.circuit.tsx`.

**How to import:**
- Drag a `.kicad_sch`, `.kicad_pcb`, or zipped KiCad project onto the file tree
- Or ask the LLM: "import my KiCad project"

**Tier 1 — shipped:**
- Schematic components → tscircuit primitives (`<resistor>`, `<capacitor>`, `<chip>`)
- Net connections → `<trace>` elements
- ~100 common footprints via translation table
- Schematic and PCB x/y placement

**Tier 2 — in-flight:**
- Symbol and footprint library lookup
- 3D models via `step-ref` pointers

**Tier 3 — out of scope for this sprint:**
- Lossless round-trip or export back to KiCad
- Full layout fidelity (differential pairs, layer stack-ups, custom design rules)
- ERC/DRC rule preservation

**Requires:** cloud pyworker service. Local-install users run `kerf-pyworker` themselves.

## Rhino .3dm

**Status: shipped**

`pyworker/routes/rhino3dm.py` + `backend/tools/import_3dm.py`. POST `/import-3dm`. Per ROADMAP: single biggest adoption unlock.

**How to import:**
- Drag a `.3dm` file onto the file tree
- Or ask the LLM: "import this Rhino file"

**What translates:**
- NURBS surfaces and polysurfaces → Kerf BREP geometry
- Curves and annotations
- Layer hierarchy
- Block definitions

**What doesn't translate:**
- Render meshes (convert to BREP in Rhino first)
- Some advanced Rhino-specific features

## STEP files

**Status: shipped**

Large STEPs (≥5MB) become `.step-ref` pointers with content-addressed object storage (migration 033). Smaller STEPs inline.

**How to import:**
- Drag a `.step` or `.stp` file onto the file tree
- Or ask the LLM: "import this STEP file"

**What translates:**
- BREP geometry (surfaces, solids)
- Assembly hierarchy (top-down)

**What doesn't translate:**
- Parametric features — STEP is a neutral format, no history

## DXF

**Status: planned (output), not started (input)**

Output via FreeCAD Draft workbench's `export_draft_dxf`. Input not yet implemented.

**Workaround:** Open in FreeCAD, explode to geometry, export as SVG or DXF, then import.

## IGES / FBX / OBJ

**Status: planned, not started**

Track progress in [ROADMAP](../ROADMAP.md).

## FreeCAD

**Status: explicitly excluded from this sprint**

Future work. Watch the roadmap for updates.

## General tips

- After any import, open the file and use the chat assistant to refine — the LLM can fix translation artifacts conversationally.
- For files that don't import cleanly, importing the rendered STEP/STL as a mesh is always an option — you lose the parametric model but keep the geometry.
- Large binary assets are stored via `.step-ref` pointers; they don't bloat git history.
