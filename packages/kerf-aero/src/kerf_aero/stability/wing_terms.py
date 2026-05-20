"""Wing stability derivative terms via VLM finite differencing.

Wraps the shipped VLM (kerf_aero.vlm.vlm_wing) to extract:
  - Cl_alpha  (lift-curve slope, /rad)
  - Cm_alpha  (pitch-stiffness, /rad, should be negative for stable a/c)
  - Cd_alpha  (drag slope, /rad)
  - Cl_q      (pitch-rate lift damping, /rad)

Finite-difference step: Δα = 0.5 deg (well inside the linear range).
"""

from __future__ import annotations

import math

from kerf_aero.vlm import vlm_wing


# finite-difference half-step (radians)
_D_ALPHA = math.radians(0.5)


def wing_lift_slope(
    span: float,
    root_chord: float,
    tip_chord: float | None = None,
    sweep_deg: float = 0.0,
    twist_deg: float = 0.0,
    alpha_deg: float = 4.0,
    m_chord: int = 4,
    n_span: int = 16,
) -> dict[str, float]:
    """Compute wing CL_alpha, Cm_alpha, CDi_alpha via central-difference VLM.

    Parameters
    ----------
    span : float
        Full wing span (m).
    root_chord : float
        Root chord (m).
    tip_chord : float, optional
        Tip chord (m).  Defaults to root_chord (rectangular).
    sweep_deg : float
        Leading-edge sweep (deg).
    twist_deg : float
        Geometric washout twist (deg).
    alpha_deg : float
        Nominal angle-of-attack for the finite difference (deg).
    m_chord : int
        Chordwise panels per semi-span.
    n_span : int
        Spanwise panels.

    Returns
    -------
    dict with keys:
        CL_alpha  (/rad)
        Cm_alpha  (/rad)
        CDi_alpha (/rad)
        CL_0      (CL at alpha_deg)
        Cm_0      (Cm at alpha_deg)
        AR        (aspect ratio)
        S_ref     (reference area, m²)
        c_mean    (mean aerodynamic chord, m)
    """
    if tip_chord is None:
        tip_chord = root_chord

    kwargs = dict(
        span=span,
        root_chord=root_chord,
        tip_chord=tip_chord,
        sweep_deg=sweep_deg,
        twist_deg=twist_deg,
        m_chord=m_chord,
        n_span=n_span,
    )

    d_alpha_deg = math.degrees(_D_ALPHA)
    hi = vlm_wing(alpha_deg=alpha_deg + d_alpha_deg, **kwargs)
    lo = vlm_wing(alpha_deg=alpha_deg - d_alpha_deg, **kwargs)
    nom = vlm_wing(alpha_deg=alpha_deg, **kwargs)

    two_da = 2.0 * _D_ALPHA

    CL_alpha = (hi["CL"] - lo["CL"]) / two_da
    Cm_alpha = (hi["Cm"] - lo["Cm"]) / two_da
    CDi_alpha = (hi["CDi"] - lo["CDi"]) / two_da

    c_mean = 0.5 * (root_chord + tip_chord)
    S_ref = span * c_mean
    AR = span**2 / S_ref

    return {
        "CL_alpha": CL_alpha,
        "Cm_alpha": Cm_alpha,
        "CDi_alpha": CDi_alpha,
        "CL_0": nom["CL"],
        "Cm_0": nom["Cm"],
        "AR": AR,
        "S_ref": S_ref,
        "c_mean": c_mean,
    }


def wing_pitch_rate_derivatives(
    span: float,
    root_chord: float,
    tip_chord: float | None = None,
    sweep_deg: float = 0.0,
    n_span: int = 16,
    alpha_deg: float = 4.0,
) -> dict[str, float]:
    """Estimate Cl_q (pitch-rate lift) using strip theory.

    Cl_q ≈ 2 * CL_alpha * x_ac / c_mean  (Etkin §4.3 strip approximation)
    where x_ac is the aerodynamic-centre offset from the reference point.

    Returns
    -------
    dict with keys:
        Cl_q  (/rad): lift sensitivity to dimensionless pitch rate q̂ = qc/(2V)
        Cm_q  (/rad): pitch damping due to pitch rate
    """
    if tip_chord is None:
        tip_chord = root_chord

    c_mean = 0.5 * (root_chord + tip_chord)
    S_ref = span * c_mean
    AR = span**2 / S_ref

    wing = wing_lift_slope(
        span=span,
        root_chord=root_chord,
        tip_chord=tip_chord,
        sweep_deg=sweep_deg,
        alpha_deg=alpha_deg,
        n_span=n_span,
    )
    CL_a = wing["CL_alpha"]

    # Strip theory Cl_q (lift due to pitch rate)
    Cl_q = 2.0 * CL_a

    # Pitch damping Cm_q (Roskam Vol I, Ch4 approximation):
    # Cm_q_wing ≈ -0.5 * CL_a  (small negative contribution)
    Cm_q_wing = -0.5 * CL_a

    return {"Cl_q": Cl_q, "Cm_q": Cm_q_wing}
