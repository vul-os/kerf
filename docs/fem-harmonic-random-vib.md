# Harmonic Response and Random Vibration (PSD)

*Domain: Structural FEM · Module: `packages/kerf-fem/src/kerf_fem/harmonic.py` · Shipped: Wave 10*

## Overview

Frequency-domain harmonic response analysis (steady-state sinusoidal excitation) and random vibration analysis via Power Spectral Density (PSD) loading. The harmonic solver applies a complex frequency-domain compliance matrix at each frequency step and returns amplitude/phase spectra. The random vibration solver integrates the PSD load through the frequency response function to compute RMS response using Miles' equation and the full modal superposition method.

## When to use

- Checking a structure's dynamic response to rotating machinery excitation.
- Qualifying a product for MIL-STD-810 or IEC 60068-2-64 random vibration environments.
- Computing peak-response PSD spectra for fatigue estimates.

## API

```python
from kerf_fem.harmonic import (
    HarmonicConfig, solve_harmonic,
    solve_random_vibration_psd,
    miles_equation,
)

# Miles' equation shortcut for SDOF system
sigma = miles_equation(
    fn_hz=150.0,
    Q=10.0,
    W0_g2_per_hz=0.04,
)
print(sigma["rms_g"], sigma["3sigma_g"])

# Full harmonic sweep
result = solve_harmonic(
    K=stiffness_matrix,
    M=mass_matrix,
    C=damping_matrix,
    F_vec=force_vector,
    freq_hz_list=[10, 20, 50, 100, 200],
)
```

## LLM tools

`fem_harmonic_response`, `fem_random_vibration_psd`

## References

- Miles, "On structural fatigue under random loading", *J. Aero. Sci.* 21(11), 1954.
- Harris & Piersol, *Harris' Shock and Vibration Handbook*, 6th ed. (2010).
- MIL-STD-810H, *Environmental Engineering Considerations and Laboratory Tests*, Method 514.8.

## Honest caveats

Miles' equation is exact only for a single-degree-of-freedom (SDOF) system with flat PSD. For multi-DOF systems, use the full modal-superposition PSD path. Structural damping is modelled as viscous (C = 2ζωM); hysteretic damping requires a separate formulation. Nonlinear softening or hardening (Duffing oscillator) is not covered.
