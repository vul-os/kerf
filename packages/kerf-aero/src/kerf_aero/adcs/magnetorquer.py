"""Magnetorquer model for spacecraft attitude control.

A magnetorquer generates a torque by interacting with the local geomagnetic
field:
    T = m × B
where m is the magnetic dipole moment [A·m²] and B is the Earth's magnetic
field [T] in the spacecraft body frame.

A simplified World Magnetic Model (WMM) approximation is provided for LEO
orbits using a tilted dipole representation.

References:
    IGRF / WMM: https://www.ngdc.noaa.gov/IAGA/vmod/igrf.html
    Dipole approximation: Wertz, "Spacecraft Attitude Determination and Control"
"""

import numpy as np
from numpy.typing import ArrayLike


# ---------------------------------------------------------------------------
# Geomagnetic field model (simplified tilted dipole)
# ---------------------------------------------------------------------------

# Earth's magnetic dipole moment magnitude [A·m²]
_EARTH_DIPOLE_MOMENT = 8.0e22  # A·m²

# Earth's mean radius [m]
_EARTH_RADIUS = 6.371e6  # m

# Magnetic North pole offset from geographic North [deg] — approximate
_DIPOLE_TILT_DEG = 11.5  # degrees

# μ₀ / (4π) = 1e-7 T·m/A
_MU0_OVER_4PI = 1.0e-7


def _dipole_field_inertial(
    r_eci: np.ndarray,
    epoch_days: float = 0.0,
) -> np.ndarray:
    """Compute the Earth's magnetic field vector in ECI frame at position r_eci.

    Uses a tilted magnetic dipole approximation.

    Parameters
    ----------
    r_eci : (3,) spacecraft position in ECI frame [m]
    epoch_days : days since J2000 (used to rotate dipole axis with Earth rotation)

    Returns
    -------
    B_eci : (3,) magnetic field vector in ECI frame [T]
    """
    # Earth rotation: ~360°/365.25 days for dipole precession (approximate)
    earth_rotation_rad = 2 * np.pi * epoch_days / 365.25
    tilt_rad = np.radians(_DIPOLE_TILT_DEG)

    # Magnetic dipole axis in ECI (tilted from geographic north, rotated with Earth)
    m_hat = np.array([
        np.sin(tilt_rad) * np.cos(earth_rotation_rad),
        np.sin(tilt_rad) * np.sin(earth_rotation_rad),
        np.cos(tilt_rad),
    ])

    r = np.linalg.norm(r_eci)
    r_hat = r_eci / r
    r3 = r ** 3

    # Dipole field: B = (μ₀/4π) * m_total/r³ * (3(m_hat·r_hat)r_hat − m_hat)
    m_total = _EARTH_DIPOLE_MOMENT * _MU0_OVER_4PI
    B_eci = (m_total / r3) * (3.0 * np.dot(m_hat, r_hat) * r_hat - m_hat)
    return B_eci


def earth_magnetic_field_body(
    r_eci: np.ndarray,
    q_body_from_eci: np.ndarray,
    epoch_days: float = 0.0,
) -> np.ndarray:
    """Return Earth's magnetic field in the spacecraft body frame.

    Parameters
    ----------
    r_eci : (3,) spacecraft position in ECI frame [m]
    q_body_from_eci : (4,) quaternion rotating ECI → body frame [w,x,y,z]
    epoch_days : days since J2000

    Returns
    -------
    B_body : (3,) magnetic field in body frame [T]
    """
    from .attitude import qrotate
    B_eci = _dipole_field_inertial(r_eci, epoch_days)
    return qrotate(q_body_from_eci, B_eci)


def leo_circular_orbit_position(
    altitude_km: float,
    inclination_deg: float,
    true_anomaly_deg: float,
    raan_deg: float = 0.0,
) -> np.ndarray:
    """Compute a simple circular LEO position vector in ECI [m].

    Parameters
    ----------
    altitude_km : orbit altitude above Earth's surface [km]
    inclination_deg : orbital inclination [deg]
    true_anomaly_deg : current true anomaly [deg]
    raan_deg : right ascension of the ascending node [deg]

    Returns
    -------
    r_eci : (3,) position vector in ECI frame [m]
    """
    r = (_EARTH_RADIUS + altitude_km * 1e3)
    nu = np.radians(true_anomaly_deg)
    inc = np.radians(inclination_deg)
    raan = np.radians(raan_deg)

    # Position in orbital plane
    x_orb = r * np.cos(nu)
    y_orb = r * np.sin(nu)

    # Rotate to ECI via RAAN and inclination
    # x_eci = Rz(-RAAN) @ Rx(-inc) @ [x_orb, y_orb, 0]
    cos_raan, sin_raan = np.cos(raan), np.sin(raan)
    cos_inc, sin_inc = np.cos(inc), np.sin(inc)

    x_eci = (cos_raan * x_orb - sin_raan * cos_inc * y_orb)
    y_eci = (sin_raan * x_orb + cos_raan * cos_inc * y_orb)
    z_eci = sin_inc * y_orb

    return np.array([x_eci, y_eci, z_eci])


