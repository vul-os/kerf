# Road Horizontal and Vertical Alignment

*Domain: Civil · Module: `packages/kerf-civil/src/kerf_civil/horizontal_alignment.py` · Shipped: Wave 10*

## Overview

Parametric road alignment design using tangent-spiral-curve geometry (clothoid/Euler spiral transitions + circular arcs for horizontal alignment) and parabolic vertical curves for vertical alignment. Computes station-offset geometry, superelevation transitions, sight distances, and generates a corridor solid at specified cross-section templates. Exports LandXML and DXF plan-profile sheets.

## When to use

- Designing a new road alignment between two endpoints with curvature constraints.
- Generating cross-sections and earthwork volumes for a corridor.
- Producing a plan-profile sheet for road design documentation.

## API

```python
from kerf_civil.horizontal_alignment import (
    HorizontalAlignment, TangentElement,
    CircularCurve, ClothoidSpiral,
    compute_alignment_geometry,
)
from kerf_civil.vertical_alignment import (
    VerticalAlignment, ParabolicCurve,
)

ha = HorizontalAlignment(elements=[
    TangentElement(bearing_deg=45.0, length_m=200.0),
    ClothoidSpiral(A=60, R=120, direction="right"),
    CircularCurve(R=120, delta_deg=30.0, direction="right"),
    ClothoidSpiral(A=60, R=120, direction="right"),
    TangentElement(bearing_deg=75.0, length_m=150.0),
])

pts = compute_alignment_geometry(ha, station_interval_m=10.0)
```

## LLM tools

`civil_horizontal_alignment`, `civil_vertical_alignment`, `civil_corridor_sections`

## References

- AASHTO, *A Policy on Geometric Design of Highways and Streets* (Green Book), 2018.
- SANS 731 (South Africa), *Road Design Standards*.

## Honest caveats

Clothoid transition curves are computed using the Fresnel integral approximation (series expansion to 7 terms). For very short or very long clothoids the approximation error increases; for A < 20 or A/R > 2 verify with exact Fresnel values. Superelevation transition design uses the AASHTO method; local authority variations may differ.
