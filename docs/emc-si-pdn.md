# EMC / Signal Integrity Pre-Compliance

> Pre-scan EMC wizard — radiated emission estimates, crosstalk, shielding effectiveness, and actionable fix recommendations before the test lab.

**Module**: `packages/kerf-electronics/src/kerf_electronics/emc_wizard.py`, `emc/estimate.py`, `si/solver.py`
**Shipped**: Wave 10
**LLM tools**: `electronics_emc_wizard`, `electronics_si_analyse`

---

## What it is

EMC test failures are expensive: re-spins, lab fees, re-testing. Pre-compliance analysis catches likely failures on a laptop before booking the chamber. This module estimates radiated emissions from differential-mode loops and common-mode cable radiation, checks clock harmonics against CISPR 32 / FCC Part 15 Class B limits, and quantifies PCB trace crosstalk and shielding effectiveness — then produces prioritised, quantified fix recommendations.

## How to use it

### From chat

> "Pre-compliance check for my 100 MHz clock board: 50 mm × 30 mm loop area, 2 m USB cable, plastic enclosure (no shielding). Target: CISPR 32 Class B."

### From Python

```python
from kerf_electronics.emc_wizard import run_emc_wizard

result = run_emc_wizard({
    "clock_freq_hz": 100e6,
    "loop_area_m2": 50e-3 * 30e-3,
    "loop_current_a": 0.01,
    "cable_length_m": 2.0,
    "cable_current_a": 0.001,
    "standard": "CISPR32_ClassB",
    "distance_m": 10.0,
})
for finding in result["findings"]:
    print(f"[{finding['severity']}] {finding['description']}")
    print(f"  Fix: {finding['recommendation']}")
```

### From an LLM tool spec

```json
{"clock_freq_hz": 100e6, "loop_area_m2": 1.5e-3,
 "loop_current_a": 0.01, "cable_length_m": 2.0,
 "cable_current_a": 0.001, "standard": "CISPR32_ClassB"}
```

## How it works

Differential-mode radiation (loop): E = (263×10⁻¹⁶ × A × I × f²) / r dBμV/m. Common-mode cable: E = (1.257×10⁻⁶ × I_cm × f × L) / r dBμV/m. Both are evaluated at each harmonic up to the 10th. `emission_margin_db` compares the result to the CISPR/FCC limit. Crosstalk uses IPC-2141A lumped-capacitance coupled-line models. Signal integrity (SI) calculates microstrip/stripline impedance via IPC-2141A and Wadell formulas and propagation delay. The wizard applies mitigation deltas: adding a common-mode choke adds 20 dB CM attenuation; halving loop area reduces DM radiation by 6 dB.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `run_emc_wizard(spec)` | `dict` | Full pre-compliance report + fixes |
| `emission_margin_db(e_dbuvpm, limit_dbuvpm)` | `float` | Margin to limit |
| `radiated_emission_differential(A, I, f, r)` | `float` | DM E-field (dBμV/m) |
| `radiated_emission_common_mode(I_cm, f, L, r)` | `float` | CM E-field (dBμV/m) |
| `near_field_crosstalk(w, s, h, length, td)` | `dict` | NEXT/FEXT coupling |

## Example

```python
from kerf_electronics.si.solver import microstrip_impedance_ipc2141a
z0 = microstrip_impedance_ipc2141a(W=0.15e-3, H=0.1e-3, T=0.035e-3, er=4.3)
print(f"Z0 = {z0:.1f} Ω")
```

## Honest caveats

All EMC estimates use simplified analytical models — they give ±6–10 dB accuracy, sufficient for go/no-go risk assessment but not for compliance certification. Shielding effectiveness uses a Schelkunoff plane-wave model; aperture coupling and seam leakage require full-wave EM simulation. CISPR 32 vs FCC Part 15 limits differ; ensure the correct standard is selected.

## References

- Ott, H.W. (2009). *Electromagnetic Compatibility Engineering*. Wiley. §6–9.
- IPC-2141A (2004). *Controlled Impedance Circuit Boards and High Speed Logic Design*.
- CISPR 32:2015/AMD2:2019 — Multimedia equipment emissions standard.
