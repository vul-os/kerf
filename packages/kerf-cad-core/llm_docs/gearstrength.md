# AGMA Gear Strength Rating (AGMA 2001-D04)

Pure-Python AGMA 2001-D04 gear-tooth strength and contact-stress calculation
tools. No OCC dependency. Units: English (lbf, in, psi) by default; SI
(N, mm, MPa) available via `metric=true`.

---

## When to use

Use these tools when the user asks about gear strength, gear rating, AGMA,
bending stress, contact stress (pitting), gear power capacity, gear safety
factor, or gear service life under cyclic loading.

Keywords: AGMA, gear strength, bending stress, contact stress, pitting, Lewis,
dynamic factor, safety factor, gear rating, power rating, gear life, S-N cycles,
YN ZN stress-cycle factors, gear overload, diametral pitch, module.

---

## Tools

### `agma_dynamic_factor`

AGMA dynamic factor Kv from quality number Qv and pitch-line velocity.

**Input:** `Vt_fpm` (required) — pitch-line velocity (ft/min); `Qv` (required) — quality number (3–12)

**Returns:** `Kv`, validity range, warning if velocity exceeds AGMA limit for Qv

---

### `agma_geometry_factor_J`

AGMA bending geometry factor J (Lewis form factor corrected for helix).

**Input:** `N` (required) — tooth count (≥ 12); `psi_deg` (required) — helix angle (0 for spur); `pressure_angle_deg` (default 20)

**Returns:** `J` (dimensionless)

---

### `agma_geometry_factor_I`

AGMA pitting (contact) geometry factor I for a gear pair.

**Input:** `N_p`, `N_g`, `psi_deg` (all required); `pressure_angle_deg` (default 20); `external` boolean (default true)

**Returns:** `I` (dimensionless)

---

### `agma_bending_stress`

AGMA 2001-D04 bending stress σ_t.

Metric: σ_t = Wt·Ko·Kv·Ks·Km·KB / (b·m·J)  
English: σ_t = Wt·Ko·Kv·Ks·Pd·Km·KB / (b·J)

**Input:** `Wt`, `Ko`, `Kv`, `Ks`, `Km`, `KB`, `b`, `m_or_Pd`, `J` (all required); `metric` boolean (default false)

**Returns:** `sigma_t` (psi or MPa)

---

### `agma_contact_stress`

AGMA 2001-D04 contact/pitting stress σ_c.

σ_c = Cp · √(Wt·Ko·Kv·Ks·Km / (d_p·b·I))

**Input:** `Wt`, `Ko`, `Kv`, `Ks`, `Km`, `Cp`, `d_p`, `b`, `I` (all required); `metric` boolean (default false)

**Returns:** `sigma_c` (√psi or √MPa)

---

### `agma_safety_factors`

AGMA 2001-D04 safety factors SF (bending) and SH (contact).

SF = sigma_t_all / sigma_b;  SH = sigma_c_all / sigma_c

**Input:** `sigma_b`, `sigma_c`, `S_t`, `S_c` (all required); optional `YN`, `ZN`, `K_T`, `K_R`

**Returns:** `SF`, `SH`, `sigma_t_all`, `sigma_c_all`, warnings if SF/SH < 1.2

---

### `agma_power_rating`

Maximum safe transmitted power and torque for a gear pair.

Solves for governing tangential load from both bending and contact allowables,
then converts to power (hp or kW).

**Input:** `S_t`, `S_c`, `Cp`, `b`, `m_or_Pd`, `d_p`, `N_p`, `N_g`, `psi_deg`, `n_rpm` (all required); many optional factors (Ko, Ks, Km, KB, Qv, K_T, K_R, YN, ZN, metric)

**Returns:** `Wt_governing`, `P_hp` (or `P_kW`), `T_Nm`, governing mode (bending/contact)

---

### `agma_service_life`

AGMA 2001-D04 stress-cycle factors YN (bending) and ZN (contact) for finite life.

**Input:** `N_cycles` (required); `hardness_HB` (default 200); `gear_type` enum `'through_hardened'`

**Returns:** `YN`, `ZN`

---

## Example

```
1. agma_dynamic_factor  Vt_fpm:1200  Qv:6
   → Kv: 1.48

2. agma_geometry_factor_J  N:20  psi_deg:0
   → J: 0.27

3. agma_geometry_factor_I  N_p:20  N_g:40  psi_deg:0
   → I: 0.107

4. agma_bending_stress  Wt:1200  Ko:1.25  Kv:1.48  Ks:1.0
                        Km:1.3  KB:1.0  b:1.5  m_or_Pd:8  J:0.27
   → sigma_t: 58 900 psi

5. agma_safety_factors  sigma_b:58900  sigma_c:92000
                        S_t:65000  S_c:225000
   → SF: 1.10  SH: 2.44
```
