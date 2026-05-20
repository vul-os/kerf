"""Horizontal and vertical tail stability derivative terms.

Uses closed-form VLM-derived lift slopes corrected for tail volume
coefficients and downwash (Roskam Vol I, Ch 4-5; Etkin & Reid Ch 4).

Sign convention: all derivatives per radian unless stated.
"""

from __future__ import annotations

import math

from kerf_aero.vlm import vlm_wing


def _tail_CL_alpha(
    span: float,
    root_chord: float,
    tip_chord: float | None = None,
    sweep_deg: float = 0.0,
    n_span: int = 10,
    alpha_deg: float = 0.0,
) -> float:
    """Lift-curve slope for a tail surface via VLM finite difference."""
    if tip_chord is None:
        tip_chord = root_chord

    d_alpha_deg = 0.5
    kwargs = dict(
        span=span,
        root_chord=root_chord,
        tip_chord=tip_chord,
        sweep_deg=sweep_deg,
        n_span=n_span,
        m_chord=2,
    )
    hi = vlm_wing(alpha_deg=alpha_deg + d_alpha_deg, **kwargs)
    lo = vlm_wing(alpha_deg=alpha_deg - d_alpha_deg, **kwargs)
    return (hi["CL"] - lo["CL"]) / (2.0 * math.radians(d_alpha_deg))


def htail_terms(
    # Horizontal tail geometry
    ht_span: float,
    ht_root_chord: float,
    ht_tip_chord: float | None = None,
    ht_sweep_deg: float = 0.0,
    # Moment arm: distance from wing MAC 25% to tail MAC 25% (positive aft)
    lt: float = 5.0,
    # Wing reference geometry
    S_ref: float = 16.2,       # m² (wing area)
    c_mean: float = 1.49,      # m  (mean aerodynamic chord)
    # Downwash gradient d(eps)/d(alpha) — Roskam Vol I, eq 4.44
    # For a conventional aircraft: d(eps)/d(alpha) ~ 2*CL_alpha_wing / (pi*AR_wing)
    d_eps_d_alpha: float | None = None,
    CL_alpha_wing: float = 5.0,
    AR_wing: float = 7.4,
    alpha_deg: float = 4.0,
) -> dict[str, float]:
    """Horizontal tail contributions to stability derivatives.

    Returns
    -------
    dict with keys:
        CL_alpha_tail   (/rad) — tail lift slope (isolated)
        Vh              (–)    — horizontal tail volume coefficient
        eta_h           (–)    — tail efficiency factor (0.9 typical)
        Cm_alpha_tail   (/rad) — tail contribution to Cm_alpha
        Cl_q_tail       (/rad) — tail contribution to Cl_q
        Cm_q_tail       (/rad) — tail contribution to Cm_q (pitch damping)
        Cl_delta_e      (/rad) — elevator effectiveness (Cm_de)
        Cm_delta_e      (/rad) — Cm sensitivity to elevator
    """
    if ht_tip_chord is None:
        ht_tip_chord = ht_root_chord

    c_ht = 0.5 * (ht_root_chord + ht_tip_chord)
    S_ht = ht_span * c_ht  # tail reference area

    # Tail aerodynamic efficiency (skin friction, downwash interference ~ 0.9)
    eta_h = 0.90

    # Horizontal tail volume coefficient
    Vh = (S_ht * lt) / (S_ref * c_mean)

    # Tail lift slope via VLM
    CL_a_t = _tail_CL_alpha(
        span=ht_span,
        root_chord=ht_root_chord,
        tip_chord=ht_tip_chord,
        sweep_deg=ht_sweep_deg,
        alpha_deg=alpha_deg,
    )

    # Downwash gradient (Roskam Vol I, eq 4.44 approximation)
    if d_eps_d_alpha is None:
        d_eps_d_alpha = 2.0 * CL_alpha_wing / (math.pi * AR_wing)

    # Cm_alpha (tail contribution) = -Vh * eta_h * CL_a_t * (1 - d_eps/d_alpha)
    Cm_alpha_tail = -Vh * eta_h * CL_a_t * (1.0 - d_eps_d_alpha)

    # Cl_q (tail contribution, Etkin §4.3):
    # delta_Cl_q = 2 * eta_h * (S_ht / S_ref) * CL_a_t * (lt / c_mean)
    Cl_q_tail = 2.0 * eta_h * (S_ht / S_ref) * CL_a_t * (lt / c_mean)

    # Cm_q (tail contribution, major source of pitch damping):
    # Cm_q_tail = -2 * eta_h * Vh * CL_a_t * (lt / c_mean)
    Cm_q_tail = -2.0 * eta_h * Vh * CL_a_t * (lt / c_mean)

    # Elevator effectiveness: assume elevator covers 40% of tail chord,
    # tau_e (Roskam Vol I, Fig 4.25 for c_e/c_t = 0.40) ~ 0.44
    tau_e = 0.44
    Cl_delta_e = eta_h * (S_ht / S_ref) * CL_a_t * tau_e
    Cm_delta_e = -Vh * eta_h * CL_a_t * tau_e

    return {
        "CL_alpha_tail": CL_a_t,
        "S_ht": S_ht,
        "Vh": Vh,
        "eta_h": eta_h,
        "d_eps_d_alpha": d_eps_d_alpha,
        "Cm_alpha_tail": Cm_alpha_tail,
        "Cl_q_tail": Cl_q_tail,
        "Cm_q_tail": Cm_q_tail,
        "Cl_delta_e": Cl_delta_e,
        "Cm_delta_e": Cm_delta_e,
    }


