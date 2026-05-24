"""
kerf_cad_core.struct.eurocode5 — Eurocode 5 (EN 1995-1-1) timber design.

Pure-Python; no OCC dependency.  All functions return plain dicts and never raise.
On error, returns {"ok": False, "reason": "<message>"}.

Registers LLM tools with the Kerf tool registry:

  ec5_strength_class        — look up EN 338 / EN 14080 characteristic values
  ec5_kmod                  — kmod factor for service class + load duration
  ec5_design_strength       — design strengths fmd, ft0d, fc0d, fvd, E0mean_d
  ec5_beam_bending          — §6.1.6 bending ULS check (kh size factor)
  ec5_combined_nm           — §6.2.4 combined N+M interaction
  ec5_column_buckling       — §6.3.2 column relative slenderness + kc + check
  ec5_shear                 — §6.1.7 shear ULS check (kcr reduction)

Units: SI — lengths in mm, forces in kN, stresses in N/mm² (MPa).

References
----------
EN 1995-1-1:2004+A1:2008 — Design of Timber Structures. General – Common rules.
EN 338:2016 — Structural timber. Strength classes.
EN 14080:2013 — Timber structures. Glued laminated timber and glued solid timber.
Porteous, J. & Kermani, A. "Structural Timber Design to Eurocode 5" (2nd ed., 2013).
Trada Technology "Eurocode 5: Design of Timber Structures" (2012).

Author: imranparuk
"""
from __future__ import annotations

import json
import math

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

# ---------------------------------------------------------------------------
# Partial factors  (EN 1995-1-1 Table 2.3)
# ---------------------------------------------------------------------------

EC5_GAMMA_M_SOLID = 1.3    # solid timber
EC5_GAMMA_M_GLULAM = 1.25  # glued laminated timber (glulam)
EC5_GAMMA_M_LVL = 1.2      # laminated veneer lumber

# ---------------------------------------------------------------------------
# kmod table  (EN 1995-1-1 Table 3.1)
# Rows: service class 1 / 2 / 3
# Cols: permanent / long_term / medium / short / instantaneous
# ---------------------------------------------------------------------------

_KMOD_TABLE: dict[int, dict[str, float]] = {
    1: {
        "permanent":      0.60,
        "long_term":      0.70,
        "medium":         0.80,
        "short":          0.90,
        "instantaneous":  1.10,
    },
    2: {
        "permanent":      0.60,
        "long_term":      0.70,
        "medium":         0.80,
        "short":          0.90,
        "instantaneous":  1.10,
    },
    3: {
        "permanent":      0.50,
        "long_term":      0.55,
        "medium":         0.65,
        "short":          0.70,
        "instantaneous":  0.90,
    },
}

_LOAD_DURATIONS = ("permanent", "long_term", "medium", "short", "instantaneous")

# ---------------------------------------------------------------------------
# Strength classes  (EN 338:2016 Table 1 — softwood C and hardwood D)
# and glulam     (EN 14080:2013 Table F.1 — homogeneous GL h)
#
# Fields: fm_k, ft0_k, fc0_k, fv_k, E0_mean, E0_05, rho_k
# Units:  N/mm² (MPa) for stresses, N/mm² for E, kg/m³ for density
# ---------------------------------------------------------------------------

