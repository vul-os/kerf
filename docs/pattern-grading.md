# Pattern Grading (Apparel)

*Domain: Apparel · Module: `packages/kerf-apparel/src/kerf_apparel/grading.py` · Shipped: Wave 10*

## Overview

Grades a base-size pattern block to a full size run (XS–3XL, or numeric EU/US sizing) using incremental nest rules for bodice, sleeve, and trouser pieces. Applies standard Müller & Sohn or AAMA/ASTM grade rule tables to each pattern piece, redistributing ease and shaping along cardinal axes. Outputs a `GradedSet` containing all size variations for marker making.

## When to use

- Generating a complete size run from a single base-size pattern.
- Checking grade spread against industry standard increments before cutting.
- Preparing graded nests for an automatic marker-making run.

## API

```python
from kerf_apparel.grading import (
    GradedSet, grade_bodice, grade_sleeve, grade_pants,
)

# Grade a front bodice block from size 10 across XS–3XL
graded: GradedSet = grade_bodice(
    base_piece=front_bodice_piece,
    base_size="10",
    size_run=["6","8","10","12","14","16","18"],
    grade_table="muller_sohn",
)

for size, piece in graded.sizes.items():
    print(f"Size {size}: {len(piece.boundary)} boundary points")
```

## LLM tools

`apparel_grade_bodice`

## References

- Müller & Sohn, *Rundschau* grade rule tables (womenswear standard).
- AAMA/ASTM D5585, *Standard Tables of Body Measurements for Adult Female Misses Figure Type*.

## Honest caveats

Grade rules are applied at discrete grade break points on the pattern boundary. Smooth redistribution between break points uses linear interpolation — complex curved seams may require manual adjustment of intermediate grade points. Menswear, childrenswear, and maternity grade rules are not included in the current table set.
