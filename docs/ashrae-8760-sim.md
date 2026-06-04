# ASHRAE 8760-Hour Annual Energy Simulation

> Hourly clear-sky irradiance and solar position across all 8760 hours of a typical meteorological year for building energy modelling.

**Module**: `packages/kerf-energy/src/kerf_energy/solar.py`
**Shipped**: Wave 9D1
**LLM tools**: `energy_solar_position`, `energy_clear_sky_irradiance`

---

## What it is

Annual energy simulation requires solar position and irradiance for every hour of the year (8760 hours for a non-leap year). Clear-sky models provide the upper-bound beam and diffuse irradiance that a climate-based simulation scales against measured weather data (TMY/EPW files). This module implements the Spencer (1971) Fourier series for solar geometry and the ASHRAE clear-sky model (Ch. 14 HOF 2021), giving the data backbone for 8760-hour runs.

## How to use it

### From chat

> "Generate hourly solar altitude and direct normal irradiance for Los Angeles (34°N, 118°W) for the entire year. What is the peak DNI month?"

### From Python

```python
from kerf_energy.solar import solar_position, clear_sky_irradiance
from datetime import date

lat, lon = 34.05, -118.24  # Los Angeles
month_max_dni = 0
max_month = 1
for month in range(1, 13):
    day = date(2024, month, 15)
    pos = solar_position(lat, lon, day, hour_utc=12)
    irr = clear_sky_irradiance(lat, day, hour_solar=12)
    if irr.DNI > month_max_dni:
        month_max_dni = irr.DNI
        max_month = month
print(f"Peak DNI month: {max_month}, DNI: {month_max_dni:.0f} W/m²")
```

### From an LLM tool spec

```json
{"latitude_deg": 34.05, "longitude_deg": -118.24,
 "year": 2024, "output": "8760_hourly_summary"}
```

## How it works

Solar declination: Spencer (1971) Fourier series with day-of-year angle B = 2π(n−1)/365. Equation of time from the same series. Solar hour angle: ω = 15°×(solar_time − 12). Solar altitude: sin(α) = sin(φ)sin(δ) + cos(φ)cos(δ)cos(ω). ASHRAE clear-sky DNI: I_b = I_o × exp(−τ_b × m^a_b) where τ_b and a_b are ASHRAE Tau-model coefficients for the location. Diffuse horizontal: I_d = I_o × exp(−τ_d × m^a_d). Air mass: m = 1/sin(α) (Kasten-Young correction for low angles).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `solar_position(lat, lon, day, hour_utc)` | `dict` | Altitude, azimuth, hour angle |
| `clear_sky_irradiance(lat, day, hour_solar)` | `ClearSkyIrradiance` | DNI, DHI, GHI (W/m²) |
| `direct_normal_irradiance_ashrae(day, hour_solar)` | `float` | DNI (W/m²) |
| `diffuse_horizontal_irradiance_ashrae(day, hour_solar)` | `float` | DHI (W/m²) |

`ClearSkyIrradiance` fields: `DNI`, `DHI`, `GHI`, `altitude_deg`, `azimuth_deg`.

## Example

```python
from kerf_energy.solar import clear_sky_irradiance
from datetime import date

irr = clear_sky_irradiance(lat=51.5, day=date(2024, 6, 21), hour_solar=12)
print(f"London summer solstice noon: DNI={irr.DNI:.0f}, GHI={irr.GHI:.0f} W/m²")
```

## Honest caveats

This module generates clear-sky (cloud-free) irradiance only. For energy compliance calculations (ASHRAE 90.1, Title 24), observed hourly data from a TMY3/TMY file (NSRDB, EnergyPlus EPW) must be used. The ASHRAE Tau coefficients are not location-specific in this release — default temperate-climate values are used; replace with ASHRAE Climate Design Data for your site.

## References

- Spencer, J.N. (1971). Fourier series representation of the position of the sun. *Search* 2(5), 172.
- ASHRAE (2021). *Handbook of Fundamentals*, Ch. 14 — Climatic Design Information.
- Iqbal, M. (1983). *An Introduction to Solar Radiation*. Academic Press. §3.