_STRENGTH_CLASSES: dict[str, dict[str, float]] = {
    # ---- Softwood (EN 338) ----
    "C14": {"fm_k": 14, "ft0_k":  8, "fc0_k": 16, "fv_k": 3.0, "E0_mean": 7000,  "E0_05": 4700,  "rho_k": 290},
    "C16": {"fm_k": 16, "ft0_k": 10, "fc0_k": 17, "fv_k": 3.2, "E0_mean": 8000,  "E0_05": 5400,  "rho_k": 310},
    "C18": {"fm_k": 18, "ft0_k": 11, "fc0_k": 18, "fv_k": 3.4, "E0_mean": 9000,  "E0_05": 6000,  "rho_k": 320},
    "C20": {"fm_k": 20, "ft0_k": 12, "fc0_k": 19, "fv_k": 3.6, "E0_mean": 9500,  "E0_05": 6400,  "rho_k": 330},
    "C22": {"fm_k": 22, "ft0_k": 13, "fc0_k": 20, "fv_k": 3.8, "E0_mean": 10000, "E0_05": 6700,  "rho_k": 340},
    "C24": {"fm_k": 24, "ft0_k": 14, "fc0_k": 21, "fv_k": 4.0, "E0_mean": 11000, "E0_05": 7400,  "rho_k": 350},
    "C27": {"fm_k": 27, "ft0_k": 16, "fc0_k": 22, "fv_k": 4.0, "E0_mean": 11500, "E0_05": 7700,  "rho_k": 370},
    "C30": {"fm_k": 30, "ft0_k": 18, "fc0_k": 23, "fv_k": 4.0, "E0_mean": 12000, "E0_05": 8000,  "rho_k": 380},
    "C35": {"fm_k": 35, "ft0_k": 21, "fc0_k": 25, "fv_k": 4.0, "E0_mean": 13000, "E0_05": 8700,  "rho_k": 400},
    "C40": {"fm_k": 40, "ft0_k": 24, "fc0_k": 26, "fv_k": 4.0, "E0_mean": 14000, "E0_05": 9400,  "rho_k": 420},
    "C45": {"fm_k": 45, "ft0_k": 27, "fc0_k": 27, "fv_k": 4.0, "E0_mean": 15000, "E0_05": 10000, "rho_k": 440},
    "C50": {"fm_k": 50, "ft0_k": 30, "fc0_k": 29, "fv_k": 4.0, "E0_mean": 16000, "E0_05": 10700, "rho_k": 460},
    # ---- Hardwood (EN 338) ----
    "D30": {"fm_k": 30, "ft0_k": 18, "fc0_k": 23, "fv_k": 4.0, "E0_mean": 10000, "E0_05": 6200,  "rho_k": 530},
    "D35": {"fm_k": 35, "ft0_k": 21, "fc0_k": 25, "fv_k": 4.0, "E0_mean": 10000, "E0_05": 6700,  "rho_k": 560},
    "D40": {"fm_k": 40, "ft0_k": 24, "fc0_k": 26, "fv_k": 4.0, "E0_mean": 11000, "E0_05": 7500,  "rho_k": 590},
    "D50": {"fm_k": 50, "ft0_k": 30, "fc0_k": 29, "fv_k": 4.0, "E0_mean": 14000, "E0_05": 9400,  "rho_k": 650},
    "D60": {"fm_k": 60, "ft0_k": 36, "fc0_k": 32, "fv_k": 4.5, "E0_mean": 17000, "E0_05": 11400, "rho_k": 700},
    "D70": {"fm_k": 70, "ft0_k": 42, "fc0_k": 34, "fv_k": 5.0, "E0_mean": 20000, "E0_05": 13400, "rho_k": 900},
    # ---- Glulam homogeneous (EN 14080:2013 Table F.1) ----
    "GL24h": {"fm_k": 24, "ft0_k": 16.5, "fc0_k": 24, "fv_k": 3.5, "E0_mean": 11600, "E0_05": 9400,  "rho_k": 380},
    "GL28h": {"fm_k": 28, "ft0_k": 19.5, "fc0_k": 26.5, "fv_k": 3.5, "E0_mean": 12600, "E0_05": 10200, "rho_k": 410},
    "GL32h": {"fm_k": 32, "ft0_k": 22.5, "fc0_k": 29,   "fv_k": 3.8, "E0_mean": 13700, "E0_05": 11100, "rho_k": 430},
}

# Classify glulam classes for γM selection
_GLULAM_CLASSES = {"GL24h", "GL28h", "GL32h"}
_LVL_CLASSES: set[str] = set()  # LVL not in generic table; γM=1.2 when explicitly requested


def _gamma_m(strength_class: str) -> float:
    """Return the appropriate γM for the given strength class."""
    if strength_class in _GLULAM_CLASSES:
        return EC5_GAMMA_M_GLULAM
    return EC5_GAMMA_M_SOLID


# ---------------------------------------------------------------------------
# Core design functions
# ---------------------------------------------------------------------------

def kmod(service_class: int, load_duration: str) -> dict:
    """
    EN 1995-1-1 Table 3.1 — modification factor for load duration and moisture.

    Parameters
    ----------
    service_class : int
        1, 2, or 3 (EN 1995-1-1 §2.3.1.3)
    load_duration : str
        One of: permanent, long_term, medium, short, instantaneous

    Returns
    -------
    dict with keys: ok, kmod, service_class, load_duration
    """
    if service_class not in (1, 2, 3):
        return {"ok": False, "reason": f"service_class must be 1, 2, or 3; got {service_class!r}"}
    ld = str(load_duration).strip().lower()
    if ld not in _LOAD_DURATIONS:
        return {
            "ok": False,
            "reason": (
                f"load_duration {load_duration!r} not recognised. "
                f"Valid values: {list(_LOAD_DURATIONS)}"
            ),
        }
    value = _KMOD_TABLE[service_class][ld]
    return {"ok": True, "kmod": value, "service_class": service_class, "load_duration": ld}


