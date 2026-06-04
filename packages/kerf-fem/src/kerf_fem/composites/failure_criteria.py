"""
Composite ply failure criteria.

Implements the most widely used failure criteria for unidirectional fibre-
reinforced polymer (FRP) composite plies under plane-stress conditions.

Criteria implemented
--------------------
  tsai_wu       — Interactive polynomial criterion (Tsai & Wu 1971).
  tsai_hill     — Anisotropic Hill criterion adapted for composites (Tsai 1965).
  maximum_stress — Independent stress-component checks.
  maximum_strain — Independent strain-component checks.
  puck           — Physically motivated fibre/matrix failure modes (Puck 1998).
  hashin         — Separate fibre and matrix failure sub-criteria (Hashin 1980).

All criteria operate on the stress vector in the material (fibre) frame:
  σ = [σ_1, σ_2, τ_12]   [Pa]
  (plane-stress CLT: σ_3 = τ_13 = τ_23 = 0)

Failure index convention
------------------------
  FI < 1  →  safe
  FI ≥ 1  →  failed
  Safety factor = 1 / FI  (margin above current load to first failure)

For criteria with multiple sub-conditions, FI = max(sub-FIs).

Strength notation
-----------------
  X_T = sigma_1_T_pa  — fibre tensile strength
  X_C = sigma_1_C_pa  — fibre compressive strength (positive value)
  Y_T = sigma_2_T_pa  — matrix tensile strength
  Y_C = sigma_2_C_pa  — matrix compressive strength (positive value)
  S   = tau_12_pa     — in-plane shear strength

References
----------
Tsai S.W., Wu E.M. (1971). "A General Theory of Strength for Anisotropic
  Materials." Journal of Composite Materials 5(1):58-80.
Tsai S.W. (1968). "Strength Theories of Filamentary Structures." in
  "Fundamental Aspects of Fiber Reinforced Plastic Composites."
Hill R. (1948). "A Theory of the Yielding and Plastic Flow of Anisotropic
  Metals." Proc. Roy. Soc. London A 193:281-297.
Hashin Z. (1980). "Failure Criteria for Unidirectional Fibre Composites."
  Journal of Applied Mechanics 47(2):329-334.
Puck A., Schürmann H. (1998). "Failure Analysis of FRP Laminates by Means
  of Physically Based Phenomenological Models." Composites Science and
  Technology 58(7):1045-1067.
Jones R.M. (1999). "Mechanics of Composite Materials." 2nd ed. Taylor &
  Francis. Chapter 2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from kerf_fem.composites.laminate_classical import LaminaPly, Laminate, LaminateResponse


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FailureResult:
    """
    Failure analysis result for a single ply under a given criterion.

    Attributes
    ----------
    criterion : str
        Name of the failure criterion applied.
    failure_index : float
        Failure index FI.  FI < 1 → safe, FI ≥ 1 → failed.
    failed : bool
        True if FI ≥ 1.
    failed_mode : str
        Dominant failure mode: 'fibre' | 'matrix' | 'shear' | 'mixed' | 'none'.
    safety_factor : float
        Reserve factor RF = 1 / FI.  RF > 1 → safe.  +inf for zero stress.
    """
    criterion: str
    failure_index: float
    failed: bool
    failed_mode: str
    safety_factor: float


def _make_result(criterion: str, fi: float, mode: str) -> FailureResult:
    fi = float(max(fi, 0.0))
    sf = (1.0 / fi) if fi > 1e-300 else float("inf")
    return FailureResult(
        criterion=criterion,
        failure_index=fi,
        failed=bool(fi >= 1.0),
        failed_mode=mode if fi >= 1.0 else "none",
        safety_factor=float(sf),
    )


# ---------------------------------------------------------------------------
# Tsai-Wu criterion
# ---------------------------------------------------------------------------

def tsai_wu(
    stress_material_frame: np.ndarray,
    ply: "LaminaPly",
    F12_interaction: float = 0.0,
) -> FailureResult:
    """
    Tsai-Wu (1971) interactive polynomial failure criterion.

    Criterion:
        F_i σ_i + F_ij σ_i σ_j ≤ 1

    Expanded for plane stress {σ_1, σ_2, τ_12}:
        F_1 σ_1 + F_2 σ_2 + F_11 σ_1² + F_22 σ_2² + F_66 τ_12² +
        2 F_12 σ_1 σ_2 ≤ 1

    Strength tensors:
        F_1  = 1/X_T - 1/X_C
        F_2  = 1/Y_T - 1/Y_C
        F_11 = 1/(X_T · X_C)
        F_22 = 1/(Y_T · Y_C)
        F_66 = 1/S²
        F_12 = interaction term (default 0; biaxial test needed for exact value)
              Stability criterion: F_12² < F_11 · F_22

    Parameters
    ----------
    stress_material_frame : np.ndarray (3,)
        Ply stress [σ_1, σ_2, τ_12] in material frame [Pa].
    ply : LaminaPly
        Ply with strength properties.
    F12_interaction : float
        Off-diagonal interaction coefficient F_12.  Default 0.
        Must satisfy |F_12| < sqrt(F_11 * F_22) for stability.

    Returns
    -------
    FailureResult

    References
    ----------
    Tsai S.W., Wu E.M. (1971). Journal of Composite Materials 5(1):58-80.
    Jones (1999) §2.5.
    """
    s = np.asarray(stress_material_frame, dtype=float)
    if s.shape != (3,):
        raise ValueError("stress must be shape (3,) [σ_1, σ_2, τ_12]")

    s1, s2, t12 = s

    X_T, X_C = ply.sigma_1_T_pa, ply.sigma_1_C_pa
    Y_T, Y_C = ply.sigma_2_T_pa, ply.sigma_2_C_pa
    S = ply.tau_12_pa

    F1  = 1.0/X_T - 1.0/X_C
    F2  = 1.0/Y_T - 1.0/Y_C
    F11 = 1.0/(X_T * X_C)
    F22 = 1.0/(Y_T * Y_C)
    F66 = 1.0/(S * S)
    F12 = float(F12_interaction)

    # Stability check
    f12_lim = math.sqrt(F11 * F22)
    if abs(F12) > f12_lim:
        raise ValueError(
            f"F12 = {F12:.3e} violates stability criterion |F12| < {f12_lim:.3e}"
        )

    FI = (F1*s1 + F2*s2
          + F11*s1**2 + F22*s2**2 + F66*t12**2
          + 2.0*F12*s1*s2)

    # Determine dominant mode
    fi_fibre  = F11 * s1**2 + F1 * s1
    fi_matrix = F22 * s2**2 + F2 * s2
    fi_shear  = F66 * t12**2
    parts = {"fibre": fi_fibre, "matrix": fi_matrix, "shear": fi_shear}
    mode = max(parts, key=lambda k: parts[k])

    return _make_result("tsai_wu", FI, mode)


# ---------------------------------------------------------------------------
# Tsai-Hill criterion
# ---------------------------------------------------------------------------

def tsai_hill(
    stress_material_frame: np.ndarray,
    ply: "LaminaPly",
) -> FailureResult:
    """
    Tsai-Hill failure criterion for composites.

    Based on Hill's (1948) anisotropic yield criterion adapted by Tsai (1965)
    for FRP composites with different tensile and compressive strengths.

    Criterion (plane stress):
        (σ_1/X)² - (σ_1 σ_2/X²) + (σ_2/Y)² + (τ_12/S)² ≤ 1

    where X = X_T if σ_1 ≥ 0 else X_C,  Y = Y_T if σ_2 ≥ 0 else Y_C.

    Parameters
    ----------
    stress_material_frame : np.ndarray (3,)
        Ply stress [σ_1, σ_2, τ_12] in material frame [Pa].
    ply : LaminaPly

    References
    ----------
    Tsai S.W. (1968). "Strength Theories of Filamentary Structures."
    Jones (1999) §2.4.
    """
    s = np.asarray(stress_material_frame, dtype=float)
    s1, s2, t12 = s

    X = ply.sigma_1_T_pa if s1 >= 0 else ply.sigma_1_C_pa
    Y = ply.sigma_2_T_pa if s2 >= 0 else ply.sigma_2_C_pa
    S = ply.tau_12_pa

    FI = (s1/X)**2 - (s1*s2)/(X**2) + (s2/Y)**2 + (t12/S)**2

    fi_fibre  = (s1/X)**2
    fi_matrix = (s2/Y)**2
    fi_shear  = (t12/S)**2
    fi_interact = abs(-(s1*s2)/(X**2))
    mode = "fibre" if fi_fibre >= max(fi_matrix, fi_shear, fi_interact) else (
           "matrix" if fi_matrix >= max(fi_shear, fi_interact) else (
           "shear" if fi_shear >= fi_interact else "mixed"))

    return _make_result("tsai_hill", FI, mode)


# ---------------------------------------------------------------------------
# Maximum stress criterion
# ---------------------------------------------------------------------------

def maximum_stress(
    stress_material_frame: np.ndarray,
    ply: "LaminaPly",
) -> FailureResult:
    """
    Maximum stress failure criterion.

    Failure occurs when any stress component exceeds its allowable:
        σ_1 > X_T  or  |σ_1| > X_C  (if σ_1 < 0)
        σ_2 > Y_T  or  |σ_2| > Y_C  (if σ_2 < 0)
        |τ_12| > S

    FI = max of all normalised stress components.

    Parameters
    ----------
    stress_material_frame : np.ndarray (3,)
        [σ_1, σ_2, τ_12] [Pa].
    ply : LaminaPly

    References
    ----------
    Jones (1999) §2.3.
    """
    s1, s2, t12 = np.asarray(stress_material_frame, dtype=float)

    fi1 = s1 / ply.sigma_1_T_pa     if s1 >= 0 else abs(s1) / ply.sigma_1_C_pa
    fi2 = s2 / ply.sigma_2_T_pa     if s2 >= 0 else abs(s2) / ply.sigma_2_C_pa
    fi6 = abs(t12) / ply.tau_12_pa

    fi_map = {"fibre": fi1, "matrix": fi2, "shear": fi6}
    FI = max(fi_map.values())
    mode = max(fi_map, key=lambda k: fi_map[k])

    return _make_result("maximum_stress", FI, mode)


# ---------------------------------------------------------------------------
# Maximum strain criterion
# ---------------------------------------------------------------------------

def maximum_strain(
    strain_material_frame: np.ndarray,
    ply: "LaminaPly",
) -> FailureResult:
    """
    Maximum strain failure criterion.

    Failure occurs when any strain component exceeds its ultimate strain:
        ε_1 > ε_1T = X_T / E1       or  ε_1 < -ε_1C = -X_C / E1
        ε_2 > ε_2T = Y_T / E2       or  ε_2 < -ε_2C = -Y_C / E2
        |γ_12| > γ_12u = S / G12

    FI = max of all normalised strain components.

    Parameters
    ----------
    strain_material_frame : np.ndarray (3,)
        Ply strains [ε_1, ε_2, γ_12] in material frame [-].
    ply : LaminaPly

    References
    ----------
    Jones (1999) §2.3.2.
    """
    e1, e2, g12 = np.asarray(strain_material_frame, dtype=float)

    e1T_ult  = ply.sigma_1_T_pa / ply.E1_pa
    e1C_ult  = ply.sigma_1_C_pa / ply.E1_pa
    e2T_ult  = ply.sigma_2_T_pa / ply.E2_pa
    e2C_ult  = ply.sigma_2_C_pa / ply.E2_pa
    g12_ult  = ply.tau_12_pa / ply.G12_pa

    fi1 = e1  / e1T_ult  if e1 >= 0 else abs(e1)  / e1C_ult
    fi2 = e2  / e2T_ult  if e2 >= 0 else abs(e2)  / e2C_ult
    fi6 = abs(g12) / g12_ult

    fi_map = {"fibre": fi1, "matrix": fi2, "shear": fi6}
    FI = max(fi_map.values())
    mode = max(fi_map, key=lambda k: fi_map[k])

    return _make_result("maximum_strain", FI, mode)


# ---------------------------------------------------------------------------
# Puck criterion
# ---------------------------------------------------------------------------

def puck(
    stress_material_frame: np.ndarray,
    ply: "LaminaPly",
    p_pT: float = 0.3,
    p_pC: float = 0.25,
) -> FailureResult:
    """
    Puck (1998) physically-based failure criterion.

    Separates failure into:
      - Fibre failure (FF): dominated by σ_1 relative to fibre strengths.
      - Inter-Fibre Failure (IFF): matrix cracking driven by σ_2, τ_12.

    Fibre failure indices:
        IFF_f^T = σ_1 / X_T       (tensile)
        IFF_f^C = |σ_1| / X_C     (compressive)

    Inter-fibre failure (Mode A: σ_2 ≥ 0, matrix tensile):
        IFF_A = sqrt((τ_12/S)² + (1 - p_pT·Y_T/S)²·(σ_2/Y_T)²) + p_pT·σ_2/S

    Inter-fibre failure (Mode B: σ_2 < 0, |τ_12| > 0):
        IFF_B = (1/S)·(sqrt(τ_12² + (p_pC·σ_2)²) + p_pC·σ_2)

    Failure: IFF_f^T ≥ 1 → fibre tension failure
             IFF_f^C ≥ 1 → fibre compression failure
             IFF_A ≥ 1   → matrix tension cracking
             IFF_B ≥ 1   → matrix shear/compression cracking

    Parameters
    ----------
    stress_material_frame : np.ndarray (3,)
        [σ_1, σ_2, τ_12] [Pa].
    ply : LaminaPly
    p_pT : float
        Slope parameter for tensile IFF (Mode A). Default 0.3.
    p_pC : float
        Slope parameter for compressive IFF (Mode B). Default 0.25.

    References
    ----------
    Puck A., Schürmann H. (1998). Composites Science and Technology 58:1045-1067.
    Knops M. (2008). "Analysis of Failure in Fibre Polymer Laminates." Springer.
    """
    s = np.asarray(stress_material_frame, dtype=float)
    s1, s2, t12 = s

    X_T, X_C = ply.sigma_1_T_pa, ply.sigma_1_C_pa
    Y_T, Y_C = ply.sigma_2_T_pa, ply.sigma_2_C_pa
    S = ply.tau_12_pa

    # Fibre failure
    if s1 >= 0:
        fi_ff = s1 / X_T
        ff_mode = "fibre"
    else:
        fi_ff = abs(s1) / X_C
        ff_mode = "fibre"

    # Inter-fibre failure
    if s2 >= 0:
        # Mode A (matrix tensile cracking)
        c1 = (t12 / S)**2
        c2 = (1.0 - p_pT * Y_T / S)**2 * (s2 / Y_T)**2
        iff_A = math.sqrt(max(c1 + c2, 0.0)) + p_pT * s2 / S
        fi_iff = iff_A
        iff_mode = "matrix"
    else:
        # Mode B (matrix compression/shear)
        # Mode C when |σ_2/Y_C| is large (simplified here: use Mode B expression)
        iff_B = (1.0 / S) * (math.sqrt(t12**2 + (p_pC * s2)**2) + p_pC * s2)
        fi_iff = iff_B
        iff_mode = "shear"

    FI = max(fi_ff, fi_iff)
    if FI == fi_ff:
        mode = ff_mode
    else:
        mode = iff_mode

    return _make_result("puck", FI, mode)


# ---------------------------------------------------------------------------
# Hashin criterion
# ---------------------------------------------------------------------------

def hashin(
    stress_material_frame: np.ndarray,
    ply: "LaminaPly",
    alpha_ht: float = 1.0,
) -> FailureResult:
    """
    Hashin (1980) failure criterion for unidirectional composites.

    Four distinct failure modes (plane stress):

    1. Fibre tension (σ_1 > 0):
        FI_ft = (σ_1 / X_T)² + α (τ_12 / S)²

    2. Fibre compression (σ_1 < 0):
        FI_fc = (σ_1 / X_C)²

    3. Matrix tension (σ_2 > 0):
        FI_mt = (σ_2 / Y_T)² + (τ_12 / S)²

    4. Matrix compression (σ_2 < 0):
        FI_mc = (σ_2 / 2S)² + [(Y_C / 2S)² - 1] σ_2/Y_C + (τ_12 / S)²

    Overall FI = max of all four.

    Parameters
    ----------
    stress_material_frame : np.ndarray (3,)
        [σ_1, σ_2, τ_12] [Pa].
    ply : LaminaPly
    alpha_ht : float
        Contribution of shear to fibre tension mode. 0 or 1. Default 1.

    References
    ----------
    Hashin Z. (1980). "Failure Criteria for Unidirectional Fibre Composites."
      J. Appl. Mech. 47(2):329-334.
    """
    s = np.asarray(stress_material_frame, dtype=float)
    s1, s2, t12 = s

    X_T, X_C = ply.sigma_1_T_pa, ply.sigma_1_C_pa
    Y_T, Y_C = ply.sigma_2_T_pa, ply.sigma_2_C_pa
    S = ply.tau_12_pa

    alpha_ht = float(alpha_ht)

    # 1. Fibre tension
    fi_ft = (s1/X_T)**2 + alpha_ht*(t12/S)**2 if s1 >= 0 else 0.0

    # 2. Fibre compression
    fi_fc = (s1/X_C)**2 if s1 < 0 else 0.0

    # 3. Matrix tension
    fi_mt = (s2/Y_T)**2 + (t12/S)**2 if s2 >= 0 else 0.0

    # 4. Matrix compression
    fi_mc = 0.0
    if s2 < 0:
        fi_mc = ((s2/(2.0*S))**2
                 + ((Y_C/(2.0*S))**2 - 1.0) * s2/Y_C
                 + (t12/S)**2)

    fi_modes = {
        "fibre":  max(fi_ft, fi_fc),
        "matrix": max(fi_mt, fi_mc),
    }
    FI = max(fi_modes.values())
    mode = max(fi_modes, key=lambda k: fi_modes[k])

    return _make_result("hashin", FI, mode)


# ---------------------------------------------------------------------------
# First-ply failure analysis
# ---------------------------------------------------------------------------

_CRITERION_MAP = {
    "tsai_wu":      lambda s, p: tsai_wu(s, p),
    "tsai_hill":    tsai_hill,
    "maximum_stress": maximum_stress,
    "hashin":       hashin,
    "puck":         puck,
}


def first_ply_failure_analysis(
    laminate: "Laminate",
    response: "LaminateResponse",
    criterion: str = "tsai_wu",
) -> dict:
    """
    First-ply failure (FPF) analysis of a loaded laminate.

    Evaluates the chosen failure criterion on every ply and reports
    the ply with the highest failure index (nearest to first failure).

    Parameters
    ----------
    laminate : Laminate
        The composite laminate definition.
    response : LaminateResponse
        CLT solution from analyze_laminate().
    criterion : str
        Failure criterion to apply: 'tsai_wu' | 'tsai_hill' | 'maximum_stress'
        | 'hashin' | 'puck'. Default 'tsai_wu'.

    Returns
    -------
    dict with keys:
        'first_failed_ply_index'             : int (0-based)
        'failure_index_at_first_failure'     : float
        'safety_factor_to_first_ply_failure' : float
        'failed_mode'                        : str
        'ply_failure_indices'                : list[float]  (all plies)
        'criterion'                          : str
        'ply_results'                        : list[dict]   (detailed per-ply)

    References
    ----------
    Jones (1999) Ch. 4 §4.5.
    Reddy (2003) §6.4.
    """
    criterion = criterion.lower()
    if criterion not in _CRITERION_MAP:
        raise ValueError(
            f"Unknown criterion {criterion!r}. "
            f"Choose from: {list(_CRITERION_MAP.keys())}"
        )
    fn = _CRITERION_MAP[criterion]

    ply_results = []
    for i, (ply, sigma_mat) in enumerate(
            zip(laminate.plies, response.ply_stresses)):
        result = fn(sigma_mat, ply)
        ply_results.append({
            "ply_index":     i,
            "orientation":   ply.orientation_deg,
            "material":      ply.material_name,
            "failure_index": result.failure_index,
            "failed":        result.failed,
            "failed_mode":   result.failed_mode,
            "safety_factor": result.safety_factor,
        })

    fi_values = [r["failure_index"] for r in ply_results]
    max_fi = max(fi_values)
    max_idx = fi_values.index(max_fi)
    sf = ply_results[max_idx]["safety_factor"]

    return {
        "first_failed_ply_index":             max_idx,
        "failure_index_at_first_failure":     max_fi,
        "safety_factor_to_first_ply_failure": sf,
        "failed_mode":                        ply_results[max_idx]["failed_mode"],
        "ply_failure_indices":                fi_values,
        "criterion":                          criterion,
        "ply_results":                        ply_results,
    }
