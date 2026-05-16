# Beam and Cross-Section Analysis (Roark / Hibbeler)

Pure-Python beam bending, cross-section properties, buckling, and stress tools.
No OCC dependency. All tools are stateless. Units: SI (N, m, Pa).

---

## When to use

Use these tools when the user asks about beam deflection, bending moment, shear
force, cross-section properties (moment of inertia, section modulus), column
buckling, combined axial and bending stress, principal stresses, shear flow,
or Mohr's circle.

Keywords: beam, deflection, bending moment, shear force, cantilever, simply
supported, fixed-fixed, section modulus, moment of inertia, I-beam, channel,
hollow tube, column buckling, Euler, Johnson, combined stress, Mohr circle,
principal stress, shear flow, VQ/It.

---

## Tools

### `beam_section_properties`

Cross-section properties for standard structural shapes.

Returns: area A, centroid, Ix/Iy, Sx_top/Sx_bot/Sy (elastic moduli),
Zx/Zy (plastic moduli), rx/ry (radii of gyration), J (torsion constant).

**Input:** `shape` (required) — one of: `'rectangle'`, `'circle'`, `'hollow_rect'`,
`'hollow_circ'`, `'I'`, `'channel'`, `'angle'`

Dimensions (all in metres) as needed by shape: `b`, `h`, `d`, `t`, `bf`, `tf`, `tw`

---

### `beam_loads`

Closed-form beam analysis: max deflection, slope, moment, shear, reactions.

**Input:**
- `support` (required) — `'cantilever'` / `'simply_supported'` / `'fixed_fixed'`
- `load_type` (required) — `'point'` / `'udl'` / `'moment'`
- `E` (Pa), `I` (m⁴), `L` (m) — all required
- `P` (N) for point load; `w` (N/m) for udl; `M0` (N·m) for moment
- `a` (m) — point load position from A (optional)

**Returns:** `max_deflection` (m), `slope_end` (rad), `max_moment` (N·m),
`max_shear` (N), `Ra`, `Rb` (N)

---

### `beam_superpose`

Linearly superpose multiple `beam_loads` result dicts (conservative sum of
max_deflection, max_moment, max_shear).

**Input:** `cases` (array of beam_loads result objects, required)

**Returns:** summed `max_deflection`, `max_moment`, `max_shear`, combined `Ra`/`Rb`

---

### `beam_buckling`

Column buckling: Euler critical load and Johnson short-column transition.

P_euler = π²EI/(K·L)².  Governs for KL/r > Cc. For KL/r ≤ Cc Johnson governs.

K values: 0.5 fixed-fixed, 0.7 fixed-pin, 1.0 pin-pin (default), 2.0 fixed-free.

**Input:** `L_eff`, `A`, `I`, `E`, `Fy` (all required); `K` (default 1.0)

**Returns:** `P_euler_N`, `P_johnson_N`, `P_critical_N`, `sigma_cr_Pa`, `KL_r`,
`Cc`, governing mode, warnings if KL/r > 200

---

### `beam_combined_stress`

Combined axial + bending stress at extreme fibres.

σ_top = P/A − M/S;  σ_bot = P/A + M/S

**Input:** `P` (N, tension positive), `M` (N·m), `A` (m²), `S` (m³) — all required

**Returns:** `sigma_axial`, `sigma_bending`, `sigma_top`, `sigma_bot`, `sigma_max` (all Pa)

---

### `beam_mohr_circle`

Mohr's circle for 2D plane stress: principal stresses and max shear.

**Input:** `sigma_x`, `sigma_y`, `tau_xy` (Pa) — all required

**Returns:** `sigma_1`, `sigma_2` (principal stresses Pa), `tau_max` (Pa),
`sigma_avg` (Pa), `R` (Pa), `theta_p_deg`

---

### `beam_shear_flow`

Shear stress at a section cut: τ = VQ/(I·b).

**Input:** `V` (N), `Q` (m³), `I` (m⁴), `b` (m) — all required

**Returns:** `tau_Pa`

---

## Example

```
1. beam_section_properties  shape:"I"  bf:0.150  d:0.300  tf:0.010  tw:0.008
   → A:5.04e-3 m²  Ix:1.214e-4 m⁴  Sx_top:8.09e-4 m³

2. beam_loads  support:"simply_supported"  load_type:"udl"
               E:200e9  I:1.214e-4  L:6.0  w:15000
   → max_deflection: 0.0124 m  max_moment: 67500 N·m

3. beam_combined_stress  P:50000  M:67500  A:5.04e-3  S:8.09e-4
   → sigma_top: 73.5 MPa  sigma_bot: 93.1 MPa

4. beam_buckling  L_eff:4.0  A:5.04e-3  I:1.214e-4  E:200e9  Fy:250e6  K:1.0
   → P_critical_N: 5.95 MN  governing: euler
```
