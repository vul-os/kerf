"""
Solar flux calculations for spacecraft thermal analysis.

References
----------
  Kopp, G. & Lean, J.L. (2011), "A new, lower value of total solar irradiance:
  Evidence and climate significance", Geophysical Research Letters, 38.
  → Solar constant S_0 = 1361 W/m² (TIM/SORCE consensus value).

  Wertz, J.R. & Larson, W.J. (eds.), "Space Mission Engineering: The New SMAD",
  3rd ed., Microcosm Press, 2011. — Chapter 11 (orbital mechanics) for
  eclipse entry/exit geometry.

  Vallado, D.A., "Fundamentals of Astrodynamics and Applications", 4th ed.

Units: SI throughout (W, m, W/m², AU, km, radians unless stated).

Conventions
-----------
  - Distance in AU; 1 AU = 1.495978707e11 m.
  - Eclipse fractions: 0.0 = full sunlight, 1.0 = full umbra.
  - All angles in radians unless the function name says _deg.
"""

from __future__ import annotations

import math
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOLAR_CONSTANT_W_M2: float = 1361.0
"""Total Solar Irradiance at 1 AU (W/m²) — Kopp & Lean 2011."""

AU_M: float = 1.495978707e11
"""One Astronomical Unit in metres."""

# Earth parameters used for eclipse geometry
EARTH_RADIUS_KM: float = 6371.0          # mean radius [km]
EARTH_RADIUS_M: float = EARTH_RADIUS_KM * 1000.0

# Sun parameters
SUN_RADIUS_KM: float = 6.957e5           # mean radius [km]
SUN_RADIUS_M: float = SUN_RADIUS_KM * 1000.0

# Mars mean orbital radius
MARS_AU: float = 1.524                   # semi-major axis [AU]


# ---------------------------------------------------------------------------
# Core flux functions
# ---------------------------------------------------------------------------

def solar_flux_at_distance(distance_au: float) -> float:
    """
    Solar flux (irradiance) at a heliocentric distance *distance_au* AU.

    Uses the inverse-square law:

        S(r) = S_0 / r²

    where S_0 = 1361 W/m² and r is in AU.

    Parameters
    ----------
    distance_au : float
        Heliocentric distance in AU.  Must be > 0.

    Returns
    -------
    float
        Solar flux [W/m²].

    Raises
    ------
    ValueError
        If distance_au <= 0.
    """
    if distance_au <= 0:
        raise ValueError(f"distance_au must be positive, got {distance_au!r}")
    return SOLAR_CONSTANT_W_M2 / (distance_au ** 2)


def solar_flux_at_distance_m(distance_m: float) -> float:
    """
    Solar flux at heliocentric distance *distance_m* metres.

    Convenience wrapper around :func:`solar_flux_at_distance`.

    Parameters
    ----------
    distance_m : float
        Heliocentric distance in metres.

    Returns
    -------
    float
        Solar flux [W/m²].
    """
    if distance_m <= 0:
        raise ValueError(f"distance_m must be positive, got {distance_m!r}")
    distance_au = distance_m / AU_M
    return solar_flux_at_distance(distance_au)


def absorbed_solar_flux(
    alpha: float,
    area: float,
    angle_deg: float = 0.0,
    distance_au: float = 1.0,
) -> float:
    """
    Solar power absorbed by a flat surface.

        Q_solar = α · A · S(r) · cos(θ)

    Parameters
    ----------
    alpha : float
        Solar absorptivity (0–1).
    area : float
        Surface area [m²].
    angle_deg : float
        Angle of incidence of the Sun vector relative to the surface normal [deg].
        0° = normal incidence (full flux), 90° = grazing (zero flux).
    distance_au : float
        Heliocentric distance [AU].  Default 1 AU (Earth orbit).

    Returns
    -------
    float
        Absorbed solar power [W].
    """
    S = solar_flux_at_distance(distance_au)
    theta_rad = math.radians(angle_deg)
    return alpha * area * S * max(0.0, math.cos(theta_rad))


# ---------------------------------------------------------------------------
# Eclipse geometry
# ---------------------------------------------------------------------------

class EclipseGeometry(NamedTuple):
    """Output of :func:`eclipse_geometry`."""

    in_umbra: bool
    """True if the spacecraft is fully in Earth's shadow (umbra)."""

    in_penumbra: bool
    """True if the spacecraft is in the penumbra (partial shadow)."""

    umbra_half_angle_rad: float
    """Half-angle of Earth's umbra cone [rad]."""

    penumbra_half_angle_rad: float
    """Half-angle of Earth's penumbra cone [rad]."""

    eclipse_fraction: float
    """
    Approximate fractional eclipse depth:
      0.0 = full sunlight,
      1.0 = deep umbra.
    Intermediate values are a linear ramp across the penumbra.
    """


