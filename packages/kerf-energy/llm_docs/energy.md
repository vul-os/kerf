# Energy / Daylight / Acoustic analysis (`kerf-energy`)

`kerf-energy` provides building-physics analysis tools for zone heating and
cooling loads, daylighting, reverberation, and solar geometry.  All
computations are pure Python (no heavy native dependencies).

---

## Tools

### `energy_heat_load`

Estimates the peak cooling load for a zone using the **ASHRAE CLTD/CLF method**
(Cooling-Load Temperature-Difference / Cooling-Load Factor).

**Input**

```json
{
  "walls": [
    { "area_m2": 30, "u_value_w_m2_k": 0.35, "facing": "south" }
  ],
  "glazing": [
    { "area_m2": 5, "u_value_w_m2_k": 1.8, "shgc": 0.4, "facing": "south" }
  ],
  "num_people": 10,
  "lighting_w": 800,
  "equipment_w": 500
}
```

All arrays are optional.  `facing` defaults to `"south"`.

**Output**

```json
{
  "peak_sensible_w": 4320.5,
  "latent_w": 550.0,
  "total_cooling_w": 4870.5,
  "peak_hour": 15,
  "method": "ASHRAE CLTD/CLF"
}
```

- `peak_hour` is the hour of day (1–24) at which peak sensible load occurs.
- Latent load covers occupancy moisture + ventilation.

---

### `energy_daylight`

Estimates the **mean Daylight Factor** (%) using the BRS **split-flux method**
(BS 8206-2 / IES LM-83).

Formula:
```
DF = (τ · A_w · θ) / (6 · A_floor · (1 − ρ̄²)) × 100 %
```
where τ = glazing transmittance, A_w = window area, θ = sky-component
fraction (obstruction factor), A_floor = room floor area, ρ̄ = mean
surface reflectance.

**Input**

```json
{
  "window_area_m2": 4.0,
  "room_floor_area_m2": 20.0,
  "tau": 0.6,
  "sky_component_fraction": 0.4,
  "average_reflectance": 0.5,
  "space_type": "office"
}
```

`tau`, `sky_component_fraction`, `average_reflectance`, and `space_type` are
optional.

**Output**

```json
{
  "daylight_factor_percent": 1.0667,
  "window_area_m2": 4.0,
  "room_floor_area_m2": 20.0,
  "method": "BS8206-2 split-flux",
  "bs8206_compliance": {
    "compliant": false,
    "target": 2.0,
    "actual": 1.0667,
    "margin": -0.9333
  }
}
```

BS 8206-2 target DF values by space type:

| Space type   | Target DF (%) |
|--------------|:-------------:|
| kitchen      | 2.0           |
| living_room  | 1.5           |
| bedroom      | 1.0           |
| office       | 2.0           |
| classroom    | 2.0           |
| corridor     | 0.5           |

---

### `energy_rt60`

Calculates **Sabine reverberation time** RT60.

```
RT60 = 0.161 · V / A   (seconds)
```

where V = room volume (m³) and A = total acoustic absorption (metric Sabines, m²).
A = Σ(area_i × absorption_coefficient_i) over all surfaces.

**Input**

```json
{
  "volume_m3": 1000,
  "total_absorption_sabines": 200
}
```

**Output**

```json
{
  "rt60_seconds": 0.805,
  "volume_m3": 1000,
  "total_absorption_sabines": 200,
  "method": "Sabine"
}
```

Typical RT60 targets:
- Speech intelligibility (office/classroom): 0.4–0.8 s
- Live music (concert hall): 1.5–2.5 s
- Recording studio (dry): 0.2–0.4 s

---

### `energy_solar`

Computes **solar geometry and ASHRAE clear-sky irradiance** for a site.

**Input**

```json
{
  "latitude_deg": -33.92,
  "longitude_deg": 18.42,
  "day_of_year": 172,
  "solar_time_hours": 12.0
}
```

`solar_time_hours` is apparent solar time (decimal hours, 0–24).

**Output**

```json
{
  "solar_altitude_deg": 79.6,
  "solar_azimuth_deg": 0.0,
  "solar_declination_deg": 23.45,
  "hour_angle_deg": 0.0,
  "direct_normal_irradiance_w_m2": 893.5,
  "diffuse_horizontal_irradiance_w_m2": 122.7,
  "global_horizontal_irradiance_w_m2": 1001.5,
  "day_of_year": 172,
  "method": "ASHRAE clear-sky"
}
```

- `solar_altitude_deg` is the angle above the horizontal plane (0–90°).
- `solar_azimuth_deg` is measured clockwise from north (0–360°).
- DNI = direct normal irradiance; DHI = diffuse horizontal; GHI = global horizontal.

---

## Python API

```python
from kerf_energy.acoustic import rt60_sabine, Surface, total_absorption
from kerf_energy.daylight import daylight_factor_split_flux, check_bs8206_compliance
from kerf_energy.solar import (
    solar_noon_altitude_deg,
    clear_sky_irradiance,
    solar_declination_deg,
)
from kerf_energy.heat_load import ZoneHeatLoad, WallElement, GlazingElement, OccupancyLoad

# Sabine RT60
rt60 = rt60_sabine(volume_m3=1000, total_absorption_sabines=200)  # 0.805 s

# Daylight factor
df = daylight_factor_split_flux(window_area_m2=4, room_floor_area_m2=20)

# Solar noon altitude at equator on equinox
alt = solar_noon_altitude_deg(latitude_deg=0.0, doy=80)  # ≈ 89.93°

# CLTD zone heat load
zone = ZoneHeatLoad()
zone.walls.append(WallElement(area_m2=30, u_value_w_m2_k=0.35))
zone.occupancy.append(OccupancyLoad(num_people=10))
peak_w = zone.peak_sensible_w()
```

---

## Methods and references

| Module        | Method                              | Standard / Reference         |
|---------------|-------------------------------------|------------------------------|
| `acoustic.py` | Sabine RT60 = 0.161·V/A             | Sabine (1900); ASHRAE HOF Ch.8 |
| `acoustic.py` | STC rating                          | ASTM E413-16                 |
| `daylight.py` | BRS split-flux mean DF              | BS 8206-2:2008; IES LM-83-12 |
| `solar.py`    | Spencer declination + EoT           | Spencer (1971)               |
| `solar.py`    | ASHRAE clear-sky DNI/DHI            | ASHRAE HOF 2021, Ch. 15      |
| `heat_load.py`| CLTD/CLF cooling load               | ASHRAE HOF 2021, Ch. 18      |
| `heat_load.py`| UA·ΔT heating load                  | ASHRAE HOF 2021, Ch. 18      |
