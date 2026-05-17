# jewelry_eternity_auto — Calibrated Eternity-Ring Auto-Distribution

RhinoGold / MatrixGold parity: given ring size, stone cut + size, and setting style, computes the exact stone count to fill a requested arc, per-stone angular positions and seat XYZ, retention spec, and production statistics.

## When to use

Use these tools when a jeweller needs to:
- Populate a full (360°), three-quarter (270°), or half (180°) eternity ring with stones
- Auto-fit stone count for a fixed stone size, or fix stone count and derive gap distribution
- Create a graduated eternity where stones decrease in size from the top outward
- Choose prong, channel, shared-bead (pavé/grain), U-cut, or bezel setting per stone
- Validate minimum metal bridge between adjacent stone cutters
- Get total carat, metal-removed volume, and estimated metal weight

Keywords: eternity ring, eternity band, anniversary ring, full eternity, half eternity, three-quarter eternity, stone distribution, calibrated, fixed count, graduated stones, channel eternity, pavé eternity, shared bead, u-cut, bridge check, minimum bridge, angular position, stone pitch.

## Coverage fractions

| Name | Arc |
|---|---|
| `full` | 360° |
| `three_quarter` | 270° |
| `half` | 180° |

## Setting styles

| Style | Description |
|---|---|
| `prong` | 4-prong or 6-prong head per stone; prong diameter 0.5 mm |
| `channel` | Continuous parallel-rail groove; shared groove cutter |
| `shared_bead` | Single raised bead at each stone boundary (pavé/grain) |
| `u_cut` | U-shaped bright-cut seat with two prong tips at open ends |
| `bezel` | Individual mini-bezel collet per stone |

## Calibration modes

| Mode | Description |
|---|---|
| `fixed_count` | Caller specifies stone count; gap is distributed evenly |
| `fixed_size` | Stone size fixed; count = floor(arc / pitch); remaining gap shared evenly (standard industry default) |
| `graduated` | Stone sizes decrease monotonically from top outward; `size_step_mm` controls increment; count computed to fill arc |

## Coordinate system

Shank centred at origin; ring axis +Z. Angle 0 = 12 o'clock (+Y). Angles increase clockwise viewed from above (consistent with ring.py and RhinoGold).

```
seat_x = ring_radius × sin(angle_rad)
seat_y = ring_radius × cos(angle_rad)
seat_z = 0.0  (centre-plane of shank)
```

## Metal bridge validation

```
bridge_mm = (pitch_deg − stone_subtended_deg) × π/180 × ring_radius
```

Warning `"thin_metal"` appended when `bridge_mm < min_bridge_mm`.

## Metal-removed estimate

Each cutter approximated as truncated cone:

`V_cone = (π/3) × h × (r1² + r1·r2 + r2²)` where r1 = girdle_radius + clearance, r2 ≈ culet_radius, h = pavilion_depth.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_eternity_auto_distribute` | Appends an `eternity_auto` node; primary wizard; required: `file_id`, `ring_size`, `size_system`, `stone_cut`, stone size (`stone_carat` or `stone_diameter_mm`), `setting_style`, `coverage` (full / three_quarter / half) |
| `jewelry_eternity_auto_stats` | Read-only: re-compute statistics from an existing `eternity_auto` node without re-writing; returns stone_count, total_carat, metal_removed_mm3, bridge_mm |

### Key inputs for `jewelry_eternity_auto_distribute`

- `ring_size`, `size_system` — ring sizing (delegates to ring.py)
- `stone_cut`, `stone_carat` or `stone_diameter_mm` — stone geometry
- `setting_style` — see table above
- `coverage` — `full` | `three_quarter` | `half`
- `calibration` — `fixed_size` (default) | `fixed_count` | `graduated`
- `stone_count` — required when calibration=`fixed_count`
- `size_step_mm` — size decrement for calibration=`graduated`
- `min_bridge_mm` — minimum metal bridge between cutters (default 0.15 mm)
- `girdle_clearance_mm` — radial seat clearance (default 0.05 mm)

## Example

Jeweller: "Fill a half-eternity band (US size 6) with 0.10 ct round brilliant diamonds in channel setting."

1. `jewelry_eternity_auto_distribute` — file_id=`<id>`, ring_size=6, size_system=`us`, stone_cut=`round_brilliant`, stone_carat=0.10, setting_style=`channel`, coverage=`half`, calibration=`fixed_size`
   → e.g. stone_count=9, total_carat=0.90 ct, bridge_mm=0.22 mm (ok)
2. `jewelry_eternity_auto_stats` — confirm totals without re-writing node