def strength_class(name: str) -> dict:
    """
    Return EN 338 / EN 14080 characteristic strength and stiffness values.

    Parameters
    ----------
    name : str
        Strength class, e.g. 'C24', 'GL28h', 'D40'.

    Returns
    -------
    dict with keys: ok, name, fm_k, ft0_k, fc0_k, fv_k, E0_mean, E0_05, rho_k, gamma_M
        All stresses in N/mm², E in N/mm², density in kg/m³.
    """
    key = str(name).strip().upper()
    # Normalise lowercase h suffix for glulam: GL24H → GL24h
    for sc in _STRENGTH_CLASSES:
        if sc.upper() == key:
            key = sc
            break
    sc_data = _STRENGTH_CLASSES.get(key)
    if sc_data is None:
        valid = sorted(_STRENGTH_CLASSES.keys())
        return {
            "ok": False,
            "reason": f"Unknown strength class '{name}'. Valid: {valid}",
        }
    return {
        "ok": True,
        "name": key,
        "gamma_M": _gamma_m(key),
        **sc_data,
    }


def design_strengths(
    strength_class_name: str,
    service_class: int,
    load_duration: str,
) -> dict:
    """
    EN 1995-1-1 §2.4.1 — design strengths.

    fd = kmod × fk / γM  (for all strength properties)
    E0mean_d = E0mean / γM  (mean value for deformation; often used without kmod)

    Parameters
    ----------
    strength_class_name : str  e.g. 'C24', 'GL28h'
    service_class       : int  1, 2 or 3
    load_duration       : str  e.g. 'medium'

    Returns
    -------
    dict with keys: ok, fm_d, ft0_d, fc0_d, fv_d, E0mean_d, kmod, gamma_M, ...
    """
    sc = strength_class(strength_class_name)
    if not sc["ok"]:
        return sc
    km = kmod(service_class, load_duration)
    if not km["ok"]:
        return km

    k = km["kmod"]
    gm = sc["gamma_M"]
    return {
        "ok": True,
        "strength_class": sc["name"],
        "service_class": service_class,
        "load_duration": load_duration,
        "kmod": k,
        "gamma_M": gm,
        # Characteristic values (pass-through)
        "fm_k": sc["fm_k"],
        "ft0_k": sc["ft0_k"],
        "fc0_k": sc["fc0_k"],
        "fv_k": sc["fv_k"],
        "E0_mean": sc["E0_mean"],
        "E0_05": sc["E0_05"],
        "rho_k": sc["rho_k"],
        # Design values (6 d.p. for test precision; trim trailing zeros on display)
        "fm_d":    round(k * sc["fm_k"] / gm, 6),
        "ft0_d":   round(k * sc["ft0_k"] / gm, 6),
        "fc0_d":   round(k * sc["fc0_k"] / gm, 6),
        "fv_d":    round(k * sc["fv_k"] / gm, 6),
        "E0mean_d": round(sc["E0_mean"] / gm, 6),   # §2.2.2: stiffness without kmod
    }


