# Dental Lab Workflow

> Package a complete dental case for milling, 3D printing, or lab dispatch with one tool call.

**Module**: `packages/kerf-dental/src/kerf_dental/lab_workflow.py`
**Shipped**: Wave 10
**LLM tools**: `dental_lab_case_report`

---

## What it is

The dental lab workflow module aggregates crown, bridge, denture, and surgical guide meshes into a structured case export. It produces a milling export (multi-body STL package with per-restoration material flags), an articulator setup (upper/lower arches with bite registration offsets), and a case status report listing all restorations, their design status, and estimated milling time.

## How to use it

### From chat

> "Generate the milling export for case C-1042: upper molar crown in zirconia and lower premolar PFM."

### From Python

```python
from kerf_dental.lab_workflow import (
    DentalCase, create_milling_export, export_articulator_setup,
    case_status_report,
)

case = DentalCase(
    case_id="C-1042",
    patient_id_hashed="a3f9...",
    restorations=[
        {"tooth": "16", "type": "crown", "material": "zirconia"},
        {"tooth": "45", "type": "crown", "material": "pfm"},
    ],
    meshes={"16": crown_mesh_16, "45": crown_mesh_45},
)

export = create_milling_export(case, output_dir="/tmp/case_C1042")
print(export.files)   # list of STL paths per restoration

report = case_status_report([case])
print(report["total_restorations"], report["ready_for_mill"])
```

### From an LLM tool spec

```json
{"tool": "dental_lab_case_report", "input": {"case_id": "C-1042", "patient_id_hashed": "a3f9", "dentist_name": "Dr Smith", "lab_name": "Precision Dental Lab"}}
```

## How it works

`create_milling_export` serialises each restoration mesh to binary STL and records the material string in a sidecar JSON manifest. `export_articulator_setup` calculates the inter-occlusal distance and writes upper and lower arch STLs with a transform matrix that reproduces the bite registration offset. The status report aggregates per-restoration design completion flags set by upstream design steps.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `create_milling_export(case, output_dir)` | `CaseExport` | Per-restoration STLs + manifest |
| `export_articulator_setup(case, output_dir)` | `dict` | Upper/lower arch STLs with bite offset |
| `case_status_report(cases)` | `dict` | Completion summary across case list |

## Example

```python
export = create_milling_export(case, output_dir="/tmp/out")
# CaseExport(files=['16_zirconia.stl', '45_pfm.stl'],
#            manifest_path='manifest.json', total_restorations=2)
```

## Honest caveats

The milling export does not validate margin fit or occlusal contact — that check is the responsibility of the upstream crown design step. Milling time estimates are based on material hardness and block size heuristics, not actual CAM path simulation. Cases with implant superstructures require the implant plan to be completed first.

## References

- ISO 6872:2015, *Dentistry — Ceramic materials*.
- Giordano & McLaren, "Ceramics overview," *Compendium* 31(9), 2010.
