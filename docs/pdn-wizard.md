# PDN Decoupling-Cap Wizard

> Power delivery network impedance analysis — select the minimum decoupling capacitor set that keeps |Z(f)| ≤ Z_target across DC to target bandwidth.

**Module**: `packages/kerf-electronics/src/kerf_electronics/pdn_wizard.py`, `pdn/ac_impedance.py`
**Shipped**: Wave 9
**LLM tools**: `pdn_analyse`, `pdn_recommend_decaps`

---

## What it is

A high-speed IC's power pin sees load-current transients in the hundreds-of-MHz range. The PDN must supply those transients without causing excessive voltage droop (ripple). The target impedance is Z_target = V_supply × ripple_fraction / I_transient. Decoupling capacitors are placed to keep the PDN impedance below Z_target across the entire frequency range. Choosing too few caps leaves the PDN non-compliant; choosing too many wastes board area and cost. This wizard analyses the impedance spectrum and recommends the minimum cap set.

## How to use it

### From chat

> "Design the PDN decoupling for a 1.8 V rail, 3 A transient, 1% ripple budget, bandwidth 500 MHz. I have 100 µF bulk caps and 100 nF MLCC 0402s available."

### From Python

```python
from kerf_electronics.pdn_wizard import analyse_pdn, recommend_decaps

spec = {
    "v_supply": 1.8, "ripple_fraction": 0.01, "i_transient_a": 3.0,
    "bandwidth_hz": 500e6,
    "vrm": {"r_out": 0.02, "l_out": 5e-9},
    "caps": [
        {"C": 100e-6, "R_esr": 0.05, "L_esl": 3e-9, "count": 4},
        {"C": 100e-9, "R_esr": 0.005, "L_esl": 0.5e-9, "count": 10},
    ]
}
result = analyse_pdn(spec)
print(f"Z_target: {result['z_target_ohm']:.4f} Ω")
print(f"Max |Z|: {result['max_z_ohm']:.4f} Ω at {result['worst_freq_hz']/1e6:.0f} MHz")
```

### From an LLM tool spec

```json
{"v_supply": 1.8, "ripple_fraction": 0.01, "i_transient_a": 3.0,
 "bandwidth_hz": 500e6,
 "vrm_l_out_h": 5e-9, "vrm_r_out": 0.02}
```

## How it works

Each capacitor is modelled as a series RLC: Z_cap(f) = R_esr + j2πf(L_esl + L_mount) + 1/(j2πfC). The VRM is a series RL; above its loop bandwidth it is an open circuit. PDN impedance: Z_pdn = 1/Σ(1/Z_i) (admittances add in parallel). Anti-resonance peaks occur where the inductive tail of one cap bank overlaps the capacitive region of the next — these are detected by scanning the swept spectrum for local maxima above Z_target. The recommendation engine adds intermediate-value caps to fill anti-resonance peaks and increases bank count when the inductive tail is too high.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `analyse_pdn(spec)` | `dict` | Impedance spectrum + compliance check |
| `recommend_decaps(spec)` | `dict` | Minimum recommended cap set |
| `pdn_impedance_sweep(components, freq_points)` | `list[dict]` | Raw Z(f) data |

## Example

```python
from kerf_electronics.pdn.ac_impedance import pdn_impedance_sweep
z = pdn_impedance_sweep([{"C":100e-9,"R_esr":0.005,"L_esl":0.5e-9,"count":10}],
                         freq_points=[1e6,10e6,100e6,500e6])
for pt in z:
    print(f"{pt['freq_hz']/1e6:.0f} MHz: |Z| = {pt['z_mag_ohm']:.4f} Ω")
```

## Honest caveats

The PDN model does not account for package inductance between the board decaps and the die — this is typically 0.1–0.5 nH and can be the dominant impedance above 300 MHz. Via inductance is modelled with a simplified Grover formula; actual via placement pattern matters for >500 MHz designs. The recommendation engine is greedy and may not find the globally minimum-cost cap set.

## References

- Ott, H.W. (2009). *Electromagnetic Compatibility Engineering*. Wiley. §11 (power distribution).
- Novak, I. & Miller, J.R. (2007). *Frequency-Domain Characterization of Power Distribution Networks*. Artech House.