def beam_bending_check(
    M_d_kNm: float,
    b_mm: float,
    h_mm: float,
    fm_d: float,
    *,
    kh_override: float | None = None,
) -> dict:
    """
    EN 1995-1-1 §6.1.6 — bending ULS check.

    σm,d = M_d / Wy ≤ fm,d × kh

    kh (size factor) = min((150/h)^0.2, 1.3) for h < 150 mm (solid timber).
    For h ≥ 150 mm, kh = 1.0.
    kh_override allows forcing a specific value (e.g. for glulam per §3.3).

    Parameters
    ----------
    M_d_kNm  : float   Design bending moment (kN·m)
    b_mm     : float   Section breadth (mm)
    h_mm     : float   Section height (depth) (mm)
    fm_d     : float   Design bending strength (N/mm²)
    kh_override : float | None   If provided, overrides computed kh.

    Returns
    -------
    dict with: ok, sigma_md, fm_d_eff, kh, utilization, pass_
    """
    errors = []
    if b_mm <= 0:
        errors.append("b_mm must be > 0")
    if h_mm <= 0:
        errors.append("h_mm must be > 0")
    if fm_d <= 0:
        errors.append("fm_d must be > 0")
    if errors:
        return {"ok": False, "reason": "; ".join(errors)}

    # Section modulus Wy = b·h²/6  (mm³)
    Wy_mm3 = b_mm * h_mm ** 2 / 6.0
    # Convert M from kN·m → N·mm: × 1e6
    M_d_Nmm = M_d_kNm * 1e6
    sigma_md = M_d_Nmm / Wy_mm3  # N/mm²

    if kh_override is not None:
        kh = float(kh_override)
    elif h_mm < 150.0:
        kh = min((150.0 / h_mm) ** 0.2, 1.3)
    else:
        kh = 1.0

    fm_d_eff = fm_d * kh
    utilization = sigma_md / fm_d_eff if fm_d_eff > 0 else float("inf")
    pass_ = utilization <= 1.0

    warnings: list[str] = []
    if utilization > 1.0:
        warnings.append(
            f"FAIL: σm,d={sigma_md:.3f} N/mm² > fm,d·kh={fm_d_eff:.3f} N/mm²"
        )

    return {
        "ok": True,
        "sigma_md_MPa": round(sigma_md, 6),
        "fm_d_MPa": fm_d,
        "kh": round(kh, 10),
        "fm_d_eff_MPa": round(fm_d_eff, 6),
        "Wy_mm3": round(Wy_mm3, 2),
        "utilization": round(utilization, 10),
        "pass_": pass_,
        "warnings": warnings,
    }


def combined_nm_check(
    sigma_c0d: float,
    fc0_d: float,
    sigma_md: float,
    fm_d: float,
    *,
    tension: bool = False,
    kc: float = 1.0,
) -> dict:
    """
    EN 1995-1-1 §6.2.4 — combined compression (or tension) + bending.

    Compression (EC5 Eq. 6.23):
        (σc,0,d / (kc · fc,0,d))² + σm,d / fm,d ≤ 1

    Tension (EC5 Eq. 6.17):
        σt,0,d / ft,0,d + σm,d / fm,d ≤ 1

    Parameters
    ----------
    sigma_c0d : float  Design compressive (or tensile) stress parallel to grain (N/mm²)
    fc0_d     : float  Design compressive (or tensile) strength (N/mm²)
    sigma_md  : float  Design bending stress (N/mm²)
    fm_d      : float  Design bending strength (N/mm²)
    tension   : bool   If True, use linear tension interaction (Eq. 6.17)
    kc        : float  Column instability factor (1.0 for no buckling, §6.3.2)

    Returns
    -------
    dict with: ok, interaction, pass_, warnings
    """
    errors = []
    if fc0_d <= 0:
        errors.append("fc0_d must be > 0")
    if fm_d <= 0:
        errors.append("fm_d must be > 0")
    if kc <= 0 or kc > 1.0:
        errors.append("kc must be in (0, 1]")
    if errors:
        return {"ok": False, "reason": "; ".join(errors)}

    if tension:
        # Eq. 6.17
        interaction = sigma_c0d / fc0_d + sigma_md / fm_d
        label = "tension linear"
    else:
        # Eq. 6.23 — compression with stability
        interaction = (sigma_c0d / (kc * fc0_d)) ** 2 + sigma_md / fm_d
        label = "compression with buckling"

    pass_ = interaction <= 1.0
    warnings: list[str] = []
    if not pass_:
        warnings.append(f"FAIL ({label}): interaction={interaction:.4f} > 1.0")

    return {
        "ok": True,
        "interaction": round(interaction, 6),
        "label": label,
        "pass_": pass_,
        "kc": kc,
        "warnings": warnings,
    }


