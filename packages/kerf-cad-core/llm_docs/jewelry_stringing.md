# Bead and Pearl Stringing — `jewelry/stringing.py`

Strand length, knot count, bead spacing, silk thread sizing, and necklace layout presets.

---

## Public API

### `strand_layout(bead_diameters_mm, *, knot_between=True, silk_size=None, clasp_allowance_mm=15.0) → dict`

Compute strand geometry for a sequence of beads.

Returns:
```json
{
  "total_length_mm": 457.2,
  "knot_count": 47,
  "silk_size": "F",
  "silk_length_m": 1.85,
  "clasp_allowance_mm": 15.0,
  "bead_count": 46
}
```

`silk_size` auto-selected from bead diameter if not supplied; override with `"0"`, `"A"`, `"B"` … `"FF"` (Griffin silk grades).

### `necklace_preset(style, *, bead_mm=8.0, clasp_allowance_mm=15.0) → dict`

Standard necklace length presets:

| Style | Length |
|-------|--------|
| `choker` | 355 mm (14 in) |
| `princess` | 457 mm (18 in) |
| `matinee` | 559 mm (22 in) |
| `opera` | 711 mm (28 in) |
| `rope` | 889 mm (35 in) |

Returns a `strand_layout` dict for the preset length and supplied bead diameter.

### `torsade(strand_count, bead_diameters_mm, *, necklace_style="princess") → dict`

Multi-strand twisted torsade design:

```json
{
  "strand_count": 3,
  "total_beads": 141,
  "strand_lengths_mm": [457.2, 463.8, 470.4],
  "silk_size": "F",
  "notes": "Offset each strand 6 mm for natural torsade drape"
}
```

---

## Usage

```python
from kerf_cad_core.jewelry.stringing import strand_layout, necklace_preset, torsade

# Custom strand of mixed pearl sizes
result = strand_layout([7.5, 8.0, 8.5, 8.0, 7.5] * 9, knot_between=True)
print(result["silk_length_m"], result["total_length_mm"])

# Quick princess-length strand at 8 mm beads
preset = necklace_preset("princess", bead_mm=8.0)

# 3-strand torsade
design = torsade(3, [6.0] * 47, necklace_style="opera")
```

---

## Notes

- Silk length includes 20% working allowance for knotting.
- `clasp_allowance_mm` is deducted from the bead-strand length.
- Griffin silk size selection: size `0/A/B/C/D/E/F/FF/G/FFF` mapped to bead-hole diameter per standard.
