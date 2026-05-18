# kerf-aero LLM Tool Surface

12 aerospace simulation tools exposed as LLM-callable functions.  Each tool
accepts plain scalar/list arguments and returns a JSON-serializable dict.

---

## aero_airfoil_coords

Return chord-normalised (x, y) surface coordinates for a named airfoil.

**Arguments**
| Name | Type | Description |
|------|------|-------------|
| `name` | str | Airfoil identifier: NACA 4-digit (`"naca0012"`, `"2412"`), NACA 5-digit (`"naca23012"`), or Selig slug (`"e387"`, `"s1223"`, `"clarky"`) |

**Returns** `{name, n_points, coords: [[x,y],...], source}`

**Example**
```python
aero_airfoil_coords("naca0012")
# {"name": "naca0012", "n_points": 399, "coords": [[1.0, 0.0], ...], "source": "NACA 4-digit analytic (TR-460)"}
```

**Raises** `ValueError` if airfoil name is not recognised.

---

## aero_airfoil_polar

CL vs alpha sweep using the 2D linear-vortex panel method (XFOIL class).

**Arguments**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `name` | str | — | Airfoil identifier (same as `aero_airfoil_coords`) |
| `alpha_min` | float | -5.0 | Minimum angle of attack [deg] |
| `alpha_max` | float | 15.0 | Maximum angle of attack [deg] |
| `step` | float | 1.0 | Alpha increment [deg] (>= 0.1) |

**Returns** `{name, alpha: [...], CL: [...], CD_wave: [...], alpha_L0, CL_alpha, method}`

**Example**
```python
aero_airfoil_polar("naca2412", -4, 10, 2)
# {"name": "naca2412", "alpha": [-4, -2, 0, 2, 4, 6, 8, 10], "CL": [...], "CL_alpha": 0.1059}
```

**Raises** `ValueError` on bad step, invalid alpha range, or unknown airfoil.

---

## aero_vlm_wing

Finite-wing steady aerodynamics via the Vortex Lattice Method (Katz & Plotkin §13).

**Arguments**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `span` | float | — | Full wing span [m] (> 0) |
| `root_chord` | float | — | Root chord [m] (> 0) |
| `tip_chord` | float\|None | None | Tip chord [m]; None = rectangular |
| `sweep_deg` | float | 0.0 | Leading-edge sweep angle [deg] |
| `alpha_deg` | float | 5.0 | Angle of attack [deg] |

**Returns** `{ok, CL, CDi, Cm, AR, span_efficiency, S_ref, n_panels, inputs}`

**Example**
```python
aero_vlm_wing(span=10.0, root_chord=1.5, tip_chord=0.8, sweep_deg=20.0, alpha_deg=5.0)
# {"CL": 0.411, "CDi": 0.0057, "Cm": -0.131, "AR": 7.94, "span_efficiency": 0.924}
```

**Raises** `ValueError` on non-positive span, root_chord, or negative tip_chord.

---

## aero_orbital_elements_to_state

Convert classical Keplerian elements to an ECI Cartesian state vector.

**Arguments**
| Name | Type | Description |
|------|------|-------------|
| `a` | float | Semi-major axis [km] (> 0) |
| `e` | float | Eccentricity [0, 1) |
| `i` | float | Inclination [deg] |
| `raan` | float | Right ascension of ascending node Ω [deg] |
| `argp` | float | Argument of periapsis ω [deg] |
| `true_anomaly` | float | True anomaly ν [deg] |
| `mu` | float\|None | Gravitational parameter [km³/s²]; default Earth |

**Returns** `{ok, position_km: [x,y,z], velocity_km_s: [vx,vy,vz], radius_km, speed_km_s, altitude_km, orbital_period_s}`

**Example**
```python
aero_orbital_elements_to_state(a=6778, e=0.001, i=51.6, raan=0, argp=0, true_anomaly=0)
# {"position_km": [6771.3, 0.0, 0.0], "velocity_km_s": [0.0, 7.673, 0.0], "altitude_km": 400.3}
```

**Raises** `ValueError` if `a <= 0` or `e` is outside [0, 1).

---

## aero_hohmann_transfer

Two-burn Hohmann ΔV between two circular orbits.

**Arguments**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `r1` | float | — | Initial orbit radius [km] (> 0) |
| `r2` | float | — | Final orbit radius [km] (> 0) |
| `mu` | float\|None | None | Gravitational parameter [km³/s²]; default Earth |

**Returns** `{ok, dv1_km_s, dv2_km_s, dv_total_km_s, tof_s, tof_min, a_transfer_km, r_ratio}`