# ---------------------------------------------------------------------------
# Magnetorquer
# ---------------------------------------------------------------------------

class Magnetorquer:
    """Single-axis magnetorquer (current coil or permanent magnet rod).

    Parameters
    ----------
    axis : (3,) unit dipole axis in body frame
    max_dipole : maximum magnetic dipole moment [A·m²]
    """

    def __init__(self, axis: ArrayLike, max_dipole: float = 1.0):
        axis = np.asarray(axis, dtype=float)
        n = np.linalg.norm(axis)
        if n < 1e-15:
            raise ValueError("Magnetorquer axis must be non-zero")
        self.axis = axis / n
        self.max_dipole = float(max_dipole)

    def torque(self, dipole_cmd: float, B_body: np.ndarray) -> np.ndarray:
        """Compute body-frame torque for a scalar dipole command.

        Parameters
        ----------
        dipole_cmd : commanded dipole moment [A·m²] (clamped to max_dipole)
        B_body : (3,) local magnetic field in body frame [T]

        Returns
        -------
        T : (3,) torque vector [N·m]
        """
        m_scalar = float(np.clip(dipole_cmd, -self.max_dipole, self.max_dipole))
        m_vec = m_scalar * self.axis
        return np.cross(m_vec, B_body)


class MagnetorquerCluster:
    """Cluster of three orthogonal magnetorquers.

    Standard configuration: one along each body axis (x, y, z).

    Parameters
    ----------
    rods : list of Magnetorquer (must have 3 elements for a full cluster)
    """

    def __init__(self, rods: list[Magnetorquer]):
        self.rods = list(rods)
        n = len(rods)
        axes = np.zeros((3, n))
        for i, rod in enumerate(rods):
            axes[:, i] = rod.axis
        self.axes = axes  # (3, N)

    @classmethod
    def orthogonal_3(cls, max_dipole: float = 1.0) -> "MagnetorquerCluster":
        """Construct a standard 3-axis orthogonal magnetorquer cluster."""
        rods = [
            Magnetorquer(np.array([1.0, 0.0, 0.0]), max_dipole),
            Magnetorquer(np.array([0.0, 1.0, 0.0]), max_dipole),
            Magnetorquer(np.array([0.0, 0.0, 1.0]), max_dipole),
        ]
        return cls(rods)

    def torque(self, dipole_cmds: ArrayLike, B_body: np.ndarray) -> np.ndarray:
        """Compute total body torque from dipole commands.

        Parameters
        ----------
        dipole_cmds : (N,) commanded dipole moments [A·m²]
        B_body : (3,) local magnetic field in body frame [T]

        Returns
        -------
        T : (3,) total torque vector [N·m]
        """
        dipole_cmds = np.asarray(dipole_cmds, dtype=float)
        # Total dipole moment vector
        m_vec = self.axes @ dipole_cmds
        return np.cross(m_vec, B_body)

    def b_dot_command(
        self,
        B_body: np.ndarray,
        Bdot_body: np.ndarray,
        gain: float = 1e6,
    ) -> np.ndarray:
        """B-dot detumbling control law.

        Generates dipole commands proportional to the negative of B_dot
        to dissipate angular momentum.

        Parameters
        ----------
        B_body : (3,) current magnetic field in body frame [T]
        Bdot_body : (3,) time derivative of B in body frame [T/s]
        gain : control gain [A·m²·s/T]

        Returns
        -------
        dipole_cmds : (3,) commanded dipole moments [A·m²]
        """
        # Command: m = -k * B_dot / |B|²
        B_mag2 = np.dot(B_body, B_body)
        if B_mag2 < 1e-30:
            return np.zeros(len(self.rods))
        m_cmd = -gain * Bdot_body / B_mag2
        # Project onto individual rod axes and clamp
        cmds = np.array([
            float(np.clip(np.dot(m_cmd, rod.axis), -rod.max_dipole, rod.max_dipole))
            for rod in self.rods
        ])
        return cmds
