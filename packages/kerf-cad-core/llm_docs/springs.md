# Mechanical Spring Design

Pure-Python spring design and analysis tools. No OCC dependency. All tools are
stateless — they compute and return results; no DB write. Units: SI
(metres, Newtons, Pascals).

References: Shigley's MED, 10th ed., Chapter 10; Wahl (1963);
Almen & László, Trans. ASME 58 (1936).

---

## When to use

Trigger on: spring design, helical spring, compression spring, extension spring,
torsion spring, Belleville washer, disc spring, spring rate, spring stiffness,
wire diameter, coil diameter, active coils, spring index, Wahl factor, solid
height, spring buckling, slenderness, spring stress, Goodman fatigue, endurance
limit, spring free length, spring deflection, initial tension.

---

## Tools

### `spring_compression`

Design a helical compression spring (Shigley Ch. 10).

**Key inputs:** `d` (wire diameter, m), `D` (mean coil diameter, m), `N`
(active coils), `G` (shear modulus, Pa; steel ≈ 79.3e9).

Optional: `Fa`, `Fm` (alternating/mean force, N) for stress; `Sut`, `Se`
for Goodman fatigue check; `free_length_m` for buckling check; `end_type`
(`'squared_ground'` default).

**Computes:** k = Gd⁴/(8D³N), spring index C, Wahl factor Kw, solid height,
slenderness λ and buckling flag, peak shear stress, Goodman fatigue ratio.

**Returns:** `{ok, k_N_per_m, spring_index, wahl_factor, solid_height_m,
slenderness, buckling_risk, tau_max_Pa, goodman_ratio, warnings:[]}`.

---

### `spring_extension`

Design a helical extension spring.

**Key inputs:** `d`, `D`, `N`, `G`. Optional: `Fa`, `Fm`, `Sut`, `Se`,
`initial_tension_N`.

**Computes:** rate k, hook bending stress concentration KB, shear stress in
coil body, hook bending stress, Goodman fatigue ratio.

**Returns:** `{ok, k_N_per_m, spring_index, wahl_factor, hook_stress_Pa,
goodman_ratio, warnings:[]}`.

---

### `spring_torsion`

Design a helical torsion spring (primary stress is bending).

**Key inputs:** `d`, `D`, `N`, `E` (Young's modulus, Pa; steel ≈ 200e9).
Optional: `torque_Nm`, `angular_deflection_deg`.

**Computes:** angular rate k = Ed⁴/(64DN) in N·m/rev and N·m/rad, inner-fiber
curvature correction Ki, bending stress.

**Returns:** `{ok, k_Nm_per_rev, k_Nm_per_rad, bending_stress_Pa,
torque_from_deflection_Nm, warnings:[]}`.

---

### `spring_belleville`

Design a Belleville (disc) spring per Almen-László theory.

**Key inputs:** `De` (outer diameter, m), `Di` (inner diameter, m), `t`
(thickness, m), `h0` (free cone height, m), `E` (Pa), `nu` (Poisson's ratio).
Optional: `P_target` (find deflection at this load) or `delta_target`
(find load at this deflection).

**Computes:** load to flatten disc, inner-edge stress, load/deflection at
specified targets, geometric constants α and β.
Warns on snap-through risk when h0/t > 1.5.

**Returns:** `{ok, P_flatten_N, stress_inner_Pa, P_at_delta_target_N,
delta_at_P_target_m, alpha, beta, warnings:[]}`.

---

## Example

**User:** "Design a compression spring: wire d=3 mm, mean coil D=25 mm, N=10
active coils, steel G=79.3 GPa. Free length 80 mm. Is it at risk of buckling?"

**Tool:** `spring_compression` d:0.003 D:0.025 N:10 G:79.3e9 free_length_m:0.080.

Returns k, slenderness λ = L_free/D, and buckling_risk flag.