def column_buckling(
    L_mm: float,
    b_mm: float,
    h_mm: float,
    fc0_k: float,
    E0_05: float,
    fc0_d: float,
    sigma_c0d: float,
    *,
    beta_c: float = 0.2,
    k_e: float = 1.0,
    axis: str = "min",
) -> dict:
    """
    EN 1995-1-1 §6.3.2 — column stability (relative slenderness + kc factor).

    λ_rel = (L_eff / i) · √(fc0_k / E0_05) / π
    k     = 0.5 · [1 + βc · (λ_rel − 0.3) + λ_rel²]
    kc    = 1 / (k + √(k² − λ_rel²))
    σc,0,d ≤ kc · fc,0,d

    Parameters
    ----------
    L_mm      : float   Member length (mm) — buckling length = k_e × L_mm
    b_mm      : float   Section breadth (mm)
    h_mm      : float   Section depth (mm)
    fc0_k     : float   Characteristic compressive strength (N/mm²)
    E0_05     : float   5th-percentile modulus of elasticity (N/mm²)
    fc0_d     : float   Design compressive strength (N/mm²)
    sigma_c0d : float   Design compressive stress (N/mm²)
    beta_c    : float   Imperfection factor: 0.2 solid timber, 0.1 glulam (EN 1995-1-1 §6.3.2(3))
    k_e       : float   Effective length factor (1.0 pin-pin, 0.7 fix-pin, 0.5 fix-fix)
    axis      : str     'min' (weak), 'max' (strong), 'both' — default 'min'

    Returns
    -------
    dict with: ok, lambda_rel_y, lambda_rel_z, kc_y, kc_z, kc, sigma_c0d, fc0_d,
               utilization, pass_, warnings
    """
    errors = []
    if L_mm <= 0:
        errors.append("L_mm must be > 0")
    if b_mm <= 0:
        errors.append("b_mm must be > 0")
    if h_mm <= 0:
        errors.append("h_mm must be > 0")
    if fc0_k <= 0:
        errors.append("fc0_k must be > 0")
    if E0_05 <= 0:
        errors.append("E0_05 must be > 0")
    if fc0_d <= 0:
        errors.append("fc0_d must be > 0")
    if errors:
        return {"ok": False, "reason": "; ".join(errors)}

    L_eff = k_e * L_mm  # effective buckling length (mm)

    # Radii of gyration for rectangular section
    i_y = h_mm / math.sqrt(12.0)  # major axis (depth h)
    i_z = b_mm / math.sqrt(12.0)  # minor axis (breadth b)

    def _lambda_rel(i: float) -> float:
        slenderness = L_eff / i
        return slenderness * math.sqrt(fc0_k / E0_05) / math.pi

    def _kc(lam: float) -> float:
        if lam <= 0.3:
            return 1.0  # no buckling reduction (EC5 §6.3.2(3))
        k = 0.5 * (1.0 + beta_c * (lam - 0.3) + lam ** 2)
        disc = k ** 2 - lam ** 2
        if disc < 0:
            disc = 0.0
        return 1.0 / (k + math.sqrt(disc))

    lam_y = _lambda_rel(i_y)  # relative slenderness about y-axis (strong)
    lam_z = _lambda_rel(i_z)  # relative slenderness about z-axis (weak → governs)
    kc_y = _kc(lam_y)
    kc_z = _kc(lam_z)

    # Governing (minimum kc)
    kc_gov = min(kc_y, kc_z)
    governing_axis = "z (weak)" if kc_z <= kc_y else "y (strong)"

    utilization = sigma_c0d / (kc_gov * fc0_d) if kc_gov * fc0_d > 0 else float("inf")
    pass_ = utilization <= 1.0

    warnings: list[str] = []
    if lam_z > 1.5 or lam_y > 1.5:
        warnings.append(
            f"High relative slenderness (λ_rel_z={lam_z:.3f}): check buckling sensitivity"
        )
    if not pass_:
        warnings.append(
            f"FAIL: σc,0,d={sigma_c0d:.3f} > kc·fc,0,d = {kc_gov:.4f}×{fc0_d:.3f}={kc_gov*fc0_d:.3f} N/mm²"
        )

    return {
        "ok": True,
        "L_eff_mm": round(L_eff, 2),
        "i_y_mm": round(i_y, 10),
        "i_z_mm": round(i_z, 10),
        "lambda_rel_y": round(lam_y, 10),
        "lambda_rel_z": round(lam_z, 10),
        "kc_y": round(kc_y, 10),
        "kc_z": round(kc_z, 10),
        "kc": round(kc_gov, 10),
        "governing_axis": governing_axis,
        "beta_c": beta_c,
        "sigma_c0d_MPa": round(sigma_c0d, 6),
        "fc0_d_MPa": round(fc0_d, 6),
        "kc_fc0d_MPa": round(kc_gov * fc0_d, 10),
        "utilization": round(utilization, 10),
        "pass_": pass_,
        "warnings": warnings,
    }


