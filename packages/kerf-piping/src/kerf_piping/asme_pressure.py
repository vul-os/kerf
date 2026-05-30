"""
kerf_piping.asme_pressure — Pipeline pressure-loss calculations.

Implements Darcy-Weisbach friction losses (Colebrook-White friction factor)
and Crane Technical Paper 410 (TP-410) §3 K-factor fitting losses for full
ASME B31 (power piping B31.1 / process piping B31.3) pipeline design.

DISCLAIMER
----------
Values are derived from ASME B31 / Crane TP-410 — NOT certified engineering
compliance. Use only as a preliminary engineering aid; always verify against
the primary standard and have results reviewed by a licensed engineer.

Key references
--------------
- Crane Technical Paper 410 (TP-410), 2013 edition, §1 and §3.
- ASME B31.1-2022 (Power Piping) §304 — Pressure Design.
- ASME B31.3-2022 (Process Piping) §302.2 — Pressure Rating.
- Hooper, W. B. (1981), "The Two-K Method Predicts Head Losses in Pipe
  Fittings", Chemical Engineering, Aug 24, pp. 96-100.

Functions
---------
darcy_weisbach_loss(diameter_in, length_ft, flow_gpm, fluid, roughness)
    Colebrook-White friction factor → ΔP (psi) for a straight pipe run.

fitting_k_factor(fitting_kind, size_inches, beta)
    Crane TP-410 §3 resistance coefficient K for common fittings.

compute_pipeline_pressure_drop(segments, fittings, flow_gpm, fluid)
    Sum Darcy-Weisbach straight-pipe losses + fitting K-factor losses.

hooper_two_k(fitting_kind, K_1, K_inf, flow_gpm, diameter_in, fluid)
    Hooper Two-K method for accurate small-pipe / low-Reynolds behaviour.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Fluid property table (water at 60 °F / 15.6 °C, per Crane TP-410 App. B)
# Keys match the `fluid` parameter accepted by public functions.
# rho_lbft3   : density, lb/ft³
# mu_lbfts    : dynamic viscosity, lb/(ft·s)
# ---------------------------------------------------------------------------

_FLUID_PROPS: dict[str, dict[str, float]] = {
    # Crane TP-410 App. B — water at 60 °F
    "water": {
        "rho_lbft3": 62.37,          # lb/ft³  (ref: 62.4 at 60 °F)
        "mu_lbfts": 6.720e-4,        # lb/(ft·s) = 0.000672 at 60 °F
    },
    # Light hydrocarbon / crude approximation (SG ~0.85, μ ~3 cP)
    "oil": {
        "rho_lbft3": 53.0,
        "mu_lbfts": 2.016e-3,
    },
    # Air at 68 °F, 14.7 psia
    "air": {
        "rho_lbft3": 0.0752,
        "mu_lbfts": 1.22e-5,
    },
    # Steam (saturated, ~212 °F / 1 bar) — approximate
    "steam": {
        "rho_lbft3": 0.0372,
        "mu_lbfts": 6.60e-6,
    },
}

# 1 US gallon = 0.133681 ft³  →  1 GPM = 0.133681/60 ft³/s
_GPM_TO_FT3S = 0.133681 / 60.0          # 0.002228 ft³/s per GPM
_FT2_TO_IN2  = 144.0                    # 1 ft² = 144 in²
# 1 lbf/in² (psi) = 144 lbf/ft²; 1 lbf = 1 lb·ft/s² / (g_c)
# In consistent lbf/ft² → psi divide by 144
_PSF_TO_PSI  = 1.0 / 144.0


# ---------------------------------------------------------------------------
# Colebrook-White friction factor
# ---------------------------------------------------------------------------

def _colebrook_friction_factor(
    reynolds: float,
    roughness_rel: float,
    max_iter: int = 50,
    tol: float = 1e-8,
) -> float:
    """
    Solve the Colebrook-White equation for the Darcy friction factor f_D.

    Colebrook (1939):
        1/√f = -2 log₁₀(ε/(3.7·D) + 2.51/(Re·√f))

    Parameters
    ----------
    reynolds      : Reynolds number (dimensionless).
    roughness_rel : Relative roughness ε/D (dimensionless).
    max_iter      : Maximum Newton iterations.
    tol           : Convergence tolerance on f.

    Returns
    -------
    f_D : Darcy friction factor (dimensionless).

    Notes
    -----
    - For Re < 2100 (laminar) the Hagen-Poiseuille result f = 64/Re is used.
    - For Re in the transition band (2100–4000) we use the turbulent formula
      as a conservative upper bound (common practice in pipeline design).
    """
    if reynolds <= 0.0:
        raise ValueError(f"Reynolds number must be positive; got {reynolds!r}")

    if reynolds < 2100.0:
        # Laminar: Hagen-Poiseuille
        return 64.0 / reynolds

    # Swamee-Jain (1976) explicit approximation as initial guess
    eps_r = roughness_rel
    f = 0.25 / (math.log10(eps_r / 3.7 + 5.74 / (reynolds ** 0.9))) ** 2

    # Newton iteration on Colebrook form: F(f) = 1/√f + 2·log₁₀(ε/3.7D + 2.51/(Re·√f))
    for _ in range(max_iter):
        sqrt_f = math.sqrt(f)
        arg = eps_r / 3.7 + 2.51 / (reynolds * sqrt_f)
        lhs = 1.0 / sqrt_f
        rhs = -2.0 * math.log10(arg)
        residual = lhs - rhs
        # dF/df = -1/(2 f^1.5) + 2.51/(Re · 2 · f^1.5 · arg · ln10)
        d_lhs = -0.5 / (f ** 1.5)
        d_rhs_df = (2.0 / (math.log(10.0) * arg)) * (2.51 / (reynolds * 2.0 * f ** 1.5))
        d_rhs = d_rhs_df
        jac = d_lhs - d_rhs
        if abs(jac) < 1e-15:
            break
        f_new = f - residual / jac
        if f_new <= 0.0:
            f_new = f / 2.0
        if abs(f_new - f) < tol * f:
            f = f_new
            break
        f = f_new

    return f


# ---------------------------------------------------------------------------
# darcy_weisbach_loss
# ---------------------------------------------------------------------------

def darcy_weisbach_loss(
    diameter_in: float,
    length_ft: float,
    flow_gpm: float,
    fluid: str = "water",
    roughness: float = 0.00015,
) -> float:
    """
    Darcy-Weisbach pressure loss for a straight pipe run.

    Implements Crane TP-410 §1 Equation (1-1):
        ΔP = f_D · (L/D) · ρ·V²/2  [lbf/ft²]

    then converts to psi.  Friction factor from Colebrook-White (iterative).

    Parameters
    ----------
    diameter_in : Internal pipe diameter (inches).
    length_ft   : Pipe length (feet).
    flow_gpm    : Volumetric flow rate (US gallons per minute).
    fluid       : Fluid identifier: 'water' | 'oil' | 'air' | 'steam'.
                  Default 'water'.
    roughness   : Absolute pipe wall roughness (feet).
                  Default 0.00015 ft — commercial steel per Crane TP-410 App. B.

    Returns
    -------
    delta_p_psi : Frictional pressure loss (psi).

    Notes
    -----
    - Values are from ASME B31 / Crane TP-410 — NOT certified compliance.
    - The 0.00015 ft roughness is for new commercial steel per Crane App. B
      Table B-1.  Use 0.0 for drawn tubing or adjust as appropriate.
    - Fluid properties are at reference temperature; for service conditions
      outside 40–150 °F (water) or 50–200 °F (oils) adjust via the `fluid`
      parameter or use real thermophysical data.
    """
    if diameter_in <= 0.0:
        raise ValueError(f"diameter_in must be > 0; got {diameter_in!r}")
    if length_ft < 0.0:
        raise ValueError(f"length_ft must be ≥ 0; got {length_ft!r}")
    if flow_gpm < 0.0:
        raise ValueError(f"flow_gpm must be ≥ 0; got {flow_gpm!r}")

    if flow_gpm == 0.0 or length_ft == 0.0:
        return 0.0

    props = _FLUID_PROPS.get(fluid.lower())
    if props is None:
        raise ValueError(
            f"Unknown fluid {fluid!r}. Supported: {sorted(_FLUID_PROPS)}"
        )

    rho   = props["rho_lbft3"]       # lb/ft³
    mu    = props["mu_lbfts"]         # lb/(ft·s)

    # Convert units to consistent ft/s system
    d_ft  = diameter_in / 12.0       # diameter, ft
    q_ft3s = flow_gpm * _GPM_TO_FT3S # volumetric flow, ft³/s
    area  = math.pi * d_ft ** 2 / 4.0  # cross-section area, ft²
    v_fps = q_ft3s / area              # mean velocity, ft/s

    # Reynolds number  Re = ρ·V·D / μ
    re    = rho * v_fps * d_ft / mu

    # Relative roughness  ε/D
    eps_r = roughness / d_ft

    # Darcy friction factor (Colebrook-White)
    f_d   = _colebrook_friction_factor(re, eps_r)

    # Darcy-Weisbach: ΔP_psf = f_D · (L/D) · ρ·V²/2
    # In the lbf/ft² (psf) system with g_c = 32.174 lbm·ft/(lbf·s²):
    #   ΔP [lbf/ft²] = f_D · (L/D) · ρ [lbm/ft³] · V² [ft²/s²] / (2 · g_c)
    g_c   = 32.174                    # lbm·ft/(lbf·s²)
    dp_psf = f_d * (length_ft / d_ft) * rho * v_fps ** 2 / (2.0 * g_c)
    dp_psi = dp_psf * _PSF_TO_PSI

    return dp_psi


# ---------------------------------------------------------------------------
# fitting_k_factor
# ---------------------------------------------------------------------------

# Crane TP-410 §3 Table B-1 representative K values (size-independent base)
# For more precise size-dependent K the Hooper Two-K method should be used.
_FITTING_K_TABLE: dict[str, float] = {
    # Elbows — threaded (screwed) per Crane TP-410 §3
    "90_elbow_threaded":   0.50,
    "45_elbow_threaded":   0.38,
    "180_return_threaded": 1.50,
    # Elbows — buttweld (standard long-radius)
    "90_elbow_welded":     0.30,
    "45_elbow_welded":     0.20,
    "180_return_welded":   0.60,
    # Tees — through (run)
    "tee_through":         0.40,
    # Tees — branch
    "tee_branch":          1.00,
    # Gate valve — fully open
    "gate_valve_open":     0.15,
    # Globe valve — fully open (Crane TP-410 highest-loss fitting)
    "globe_valve":         10.0,
    # Swing check valve
    "check_valve":         2.00,
    # Ball valve — fully open
    "ball_valve_open":     0.07,
    # Butterfly valve — fully open
    "butterfly_valve_open": 0.30,
    # Angle valve — fully open
    "angle_valve_open":    2.00,
    # Plug valve — fully open
    "plug_valve_open":     0.30,
}


def fitting_k_factor(
    fitting_kind: str,
    size_inches: float,
    beta: float = 1.0,
) -> float:
    """
    Crane TP-410 §3 resistance coefficient K for a single fitting.

    For standard fittings the K value is read from an internal table derived
    from Crane TP-410 §3 (size-independent representative values).  For
    reducers/expanders the K is computed from the area-change geometry.

    Parameters
    ----------
    fitting_kind : One of the recognised fitting identifiers (case-insensitive):
        '90_elbow_threaded', '45_elbow_threaded', '180_return_threaded',
        '90_elbow_welded', '45_elbow_welded', '180_return_welded',
        'tee_through', 'tee_branch',
        'gate_valve_open', 'globe_valve', 'check_valve',
        'ball_valve_open', 'butterfly_valve_open', 'angle_valve_open',
        'plug_valve_open',
        'reducer_sudden', 'expander_sudden'.
    size_inches  : Nominal pipe size (inches).  Used for 'reducer_sudden' and
                   'expander_sudden' K scaling; ignored for fixed-K fittings.
    beta         : Diameter ratio d_small/d_large (0 < β ≤ 1).
                   Required for 'reducer_sudden' and 'expander_sudden'.
                   Default 1.0 (no change in area).

    Returns
    -------
    K : Dimensionless resistance coefficient.

    Notes
    -----
    - Values are from Crane TP-410 — NOT certified compliance.
    - For precision sizing especially in small-diameter or low-Re service,
      use `hooper_two_k` instead.

    Crane TP-410 §3 reducer / expander formulae
    --------------------------------------------
    Sudden contraction (reducer):  K = 0.5·(1 − β²)²
    Sudden enlargement (expander): K = (1 − β²)²    (Borda-Carnot)
    where β = d_small / d_large.
    """
    if size_inches <= 0.0:
        raise ValueError(f"size_inches must be > 0; got {size_inches!r}")

    kind = fitting_kind.lower().strip()

    if kind == "reducer_sudden":
        if not (0.0 < beta <= 1.0):
            raise ValueError(f"beta must be in (0, 1] for reducer_sudden; got {beta!r}")
        return 0.5 * (1.0 - beta ** 2) ** 2

    if kind == "expander_sudden":
        if not (0.0 < beta <= 1.0):
            raise ValueError(f"beta must be in (0, 1] for expander_sudden; got {beta!r}")
        return (1.0 - beta ** 2) ** 2

    k = _FITTING_K_TABLE.get(kind)
    if k is None:
        known = sorted(_FITTING_K_TABLE.keys()) + ["reducer_sudden", "expander_sudden"]
        raise ValueError(
            f"Unknown fitting_kind {fitting_kind!r}. "
            f"Known values: {known}"
        )
    return k


# ---------------------------------------------------------------------------
# hooper_two_k
# ---------------------------------------------------------------------------

# Hooper Two-K coefficients for common fittings.
# K = K_1/Re + K_inf · (1 + 1/ID_inches)
# Source: Hooper (1981), Table 1.
_HOOPER_TWO_K: dict[str, tuple[float, float]] = {
    "90_elbow_standard":    (800.0,  0.40),
    "90_elbow_longrad":     (800.0,  0.25),
    "45_elbow_standard":    (500.0,  0.20),
    "45_elbow_longrad":     (500.0,  0.15),
    "180_return_close":     (1000.0, 1.50),
    "180_return_std":       (1000.0, 0.70),
    "tee_through":          (150.0,  0.50),
    "tee_branch":           (800.0,  0.80),
    "gate_valve_open":      (300.0,  0.10),
    "globe_valve_open":     (1500.0, 4.00),
    "check_valve_swing":    (1500.0, 1.50),
    "ball_valve_open":      (300.0,  0.10),
    "butterfly_valve_open": (1000.0, 0.35),
    "reducer_sudden":       (0.0,    0.50),
    "expander_sudden":      (0.0,    1.00),
}


def hooper_two_k(
    fitting_kind: str,
    K_1: float | None = None,
    K_inf: float | None = None,
    reynolds: float = 1e5,
    diameter_in: float = 4.0,
) -> float:
    """
    Hooper Two-K method for fitting resistance coefficient K.

    Per Hooper (1981), the total head-loss coefficient is:
        K = K_1 / Re + K_inf · (1 + 1/ID_in)

    where Re is the pipe Reynolds number and ID_in is the inside diameter
    in inches.  This provides accurate results over a wide Re range,
    especially for small-diameter (<2") and low-Re (<10 000) service where
    the simpler Crane TP-410 one-K approach over-predicts losses.

    Parameters
    ----------
    fitting_kind : Fitting identifier (case-insensitive).  If the built-in
                   table contains the key, K_1 and K_inf are read from it
                   and any provided values override them.
                   Built-in keys: '90_elbow_standard', '90_elbow_longrad',
                   '45_elbow_standard', '45_elbow_longrad',
                   '180_return_close', '180_return_std',
                   'tee_through', 'tee_branch',
                   'gate_valve_open', 'globe_valve_open', 'check_valve_swing',
                   'ball_valve_open', 'butterfly_valve_open',
                   'reducer_sudden', 'expander_sudden'.
    K_1          : Two-K high-Re coefficient.  Required if `fitting_kind` is
                   not in the built-in table.
    K_inf        : Two-K large-pipe / fully-turbulent coefficient.  Required if
                   `fitting_kind` is not in the built-in table.
    reynolds     : Pipe Reynolds number.  Default 1e5.
    diameter_in  : Inside pipe diameter (inches).  Default 4.0.

    Returns
    -------
    K : Dimensionless resistance coefficient.

    Notes
    -----
    - Values are from Hooper (1981) — NOT certified compliance.
    """
    if diameter_in <= 0.0:
        raise ValueError(f"diameter_in must be > 0; got {diameter_in!r}")
    if reynolds <= 0.0:
        raise ValueError(f"reynolds must be > 0; got {reynolds!r}")

    kind = fitting_kind.lower().strip()
    row = _HOOPER_TWO_K.get(kind)

    if row is not None:
        k1   = K_1   if K_1   is not None else row[0]
        kinf = K_inf if K_inf is not None else row[1]
    else:
        if K_1 is None or K_inf is None:
            known = sorted(_HOOPER_TWO_K.keys())
            raise ValueError(
                f"Unknown fitting_kind {fitting_kind!r} and K_1/K_inf not "
                f"provided. Known: {known}"
            )
        k1   = K_1
        kinf = K_inf

    return k1 / reynolds + kinf * (1.0 + 1.0 / diameter_in)


# ---------------------------------------------------------------------------
# compute_pipeline_pressure_drop
# ---------------------------------------------------------------------------

def compute_pipeline_pressure_drop(
    segments: list[dict[str, Any]],
    fittings: list[dict[str, Any]],
    flow_gpm: float,
    fluid: str = "water",
) -> dict[str, Any]:
    """
    Total ASME B31 pipeline pressure drop.

    Sums Darcy-Weisbach straight-pipe losses over all segments plus
    K-factor fitting losses, all evaluated at the same flow rate.

    Parameters
    ----------
    segments : List of segment dicts, each with keys:
        'diameter_in'  (float) — inside pipe diameter, inches.
        'length_ft'    (float) — segment length, feet.
        'roughness'    (float, optional) — wall roughness, ft. Default 0.00015.
        'fluid'        (str, optional)   — fluid override per segment.
    fittings : List of fitting dicts, each with keys:
        'fitting_kind' (str)   — fitting type key for fitting_k_factor().
        'diameter_in'  (float) — pipe diameter at the fitting, inches.
        'beta'         (float, optional) — area ratio for reducer/expander.
        'quantity'     (int, optional)   — number of identical fittings. Default 1.
    flow_gpm : Total flow rate (US GPM).  Assumed constant along the pipeline
               (single-phase, incompressible, no branches).
    fluid    : Default fluid for all segments ('water' | 'oil' | 'air' | 'steam').

    Returns
    -------
    dict with keys:
        'total_dp_psi'        (float) — total pipeline pressure drop, psi.
        'pipe_dp_psi'         (float) — straight-pipe contribution, psi.
        'fitting_dp_psi'      (float) — fitting contribution, psi.
        'segment_details'     (list)  — per-segment ΔP.
        'fitting_details'     (list)  — per-fitting ΔP.
        'disclaimer'          (str)   — mandatory engineering notice.

    Notes
    -----
    - Values are from ASME B31 / Crane TP-410 — NOT certified compliance.
    - This function assumes incompressible, single-phase, steady-state flow.
      It is NOT valid for two-phase, compressible (gas at high ΔP/P), or
      transient cases.
    """
    if flow_gpm < 0.0:
        raise ValueError(f"flow_gpm must be ≥ 0; got {flow_gpm!r}")

    segment_details: list[dict] = []
    pipe_dp_total   = 0.0

    for seg in segments:
        d_in   = float(seg["diameter_in"])
        l_ft   = float(seg["length_ft"])
        rough  = float(seg.get("roughness", 0.00015))
        f_name = str(seg.get("fluid", fluid))

        dp = darcy_weisbach_loss(d_in, l_ft, flow_gpm, f_name, rough)
        pipe_dp_total += dp
        segment_details.append({
            "diameter_in": d_in,
            "length_ft":   l_ft,
            "dp_psi":      round(dp, 6),
        })

    fitting_details: list[dict] = []
    fitting_dp_total = 0.0

    for fit in fittings:
        kind   = str(fit["fitting_kind"])
        d_in   = float(fit["diameter_in"])
        beta   = float(fit.get("beta", 1.0))
        qty    = int(fit.get("quantity", 1))
        f_name = str(fit.get("fluid", fluid))

        k   = fitting_k_factor(kind, d_in, beta)
        dp  = _k_to_psi(k, d_in, flow_gpm, f_name) * qty
        fitting_dp_total += dp
        fitting_details.append({
            "fitting_kind": kind,
            "diameter_in":  d_in,
            "quantity":     qty,
            "K":            round(k, 5),
            "dp_psi":       round(dp, 6),
        })

    total_dp = pipe_dp_total + fitting_dp_total

    return {
        "total_dp_psi":    round(total_dp, 4),
        "pipe_dp_psi":     round(pipe_dp_total, 4),
        "fitting_dp_psi":  round(fitting_dp_total, 4),
        "segment_details": segment_details,
        "fitting_details": fitting_details,
        "disclaimer": (
            "Values from ASME B31 / Crane TP-410 — NOT certified compliance. "
            "Have results reviewed by a licensed engineer."
        ),
    }


# ---------------------------------------------------------------------------
# Internal helper: convert K → ΔP (psi)
# ---------------------------------------------------------------------------

def _k_to_psi(
    k: float,
    diameter_in: float,
    flow_gpm: float,
    fluid: str = "water",
) -> float:
    """
    Convert a fitting resistance coefficient K to pressure drop in psi.

    ΔP = K · ρ·V²/(2·g_c)   [lbf/ft²]  →  divide by 144 → psi.

    Parameters
    ----------
    k           : Dimensionless resistance coefficient (Crane K).
    diameter_in : Inside pipe diameter, inches.
    flow_gpm    : Flow rate, GPM.
    fluid       : Fluid identifier.

    Returns
    -------
    delta_p_psi : Pressure drop, psi.
    """
    if flow_gpm == 0.0 or k == 0.0:
        return 0.0

    props   = _FLUID_PROPS[fluid.lower()]
    rho     = props["rho_lbft3"]
    d_ft    = diameter_in / 12.0
    q_ft3s  = flow_gpm * _GPM_TO_FT3S
    area    = math.pi * d_ft ** 2 / 4.0
    v_fps   = q_ft3s / area
    g_c     = 32.174
    dp_psf  = k * rho * v_fps ** 2 / (2.0 * g_c)
    return dp_psf * _PSF_TO_PSI
