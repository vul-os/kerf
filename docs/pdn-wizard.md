# PDN Wizard (Power Delivery Network)

*Domain: Electronics · Module: `packages/kerf-electronics/src/kerf_electronics/pdn_wizard.py` · Shipped: Wave 10*

## Overview

Analyses and optimises a PCB power delivery network (PDN) by sweeping impedance versus frequency across capacitor bank combinations. Computes the target impedance from the transient current spec, sweeps the bank network at each frequency, finds resonance peaks exceeding the target, and recommends capacitor additions or re-sizing to flatten the impedance profile. Covers bulk, mid-band, and high-frequency (HF) decoupling stages.

## When to use

- Checking whether a decoupling scheme meets the target impedance spec for an FPGA or processor.
- Recommending bulk/ceramic/HF capacitor placements to suppress PDN resonances.
- Generating impedance plots for PI (power integrity) review.

## API

```python
from kerf_electronics.pdn_wizard import (
    z_target_from_spec,
    characterise_cap,
    pdn_wizard,
)

z_target = z_target_from_spec(
    vdd_v=1.8, ripple_frac=0.05, i_transient_a=2.0
)

result = pdn_wizard({
    "vdd_v": 1.8,
    "ripple_frac": 0.05,
    "i_transient_a": 2.0,
    "bandwidth_hz": 500e6,
    "banks": [
        {"C_f": 100e-6, "ESR": 0.005, "ESL": 2e-9, "count": 4},
        {"C_f": 10e-9,  "ESR": 0.02,  "ESL": 0.5e-9, "count": 8},
    ],
})
print(result["peaks_above_target"])
print(result["recommendations"])
```

## LLM tools

`feature_pdn_wizard`

## References

- Ott, *Electromagnetic Compatibility Engineering*, ch. 10 (PDN).
- Novak & Miller, *Frequency-Domain Characterization of Power Distribution Networks* (2007).

## Honest caveats

PDN modelling is a lumped-element approximation. Spreading inductance, board stackup geometry, and via inductance are not automatically extracted — supply them as `ESL` per bank. The optimiser assumes all capacitors in a bank are placed at the same location; split placement is not modelled.
