# Heat Transfer Engineering (Incropera / Churchill)

Pure-Python heat transfer tools covering conduction, convection, radiation, fins,
heat exchangers, and transient lumped models. No OCC dependency. Units: SI (W, K, m).

---

## When to use

Use these tools when the user asks about heat conduction through walls or pipes,
convection correlations (flat plate, pipe, cylinder, natural convection),
radiation between surfaces, fin efficiency, heat exchanger sizing (LMTD or
ε-NTU), or transient cooling/heating of a body.

Keywords: heat transfer, conduction, convection, radiation, Nusselt, flat plate,
pipe flow, Dittus-Boelter, Churchill-Bernstein, natural convection, fin efficiency,
fin array, heat exchanger, LMTD, NTU, effectiveness, lumped capacitance, Biot,
thermal resistance, composite wall, cylindrical pipe insulation.

---

## Tools

### `hx_composite_wall`

1D steady-state conduction through a plane composite wall (series resistance).

**Input:** `layers` (array of `{k, t, A}` or `{R_contact, A}`), `T_hot` (K), `T_cold` (K) — all required

**Returns:** `Q_W`, `R_total`, `layer_resistances`, `T_interfaces`

---

### `hx_cylindrical_shell`

1D radial conduction through a cylindrical shell.

Q = 2πkL(T_inner − T_outer)/ln(r_outer/r_inner)

**Input:** `r_inner`, `r_outer`, `k`, `T_inner`, `T_outer` (all required); `L` (default 1.0 m)

**Returns:** `Q_W`, `q_per_m`, `R_cond`

---

### `hx_spherical_shell`

1D radial conduction through a spherical shell.

**Input:** `r_inner`, `r_outer`, `k`, `T_inner`, `T_outer` — all required

**Returns:** `Q_W`, `R_cond`

---

### `hx_nusselt_flat_plate`

Average Nusselt number for forced convection over a flat plate (laminar, turbulent, or mixed).

**Input:** `Re_L`, `Pr` (required); `regime` enum `'auto'`/`'laminar'`/`'turbulent'`/`'mixed'` (default auto)

**Returns:** `Nu`, `regime`

---

### `hx_nusselt_pipe_dittus`

Dittus-Boelter Nusselt for fully developed turbulent pipe flow.

Nu = 0.023·Re^0.8·Pr^n (n=0.4 heating, n=0.3 cooling). Valid Re > 10 000.

**Input:** `Re_D`, `Pr` (required); `heating` boolean (default true)

**Returns:** `Nu`, warning if Re ≤ 10 000

---

### `hx_nusselt_pipe_laminar`

Average Nusselt for laminar internal pipe flow (Hausen/Graetz). Valid Re < 2300.

**Input:** `Re_D`, `Pr`, `L_D` (L/D ratio) — all required

**Returns:** `Nu`, `Gz`

---

### `hx_nusselt_cylinder_cb`

Average Nusselt for external cross-flow over a cylinder (Churchill-Bernstein 1977).

**Input:** `Re_D`, `Pr` — both required

**Returns:** `Nu`

---

### `hx_nusselt_natural_vplate`

Average Nusselt for natural convection on a vertical plate (Churchill-Chu 1975).

**Input:** `Ra_L` (Rayleigh number), `Pr` (required); `regime` enum `'all'`/`'laminar'` (default all)

**Returns:** `Nu`

---

### `hx_radiation_two_surface`

Net radiation heat transfer between two gray diffuse surfaces using electrical analogy.

Q_12 = (σT1⁴ − σT2⁴) / (R_surf1 + R_space + R_surf2)

**Input:** `T1`, `T2` (K), `eps1`, `eps2` (emissivity), `A1`, `A2` (m²), `F12` (view factor) — all required

**Returns:** `Q_12_W`, `R_total`, `Eb1`, `Eb2`

---

### `hx_fin_straight`

Efficiency and effectiveness of a straight rectangular fin.

η_f = tanh(m·L_c)/(m·L_c);  m = √(2h/(k·t))

**Input:** `L` (m), `t` (m), `k` (W/m·K), `h` (W/m²·K) — all required; `tip` enum `'adiabatic'`/`'convective'`

**Returns:** `eta_f`, `eps_f`, `mL_c`, `L_c`, `m`

---

### `hx_fin_pin`

Efficiency and effectiveness of a cylindrical pin fin.

m = √(4h/(k·D));  L_c = L + D/4

**Input:** `L`, `D`, `k`, `h` — all required

**Returns:** `eta_f`, `eps_f`, `mL_c`, `L_c`, `m`

---

### `hx_fin_array_resistance`

Overall thermal resistance of a fin array.

η_overall = 1 − N·A_fin/A_total·(1−η_f);  R = 1/(η_overall·h·A_total)

**Input:** `N`, `eta_f`, `A_fin`, `A_base`, `h`, `A_total` — all required

**Returns:** `R_array` (K/W), `eta_overall`

---

### `hx_lmtd`

Heat exchanger sizing via LMTD method: Q = U·A·F·ΔT_lm.

**Input:** `T_h_in`, `T_h_out`, `T_c_in`, `T_c_out`, `U`, `A` (all required); `flow` enum `'counter'`/`'parallel'`/`'crossflow_unmixed'` (default counter)

**Returns:** `Q_W`, `LMTD_K`, `F`, `dT1`, `dT2`

---

### `hx_effectiveness_ntu`

Heat exchanger effectiveness via ε-NTU method.

**Input:** `C_min` (W/K), `C_max` (W/K), `NTU` (required); `flow` enum (default counter)

**Returns:** `epsilon`, `C_r`, `NTU`, `C_min`, `C_max`

---

### `hx_lumped_capacitance`

Transient temperature T(t) using lumped-capacitance model.

τ = ρVcp/(hA_s);  T(t) = T_inf + (T_i − T_inf)·exp(−t/τ). Warns if Bi > 0.1.

**Input:** `T_i`, `T_inf`, `h`, `A_s`, `rho`, `V`, `c_p`, `t` (all required); `k` (optional for Bi check)

**Returns:** `T_t_K`, `tau_s`, `Bi`, `theta`, `Q_total_J`

---

## Example

```
1. hx_composite_wall
     layers:[{k:0.045,t:0.10},{k:200,t:0.003}]
     T_hot:350  T_cold:293
   → Q_W: 25.7  R_total: 2.22 K/W

2. hx_nusselt_pipe_dittus  Re_D:25000  Pr:7.0
   → Nu: 142

3. hx_lmtd  T_h_in:380  T_h_out:320  T_c_in:290  T_c_out:330
             U:800  A:2.5  flow:"counter"
   → Q_W: 88000  LMTD_K: 44.0

4. hx_lumped_capacitance  T_i:500  T_inf:300  h:50  A_s:0.01
                           rho:7800  V:5e-5  c_p:500  t:120
   → T_t_K: 342.7  tau_s: 78
```
