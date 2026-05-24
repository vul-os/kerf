"""
kerf_cad_core.elecpower.protection — IEEE C37.112-2018 inverse time-overcurrent curves.

Implements the five standard IEC/IEEE inverse-time overcurrent relay curves
(IEEE C37.112-2018 / IEC 60255-151) and a protection coordination helper.

Curve designations (IEEE C37.112-2018 Table 1)
----------------------------------------------
  U1 — Moderately Inverse (Standard Inverse)
  U2 — Very Inverse
  U3 — Extremely Inverse
  U4 — Long-Time Inverse
  U5 — Short-Time Inverse

Trip time formula
-----------------
  t = TD × [ A / (M^P - 1) + B ]

where  M = I / I_pickup  (must be > 1.0)
       A, B, P  are curve-specific constants (IEEE C37.112-2018 Table 1).

Functions
---------
  relay_trip_time(I, Ipickup, TD, curve)
      Return trip time (seconds) for a given current and time dial.

  coordinate(upstream, downstream, fault_currents)
      Check coordination between upstream and downstream relays across a list
      of fault currents. CTI = t_upstream - t_downstream must be ≥ cti_min
      at every fault current level.

All functions return plain dicts; never raise.

References
----------
  IEEE Std C37.112-2018 — IEEE Standard Inverse-Time Characteristics Equations
    for Overcurrent Relays.
  IEC 60255-151:2009 — Measuring relays and protection equipment.
  Blackburn & Domin, "Protective Relaying Principles and Applications", 4th ed.

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# IEEE C37.112-2018 Table 1 constants
# Each entry: (A, B, P)
# ---------------------------------------------------------------------------
_CURVE_PARAMS: dict[str, tuple[float, float, float]] = {
    # designation : (A,        B,       P)
    "U1": (0.0515,   0.1140,  0.02),   # Moderately Inverse (Standard Inverse)
    "U2": (19.61,    0.4910,  2.00),   # Very Inverse
    "U3": (28.2,     0.1217,  2.00),   # Extremely Inverse
    "U4": (5.6143,   2.1800,  1.00),   # Long-Time Inverse
    "U5": (0.1140,   0.0000,  0.02),   # Short-Time Inverse
}

_CURVE_ALIASES: dict[str, str] = {
    "standard_inverse":  "U1",
    "moderately_inverse": "U1",
    "very_inverse":      "U2",
    "extremely_inverse": "U3",
    "long_time_inverse": "U4",
    "short_time_inverse": "U5",
}

# Default minimum coordination time interval (seconds)
_CTI_DEFAULT = 0.3


def _resolve_curve(curve: str) -> str | None:
    key = curve.strip().upper()
    if key in _CURVE_PARAMS:
        return key
    alias = _CURVE_ALIASES.get(curve.strip().lower())
    return alias


def relay_trip_time(
    I: float,
    Ipickup: float,
    TD: float,
    curve: str = "U1",
) -> dict[str, Any]:
    """
    Calculate relay trip time per IEEE C37.112-2018.

    Parameters
    ----------
    I       : float  Fault current (A). Must be > Ipickup.
    Ipickup : float  Relay pickup current (A). Must be > 0.
    TD      : float  Time dial setting (0.5–10 typical; positive float).
    curve   : str    Curve code: "U1","U2","U3","U4","U5" or long names.

    Returns
    -------
    dict with trip_time_s, M (per-unit multiple), curve, TD.
    Returns {ok:False, reason} for invalid inputs.
    """
    if Ipickup <= 0:
        return {"ok": False, "reason": "Ipickup must be > 0"}
    if I <= 0:
        return {"ok": False, "reason": "I must be > 0"}
    if TD <= 0:
        return {"ok": False, "reason": "TD must be > 0"}

    code = _resolve_curve(curve)
    if code is None:
        return {
            "ok": False,
            "reason": f"Unknown curve '{curve}'. Valid: U1,U2,U3,U4,U5 or long names.",
        }

    M = I / Ipickup
    if M <= 1.0:
        return {
            "ok": False,
            "reason": f"I/Ipickup = {M:.3f} ≤ 1.0; relay does not trip below pickup.",
        }

    A, B, P = _CURVE_PARAMS[code]
    try:
        t = TD * (A / (M**P - 1.0) + B)
    except (ZeroDivisionError, OverflowError) as exc:
        return {"ok": False, "reason": f"Math error in trip-time calculation: {exc}"}

    if t < 0:
        t = 0.0

    return {
        "ok": True,
        "trip_time_s": round(t, 4),
        "M": round(M, 4),
        "curve": code,
        "TD": TD,
        "Ipickup": Ipickup,
        "I": I,
    }


def coordinate(
    upstream: dict,
    downstream: dict,
    fault_currents: list[float],
    *,
    cti_min: float = _CTI_DEFAULT,
) -> dict[str, Any]:
    """
    Check protection coordination between upstream and downstream relays.

    Computes trip times at each fault current level and verifies
    CTI = t_upstream - t_downstream ≥ cti_min.

    Parameters
    ----------
    upstream   : dict  Relay config: {Ipickup, TD, curve}
    downstream : dict  Relay config: {Ipickup, TD, curve}
    fault_currents : list[float]  Fault current levels to check (A).
    cti_min    : float  Minimum coordination time interval (s), default 0.3.

    Returns
    -------
    dict with:
        coordinated : bool   — True if all CTI ≥ cti_min
        cti_min     : float  — required CTI
        results     : list   — per-fault-current {I, t_up, t_dn, CTI, ok}
        violations  : list   — fault currents where CTI < cti_min
        warnings    : list
    """
    if not fault_currents:
        return {"ok": False, "reason": "fault_currents list is empty"}

    results = []
    violations = []
    warnings: list[str] = []

    for I in fault_currents:
        t_up_res = relay_trip_time(
            I,
            upstream["Ipickup"],
            upstream["TD"],
            upstream.get("curve", "U1"),
        )
        t_dn_res = relay_trip_time(
            I,
            downstream["Ipickup"],
            downstream["TD"],
            downstream.get("curve", "U1"),
        )

        # If downstream doesn't pick up but upstream does — still coordination
        dn_no_trip = not t_dn_res.get("ok", False)
        up_no_trip = not t_up_res.get("ok", False)

        if up_no_trip and dn_no_trip:
            results.append({
                "I": I,
                "t_upstream_s": None,
                "t_downstream_s": None,
                "CTI_s": None,
                "ok": True,
                "note": "Neither relay picks up",
            })
            continue

        if dn_no_trip:
            results.append({
                "I": I,
                "t_upstream_s": t_up_res.get("trip_time_s"),
                "t_downstream_s": None,
                "CTI_s": None,
                "ok": True,
                "note": "Downstream does not pick up; upstream operates",
            })
            continue

        if up_no_trip:
            results.append({
                "I": I,
                "t_upstream_s": None,
                "t_downstream_s": t_dn_res.get("trip_time_s"),
                "CTI_s": None,
                "ok": False,
                "note": "Upstream does not pick up but downstream does — miscoordination",
            })
            violations.append(I)
            continue

        t_up = t_up_res["trip_time_s"]
        t_dn = t_dn_res["trip_time_s"]
        CTI = round(t_up - t_dn, 4)
        ok = CTI >= cti_min

        if not ok:
            violations.append(I)

        results.append({
            "I": I,
            "t_upstream_s": t_up,
            "t_downstream_s": t_dn,
            "CTI_s": CTI,
            "ok": ok,
        })

    coordinated = len(violations) == 0
    return {
        "ok": True,
        "coordinated": coordinated,
        "cti_min_s": cti_min,
        "results": results,
        "violations": violations,
        "warnings": warnings,
    }
