# IFC Import — `import_ifc` tool

Imports an Industry Foundation Classes (`.ifc`) file into a Kerf project,
producing a `.bim` architecture file.  The reverse of `compile_bim_to_ifc`.

## LLM tool

```
import_ifc(project_id, file_blob_id, import_folder?, mode?)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_id` | string | required | UUID of the target Kerf project |
| `file_blob_id` | string | required | Blob / storage key of the uploaded `.ifc` file |
| `import_folder` | string | `/ifc_import` | Project-tree path for the created `.bim` file |
| `mode` | `"project"` \| `"library"` | `"project"` | Import destination |

Returns `{ created_file, stats, warnings, import_folder }`.

`created_file` is `{ file_id, name, kind: "bim" }`.

`stats` is `{ sites, levels, walls, slabs, spaces }` — count of translated entities.

## Tier 1 coverage (shipped)

| IFC entity | .bim output |
|------------|-------------|
| `IfcSite` | `site` block (name, lat/lon decimal degrees, elevation mm) |
| `IfcBuildingStorey` | `levels[]` entry (name, elevation mm) |
| `IfcWall` / `IfcWallStandardCase` | `walls[]` entry |
| `IfcSlab` (FLOOR, ROOF, BASESLAB, LANDING) | `slabs[]` entry |
| `IfcSpace` | `spaces[]` entry |

Only the first `IfcSite` is translated; multi-site projects emit a warning.

## Tier 2 (not yet supported — future PR)

- `IfcWindow`, `IfcDoor` → openings  
- `IfcCurtainWall` → curtain wall system  
- `IfcColumn`, `IfcBeam` → structural framing  
- `IfcRailing`, `IfcStairFlight` → railings / stairs  
- `IfcFlowTerminal`, `IfcFlowSegment` → MEP  
- Type definitions, property sets, families  
- Schedules, views, sheets  

Tier-2 entities encountered during import are counted and listed in
`warnings` under the key `"Tier-2 entity types skipped"`.

## .bim JSON shape produced

```json
{
  "version": 1,
  "name": "Imported Project",
  "site": {
    "name": "Main Site",
    "latitude": -33.918,
    "longitude": 18.423,
    "elevation": 0.0
  },
  "levels": [
    { "name": "L1", "elevation": 0.0 },
    { "name": "L2", "elevation": 3000.0 }
  ],
  "walls": [
    {
      "level": "L1",
      "from": [0.0, 0.0],
      "to": [5000.0, 0.0],
      "height": 3000.0,
      "thickness": 200.0
    }
  ],
  "slabs": [
    {
      "level": "L1",
      "boundary": [[0,0],[5000,0],[5000,4000],[0,4000]],
      "thickness": 200.0
    }
  ],
  "spaces": [
    {
      "level": "L1",
      "boundary": [[200,200],[4800,200],[4800,3800],[200,3800]],
      "name": "Living Room"
    }
  ],
  "openings": []
}
```

All distances in **millimetres**.

## IfcLocalPlacement chain

IFC placements are hierarchical — each `IfcLocalPlacement` has a
`PlacementRelTo` pointer to a parent placement.  The importer uses
`ifcopenshell.util.placement.get_local_placement()` which traverses the
full parent chain and returns the absolute 4×4 world matrix.  This is
necessary to obtain correct world-space coordinates for walls whose
parent storey or building has a non-zero placement.

## Geometry extraction strategy

### Walls
Preferred: `IfcExtrudedAreaSolid` with `IfcRectangleProfileDef` — reads
`XDim` (length), `YDim` (thickness), `Depth` (height), and
`Position.RefDirection` (orientation).

Fallback: placement origin + default dimensions (height=3000, thickness=200,
length=1000) with a warning.

### Slabs
Preferred: `IfcExtrudedAreaSolid` with `IfcArbitraryClosedProfileDef` — reads
polyline boundary and `Depth` (thickness).

Secondary: `IfcRectangleProfileDef` — reconstructs rectangular boundary.

Fallback: 1000×1000 square at placement origin.

### Spaces
Preferred: `FootPrint` representation identifier with polyline items.

Secondary: `Body` representation with extruded closed profile.

Fallback: 1000×1000 square at placement origin.

## Dependencies

IfcOpenShell (LGPL) is required on the pyworker sidecar:

```
pip install ifcopenshell
```

If absent, `POST /import-ifc` returns HTTP 503 with a descriptive message.
The plugin route catches `IFCOpenShellNotInstalled` and surfaces it cleanly
to the caller.

## Known schema gaps (Tier 2 design notes)

| IFC concept | .bim gap | Notes |
|-------------|----------|-------|
| `IfcWindow` / `IfcDoor` hosted in wall | `openings[]` has `wall` reference by name, not GlobalId | Tier 1 openings use wall index; IFC links by `IfcRelVoidsElement` — need wall GlobalId→index mapping |
| Slab `PredefinedType` (ROOF vs FLOOR) | Not preserved in .bim | Add `type` field to slab in future schema version |
| Space `PredefinedType` (INTERNAL vs EXTERNAL) | Not preserved | Add `type` field to space |
| `IfcPropertySet` / `IfcQuantitySet` | No equivalent in .bim | Would need a generic `properties` dict per element |
| Multi-site projects | Only first site translated | .bim is single-site by design |
| `IfcMaterial` / layer sets | Not captured | Add `material` to wall/slab for Tier 2 |
