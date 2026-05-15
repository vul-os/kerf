# Flex & Rigid-Flex Stackup Manager

Tools for modelling flex / rigid-flex PCB stackups and validating bend regions
against IPC-2223C published design guidance.

---

## Data model

### Layer object

```jsonc
{
  "name":         "PI_core",       // optional label
  "type":         "PI",            // copper | PI | adhesive | coverlay | stiffener
  "thickness_mm": 0.050,
  "er":           3.4,             // optional; meaningful for PI / adhesive
  "zone":         "flex"           // flex (default) | rigid
}
```

**Layer types:**

| type      | Description                                             |
|-----------|--------------------------------------------------------|
| copper    | Conductor foil (1 oz = 0.035 mm)                       |
| PI        | Polyimide dielectric film (Kapton-class)               |
| adhesive  | Acrylic or epoxy bonding film                          |
| coverlay  | Polyimide + adhesive protective overlay                |
| stiffener | FR4 or stainless-steel stiffener (rigid zone only)     |

### Typical single-sided flex cross-section (top → bottom)

```
coverlay   0.025 mm   flex
copper     0.035 mm   flex  ← 1 oz foil
adhesive   0.025 mm   flex
PI         0.050 mm   flex  ← core dielectric, εr ≈ 3.4
adhesive   0.025 mm   flex
coverlay   0.025 mm   flex
────────────────────────────
Total flex thickness t ≈ 0.185 mm
```

---

## IPC-2223 bend radius rules

Reference: **IPC-2223C** *Sectional Design Standard for Flexible Printed Boards*
(2013), §4.6 (static flex) and §4.7 (dynamic flex).

| Flex type              | Minimum inner radius r_min |
|------------------------|---------------------------|
| Static single-sided    | r ≥ **6 × t**             |
| Static double-sided    | r ≥ **12 × t**            |
| Dynamic (any)          | r ≥ **100 × t**           |

where **t** = total flex-zone laminate thickness at the bend.

## Outer-fibre strain

Standard beam-bending formula (IPC-2223C §4.6):

```
ε = t / (2r)
```

Recommended limits:
- Static flex:  ε ≤ **0.3 %**
- Dynamic flex: ε ≤ **0.1 %**

---

## Tools

### `flex_stackup_define`

Build a stackup from an ordered layer list.  Returns thickness summary, copper
count, zone breakdown, and rigid-flex flag.

```json
{
  "layers": [
    {"type": "coverlay",  "thickness_mm": 0.025, "zone": "flex"},
    {"type": "copper",    "thickness_mm": 0.035, "zone": "flex"},
    {"type": "PI",        "thickness_mm": 0.050, "er": 3.4, "zone": "flex"},
    {"type": "coverlay",  "thickness_mm": 0.025, "zone": "flex"}
  ],
  "stackup_name": "1L_FLEX"
}
```

Returns:
```json
{
  "ok": true,
  "total_thickness_mm": 0.135,
  "flex_thickness_mm": 0.135,
  "copper_count": 1,
  "flex_copper_count": 1,
  "is_rigid_flex": false,
  "zones": [...]
}
```

---

### `flex_bend_check`

Check a bend region against IPC-2223C minimum radius rules.

```json
{
  "inner_radius_mm": 1.5,
  "flex_thickness_mm": 0.185,
  "flex_type": "single_sided"
}
```

Returns:
```json
{
  "ok": true,
  "passed": true,
  "multiplier": 6,
  "recommended_min_radius_mm": 1.11,
  "margin_mm": 0.39,
  "message": "PASS: inner radius 1.5000 mm ≥ 6t = 1.1100 mm (IPC-2223C single_sided)",
  "reference": "IPC-2223C (2013) §4.6 (static) / §4.7 (dynamic)"
}
```

**flex_type values:**

| value           | Applies when                                        |
|-----------------|-----------------------------------------------------|
| `single_sided`  | Copper on one face of the flex core (6t rule)       |
| `double_sided`  | Copper on both faces (12t rule)                     |
| `dynamic`       | Flex section cycles repeatedly in use (100t rule)   |

---

### `flex_neutral_axis`

Calculate neutral-axis offset and outer-fibre strain.

```json
{
  "inner_radius_mm": 2.0,
  "flex_thickness_mm": 0.185,
  "flex_type": "single_sided"
}
```

Returns:
```json
{
  "ok": true,
  "neutral_axis_offset_from_inner_mm": 0.0925,
  "outer_fibre_strain": 0.04625,
  "outer_fibre_strain_pct": 4.625,
  "strain_limit_pct": 0.3,
  "within_strain_limit": false,
  "warnings": ["Outer-fibre strain 4.625% exceeds static limit 0.3% — increase inner radius."],
  "formula": "ε = t / (2r)  [IPC-2223C §4.6; beam bending theory]"
}
```

---

### `flex_fab_summary`

Generate fabrication notes from a stackup and optional bend check results.

```json
{
  "layers": [...],
  "bend_results": [
    { "passed": true, "inner_radius_mm": 1.5, "flex_type": "single_sided",
      "recommended_min_radius_mm": 1.11, "message": "PASS" }
  ],
  "stackup_name": "MY_FLEX"
}
```

Returns notes and warnings covering:
- Coverlay coverage on flex / rigid zones
- Stiffener placement recommendations
- Controlled-impedance feasibility (requires ≥2 flex copper layers + εr on PI)
- Bend region pass/fail summary

---

## Typical workflows

### Validate a static single-sided flex design

```
1. flex_stackup_define  — build stackup, note flex_thickness_mm (t)
2. flex_bend_check      — inner_radius_mm=r, flex_thickness_mm=t,
                          flex_type="single_sided"
                          → check passed; if not, increase r to recommended_min_radius_mm
3. flex_neutral_axis    — verify outer_fibre_strain_pct ≤ 0.3%
4. flex_fab_summary     — review coverlay, stiffener, impedance notes
```

### Size a dynamic flex cable

```
1. flex_stackup_define  — all layers zone="flex"; note flex_thickness_mm t
2. flex_bend_check      — flex_type="dynamic"
                          r_min = 100 × t
3. flex_neutral_axis    — flex_type="dynamic", limit 0.1%
                          ε = t/(2r) must be ≤ 0.001
4. flex_fab_summary     — verify no stiffeners overlap dynamic bend zone
```

### Rigid-flex 4-layer board

```
1. flex_stackup_define  — mix zone="rigid" (FR4/stiffener layers) and
                          zone="flex" (PI + copper + coverlay)
                          → is_rigid_flex=true
2. flex_bend_check      — use flex_thickness_mm (not total_thickness_mm)
3. flex_fab_summary     — check stiffener and coverlay recommendations
```

---

## Reference

- IPC-2223C *Sectional Design Standard for Flexible Printed Boards* (2013), §4.6–4.7
- IPC-6013D *Qualification and Performance Specification for Flexible/Rigid-Flex PCBs*