def shear_check(
    V_d_kN: float,
    b_mm: float,
    h_mm: float,
    fv_d: float,
    *,
    kcr: float = 0.67,
) -> dict:
    """
    EN 1995-1-1 §6.1.7 — shear ULS check.

    τd = 1.5 · Vd / (b · h) ≤ kcr · fv,d

    kcr accounts for cracking (EN 1995-1-1 §6.1.7(2)):
      kcr = 0.67 (solid timber) / 1.0 (glulam — cracks already in design)

    Parameters
    ----------
    V_d_kN : float  Design shear force (kN)
    b_mm   : float  Section breadth (mm)
    h_mm   : float  Section depth (mm)
    fv_d   : float  Design shear strength (N/mm²)
    kcr    : float  Crack factor (0.67 solid, 1.0 glulam); default 0.67

    Returns
    -------
    dict with: ok, tau_d, fv_d_eff, utilization, pass_, warnings
    """
    errors = []
    if b_mm <= 0:
        errors.append("b_mm must be > 0")
    if h_mm <= 0:
        errors.append("h_mm must be > 0")
    if fv_d <= 0:
        errors.append("fv_d must be > 0")
    if kcr <= 0:
        errors.append("kcr must be > 0")
    if errors:
        return {"ok": False, "reason": "; ".join(errors)}

    # Convert kN → N
    V_d_N = V_d_kN * 1e3
    A_mm2 = b_mm * h_mm
    tau_d = 1.5 * V_d_N / A_mm2  # N/mm²

    fv_d_eff = kcr * fv_d
    utilization = tau_d / fv_d_eff if fv_d_eff > 0 else float("inf")
    pass_ = utilization <= 1.0

    warnings: list[str] = []
    if not pass_:
        warnings.append(
            f"FAIL: τd={tau_d:.4f} N/mm² > kcr·fv,d={fv_d_eff:.4f} N/mm²"
        )

    return {
        "ok": True,
        "tau_d_MPa": round(tau_d, 10),
        "fv_d_MPa": fv_d,
        "kcr": kcr,
        "fv_d_eff_MPa": round(fv_d_eff, 6),
        "utilization": round(utilization, 10),
        "pass_": pass_,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# LLM tool wrappers
# ---------------------------------------------------------------------------

def _err(msg: str) -> str:
    return ok_payload({"ok": False, "reason": msg})


# ---- ec5_strength_class ----

_sc_spec = ToolSpec(
    name="ec5_strength_class",
    description=(
        "Look up EN 338 / EN 14080 characteristic strength and stiffness values for an "
        "EC5 timber strength class.\n\n"
        "Softwood (EN 338): C14, C16, C18, C20, C22, C24, C27, C30, C35, C40, C45, C50.\n"
        "Hardwood (EN 338): D30, D35, D40, D50, D60, D70.\n"
        "Glulam homogeneous (EN 14080): GL24h, GL28h, GL32h.\n\n"
        "Returns: fm_k, ft0_k, fc0_k, fv_k (N/mm²); E0_mean, E0_05 (N/mm²); "
        "rho_k (kg/m³); gamma_M."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Strength class name, e.g. 'C24', 'GL28h', 'D40'.",
            },
        },
        "required": ["name"],
    },
)


@register(_sc_spec, write=False)
async def run_ec5_strength_class(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    name = a.get("name")
    if not name:
        return _err("name is required")
    return ok_payload(strength_class(str(name)))


# ---- ec5_kmod ----

_kmod_spec = ToolSpec(
    name="ec5_kmod",
    description=(
        "Return the EN 1995-1-1 Table 3.1 kmod factor for a given service class and "
        "load-duration class.\n\n"
        "service_class: 1 (dry interior), 2 (covered outdoor), 3 (exposed outdoor).\n"
        "load_duration: permanent | long_term | medium | short | instantaneous.\n\n"
        "kmod is used to convert characteristic strength to design strength: "
        "fd = kmod × fk / γM."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "service_class": {
                "type": "integer",
                "description": "Service class: 1, 2, or 3.",
            },
            "load_duration": {
                "type": "string",
                "description": (
                    "Load-duration class: permanent | long_term | medium | short | instantaneous."
                ),
            },
        },
        "required": ["service_class", "load_duration"],
    },
)


@register(_kmod_spec, write=False)
async def run_ec5_kmod(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    sc = a.get("service_class")
    ld = a.get("load_duration")
    if sc is None:
        return _err("service_class is required")
    if ld is None:
        return _err("load_duration is required")
    return ok_payload(kmod(int(sc), str(ld)))


# ---- ec5_design_strength ----

_ds_spec = ToolSpec(
    name="ec5_design_strength",
    description=(
        "Compute EC5 design strengths for a given strength class, service class and "
        "load-duration class.\n\n"
        "Returns: fm_d, ft0_d, fc0_d, fv_d (N/mm²) and E0mean_d (N/mm²), "
        "plus the input characteristic values and factors used.\n\n"
        "fd = kmod × fk / γM  (EN 1995-1-1 §2.4.1)\n"
        "E0mean_d = E0mean / γM (deformation, no kmod per §2.2.2)"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "strength_class": {
                "type": "string",
                "description": "Timber strength class, e.g. 'C24', 'GL28h'.",
            },
            "service_class": {
                "type": "integer",
                "description": "Service class 1, 2, or 3.",
            },
            "load_duration": {
                "type": "string",
                "description": "Load-duration class: permanent | long_term | medium | short | instantaneous.",
            },
        },
        "required": ["strength_class", "service_class", "load_duration"],
    },
)


