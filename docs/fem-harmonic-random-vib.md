# Harmonic Response and Random Vibration (PSD)

> Frequency-domain harmonic response and random vibration analysis via PSD — qualify products for MIL-STD-810 and IEC environments, compute RMS acceleration.

**Module**: `packages/kerf-fem/src/kerf_fem/harmonic.py`
**Shipped**: Wave 10
**LLM tools**: `fem_harmonic_response`, `fem_random_vibration_psd`

---

## What it is

Many structures experience sinusoidal or broad-spectrum random excitation from rotating machinery, vehicle vibration, or rocket launch. Harmonic response analysis computes the steady-state complex displacement amplitude at each frequency. Random vibration analysis integrates the input power spectral density (PSD) through the frequency response function to give RMS response, used for fatigue and qualification testing.

This module provides: Miles' equation for the SDOF RMS response to flat PSD, single-DOF damped frequency response (compliance), multi-DOF harmonic response by modal superposition, and full PSD integration by the modal method. Engineers use it to check resonance margins, compute RMS acceleration for vibration fatigue, and verify compliance with MIL-STD-810H or IEC 60068-2-64 random vibration environments.

## How to use it

### From chat (natural language)

> "Compute the RMS acceleration for a component with fn=150Hz, Q=10, input PSD=0.04 g²/Hz"

The LLM calls `fem_random_vibration_psd` (Miles' equation shortcut).

### From Python

```python
from kerf_fem.harmonic import (
    miles_equation, harmonic_response, random_vibration_psd,
)

# Miles' equation — SDOF shortcut
sigma = miles_equation(fn_hz=150.0, Q=10.0, W0_g2_per_hz=0.04)
print(f"RMS: {sigma['rms_g']:.2f} g,  3σ: {sigma['3sigma_g']:.2f} g")

# Full harmonic sweep on a beam model
result = harmonic_response(
    K=K_matrix, M=M_matrix,
    C=C_matrix,
    F_vec=F_vector,
    freq_hz_list=[10, 50, 100, 200, 500],
)
for f, amp in zip(result["freq_hz"], result["amplitude"]):
    print(f"  {f} Hz: amplitude = {amp:.4e} m")
```

### From an LLM tool spec

```json
{"tool": "fem_random_vibration_psd", "fn_hz": 150, "Q": 10,
 "W0_g2_per_hz": 0.04, "method": "miles"}
```

## How it works

Miles' equation: GRMS = √(π/2 × fn × Q × W₀), where fn is the natural frequency, Q = 1/(2ζ) is the quality factor, and W₀ is the flat PSD level. This is exact for SDOF + flat PSD. For multi-DOF systems, the harmonic FRF H(ω) = (K - ω²M + iωC)⁻¹F is computed by direct inversion at each frequency. PSD response is Sy = |H(ω)|² × Sx(ω); RMS² = ∫ Sy dω integrated by trapezoid rule.

Structural damping uses the viscous model: C = α M + β K (Rayleigh damping), with α, β computed from two specified modal damping ratios.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `miles_equation(fn_hz, Q, W0_g2_per_hz)` | `dict` | SDOF RMS response |
| `harmonic_response(K, M, C, F_vec, freq_hz_list)` | `dict` | FRF sweep |
| `random_vibration_psd(K, M, zeta, psd_fn, freq_range)` | `dict` | Modal PSD integration |
| `sdof_daf(r, zeta)` | `float` | Dynamic amplification factor |

## Example

```python
sigma = miles_equation(fn_hz=200.0, Q=15.0, W0_g2_per_hz=0.02)
print(f"RMS = {sigma['rms_g']:.3f} g")
print(f"3σ  = {sigma['3sigma_g']:.3f} g")  # peak qualification level
```

## Honest caveats

Miles' equation assumes flat PSD — it overestimates RMS for bandwidth-limited or peaked spectra. The harmonic solver uses direct inversion, which is O(n³) per frequency — use modal reduction for large DOF counts. Structural damping is modelled as viscous (Rayleigh); hysteretic damping requires a different formulation. Non-linear softening/hardening (Duffing oscillator) is not covered.

## References

- Miles (1954). "On structural fatigue under random loading." *J. Aeronautical Sciences* 21(11).
- Harris & Piersol (2010). *Harris' Shock and Vibration Handbook*, 6th ed. McGraw-Hill.
- MIL-STD-810H (2019). Environmental Engineering Considerations and Laboratory Tests. Method 514.8.
