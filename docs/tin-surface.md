# TIN Surface (Triangulated Irregular Network)

*Domain: Civil · Module: `packages/kerf-civil/src/kerf_civil/tin.py` · Shipped: Wave 10*

## Overview

Builds a Triangulated Irregular Network (TIN) from scattered survey points using Delaunay triangulation, then provides contour generation, slope and aspect analysis, 2-D area and volume-above-datum calculation, and LandXML export. Used as the terrain model backbone for corridor design, cut/fill earthwork, and landscape grading.

## When to use

- Generating terrain contours from LiDAR or survey point data.
- Computing cut/fill volumes between an existing and proposed grade.
- Checking slope percentages across a site for drainage or accessibility analysis.

## API

```python
from kerf_civil.tin import (
    TIN, build_tin,
    contours, slope, aspect,
    area_2d, volume_above,
)

import numpy as np
xy = np.array([[0,0],[10,0],[5,8],[0,10],[10,10]])
z  = np.array([100.0, 101.5, 103.0, 100.5, 102.0])

tin: TIN = build_tin(xy, z)

# Generate contours at 0.5m interval
c_lines = contours(tin, levels=[100.5, 101.0, 101.5, 102.0, 102.5])

# Slope for triangle 0 (decimal fraction, not percent)
s = slope(tin, triangle_index=0)

# Volume above 100.0m datum
vol = volume_above(tin, datum_z=100.0)
```

## LLM tools

`civil_terrain_build`, `civil_earthwork_volume`

## References

- Tsai, "Delaunay triangulations in TIN creation: an overview and a linear-time algorithm", *IJGIS* 7(6), 1993.
- ASCE 2413-17, *Standard Practice for the Design and Review of Civil Engineering Projects* (earthwork volume).

## Honest caveats

The Delaunay triangulation uses `scipy.spatial.Delaunay` when available; otherwise it falls back to a pure-Python incremental insertion which is O(n²). Breakline constraints (feature lines that must align with triangle edges) are not currently supported. Volume-above-datum uses the prismatoid formula per triangle and ignores points below datum.