def eclipse_geometry(
    spacecraft_altitude_km: float,
    sun_angle_rad: float,
) -> EclipseGeometry:
    """
    Determine whether a spacecraft in circular Earth orbit is in sunlight,
    penumbra, or umbra for a given orbital angle from the Sun.

    The model computes the umbra and penumbra cone half-angles from geometry
    and checks whether the spacecraft's angular distance from the anti-Sun
    direction (180° − sun_angle_rad) places it inside the shadow.

    Parameters
    ----------
    spacecraft_altitude_km : float
        Orbit altitude above Earth's surface [km].
    sun_angle_rad : float
        Angle between the spacecraft position vector and the Sun direction [rad].
        0 = spacecraft in the Sun direction, π = directly behind Earth.

    Returns
    -------
    EclipseGeometry
    """
    if spacecraft_altitude_km <= 0:
        raise ValueError("spacecraft_altitude_km must be positive")

    r_sc = (EARTH_RADIUS_KM + spacecraft_altitude_km) * 1e3  # [m]
    r_e = EARTH_RADIUS_M
    r_s = SUN_RADIUS_M
    d_sun = AU_M  # assume 1 AU Sun–Earth distance

    # Half-angles of the umbra and penumbra cones (radians)
    # Umbra:    sin(α_u) = (r_s - r_e) / d_sun  — decreasing cone
    # Penumbra: sin(α_p) = (r_s + r_e) / d_sun  — expanding cone
    alpha_umbra = math.asin((r_s - r_e) / d_sun)
    alpha_penumbra = math.asin((r_s + r_e) / d_sun)

    # Angular radius of Earth as seen from the spacecraft
    rho = math.asin(r_e / r_sc)   # Earth's angular radius [rad]

    # The umbra boundary angle measured from the anti-Sun direction
    # The spacecraft is in umbra when sun_angle_rad > π − rho − alpha_umbra
    # In penumbra when π − rho − alpha_penumbra < sun_angle_rad
    # Simplified: compare the spacecraft's angle to Earth's shadow boundaries.
    #
    # We use the direct criterion:
    #   spacecraft is in Earth's shadow when the angle to the anti-Sun direction
    #   is less than the apparent radius of Earth's shadow.
    #
    # anti-sun angle (0 = directly behind Earth)
    anti_sun_angle = abs(math.pi - sun_angle_rad)

    # Penumbra outer boundary: spacecraft is outside Earth's penumbra when
    #   anti_sun_angle > rho + alpha_penumbra
    # Umbra inner boundary:
    #   anti_sun_angle < rho - alpha_umbra  (for the deep-shadow core)

    penumbra_boundary = rho + alpha_penumbra
    umbra_boundary = rho - alpha_umbra if rho > alpha_umbra else 0.0

    in_umbra = anti_sun_angle < umbra_boundary
    in_penumbra = (not in_umbra) and (anti_sun_angle < penumbra_boundary)

    # Eclipse fraction: linear ramp from 0 (full sun) to 1 (full umbra)
    if in_umbra:
        eclipse_fraction = 1.0
    elif in_penumbra:
        # 0 at penumbra outer edge → 1 at umbra edge
        width = penumbra_boundary - umbra_boundary
        if width > 0:
            eclipse_fraction = (penumbra_boundary - anti_sun_angle) / width
        else:
            eclipse_fraction = 0.5
    else:
        eclipse_fraction = 0.0

    return EclipseGeometry(
        in_umbra=in_umbra,
        in_penumbra=in_penumbra,
        umbra_half_angle_rad=alpha_umbra,
        penumbra_half_angle_rad=alpha_penumbra,
        eclipse_fraction=eclipse_fraction,
    )


# ---------------------------------------------------------------------------
# Orbit-averaged solar flux
# ---------------------------------------------------------------------------

def orbit_average_solar_flux(
    spacecraft_altitude_km: float,
    distance_au: float = 1.0,
    n_points: int = 720,
) -> float:
    """
    Numerically integrate the orbit-averaged solar flux for a circular orbit,
    accounting for Earth eclipse.

    The result is the mean flux (W/m²) incident on a 1-m² panel that always
    faces the Sun (i.e., the solar array normal tracks the Sun direction).

    Parameters
    ----------
    spacecraft_altitude_km : float
        Circular orbit altitude [km].
    distance_au : float
        Heliocentric distance [AU].
    n_points : int
        Number of quadrature points around the orbit.

    Returns
    -------
    float
        Orbit-averaged solar flux [W/m²].
    """
    S = solar_flux_at_distance(distance_au)
    total = 0.0
    for i in range(n_points):
        theta = 2.0 * math.pi * i / n_points
        geo = eclipse_geometry(spacecraft_altitude_km, theta)
        total += S * (1.0 - geo.eclipse_fraction)
    return total / n_points


# ---------------------------------------------------------------------------
# Planet solar flux table
# ---------------------------------------------------------------------------

PLANET_SOLAR_FLUX: dict[str, float] = {
    planet: solar_flux_at_distance(au)
    for planet, au in [
        ("mercury_perihelion", 0.307),
        ("mercury_aphelion", 0.467),
        ("venus", 0.723),
        ("earth", 1.000),
        ("mars", MARS_AU),
        ("jupiter", 5.203),
        ("saturn", 9.537),
        ("uranus", 19.191),
        ("neptune", 30.069),
    ]
}
"""Pre-computed solar flux [W/m²] at mean orbital distances for solar-system bodies."""
