# kerf-structural

Structural engineering design utilities: ACI 318 RC beam design, AISC 360 steel moment capacity, rebar detailing, and ASCE 7 load combinations. All computations are pure-Python with no heavy dependencies.

---

## Modules

### `rc_beam.py` — ACI 318 RC beam design

#### `design_rc_beam(b, h, Mu_kip_ft, *, fc=4000, fy=60000, cover=1.5, ...) → RCBeamResult`

Singly-reinforced rectangular beam: required tension steel area using the ACI R-method.

```
d = h − cover − stirrup_dia − bar_dia/2
Rn = Mu / (φ b d²)          [psi]
ρ  = (0.85 f'c / fy) × (1 − √(1 − 2 Rn / (0.85 f'c)))
As = max(ρ, ρ_min) × b × d  [in²]
```

Checks:
- ρ_min = max(3√f'c / fy, 200/fy)   ACI 318-19 §9.6.1.2
- ρ_max based on εt ≥ 0.004          ACI 318-19 §9.3.3.1
- Returns `ok=False` with reason if over-reinforced or geometry invalid

Key result fields: `As_required`, `rho`, `rho_min`, `rho_max`, `d`, `Rn`, `phi`.

#### `check_rc_beam(b, h, As, *, ...) → dict`

Capacity check: returns `phi_Mn_kip_ft`, `epsilon_t`, `phi`, `a`, `c` for a given steel area.

---

### `steel_beam.py` — AISC 360-22 W-shape moment capacity

#### `design_steel_beam(section, Lb_ft, *, Fy=50, E=29000, Cb=1.0, phi=0.9) → SteelBeamResult`

AISC 360-22 Chapter F2 — compact doubly-symmetric W-shapes, strong-axis bending.

LTB zones:
- `Lb ≤ Lp` → **plastic**:   Mn = Mp = Fy × Zx
- `Lp < Lb ≤ Lr` → **inelastic**:  linear interpolation F2-2
- `Lb > Lr` → **elastic**:  Fcr via F2-3; Mn = Fcr × Sx

Limit lengths:
```
Lp = 1.76 ry √(E / Fy)                    [in]  AISC F2-5
Lr = 1.95 rts (E / 0.7Fy) √(J c/(Sx ho) + √(...))   AISC F2-6
```

Key result fields: `phi_Mn_kip_ft`, `ltb_zone`, `Lp`, `Lr`, `Mp`, `Mn`.

Built-in W-shape table: W8×31 through W36×135 (17 common sections). Supply a `WSection` dataclass for any other section.

#### `w_section(designation) → WSection`

Look up a section from the built-in table (e.g. `w_section("W18X50")`).

#### `moment_capacity(designation, Lb_ft, *, Fy=50, Cb=1.0) → float`

Convenience wrapper returning φMn in kip-ft; raises `ValueError` on failure.

---

### `rebar_detailing.py` — ACI 318 §25 detailing

#### `bar_info(bar_mark) → BarInfo`

Returns nominal `diameter` (in), `area` (in²), `weight` (lb/ft) for bar marks #3–#18.

#### `development_length(bar_mark, *, fc=4000, fy=60000, psi_t=1.0, psi_e=1.0, lambda_factor=1.0, cb_Ktr_db=2.5) → float`

Tension development length l_d (in) per ACI 318-19 §25.5.2.1 detailed formula:

```
l_d = (3/40) × (fy / (λ √f'c)) × (ψ_t ψ_e ψ_s / ((cb+Ktr)/db)) × db
```

Minimum 12 in enforced. Size factor ψ_s = 0.8 for #6 and smaller, 1.0 otherwise.

#### `lap_splice_length(bar_mark, splice_class='B', *, ...) → float`

ACI 318-19 §25.5.5:
- Class A: 1.0 × l_d  (≥50% of bars spliced with adequate spacing)
- Class B: 1.3 × l_d  (more common conservative case)

#### `hook_development_length(bar_mark, *, fc=4000, fy=60000, ...) → float`

Standard hook l_dh per ACI 318-19 §25.4.3.1. Minimum max(8 db, 6 in).

---

### `load_combinations.py` — ASCE 7 strength design

#### `asce7_strength_combinations(lc: LoadCase) → list[CombinationResult]`

All 7 ASCE 7-22 §2.3.1 basic combinations:

| # | Label              | Formula                                   |
|---|--------------------|-------------------------------------------|
| 1 | 1.4D               | 1.4D + F                                  |
| 2 | 1.2D+1.6L          | 1.2D + 1.6L + 0.5 max(Lr,S,R) + F        |
| 3 | 1.2D+1.6Lr(S,R)+L  | 1.2D + 1.6 max(Lr,S,R) + max(L, 0.5W) + F |
| 4 | 1.2D+1.0W+L+0.5Lr  | 1.2D + W + L + 0.5 max(Lr,S,R) + F       |
| 5 | 0.9D+1.0W          | 0.9D + W + H                              |
| 6 | 1.2D+1.0E+L+0.2S   | 1.2D + E + L + 0.2S + F                  |
| 7 | 0.9D+1.0E          | 0.9D + E + H                              |

#### `governing_combination(lc) → CombinationResult`

Returns the combination with maximum factored demand.

#### `combo_by_label(lc, label) → float`

Look up a specific combination by label prefix string.

---

### LLM tool specs

| Tool name                | Description                                   |
|--------------------------|-----------------------------------------------|
| `structural_rc_beam`     | ACI 318 RC beam — required As, ρ, ρ_min/max   |
| `structural_steel_beam`  | AISC 360 W-shape φMn with LTB                 |
| `structural_rebar`       | Development + lap-splice lengths (ACI §25)    |
| `structural_loads`       | ASCE 7 factored load combinations             |

---

## Quick reference: common values

**RC beam defaults**: f'c=4000 psi, fy=60000 psi (Grade 60), cover=1.5 in, #3 stirrups, #5 bars.

**Steel defaults**: A992 steel Fy=50 ksi, E=29000 ksi, φ=0.90.

**Rebar detailing defaults**: normal-weight concrete (λ=1.0), uncoated (ψ_e=1.0), well-confined (cb+Ktr)/db=2.5.