@register(_ds_spec, write=False)
async def run_ec5_design_strength(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    sc_name = a.get("strength_class")
    sc_class = a.get("service_class")
    ld = a.get("load_duration")
    if not sc_name:
        return _err("strength_class is required")
    if sc_class is None:
        return _err("service_class is required")
    if not ld:
        return _err("load_duration is required")
    return ok_payload(design_strengths(str(sc_name), int(sc_class), str(ld)))


# ---- ec5_beam_bending ----

_bb_spec = ToolSpec(
    name="ec5_beam_bending",
    description=(
        "EC5 §6.1.6 bending ULS check for a rectangular timber section.\n\n"
        "σm,d = M_d / Wy ≤ fm,d × kh\n"
        "kh = min((150/h)^0.2, 1.3) for h < 150 mm (size factor); kh=1.0 for h≥150.\n\n"
        "M_d_kNm: design bending moment (kN·m).\n"
        "b_mm, h_mm: section breadth and depth (mm).\n"
        "fm_d: design bending strength (N/mm²) — obtain via ec5_design_strength.\n"
        "kh_override: optional, force a specific kh (e.g. 1.0 for glulam §3.3)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "M_d_kNm": {"type": "number", "description": "Design moment (kN·m)."},
            "b_mm": {"type": "number", "description": "Section breadth (mm)."},
            "h_mm": {"type": "number", "description": "Section depth (mm)."},
            "fm_d": {"type": "number", "description": "Design bending strength fm,d (N/mm²)."},
            "kh_override": {
                "type": "number",
                "description": "Override size factor kh (optional; 1.0 = no override).",
            },
        },
        "required": ["M_d_kNm", "b_mm", "h_mm", "fm_d"],
    },
)


@register(_bb_spec, write=False)
async def run_ec5_beam_bending(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    M = a.get("M_d_kNm")
    b = a.get("b_mm")
    h = a.get("h_mm")
    fm = a.get("fm_d")
    if M is None:
        return _err("M_d_kNm is required")
    if b is None:
        return _err("b_mm is required")
    if h is None:
        return _err("h_mm is required")
    if fm is None:
        return _err("fm_d is required")
    kh_ov = a.get("kh_override")
    return ok_payload(beam_bending_check(float(M), float(b), float(h), float(fm),
                                         kh_override=kh_ov))


# ---- ec5_combined_nm ----

_cnm_spec = ToolSpec(
    name="ec5_combined_nm",
    description=(
        "EC5 §6.2.4 combined axial + bending interaction check.\n\n"
        "Compression: (σc,0,d / (kc·fc,0,d))² + σm,d/fm,d ≤ 1  (Eq. 6.23)\n"
        "Tension:      σt,0,d / ft,0,d + σm,d / fm,d ≤ 1         (Eq. 6.17)\n\n"
        "kc: column stability factor from ec5_column_buckling (use 1.0 for no buckling).\n"
        "All stresses and strengths in N/mm²."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma_c0d": {"type": "number", "description": "Design axial stress (N/mm²). Positive = compression."},
            "fc0_d": {"type": "number", "description": "Design compressive (or tensile) strength (N/mm²)."},
            "sigma_md": {"type": "number", "description": "Design bending stress (N/mm²)."},
            "fm_d": {"type": "number", "description": "Design bending strength (N/mm²)."},
            "tension": {
                "type": "boolean",
                "description": "True = tension+bending (Eq. 6.17); False = compression+bending with buckling (Eq. 6.23). Default False.",
            },
            "kc": {
                "type": "number",
                "description": "Column instability factor kc (0 < kc ≤ 1.0); from ec5_column_buckling. Default 1.0.",
            },
        },
        "required": ["sigma_c0d", "fc0_d", "sigma_md", "fm_d"],
    },
)


