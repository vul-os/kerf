"""
kerf_mates.mbd.machinery — Adams/Machinery-equivalent: gear mesh + belt/chain drives.

Implements:
  - Spur-gear mesh dynamics (time-varying stiffness, backlash, ISO 6336 forces)
  - Belt/V-belt drive (Shigley §17 Euler belt equation, tight/slack tensions)
  - Chain drive (polygonal effect, chordal action)

Theory — Gear Mesh
------------------
The tooth-mesh is modelled as a spring-damper along the line of action.
The mesh force F_m is driven by the transmission error e(t) = θ_p/z_p - θ_g/z_g
(the kinematic deviation from perfect conjugate action).  Backlash is included
via a dead-band nonlinearity.

  F_m = k_m · (x_p - x_g - e(t) - b/2·sign(x_p - x_g))    if |x_p-x_g| > b/2
      = 0                                                      otherwise

where x_p, x_g are roll positions on the base circle.

ISO 6336-1:2019 tangential force:
  F_t = P_input / (ω_p · r_p)

Contact ratio:
  ε_α = (√(r_a1² - r_b1²) + √(r_a2² - r_b2²) - C·sin(α)) / (π·m·cos(α))

References
----------
Litvin, F.L., Fuentes, A. (2004). "Gear Geometry and Applied Theory." 2nd ed.,
    Cambridge University Press. §8 (tooth-contact analysis + stiffness).

ISO 6336-1:2019. "Calculation of load capacity of spur and helical gears —
    Part 1: Basic principles." §6 (tooth load factors).

Shigley, J.E., et al. "Mechanical Engineering Design." 10th ed., Ch. 17
    (flexible-drive elements — belt drives).

Disclaimer: for design exploration only — not Adams MSC-accurate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Gear mesh dynamics
# ---------------------------------------------------------------------------

@dataclass
class GearMeshDynamics:
    """Spur-gear pair mesh parameters.

    Attributes
    ----------
    pinion_teeth         : z_p — number of pinion teeth
    gear_teeth           : z_g — number of gear teeth
    module_mm            : ISO module [mm]
    mesh_stiffness_n_per_m : k_m — mean tooth-pair stiffness [N/m]
                           Typical: 1e8–5e8 N/m for steel
                           Reference: Litvin (2004) §8.
    backlash_mm          : total tooth-to-tooth clearance [mm] (default 0.05)
    contact_ratio        : ε_α — if None, computed from geometry
    pressure_angle_deg   : standard pressure angle (default 20°)

    Reference: Litvin (2004) §8; ISO 6336-1:2019 §6.
    """
    pinion_teeth: int
    gear_teeth: int
    module_mm: float
    mesh_stiffness_n_per_m: float
    backlash_mm: float = 0.05
    contact_ratio: float | None = None
    pressure_angle_deg: float = 20.0

    def __post_init__(self):
        if self.contact_ratio is None:
            self.contact_ratio = self._compute_contact_ratio()

    def _compute_contact_ratio(self) -> float:
        """Compute contact ratio ε_α from basic gear geometry.

        ε_α = (√(r_a1² - r_b1²) + √(r_a2² - r_b2²) - C·sin(α)) / (π·m·cos(α))

        where r_a = addendum radius, r_b = base circle radius,
              C = centre distance, α = pressure angle.

        Reference: Litvin (2004) §2.2; ISO 6336-1:2019 §5.
        """
        m = self.module_mm * 1e-3          # module [m]
        alpha = math.radians(self.pressure_angle_deg)
        z1, z2 = self.pinion_teeth, self.gear_teeth

        r1 = 0.5 * m * z1                 # pitch circle radii
        r2 = 0.5 * m * z2
        r_b1 = r1 * math.cos(alpha)        # base circle radii
        r_b2 = r2 * math.cos(alpha)
        r_a1 = r1 + m                      # addendum radii (standard)
        r_a2 = r2 + m

        C = r1 + r2                        # centre distance

        under1 = r_a1**2 - r_b1**2
        under2 = r_a2**2 - r_b2**2

        if under1 < 0 or under2 < 0:
            return 1.0                     # degenerate — return minimum

        numerator = math.sqrt(under1) + math.sqrt(under2) - C * math.sin(alpha)
        denominator = math.pi * m * math.cos(alpha)
        if denominator < 1e-15:
            return 1.0

        return max(1.0, numerator / denominator)

    @property
    def gear_ratio(self) -> float:
        """z_g / z_p — gear ratio (output/input)."""
        return self.gear_teeth / self.pinion_teeth

    @property
    def pitch_radius_pinion_m(self) -> float:
        """Pinion pitch circle radius [m]."""
        return 0.5 * self.module_mm * 1e-3 * self.pinion_teeth

    @property
    def pitch_radius_gear_m(self) -> float:
        """Gear pitch circle radius [m]."""
        return 0.5 * self.module_mm * 1e-3 * self.gear_teeth


def gear_mesh_force(
    omega_p_rad_s: float,
    omega_g_rad_s: float,
    mesh: GearMeshDynamics,
    dt: float,
) -> tuple[float, float]:
    """Tangential and normal tooth-contact force at the mesh point.

    The kinematic transmission error (KTE) is the deviation from conjugate
    motion.  For constant angular velocities the ideal relation is:
        ω_p · z_p = ω_g · z_g  →  ω_p / ω_g = z_g / z_p

    The mesh force is proportional to the transmission error displacement
    on the line of action:
        x_KTE = r_p · θ_p - r_g · θ_g  (accumulated over dt)
              ≈ (ω_p · r_p - ω_g · r_g) · dt

    Backlash dead-band is applied before multiplying by mesh stiffness.

    Returns
    -------
    (F_tangential_N, F_normal_N)

    Reference: Litvin (2004) §8; ISO 6336-1:2019 §6.
    """
    r_p = mesh.pitch_radius_pinion_m
    r_g = mesh.pitch_radius_gear_m
    alpha = math.radians(mesh.pressure_angle_deg)

    # Velocity on pitch circles (m/s)
    v_p = omega_p_rad_s * r_p
    v_g = omega_g_rad_s * r_g

    # Transmission error displacement over dt [m]
    kte = (v_p - v_g) * dt

    # Backlash dead-band
    b_half = 0.5 * mesh.backlash_mm * 1e-3
    if abs(kte) <= b_half:
        # In backlash zone — no mesh force
        return 0.0, 0.0

    kte_eff = kte - math.copysign(b_half, kte)

    # Tangential force at pitch point
    F_t = mesh.mesh_stiffness_n_per_m * abs(kte_eff)

    # Normal force along line of action
    F_n = F_t / math.cos(alpha)

    return F_t, F_n


def iso6336_tangential_force(
    power_w: float,
    omega_pinion_rad_s: float,
    mesh: GearMeshDynamics,
) -> float:
    """ISO 6336-1:2019 §6 nominal tangential force at pitch circle.

        F_t = P / (ω_p · r_p)

    Reference: ISO 6336-1:2019 §6.1.
    """
    r_p = mesh.pitch_radius_pinion_m
    if abs(omega_pinion_rad_s) < 1e-9 or r_p < 1e-9:
        return 0.0
    return abs(power_w) / (abs(omega_pinion_rad_s) * r_p)


# ---------------------------------------------------------------------------
# Belt drive (Shigley §17)
# ---------------------------------------------------------------------------

@dataclass
class BeltDrive:
    """Open flat-belt or V-belt drive between two pulleys.

    The Euler belt equation gives the tension ratio between tight and slack sides:
        T1 / T2 = e^(μ · θ)

    where θ is the angle of wrap on the smaller pulley and μ is the
    coefficient of friction (effective for V-belts: μ_eff = μ/sin(β/2)).

    Reference: Shigley (2014), §17.2.
    """
    pulley_a_radius_m: float             # driving pulley radius [m]
    pulley_b_radius_m: float             # driven pulley radius [m]
    belt_pitch_m: float                  # centre-to-centre distance [m]  (≈ C)
    belt_youngs_modulus_pa: float        # belt stiffness (longitudinal EA) [Pa·m²?]
                                         # treated as effective axial stiffness EA [N]
    pretension_n: float                  # initial belt pretension Ti [N]

    # Friction parameters
    mu: float = 0.35                     # coefficient of friction (flat belt on steel)
    groove_angle_deg: float = 0.0        # 0 = flat belt; 38 = typical V-belt groove
    belt_width_m: float = 0.05          # belt width for stress calculations

    @property
    def is_v_belt(self) -> bool:
        return self.groove_angle_deg > 1.0

    @property
    def mu_eff(self) -> float:
        """Effective friction coefficient for V-belt (Shigley §17.3)."""
        if not self.is_v_belt:
            return self.mu
        beta_half = math.radians(self.groove_angle_deg / 2.0)
        return self.mu / math.sin(beta_half)

    def wrap_angle_small(self) -> float:
        """Angle of wrap on the smaller pulley [rad] (open belt).

        φ = π - 2·arcsin((r_a - r_b) / C)

        Reference: Shigley (2014), §17.2 Eq. 17-1.
        """
        r_a = self.pulley_a_radius_m
        r_b = self.pulley_b_radius_m
        C = self.belt_pitch_m
        r_small = min(r_a, r_b)
        r_large = max(r_a, r_b)
        delta = (r_large - r_small) / max(C, 1e-9)
        delta = min(delta, 1.0)
        # Wrap on SMALL pulley
        phi = math.pi - 2.0 * math.asin(delta)
        return max(phi, 0.1)   # floor at ~6 deg to avoid log(1)

    def tension_ratio(self) -> float:
        """T1/T2 = e^(μ_eff · φ) per Euler belt equation (Shigley §17.2)."""
        return math.exp(self.mu_eff * self.wrap_angle_small())


def belt_drive_force(
    omega_a: float,
    omega_b: float,
    belt: BeltDrive,
) -> tuple[float, float]:
    """Tight-side (T1) and slack-side (T2) belt tensions [N].

    Uses the Euler belt equation:
        T1 / T2 = e^(μ_eff · θ)

    Combined with the pretension constraint (Spotts / Shigley §17.2):
        T1 + T2 ≈ 2 · Ti   (constant if belt elasticity neglected)

    Slip is modelled by the angular velocity mismatch as a perturbation to
    the pretension, scaling the effective friction utilisation.

    Parameters
    ----------
    omega_a : driving pulley angular velocity [rad/s]
    omega_b : driven pulley angular velocity [rad/s]
    belt    : BeltDrive specification

    Returns
    -------
    (T1_tight_n, T2_slack_n)   both in Newtons

    Reference: Shigley (2014), §17.2; Norton (2012), Ch. 11.
    """
    # Kinematic ratio check: ideal ω_b = ω_a · r_a / r_b
    r_a = belt.pulley_a_radius_m
    r_b = belt.pulley_b_radius_m
    Ti = belt.pretension_n

    # Effective torque demand from velocity mismatch
    ideal_omega_b = omega_a * (r_a / max(r_b, 1e-9))
    slip = (ideal_omega_b - omega_b) / (max(abs(ideal_omega_b), 0.1))

    e_ratio = belt.tension_ratio()          # e^(μ_eff θ)

    # At maximum friction (full slip): T1/T2 = e_ratio, T1+T2 = 2Ti
    # At zero slip (no load):          T1 = T2 = Ti
    # Interpolate by |slip| fraction
    slip_frac = min(abs(slip), 1.0)

    # Max tensions at full slip
    T1_max = 2.0 * Ti * e_ratio / (1.0 + e_ratio)
    T2_max = 2.0 * Ti / (1.0 + e_ratio)

    # Actual tensions (linearly interpolated from Ti toward max)
    T1 = Ti + slip_frac * (T1_max - Ti)
    T2 = Ti - slip_frac * (Ti - T2_max)

    return max(T1, 0.0), max(T2, 0.0)


# ---------------------------------------------------------------------------
# Chain drive (polygonal / chordal action)
# ---------------------------------------------------------------------------

@dataclass
class ChainDrive:
    """Roller chain drive with chordal (polygonal) action.

    The chordal velocity variation arises because the chain engages the
    sprocket as a polygon rather than a circle, causing periodic velocity
    fluctuations even at constant input speed.

    Reference: Shigley (2014), §17.4; Norton (2012), §12.4.
    """
    drive_sprocket_teeth: int
    driven_sprocket_teeth: int
    chain_pitch_m: float                  # p — chain pitch [m]
    shaft_centre_m: float                 # C — shaft centre distance [m]

    @property
    def gear_ratio(self) -> float:
        return self.driven_sprocket_teeth / self.drive_sprocket_teeth

    @property
    def chordal_speed_ratio(self) -> float:
        """Peak-to-mean speed variation due to polygon effect.

        Δv/v̄ = 1 - cos(π/N)   (first-order, N = drive sprocket teeth)

        Reference: Shigley (2014) §17.4 Eq. 17-25.
        """
        N = self.drive_sprocket_teeth
        return 1.0 - math.cos(math.pi / N)


def chain_drive_tension(
    omega_drive: float,
    load_torque_nm: float,
    chain: ChainDrive,
) -> dict:
    """Tight-side chain tension and chordal velocity variation.

    Returns
    -------
    dict:
        T_tight_n    : tight-side tension [N]
        T_slack_n    : slack-side tension (centrifugal + catenary estimate) [N]
        v_chain_m_s  : mean chain velocity [m/s]
        delta_v_m_s  : peak chordal velocity variation [m/s]

    Reference: Shigley (2014), §17.4.
    """
    N = chain.drive_sprocket_teeth
    p = chain.chain_pitch_m

    # Pitch circle radius of drive sprocket
    r_drive = p / (2.0 * math.sin(math.pi / N))

    v_chain = abs(omega_drive) * r_drive         # [m/s]
    delta_v = v_chain * chain.chordal_speed_ratio

    # Tight-side from torque
    if r_drive < 1e-9:
        T_tight = 0.0
    else:
        T_tight = abs(load_torque_nm) / r_drive

    # Centrifugal tension estimate: Tc = m_chain · v²  (assume 0.5 kg/m belt mass)
    mass_per_m = 0.5    # conservative kg/m (roller chain ~3–6 kg/m for heavy; 0.5 light)
    Tc = mass_per_m * v_chain**2

    T_slack = Tc         # Slack side ≈ centrifugal only (assume tight >> slack)

    return {
        "T_tight_n": T_tight,
        "T_slack_n": T_slack,
        "v_chain_m_s": v_chain,
        "delta_v_m_s": delta_v,
    }
