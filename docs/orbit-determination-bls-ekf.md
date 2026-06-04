# Orbit Determination — Batch Least Squares and EKF

> Determine initial orbit state from ground-station angle/range observations using BLS or EKF.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/aerospace/orbit_determination.py`
**Shipped**: Wave 10C2
**LLM tools**: `aerospace_batch_od`, `aerospace_ekf_od`

---

## What it is

Orbit determination (OD) computes the best-estimate initial state vector (position and velocity) that is consistent with a set of ground-station observations (azimuth, elevation, range). Two methods are implemented: Batch Least Squares (BLS), which solves the entire observation arc simultaneously as a weighted least-squares problem, and the Extended Kalman Filter (EKF), which processes observations sequentially and propagates a state covariance matrix.

## How to use it

### From chat

> "Determine the orbit of a LEO satellite from 12 radar observations over 3 ground passes."

### From Python

```python
from kerf_cad_core.aerospace.orbit_determination import (
    GroundStationObservation, batch_least_squares_od,
    extended_kalman_filter_od,
)

obs = [
    GroundStationObservation(
        epoch_iso="2025-06-01T00:10:00Z",
        station_lat_deg=-26.2, station_lon_deg=28.0, station_alt_m=1750,
        az_deg=45.0, el_deg=32.0, range_km=850.0,
    ),
    # ... more observations
]
od_result = batch_least_squares_od(
    observations=obs,
    x0_guess=initial_state_guess,  # [x, y, z, vx, vy, vz] in ECI, m and m/s
    sigma_angle_arcsec=30.0,
    sigma_range_km=0.1,
)
print(od_result.state_eci, od_result.covariance_3sigma)
```

### From an LLM tool spec

```json
{"tool": "aerospace_batch_od", "input": {"observations": [...], "sigma_angle_arcsec": 30, "sigma_range_km": 0.1}}
```

## How it works

BLS linearises the observation model `y = h(x)` around a reference trajectory and solves the normal equations `(HᵀWH) Δx = HᵀW Δy` iteratively (differential correction) until the update norm is below the convergence threshold. The Jacobian `H = ∂h/∂x` is computed by numerical differentiation of the propagated state. EKF propagates the state and covariance matrix between observations using the state transition matrix (STM), then applies the Kalman measurement update at each observation.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `batch_least_squares_od(observations, x0_guess, sigma_angle, sigma_range)` | `ODReport` | BLS orbit determination |
| `extended_kalman_filter_od(observations, x0_mean, P0, process_noise)` | `ODReport` | EKF sequential OD |
| `generate_synthetic_observations(true_state, stations, t_span)` | `list` | Simulate synthetic obs for testing |

## Example

```python
result = batch_least_squares_od(obs, x0, sigma_angle_arcsec=30.0)
# ODReport(state_eci=[...], rms_residual_arcsec=12.4,
#           converged=True, iterations=4)
```

## Honest caveats

BLS convergence depends on the quality of the initial state guess; a poor guess may not converge or may converge to a wrong solution. The propagator is a Keplerian RK4 — J2 and drag are not included by default, which degrades OD accuracy for LEO arcs longer than ~1 orbit. Radar biases (tropospheric refraction, clock errors) are not modelled. The EKF may diverge for highly nonlinear dynamics without careful process-noise tuning.

## References

- Tapley, Schutz & Born, *Statistical Orbit Determination*, Elsevier (2004), Ch. 3–4.
- Vallado, *Fundamentals of Astrodynamics and Applications*, 4th ed. (2013), Ch. 7.
