# Pattern Grading (Apparel)

> Grade a base-size pattern block to a full size run (XS–3XL or EU/US) using Müller & Sohn or AAMA/ASTM rule tables.

**Module**: `packages/kerf-apparel/src/kerf_apparel/grading.py`
**Shipped**: Wave 10
**LLM tools**: `apparel_grade_bodice`, `apparel_apply_grading`, `apparel_grade_check`

---

## What it is

Pattern grading generates a complete size run from a single base-size pattern block, applying incremental grade rules for bodice, sleeve, and trouser pieces. Grade rules redistribute ease and shaping along cardinal axes at predefined grade points. The output is a `GradedSet` containing all size variations for marker making.

## How to use it

### From chat

> "Grade my front bodice block (base size 10) through sizes 6–18 using Müller & Sohn womenswear rules."

### From Python

```python
from kerf_apparel.grading import GradedSet, grade_bodice, grade_sleeve, grade_pants

graded: GradedSet = grade_bodice(
    base_piece=front_bodice_piece,
    base_size="10",
    size_run=["6","8","10","12","14","16","18"],
    grade_table="muller_sohn",
)

for size, piece in graded.sizes.items():
    print(f"Size {size}: {len(piece.boundary)} boundary points")
```

### From an LLM tool spec

```json
{"tool": "apparel_grade_bodice", "input": {"base_size": "10", "size_run": ["8","10","12","14"], "grade_table": "muller_sohn"}}
```

## How it works

Each grade rule table maps (garment_type, pattern_piece, size_break) → (Δx, Δy) shift vectors at a set of predefined grade points on the pattern boundary. The grade is applied cumulatively from the base size up and down the size run. Between grade points, linear interpolation redistributes the shift along the boundary curve. `grade_check_iso_8559` validates the graded measurements against ISO 8559 body measurement tables.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `grade_bodice(base_piece, base_size, size_run, grade_table)` | `GradedSet` | Graded bodice pieces |
| `grade_sleeve(base_piece, base_size, size_run, grade_table)` | `GradedSet` | Graded sleeve pieces |
| `grade_pants(base_piece, base_size, size_run, grade_table)` | `GradedSet` | Graded trouser pieces |
| `grade_check_iso_8559(measurements)` | `list[GradingWarning]` | ISO 8559 compliance warnings |

## Example

```python
graded = grade_bodice(piece, "10", ["8","10","12","14"], "muller_sohn")
# GradedSet with 4 size variants, each a PatternPiece with updated boundary points
```

## Honest caveats

Grade rules are applied at discrete grade break points; complex curved seams between break points use linear interpolation, which may require manual adjustment. Menswear, childrenswear, and maternity grade rules are not included. The ISO 8559 check validates body measurement proportions but does not guarantee fashion-correct ease or silhouette.

## References

- Müller & Sohn, *Rundschau* grade rule tables (womenswear standard).
- AAMA/ASTM D5585, *Standard Tables of Body Measurements for Adult Female Misses Figure Type*.
- ISO 8559-1:2017, *Garment construction and anthropometric surveys — Body dimensions*.
