# Fatigue Life Analysis (Shigley / Dowling / ASTM E1049)

Pure-Python fatigue-life calculation tools. No OCC dependency. All tools are
stateless — compute and return results; no DB write. Units: SI (Pa, m/m, cycles).

---

## When to use

Use these tools when the user asks about fatigue life, S-N curve, endurance
limit, Marin factors, strain-life, Coffin-Manson, cumulative damage, Miner's
rule, rainflow counting, mean stress, Goodman, Gerber, Soderberg, notch
correction, or Neuber.

Keywords: fatigue, S-N, endurance limit, Marin, Basquin, strain-life, Coffin-Manson,
Miner's rule, cumulative damage, rainflow, mean stress, Goodman, Gerber, Soderberg,
Morrow, SWT, notch, Neuber, stress concentration, infinite life, finite life, cycles.

---

## Tools

### `fatigue_sn_cycles`

Cycles to failure via Basquin S-N power law: sigma_a = Sf'·(2N)^b.

**Input:** `sigma_a` (Pa, required), `Sf_prime` (Pa, required), `b` (Basquin exponent < 0, required)

**Returns:** `N_cycles`, `infinite_life` flag (true if N > 1e7)

---

### `fatigue_endurance_limit`

Modified endurance limit Se using Marin factors: Se = ka·kb·kc·kd·ke·kf·Se'.

**Input:** `Se_prime` (Pa, required); all Marin factors `ka`–`kf` optional (default 1.0)

**Returns:** `Se` (Pa), applied factor values

---

### `fatigue_strain_life`

Cycles to failure via Coffin-Manson-Basquin strain-life (ε-N) equation solved
numerically by bisection.

**Input:** `eps_a`, `E`, `Sf_prime`, `b`, `eps_f_prime`, `c` — all required

**Returns:** `N_cycles`, elastic and plastic strain components at that life

---

### `fatigue_neuber_notch`

Neuber notch correction for elasto-plastic notch root analysis.

sigma_local · eps_local = Kf² · S_nom · e_nom

**Input:** `S_nom` (Pa), `e_nom` (m/m), `Kf`, `E` — all required

**Returns:** `C_neuber`, `sigma_el`, `eps_el`, `plasticity` flag

---

### `fatigue_mean_stress`

Mean-stress correction: convert (sigma_a, sigma_m) to equivalent fully-reversed sigma_ar.

**Input:** `sigma_a`, `sigma_m`, `Se`, `Sut`, `Sy` (all required); `method` enum `'goodman'`/`'gerber'`/`'soderberg'`/`'morrow'`/`'swt'` (default goodman); `Sf_prime` (required for morrow)

**Returns:** `sigma_ar`, `safety_factor`, `fatigue_ok`

---

### `fatigue_miner_damage`

Palmgren-Miner cumulative damage D = Σ(n_i/N_i) from a load spectrum.

**Input:** `cycles` (array), `stress_amplitudes` (array, Pa), `Sf_prime`, `b` — all required

**Returns:** `D_total`, `remaining_life`, per-block damage list; `failed` flag if D ≥ 1

---

### `fatigue_rainflow_count`

ASTM E1049 four-point rainflow cycle counting on a stress/strain time history.

**Input:** `history` (array of values, required; ≥ 2 elements)

**Returns:** list of counted cycles: `{range, mean, count}`

---

### `fatigue_life`

Combined fatigue safety factor and predicted S-N life summary.

n_fatigue = Se/sigma_a; N_predicted via Basquin; infinite_life if sigma_a ≤ Se.

**Input:** `sigma_a`, `Se`, `Sf_prime`, `b`, `Sut` (all required); `safety_factor` (default 1.0)

**Returns:** `n_fatigue`, `N_predicted`, `infinite_life`, `sigma_a_design`

---

## Example

```
1. fatigue_endurance_limit  Se_prime:350e6  ka:0.72  kb:0.85  ke:0.868
   → Se: 184.7 MPa

2. fatigue_mean_stress  sigma_a:120e6  sigma_m:80e6
                        Se:184.7e6  Sut:620e6  Sy:450e6  method:"goodman"
   → sigma_ar: 136.6 MPa  fatigue_ok: true

3. fatigue_sn_cycles  sigma_a:136.6e6  Sf_prime:657.2e6  b:-0.085
   → N_cycles: 1.23e6  infinite_life: false

4. fatigue_miner_damage  cycles:[1e5,5e4]
                         stress_amplitudes:[150e6,180e6]
                         Sf_prime:657.2e6  b:-0.085
   → D_total: 0.42  remaining_life: 0.58  failed: false
```
