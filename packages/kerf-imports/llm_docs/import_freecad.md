# import_freecad_project

*Module: `kerf_imports.tools.import_freecad` · Domain: imports*

## Description

Import a FreeCAD .FCStd file into a new (or existing) Kerf project. Creates one .feature file per PartDesign::Body, one .sketch per Sketcher::SketchObject, an .assembly if there is more than one body, and lifts the cached BRep blobs from the archive losslessly. Tier 2 additions: Spreadsheet::Sheet → .equations (named cell parameters), TechDraw::DrawPage → .drawing (projected views), and App::MaterialObject → .material (density, modulus, color, etc.). Tier 3 additions: PartDesign::Plane/Line/Point datums → datum_attachment metadata on sketch planes; Draft Workbench objects → .sketch files (Draft::Wire, Rectangle, Circle, Polygon, Ellipse, BSpline) and .feature files (Draft::Array, Clone, Mirror). Unsupported Draft types warn-and-skip. The imported feature-tree metadata is read-only — geometry is the lifted BRep, not a recompute. Returns the list of created files and translation warnings.

## Input schema

```json
{
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
      "description": "Path inside the project tree where imported files will be placed. Defaults to /freecad_import."
    },
    "mode": {
      "type": "string",
      "enum": [
        "project",
        "library"
      ],
      "description": "Import mode: 'project' (default) creates files inside the project, 'library' imports as Library Parts."
    }
  },
  "required": [
    "project_id",
    "file_blob_id_or_storage_key"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="import_freecad_project",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_imports`