**Example**
```python
aero_hohmann_transfer(r1=6778, r2=42164)  # LEO → GEO
# {"dv_total_km_s": 3.935, "tof_min": 317.5, "a_transfer_km": 24471.0}
```

**Raises** `ValueError` if `r1 <= 0` or `r2 <= 0`.

---

## aero_lambert_solve

Solve Lambert's problem via the universal-variable (BMW) method.  Returns the
velocity vectors that connect two positions in a specified time of flight.

**Arguments**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `r1` | [x,y,z] | — | Initial position [km] |
| `r2` | [x,y,z] | — | Final position [km] |
| `tof` | float | — | Time of flight [s] (> 0) |
| `mu` | float\|None | None | Gravitational parameter; default Earth |
| `prograde` | bool | True | Assume prograde transfer |

**Returns** `{ok, v1_km_s: [vx,vy,vz], v2_km_s: [vx,vy,vz], dv1_km_s, dv2_km_s, tof_s}`

**Example**
```python
aero_lambert_solve([7000,0,0], [0,7000,0], tof=3600)
# {"v1_km_s": [-0.12, 7.52, 0.0], "v2_km_s": [-7.52, 0.12, 0.0]}
```

**Raises** `ValueError` if r1/r2 are not length-3, tof ≤ 0, or positions are collinear.

---

## aero_rocket_dv

Tsiolkovsky rocket equation: ΔV = Isp · g₀ · ln(m₀/mf).

**Arguments**
| Name | Type | Description |
|------|------|-------------|
| `mass_ratio` | float | Initial-to-final mass ratio m₀/mf (>= 1.0) |
| `isp` | float | Specific impulse [s] (> 0) |

**Returns** `{ok, delta_v_m_s, delta_v_km_s, ve_m_s, propellant_fraction, isp, mass_ratio}`

**Example**
```python
aero_rocket_dv(mass_ratio=4.0, isp=350)
# {"delta_v_m_s": 4764.3, "delta_v_km_s": 4.764, "propellant_fraction": 0.75}
```

**Raises** `ValueError` if mass_ratio < 1.0 or isp ≤ 0.

---

## aero_cea_lite

Simplified NASA CEA for canonical bipropellants.  Fits within ±3% of full CEA
for LOX/RP-1, LOX/LH2, N2O4/MMH, LOX/CH4.

**Arguments**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `propellant` | str | — | Propellant name or combined `"LOX/RP-1"` |
| `oxidizer` | str\|None | None | Oxidizer name (if propellant is just fuel) |
| `of_ratio` | float | 2.3 | Oxidizer-to-fuel mass ratio |
| `chamber_pressure` | float | 70.0 | Chamber pressure [bar] |

**Supported pairs:** `LOX/RP-1`, `LOX/LH2`, `N2O4/MMH`, `LOX/CH4`

**Returns** `{ok, propellant, tc_k, gamma, c_star_m_s, isp_vac_s, isp_sl_s, pe_over_pc, within_of_range}`

**Example**
```python
aero_cea_lite("LOX/RP-1", of_ratio=2.3, chamber_pressure=70)
# {"tc_k": 3571, "isp_vac_s": 350.2, "c_star_m_s": 1789, "gamma": 1.136}
```

**Raises** `ValueError` on unknown propellant, of_ratio ≤ 0, or chamber_pressure ≤ 0.

---

## aero_atmosphere

U.S. Standard Atmosphere 1976: temperature, pressure, density, speed of sound,
dynamic viscosity from 0 to 86 km altitude.

**Arguments**
| Name | Type | Description |
|------|------|-------------|
| `altitude_km` | float | Geometric altitude [km] (0–86) |

**Returns** `{ok, altitude_km, temperature_k, pressure_pa, pressure_hpa, density_kg_m3, speed_of_sound_m_s, viscosity_pa_s, layer}`

**Example**
```python
aero_atmosphere(10.0)
# {"temperature_k": 223.25, "pressure_hpa": 265.0, "density_kg_m3": 0.4135, "layer": "Tropopause"}
```

**Raises** `ValueError` if altitude < 0 or > 86 km.

---

## aero_attitude_propagate

Propagate spacecraft attitude dynamics (Euler's rotation equation + quaternion
kinematics) using a 4th-order Runge-Kutta integrator.

