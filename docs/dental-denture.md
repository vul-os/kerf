# Denture and RPD Design

*Domain: Dental · Module: `packages/kerf-dental/src/kerf_dental/denture.py` · Shipped: Wave 10*

## Overview

Generates complete and partial denture geometries: full-arch acrylic denture bases, removable partial denture (RPD) frameworks with clasps and connectors, and impression tray designs. Takes an arch scan and tooth-placement prescription and returns a printable or millable denture body. Exports STL for 3D printing or open-format CAM.

## When to use

- Designing a full denture from a maxillary or mandibular edentulous scan.
- Laying out an RPD framework with specified clasp positions and major/minor connectors.
- Generating a stock or custom impression tray from an arch scan.

## API

```python
from kerf_dental.denture import (
    DentureDesign, design_full_denture,
    RPDFramework, design_rpd_framework,
)

denture = design_full_denture(
    arch="maxillary",
    ridge_scan_mesh=scan_mesh,
    tooth_arrangement="anatomic_18",
    flange_extension_mm=2.0,
    base_material="acrylic_pmma",
)

rpd = design_rpd_framework(
    arch="mandibular",
    missing_teeth=[18, 19, 20],  # FDI notation
    clasp_teeth=[17, 21],
    major_connector="lingual_bar",
)
```

## LLM tools

`dental_denture_design`

## References

- Zarb et al., *Prosthodontic Treatment for Edentulous Patients*, 13th ed. (2012).
- ISO 22112:2017, *Dentistry — Artificial teeth for dental prostheses*.

## Honest caveats

Tooth arrangement follows a standard anatomic library; custom tooth morphologies require importing individual tooth STLs. RPD clasp geometry is simplified to circumferential cast clasps — Akers, RPI, and ring clasps are supported but bar clasps are not. Occlusal adjustment and bite registration are clinical steps that cannot be automated.
