"""Control-surface effectiveness derivatives.

Elevator (longitudinal), aileron (lateral), and rudder (directional).

References
----------
Roskam, J. (1971). "Methods for Estimating Stability and Control
  Derivatives of Conventional Subsonic Airplanes", Part I, Ch 6.
"""

from __future__ import annotations

import math

from kerf_aero.vlm import vlm_wing


def aileron_effectiveness(
    # Wing geometry
    wing_span: float,
    root_chord: float,
    tip_chord: float | None = None,
    sweep_deg: float = 0.0,
    # Aileron span fraction (inboard and outboard stations as fraction of semi-span)
    aileron_inboard: float = 0.60,
    aileron_outboard: float = 0.90,
    # Aileron chord ratio c_a/c ~ 0.25
    chord_ratio: float = 0.25,
    # Reference
    S_ref: float = 16.2,
    b_ref: float = 11.0,
    alpha_deg: float = 4.0,
) -> dict[str, float]:
    """Aileron control effectiveness Cl_delta_a (/rad).

    Uses strip theory with the Roskam aileron effectiveness factor tau_a.

    Cl_delta_a = (2 * CL_alpha_wing / S_ref / b_ref) * tau_a
                * integral_{y_i}^{y_o} c(y) * y dy

    where tau_a ≈ 0.40 for chord_ratio = 0.25 (Roskam Fig 6.5).

    Returns
    -------
    dict with keys:
        Cl_delta_a  (/rad) — rolling moment coefficient per rad aileron
        Cn_delta_a  (/rad) — adverse yaw per rad aileron (small, ~0)
    """
    if tip_chord is None:
        tip_chord = root_chord

    c_mean = 0.5 * (root_chord + tip_chord)

    # Aileron hinge-moment effectiveness factor tau_a (Roskam Fig 6.5)
    # For c_a/c = 0.25 -> tau_a ~ 0.40; for 0.30 -> 0.50
    tau_a = 0.40 + (chord_ratio - 0.25) / 0.05 * 0.10

    # Wing lift slope (fast approx using VLM finite difference)
    from kerf_aero.stability.wing_terms import wing_lift_slope
    wt = wing_lift_slope(
        span=wing_span,
        root_chord=root_chord,
        tip_chord=tip_chord,
        sweep_deg=sweep_deg,
        alpha_deg=alpha_deg,
        n_span=10,
    )
    CL_a_w = wt["CL_alpha"]

    b = wing_span
    # Spanwise integral of c(y)*y from y_i to y_o (positive semi-span only)
    y_i = aileron_inboard * b / 2.0
    y_o = aileron_outboard * b / 2.0

    # Linear taper: c(y) = root_chord + (tip_chord - root_chord) * (y / (b/2))
    # integral c(y)*y dy from y_i to y_o (one semi-span, positive side)
    # = root_chord * (y_o^2 - y_i^2)/2 + (tip_chord - root_chord)/(b/2) * (y_o^3 - y_i^3)/3
    integral = (
        root_chord * (y_o**2 - y_i**2) / 2.0
        + (tip_chord - root_chord) / (b / 2.0) * (y_o**3 - y_i**3) / 3.0
    )

    # Cl_delta_a = 2 * CL_a_w / (S_ref * b_ref) * tau_a * integral * 2
    # Factor of 2 outside for both ailerons (one goes up, one goes down — same sign for roll)
    Cl_delta_a = 2.0 * CL_a_w * tau_a * integral / (S_ref * b_ref)

    # Adverse yaw: Cn_delta_a (small, proportional to CDi slope)
    # Roskam approximation: Cn_delta_a ~ -Cl_delta_a * CD_i_factor
    Cn_delta_a = -0.10 * Cl_delta_a  # small adverse yaw

    return {
        "Cl_delta_a": Cl_delta_a,
        "Cn_delta_a": Cn_delta_a,
        "tau_a": tau_a,
    }


def lateral_damping_derivatives(
    # Wing geometry
    wing_span: float,
    root_chord: float,
    tip_chord: float | None = None,
    # Reference
    S_ref: float = 16.2,
    b_ref: float = 11.0,
    # Vertical tail for yaw damping
    vt_span: float = 1.83,
    vt_chord: float = 0.9,
    lv: float = 5.0,
    alpha_deg: float = 4.0,
) -> dict[str, float]:
    """Roll and yaw damping derivatives Cl_p, Cn_r, Cl_r, Cn_p.

    Strip theory (Etkin §4.4; Roskam Vol I, §4.5):

    Cl_p = (1 / (S_ref * b^2)) * integral (c(y) * CL_a_local * y^2) dy
         (negative — roll damping)

    Cn_r = -2 * eta_v * Vv * CL_a_v * (lv/b)^2
         (negative — yaw damping)

    Cl_r = CL_0 / 4  (positive — adverse coupling)

    Cn_p ≈ -CL_0 / (4*pi*AR)  (small)
    """
    if tip_chord is None:
        tip_chord = root_chord

    from kerf_aero.stability.wing_terms import wing_lift_slope
    from kerf_aero.stability.tail_terms import _tail_CL_alpha

    wt = wing_lift_slope(
        span=wing_span,
        root_chord=root_chord,
        tip_chord=tip_chord,
        alpha_deg=alpha_deg,
        n_span=10,
    )
    CL_a_w = wt["CL_alpha"]
    CL_0 = wt["CL_0"]
    AR = wt["AR"]
    b = wing_span

    # Cl_p (roll damping): strip theory integral
    # Cl_p = CL_a_w / (S_ref * b^2) * integral c(y) * y^2 dy over full span
    def _c_at_y(y: float) -> float:
        return root_chord + (tip_chord - root_chord) * abs(y) / (b / 2.0)

    # Numerical integration (simple trapezoidal)
    n_pts = 40
    y_pts = [b / 2.0 * (2.0 * i / n_pts - 1.0) for i in range(n_pts + 1)]
    integral_p = sum(
        0.5 * (_c_at_y(y_pts[i]) * y_pts[i]**2 + _c_at_y(y_pts[i + 1]) * y_pts[i + 1]**2)
        * (y_pts[i + 1] - y_pts[i])
        for i in range(n_pts)
    )
    Cl_p = -CL_a_w * integral_p / (S_ref * b**2)

    # Cn_r (yaw damping — from vtail):
    CL_a_v = _tail_CL_alpha(span=vt_span, root_chord=vt_chord, alpha_deg=0.0, n_span=6)
    eta_v = 0.95
    S_vt = vt_span * vt_chord
    Vv = (S_vt * lv) / (S_ref * b_ref)
    Cn_r = -2.0 * eta_v * Vv * CL_a_v * (lv / b_ref)

    # Cl_r (coupling: yaw rate → rolling moment, Roskam Vol I)
    # Cl_r ≈ CL_0 / 4
    Cl_r = CL_0 / 4.0

    # Cn_p (coupling: roll rate → yawing moment)
    # Cn_p ≈ -CL_0 / (4 * pi * AR)  (Etkin §4.4, sign: adverse)
    Cn_p = -CL_0 / (4.0 * math.pi * AR) if AR > 0 else 0.0

    return {
        "Cl_p": Cl_p,
        "Cn_r": Cn_r,
        "Cl_r": Cl_r,
        "Cn_p": Cn_p,
    }
