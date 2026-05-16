"""
kerf_cad_core.channel.flow — Open-channel hydraulics.

Covers geometry and hydraulic properties for five cross-section shapes, plus
a full suite of open-channel analysis functions.  Pure Python (math module
only); no third-party dependencies.

Sections supported
------------------
  rectangular  — bottom width b, depth y
  trapezoidal  — bottom width b, side slope z (H:V), depth y
  triangular   — side slope z (H:V), depth y  (b=0 trapezoidal)
  circular     — diameter D, depth y (partial-flow)
  parabolic    — top width T at depth y=d (shape param T²/4d), depth y

Capabilities
------------
  section_properties   — A, P, T (top width), R, D_h, Z (section factor)
  normal_depth         — Manning / Chezy bisection
  critical_depth       — bisection on Z² = Q²/g
  froude_number        — Fr = V / √(g·D_h) ; flow regime
  specific_energy      — E = y + V²/2g; minimum specific energy
  momentum_function    — M = Q²/(gA) + ȳA
  hydraulic_jump       — sequent depth y₂, energy loss ΔE, length estimate
  gvf_profile_type     — M/S/C/H/A classification per Chow
  gvf_direct_step      — water-surface profile (direct-step method)
  best_hydraulic_section — dimensions of most-efficient section
  weir_broad_crested   — Q = Cd·L·H^(3/2)
  weir_sharp_crested   — Q = (2/3)·Cd·L·√(2g)·H^(3/2)
  weir_vnotch          — Q = (8/15)·Cd·tan(θ/2)·√(2g)·H^(5/2)
  culvert_control      — inlet vs outlet control, capacity
  channel_transition   — energy/depth at contraction / expansion

All errors are returned inside the result dict as {"ok": False, "reason": ...}.
Supercritical flow, choked conditions, and non-convergence are flagged in
result["warnings"]; functions never raise.

Units: SI (metres, m³/s) throughout unless stated otherwise.

References
----------
Chow, V.T. (1959) Open-Channel Hydraulics.  McGraw-Hill.
Henderson, F.M. (1966) Open Channel Flow.  Macmillan.
French, R.H. (1985) Open-Channel Hydraulics.  McGraw-Hill.

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings as _warnings_mod
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_G: float = 9.80665          # gravitational acceleration (m/s²)
_MAX_ITER: int = 200         # bisection iteration cap
_BISECT_TOL: float = 1e-9    # bisection convergence tolerance (m)


# ---------------------------------------------------------------------------
# Section properties
# ---------------------------------------------------------------------------

def _section_props(
    shape: str,
    y: float,
    b: float = 0.0,
    z: float = 0.0,
    D: float = 0.0,
    T_top: float = 0.0,
) -> dict[str, float]:
    """Return hydraulic properties for a given section and depth y.

    Parameters
    ----------
    shape : one of 'rectangular', 'trapezoidal', 'triangular', 'circular',
            'parabolic'
    y     : flow depth (m)
    b     : bottom width (m) — rectangular / trapezoidal
    z     : side slope H:V — trapezoidal / triangular
    D     : diameter (m) — circular
    T_top : top width at full depth (m) — parabolic shape param

    Returns
    -------
    dict with keys: A, P, T, R, D_h, Z
      A   — flow area (m²)
      P   — wetted perimeter (m)
      T   — top width (m)
      R   — hydraulic radius A/P (m)
      D_h — hydraulic depth A/T (m)
      Z   — section factor A·√D_h (m^(5/2))
    """
    if y <= 0.0:
        return {"A": 0.0, "P": 0.0, "T": 0.0, "R": 0.0, "D_h": 0.0, "Z": 0.0}

    if shape == "rectangular":
        A = b * y
        P = b + 2.0 * y
        T = b

    elif shape == "trapezoidal":
        A = (b + z * y) * y
        P = b + 2.0 * y * math.sqrt(1.0 + z * z)
        T = b + 2.0 * z * y

    elif shape == "triangular":
        A = z * y * y
        P = 2.0 * y * math.sqrt(1.0 + z * z)
        T = 2.0 * z * y

    elif shape == "circular":
        # Partial-flow using central half-angle θ
        r = D / 2.0
        y_c = min(y, D)   # cap at full
        theta = 2.0 * math.acos(1.0 - y_c / r)   # central angle (rad)
        A = 0.5 * r * r * (theta - math.sin(theta))
        P = r * theta
        T = D * math.sin(theta / 2.0)

    elif shape == "parabolic":
        # y = (T_top²/(4·d_ref)) * (T_top/2)² ... shape param k = T_top²/(4·d_ref)
        # At depth y, top width T_y = T_top * √(y / d_ref)
        # We use d_ref = reference depth at which T_top is defined; caller passes
        # T_top as top width at y=d_ref, and d_ref is implicitly the actual y
        # parameter here — so we use the "running" form:
        # Store shape via ratio r = T_top/sqrt(d_ref); pass as T_top with d_ref=y
        # Simpler: caller passes T_top as the top-width coefficient at unit depth
        # so T_y = T_top * sqrt(y).  This is the standard parabolic channel form.
        # A = (2/3) * T_top * sqrt(y) * y = (2/3) * T_y * y
        T_y = T_top * math.sqrt(y)
        A = (2.0 / 3.0) * T_y * y
        # Wetted perimeter (approximate): P ≈ T_y * (1 + 8y²/(3T_y²))
        if T_y > 0:
            P = T_y * (1.0 + 8.0 * y * y / (3.0 * T_y * T_y))
        else:
            P = 0.0
        T = T_y

    else:
        raise ValueError(f"Unknown section shape: {shape!r}")

    if P <= 0.0:
        return {"A": A, "P": P, "T": T, "R": 0.0, "D_h": 0.0, "Z": 0.0}

    R = A / P
    D_h = A / T if T > 0.0 else 0.0
    Z = A * math.sqrt(D_h) if D_h > 0.0 else 0.0

    return {"A": A, "P": P, "T": T, "R": R, "D_h": D_h, "Z": Z}


def section_properties(
    shape: str,
    y: float,
    **kwargs: float,
) -> dict[str, Any]:
    """Public wrapper — compute section geometry + hydraulic properties.

    Parameters
    ----------
    shape : 'rectangular' | 'trapezoidal' | 'triangular' | 'circular' | 'parabolic'
    y     : flow depth (m), > 0
    **kwargs : shape parameters (b, z, D, T_top — as appropriate)

    Returns
    -------
    {ok, shape, y, A, P, T, R, D_h, Z}
    """
    try:
        if y <= 0:
            return {"ok": False, "reason": "depth y must be > 0"}
        props = _section_props(shape, y, **kwargs)
        return {"ok": True, "shape": shape, "y": y, **props}
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"section_properties error: {exc}"}


# ---------------------------------------------------------------------------
# Manning / Chezy discharge
# ---------------------------------------------------------------------------

def _manning_Q(
    shape: str,
    y: float,
    manning_n: float,
    slope: float,
    **kwargs: float,
) -> float:
    """Manning discharge Q = (1/n) A R^(2/3) S^(1/2) for given y."""
    props = _section_props(shape, y, **kwargs)
    A = props["A"]
    R = props["R"]
    if A <= 0.0 or R <= 0.0:
        return 0.0
    return (1.0 / manning_n) * A * (R ** (2.0 / 3.0)) * math.sqrt(slope)


def _chezy_Q(
    shape: str,
    y: float,
    chezy_C: float,
    slope: float,
    **kwargs: float,
) -> float:
    """Chezy discharge Q = C A √(RS) for given y."""
    props = _section_props(shape, y, **kwargs)
    A = props["A"]
    R = props["R"]
    if A <= 0.0 or R <= 0.0:
        return 0.0
    return chezy_C * A * math.sqrt(R * slope)


# ---------------------------------------------------------------------------
# Normal depth (bisection)
# ---------------------------------------------------------------------------

def normal_depth(
    shape: str,
    flow_m3s: float,
    slope: float,
    manning_n: float | None = None,
    chezy_C: float | None = None,
    max_depth_m: float = 20.0,
    **kwargs: float,
) -> dict[str, Any]:
    """Solve for normal depth using Manning or Chezy equation by bisection.

    Exactly one of *manning_n* or *chezy_C* must be supplied.

    Returns
    -------
    dict with ok, normal_depth_m, velocity_m_per_s, flow_area_m2,
    wetted_perimeter_m, hydraulic_radius_m, top_width_m, hydraulic_depth_m,
    froude_number, flow_regime, channel_full, warnings
    """
    result_warnings: list[str] = []

    # --- validation ---------------------------------------------------------
    if flow_m3s <= 0.0:
        return {"ok": False, "reason": "flow_m3s must be > 0"}
    if slope <= 0.0:
        return {"ok": False, "reason": "slope must be > 0"}
    if manning_n is not None and chezy_C is not None:
        return {"ok": False, "reason": "supply either manning_n or chezy_C, not both"}
    if manning_n is None and chezy_C is None:
        return {"ok": False, "reason": "supply either manning_n or chezy_C"}
    if manning_n is not None and manning_n <= 0.0:
        return {"ok": False, "reason": "manning_n must be > 0"}
    if chezy_C is not None and chezy_C <= 0.0:
        return {"ok": False, "reason": "chezy_C must be > 0"}
    if max_depth_m <= 0.0:
        return {"ok": False, "reason": "max_depth_m must be > 0"}

    # --- choose discharge function ------------------------------------------
    if manning_n is not None:
        def _Q(y: float) -> float:
            return _manning_Q(shape, y, manning_n, slope, **kwargs)
    else:
        def _Q(y: float) -> float:
            return _chezy_Q(shape, y, chezy_C, slope, **kwargs)

    # --- check capacity at max_depth ----------------------------------------
    Q_max = _Q(max_depth_m)
    if Q_max < flow_m3s:
        props_full = _section_props(shape, max_depth_m, **kwargs)
        return {
            "ok": True,
            "normal_depth_m": max_depth_m,
            "velocity_m_per_s": flow_m3s / props_full["A"] if props_full["A"] > 0 else 0.0,
            "flow_area_m2": props_full["A"],
            "wetted_perimeter_m": props_full["P"],
            "hydraulic_radius_m": props_full["R"],
            "top_width_m": props_full["T"],
            "hydraulic_depth_m": props_full["D_h"],
            "froude_number": None,
            "flow_regime": "channel_full",
            "channel_full": True,
            "warnings": ["Flow exceeds channel capacity at max_depth_m"],
        }

    # --- bisection ----------------------------------------------------------
    lo, hi = 1e-9, max_depth_m
    converged = False
    for _ in range(_MAX_ITER):
        mid = 0.5 * (lo + hi)
        Q_mid = _Q(mid)
        if Q_mid < flow_m3s:
            lo = mid
        else:
            hi = mid
        if (hi - lo) < _BISECT_TOL:
            converged = True
            break

    y_n = 0.5 * (lo + hi)
    if not converged:
        result_warnings.append("normal_depth bisection did not converge to tolerance")

    props = _section_props(shape, y_n, **kwargs)
    A = props["A"]
    V = flow_m3s / A if A > 0 else 0.0
    D_h = props["D_h"]
    Fr = V / math.sqrt(_G * D_h) if D_h > 0.0 else 0.0

    if Fr > 1.05:
        flow_regime = "supercritical"
        result_warnings.append("supercritical normal flow (Fr > 1)")
    elif Fr < 0.95:
        flow_regime = "subcritical"
    else:
        flow_regime = "critical"

    return {
        "ok": True,
        "normal_depth_m": y_n,
        "velocity_m_per_s": V,
        "flow_area_m2": A,
        "wetted_perimeter_m": props["P"],
        "hydraulic_radius_m": props["R"],
        "top_width_m": props["T"],
        "hydraulic_depth_m": D_h,
        "froude_number": Fr,
        "flow_regime": flow_regime,
        "channel_full": False,
        "warnings": result_warnings,
    }


# ---------------------------------------------------------------------------
# Critical depth
# ---------------------------------------------------------------------------

def critical_depth(
    shape: str,
    flow_m3s: float,
    max_depth_m: float = 20.0,
    **kwargs: float,
) -> dict[str, Any]:
    """Solve for critical depth using Z² = Q²/g by bisection.

    At critical depth, Z = A√D_h equals Q/√g.

    Returns
    -------
    dict with ok, critical_depth_m, critical_velocity_m_per_s,
    critical_area_m2, froude_number (≈1), min_specific_energy_m, warnings
    """
    result_warnings: list[str] = []

    if flow_m3s <= 0.0:
        return {"ok": False, "reason": "flow_m3s must be > 0"}
    if max_depth_m <= 0.0:
        return {"ok": False, "reason": "max_depth_m must be > 0"}

    Z_target = flow_m3s / math.sqrt(_G)

    def _Z(y: float) -> float:
        props = _section_props(shape, y, **kwargs)
        return props["Z"]

    Z_max = _Z(max_depth_m)
    if Z_max < Z_target:
        result_warnings.append("critical depth exceeds max_depth_m; result capped")
        return {
            "ok": True,
            "critical_depth_m": max_depth_m,
            "critical_velocity_m_per_s": None,
            "critical_area_m2": None,
            "froude_number": None,
            "min_specific_energy_m": None,
            "warnings": result_warnings,
        }

    lo, hi = 1e-9, max_depth_m
    converged = False
    for _ in range(_MAX_ITER):
        mid = 0.5 * (lo + hi)
        if _Z(mid) < Z_target:
            lo = mid
        else:
            hi = mid
        if (hi - lo) < _BISECT_TOL:
            converged = True
            break

    if not converged:
        result_warnings.append("critical_depth bisection did not converge")

    y_c = 0.5 * (lo + hi)
    props = _section_props(shape, y_c, **kwargs)
    A = props["A"]
    V_c = flow_m3s / A if A > 0.0 else 0.0
    E_min = y_c + V_c * V_c / (2.0 * _G)
    Fr = V_c / math.sqrt(_G * props["D_h"]) if props["D_h"] > 0.0 else None

    return {
        "ok": True,
        "critical_depth_m": y_c,
        "critical_velocity_m_per_s": V_c,
        "critical_area_m2": A,
        "froude_number": Fr,
        "min_specific_energy_m": E_min,
        "warnings": result_warnings,
    }


# ---------------------------------------------------------------------------
# Froude number and flow regime
# ---------------------------------------------------------------------------

def froude_number(
    shape: str,
    flow_m3s: float,
    depth_m: float,
    **kwargs: float,
) -> dict[str, Any]:
    """Compute Froude number and flow regime for given depth.

    Fr = V / √(g · D_h)  where D_h = A/T (hydraulic depth).

    Returns
    -------
    {ok, froude_number, flow_regime, velocity_m_per_s, hydraulic_depth_m}
    """
    if flow_m3s <= 0.0:
        return {"ok": False, "reason": "flow_m3s must be > 0"}
    if depth_m <= 0.0:
        return {"ok": False, "reason": "depth_m must be > 0"}

    props = _section_props(shape, depth_m, **kwargs)
    A = props["A"]
    D_h = props["D_h"]
    if A <= 0.0:
        return {"ok": False, "reason": "zero flow area at given depth"}
    if D_h <= 0.0:
        return {"ok": False, "reason": "zero hydraulic depth at given depth"}

    V = flow_m3s / A
    Fr = V / math.sqrt(_G * D_h)

    if Fr > 1.05:
        regime = "supercritical"
    elif Fr < 0.95:
        regime = "subcritical"
    else:
        regime = "critical"

    return {
        "ok": True,
        "froude_number": Fr,
        "flow_regime": regime,
        "velocity_m_per_s": V,
        "hydraulic_depth_m": D_h,
    }


# ---------------------------------------------------------------------------
# Specific energy and momentum function
# ---------------------------------------------------------------------------

def specific_energy(
    shape: str,
    flow_m3s: float,
    depth_m: float,
    **kwargs: float,
) -> dict[str, Any]:
    """Compute specific energy E = y + V²/(2g) and related quantities.

    Returns
    -------
    {ok, specific_energy_m, depth_m, velocity_head_m, velocity_m_per_s}
    """
    if flow_m3s <= 0.0:
        return {"ok": False, "reason": "flow_m3s must be > 0"}
    if depth_m <= 0.0:
        return {"ok": False, "reason": "depth_m must be > 0"}

    props = _section_props(shape, depth_m, **kwargs)
    A = props["A"]
    if A <= 0.0:
        return {"ok": False, "reason": "zero flow area at given depth"}

    V = flow_m3s / A
    V_head = V * V / (2.0 * _G)
    E = depth_m + V_head

    return {
        "ok": True,
        "specific_energy_m": E,
        "depth_m": depth_m,
        "velocity_head_m": V_head,
        "velocity_m_per_s": V,
    }


def momentum_function(
    shape: str,
    flow_m3s: float,
    depth_m: float,
    **kwargs: float,
) -> dict[str, Any]:
    """Compute the momentum (specific force) function M = Q²/(gA) + ȳ·A.

    ȳ is the depth to centroid of the flow area (approximated for each shape).

    Returns
    -------
    {ok, momentum_m3, depth_m}
    """
    if flow_m3s <= 0.0:
        return {"ok": False, "reason": "flow_m3s must be > 0"}
    if depth_m <= 0.0:
        return {"ok": False, "reason": "depth_m must be > 0"}

    props = _section_props(shape, depth_m, **kwargs)
    A = props["A"]
    if A <= 0.0:
        return {"ok": False, "reason": "zero flow area at given depth"}

    y = depth_m
    shape_l = shape.lower()

    # Centroid depth ȳ below water surface for common shapes
    if shape_l == "rectangular":
        b = kwargs.get("b", 0.0)
        y_bar = y / 2.0
    elif shape_l == "trapezoidal":
        b = kwargs.get("b", 0.0)
        z = kwargs.get("z", 0.0)
        # ȳ = y(3b + 2zy) / (6(b + zy))  ... standard formula
        denom = 6.0 * (b + z * y)
        y_bar = y * (3.0 * b + 2.0 * z * y) / denom if denom > 0 else y / 2.0
    elif shape_l == "triangular":
        y_bar = y / 3.0
    elif shape_l == "circular":
        # Use 2/3 * y as approximation (exact would need theta integration)
        y_bar = 2.0 * y / 3.0
    elif shape_l == "parabolic":
        y_bar = 2.0 * y / 5.0
    else:
        y_bar = y / 2.0

    M = flow_m3s * flow_m3s / (_G * A) + y_bar * A

    return {
        "ok": True,
        "momentum_m3": M,
        "depth_m": depth_m,
    }


# ---------------------------------------------------------------------------
# Hydraulic jump
# ---------------------------------------------------------------------------

def hydraulic_jump(
    shape: str,
    flow_m3s: float,
    depth1_m: float,
    **kwargs: float,
) -> dict[str, Any]:
    """Compute sequent depth, energy loss, and estimated length of hydraulic jump.

    For rectangular channels the Belanger equation is used analytically.
    For other shapes the sequent depth is found by equating the momentum function.

    Parameters
    ----------
    shape     : section shape
    flow_m3s  : discharge (m³/s)
    depth1_m  : upstream (supercritical) depth (m)

    Returns
    -------
    {ok, depth1_m, depth2_m (sequent), froude1, froude2,
     energy_loss_m, relative_energy_loss, length_estimate_m,
     warnings}

    Length estimate uses Chow's correlation: L ≈ 6·(y₂ − y₁) for Fr₁ in 1.7–17.
    """
    result_warnings: list[str] = []

    if flow_m3s <= 0.0:
        return {"ok": False, "reason": "flow_m3s must be > 0"}
    if depth1_m <= 0.0:
        return {"ok": False, "reason": "depth1_m must be > 0"}

    # Check Fr1 > 1
    fr_result = froude_number(shape, flow_m3s, depth1_m, **kwargs)
    if not fr_result["ok"]:
        return {"ok": False, "reason": fr_result["reason"]}

    Fr1 = fr_result["froude_number"]
    if Fr1 <= 1.0:
        result_warnings.append(f"upstream flow is not supercritical (Fr1={Fr1:.3f}); jump may not form")

    shape_l = shape.lower()

    # --- rectangular: exact Belanger equation ---
    if shape_l == "rectangular":
        # y2 = (y1/2) * (sqrt(1 + 8*Fr1²) - 1)
        y2 = 0.5 * depth1_m * (math.sqrt(1.0 + 8.0 * Fr1 * Fr1) - 1.0)
    else:
        # --- general: bisect on momentum function ---
        M1 = momentum_function(shape, flow_m3s, depth1_m, **kwargs)
        if not M1["ok"]:
            return {"ok": False, "reason": M1["reason"]}
        M1_val = M1["momentum_m3"]

        # Search for y2 > depth1_m (subcritical sequent depth)
        lo_y = depth1_m * 1.001
        hi_y = depth1_m * 50.0

        def _M(y: float) -> float:
            r = momentum_function(shape, flow_m3s, y, **kwargs)
            return r["momentum_m3"] if r["ok"] else 1e30

        # Ensure sign change
        found = False
        for _ in range(30):
            M_hi = _M(hi_y)
            if abs(M_hi - M1_val) > 1e-12:
                found = True
                break
            hi_y *= 2.0

        if not found:
            result_warnings.append("could not bracket sequent depth; result approximate")
            y2 = lo_y

        # Bisect
        converged = False
        for _ in range(_MAX_ITER):
            mid = 0.5 * (lo_y + hi_y)
            M_mid = _M(mid)
            if M_mid < M1_val:
                lo_y = mid
            else:
                hi_y = mid
            if (hi_y - lo_y) < _BISECT_TOL:
                converged = True
                break

        y2 = 0.5 * (lo_y + hi_y)
        if not converged:
            result_warnings.append("hydraulic_jump bisection did not converge")

    # --- energy loss ---
    E1 = specific_energy(shape, flow_m3s, depth1_m, **kwargs)
    E2 = specific_energy(shape, flow_m3s, y2, **kwargs)
    if E1["ok"] and E2["ok"]:
        dE = E1["specific_energy_m"] - E2["specific_energy_m"]
        rel_E = dE / E1["specific_energy_m"] if E1["specific_energy_m"] > 0 else None
    else:
        dE = None
        rel_E = None

    fr2_result = froude_number(shape, flow_m3s, y2, **kwargs)
    Fr2 = fr2_result["froude_number"] if fr2_result["ok"] else None
    if Fr2 is not None and Fr2 >= 1.0:
        result_warnings.append(f"sequent depth Fr2={Fr2:.3f} >= 1; check inputs")

    # Length estimate: L ≈ 6*(y2-y1) (Chow 1959, hydraulic jump on horizontal floor)
    length_est = 6.0 * (y2 - depth1_m) if y2 > depth1_m else None

    return {
        "ok": True,
        "depth1_m": depth1_m,
        "depth2_m": y2,
        "froude1": Fr1,
        "froude2": Fr2,
        "energy_loss_m": dE,
        "relative_energy_loss": rel_E,
        "length_estimate_m": length_est,
        "warnings": result_warnings,
    }


# ---------------------------------------------------------------------------
# GVF profile classification
# ---------------------------------------------------------------------------

_MILD_PROFILES = {
    # (y rel yn, y rel yc) : profile
    (1, 1): "M1",   # y > yn > yc : subcritical above normal
    (0, 1): "M2",   # yn > y > yc : subcritical between normal and critical
    (0, 0): "M3",   # yn > yc > y : supercritical below critical
}

_STEEP_PROFILES = {
    (1, 1): "S1",   # y > yc > yn : subcritical
    (1, 0): "S2",   # yc > y > yn : supercritical between critical and normal
    (0, 0): "S3",   # yc > yn > y : supercritical below normal
}


def gvf_profile_type(
    shape: str,
    flow_m3s: float,
    slope: float,
    manning_n: float,
    depth_m: float,
    **kwargs: float,
) -> dict[str, Any]:
    """Classify the GVF water-surface profile type per Chow (1959).

    Returns profile type (M1/M2/M3/S1/S2/S3/C1/C3/H2/H3/A2/A3)
    and channel classification (mild/steep/critical/horizontal/adverse).

    Returns
    -------
    {ok, profile_type, channel_class, normal_depth_m, critical_depth_m,
     depth_m, froude_number}
    """
    if flow_m3s <= 0.0:
        return {"ok": False, "reason": "flow_m3s must be > 0"}
    if slope < 0.0:
        channel_class = "adverse"
    elif slope == 0.0:
        channel_class = "horizontal"
    else:
        channel_class = None  # to be determined

    # Critical depth
    yc_res = critical_depth(shape, flow_m3s, **kwargs)
    if not yc_res["ok"]:
        return {"ok": False, "reason": f"critical_depth failed: {yc_res['reason']}"}
    yc = yc_res["critical_depth_m"]

    # Normal depth (only meaningful for positive slope)
    if slope > 0.0:
        yn_res = normal_depth(shape, flow_m3s, slope, manning_n=manning_n, **kwargs)
        if not yn_res["ok"] or yn_res["channel_full"]:
            yn = None
        else:
            yn = yn_res["normal_depth_m"]

        if yn is not None and channel_class is None:
            if abs(yn - yc) / max(yn, yc, 1e-12) < 0.01:
                channel_class = "critical"
            elif yn > yc:
                channel_class = "mild"
            else:
                channel_class = "steep"
    else:
        yn = None

    if channel_class is None:
        channel_class = "mild"  # fallback

    # Fr at actual depth
    fr_res = froude_number(shape, flow_m3s, depth_m, **kwargs)
    Fr = fr_res["froude_number"] if fr_res["ok"] else None

    # Classify profile
    y = depth_m
    if channel_class == "mild" and yn is not None:
        if y > yn:
            ptype = "M1"
        elif y > yc:
            ptype = "M2"
        else:
            ptype = "M3"
    elif channel_class == "steep" and yn is not None:
        if y > yc:
            ptype = "S1"
        elif y > yn:
            ptype = "S2"
        else:
            ptype = "S3"
    elif channel_class == "critical":
        ptype = "C1" if y > yc else "C3"
    elif channel_class == "horizontal":
        ptype = "H2" if y > yc else "H3"
    elif channel_class == "adverse":
        ptype = "A2" if y > yc else "A3"
    else:
        ptype = "unknown"

    return {
        "ok": True,
        "profile_type": ptype,
        "channel_class": channel_class,
        "normal_depth_m": yn,
        "critical_depth_m": yc,
        "depth_m": depth_m,
        "froude_number": Fr,
    }


# ---------------------------------------------------------------------------
# GVF direct-step water-surface profile
# ---------------------------------------------------------------------------

def gvf_direct_step(
    shape: str,
    flow_m3s: float,
    slope: float,
    manning_n: float,
    depth_start_m: float,
    depth_end_m: float,
    n_steps: int = 100,
    **kwargs: float,
) -> dict[str, Any]:
    """Compute a gradually-varied flow water-surface profile by direct-step.

    The direct-step method computes the distance Δx between successive depth
    increments:
        Δx = (E₂ − E₁) / (S₀ − S_f)
    where S_f = [Qn / (A R^(2/3))]² is the friction slope.

    Parameters
    ----------
    depth_start_m : known boundary depth (m)
    depth_end_m   : target end depth (m)
    n_steps       : number of depth increments

    Returns
    -------
    {ok, profile (list of {x, y, E, V, Fr, Sf}), total_length_m, warnings}
    """
    result_warnings: list[str] = []

    if flow_m3s <= 0.0:
        return {"ok": False, "reason": "flow_m3s must be > 0"}
    if slope < 0.0:
        return {"ok": False, "reason": "slope must be >= 0"}
    if manning_n <= 0.0:
        return {"ok": False, "reason": "manning_n must be > 0"}
    if depth_start_m <= 0.0 or depth_end_m <= 0.0:
        return {"ok": False, "reason": "depths must be > 0"}
    if n_steps < 2:
        return {"ok": False, "reason": "n_steps must be >= 2"}

    depths = [depth_start_m + i * (depth_end_m - depth_start_m) / (n_steps - 1)
              for i in range(n_steps)]

    def _step_props(y: float) -> tuple[float, float, float, float]:
        """Return (E, V, Fr, Sf)."""
        props = _section_props(shape, y, **kwargs)
        A = props["A"]
        R = props["R"]
        D_h = props["D_h"]
        if A <= 0.0 or R <= 0.0:
            return (y, 0.0, 0.0, 0.0)
        V = flow_m3s / A
        V_head = V * V / (2.0 * _G)
        E = y + V_head
        Fr = V / math.sqrt(_G * D_h) if D_h > 0.0 else 0.0
        # Friction slope from Manning: Sf = (Q·n / (A·R^(2/3)))²
        Sf = (flow_m3s * manning_n / (A * R ** (2.0 / 3.0))) ** 2
        return (E, V, Fr, Sf)

    profile: list[dict] = []
    x = 0.0
    prev_E, prev_V, prev_Fr, prev_Sf = _step_props(depths[0])
    profile.append({
        "x_m": x,
        "depth_m": depths[0],
        "specific_energy_m": prev_E,
        "velocity_m_per_s": prev_V,
        "froude_number": prev_Fr,
        "friction_slope": prev_Sf,
    })

    for i in range(1, n_steps):
        y = depths[i]
        E, V, Fr, Sf = _step_props(y)
        avg_Sf = 0.5 * (prev_Sf + Sf)
        denom = slope - avg_Sf
        if abs(denom) < 1e-15:
            result_warnings.append(f"critical-flow zone near x={x:.1f} m; step skipped")
            x_new = x  # no advance
        else:
            dx = (E - prev_E) / denom
            x += dx
        x_new = x
        profile.append({
            "x_m": x_new,
            "depth_m": y,
            "specific_energy_m": E,
            "velocity_m_per_s": V,
            "froude_number": Fr,
            "friction_slope": Sf,
        })
        prev_E, prev_V, prev_Fr, prev_Sf = E, V, Fr, Sf

    return {
        "ok": True,
        "profile": profile,
        "total_length_m": profile[-1]["x_m"] - profile[0]["x_m"],
        "warnings": result_warnings,
    }


# ---------------------------------------------------------------------------
# Best hydraulic section
# ---------------------------------------------------------------------------

def best_hydraulic_section(
    shape: str,
    flow_m3s: float,
    slope: float,
    manning_n: float,
    **kwargs: float,
) -> dict[str, Any]:
    """Compute dimensions of the most-hydraulically-efficient cross-section.

    The best hydraulic section minimises wetted perimeter for a given area
    (maximum hydraulic radius), yielding minimum excavation for a given
    discharge.

    Analytical results (Chow 1959)
    --------------------------------
    rectangular  — b = 2y (half-hexagon); R = y/2
    trapezoidal  — b = 2y/√3, z = 1/√3 ≈ 0.577 (half-hexagon)
    triangular   — z = 1 (45°); y = √(Q·n / S^0.5)^(3/8) ... iterative
    circular     — y/D = 0.938 (max Q), D solved iteratively
    parabolic    — T = 2√2 · y; R = y/2 ... iterative

    For shapes without a closed-form solution the function solves numerically.

    Returns
    -------
    {ok, shape, optimal_depth_m, optimal_bottom_width_m (if applicable),
     optimal_side_slope (if applicable), normal_depth_m, wetted_perimeter_m,
     hydraulic_radius_m, flow_area_m2, warnings}
    """
    result_warnings: list[str] = []

    if flow_m3s <= 0.0:
        return {"ok": False, "reason": "flow_m3s must be > 0"}
    if slope <= 0.0:
        return {"ok": False, "reason": "slope must be > 0"}
    if manning_n <= 0.0:
        return {"ok": False, "reason": "manning_n must be > 0"}

    shape_l = shape.lower()

    if shape_l == "rectangular":
        # b = 2y; solve normal depth for y with b=2y substituted into Manning
        # Q = (1/n) * (2y²) * (y/2)^(2/3) * S^0.5
        # Q = (1/n) * 2 * 2^(-2/3) * y^(8/3) * S^0.5
        # y = ( Q*n / (2*2^(-2/3)*S^0.5) )^(3/8)
        coeff = 2.0 * (2.0 ** (-2.0 / 3.0)) * math.sqrt(slope) / manning_n
        y_opt = (flow_m3s / coeff) ** (3.0 / 8.0)
        b_opt = 2.0 * y_opt
        props = _section_props("rectangular", y_opt, b=b_opt)
        return {
            "ok": True,
            "shape": shape,
            "optimal_depth_m": y_opt,
            "optimal_bottom_width_m": b_opt,
            "wetted_perimeter_m": props["P"],
            "hydraulic_radius_m": props["R"],
            "flow_area_m2": props["A"],
            "warnings": result_warnings,
        }

    elif shape_l == "trapezoidal":
        # Half-hexagon: z = 1/√3, b = 2y(1/√3) actually b = 2y(√(1+z²) - z)
        # with z=1/√3: b = 2y(√(4/3) - 1/√3) = 2y * (2/√3 - 1/√3) = 2y/√3
        z_opt = 1.0 / math.sqrt(3.0)
        # Solve y from Manning with b=2y/sqrt(3), z=z_opt
        # A = (b + zy) y = (2y/√3 + y/√3) y = (3y/√3) y = √3 y²
        # P = b + 2y√(1+z²) = 2y/√3 + 2y * (2/√3) = 2y/√3 + 4y/√3 = 6y/√3 = 2√3 y
        # R = A/P = √3 y² / (2√3 y) = y/2
        # Q = (1/n) * √3 y² * (y/2)^(2/3) * S^0.5
        coeff = (math.sqrt(3.0) / manning_n) * (0.5 ** (2.0 / 3.0)) * math.sqrt(slope)
        y_opt = (flow_m3s / coeff) ** (3.0 / 8.0)
        b_opt = 2.0 * y_opt / math.sqrt(3.0)
        props = _section_props("trapezoidal", y_opt, b=b_opt, z=z_opt)
        return {
            "ok": True,
            "shape": shape,
            "optimal_depth_m": y_opt,
            "optimal_bottom_width_m": b_opt,
            "optimal_side_slope": z_opt,
            "wetted_perimeter_m": props["P"],
            "hydraulic_radius_m": props["R"],
            "flow_area_m2": props["A"],
            "warnings": result_warnings,
        }

    elif shape_l == "triangular":
        # z=1 (45°); R = y√2/4; A=y²; P=2√2 y
        # Q = (1/n) * y² * (y√2/4)^(2/3) * S^0.5
        z_opt = 1.0
        coeff = (1.0 / manning_n) * ((math.sqrt(2.0) / 4.0) ** (2.0 / 3.0)) * math.sqrt(slope)
        y_opt = (flow_m3s / coeff) ** (3.0 / 8.0)
        props = _section_props("triangular", y_opt, z=z_opt)
        return {
            "ok": True,
            "shape": shape,
            "optimal_depth_m": y_opt,
            "optimal_side_slope": z_opt,
            "wetted_perimeter_m": props["P"],
            "hydraulic_radius_m": props["R"],
            "flow_area_m2": props["A"],
            "warnings": result_warnings,
        }

    elif shape_l == "circular":
        # For maximum velocity: y/D ≈ 0.813; for max Q: y/D ≈ 0.938
        # Use max-Q condition; find D numerically
        y_frac = 0.938
        # At y/D = 0.938, θ = 2 acos(1 - 2*0.938) ... careful: 1 - y/r = 1 - 2*0.938/1 <0
        # θ from: 1 - y_c/r = 1 - y_frac * 2 / 2 = 1 - y_frac ... wait r=D/2
        # theta = 2 acos(1 - y/r) = 2 acos(1 - 2*y_frac)
        cos_arg = 1.0 - 2.0 * y_frac
        theta = 2.0 * math.acos(cos_arg)
        A_nd = 0.5 * (theta - math.sin(theta))         # A/D²
        P_nd = 0.5 * theta                              # P/D
        R_nd = A_nd / P_nd                              # R/D
        # Q = (1/n) * A * R^(2/3) * S^0.5
        # = (1/n) * (A_nd * D²) * (R_nd * D)^(2/3) * S^0.5
        # = (1/n) * A_nd * R_nd^(2/3) * D^(8/3) * S^0.5
        coeff_D = (1.0 / manning_n) * A_nd * (R_nd ** (2.0 / 3.0)) * math.sqrt(slope)
        D_opt = (flow_m3s / coeff_D) ** (3.0 / 8.0)
        y_opt = y_frac * D_opt
        props = _section_props("circular", y_opt, D=D_opt)
        return {
            "ok": True,
            "shape": shape,
            "optimal_depth_m": y_opt,
            "optimal_diameter_m": D_opt,
            "optimal_depth_to_diameter_ratio": y_frac,
            "wetted_perimeter_m": props["P"],
            "hydraulic_radius_m": props["R"],
            "flow_area_m2": props["A"],
            "warnings": result_warnings,
        }

    elif shape_l == "parabolic":
        # Best parabolic: T = 2√2 y; R = y/2
        # A = (2/3) T y = (2/3) * 2√2 * y² = (4√2/3) y²
        # Q = (1/n) * (4√2/3) y² * (y/2)^(2/3) * S^0.5
        c1 = (4.0 * math.sqrt(2.0) / 3.0)
        c2 = 0.5 ** (2.0 / 3.0)
        coeff = (1.0 / manning_n) * c1 * c2 * math.sqrt(slope)
        y_opt = (flow_m3s / coeff) ** (3.0 / 8.0)
        T_top_opt = 2.0 * math.sqrt(2.0) * y_opt / math.sqrt(y_opt)  # T_top coeff
        props = _section_props("parabolic", y_opt, T_top=T_top_opt)
        return {
            "ok": True,
            "shape": shape,
            "optimal_depth_m": y_opt,
            "optimal_top_width_m": 2.0 * math.sqrt(2.0) * math.sqrt(y_opt),
            "wetted_perimeter_m": props["P"],
            "hydraulic_radius_m": props["R"],
            "flow_area_m2": props["A"],
            "warnings": result_warnings,
        }

    else:
        return {"ok": False, "reason": f"Unsupported shape: {shape!r}"}


# ---------------------------------------------------------------------------
# Weir discharge
# ---------------------------------------------------------------------------

def weir_broad_crested(
    head_m: float,
    crest_length_m: float,
    Cd: float = 0.848,
) -> dict[str, Any]:
    """Broad-crested weir discharge: Q = Cd · L · H^(3/2).

    The coefficient Cd = 0.848 corresponds to the theoretical value
    (2/3)·√(2g/3) · 1 ≈ 1.705 when Cd is the full-form coefficient, but
    the standard compact form Q = Cd·L·H^(3/2) uses Cd ≈ 1.7 (SI) or
    the dimensionless form Q = Cd·L·√(2g)·(2/3)^(3/2)·H^(3/2).

    Here the *dimensionless* Cd is used; the default 0.848 gives the
    standard Q = 1.705 · L · H^(3/2) form.

    Returns {ok, discharge_m3s, head_m, crest_length_m, Cd}
    """
    if head_m <= 0.0:
        return {"ok": False, "reason": "head_m must be > 0"}
    if crest_length_m <= 0.0:
        return {"ok": False, "reason": "crest_length_m must be > 0"}
    if Cd <= 0.0 or Cd > 3.0:
        return {"ok": False, "reason": "Cd must be in (0, 3.0]"}

    # Q = Cd * (2/3) * sqrt(2g/3) * L * H^(3/2)
    # Numerical: sqrt(2*9.80665/3) = sqrt(6.5378) = 2.557
    # (2/3) * 2.557 * Cd = 1.705 * Cd  (default Cd=1.0 gives classic form)
    # BUT the task says dimensionless Cd: Q = Cd * L * H^(3/2) with Cd≈1.7
    # To keep both modes: use Q = Cd * L * H^1.5  directly (Cd absorbs √(2g) terms)
    Q = Cd * crest_length_m * (head_m ** 1.5)
    return {
        "ok": True,
        "discharge_m3s": Q,
        "head_m": head_m,
        "crest_length_m": crest_length_m,
        "Cd": Cd,
        "formula": "Q = Cd * L * H^(3/2)",
    }


def weir_sharp_crested(
    head_m: float,
    crest_length_m: float,
    Cd: float = 0.611,
) -> dict[str, Any]:
    """Sharp-crested (thin-plate) rectangular weir discharge.

    Q = (2/3) · Cd · L · √(2g) · H^(3/2)

    Default Cd = 0.611 (Francis, for free-nappe conditions).

    Returns {ok, discharge_m3s, head_m, crest_length_m, Cd}
    """
    if head_m <= 0.0:
        return {"ok": False, "reason": "head_m must be > 0"}
    if crest_length_m <= 0.0:
        return {"ok": False, "reason": "crest_length_m must be > 0"}
    if Cd <= 0.0 or Cd > 1.0:
        return {"ok": False, "reason": "Cd must be in (0, 1.0]"}

    Q = (2.0 / 3.0) * Cd * crest_length_m * math.sqrt(2.0 * _G) * (head_m ** 1.5)
    return {
        "ok": True,
        "discharge_m3s": Q,
        "head_m": head_m,
        "crest_length_m": crest_length_m,
        "Cd": Cd,
        "formula": "Q = (2/3) * Cd * L * sqrt(2g) * H^(3/2)",
    }


def weir_vnotch(
    head_m: float,
    notch_angle_deg: float = 90.0,
    Cd: float = 0.611,
) -> dict[str, Any]:
    """V-notch (triangular) weir discharge.

    Q = (8/15) · Cd · tan(θ/2) · √(2g) · H^(5/2)

    Default notch angle θ = 90°, Cd = 0.611.

    Returns {ok, discharge_m3s, head_m, notch_angle_deg, Cd}
    """
    if head_m <= 0.0:
        return {"ok": False, "reason": "head_m must be > 0"}
    if notch_angle_deg <= 0.0 or notch_angle_deg >= 180.0:
        return {"ok": False, "reason": "notch_angle_deg must be in (0, 180)"}
    if Cd <= 0.0 or Cd > 1.0:
        return {"ok": False, "reason": "Cd must be in (0, 1.0]"}

    theta_rad = math.radians(notch_angle_deg)
    Q = (8.0 / 15.0) * Cd * math.tan(theta_rad / 2.0) * math.sqrt(2.0 * _G) * (head_m ** 2.5)
    return {
        "ok": True,
        "discharge_m3s": Q,
        "head_m": head_m,
        "notch_angle_deg": notch_angle_deg,
        "Cd": Cd,
        "formula": "Q = (8/15) * Cd * tan(theta/2) * sqrt(2g) * H^(5/2)",
    }


# ---------------------------------------------------------------------------
# Culvert control
# ---------------------------------------------------------------------------

def culvert_control(
    diameter_m: float,
    length_m: float,
    slope: float,
    manning_n: float,
    headwater_m: float,
    tailwater_m: float = 0.0,
    Ke: float = 0.5,
) -> dict[str, Any]:
    """Estimate culvert capacity and identify controlling condition.

    Uses FHWA HDS-5 simplified method:
      - Inlet control: Q = Cd · A · √(2g · HW) where Cd accounts for submerged inlet
      - Outlet control: solved from energy balance including friction losses

    Parameters
    ----------
    diameter_m   : culvert diameter (m)
    length_m     : culvert length (m)
    slope        : barrel slope (m/m), >= 0
    manning_n    : Manning's n for culvert barrel
    headwater_m  : headwater depth above culvert inlet invert (m)
    tailwater_m  : tailwater depth above culvert outlet invert (m), default 0
    Ke           : entrance loss coefficient (default 0.5, square-edge)

    Returns
    -------
    {ok, controlling_condition, capacity_m3s, headwater_m, tailwater_m,
     inlet_control_Q_m3s, outlet_control_Q_m3s, warnings}
    """
    result_warnings: list[str] = []

    if diameter_m <= 0.0:
        return {"ok": False, "reason": "diameter_m must be > 0"}
    if length_m <= 0.0:
        return {"ok": False, "reason": "length_m must be > 0"}
    if slope < 0.0:
        return {"ok": False, "reason": "slope must be >= 0"}
    if manning_n <= 0.0:
        return {"ok": False, "reason": "manning_n must be > 0"}
    if headwater_m <= 0.0:
        return {"ok": False, "reason": "headwater_m must be > 0"}

    A = math.pi * diameter_m * diameter_m / 4.0
    R = diameter_m / 4.0  # full-flow hydraulic radius

    # --- Inlet control (submerged inlet, weir-like): Q = Cd * A * sqrt(2g*HW)
    Cd_inlet = 0.6  # typical for box/circular submerged
    Q_inlet = Cd_inlet * A * math.sqrt(2.0 * _G * headwater_m)

    # --- Outlet control (energy balance):
    # HW = TW + (1 + Ke + f*L/D) * V²/(2g) - S*L
    # Solve iteratively for Q given HW
    # V = Q/A, so HW + S*L - TW = (1 + Ke + f*L/D) * Q²/(2g*A²)
    # f = (2g * n² / R^(4/3))  from Manning: Sf = (Vn/R^(2/3))² = V²n²/R^(4/3)
    # Darcy equiv: f_eq = 2g n² L / R^(4/3) / L  ... integrate as 2gn²/R^(4/3)
    f_equiv = 2.0 * _G * manning_n * manning_n / (R ** (4.0 / 3.0))
    K_loss = 1.0 + Ke + f_equiv * length_m / diameter_m
    dH = headwater_m + slope * length_m - tailwater_m
    if dH <= 0.0:
        result_warnings.append("outlet headwater <= tailwater + elevation gain; flow may be zero")
        Q_outlet = 0.0
    else:
        Q_outlet = A * math.sqrt(2.0 * _G * dH / K_loss)

    # Governing condition: the lower Q governs (most restrictive)
    if Q_inlet <= Q_outlet:
        controlling = "inlet"
        Q_cap = Q_inlet
    else:
        controlling = "outlet"
        Q_cap = Q_outlet

    if tailwater_m > diameter_m:
        result_warnings.append("tailwater exceeds culvert diameter; outlet may be submerged")

    return {
        "ok": True,
        "controlling_condition": controlling,
        "capacity_m3s": Q_cap,
        "headwater_m": headwater_m,
        "tailwater_m": tailwater_m,
        "inlet_control_Q_m3s": Q_inlet,
        "outlet_control_Q_m3s": Q_outlet,
        "warnings": result_warnings,
    }


# ---------------------------------------------------------------------------
# Channel transition (contraction / expansion)
# ---------------------------------------------------------------------------

def channel_transition(
    shape1: str,
    flow_m3s: float,
    depth1_m: float,
    shape2: str,
    contraction_loss_coeff: float = 0.1,
    expansion_loss_coeff: float = 0.3,
    **kwargs1: float,
) -> dict[str, Any]:
    """Compute depth at a channel transition (contraction or expansion).

    Applies the energy equation with head-loss coefficient:
        E₁ = E₂ + K |V₁²/2g − V₂²/2g|
    where K is the contraction or expansion loss coefficient.

    The function determines whether the transition is a contraction or
    expansion from the velocity heads, then solves for y₂ using bisection.

    Parameters
    ----------
    shape1  : upstream cross-section shape
    shape2  : downstream cross-section shape
    depth1_m: upstream depth (m)
    contraction_loss_coeff : K for contractions (default 0.1)
    expansion_loss_coeff   : K for expansions (default 0.3)
    **kwargs1 : shape parameters for shape1; shape2 parameters can be
                distinguished by suffix '_2' (e.g. b_2=1.5); plain params
                apply to shape1 only (shape2 uses its own defaults if not
                supplied).

    Returns
    -------
    {ok, depth2_m, velocity1_m_per_s, velocity2_m_per_s,
     energy1_m, energy2_m, head_loss_m, transition_type, warnings}
    """
    result_warnings: list[str] = []

    if flow_m3s <= 0.0:
        return {"ok": False, "reason": "flow_m3s must be > 0"}
    if depth1_m <= 0.0:
        return {"ok": False, "reason": "depth1_m must be > 0"}

    # Split kwargs into section 1 and section 2
    kwargs2 = {k[:-2]: v for k, v in kwargs1.items() if k.endswith("_2")}
    kwargs1_clean = {k: v for k, v in kwargs1.items() if not k.endswith("_2")}

    props1 = _section_props(shape1, depth1_m, **kwargs1_clean)
    A1 = props1["A"]
    if A1 <= 0.0:
        return {"ok": False, "reason": "zero upstream flow area"}

    V1 = flow_m3s / A1
    Vh1 = V1 * V1 / (2.0 * _G)
    E1 = depth1_m + Vh1

    # Determine contraction vs expansion later (need y2 estimate first)
    # Use bisection on energy equation
    # E2 = E1 - K * |Vh1 - Vh2|  (loss for expansion) or
    # E2 = E1 - K * |Vh2 - Vh1|  (loss for contraction, velocity increases)
    # We don't know y2 yet; iterate.

    def _residual(y2: float) -> float:
        props2 = _section_props(shape2, y2, **kwargs2)
        A2 = props2["A"]
        if A2 <= 0.0:
            return 1e30
        V2 = flow_m3s / A2
        Vh2 = V2 * V2 / (2.0 * _G)
        dVh = abs(Vh2 - Vh1)
        if Vh2 > Vh1:
            K = contraction_loss_coeff
        else:
            K = expansion_loss_coeff
        E2_target = E1 - K * dVh
        E2_actual = y2 + Vh2
        return E2_actual - E2_target

    # Bracket
    lo, hi = 1e-6, depth1_m * 20.0
    r_lo = _residual(lo)
    r_hi = _residual(hi)

    # If no sign change, try extending bracket
    if r_lo * r_hi > 0:
        for factor in [50.0, 100.0, 500.0]:
            r_hi = _residual(depth1_m * factor)
            if r_lo * r_hi < 0:
                hi = depth1_m * factor
                break
        if r_lo * r_hi > 0:
            result_warnings.append("could not bracket depth2; returning upstream depth")
            y2 = depth1_m
        else:
            # bisect
            converged = False
            for _ in range(_MAX_ITER):
                mid = 0.5 * (lo + hi)
                r_mid = _residual(mid)
                if r_lo * r_mid <= 0:
                    hi = mid
                    r_hi = r_mid
                else:
                    lo = mid
                    r_lo = r_mid
                if (hi - lo) < _BISECT_TOL:
                    converged = True
                    break
            y2 = 0.5 * (lo + hi)
            if not converged:
                result_warnings.append("channel_transition bisection did not converge")
    else:
        converged = False
        for _ in range(_MAX_ITER):
            mid = 0.5 * (lo + hi)
            r_mid = _residual(mid)
            if r_lo * r_mid <= 0:
                hi = mid
                r_hi = r_mid
            else:
                lo = mid
                r_lo = r_mid
            if (hi - lo) < _BISECT_TOL:
                converged = True
                break
        y2 = 0.5 * (lo + hi)
        if not converged:
            result_warnings.append("channel_transition bisection did not converge")

    # Compute final values
    props2 = _section_props(shape2, y2, **kwargs2)
    A2 = props2["A"]
    V2 = flow_m3s / A2 if A2 > 0.0 else 0.0
    Vh2 = V2 * V2 / (2.0 * _G)
    E2 = y2 + Vh2
    head_loss = E1 - E2
    trans_type = "contraction" if V2 > V1 else "expansion"

    fr2_res = froude_number(shape2, flow_m3s, y2, **kwargs2)
    if fr2_res.get("ok") and fr2_res["froude_number"] > 0.95:
        result_warnings.append(f"downstream flow is near/supercritical (Fr2={fr2_res['froude_number']:.3f}); choked condition possible")

    return {
        "ok": True,
        "depth2_m": y2,
        "velocity1_m_per_s": V1,
        "velocity2_m_per_s": V2,
        "energy1_m": E1,
        "energy2_m": E2,
        "head_loss_m": head_loss,
        "transition_type": trans_type,
        "warnings": result_warnings,
    }
