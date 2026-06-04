# Denture and Removable Partial Denture Design

> Design a full-arch denture or RPD framework with clasps and connectors from an arch scan.

**Module**: `packages/kerf-dental/src/kerf_dental/denture.py`
**Shipped**: Wave 10
**LLM tools**: `dental_denture_design`

---

## What it is

The denture module generates complete and partial denture geometries: full-arch acrylic denture bases, removable partial denture (RPD) frameworks with clasps and connectors, and custom impression trays. It takes an arch scan mesh and a prescription (arch, tooth arrangement, clasp positions) and returns a printable or millable denture body as a closed STL mesh.

## How to use it

### From chat

> "Design a full maxillary denture with anatomic tooth arrangement and 2 mm flange extension."

### From Python

```python
from kerf_dental.denture import DentureSpec, RPDSpec, design_full_denture, design_rpd

spec = DentureSpec(
    arch="maxillary",
    tooth_arrangement="anatomic_18",
    flange_extension_mm=2.0,
    base_material="acrylic_pmma",
)
result = design_full_denture(spec, ridge_scan_mesh=scan_mesh)
# result.vertices, result.faces — printable denture body

rpd_spec = RPDSpec(
    arch="mandibular",
    missing_teeth=["18", "19", "20"],
    clasp_teeth=["17", "21"],
    major_connector="lingual_bar",
)
rpd_result = design_rpd(rpd_spec, ridge_scan_mesh=scan_mesh)
```

### From an LLM tool spec

```json
{"tool": "dental_denture_design", "input": {"arch": "maxillary", "type": "full", "tooth_arrangement": "anatomic_18", "flange_extension_mm": 2.0}}
```

## How it works

`_arch_centreline` fits a smooth arch curve to the ridge scan landmark points. `_arch_tube_mesh` sweeps a D-shaped cross-section along the centreline to produce the denture base shell. Teeth are placed at anatomically prescribed intervals along the arch centreline and Booleanunioned into the base. For RPDs, clasp arms and major connectors are swept as thin bar profiles and assembled into a framework body.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `design_full_denture(spec, ridge_scan_mesh)` | `DentureResult` | Complete denture mesh |
| `design_rpd(spec, ridge_scan_mesh)` | `RPDResult` | RPD framework mesh |
| `DentureSpec(arch, tooth_arrangement, flange_extension_mm, base_material)` | instance | Full denture prescription |
| `RPDSpec(arch, missing_teeth, clasp_teeth, major_connector)` | instance | RPD prescription |

## Example

```python
result = design_full_denture(spec, scan_mesh)
# DentureResult(vertices=..., faces=..., n_teeth=14, arch='maxillary')
```

## Honest caveats

Tooth arrangement follows a standard anatomic library; custom tooth morphologies require importing individual tooth STLs. RPD clasp geometry covers circumferential cast clasps (Akers, RPI, ring) only — bar clasps are not included. Occlusal adjustment and bite registration are clinical steps that cannot be automated by this module.

## References

- Zarb et al., *Prosthodontic Treatment for Edentulous Patients*, 13th ed. (2012).
- ISO 22112:2017, *Dentistry — Artificial teeth for dental prostheses*.