@register(_cnm_spec, write=False)
async def run_ec5_combined_nm(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    for req in ("sigma_c0d", "fc0_d", "sigma_md", "fm_d"):
        if a.get(req) is None:
            return _err(f"{req} is required")
    return ok_payload(combined_nm_check(
        float(a["sigma_c0d"]),
        float(a["fc0_d"]),
        float(a["sigma_md"]),
        float(a["fm_d"]),
        tension=bool(a.get("tension", False)),
        kc=float(a.get("kc", 1.0)),
    ))


# ---- ec5_column_buckling ----

_cb_spec = ToolSpec(
    name="ec5_column_buckling",
    description=(
        "EC5 §6.3.2 column buckling check — relative slenderness, kc factor, and "
        "compression capacity.\n\n"
        "λ_rel = (Leff/i)·√(fc0_k/E0_05)/π\n"
        "k = 0.5·[1 + βc·(λ_rel−0.3) + λ_rel²]\n"
        "kc = 1/(k + √(k²−λ_rel²))   (≤ 1.0)\n"
        "σc,0,d ≤ kc·fc,0,d\n\n"
        "beta_c: 0.2 solid timber, 0.1 glulam (EN 1995-1-1 §6.3.2(3)).\n"
        "k_e: effective length factor (1.0 pin-pin, 0.7 fix-pin, 0.5 fix-fix).\n"
        "All lengths in mm, stresses in N/mm²."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "L_mm": {"type": "number", "description": "Column length (mm)."},
            "b_mm": {"type": "number", "description": "Section breadth (mm)."},
            "h_mm": {"type": "number", "description": "Section depth (mm)."},
            "fc0_k": {"type": "number", "description": "Characteristic compressive strength fc,0,k (N/mm²)."},
            "E0_05": {"type": "number", "description": "5th-percentile modulus E0,05 (N/mm²)."},
            "fc0_d": {"type": "number", "description": "Design compressive strength fc,0,d (N/mm²)."},
            "sigma_c0d": {"type": "number", "description": "Design compressive stress σc,0,d (N/mm²)."},
            "beta_c": {
                "type": "number",
                "description": "Imperfection factor: 0.2 solid timber (default), 0.1 glulam.",
            },
            "k_e": {
                "type": "number",
                "description": "Effective-length factor: 1.0 pin-pin (default), 0.7 fix-pin, 0.5 fix-fix.",
            },
        },
        "required": ["L_mm", "b_mm", "h_mm", "fc0_k", "E0_05", "fc0_d", "sigma_c0d"],
    },
)


@register(_cb_spec, write=False)
async def run_ec5_column_buckling(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    for req in ("L_mm", "b_mm", "h_mm", "fc0_k", "E0_05", "fc0_d", "sigma_c0d"):
        if a.get(req) is None:
            return _err(f"{req} is required")
    return ok_payload(column_buckling(
        float(a["L_mm"]),
        float(a["b_mm"]),
        float(a["h_mm"]),
        float(a["fc0_k"]),
        float(a["E0_05"]),
        float(a["fc0_d"]),
        float(a["sigma_c0d"]),
        beta_c=float(a.get("beta_c", 0.2)),
        k_e=float(a.get("k_e", 1.0)),
    ))


# ---- ec5_shear ----

_sh_spec = ToolSpec(
    name="ec5_shear",
    description=(
        "EC5 §6.1.7 shear ULS check for a rectangular cross-section.\n\n"
        "τd = 1.5·Vd / (b·h) ≤ kcr·fv,d\n\n"
        "kcr (crack factor): 0.67 solid timber (default), 1.0 glulam.\n"
        "V_d_kN: design shear force (kN).\n"
        "b_mm, h_mm: section breadth and depth (mm).\n"
        "fv_d: design shear strength (N/mm²) from ec5_design_strength."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V_d_kN": {"type": "number", "description": "Design shear force (kN)."},
            "b_mm": {"type": "number", "description": "Section breadth (mm)."},
            "h_mm": {"type": "number", "description": "Section depth (mm)."},
            "fv_d": {"type": "number", "description": "Design shear strength fv,d (N/mm²)."},
            "kcr": {
                "type": "number",
                "description": "Crack factor: 0.67 solid timber (default), 1.0 glulam.",
            },
        },
        "required": ["V_d_kN", "b_mm", "h_mm", "fv_d"],
    },
)


@register(_sh_spec, write=False)
async def run_ec5_shear(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    for req in ("V_d_kN", "b_mm", "h_mm", "fv_d"):
        if a.get(req) is None:
            return _err(f"{req} is required")
    return ok_payload(shear_check(
        float(a["V_d_kN"]),
        float(a["b_mm"]),
        float(a["h_mm"]),
        float(a["fv_d"]),
        kcr=float(a.get("kcr", 0.67)),
    ))
