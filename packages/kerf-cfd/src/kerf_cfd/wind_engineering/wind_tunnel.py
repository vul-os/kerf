"""
Building wind loads and bluff-body aerodynamics.

Overview
--------
Implements ASCE 7-22 power-law wind profiles, building surface pressure
coefficients (Cp), drag, base shear, and overturning moment, together with
analytical bluff-body phenomena:

  * Vortex shedding frequency — Bearman (1984) St = f·D/v
  * Den Hartog galloping criterion — v_cr = 4·m·ξ·f_n·H / (ρ·Cl_α)

HONEST FLAG: This module uses the simplified ASCE 7-22 §26.6 Cp approach
(windward Cp = +0.8, leeward Cp = −0.5, side Cp = −0.7).  Buildings taller
than 60 m and unusual geometries require full wind-tunnel physical testing or
validated LES/DES CFD, which is beyond the scope of this module.

References
----------
ASCE 7-22: "Minimum Design Loads and Associated Criteria for Buildings and
Other Structures," Chapters 26–31.

Bearman, P.W. (1984). "Vortex Shedding from Oscillating Bluff Bodies."
Annual Review of Fluid Mechanics, 16, 195–222.

Holmes, J.D. (2018). "Wind Loading of Structures," 3rd ed. CRC Press.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# ASCE 7-22 exposure parameters
# ---------------------------------------------------------------------------

# ASCE 7-22 Table 26.10-1 — power-law exponent α and gradient height z_g [m]
# Exposure B: urban/suburban; C: open terrain; D: flat/open water
_EXPOSURE_PARAMS: dict[str, dict] = {
    "B": {"alpha": 0.250, "z_g_m": 365.76},  # 1200 ft
    "C": {"alpha": 0.143, "z_g_m": 274.32},  # 900 ft
    "D": {"alpha": 0.111, "z_g_m": 213.36},  # 700 ft
}

_Z_REF_M = 10.0        # Reference height [m] — ASCE 7-22 §26.5.1
_AIR_DENSITY = 1.225   # kg/m³ at sea level, 15 °C

# ASCE 7-22 §26.6 Cp values (simplified, rectangular buildings)
_CP_WINDWARD = 0.8
_CP_LEEWARD  = -0.5
_CP_SIDE     = -0.7
_CP_ROOF_FLAT = -0.7   # Flat roof (pressure suction)

# Gust factor for peak pressure — ASCE 7-22 §26.11 simplified approach
_GUST_FACTOR = 0.85    # G (gust factor, rigid structure, Exposure C)
_PEAK_MULTIPLIER = 1.5 / _GUST_FACTOR  # converts mean → peak (~1.76)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WindProfile:
    """
    ASCE 7-22 Exposure Category power-law wind profile.

    Parameters
    ----------
    exposure : str
        ASCE 7-22 Exposure Category: ``'B'`` (urban/suburban),
        ``'C'`` (open terrain/scattered obstructions), or
        ``'D'`` (flat/open coastal).
    reference_velocity_m_s : float
        Basic wind speed v_ref at z_ref = 10 m [m/s], corresponding to
        the ASCE 7-22 3-second-gust speed at 10 m above ground in
        Exposure C (or as specified by the designer).

    Notes
    -----
    The power-law profile is:

        v(z) = v_ref · (z / z_ref)^α

    where α is the terrain roughness exponent from ASCE 7-22 Table 26.10-1
    and z_ref = 10 m.  The gradient height z_g is used as an upper cap.

    References
    ----------
    ASCE 7-22 §26.10.1 — "Velocity pressure exposure coefficient."
    Holmes (2018) §3.2 — "Wind speed profiles."
    """

    exposure: str
    reference_velocity_m_s: float

    def _params(self) -> dict:
        expo = self.exposure.upper()
        if expo not in _EXPOSURE_PARAMS:
            raise ValueError(
                f"Unknown ASCE 7-22 exposure '{self.exposure}'. "
                f"Must be one of: {list(_EXPOSURE_PARAMS)}"
            )
        return _EXPOSURE_PARAMS[expo]

    def velocity_at(self, height_m: float) -> float:
        """
        Mean wind speed at elevation ``height_m`` [m].

        v(z) = v_ref · (z / z_ref)^α   for z ≤ z_g
                                        = v(z_g)  for z > z_g

        ASCE 7-22 Table 26.10-1.

        Parameters
        ----------
        height_m : float
            Height above ground [m].  Clipped to z_min = 0.5 m.

        Returns
        -------
        float
            Wind speed [m/s].
        """
        p = self._params()
        alpha = p["alpha"]
        z_g = p["z_g_m"]
        z = max(0.5, height_m)
        z_eff = min(z, z_g)
        return float(self.reference_velocity_m_s * (z_eff / _Z_REF_M) ** alpha)


@dataclass
class BuildingGeometry:
    """
    Simplified building geometry for wind-load calculations.

    Parameters
    ----------
    name : str
        Identifier label.
    footprint_polygon : list[tuple[float, float]]
        Ordered (x, y) vertices of the building footprint [m].
        Should form a closed polygon; the first vertex need not be
        repeated.  Convex polygons assumed.
    height_m : float
        Total building height above ground [m].
    roof_type : str
        ``'flat'`` | ``'gable'`` | ``'hip'`` | ``'mansard'``.
        Controls the roof pressure coefficient selection.
    """

    name: str
    footprint_polygon: list
    height_m: float
    roof_type: str = "flat"

    def footprint_area_m2(self) -> float:
        """Footprint area via shoelace formula [m²]."""
        pts = np.asarray(self.footprint_polygon, dtype=float)
        n = len(pts)
        if n < 3:
            return 0.0
        xs, ys = pts[:, 0], pts[:, 1]
        return float(abs(
            np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1))
        ) / 2.0)

    def projected_width_m(self, yaw_deg: float = 0.0) -> float:
        """
        Projected width (face perpendicular to wind) at given yaw angle [m].

        Rotates the footprint polygon and returns its extent along the
        wind axis (x after rotation).
        """
        pts = np.asarray(self.footprint_polygon, dtype=float)
        theta = math.radians(yaw_deg)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        rotated_x = pts[:, 0] * cos_t + pts[:, 1] * sin_t
        rotated_y = -pts[:, 0] * sin_t + pts[:, 1] * cos_t
        # Width = extent in y-direction (lateral to wind)
        width = float(rotated_y.max() - rotated_y.min())
        return max(width, 1e-6)

    def projected_depth_m(self, yaw_deg: float = 0.0) -> float:
        """Building depth along wind direction [m]."""
        pts = np.asarray(self.footprint_polygon, dtype=float)
        theta = math.radians(yaw_deg)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        rotated_x = pts[:, 0] * cos_t + pts[:, 1] * sin_t
        depth = float(rotated_x.max() - rotated_x.min())
        return max(depth, 1e-6)

    def windward_wall_area_m2(self, yaw_deg: float = 0.0) -> float:
        """Windward face projected area [m²]."""
        return self.projected_width_m(yaw_deg) * self.height_m

    def roof_area_m2(self) -> float:
        """Roof area [m²] — same as footprint for flat/hip/gable simplified."""
        return self.footprint_area_m2()


@dataclass
class WindPressureReport:
    """
    Wind pressure and force results for a building.

    Attributes
    ----------
    mean_pressure_pa : dict[str, float]
        Face identifier → mean wind pressure [Pa].
        Keys: ``'windward'``, ``'leeward'``, ``'side_left'``,
        ``'side_right'``, ``'roof'``.
        Positive = pressure (pushing in); negative = suction (pulling out).
    peak_pressure_pa : dict[str, float]
        Peak gust pressures (mean × 1.5 / G ≈ ×1.76).
    drag_coefficient : float
        Overall building drag coefficient Cd = F_drag / (0.5·ρ·v_h²·A_proj).
    overturning_moment_kn_m : float
        Overturning moment at base [kN·m].
    base_shear_kn : float
        Total horizontal wind base shear [kN].
    velocity_pressure_pa : float
        Dynamic pressure q_h = 0.5·ρ·v_h² at building height [Pa].
    """

    mean_pressure_pa: dict
    peak_pressure_pa: dict
    drag_coefficient: float
    overturning_moment_kn_m: float
    base_shear_kn: float
    velocity_pressure_pa: float = 0.0


# ---------------------------------------------------------------------------
# Core wind-load function
# ---------------------------------------------------------------------------

def compute_wind_load_aerodynamic(
    building: BuildingGeometry,
    wind: WindProfile,
    yaw_deg: float = 0.0,
) -> WindPressureReport:
    """
    Compute ASCE 7-22 §26.6 wind pressures, drag, base shear, and overturning
    moment for a rectangular building.

    Method
    ------
    1. Evaluate mean wind speed v_h at building height using the exposure
       power-law profile.
    2. Dynamic pressure: q_h = 0.5 · ρ · v_h²
    3. Surface pressures: p = G · Cp · q_h
       Cp: windward +0.8, leeward −0.5, side −0.7, flat roof −0.7.
    4. Net drag (windward + leeward contributions):
       F_D = (G · Cp_w − G · Cp_l) · q_h · A_windward
    5. Cd = F_D / (q_h · A_windward)
    6. Overturning moment via tributary height = H/2 (simplified uniform
       pressure distribution).

    Parameters
    ----------
    building : BuildingGeometry
    wind : WindProfile
    yaw_deg : float
        Wind direction yaw angle [degrees] from building normal (0 = head-on).

    Returns
    -------
    WindPressureReport

    HONEST: Simplified ASCE 7-22 §26.6 Cp approach.  Full CFD or physical
    wind-tunnel testing required for tall buildings (h > 60 m) or complex
    geometry.

    References
    ----------
    ASCE 7-22 §26.6, §26.10, §26.11, §27.2.
    Holmes (2018) §4.2 — "Bluff body aerodynamics."
    """
    if building.height_m <= 0:
        raise ValueError("building.height_m must be positive")

    v_h = wind.velocity_at(building.height_m)
    q_h = 0.5 * _AIR_DENSITY * v_h ** 2  # dynamic pressure at roof level [Pa]

    G = _GUST_FACTOR  # rigid structure gust factor

    # Surface mean pressures
    p_windward = G * _CP_WINDWARD * q_h    # +ve (pressure)
    p_leeward  = G * _CP_LEEWARD  * q_h   # -ve (suction)
    p_side     = G * _CP_SIDE     * q_h   # -ve (suction)

    # Roof Cp — ASCE 7-22 §27.3 flat roof simplified
    if building.roof_type == "flat":
        cp_roof = _CP_ROOF_FLAT
    elif building.roof_type in ("gable", "hip"):
        cp_roof = -0.5  # gable: less suction near ridge
    elif building.roof_type == "mansard":
        cp_roof = -0.6
    else:
        cp_roof = _CP_ROOF_FLAT

    p_roof = G * cp_roof * q_h  # -ve (suction) for flat/nearly flat

    mean_pressures = {
        "windward":   float(p_windward),
        "leeward":    float(p_leeward),
        "side_left":  float(p_side),
        "side_right": float(p_side),
        "roof":       float(p_roof),
    }

    peak_pressures = {k: float(v * _PEAK_MULTIPLIER) for k, v in mean_pressures.items()}

    # Windward wall area (projected area perpendicular to wind)
    A_w = building.windward_wall_area_m2(yaw_deg)

    # Net drag force: windward pressure pushes in, leeward suction pulls back
    # F_drag = (p_windward - p_leeward) * A_windward
    # (leeward p is negative, so this is additive)
    F_drag_N = (p_windward - p_leeward) * A_w  # [N]

    # Drag coefficient: Cd = F_D / (q_h * A_proj)
    Cd = float(F_drag_N / max(q_h * A_w, 1e-6))

    # Base shear = net drag force [N] → [kN]
    base_shear_kn = float(F_drag_N / 1000.0)

    # Overturning moment — simplified: assume uniform pressure, resultant at H/2
    # M_OT = F_drag * H/2
    overturning_moment_kn_m = float(F_drag_N * building.height_m / 2.0 / 1000.0)

    return WindPressureReport(
        mean_pressure_pa=mean_pressures,
        peak_pressure_pa=peak_pressures,
        drag_coefficient=Cd,
        overturning_moment_kn_m=overturning_moment_kn_m,
        base_shear_kn=base_shear_kn,
        velocity_pressure_pa=float(q_h),
    )


# ---------------------------------------------------------------------------
# Bluff-body aerodynamics
# ---------------------------------------------------------------------------

def vortex_shedding_frequency(
    body_width_m: float,
    velocity_m_s: float,
    strouhal_number: float = 0.2,
) -> float:
    """
    Vortex shedding frequency from a bluff body.

    Implements the Strouhal relation:

        f_s = St · v / D

    where St ≈ 0.2 for a wide range of bluff-body cross-sections (rectangular
    buildings, circular cylinders above Re ~ 10³).

    Parameters
    ----------
    body_width_m : float
        Characteristic body dimension D perpendicular to flow [m].
    velocity_m_s : float
        Incident wind speed [m/s].
    strouhal_number : float
        Strouhal number (dimensionless).  Default 0.2 per Bearman (1984)
        for a sharp-edged rectangular section.

    Returns
    -------
    float
        Vortex shedding frequency [Hz].

    Notes
    -----
    Critical when f_s approaches the natural frequency of the structure —
    lock-in can cause resonant oscillations.  See Holmes (2018) §6.3.

    References
    ----------
    Bearman, P.W. (1984). Ann. Rev. Fluid Mech. 16, 195–222.
    Holmes, J.D. (2018). "Wind Loading of Structures." §6.3.
    """
    if body_width_m <= 0:
        raise ValueError("body_width_m must be positive")
    if velocity_m_s < 0:
        raise ValueError("velocity_m_s must be non-negative")
    return float(strouhal_number * velocity_m_s / body_width_m)


def galloping_critical_velocity(
    building: BuildingGeometry,
    damping_ratio: float = 0.02,
    natural_frequency_hz: Optional[float] = None,
    mass_per_unit_height_kg_m: Optional[float] = None,
    cl_alpha: Optional[float] = None,
) -> float:
    """
    Den Hartog galloping onset velocity.

    The Den Hartog (1932) criterion gives the critical wind speed at which
    a flexible building/structure begins transverse galloping oscillations:

        v_cr = 4 · m · ξ · ω_n / (ρ · B · (-dCl/dα))

    where:
      m   = mass per unit length [kg/m]
      ξ   = structural damping ratio (fraction of critical)
      ω_n = natural frequency [rad/s]
      ρ   = air density [kg/m³]
      B   = building width perpendicular to flow [m]
      Cl_α = |dCl/dα| ≈ 2π for an aerofoil-like section; use 3.0–4.0 for
             a rectangular building cross-section (Holmes 2018 §6.4).

    Parameters
    ----------
    building : BuildingGeometry
    damping_ratio : float
        Structural damping ratio ξ (fraction of critical, e.g. 0.02 = 2 %).
    natural_frequency_hz : float, optional
        Fundamental natural frequency of the building [Hz].
        If None, estimated empirically as f_n ≈ 46 / H (ASCE 7-22 §26.9.1).
    mass_per_unit_height_kg_m : float, optional
        Mass per unit height [kg/m].
        If None, estimated as ρ_structure · A_footprint where
        ρ_structure = 250 kg/m² typical (Holmes 2018 §6.1).
    cl_alpha : float, optional
        Lift-slope coefficient |dCl/dα| (per radian).
        Default 3.0 (rectangular section, Holmes 2018 §6.4).

    Returns
    -------
    float
        Galloping critical velocity v_cr [m/s].

    References
    ----------
    Holmes, J.D. (2018). "Wind Loading of Structures," §6.4.
    Den Hartog, J.P. (1932). "Transmission Line Vibration Due to Sleet."
    Trans. AIEE 51(4), 1074–1076.
    """
    # Defaults
    if natural_frequency_hz is None:
        # Empirical: f_n ≈ 46 / H (ASCE 7-22 Eq. 26.9-1, metric)
        natural_frequency_hz = 46.0 / max(building.height_m, 1.0)

    if mass_per_unit_height_kg_m is None:
        # Typical: 250 kg/m² of floor area times footprint / height fraction
        area = building.footprint_area_m2()
        mass_per_unit_height_kg_m = max(250.0 * area / max(building.height_m, 1.0), 1.0)

    if cl_alpha is None:
        cl_alpha = 3.0  # rectangular section (Holmes 2018 §6.4)

    omega_n = 2.0 * math.pi * natural_frequency_hz  # [rad/s]
    B = building.projected_width_m(0.0)              # width perpendicular to flow [m]

    # Den Hartog formula
    v_cr = (4.0 * mass_per_unit_height_kg_m * damping_ratio * omega_n) / (
        _AIR_DENSITY * B * max(cl_alpha, 1e-6)
    )
    return float(v_cr)
