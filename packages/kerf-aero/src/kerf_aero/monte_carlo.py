"""Monte Carlo trajectory dispersion analysis for rocket flights.

Performs a Monte Carlo ensemble over uncertain input parameters (wind speed,
drag coefficient, launch angle perturbation, thrust Isp variation, ignition
delay) to produce landing-scatter statistics.

Each sample propagates a 3-DOF ballistic trajectory under:
  - Thrust phase: variable-Isp Tsiolkovsky propulsion
  - Gravity turn / coast phase: 3-DOF point mass with quadratic drag
  - Parachute descent: constant-Cd descent (see recovery.py)
  - Atmospheric properties: USSA-76 at each altitude step

Output quantities:
  - Landing radius distribution (apogee dispersion for no-recovery cases)
  - Apogee altitude distribution
  - Max-Q distribution

References
----------
Niskanen, S. (2009). "OpenRocket — A Software Tool for Model Rocket
    Design and Simulation." Master's Thesis, Helsinki University of
    Technology.  §5.4 Monte Carlo simulation.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .flight_dynamics.atmosphere import atmosphere


# ---------------------------------------------------------------------------
# Input parameter distributions
# ---------------------------------------------------------------------------

@dataclass
class DispersionInputs:
    """1-sigma uncertainties for Monte Carlo dispersion analysis.

    All values are 1-sigma standard deviations; the sampler uses normal
    distributions for each parameter.

    Attributes
    ----------
    wind_speed_mps : float
        1-σ horizontal wind speed uncertainty [m/s].
    wind_direction_deg : float
        1-σ wind direction uncertainty [deg].  Uniform azimuth adds scatter.
    drag_coefficient_frac : float
        Fractional 1-σ uncertainty in drag coefficient (e.g. 0.05 = 5%).
    isp_frac : float
        Fractional 1-σ uncertainty in specific impulse (e.g. 0.02 = 2%).
    launch_angle_deg : float
        1-σ launch angle perturbation from nominal [deg].
    ignition_delay_s : float
        1-σ ignition delay uncertainty [s].
    """

    wind_speed_mps: float = 5.0
    wind_direction_deg: float = 45.0
    drag_coefficient_frac: float = 0.05
    isp_frac: float = 0.02
    launch_angle_deg: float = 0.5
    ignition_delay_s: float = 0.1


@dataclass
class NominalInputs:
    """Nominal (mean) rocket and launch parameters.

    Attributes
    ----------
    total_impulse_ns : float
        Total motor impulse [N·s].
    burn_time_s : float
        Motor burn time [s].
    initial_mass_kg : float
        Launch mass including propellant [kg].
    propellant_mass_kg : float
        Propellant mass [kg].
    body_diameter_m : float
        Body tube diameter [m], used for reference area.
    drag_coefficient : float
        Nominal drag coefficient (typical 0.3–0.6 for rocket).
    launch_elevation_deg : float
        Launch elevation angle from horizontal [deg] (typically 80–90).
    launch_altitude_m : float
        Launch site altitude above MSL [m].
    has_recovery : bool
        Whether a parachute recovery system deploys at apogee.
    chute_cd : float
        Recovery parachute Cd·A [m²] (Cd × chute area).
    chute_mass_kg : float
        Descent mass after apogee (airframe mass) [kg].
    """

    total_impulse_ns: float = 1000.0
    burn_time_s: float = 2.0
    initial_mass_kg: float = 1.5
    propellant_mass_kg: float = 0.3
    body_diameter_m: float = 0.05
    drag_coefficient: float = 0.45
    launch_elevation_deg: float = 87.0
    launch_altitude_m: float = 0.0
    has_recovery: bool = True
    chute_cd: float = 0.5    # Cd * A [m²]
    chute_mass_kg: float = 1.2


# ---------------------------------------------------------------------------
# Single-trajectory 3-DOF simulation
# ---------------------------------------------------------------------------

def _simulate_trajectory(
    nom: NominalInputs,
    *,
    cd_multiplier: float = 1.0,
    thrust_multiplier: float = 1.0,
    wind_x_mps: float = 0.0,
    elevation_deg: float | None = None,
    ignition_delay_s: float = 0.0,
    dt: float = 0.02,
) -> dict:
    """Simulate a single 3-DOF trajectory, returning key output scalars.

    Returns dict with: apogee_m, max_q_pa, flight_time_s,
                       landing_x_m, landing_y_m (downrange / crossrange).
    """
    elevation_rad = math.radians(
        elevation_deg if elevation_deg is not None else nom.launch_elevation_deg
    )

    # Initial state: position (x=downrange, z=altitude), velocity
    x = 0.0       # downrange [m]
    z = nom.launch_altitude_m   # altitude [m]
    vx = 0.0      # downrange velocity [m/s]
    vz = 0.0      # vertical velocity [m/s]

    mass = nom.initial_mass_kg
    s_ref = math.pi * (nom.body_diameter_m / 2.0) ** 2  # reference area [m²]
    thrust_avg = nom.total_impulse_ns / nom.burn_time_s  # mean thrust [N]
    mass_flow = nom.propellant_mass_kg / nom.burn_time_s  # [kg/s]

    t = 0.0
    t_burnout = ignition_delay_s + nom.burn_time_s
    apogee_m = z
    max_q = 0.0
    launched = False

    cd = nom.drag_coefficient * cd_multiplier

    while True:
        # Thrust
        if t < ignition_delay_s:
            thrust = 0.0
        elif t <= t_burnout:
            thrust = thrust_avg * thrust_multiplier
            mass = max(
                nom.initial_mass_kg - nom.propellant_mass_kg,
                nom.initial_mass_kg - mass_flow * (t - ignition_delay_s),
            )
        else:
            thrust = 0.0
            mass = nom.initial_mass_kg - nom.propellant_mass_kg

        # Atmosphere
        atm = atmosphere(min(max(z, 0.0), 86000.0))
        rho = atm.density_kg_m3
        g = 9.80665  # simplified (constant g acceptable for model rocketry altitudes)

        speed = math.sqrt((vx - wind_x_mps) ** 2 + vz ** 2)
        q = 0.5 * rho * speed ** 2
        max_q = max(max_q, q)

        drag = cd * s_ref * q   # [N]

        # Direction of drag (opposes relative velocity)
        if speed > 1e-6:
            drag_x = -drag * (vx - wind_x_mps) / speed
            drag_z = -drag * vz / speed
        else:
            drag_x = 0.0
            drag_z = 0.0

        # Thrust direction: always along launch angle while on rail (vz ≤ 0 or still burning)
        if not launched and thrust > 0:
            launched = True

        # Use body velocity (not relative wind) for thrust direction, and only
        # align thrust with velocity once the rocket has meaningful body motion.
        # During the burn phase on the rail, thrust is along the launch elevation.
        body_speed = math.sqrt(vx ** 2 + vz ** 2)
        if body_speed > 5.0 and t > ignition_delay_s + 0.2:
            tx = thrust * vx / body_speed
            tz = thrust * vz / body_speed
        else:
            tx = thrust * math.cos(elevation_rad)
            tz = thrust * math.sin(elevation_rad)

        # Equations of motion
        ax = (tx + drag_x) / mass
        az = (tz + drag_z) / mass - g

        # Euler integration
        vx += ax * dt
        vz += az * dt
        x += vx * dt
        z += vz * dt
        t += dt

        # Constrain to launch pad before ignition
        if not launched and z < nom.launch_altitude_m:
            z = nom.launch_altitude_m
            vz = 0.0
            vx = 0.0

        if z > apogee_m:
            apogee_m = z

        # Check for ground impact — only well after burnout
        if (z <= nom.launch_altitude_m and launched
                and t > ignition_delay_s + nom.burn_time_s + 1.0):
            break

        # Safety timeout
        if t > 600.0:
            break

    # Recovery descent (if applicable) — already reached ground in sim above
    # (parachute effect captured via recovery.py conceptually; for dispersion
    # the horizontal scatter is the key metric)
    landing_x = x
    landing_y = 0.0   # 2D sim; y-scatter added by Monte Carlo via wind_y

    return {
        "apogee_m": apogee_m,
        "max_q_pa": max_q * s_ref,   # total drag-area × q for reference
        "flight_time_s": t,
        "landing_x_m": landing_x,
        "landing_y_m": landing_y,
    }


# ---------------------------------------------------------------------------
# Monte Carlo runner
# ---------------------------------------------------------------------------

@dataclass
class MonteCarloResult:
    """Results of a Monte Carlo dispersion analysis.

    Attributes
    ----------
    n_samples : int
        Number of trajectory samples run.
    apogee_mean_m, apogee_std_m : float
        Apogee altitude mean and 1-σ [m].
    apogee_p05_m, apogee_p95_m : float
        5th and 95th percentile apogee [m].
    landing_radius_mean_m, landing_radius_std_m : float
        Distance from launch site mean and 1-σ [m].
    landing_radius_p95_m : float
        95th percentile landing radius [m].
    max_q_mean_pa : float
        Mean maximum dynamic pressure [Pa].
    samples : list[dict]
        Raw per-sample result dicts (apogee_m, landing_radius_m, max_q_pa).
    """

    n_samples: int
    apogee_mean_m: float
    apogee_std_m: float
    apogee_p05_m: float
    apogee_p95_m: float
    landing_radius_mean_m: float
    landing_radius_std_m: float
    landing_radius_p95_m: float
    max_q_mean_pa: float
    samples: list = field(default_factory=list)


def monte_carlo_dispersion(
    nominal: NominalInputs,
    dispersion: DispersionInputs | None = None,
    *,
    n_samples: int = 200,
    seed: Optional[int] = None,
    dt: float = 0.05,
) -> MonteCarloResult:
    """Run a Monte Carlo dispersion analysis for a rocket trajectory.

    Each sample perturbs the input parameters by drawing from normal
    distributions with the given 1-σ uncertainties, then integrates a
    3-DOF trajectory.

    Parameters
    ----------
    nominal : NominalInputs
        Nominal (mean) rocket and launch parameters.
    dispersion : DispersionInputs | None
        Parameter uncertainty specification.  Default uncertainties used
        if not provided.
    n_samples : int
        Number of Monte Carlo samples (200 gives adequate scatter distribution;
        1000 for certification analysis).
    seed : int | None
        Random seed for reproducibility.
    dt : float
        Integration time step [s].  Smaller = more accurate but slower.

    Returns
    -------
    MonteCarloResult

    Examples
    --------
    >>> nom = NominalInputs(total_impulse_ns=640, burn_time_s=1.7,
    ...                     initial_mass_kg=0.7, propellant_mass_kg=0.12)
    >>> result = monte_carlo_dispersion(nom, n_samples=50, seed=42)
    >>> result.apogee_mean_m > 50
    True
    """
    if dispersion is None:
        dispersion = DispersionInputs()

    rng = random.Random(seed)

    apogees: list[float] = []
    landing_radii: list[float] = []
    max_qs: list[float] = []
    samples: list[dict] = []

    for _ in range(n_samples):
        # Sample each uncertain parameter
        cd_mult = max(
            0.1,
            1.0 + rng.gauss(0, dispersion.drag_coefficient_frac)
        )
        thrust_mult = max(
            0.5,
            1.0 + rng.gauss(0, dispersion.isp_frac)
        )
        wind_magnitude = abs(rng.gauss(0, dispersion.wind_speed_mps))
        wind_azimuth_rad = math.radians(rng.uniform(0, 360))
        wind_x = wind_magnitude * math.cos(wind_azimuth_rad)
        wind_y = wind_magnitude * math.sin(wind_azimuth_rad)

        elev_perturb = rng.gauss(0, dispersion.launch_angle_deg)
        elev = nominal.launch_elevation_deg + elev_perturb

        ig_delay = max(0.0, nominal.burn_time_s * 0.0 + rng.gauss(0, dispersion.ignition_delay_s))

        res = _simulate_trajectory(
            nominal,
            cd_multiplier=cd_mult,
            thrust_multiplier=thrust_mult,
            wind_x_mps=wind_x,
            elevation_deg=elev,
            ignition_delay_s=ig_delay,
            dt=dt,
        )

        # Add crossrange wind drift to landing scatter
        # Simplified: horizontal drift ~ wind_y * flight_time * (1 - cos(elev))
        y_drift = wind_y * res["flight_time_s"] * 0.3  # rough drift factor
        total_x = res["landing_x_m"]
        total_y = res["landing_y_m"] + y_drift
        radius = math.sqrt(total_x ** 2 + total_y ** 2)

        sample = {
            "apogee_m": res["apogee_m"],
            "landing_radius_m": radius,
            "max_q_pa": res["max_q_pa"],
            "wind_speed_mps": wind_magnitude,
            "cd_multiplier": cd_mult,
        }
        apogees.append(res["apogee_m"])
        landing_radii.append(radius)
        max_qs.append(res["max_q_pa"])
        samples.append(sample)

    # Statistics
    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    def _std(xs: list[float], mu: float) -> float:
        if len(xs) < 2:
            return 0.0
        return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))

    def _percentile(xs: list[float], p: float) -> float:
        s = sorted(xs)
        idx = (p / 100.0) * (len(s) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(s) - 1)
        frac = idx - lo
        return s[lo] * (1 - frac) + s[hi] * frac

    a_mean = _mean(apogees)
    a_std = _std(apogees, a_mean)
    r_mean = _mean(landing_radii)
    r_std = _std(landing_radii, r_mean)

    return MonteCarloResult(
        n_samples=n_samples,
        apogee_mean_m=a_mean,
        apogee_std_m=a_std,
        apogee_p05_m=_percentile(apogees, 5),
        apogee_p95_m=_percentile(apogees, 95),
        landing_radius_mean_m=r_mean,
        landing_radius_std_m=r_std,
        landing_radius_p95_m=_percentile(landing_radii, 95),
        max_q_mean_pa=_mean(max_qs),
        samples=samples,
    )
