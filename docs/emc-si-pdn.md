# EMC, Signal Integrity, and PDN Wizards

*Domain: Electronics · Module: `packages/kerf-electronics/src/kerf_electronics/emc_wizard.py` · Shipped: Wave 10*

## Overview

Pre-compliance EMC analysis: radiated emission estimation (horizontal and vertical dipole radiation from PCB traces), conducted emission check (LISN model), and ESD susceptibility assessment. Signal integrity: eye-diagram prediction from IBIS driver models and transmission-line parameters, differential pair skew and pre-emphasis sizing. PDN analysis is covered separately in `pdn_wizard.py`.

## When to use

- Early-stage radiated emission screening before sending a board to an EMC lab.
- Checking if a clock trace layout is likely to cause FCC Class B failures.
- Sizing pre-emphasis for a high-speed serial link to hit a target eye opening.

## API

```python
from kerf_electronics.emc_wizard import (
    radiated_emission_estimate,
    conducted_emission_lisn,
    differential_pair_skew,
)
from kerf_electronics.si_eye_wizard import (
    eye_diagram_estimate,
)

# Estimate radiated emission from a 100mm loop at 100MHz
em = radiated_emission_estimate(
    loop_area_m2=0.001,
    frequency_hz=100e6,
    current_A=0.01,
    distance_m=3.0,
)
print(em["E_field_dBuVm"])
print(em["fcc_class_b_limit_dBuVm"])
print(em["margin_dB"])
```

## LLM tools

`pcb_emc_check`, `pcb_si_eye`, `pcb_pdn_wizard`

## References

- Paul, *Introduction to Electromagnetic Compatibility*, 2nd ed. (2006).
- Ott, *Electromagnetic Compatibility Engineering* (2009).
- IEC CISPR 32:2015, *Multimedia equipment — EMC requirements*.

## Honest caveats

Radiated emission estimates use simplified dipole antenna models and are order-of-magnitude accuracy only (±6 dB typical). They indicate risk, not compliance. Actual EMC compliance requires accredited laboratory testing per CISPR/FCC/CE. The IBIS eye-diagram model uses simplified channel models without crosstalk or power-plane resonance — add SI simulation tool (HyperLynx, Sigrity) for production-level SI analysis.
