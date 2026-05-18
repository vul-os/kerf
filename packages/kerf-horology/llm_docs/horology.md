# kerf-horology — watchmaking / horology plugin

`kerf-horology` provides parametric generators and LLM tools for mechanical
watch and clock design. It is a thin wrapper around
`kerf_partsgen.generators.horology` and exposes the geometry through Kerf's
tool-call layer.

---

## Generators

All generators live in `packages/kerf-partsgen/src/kerf_partsgen/generators/horology/`
and follow the standard `kerf-partsgen` FAMILY / SIZES / build() contract.

| Generator | family_id | Category | Description |
|---|---|---|---|
| `escape_wheel.py` | `horology_escape_wheel` | `horology/escapement` | Swiss lever escape wheel blank, 15 teeth, 3 lignes sizes |
| `pallet_fork.py` | `horology_pallet_fork` | `horology/escapement` | Swiss lever pallet fork body blank |
| `gear_train.py` | `horology_gear_train_wheel` | `horology/gear_train` | Gear-train wheel blank (DIN 58400 module series) |
| `mainspring_barrel.py` | `horology_mainspring_barrel` | `horology/barrel` | Mainspring barrel drum (annular cylinder) |

---

## Tools

### `train_calculator`

Compute the required gear-train ratio for a mechanical watch movement.

**Formula (time-independent):**

```
R = (freq_hz × 86400) / (escape_wheel_teeth × barrel_turns_per_day)
```

**Common values:**

| Frequency | bph | R (15t, 7.5 tpd) |
|---|---|---|
| 2.5 Hz | 18 000 | 1920 |
| 3.0 Hz | 21 600 | 2304 |
| 4.0 Hz | 28 800 | 3072 |
| 5.0 Hz | 36 000 | 3840 |

**Example:**

```python
from kerf_horology import compute_train_ratio

spec = compute_train_ratio(
    freq_hz=3.0,
    power_reserve_hours=48,
    escape_wheel_teeth=15,
    barrel_turns_per_day=7.5,
)
print(spec.required_ratio)        # 2304.0
print(spec.barrel_turns_stored)   # 15.0
for s in spec.stages:
    print(s.wheel_teeth, s.pinion_leaves, s.ratio)
```

**Power reserve** determines how many barrel turns must be stored
(`barrel_turns_stored = barrel_turns_per_day × power_reserve_hours / 24`)
but does NOT change the required ratio.

---

### `check_tooth_profile`

Validate an involute tooth profile for a given module, tooth count, and
pressure angle.

```python
from kerf_horology import check_involute_profile

result = check_involute_profile(module=0.128, num_teeth=15, pressure_angle_deg=20.0)
print(result.passed)   # True
print(result.r_base)   # base-circle radius (mm)
print(result.r_pitch)  # pitch radius (mm)
print(result.r_tip)    # tip-circle radius (mm)
```

Validity criteria checked:
1. Base-circle radius is positive and < pitch radius
2. Profile starts at the base circle (t ≥ 0)
3. Profile reaches the tip circle (within tolerance)
4. Radii are monotonically non-decreasing (no fold-back)
5. No discontinuities (chord < 2× mean spacing)

---

## Involute geometry

The involute of a base circle of radius `r_b`:

```
x(t) = r_b * (cos t + t * sin t)
y(t) = r_b * (sin t - t * cos t)
r(t) = r_b * sqrt(1 + t²)
```

where `t = 0` at the base circle and increases toward the tip.

Key radii from module `m` and tooth count `z` at pressure angle `α`:

```
d   = m × z          # pitch diameter
r_p = d / 2          # pitch radius
r_b = r_p × cos α   # base-circle radius
r_a = r_p + m        # tip-circle radius (addendum = 1 module)
r_f = r_p - 1.25m   # root-circle radius (dedendum = 1.25 module)
```

---

## Gear-train ratio derivation

The Swiss lever escapement produces **2 impulses per oscillation**.
For a balance wheel at frequency `f` Hz:

```
beats_per_hour = f × 3600
```

The escape wheel (15 teeth) advances one tooth per beat:

```
escape_wheel_rph = beats_per_hour / 15 = f × 240
```

The barrel turns `n` times per day:

```
barrel_rph = n / 24
```

The required ratio (barrel → escape wheel):

```
R = escape_wheel_rph / barrel_rph = (f × 240) / (n / 24) = (f × 86400) / (15 × n)
```

For ETA 2824-2 defaults (f=3 Hz, n=7.5 tpd): R = 259200 / 112.5 = **2304**.

---

## References

- Cousins UK: Swiss lever escapement geometry tables
- DIN 58400: Fine-mechanics gear module series (0.06–0.25 mm)
- NIHS 94-10: Pallet-fork geometry specification
- Shigley §13-5: Involute tooth profile derivation
- AGMA 908-B89: Geometry factors for involute gears
