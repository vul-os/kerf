"""
kerf_mates.mbd.vehicle_dynamics — Adams/Car-equivalent vehicle dynamics.

Implements:
  - Pacejka 'Magic Formula' (MF) tire model (2012 3rd ed.)
  - McPherson / double-wishbone suspension model
  - Single-track (bicycle) model with weight transfer and Pacejka tire forces
  - Steady-state cornering analysis

Theory
------
The single-track (bicycle) vehicle model collapses left/right wheels into a
single front and rear wheel.  The lateral load transfer due to cornering and
longitudinal transfer due to braking/acceleration modify the normal loads on
each axle.  The Pacejka Magic Formula maps slip angle (lateral) and slip ratio
(longitudinal) to tyre forces with high fidelity for small-to-moderate inputs.

Pacejka Magic Formula (simplified, no combined slip):
    F = D · sin(C · arctan(B·α - E·(B·α - arctan(B·α))))
where B, C, D, E are the shape/stiffness/peak/curvature factors.

References
----------
Pacejka, H.B. (2012). "Tire and Vehicle Dynamics." 3rd ed., Ch. 4.
    Butterworth-Heinemann / Elsevier.  §4.3 longitudinal, §4.4 lateral.

Rajamani, R. (2012). "Vehicle Dynamics and Control." 2nd ed., Springer.
    Ch. 2 (single-track / bicycle model).

Disclaimer: for design exploration only — not Adams MSC-accurate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Pacejka 'Magic Formula' tire model (2012, simplified)
# ---------------------------------------------------------------------------

@dataclass
class TireModel:
    """Pacejka 'Magic Formula' simplified tire model.

    Defaults tuned for a typical passenger-car tire on dry asphalt.

    Longitudinal (§4.3):
        Fx(κ) = Dx · sin(Cx · arctan(Bx·κ - Ex·(Bx·κ - arctan(Bx·κ))))

    Lateral (§4.4):
        Fy(α) = Dy · sin(Cy · arctan(By·α - Ey·(By·α - arctan(By·α))))

    where the peak force ≈ D · Fz  (linear in normal load, first-order scaling).

    Reference: Pacejka (2012), §4.3–4.4.
    """
    # Longitudinal parameters (dry asphalt typical)
    Bx: float = 10.0     # stiffness factor
    Cx: float = 1.65     # shape factor
    Dx: float = 1.2      # peak factor (≈ μ_x)
    Ex: float = -0.7     # curvature factor

    # Lateral parameters
    By: float = 12.0
    Cy: float = 1.30
    Dy: float = 1.0      # peak lateral ≈ μ_y
    Ey: float = -1.6

    def _mf(self, B: float, C: float, D: float, E: float, x: float) -> float:
        """Core Magic Formula evaluation (no combined slip, no offsets)."""
        Bx_val = B * x
        return D * math.sin(C * math.atan(Bx_val - E * (Bx_val - math.atan(Bx_val))))

    def Fx(self, slip_ratio: float, normal_load_n: float) -> float:
        """Longitudinal tyre force [N].

        Parameters
        ----------
        slip_ratio     : κ — (v_wheel - v_vehicle) / v_vehicle (braking < 0)
        normal_load_n  : Fz [N]

        Returns
        -------
        Fx [N] positive = forward traction

        Reference: Pacejka (2012), §4.3.
        """
        if normal_load_n <= 0.0:
            return 0.0
        return self._mf(self.Bx, self.Cx, self.Dx, self.Ex, slip_ratio) * normal_load_n

    def Fy(self, slip_angle_rad: float, normal_load_n: float) -> float:
        """Lateral tyre force [N].

        Parameters
        ----------
        slip_angle_rad : α [rad] — positive = steer left
        normal_load_n  : Fz [N]

        Returns
        -------
        Fy [N] positive = left (SAE sign convention flipped to ISO here)

        Reference: Pacejka (2012), §4.4.
        """
        if normal_load_n <= 0.0:
            return 0.0
        return self._mf(self.By, self.Cy, self.Dy, self.Ey, slip_angle_rad) * normal_load_n


# ---------------------------------------------------------------------------
# Suspension
# ---------------------------------------------------------------------------

@dataclass
class SuspensionLink:
    """Simplified MacPherson strut or double-wishbone suspension.

    Models vertical spring-damper compliance.  For vehicle-level simulation
    the suspension travel is computed from the wheel normal load and the spring
    rate; the damper resists the rate of change of wheel travel.

    Reference: Milliken & Milliken (1995). "Race Car Vehicle Dynamics." SAE.
    """
    kind: str = "mcpherson"            # 'mcpherson' | 'double_wishbone'
    spring_rate_n_per_m: float = 25_000.0
    damper_rate_n_s_per_m: float = 2_500.0
    arm_length_m: float = 0.30         # control arm length [m]

    def wheel_travel(self, delta_load_n: float) -> float:
        """Quasi-static wheel travel [m] for a given incremental load [N]."""
        return delta_load_n / self.spring_rate_n_per_m

    def damper_force(self, travel_rate_m_s: float) -> float:
        """Damper force [N] opposing motion."""
        return -self.damper_rate_n_s_per_m * travel_rate_m_s


# ---------------------------------------------------------------------------
# Vehicle specification
# ---------------------------------------------------------------------------

@dataclass
class VehicleSpec:
    """Full vehicle specification for single-track dynamic model.

    Default values approximate a compact passenger car.
    """
    mass_kg: float = 1_200.0
    wheelbase_m: float = 2.65
    cg_height_m: float = 0.55
    # Distance from CG to front/rear axle (from wheelbase + cg_ratio)
    cg_front_ratio: float = 0.45    # fraction of wheelbase ahead of CG
    front_tire: TireModel = field(default_factory=TireModel)
    rear_tire: TireModel = field(default_factory=TireModel)
    front_suspension: SuspensionLink = field(default_factory=SuspensionLink)
    rear_suspension: SuspensionLink = field(default_factory=SuspensionLink)

    # Aerodynamic drag (simplified)
    drag_coefficient: float = 0.30
    frontal_area_m2: float = 2.20
    air_density_kg_m3: float = 1.225

    # Drive configuration
    drive: str = "rear"             # 'front' | 'rear' | 'all'

    @property
    def a_m(self) -> float:
        """Distance from front axle to CG [m]."""
        return self.cg_front_ratio * self.wheelbase_m

    @property
    def b_m(self) -> float:
        """Distance from CG to rear axle [m]."""
        return (1.0 - self.cg_front_ratio) * self.wheelbase_m

    @property
    def g(self) -> float:
        return 9.81


# ---------------------------------------------------------------------------
# State dict keys
# ---------------------------------------------------------------------------
# 'x', 'y'          : position [m]
# 'psi'             : heading [rad]
# 'vx', 'vy'        : body-frame velocities [m/s]
# 'r'               : yaw rate [rad/s]
# 'ax', 'ay'        : accelerations [m/s²]
# 'Fz_front'        : front normal load [N]
# 'Fz_rear'         : rear normal load [N]
# 'alpha_f'         : front slip angle [rad]
# 'alpha_r'         : rear slip angle [rad]


def _static_load(spec: VehicleSpec) -> tuple[float, float]:
    """Static front and rear axle loads [N]."""
    L = spec.wheelbase_m
    W = spec.mass_kg * spec.g
    Fz_f = W * spec.b_m / L
    Fz_r = W * spec.a_m / L
    return Fz_f, Fz_r


def step_vehicle(
    state: dict,
    spec: VehicleSpec,
    steering_rad: float,
    throttle: float,       # [0, 1]
    brake: float,          # [0, 1]
    dt: float,
) -> dict:
    """Single-track bicycle model step with weight transfer and Pacejka tires.

    Integrates the planar equations of motion:
        m (v̇x - r·vy) = Fx_f + Fx_r - Faero
        m (v̇y + r·vx) = Fy_f + Fy_r
        Iz r̈ = a·Fy_f - b·Fy_r

    Longitudinal weight transfer (braking/traction):
        ΔFz = m·ax·h / L

    Lateral weight transfer is lumped into the bicycle (single track = no roll).

    Parameters
    ----------
    state       : dict (see key list above; pass empty dict for initial step)
    spec        : VehicleSpec
    steering_rad: front wheel steer angle δ [rad]
    throttle    : [0, 1] normalised engine torque request
    brake       : [0, 1] normalised brake pressure
    dt          : time step [s]

    Returns
    -------
    Updated state dict.

    Reference: Rajamani (2012), Ch. 2; Pacejka (2012) §4.3–4.4.
    """
    g = spec.g
    m = spec.mass_kg
    L = spec.wheelbase_m
    a = spec.a_m
    b = spec.b_m
    h = spec.cg_height_m
    Iz = m * (a**2 + b**2) / 3.0   # simple yaw inertia estimate

    # Defaults for first call
    vx = state.get("vx", 10.0)     # [m/s] default 36 km/h
    vy = state.get("vy", 0.0)
    r = state.get("r", 0.0)
    x = state.get("x", 0.0)
    y = state.get("y", 0.0)
    psi = state.get("psi", 0.0)

    V = max(math.sqrt(vx**2 + vy**2), 0.1)   # total speed (floor 0.1 m/s)

    # ── Aerodynamic drag ──────────────────────────────────────────────────
    Faero = 0.5 * spec.air_density_kg_m3 * spec.drag_coefficient * spec.frontal_area_m2 * vx**2

    # ── Longitudinal force (engine / brake) ───────────────────────────────
    # Simplified: treat wheel slip ratio ≈ 0 for throttle / small for brake
    MAX_DRIVE_FORCE = 0.3 * m * g      # ~30% of weight (typical peak μ×0.25)
    MAX_BRAKE_FORCE = 0.9 * m * g      # ~90% of weight (ABS limit)
    Fx_drive = throttle * MAX_DRIVE_FORCE
    Fx_brake = -brake * MAX_BRAKE_FORCE
    Fx_total = Fx_drive + Fx_brake     # positive = forward

    # ── Longitudinal acceleration (before normal load update) ─────────────
    ax_approx = (Fx_total - Faero) / m

    # ── Normal load with longitudinal weight transfer ─────────────────────
    Fz_f_static, Fz_r_static = _static_load(spec)
    delta_Fz_long = m * ax_approx * h / L
    Fz_f = Fz_f_static - delta_Fz_long   # braking loads front (+ax_approx<0)
    Fz_r = Fz_r_static + delta_Fz_long
    Fz_f = max(Fz_f, 0.0)
    Fz_r = max(Fz_r, 0.0)

    # ── Slip angles ───────────────────────────────────────────────────────
    # Front: α_f = δ - arctan((vy + a·r) / vx)
    # Rear:  α_r =   -arctan((vy - b·r) / vx)
    vy_f = vy + a * r
    vy_r = vy - b * r
    alpha_f = steering_rad - math.atan2(vy_f, max(abs(vx), 0.1)) * math.copysign(1.0, vx)
    alpha_r = -math.atan2(vy_r, max(abs(vx), 0.1)) * math.copysign(1.0, vx)

    # ── Lateral tyre forces (Pacejka) ─────────────────────────────────────
    Fy_f = spec.front_tire.Fy(alpha_f, Fz_f)
    Fy_r = spec.rear_tire.Fy(alpha_r, Fz_r)

    # ── Distribute longitudinal force ─────────────────────────────────────
    if spec.drive == "front":
        Fx_f = Fx_total
        Fx_r = 0.0
    elif spec.drive == "rear":
        Fx_f = 0.0
        Fx_r = Fx_total
    else:  # all
        Fx_f = 0.5 * Fx_total
        Fx_r = 0.5 * Fx_total

    # Braking shared proportionally to Fz
    total_Fz = Fz_f + Fz_r + 1e-9
    Fx_f_brk = Fx_brake * Fz_f / total_Fz
    Fx_r_brk = Fx_brake * Fz_r / total_Fz
    Fx_f = Fx_drive * (1.0 if spec.drive == "front" else 0.0) + Fx_f_brk
    Fx_r = Fx_drive * (1.0 if spec.drive == "rear" else 0.5) + Fx_r_brk
    if spec.drive == "all":
        Fx_f = 0.5 * Fx_drive + Fx_f_brk
        Fx_r = 0.5 * Fx_drive + Fx_r_brk

    # ── Equations of motion ───────────────────────────────────────────────
    # Longitudinal (body-frame)
    ax = (Fx_f + Fx_r - Faero) / m + vy * r
    # Lateral
    ay = (Fy_f + Fy_r) / m - vx * r
    # Yaw
    r_dot = (a * Fy_f - b * Fy_r) / Iz

    # ── Euler integration ─────────────────────────────────────────────────
    vx_new = vx + ax * dt
    vy_new = vy + ay * dt
    r_new = r + r_dot * dt

    # Body-frame to world
    psi_new = psi + r * dt
    x_new = x + (vx * math.cos(psi) - vy * math.sin(psi)) * dt
    y_new = y + (vx * math.sin(psi) + vy * math.cos(psi)) * dt

    return {
        "x": x_new,
        "y": y_new,
        "psi": psi_new,
        "vx": max(vx_new, 0.0),   # no reverse for simplicity
        "vy": vy_new,
        "r": r_new,
        "ax": ax - vy * r,         # body-frame without Coriolis for reporting
        "ay": ay + vx * r,
        "Fz_front": Fz_f,
        "Fz_rear": Fz_r,
        "alpha_f": alpha_f,
        "alpha_r": alpha_r,
        "Fy_front": Fy_f,
        "Fy_rear": Fy_r,
    }


def steady_state_cornering(
    spec: VehicleSpec,
    speed_m_s: float,
    radius_m: float,
) -> dict:
    """Steady-state cornering analysis using the bicycle model.

    At steady state: r = V / R, vy constant, ay = V²/R.

    Solves for the required steering angle δ such that lateral equilibrium and
    yaw-moment equilibrium are satisfied (linear-slip approximation for initial
    estimate, then Pacejka refinement).

    Returns
    -------
    dict with keys:
        steering_rad    : front-wheel steer angle [rad]
        steering_deg    : front-wheel steer angle [deg]
        alpha_f_rad     : front slip angle [rad]
        alpha_r_rad     : rear slip angle [rad]
        lateral_g       : lateral acceleration / g
        understeer_grad : dδ/d(ay/g)  [rad/g] — positive = understeer
        Fz_front_n      : front normal load [N]
        Fz_rear_n       : rear normal load [N]
        ok              : bool

    Reference: Pacejka (2012), §4; Rajamani (2012), Ch. 2.
    """
    g = spec.g
    V = speed_m_s
    R = radius_m
    m = spec.mass_kg
    a = spec.a_m
    b = spec.b_m
    L = spec.wheelbase_m

    if R <= 0 or V <= 0:
        return {"ok": False, "reason": "radius and speed must be positive"}

    ay = V**2 / R                           # centripetal acceleration [m/s²]
    lateral_g = ay / g

    # Static normal loads
    Fz_f, Fz_r = _static_load(spec)

    # ── Linear estimate: slip angles from cornering stiffnesses ──────────
    # C_α ≈ 2 × B × C × D × Fz  (Pacejka linearisation at α→0)
    Caf = 2.0 * spec.front_tire.By * spec.front_tire.Cy * spec.front_tire.Dy * Fz_f
    Car = 2.0 * spec.rear_tire.By * spec.rear_tire.Cy * spec.rear_tire.Dy * Fz_r

    # Linear bicycle model steering:
    # δ = L/R + m·ay·(b/Car - a/Caf) / L    (Ackermann + lateral correction)
    if Caf < 1.0 or Car < 1.0:
        return {"ok": False, "reason": "degenerate cornering stiffness"}

    steer_ackermann = L / R
    steer_correction = m * ay * (b / Car - a / Caf) / L
    steering_rad = steer_ackermann + steer_correction

    # Slip angles at steady state (linear model)
    alpha_r = -m * ay * a / (Car * L)
    alpha_f = steering_rad + alpha_r - L / R

    # Understeer gradient [rad/g]
    K_us = m * (b / Car - a / Caf) / L

    return {
        "ok": True,
        "steering_rad": steering_rad,
        "steering_deg": math.degrees(steering_rad),
        "alpha_f_rad": alpha_f,
        "alpha_r_rad": alpha_r,
        "lateral_g": lateral_g,
        "understeer_grad": K_us,
        "Fz_front_n": Fz_f,
        "Fz_rear_n": Fz_r,
    }
