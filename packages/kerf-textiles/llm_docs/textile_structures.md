# Textile Structures Reference

## Weave Structures

### Plain Weave
- Repeat: 2×2
- Warp/weft float = 1.0 (minimum possible)
- Most stable, firmest hand
- Formula: cell[r][c] = (r + c) % 2 == 0

### Twill Weave (N/M)
- Repeat: (N + M) × (N + M)
- Warp float = N, weft float = M
- Diagonal rib line; RH = positive slope, LH = negative slope
- Common: 2/1 (denim), 2/2 (herringbone), 3/1 (twill suiting)

### Satin Weave
- Repeat: S × S (S = shaft count)
- Float = S − 1 (very long floats → lustrous surface)
- gcd(shafts, move) must equal 1
- Common: 5-shaft/move-2, 8-shaft/move-3

### Jacquard
- Arbitrary structure from draft (threading + treadling + tie-up)
- Enables complex figured patterns

## Draft Notation

A complete loom draft comprises:
1. **Threading** — which shaft each warp end uses (straight, pointed, etc.)
2. **Tie-up** — which treadles activate which shafts
3. **Treadling** — which treadle is pressed for each pick

Round-trip serialisation: JSON dict and WIF (Weaving Information File) format.

## Knit Structures

### Jersey (Single Jersey)
- All loops; one needle bed
- Stitch density = gauge × courses_per_cm
- Lightweight, stretchy

### Rib (k×p)
- Knit + purl columns; double bed
- 1×1 rib: equal width knit/purl
- Excellent width stretch and recovery

### Interlock
- Two interlocked 1×1 rib courses
- Stable, reversible, thicker than jersey

## Key Formulas

| Structure | Warp float | Weft float |
|-----------|-----------|-----------|
| Plain     | 1         | 1         |
| N/M twill | N         | M         |
| S-shaft satin | S−1 | S−1     |

Knit stitch density: `ρ = gauge × courses_per_cm`