**Arguments**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `quaternion` | [w,x,y,z] | — | Initial unit quaternion (normalised internally) |
| `omega_body` | [wx,wy,wz] | — | Initial body angular velocity [rad/s] |
| `duration` | float | — | Simulation duration [s] (> 0) |
| `dt` | float | 0.1 | Integration time step [s] (>= 0.001) |
| `inertia` | 3×3 list\|None | None | Body inertia tensor [kg·m²]; default I₃×₃ |
| `torque` | [Tx,Ty,Tz]\|None | None | Constant body torque [N·m]; default zero |

**Limit:** duration/dt ≤ 10000 steps to bound computation time.

**Returns** `{ok, q_initial, q_final, omega_final, euler_final_deg: [roll,pitch,yaw], n_steps, duration_s}`

**Example**
```python
aero_attitude_propagate([1,0,0,0], [0.1, 0.05, 0.0], duration=10.0)
# {"q_final": [0.878, 0.434, 0.186, 0.0], "euler_final_deg": [49.8, 21.4, 0.0]}
```

**Raises** `ValueError` on wrong vector lengths, zero duration, dt too small, or too many steps.

---

## aero_thermal_steady_state

Solve a lumped-parameter thermal resistance network for steady-state temperatures
via Newton-Raphson iteration (handles conductive and radiative links).

**Arguments**
| Name | Type | Description |
|------|------|-------------|
| `nodes_json` | list[dict] | Node list: `{node_id, T [K], Q_ext [W]=0, fixed=False, C=1}` |
| `links_json` | list[dict] | Link list: type=`"conductive"` or `"radiative"` with associated parameters |

**Conductive link fields:** `type, node_a, node_b, conductance [W/K]`

**Radiative link fields:** `type, node_a, node_b, epsilon_eff, area [m²], view_factor`

**Returns** `{ok, converged, temperatures: {node_id: T_K}, heat_flows: {node_id: Q_W}}`

**Example**
```python
nodes = [{"node_id": "panel", "T": 300, "Q_ext": 100},
         {"node_id": "space", "T": 3,   "fixed": True}]
links = [{"type": "radiative", "node_a": "panel", "node_b": "space",
          "epsilon_eff": 0.85, "area": 1.0, "view_factor": 1.0}]
aero_thermal_steady_state(nodes, links)
# {"converged": true, "temperatures": {"panel": 393.4, "space": 3.0}}
```

**Raises** `ValueError` on missing fields, unknown node IDs, or unknown link type.

---

## aero_material_lookup

Look up aerospace material properties from the built-in database.

**Arguments**
| Name | Type | Description |
|------|------|-------------|
| `name` | str | Material slug or alias (case-insensitive) |

**Available materials** (slugs):
`al2024-t3`, `al6061-t6`, `al7075-t6`, `ti-6al-4v`, `4340-steel`,
`cfrp-ud-t300`, `cfrp-woven-t300`, `gfrp-e-glass`, `inconel-718`, `rene-41`,
`sic-cmc`, `ablator-pica`, `kapton-h`

**Aliases:** `titanium`, `cfrp`, `gfrp`, `inconel`, `pica`, `kapton`, `al7075`, `7075`, etc.

**Returns** `{ok, slug, name, category, density_kg_m3, youngs_modulus_gpa, yield_strength_mpa, uts_mpa, thermal_conductivity_w_mk, specific_heat_j_kgk, cte_per_k, poisson, max_service_temp_c, uses}`

**Example**
```python
aero_material_lookup("al7075")
# {"name": "Aluminium 7075-T6", "density_kg_m3": 2810, "yield_strength_mpa": 503, "uts_mpa": 572}
```

**Raises** `ValueError` listing all available slugs if material not found.

---

## Tool Registry

All tools are collected in `AEROSPACE_TOOLS: list[dict]` with keys
`{name, fn, description}`, suitable for programmatic registration with any
LLM tool-calling framework.

```python
from kerf_aero.llm_tools import AEROSPACE_TOOLS

for tool in AEROSPACE_TOOLS:
    print(tool["name"], "—", tool["description"])
```

---

## References

- Katz & Plotkin, *Low-Speed Aerodynamics*, 2nd ed., Cambridge UP 2001
- Bate, Mueller & White, *Fundamentals of Astrodynamics*, Dover 1971
- Sutton & Biblarz, *Rocket Propulsion Elements*, 9th ed., Wiley 2016
- Gordon & McBride, NASA RP-1311 (1994) — CEA database
- NOAA/NASA/USAF, *U.S. Standard Atmosphere 1976*
- Gilmore (ed.), *Spacecraft Thermal Control Handbook*, 2nd ed., Aerospace Press 2002
