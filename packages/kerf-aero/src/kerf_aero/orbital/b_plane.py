"""B-plane targeting for planetary approach / flyby manoeuvres.

The B-plane is defined at the target body encounter as the plane containing
the aim point (B-vector) perpendicular to the incoming hyperbolic asymptote.

Coordinate system (per GMAT / JPL documentation):
  - S-hat: unit vector in the direction of the incoming V_infinity asymptote
  - T-hat: S × north_pole / |S × north_pole|   (approximately ecliptic-east)
  - R-hat: S × T                                (approximately ecliptic-north)

B-vector components:
  - BdotT = B · T  (controls periapsis latitude / inclination relative to target)
  - BdotR = B · R  (controls periapsis longitude / right ascension)
  - B_mag = |B| = semi-latus rectum of the hyperbola = a*(e²-1)^½ = a*sqrt(e²-1)

The miss distance (closest approach distance) is related to B by:
  r_p = a*(e - 1)   where a = mu / V_inf²  (sign: a is negative for hyperbola)
                    and e = sqrt(1 + (B/a)²)

References
----------
Bate, Mueller, White (1971). "Fundamentals of Astrodynamics." §7.3.
Vallado, D.A. (2013). "Fundamentals of Astrodynamics and Applications," 4th ed.
    §7.6 B-plane targeting.
GMAT Mathematical Specification, §4.2 B-plane coordinates.
    https://gmat.atlassian.net/wiki/spaces/GW/pages/380274219
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# B-plane coordinate system
# ---------------------------------------------------------------------------

@dataclass
class BPlaneFrame:
    """B-plane coordinate unit vectors.

    Attributes
    ----------
    s_hat : NDArray[float]  shape (3,)
        Incoming hyperbolic asymptote direction.
    t_hat : NDArray[float]  shape (3,)
        T-hat in the B-plane.
    r_hat : NDArray[float]  shape (3,)
        R-hat in the B-plane.
    """

    s_hat: NDArray
    t_hat: NDArray
    r_hat: NDArray


def b_plane_frame(
    v_inf: NDArray,
    north: NDArray | None = None,
) -> BPlaneFrame:
    """Compute the B-plane coordinate frame from the hyperbolic asymptote.

    Parameters
    ----------
    v_inf : array-like, shape (3,)
        Incoming V_infinity vector [km/s].  Direction of arrival.
    north : array-like, shape (3,) | None
        North reference vector.  Defaults to ecliptic north [0, 0, 1].

    Returns
    -------
    BPlaneFrame
        Orthonormal {S, T, R} triad.

    Raises
    ------
    ValueError
        If v_inf is zero-magnitude or nearly parallel to north.
    """
    v = np.asarray(v_inf, dtype=float)
    mag = float(np.linalg.norm(v))
    if mag < 1e-12:
        raise ValueError("v_inf must be non-zero")

    s_hat = v / mag

    if north is None:
        n = np.array([0.0, 0.0, 1.0])
    else:
        n = np.asarray(north, dtype=float)
        n_mag = float(np.linalg.norm(n))
        if n_mag < 1e-12:
            raise ValueError("north must be non-zero")
        n = n / n_mag

    # T = S × n / |S × n|
    t_raw = np.cross(s_hat, n)
    t_mag = float(np.linalg.norm(t_raw))
    if t_mag < 1e-10:
        raise ValueError(
            "v_inf nearly parallel to north pole; choose a different north vector"
        )
    t_hat = t_raw / t_mag

    # R = S × T  (completes the right-hand triad)
    r_hat = np.cross(s_hat, t_hat)
    r_hat = r_hat / float(np.linalg.norm(r_hat))

    return BPlaneFrame(s_hat=s_hat, t_hat=t_hat, r_hat=r_hat)


# ---------------------------------------------------------------------------
# B-vector from state vector
# ---------------------------------------------------------------------------

@dataclass
class BPlaneResult:
    """B-plane parameters computed from a hyperbolic encounter state.

    Attributes
    ----------
    b_dot_t : float
        BdotT component [km].
    b_dot_r : float
        BdotR component [km].
    b_magnitude : float
        B-vector magnitude [km].
    theta_b : float
        B-plane angle B·T vs B·R [rad].
    c3_km2s2 : float
        Characteristic energy C3 = V_inf² [km²/s²].
    rp_km : float
        Periapsis radius of hyperbolic trajectory [km].
    ecc : float
        Hyperbolic eccentricity (> 1).
    """

    b_dot_t: float
    b_dot_r: float
    b_magnitude: float
    theta_b: float
    c3_km2s2: float
    rp_km: float
    ecc: float


def b_plane_from_state(
    r_vec: NDArray,
    v_vec: NDArray,
    mu: float,
) -> BPlaneResult:
    """Compute B-plane parameters from a hyperbolic approach state vector.

    The spacecraft state (r, v) must be at an approach distance where the
    trajectory is well-approximated as Keplerian hyperbolic (no planetary
    oblateness or 3rd-body effects).

    Parameters
    ----------
    r_vec : array-like, shape (3,)
        Position vector in ECI or body-centred frame [km].
    v_vec : array-like, shape (3,)
        Velocity vector [km/s].
    mu : float
        Target body gravitational parameter [km^3/s^2].

    Returns
    -------
    BPlaneResult

    Raises
    ------
    ValueError
        If the orbit is not hyperbolic (e < 1).

    References
    ----------
    Bate et al. (1971), §7.3, eq. (7.3-3) through (7.3-9).
    Vallado (2013), §7.6.
    """
    r = np.asarray(r_vec, dtype=float)
    v = np.asarray(v_vec, dtype=float)

    r_mag = float(np.linalg.norm(r))
    v_mag = float(np.linalg.norm(v))

    # Vis-viva specific energy
    xi = v_mag ** 2 / 2.0 - mu / r_mag   # [km²/s²]
    if xi <= 0:
        raise ValueError(
            f"Orbit is not hyperbolic (energy xi = {xi:.6g} ≤ 0); "
            "state must be on an escape/hyperbolic trajectory"
        )

    c3 = 2.0 * xi   # V_inf² [km²/s²]
    v_inf_mag = math.sqrt(c3)

    # Semi-major axis (negative for hyperbola)
    a = -mu / (2.0 * xi)

    # Angular momentum
    h_vec = np.cross(r, v)
    h_mag = float(np.linalg.norm(h_vec))

    # Eccentricity vector
    e_vec = np.cross(v, h_vec) / mu - r / r_mag
    ecc = float(np.linalg.norm(e_vec))

    if ecc <= 1.0:
        raise ValueError(
            f"Eccentricity {ecc:.6f} ≤ 1; orbit must be hyperbolic"
        )

    # Periapsis radius
    rp = a * (1.0 - ecc)   # a < 0, 1-e < 0 → rp > 0

    # B magnitude = semi-latus rectum of hyperbola = a * sqrt(e²-1)
    b_mag = abs(a) * math.sqrt(ecc ** 2 - 1.0)

    # Asymptote direction (incoming V_inf in ECI frame):
    # For hyperbolic orbit, the outgoing asymptote direction is:
    #   s_out = e_hat * cos(acos(-1/e)) + e_perp_hat * sin(acos(-1/e))
    # but the incoming asymptote is the direction the spacecraft came from.
    # A robust approach: compute V at very large r (at infinity) by limit:
    #   V_inf^2 = v^2 - 2mu/r  → as r→∞, V = V_inf in the asymptote direction
    # Approximate incoming asymptote from state:
    #   v_inf_hat ≈ (v - v_perp_to_r) at large r, or directly from eccentricity:
    #   v_inf_hat = e_hat * sin(half_angle) - perp_e * cos(half_angle)
    # Standard formula (Bate eq. 7.3-7):
    #   cos(half_asymptote) = -1/e
    e_hat = e_vec / ecc
    delta_v = math.acos(-1.0 / ecc)    # half-turn to asymptote

    # Construct perpendicular to e in the orbit plane
    h_hat = h_vec / h_mag
    e_perp = np.cross(h_hat, e_hat)    # in-plane, 90° from e_hat

    # Incoming asymptote direction (approaching, so negate outgoing):
    s_hat = -(e_hat * math.cos(delta_v) + e_perp * math.sin(delta_v))
    s_hat = s_hat / float(np.linalg.norm(s_hat))

    # B-vector: perpendicular to s_hat, in the orbit plane, with magnitude b_mag
    # B is in the orbit plane, pointing from the asymptote-intercept to the focus
    # B-direction is the component of r_hat perpendicular to s_hat:
    frame = b_plane_frame(s_hat)

    # B-vector in 3D (lies in the B-plane perp to s_hat)
    # Project the closest-approach geometry:
    # B = b_mag * (e_hat component perpendicular to s) / |e_hat perp s|
    e_perp_s = e_hat - float(np.dot(e_hat, s_hat)) * s_hat
    e_perp_s_mag = float(np.linalg.norm(e_perp_s))
    if e_perp_s_mag > 1e-12:
        b_dir = e_perp_s / e_perp_s_mag
    else:
        b_dir = frame.t_hat

    b_vec = b_mag * b_dir

    b_dot_t = float(np.dot(b_vec, frame.t_hat))
    b_dot_r = float(np.dot(b_vec, frame.r_hat))
    theta_b = math.atan2(b_dot_r, b_dot_t)

    return BPlaneResult(
        b_dot_t=b_dot_t,
        b_dot_r=b_dot_r,
        b_magnitude=b_mag,
        theta_b=theta_b,
        c3_km2s2=c3,
        rp_km=float(abs(rp)),
        ecc=ecc,
    )


# ---------------------------------------------------------------------------
# B-plane targeting: compute required delta-V to achieve target BdotT / BdotR
# ---------------------------------------------------------------------------

@dataclass
class BPlaneTargetResult:
    """Result of a B-plane targeting correction manoeuvre.

    Attributes
    ----------
    dv_vec : NDArray[float]  shape (3,)
        Required delta-V vector in ECI [km/s].
    dv_magnitude : float
        Delta-V magnitude [km/s].
    b_dot_t_achieved : float
        BdotT after correction [km].
    b_dot_r_achieved : float
        BdotR after correction [km].
    rp_achieved_km : float
        Periapsis distance after correction [km].
    """

    dv_vec: NDArray
    dv_magnitude: float
    b_dot_t_achieved: float
    b_dot_r_achieved: float
    rp_achieved_km: float


def b_plane_target_delta_v(
    r_vec: NDArray,
    v_vec: NDArray,
    mu: float,
    target_b_dot_t: float,
    target_b_dot_r: float,
    *,
    north: NDArray | None = None,
    tol: float = 1e-6,
    max_iter: int = 20,
) -> BPlaneTargetResult:
    """Compute a TCM (trajectory correction manoeuvre) to hit target B-plane.

    Uses a first-order differential correction (linear algebra) to compute the
    velocity adjustment that maps the current B-plane to the target.  The
    correction is applied at the current state.

    Algorithm:
      1. Compute the B-plane sensitivity matrix dB/dV (3×3) by finite
         differencing V in each ECI axis.
      2. Solve for dV using the Moore-Penrose pseudo-inverse of [dBdotT/dV;
         dBdotR/dV] (2×3 rows → 3-vector solution).
      3. The solution minimises |dV|² subject to hitting the target.

    Parameters
    ----------
    r_vec : array-like, shape (3,)
        Spacecraft position at correction burn [km].
    v_vec : array-like, shape (3,)
        Spacecraft velocity at correction burn [km/s].
    mu : float
        Target body gravitational parameter [km^3/s^2].
    target_b_dot_t : float
        Target BdotT [km].
    target_b_dot_r : float
        Target BdotR [km].
    north : array-like, shape (3,) | None
        North reference for B-plane frame.
    tol : float
        Convergence tolerance on |B - B_target| [km].
    max_iter : int
        Maximum differential-correction iterations.

    Returns
    -------
    BPlaneTargetResult

    References
    ----------
    Vallado (2013), §7.6.3 — differential correction for B-plane targeting.
    """
    r = np.asarray(r_vec, dtype=float)
    v = np.asarray(v_vec, dtype=float)

    dv_step = 1e-4   # finite-difference step [km/s]

    current_v = v.copy()

    for _ in range(max_iter):
        current_state = b_plane_from_state(r, current_v, mu)
        b_t = current_state.b_dot_t
        b_r = current_state.b_dot_r

        db_t = b_t - target_b_dot_t
        db_r = b_r - target_b_dot_r

        if math.sqrt(db_t ** 2 + db_r ** 2) < tol:
            break

        # Build sensitivity matrix: rows = [dBdotT, dBdotR], cols = [dvx, dvy, dvz]
        jac = np.zeros((2, 3))
        for j in range(3):
            v_plus = current_v.copy()
            v_plus[j] += dv_step
            try:
                bp = b_plane_from_state(r, v_plus, mu)
                jac[0, j] = (bp.b_dot_t - b_t) / dv_step
                jac[1, j] = (bp.b_dot_r - b_r) / dv_step
            except ValueError:
                jac[0, j] = 0.0
                jac[1, j] = 0.0

        # Minimum-norm correction: dV = J^T (J J^T)^-1 (-dB)
        b_error = np.array([-db_t, -db_r])
        jjt = jac @ jac.T + 1e-14 * np.eye(2)
        try:
            coeffs = np.linalg.solve(jjt, b_error)
            dv_correction = jac.T @ coeffs
        except np.linalg.LinAlgError:
            break

        current_v = current_v + dv_correction

    final_state = b_plane_from_state(r, current_v, mu)
    dv_total = current_v - v

    return BPlaneTargetResult(
        dv_vec=dv_total,
        dv_magnitude=float(np.linalg.norm(dv_total)),
        b_dot_t_achieved=final_state.b_dot_t,
        b_dot_r_achieved=final_state.b_dot_r,
        rp_achieved_km=final_state.rp_km,
    )
