"""Rocket recovery event simulation — parachute and streamer descent.

Models dual-deploy recovery system events:
  1. Apogee detect → drogue chute deployment
  2. Drogue descent to trigger altitude
  3. Main chute deployment at trigger altitude
  4. Main chute descent to ground

Also models:
  - Streamer descent (rectangular ribbon; lower drag, faster descent)
  - Horizontal drift from wind during descent

Uses USSA-76 atmospheric density at each altitude step.

References
----------
Niskanen, S. (2009). "OpenRocket Technical Documentation", §5.1-5.3.
Knacke, T.W. (1992). "Parachute Recovery Systems Design Manual."
    Para Publishing. (Cd values and descent rate formulas.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .flight_dynamics.atmosphere import atmosphere


# ---------------------------------------------------------------------------
# Drag areas for common recovery devices
# ---------------------------------------------------------------------------

# Typical Cd * S (drag area) for standard devices [m²]
DROGUE_TYPICAL_CD_S = {
    "cruciform_0.3m": 0.06,   # 30 cm cruciform
    "cruciform_0.6m": 0.22,
    "toroidal_0.3m": 0.09,
    "ribbon_streamer_1mx0.05m": 0.018,
    "ribbon_streamer_1mx0.1m": 0.035,
}

MAIN_TYPICAL_CD_S = {
    "round_0.6m": 0.25,    # 60 cm round parachute
    "round_1.0m": 0.70,
    "round_1.2m": 1.00,
    "hexagonal_0.9m": 0.55,
    "elliptical_0.9m": 0.48,
}


# ---------------------------------------------------------------------------
# Descent calculation
# ---------------------------------------------------------------------------

@dataclass
class DescentResult:
    """Results of a descent phase simulation.

    Attributes
    ----------
    touchdown_speed_ms : float
        Vertical speed at ground impact [m/s].  Positive = downward.
    descent_time_s : float
        Time from deployment to touchdown [s].
    horizontal_drift_m : float
        Horizontal displacement due to wind [m].
    terminal_speed_ms : float
        Terminal descent speed at sea-level density [m/s].
    altitude_profile_m : list[float]
        Sampled altitude [m] during descent (coarse, for reporting).
    """

    touchdown_speed_ms: float
    descent_time_s: float
    horizontal_drift_m: float
    terminal_speed_ms: float
    altitude_profile_m: list


def terminal_descent_speed(
    mass_kg: float,
    cd_area_m2: float,
    altitude_m: float = 0.0,
) -> float:
    """Compute terminal descent speed at the given altitude.

    At terminal velocity:

        mg = ½ ρ V² Cd A
        V = sqrt(2mg / (ρ Cd A))

    Parameters
    ----------
    mass_kg : float
        Total descending mass [kg].
    cd_area_m2 : float
        Drag area Cd × A [m²].
    altitude_m : float
        Altitude for atmospheric density [m].

    Returns
    -------
    float
        Terminal descent speed [m/s].  Positive = downward.

    Examples
    --------
    >>> v = terminal_descent_speed(1.0, 0.7)
    >>> 4 < v < 8   # typical 1 kg rocket with 1 m round chute
    True
    """
    if mass_kg <= 0:
        raise ValueError(f"mass_kg must be positive; got {mass_kg}")
    if cd_area_m2 <= 0:
        raise ValueError(f"cd_area_m2 must be positive; got {cd_area_m2}")

    atm = atmosphere(max(altitude_m, 0.0))
    rho = atm.density_kg_m3
    g = 9.80665

    v_term = math.sqrt(2.0 * mass_kg * g / (rho * cd_area_m2))
    return v_term


def simulate_descent(
    deployment_altitude_m: float,
    mass_kg: float,
    cd_area_m2: float,
    wind_speed_mps: float = 0.0,
    dt: float = 0.5,
) -> DescentResult:
    """Simulate descent from deployment altitude to ground.

    Integrates the 1-DOF equation of motion under gravity and aerodynamic
    drag using Euler integration:

        m * a = m*g - ½ ρ(z) V² Cd A

    Wind-driven horizontal drift is computed as:

        x_drift = wind_speed * descent_time    (constant wind approximation)

    Parameters
    ----------
    deployment_altitude_m : float
        Altitude at which the recovery device is deployed [m].
    mass_kg : float
        Descending mass [kg].
    cd_area_m2 : float
        Recovery device drag area Cd × A [m²].
    wind_speed_mps : float
        Mean horizontal wind speed during descent [m/s].
    dt : float
        Integration time step [s].

    Returns
    -------
    DescentResult

    Examples
    --------
    >>> res = simulate_descent(300, 1.0, 0.7)
    >>> res.touchdown_speed_ms < 15
    True
    """
    if deployment_altitude_m <= 0:
        raise ValueError(f"deployment_altitude_m must be positive; got {deployment_altitude_m}")

    z = deployment_altitude_m
    vz = 0.0   # initial descent speed [m/s], positive = downward
    t = 0.0
    g = 9.80665
    altitude_profile = [z]

    while z > 0:
        atm = atmosphere(min(max(z, 0.0), 86000.0))
        rho = atm.density_kg_m3

        drag = 0.5 * rho * vz ** 2 * cd_area_m2   # [N], opposes motion
        a = g - drag / mass_kg   # net downward acceleration [m/s²]

        vz += a * dt
        z -= vz * dt   # z decreases as rocket descends
        t += dt

        if t % 10.0 < dt:   # sample every ~10 s
            altitude_profile.append(max(z, 0.0))

        if t > 3600:   # safety timeout
            break

    # Terminal speed at sea level
    v_term = terminal_descent_speed(mass_kg, cd_area_m2, 0.0)

    # Horizontal drift
    drift = wind_speed_mps * t

    return DescentResult(
        touchdown_speed_ms=vz,
        descent_time_s=t,
        horizontal_drift_m=drift,
        terminal_speed_ms=v_term,
        altitude_profile_m=altitude_profile,
    )


# ---------------------------------------------------------------------------
# Dual-deploy event sequencer
# ---------------------------------------------------------------------------

@dataclass
class DualDeployResult:
    """Results of dual-deploy recovery sequence simulation.

    Attributes
    ----------
    drogue_deployed_at_m : float
        Altitude at which drogue deployed [m].
    main_deployed_at_m : float
        Altitude at which main chute deployed [m].
    drogue_descent : DescentResult
        Drogue phase descent data (apogee → main deploy altitude).
    main_descent : DescentResult
        Main chute phase descent data (main deploy altitude → touchdown).
    total_descent_time_s : float
        Total time from apogee to touchdown [s].
    touchdown_speed_ms : float
        Final touchdown speed [m/s].
    total_drift_m : float
        Total horizontal drift from all descent phases [m].
    """

    drogue_deployed_at_m: float
    main_deployed_at_m: float
    drogue_descent: DescentResult
    main_descent: DescentResult
    total_descent_time_s: float
    touchdown_speed_ms: float
    total_drift_m: float


def simulate_dual_deploy(
    apogee_m: float,
    mass_kg: float,
    drogue_cd_area_m2: float,
    main_cd_area_m2: float,
    main_deploy_altitude_m: float = 150.0,
    apogee_detect_delay_s: float = 0.5,
    wind_speed_mps: float = 0.0,
) -> DualDeployResult:
    """Simulate a dual-deploy recovery sequence.

    Sequence:
      1. Apogee + detect_delay → drogue fires.
      2. Drogue descent from apogee to main_deploy_altitude.
      3. Main chute fires at main_deploy_altitude.
      4. Main chute descent to touchdown.

    Parameters
    ----------
    apogee_m : float
        Apogee altitude [m].
    mass_kg : float
        Descending mass [kg].
    drogue_cd_area_m2 : float
        Drogue drag area [m²].
    main_cd_area_m2 : float
        Main parachute drag area [m²].
    main_deploy_altitude_m : float
        Altitude to deploy main chute [m].
    apogee_detect_delay_s : float
        Delay between apogee and drogue firing [s] (altimeter response).
    wind_speed_mps : float
        Mean wind speed during descent [m/s].

    Returns
    -------
    DualDeployResult

    Examples
    --------
    >>> r = simulate_dual_deploy(300, 1.0, 0.06, 0.7)
    >>> r.touchdown_speed_ms < 10
    True
    """
    if apogee_m <= main_deploy_altitude_m:
        raise ValueError(
            f"apogee ({apogee_m} m) must be above main deploy altitude "
            f"({main_deploy_altitude_m} m)"
        )

    drogue_alt = apogee_m  # fire at apogee (delay accounted for in flight sim)

    drogue_phase = simulate_descent(
        deployment_altitude_m=drogue_alt - main_deploy_altitude_m,
        mass_kg=mass_kg,
        cd_area_m2=drogue_cd_area_m2,
        wind_speed_mps=wind_speed_mps,
    )

    main_phase = simulate_descent(
        deployment_altitude_m=main_deploy_altitude_m,
        mass_kg=mass_kg,
        cd_area_m2=main_cd_area_m2,
        wind_speed_mps=wind_speed_mps,
    )

    return DualDeployResult(
        drogue_deployed_at_m=drogue_alt,
        main_deployed_at_m=main_deploy_altitude_m,
        drogue_descent=drogue_phase,
        main_descent=main_phase,
        total_descent_time_s=drogue_phase.descent_time_s + main_phase.descent_time_s,
        touchdown_speed_ms=main_phase.touchdown_speed_ms,
        total_drift_m=drogue_phase.horizontal_drift_m + main_phase.horizontal_drift_m,
    )


# ---------------------------------------------------------------------------
# Streamer descent
# ---------------------------------------------------------------------------

def streamer_cd_area(
    width_m: float,
    length_m: float,
    cd_streamer: float = 0.75,
) -> float:
    """Compute drag area for a ribbon streamer.

    Streamers are commonly used on small/lower-power rockets in place of a
    drogue chute.  The effective drag area is:

        Cd_A = Cd_streamer * width * length

    where Cd_streamer ≈ 0.75 for a typical polyester ribbon.

    Parameters
    ----------
    width_m : float
        Streamer width [m].
    length_m : float
        Streamer length [m].
    cd_streamer : float
        Drag coefficient (default 0.75 per Knacke 1992, p. 5-12).

    Returns
    -------
    float
        Drag area Cd × A [m²].
    """
    return cd_streamer * width_m * length_m