def vtail_terms(
    # Vertical tail geometry
    vt_span: float,
    vt_root_chord: float,
    vt_tip_chord: float | None = None,
    vt_sweep_deg: float = 0.0,
    # Moment arm: distance from CG to vtail aerodynamic centre (m)
    lv: float = 5.0,
    # Wing reference geometry
    S_ref: float = 16.2,
    b_ref: float = 11.0,      # wing span (m)
    # Fuselage sidewash gradient d(sigma)/d(beta) ~ 0 for thin fuselages
    d_sigma_d_beta: float = 0.0,
    alpha_deg: float = 0.0,
) -> dict[str, float]:
    """Vertical tail contributions to lateral-directional derivatives.

    Returns
    -------
    dict with keys:
        CY_alpha_vt   (/rad) — vtail lift slope (isolated)
        Vv            (–)    — vertical tail volume coefficient
        CY_beta       (/rad) — side force per rad sideslip
        Cl_beta_vt    (/rad) — rolling moment from vtail (dihedral-like)
        Cn_beta       (/rad) — yaw stiffness from vtail (weathercock)
        Cn_delta_r    (/rad) — rudder control effectiveness (Cn)
        CY_delta_r    (/rad) — side force from rudder
    """
    if vt_tip_chord is None:
        vt_tip_chord = vt_root_chord

    c_vt = 0.5 * (vt_root_chord + vt_tip_chord)
    S_vt = vt_span * c_vt

    # Vtail efficiency ~ 0.95 (less interference than htail)
    eta_v = 0.95

    # Vertical tail volume coefficient
    Vv = (S_vt * lv) / (S_ref * b_ref)

    # VLM on vertical tail (solve as a horizontal wing at small angle)
    CL_a_v = _tail_CL_alpha(
        span=vt_span,
        root_chord=vt_root_chord,
        tip_chord=vt_tip_chord,
        sweep_deg=vt_sweep_deg,
        alpha_deg=0.0,
    )

    # Sidewash correction (1 + d_sigma/d_beta)
    k_sigma = 1.0 + d_sigma_d_beta

    # CY_beta = -eta_v * (S_vt / S_ref) * CL_a_v * k_sigma
    CY_beta = -eta_v * (S_vt / S_ref) * CL_a_v * k_sigma

    # Cn_beta (weathercock stability) = +eta_v * Vv * CL_a_v * k_sigma
    Cn_beta = eta_v * Vv * CL_a_v * k_sigma

    # Cl_beta from vtail: destabilising rolling moment
    # z_v = height of vtail aerodynamic centre above fuselage centreline
    # Approximation: z_v ~ vt_span * 0.4 (mean height)
    z_v = vt_span * 0.4
    Cl_beta_vt = -eta_v * (S_vt / S_ref) * CL_a_v * (z_v / b_ref) * k_sigma

    # Rudder effectiveness: assume rudder covers 35% of vtail chord
    tau_r = 0.40
    Cn_delta_r = -eta_v * Vv * CL_a_v * tau_r
    CY_delta_r = eta_v * (S_vt / S_ref) * CL_a_v * tau_r

    return {
        "CL_alpha_vt": CL_a_v,
        "S_vt": S_vt,
        "Vv": Vv,
        "eta_v": eta_v,
        "CY_beta": CY_beta,
        "Cl_beta_vt": Cl_beta_vt,
        "Cn_beta": Cn_beta,
        "Cn_delta_r": Cn_delta_r,
        "CY_delta_r": CY_delta_r,
    }
