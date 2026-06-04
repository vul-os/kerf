# Marine Hydrodynamics and Ship Resistance

> Estimate ship resistance, wave-induced forces, and seakeeping response using Holtrop-Mennen regression and JONSWAP wave spectra.

**Module**: `packages/kerf-cfd/src/kerf_cfd/marine/hydrodynamics.py`
**Shipped**: Wave 10
**LLM tools**: `cfd_marine_resistance`

---

## What it is

Ship resistance prediction is the first step in propulsion system sizing. The Holtrop-Mennen statistical regression method (1984) gives total resistance (frictional + residuary + appendage + air drag) from hull geometry parameters (LWL, displacement, Cb, Cp) and Froude number. For wave-induced loads and seakeeping, irregular sea states are modelled by the JONSWAP spectrum and linear wave diffraction theory.

This module provides: Holtrop-Mennen resistance prediction, ITTC 1957 frictional resistance, JONSWAP wave spectrum generation, linear wave diffraction force estimation on a vertical cylinder, and wetted surface estimation. Naval architects use it for early-stage resistance curves, propulsion sizing, and seakeeping assessment before full CFD runs.

## How to use it

### From chat (natural language)

> "Estimate the total resistance of a 60m vessel with displacement 800t, Cb=0.72, at 12 knots"

The LLM calls `cfd_marine_resistance` with the hull parameters.

### From Python

```python
from kerf_cfd.marine.hydrodynamics import (
    ShipHull, holtrop_mennen_resistance, ResistanceReport,
    jonswap_spectrum, linear_wave_diffraction_force,
)

hull = ShipHull(
    LWL=60.0, B=12.0, T=4.0,
    displacement_t=800.0,
    Cb=0.72, Cp=0.74, Cm=0.99,
    LCB_from_midship_m=1.5,
)
report: ResistanceReport = holtrop_mennen_resistance(hull, velocity_m_s=6.17)  # 12 kn
print(f"Total resistance: {report.Rt_N/1000:.1f} kN")
print(f"Effective power: {report.PE_kW:.1f} kW")

# JONSWAP wave spectrum
import numpy as np
omega = np.linspace(0.3, 2.0, 100)
S = jonswap_spectrum(omega, Hs=3.0, Tp=10.0, gamma=3.3)
```

### From an LLM tool spec

```json
{"tool": "cfd_marine_resistance", "LWL_m": 60, "B_m": 12, "T_m": 4,
 "displacement_t": 800, "Cb": 0.72, "speed_kn": 12}
```

## How it works

Holtrop-Mennen decomposes total resistance into: frictional (ITTC 1957 line: Cf = 0.075/(log₁₀Re - 2)²), form factor k₁ (hull form correction), residuary resistance Rr (polynomial regression on Froude number and hull form coefficients), and appendage drag. The method was calibrated against 334 model tests covering Froude numbers 0.1–0.9.

JONSWAP spectrum: S(ω) = (αg²/ω⁵) exp(-1.25(ω_p/ω)⁴) γ^exp(-(ω-ω_p)²/(2σ²ω_p²)), where γ=3.3 is the peak enhancement factor for developing sea states.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `holtrop_mennen_resistance(hull, velocity_m_s)` | `ResistanceReport` | Total resistance prediction |
| `jonswap_spectrum(omega, Hs, Tp, gamma)` | `np.ndarray` | Wave energy spectrum |
| `linear_wave_diffraction_force(R, omega, Hs, rho, h)` | `dict` | Inertia + drag force on cylinder |

`ResistanceReport` fields: `Rt_N`, `Rf_N`, `Rr_N`, `Ra_N`, `PE_kW`, `Fn`, `Re`.

## Example

```python
report = holtrop_mennen_resistance(hull, velocity_m_s=6.17)
print(f"Froude number: {report.Fn:.3f}")
print(f"Power: {report.PE_kW:.0f} kW at 12 knots")
```

## Honest caveats

Holtrop-Mennen is a statistical regression method — accuracy is ±5-10% for hulls within the regression database (conventional monohulls). It is not valid for high-speed planing craft (Fn > 0.6), catamarans, or unusual hull forms. Wave diffraction forces are computed for a vertical circular cylinder (Morison equation) — complex platform geometries require panel methods or CFD. Seakeeping (RAOs) requires a strip theory or 3D panel code.

## References

- Holtrop & Mennen (1984). "An approximate power prediction method." *International Shipbuilding Progress* 29(335).
- ITTC (1957). "Skin friction and turbulence stimulation." *Proceedings 8th ITTC*.
- Hasselmann et al. (1973). "Measurements of wind-wave growth and swell decay during the Joint North Sea Wave Project (JONSWAP)." *Ergnzungsheft Deutschen Hydrographischen Zeitschrift* A(8).
