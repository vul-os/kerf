"""Top-level driver: compute_derivatives(geom, flight) -> StabilityDerivatives.

Assembles wing, tail, and fuselage terms into the full stability-derivative
set for a parametric aircraft geometry at a specified flight condition.

All outputs are per radian of perturbation unless the key ends in `_per_deg`.

References
----------
Roskam, J. (1971). *Methods for Estimating Stability and Control Derivatives
  of Conventional Subsonic Airplanes*, University of Kansas.
Etkin, B. and Reid, L.D. (1996). *Dynamics of Flight*, 3rd ed., Wiley.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from kerf_aero.flight_dynamics.atmosphere import atmosphere as std_atmosphere

from .wing_terms import wing_lift_slope, wing_pitch_rate_derivatives
from .tail_terms import htail_terms, vtail_terms
from .fuselage_terms import fuselage_pitching_moment, propeller_contribution
from .control_surfaces import aileron_effectiveness, lateral_damping_derivatives


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WingGeom:
    """Parametric wing geometry."""
    span: float                   # m (full span)
    root_chord: float             # m
    tip_chord: float | None = None  # m (default = root_chord → rectangular)
    sweep_le_deg: float = 0.0    # leading-edge sweep (deg)
    twist_deg: float = 0.0       # geometric washout (deg)
    # Reference area / MAC (computed from span+chord if not given)
    S_ref: float | None = None   # m² (overrides computed value)
    c_mean: float | None = None  # m  (overrides computed value)


@dataclass
class HTailGeom:
    """Horizontal tail geometry."""
    span: float            # m
    root_chord: float      # m
    tip_chord: float | None = None
    sweep_le_deg: float = 0.0
    # Moment arm: wing 25%-MAC to htail 25%-MAC (m)
    moment_arm: float = 5.0


@dataclass
class VTailGeom:
    """Vertical tail geometry."""
    span: float            # m (height)
    root_chord: float      # m
    tip_chord: float | None = None
    sweep_le_deg: float = 0.0
    # Moment arm: CG to vtail aerodynamic centre (m)
    moment_arm: float = 5.0


@dataclass
class FuselageGeom:
    """Fuselage geometry (simplified)."""
    length: float          # m
    max_width: float       # m
    max_height: float      # m


@dataclass
class AircraftGeom:
    """Full parametric aircraft geometry."""
    wing: WingGeom
    htail: HTailGeom | None = None
    vtail: VTailGeom | None = None
    fuselage: FuselageGeom | None = None
    n_engines: int = 1


@dataclass
class FlightCondition:
    """Flight condition for derivative evaluation."""
    mach: float = 0.12          # Mach number
    altitude_m: float = 600.0   # geometric altitude (m)
    alpha_deg: float = 4.0      # angle of attack (deg)
    beta_deg: float = 0.0       # sideslip angle (deg)
    # CG position as a fraction of MAC, measured from LE (0.25 = 25% MAC).
    # Affects the wing-body contribution to Cm_alpha (CG offset from wing AC).
    cg_frac_mac: float = 0.25   # dimensionless (0 = LE, 1 = TE)


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class StabilityDerivatives:
    """Full set of stability and control derivatives.

    All per-radian (1/rad) unless noted.
    """
    # --- Longitudinal ---
    CL_alpha: float = 0.0    # lift slope
    Cd_alpha: float = 0.0    # drag slope
    Cm_alpha: float = 0.0    # pitch stiffness (< 0 → stable)
    Cl_q: float = 0.0        # lift due to pitch rate q̂ = qc/(2V)
    Cm_q: float = 0.0        # pitch damping (< 0)
    Cm_delta_e: float = 0.0  # elevator pitch effectiveness
    Cl_delta_e: float = 0.0  # elevator lift effectiveness

    # --- Lateral-directional ---
    CY_beta: float = 0.0     # side force per rad sideslip
    Cl_beta: float = 0.0     # dihedral effect (< 0 → stable)
    Cn_beta: float = 0.0     # weathercock stability (> 0 → stable)
    Cl_p: float = 0.0        # roll damping (< 0)
    Cn_p: float = 0.0        # adverse yaw from roll rate
    Cl_r: float = 0.0        # roll from yaw rate
    Cn_r: float = 0.0        # yaw damping (< 0)
    CY_delta_r: float = 0.0  # side force from rudder
    Cn_delta_r: float = 0.0  # rudder yaw effectiveness
    Cl_delta_a: float = 0.0  # aileron roll effectiveness

    # --- Per-degree versions (convenience) ---
    @property
    def CL_alpha_per_deg(self) -> float:
        return self.CL_alpha / math.degrees(1.0)

    @property
    def Cm_alpha_per_deg(self) -> float:
        return self.Cm_alpha / math.degrees(1.0)

    @property
    def Cn_beta_per_deg(self) -> float:
        return self.Cn_beta / math.degrees(1.0)

    def as_dict(self) -> dict[str, float]:
        """Return all derivatives as a flat dict (/rad and /deg)."""
        return {
            "CL_alpha": self.CL_alpha,
            "CL_alpha_per_deg": self.CL_alpha_per_deg,
            "Cd_alpha": self.Cd_alpha,
            "Cm_alpha": self.Cm_alpha,
            "Cm_alpha_per_deg": self.Cm_alpha_per_deg,
            "Cl_q": self.Cl_q,
            "Cm_q": self.Cm_q,
            "Cm_delta_e": self.Cm_delta_e,
            "Cl_delta_e": self.Cl_delta_e,
            "CY_beta": self.CY_beta,
            "Cl_beta": self.Cl_beta,
            "Cn_beta": self.Cn_beta,
            "Cn_beta_per_deg": self.Cn_beta_per_deg,
            "Cl_p": self.Cl_p,
            "Cn_p": self.Cn_p,
            "Cl_r": self.Cl_r,
            "Cn_r": self.Cn_r,
            "CY_delta_r": self.CY_delta_r,
            "Cn_delta_r": self.Cn_delta_r,
            "Cl_delta_a": self.Cl_delta_a,
        }


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def compute_derivatives(
    geom: AircraftGeom,
    flight: FlightCondition,
) -> StabilityDerivatives:
    """Compute full stability and control derivative set.

    Lifting-surface terms from VLM (wing + tails).
    Fuselage + propeller terms from DATCOM/Roskam closed-form.

    Parameters
    ----------
    geom:
        Parametric aircraft geometry.
    flight:
        Flight condition (Mach, altitude, α, β).

    Returns
    -------
    StabilityDerivatives
        Full set of dimensionless derivatives (/rad).
    """
    # Atmosphere at flight condition (for Mach-correction hook, currently unused)
    _atm = std_atmosphere(flight.altitude_m)
    mach = flight.mach

    w = geom.wing
    tip_chord = w.tip_chord if w.tip_chord is not None else w.root_chord
    c_mean = w.c_mean if w.c_mean is not None else 0.5 * (w.root_chord + tip_chord)
    S_ref = w.S_ref if w.S_ref is not None else w.span * c_mean

    # ------------------------------------------------------------------
    # 1. Wing terms (VLM)
    # ------------------------------------------------------------------
    wt = wing_lift_slope(
        span=w.span,
        root_chord=w.root_chord,
        tip_chord=tip_chord,
        sweep_deg=w.sweep_le_deg,
        twist_deg=w.twist_deg,
        alpha_deg=flight.alpha_deg,
        n_span=16,
    )
    CL_alpha_w = wt["CL_alpha"]
    CDi_alpha = wt["CDi_alpha"]
    AR = wt["AR"]

    # Wing Cm_alpha about the reference CG.
    #
    # For a thin flat-plate VLM model the aerodynamic centre is at 25% chord;
    # Cm_alpha about the AC is zero.  The CG offset from the wing AC adds a
    # term:   dCm_cg/dalpha = -(x_cg - x_ac_w) / c_mean * CL_alpha_w
    # where (x_cg - x_ac_w) = (cg_frac_mac - 0.25) * c_mean.
    # A CG forward of wing AC (cg < 0.25) gives a positive (destabilising) term
    # in the sign convention used here (CG movement aft stabilises).
    x_cg_frac = flight.cg_frac_mac      # CG as fraction of MAC from LE
    x_ac_w_frac = 0.25                   # wing AC at 25% MAC (thin-plate VLM)
    # Cm_w about CG: if CG is aft of wing AC, wing contribution is destabilising (+).
    # Cm_alpha_w = (x_cg - x_ac_w)/c * CL_alpha_w
    # (positive for CG aft of wing AC — wing destabilises)
    Cm_alpha_w_mac = (x_cg_frac - x_ac_w_frac) * CL_alpha_w

    wpr = wing_pitch_rate_derivatives(
        span=w.span,
        root_chord=w.root_chord,
        tip_chord=tip_chord,
        alpha_deg=flight.alpha_deg,
        n_span=10,
    )
    Cl_q_w = wpr["Cl_q"]
    Cm_q_w = wpr["Cm_q"]

    # Assemble longitudinal totals (wing only so far)
    CL_alpha = CL_alpha_w
    Cm_alpha = Cm_alpha_w_mac   # will add tail + fuselage below
    Cd_alpha = CDi_alpha
    Cl_q = Cl_q_w
    Cm_q = Cm_q_w
    Cm_delta_e = 0.0
    Cl_delta_e = 0.0

    # ------------------------------------------------------------------
    # 2. Horizontal tail terms
    # ------------------------------------------------------------------
    if geom.htail is not None:
        ht = geom.htail
        ht_tip = ht.tip_chord if ht.tip_chord is not None else ht.root_chord

        ht_res = htail_terms(
            ht_span=ht.span,
            ht_root_chord=ht.root_chord,
            ht_tip_chord=ht_tip,
            ht_sweep_deg=ht.sweep_le_deg,
            lt=ht.moment_arm,
            S_ref=S_ref,
            c_mean=c_mean,
            CL_alpha_wing=CL_alpha_w,
            AR_wing=AR,
            alpha_deg=flight.alpha_deg,
        )
        Cm_alpha += ht_res["Cm_alpha_tail"]
        Cl_q += ht_res["Cl_q_tail"]
        Cm_q += ht_res["Cm_q_tail"]
        Cm_delta_e = ht_res["Cm_delta_e"]
        Cl_delta_e = ht_res["Cl_delta_e"]
        CL_alpha += ht_res["CL_alpha_tail"] * ht_res["eta_h"] * (ht_res["S_ht"] / S_ref) * (
            1.0 - ht_res["d_eps_d_alpha"]
        )

    # ------------------------------------------------------------------
    # 3. Fuselage terms
    # ------------------------------------------------------------------
    if geom.fuselage is not None:
        fus = geom.fuselage
        fus_res = fuselage_pitching_moment(
            fuselage_length=fus.length,
            fuselage_max_width=fus.max_width,
            fuselage_max_height=fus.max_height,
            S_ref=S_ref,
            c_mean=c_mean,
            mach=mach,
        )
        Cm_alpha += fus_res["Cm_alpha_fus"]   # destabilising (positive)

    # ------------------------------------------------------------------
    # 4. Vertical tail terms (lateral-directional)
    # ------------------------------------------------------------------
    CY_beta = 0.0
    Cl_beta = 0.0
    Cn_beta = 0.0
    CY_delta_r = 0.0
    Cn_delta_r = 0.0

    if geom.vtail is not None:
        vt = geom.vtail
        vt_tip = vt.tip_chord if vt.tip_chord is not None else vt.root_chord

        vt_res = vtail_terms(
            vt_span=vt.span,
            vt_root_chord=vt.root_chord,
            vt_tip_chord=vt_tip,
            vt_sweep_deg=vt.sweep_le_deg,
            lv=vt.moment_arm,
            S_ref=S_ref,
            b_ref=w.span,
            alpha_deg=flight.alpha_deg,
        )
        CY_beta = vt_res["CY_beta"]
        Cl_beta = vt_res["Cl_beta_vt"]   # vtail contribution; dihedral added below
        Cn_beta = vt_res["Cn_beta"]
        CY_delta_r = vt_res["CY_delta_r"]
        Cn_delta_r = vt_res["Cn_delta_r"]

        # Add fuselage destabilising Cn_beta if fuselage is defined
        if geom.fuselage is not None:
            Cn_beta += fus_res["Cn_beta_fus_per_b"] / w.span  # type: ignore[possibly-undefined]

    # Wing dihedral contribution to Cl_beta (Roskam Vol I, eq 4.57 simplified)
    # For a low-wing aircraft Cl_beta_dihedral ~ 0.  For high-wing or with
    # explicit dihedral angle we would add a term here.
    # Approximation: -0.0001 * AR (very small for straight wing)
    Cl_beta += -0.0002 * AR  # small wing dihedral contribution

    # ------------------------------------------------------------------
    # 5. Roll and yaw damping (from control_surfaces.py)
    # ------------------------------------------------------------------
    vt_span_val = geom.vtail.span if geom.vtail else 0.0
    vt_chord_val = geom.vtail.root_chord if geom.vtail else 1.0
    lv_val = geom.vtail.moment_arm if geom.vtail else 5.0

    damp = lateral_damping_derivatives(
        wing_span=w.span,
        root_chord=w.root_chord,
        tip_chord=tip_chord,
        S_ref=S_ref,
        b_ref=w.span,
        vt_span=vt_span_val if vt_span_val > 0 else 1.83,
        vt_chord=vt_chord_val if vt_chord_val > 0 else 0.9,
        lv=lv_val,
        alpha_deg=flight.alpha_deg,
    )
    Cl_p = damp["Cl_p"]
    Cn_r = damp["Cn_r"]
    Cl_r = damp["Cl_r"]
    Cn_p = damp["Cn_p"]

    # ------------------------------------------------------------------
    # 6. Aileron effectiveness
    # ------------------------------------------------------------------
    Cl_delta_a = 0.0
    if geom.vtail is not None:  # only compute if lateral derivatives make sense
        ail_res = aileron_effectiveness(
            wing_span=w.span,
            root_chord=w.root_chord,
            tip_chord=tip_chord,
            sweep_deg=w.sweep_le_deg,
            S_ref=S_ref,
            b_ref=w.span,
            alpha_deg=flight.alpha_deg,
        )
        Cl_delta_a = ail_res["Cl_delta_a"]

    return StabilityDerivatives(
        CL_alpha=CL_alpha,
        Cd_alpha=Cd_alpha,
        Cm_alpha=Cm_alpha,
        Cl_q=Cl_q,
        Cm_q=Cm_q,
        Cm_delta_e=Cm_delta_e,
        Cl_delta_e=Cl_delta_e,
        CY_beta=CY_beta,
        Cl_beta=Cl_beta,
        Cn_beta=Cn_beta,
        Cl_p=Cl_p,
        Cn_p=Cn_p,
        Cl_r=Cl_r,
        Cn_r=Cn_r,
        CY_delta_r=CY_delta_r,
        Cn_delta_r=Cn_delta_r,
        Cl_delta_a=Cl_delta_a,
    )
