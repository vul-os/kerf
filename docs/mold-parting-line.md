# Mold Parting Line and Cavity/Core Split

*Domain: Manufacturing · Module: `packages/kerf-mold/src/kerf_mold/mold.py` · Shipped: Wave 10*

## Overview

Performs injection-mould design analysis: per-face draft angle measurement, automatic parting-line generation along the maximum-draft-change silhouette, moldability checking (undercut detection, minimum draft), and parting-surface generation for the cavity/core split. Generates a `MoldDesign` data structure with gate locations, ejector pin positions, and parting-surface geometry.

## When to use

- Checking a part for undercuts and minimum draft angles before mould design.
- Automatically generating a parting line and parting surface for a new mould.
- Placing ejector pins and gating in a `MoldDesign` for tool path planning.

## API

```python
from kerf_mold.mold import (
    MoldDesign, PartingLine,
    draft_angle_per_face,
    generate_parting_surface,
    check_moldability,
)

# Check for undercuts and draft
report = check_moldability(
    faces=face_list,
    pull_direction=[0, 0, 1],
    min_draft_deg=1.5,
)
print(report["undercuts"])       # list of face indices with undercuts
print(report["faces_below_draft"])

# Generate parting line
parting = generate_parting_surface(
    faces=face_list,
    pull_direction=[0, 0, 1],
)
```

## LLM tools

`mold_check_moldability`, `mold_generate_parting_surface`, `mold_draft_angle_per_face`

## References

- Rosato & Rosato, *Injection Molding Handbook*, 3rd ed.
- Warburton & Shercliff, "Parting surface generation for plastic injection moulds", *Int. J. Adv. Manuf. Technol.* 17, 2001.

## Honest caveats

Parting-line generation uses a silhouette-edge walk in the projection direction. Highly non-convex parts or parts with internal undercuts may produce incomplete or invalid parting surfaces — check the returned geometry for gaps. Core pulls and lifters for undercuts are not automatically generated; they must be added manually after the initial parting-surface check.
