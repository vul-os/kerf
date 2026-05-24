"""Ground station access / contact interval analysis.

Computes the times when a satellite is visible above a minimum elevation angle
from a ground station (or set of stations).  Analogous to GMAT's
ContactLocator / GroundStation access interval feature.

Approach
--------
For a given set of Keplerian elements and ground station(s), the orbit is
numerically sampled at a fixed time step.  At each sample, the satellite
elevation angle above the station horizon is computed.  Rise/set crossings
(transitions through the minimum elevation angle) are refined with bisection.

Coordinate transforms:
  - ECI position of satellite from Keplerian propagation.
  - ECEF position of ground station from geodetic lat/lon/alt.
  - ECI→ECEF rotation: approximate sidereal time (GST = GMST).
  - Local Elevation from station to satellite in the ENU frame.

References
----------
Vallado, D.A. (2013). "Fundamentals of Astrodynamics and Applications," 4th ed.
    §11.6 Viewing.
Montenbruck & Gill (2000), §7.4.
Wertz, J.R. (ed.) (1978). "Spacecraft Attitude Determination and Control."
    Appendix D: ground station visibility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

from .kepler import (
    KeplerianElements,
    MU_EARTH,
    elements_to_state,
    propagate_kepler,
    state_to_elements,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Earth rotation rate [rad/s]
OMEGA_EARTH: float = 7.2921150e-5

# Earth equatorial radius [km]
R_EARTH_ELLIPSOID: float = 6378.1363

# Earth flattening (WGS-84)
F_EARTH: float = 1.0 / 298.257223563


# ---------------------------------------------------------------------------
# Ground station
# ---------------------------------------------------------------------------

@dataclass
class GroundStation:
    """Ground station definition.

    Attributes
    ----------
    name : str
        Station identifier.
    latitude_deg : float
        Geodetic latitude [deg].  North positive.
    longitude_deg : float
        East longitude [deg].
    altitude_km : float
        Station altitude above WGS-84 ellipsoid [km].
    min_elevation_deg : float
        Minimum elevation angle for contact [deg].  Default 5°.
    """

    name: str
    latitude_deg: float
    longitude_deg: float
    altitude_km: float = 0.0
    min_elevation_deg: float = 5.0


# ---------------------------------------------------------------------------
# Coordinate utilities
# ---------------------------------------------------------------------------

def geodetic_to_ecef(
    lat_deg: float,
    lon_deg: float,
    alt_km: float,
) -> NDArray:
    """Convert geodetic (WGS-84) coordinates to ECEF position [km].

    Parameters
    ----------
    lat_deg, lon_deg : float
        Geodetic latitude and east longitude [deg].
    alt_km : float
        Altitude above ellipsoid [km].

    Returns
    -------
    NDArray, shape (3,)
        ECEF position [km].
    """
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    a = R_EARTH_ELLIPSOID
    e2 = 2.0 * F_EARTH - F_EARTH ** 2   # first eccentricity squared

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    N = a / math.sqrt(1.0 - e2 * sin_lat ** 2)   # prime vertical radius of curvature

    x = (N + alt_km) * cos_lat * math.cos(lon)
    y = (N + alt_km) * cos_lat * math.sin(lon)
    z = (N * (1.0 - e2) + alt_km) * sin_lat

    return np.array([x, y, z])


def gst_from_epoch(t_since_j2000_s: float) -> float:
    """Approximate Greenwich Sidereal Time [rad] from epoch J2000.0.

    Uses the IAU 1982 linear model:

        GMST = 67310.5484 + (3164400184.8128660 + 0.093104*T - 6.2e-6*T^2) * T / 3600
        where T is Julian centuries from J2000.

    A simplified approximation is used here (sufficient for satellite contact
    analysis, error < 1 arcminute):

        GST ≈ GST_J2000 + omega_E * t

    Parameters
    ----------
    t_since_j2000_s : float
        Seconds since J2000.0 (2000-01-01 12:00:00 TT).

    Returns
    -------
    float
        GST [rad], normalised to [0, 2π).
    """
    # GST at J2000.0 [rad]: 18h 41m 50.54841s = 280.46061837 deg
    gst0 = math.radians(280.46061837)
    gst = gst0 + OMEGA_EARTH * t_since_j2000_s
    return gst % (2.0 * math.pi)


def eci_to_ecef(r_eci: NDArray, t_since_j2000_s: float) -> NDArray:
    """Rotate ECI position to ECEF using sidereal time rotation.

    Parameters
    ----------
    r_eci : array-like, shape (3,)
        ECI position [km].
    t_since_j2000_s : float
        Epoch [s since J2000.0].

    Returns
    -------
    NDArray, shape (3,)
        ECEF position [km].
    """
    theta = gst_from_epoch(t_since_j2000_s)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    r = np.asarray(r_eci, dtype=float)
    x_ecef = cos_t * r[0] + sin_t * r[1]
    y_ecef = -sin_t * r[0] + cos_t * r[1]
    z_ecef = r[2]
    return np.array([x_ecef, y_ecef, z_ecef])


def elevation_angle(
    r_station_ecef: NDArray,
    r_sat_ecef: NDArray,
    lat_deg: float,
    lon_deg: float,
) -> float:
    """Compute elevation angle from station to satellite [deg].

    Uses the ENU (East-North-Up) local frame at the station.

    Parameters
    ----------
    r_station_ecef : array-like, shape (3,)
        Station ECEF position [km].
    r_sat_ecef : array-like, shape (3,)
        Satellite ECEF position [km].
    lat_deg, lon_deg : float
        Station geodetic latitude and east longitude [deg].

    Returns
    -------
    float
        Elevation angle [deg].  Positive = above horizon.
    """
    rho = np.asarray(r_sat_ecef, dtype=float) - np.asarray(r_station_ecef, dtype=float)

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)

    # ENU unit vectors in ECEF
    e_east = np.array([-sin_lon, cos_lon, 0.0])
    e_north = np.array([-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat])
    e_up = np.array([cos_lat * cos_lon, cos_lat * sin_lon, sin_lat])

    rho_e = float(np.dot(rho, e_east))
    rho_n = float(np.dot(rho, e_north))
    rho_u = float(np.dot(rho, e_up))

    rho_mag = float(np.linalg.norm(rho))
    if rho_mag < 1e-9:
        return 90.0   # station at sub-satellite point

    el_rad = math.asin(rho_u / rho_mag)
    return math.degrees(el_rad)


# ---------------------------------------------------------------------------
# Contact interval data structures
# ---------------------------------------------------------------------------

@dataclass
class ContactInterval:
    """A single continuous contact interval.

    Attributes
    ----------
    rise_time_s : float
        Time of AOS (acquisition of signal) [s since epoch].
    set_time_s : float
        Time of LOS (loss of signal) [s since epoch].
    duration_s : float
        Contact duration [s].
    max_elevation_deg : float
        Maximum elevation angle during contact [deg].
    station_name : str
        Ground station identifier.
    """

    rise_time_s: float
    set_time_s: float
    duration_s: float
    max_elevation_deg: float
    station_name: str


@dataclass
class CoverageResult:
    """Results of a ground station access analysis.

    Attributes
    ----------
    contacts : list[ContactInterval]
        All contact intervals sorted by rise time.
    total_contact_time_s : float
        Sum of all contact durations [s].
    max_gap_s : float
        Maximum gap between consecutive contacts [s].
    mean_contact_duration_s : float
        Mean contact interval duration [s].
    access_fraction : float
        Fraction of analysis window with at least one contact.
    """

    contacts: list = field(default_factory=list)
    total_contact_time_s: float = 0.0
    max_gap_s: float = 0.0
    mean_contact_duration_s: float = 0.0
    access_fraction: float = 0.0


# ---------------------------------------------------------------------------
# Main access analysis
# ---------------------------------------------------------------------------

def compute_contacts(
    elements: KeplerianElements,
    station: GroundStation,
    analysis_duration_s: float,
    *,
    epoch_j2000_s: float = 0.0,
    time_step_s: float | None = None,
    mu: float = MU_EARTH,
) -> list[ContactInterval]:
    """Compute contact intervals for one satellite / one ground station.

    Parameters
    ----------
    elements : KeplerianElements
        Initial Keplerian orbital elements (at epoch_j2000_s).
    station : GroundStation
        Ground station definition.
    analysis_duration_s : float
        Length of analysis window [s].
    epoch_j2000_s : float
        Epoch of initial elements [s since J2000.0].
    time_step_s : float | None
        Sampling time step [s].  Default: T_orbital / 100.
    mu : float
        Gravitational parameter [km^3/s^2].

    Returns
    -------
    list[ContactInterval]
        Contact intervals sorted by rise time.
    """
    from math import pi

    # Default time step: 1% of orbital period
    if time_step_s is None:
        T_orb = 2.0 * pi * math.sqrt(elements.a ** 3 / mu)
        time_step_s = max(T_orb / 100.0, 10.0)

    r_station_ecef = geodetic_to_ecef(
        station.latitude_deg, station.longitude_deg, station.altitude_km
    )
    min_el = station.min_elevation_deg

    n_steps = max(int(analysis_duration_s / time_step_s), 1)
    times = [i * time_step_s for i in range(n_steps + 1)]

    # Initial state vector from Keplerian elements
    r0_eci, v0_eci = elements_to_state(elements, mu)

    # Sample elevation at each time step
    def _elevation_at_t(t: float) -> float:
        t_abs = epoch_j2000_s + t
        r_eci, _ = propagate_kepler(r0_eci, v0_eci, t, mu)
        r_ecef = eci_to_ecef(r_eci, t_abs)
        return elevation_angle(r_station_ecef, r_ecef, station.latitude_deg, station.longitude_deg)

    elevations = [_elevation_at_t(t) for t in times]

    # Find rise/set crossings
    contacts: list[ContactInterval] = []
    in_contact = False
    t_rise = 0.0
    max_el_during = 0.0

    for k in range(len(times) - 1):
        el0 = elevations[k]
        el1 = elevations[k + 1]
        t0 = times[k]
        t1 = times[k + 1]

        if not in_contact:
            if el0 < min_el and el1 >= min_el:
                # Rising — refine with bisection
                t_lo, t_hi = t0, t1
                for _ in range(20):
                    t_mid = (t_lo + t_hi) / 2.0
                    el_mid = _elevation_at_t(t_mid)
                    if el_mid < min_el:
                        t_lo = t_mid
                    else:
                        t_hi = t_mid
                t_rise = (t_lo + t_hi) / 2.0
                max_el_during = max(el1, 0.0)
                in_contact = True
            elif el0 >= min_el:
                # Started already in contact (begin of window)
                if k == 0:
                    t_rise = t0
                    max_el_during = el0
                    in_contact = True
        else:
            max_el_during = max(max_el_during, el0)
            if el0 >= min_el and el1 < min_el:
                # Setting — refine with bisection
                t_lo, t_hi = t0, t1
                for _ in range(20):
                    t_mid = (t_lo + t_hi) / 2.0
                    el_mid = _elevation_at_t(t_mid)
                    if el_mid >= min_el:
                        t_lo = t_mid
                    else:
                        t_hi = t_mid
                t_set = (t_lo + t_hi) / 2.0
                contacts.append(ContactInterval(
                    rise_time_s=t_rise,
                    set_time_s=t_set,
                    duration_s=t_set - t_rise,
                    max_elevation_deg=max_el_during,
                    station_name=station.name,
                ))
                in_contact = False
                max_el_during = 0.0

    # Close open interval at end of analysis window
    if in_contact:
        t_set = times[-1]
        contacts.append(ContactInterval(
            rise_time_s=t_rise,
            set_time_s=t_set,
            duration_s=t_set - t_rise,
            max_elevation_deg=max_el_during,
            station_name=station.name,
        ))

    return contacts


def coverage_analysis(
    elements: KeplerianElements,
    stations: Sequence[GroundStation],
    analysis_duration_s: float,
    *,
    epoch_j2000_s: float = 0.0,
    time_step_s: float | None = None,
    mu: float = MU_EARTH,
) -> CoverageResult:
    """Multi-station coverage analysis over an analysis window.

    Parameters
    ----------
    elements : KeplerianElements
        Initial Keplerian elements.
    stations : sequence of GroundStation
        Ground stations to analyse.
    analysis_duration_s : float
        Analysis window duration [s].
    epoch_j2000_s : float
        Epoch [s since J2000.0].
    time_step_s : float | None
        Time step for sampling.
    mu : float
        Gravitational parameter [km^3/s^2].

    Returns
    -------
    CoverageResult
        Aggregate contact statistics.
    """
    all_contacts: list[ContactInterval] = []
    for station in stations:
        contacts = compute_contacts(
            elements, station, analysis_duration_s,
            epoch_j2000_s=epoch_j2000_s,
            time_step_s=time_step_s,
            mu=mu,
        )
        all_contacts.extend(contacts)

    all_contacts.sort(key=lambda c: c.rise_time_s)

    total_time = sum(c.duration_s for c in all_contacts)
    n = len(all_contacts)
    mean_dur = total_time / n if n > 0 else 0.0

    # Max gap between consecutive contacts
    max_gap = 0.0
    if n > 1:
        for k in range(n - 1):
            gap = all_contacts[k + 1].rise_time_s - all_contacts[k].set_time_s
            if gap > max_gap:
                max_gap = gap

    # Access fraction: fraction of analysis window covered by at least one contact
    # (merge overlapping intervals)
    covered = 0.0
    if all_contacts:
        merged_start = all_contacts[0].rise_time_s
        merged_end = all_contacts[0].set_time_s
        for c in all_contacts[1:]:
            if c.rise_time_s <= merged_end:
                merged_end = max(merged_end, c.set_time_s)
            else:
                covered += merged_end - merged_start
                merged_start = c.rise_time_s
                merged_end = c.set_time_s
        covered += merged_end - merged_start

    access_frac = covered / analysis_duration_s if analysis_duration_s > 0 else 0.0

    return CoverageResult(
        contacts=all_contacts,
        total_contact_time_s=total_time,
        max_gap_s=max_gap,
        mean_contact_duration_s=mean_dur,
        access_fraction=access_frac,
    )
