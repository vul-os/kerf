# kerf-apparel — apparel / pattern-making

`kerf-apparel` provides parametric 2-D pattern-making primitives for apparel design:
block generation, seam allowance offsetting, size grading, and marker making.

No heavy dependencies required — pure Python, no OCC or FEniCSx needed.

---

## Modules

### `blocks` — parametric block generators

Generates closed 2-D polylines (pattern pieces) from body measurements (cm).

Supported blocks:

| Function | Description |
|---|---|
| `bodice_front(bust, waist, hip, back_length)` | Basic bodice front block |
| `bodice_back(bust, waist, hip, back_length)` | Basic bodice back block |
| `sleeve(bust, sleeve_length)` | One-piece set-in sleeve |
| `pants_front(waist, hip, inseam, rise)` | Trouser front block |
| `pants_back(waist, hip, inseam, rise)` | Trouser back block |

All accept optional `ease_*` kwargs (cm). Each returns a `PatternPiece`:

```python
@dataclass
class PatternPiece:
    name: str
    outline: list[tuple[float, float]]   # closed polygon, last == first
    grain_line: tuple[Point, Point] | None
    notches: list[Point]
    labels: dict[str, float]             # stores measurements used

    def area() -> float                  # Shoelace area
    def perimeter() -> float
    def bounding_box() -> tuple[float, float, float, float]  # minx, miny, maxx, maxy
```

Size table (`get_measurements(size)` → dict) covers:
- Alpha: XS, S, M, L, XL, XXL
- Numeric US women's: 0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22

---

### `seam_allowance` — offset a pattern outline

```python
add_seam_allowance(piece, offset_cm)    -> PatternPiece  # expand outward
remove_seam_allowance(piece, offset_cm) -> PatternPiece  # shrink inward
offset_polyline(pts, offset)            -> list[Point]   # raw offset
```

Uses a miter-join polygon offset (no external geometry library). Positive offset
expands outward (adds seam allowance); negative shrinks inward.

**Area identity**: for a convex polygon, `ΔA ≈ perimeter × offset` (within ~20 %).

---

### `grading` — proportional size grading

```python
grade_bodice(base_size, size_run=None, ...)  -> GradedSet
grade_sleeve(base_size, size_run=None, ...)  -> GradedSet
grade_pants(base_size, size_run=None, ...)   -> GradedSet
```

`GradedSet.pieces` is a dict keyed `"{size}_front"` / `"{size}_back"` / `"{size}_sleeve"`.

Grading is driven by the measurement table; no separate grade-rules table needed.
Standard increments: bust +5 cm per alpha size step (e.g. M=88 → L=93 cm body).

---

### `marker_making` — nest pieces on fabric

```python
result = make_marker(pieces, fabric_width, gap=0.5, step=0.5)

result.placements     # list[PlacedPiece] with (name, x, y, width, height, area)
result.utilisation    # float, percent (0–100)
result.marker_length  # total fabric length consumed
result.unplaced       # pieces wider than fabric_width
```

Uses a **bottom-left-fill** heuristic (AABB collision). Typical utilisation: 70–80 %.

---

## LLM tools

| Tool | Description |
|---|---|
| `apparel_grade_bodice` | Grade bodice across size run; returns bust girth per size |
| `apparel_add_seam` | Add seam allowance to a standard block; returns area/bbox |
| `apparel_make_marker` | Nest pieces on fabric width; reports utilisation % |

### `apparel_grade_bodice`

```json
{
  "base_size": "M",
  "size_run": ["S", "M", "L"]   // optional, defaults to full run
}
```

Returns `{ "base_size": "M", "sizes": { "M": { "bust_girth_cm": 92, "width_cm": ..., "height_cm": ... }, ... } }`.

### `apparel_add_seam`

```json
{
  "block": "bodice_front",
  "size": "M",
  "seam_allowance_cm": 1.0
}
```

Returns original and expanded area + bounding box.

### `apparel_make_marker`

```json
{
  "size": "M",
  "blocks": ["bodice_front", "bodice_back"],
  "fabric_width_cm": 150
}
```

Returns `utilisation_pct`, `marker_length_cm`, and placement list.

---

## Plugin registration

```python
async def register(app, ctx):
    ctx.tools.register("apparel_grade_bodice", ...)
    ctx.tools.register("apparel_add_seam", ...)
    ctx.tools.register("apparel_make_marker", ...)
    return PluginManifest(
        name="apparel",
        provides=["apparel.blocks", "apparel.seam", "apparel.grading", "apparel.marker"],
        depends=[],
    )
```
