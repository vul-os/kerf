"""
kerf_civil.drainage — Rational Method drainage flow-rate calculations.

Implements the FHWA HEC-22 (3rd Edition, 2009) rational method for
stormwater peak runoff estimation.  All functions work in US customary
units (feet, acres, inches/hour, cubic feet per second) consistent with
HEC-22 §3, as is conventional for rational-method stormwater design.

Note: This module implements the rational method *as documented in* FHWA
HEC-22.  It is not reviewed, certified, or endorsed by FHWA.

References
----------
* FHWA (2009) "Urban Drainage Design Manual", Hydraulic Engineering
  Circular No. 22 (HEC-22), 3rd Edition. FHWA-NHI-10-009.
  §3.1  Rational Method
  §3.3  Composite Runoff Coefficient
  §3.5  Time of Concentration
  Table 3-1  Runoff Coefficients

* ASCE Manual 77 (1992) "Design and Construction of Urban Stormwater
  Management Systems".

Public API
----------
rational_method(C, i, A_acres) -> float
    Q = C · i · A  [cfs]  — HEC-22 §3.1.

runoff_coefficient_lookup(surface_kind) -> float
    Mid-range C values from HEC-22 Table 3-1.

time_of_concentration(length_ft, slope, surface_kind) -> float
    Kirpich formula — HEC-22 §3.5 / Kirpich (1940). [minutes]

compute_design_flow(watershed, return_period_years) -> dict
    Composite weighted-C method — HEC-22 §3.3.

SubareaSpec
    TypedDict describing a single subarea in a composite watershed.
"""

from __future__ import annotations

import math
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 1 ft³/s = 0.028316846 m³/s
_CFS_TO_M3S: float = 0.028316846

# ---------------------------------------------------------------------------
# HEC-22 Table 3-1 — Runoff Coefficients
# Range (low, high) for each cover type.
# ---------------------------------------------------------------------------

#: HEC-22 Table 3-1 runoff coefficient ranges (low, high).
#: Mid-range = (low + high) / 2.
_HEC22_C_TABLE: dict[str, tuple[float, float]] = {
    # Pavement
    "asphalt":            (0.85, 0.95),
    "concrete":           (0.85, 0.95),
    # Roofs
    "roofs":              (0.75, 0.95),
    # Drives / walks
    "gravel_drives":      (0.30, 0.50),
    # Lawns (per soil type)
    "lawn_sandy":         (0.05, 0.20),
    "lawn_clay":          (0.13, 0.35),
    # Forest / woodland
    "forest_flat":        (0.05, 0.30),
}


# ---------------------------------------------------------------------------
# Rational Method — HEC-22 §3.1
# ---------------------------------------------------------------------------

def rational_method(
    runoff_coefficient_C: float,
    rainfall_intensity_i: float,
    area_A_acres: float,
) -> float:
    """
    Compute peak surface runoff using the Rational Method (HEC-22 §3.1).

    Formula:  Q = C · i · A

    The units balance when i is in inches/hour and A is in acres:
        Q [ft³/s] = C [dimensionless] · i [in/hr] · A [acres]

    The dimensional conversion factor is 1.008 ≈ 1 (exact derivation:
    1 in/hr × 1 acre = 1.008 ft³/s), which HEC-22 and engineering
    practice round to 1.0 — making the formula dimensionally exact for
    design purposes.

    Parameters
    ----------
    runoff_coefficient_C : float
        Runoff coefficient, dimensionless (0.0–1.0).
        Represents the fraction of rainfall that becomes runoff.
        Use ``runoff_coefficient_lookup()`` for HEC-22 Table 3-1 values.
    rainfall_intensity_i : float
        Design rainfall intensity [in/hr] for the storm return period.
        Obtained from IDF curves for the time of concentration Tc.
    area_A_acres : float
        Drainage area [acres].  HEC-22 §3.1 limits applicability to
        watersheds ≤ 200 acres (some references extend to 640 acres).

    Returns
    -------
    float
        Peak discharge Q [ft³/s (cfs)].

    Raises
    ------
    ValueError
        If C is outside [0, 1], i < 0, or A_acres < 0.

    Notes
    -----
    HEC-22 §3.1 states: "The rational formula is  Q = CiA"  where
    Q is peak discharge (cfs), C is the runoff coefficient, i is rainfall
    intensity (in/hr) for a duration equal to the time of concentration,
    and A is drainage area (acres).

    For large catchments (> 200 acres) or non-uniform rainfall, the
    Modified Rational Method or SCS/TR-55 is preferred.

    Examples
    --------
    Asphalt parking lot: C=0.9, i=5 in/hr, A=2 acres → Q = 9 cfs.

    >>> rational_method(0.9, 5.0, 2.0)
    9.0
    """
    if not (0.0 <= runoff_coefficient_C <= 1.0):
        raise ValueError(
            f"runoff_coefficient_C must be in [0, 1], got {runoff_coefficient_C!r}"
        )
    if rainfall_intensity_i < 0.0:
        raise ValueError(
            f"rainfall_intensity_i must be >= 0, got {rainfall_intensity_i!r}"
        )
    if area_A_acres < 0.0:
        raise ValueError(
            f"area_A_acres must be >= 0, got {area_A_acres!r}"
        )
    return runoff_coefficient_C * rainfall_intensity_i * area_A_acres


# ---------------------------------------------------------------------------
# Runoff coefficient lookup — HEC-22 Table 3-1
# ---------------------------------------------------------------------------

def runoff_coefficient_lookup(surface_kind: str) -> float:
    """
    Look up the mid-range runoff coefficient C for a surface type.

    Values from FHWA HEC-22 (3rd Edition) Table 3-1.

    Parameters
    ----------
    surface_kind : str
        One of:
            'asphalt'       — Asphalt pavement (0.85–0.95)
            'concrete'      — Concrete pavement (0.85–0.95)
            'roofs'         — Impervious roofs (0.75–0.95)
            'gravel_drives' — Gravel drives and walks (0.30–0.50)
            'lawn_sandy'    — Lawns, sandy soil (0.05–0.20)
            'lawn_clay'     — Lawns, clay soil (0.13–0.35)
            'forest_flat'   — Forests/woodlands, flat terrain (0.05–0.30)

    Returns
    -------
    float
        Mid-range C value: (low + high) / 2.

    Raises
    ------
    ValueError
        If surface_kind is not in the table.

    Notes
    -----
    HEC-22 Table 3-1 provides ranges rather than single values because
    the coefficient varies with storm intensity and antecedent moisture.
    The mid-range value is appropriate for standard design practice.
    For conservative (high-runoff) design, use the upper bound.

    Examples
    --------
    >>> runoff_coefficient_lookup('asphalt')
    0.9
    >>> runoff_coefficient_lookup('lawn_sandy')
    0.125
    """
    kind = surface_kind.strip().lower()
    if kind not in _HEC22_C_TABLE:
        valid = ", ".join(sorted(_HEC22_C_TABLE.keys()))
        raise ValueError(
            f"surface_kind {surface_kind!r} not in HEC-22 Table 3-1. "
            f"Valid: {valid}"
        )
    lo, hi = _HEC22_C_TABLE[kind]
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# Time of concentration — Kirpich formula (HEC-22 §3.5)
# ---------------------------------------------------------------------------

def time_of_concentration(
    length_ft: float,
    slope: float,
    surface_kind: str = "asphalt",
) -> float:
    """
    Compute time of concentration using the Kirpich (1940) formula.

    Formula (HEC-22 §3.5, US customary):

        Tc = 0.0078 · L^0.77 / S^0.385   [minutes]

    where:
        L = channel/flow length [ft]
        S = average watershed slope [ft/ft] (dimensionless, not percent)

    The ``surface_kind`` parameter is accepted for interface compatibility
    (composite watersheds may pass different cover types) but the Kirpich
    formula is geometry-based and does not use surface type directly.
    Surface texture affects channel velocity and travel time through the
    choice of flow path and slope — the practitioner must select L and S
    accordingly.

    Parameters
    ----------
    length_ft : float
        Hydraulic length of the flow path from the most remote point in the
        watershed to the design point [ft].  Must be > 0.
    slope : float
        Average slope along the flow path [ft/ft], e.g. 0.02 for 2% slope.
        Must be > 0.
    surface_kind : str
        Surface/cover type.  Accepted for composite-watershed workflows
        but does not alter the Kirpich computation.  Default 'asphalt'.

    Returns
    -------
    float
        Time of concentration Tc [minutes].

    Raises
    ------
    ValueError
        If length_ft <= 0 or slope <= 0.

    Notes
    -----
    Kirpich (1940) formula is valid for small catchments (< 200 acres) and
    channels with defined flow paths.  HEC-22 §3.5 notes it tends to
    under-predict Tc for overland-flow-dominated catchments; the user should
    apply a correction factor of 2 for overland flow on paved surfaces or
    sheet flow conditions (Wanielista et al., 1997).

    For L=1000 ft, S=0.02:
        Tc = 0.0078 × 1000^0.77 / 0.02^0.385
           = 0.0078 × 204.17 / 0.4475
           ≈ 7.18 min

    References
    ----------
    Kirpich, Z.P. (1940). Time of concentration of small agricultural
    watersheds. Civil Engineering, 10(6), 362.

    FHWA (2009) HEC-22, 3rd Edition, §3.5.

    Examples
    --------
    >>> time_of_concentration(1000.0, 0.02)
    7.1812...
    """
    if length_ft <= 0.0:
        raise ValueError(
            f"length_ft must be > 0, got {length_ft!r}"
        )
    if slope <= 0.0:
        raise ValueError(
            f"slope must be > 0, got {slope!r}"
        )
    return 0.0078 * (length_ft ** 0.77) / (slope ** 0.385)


# ---------------------------------------------------------------------------
# SubareaSpec — typed descriptor for composite watershed sub-areas
# ---------------------------------------------------------------------------

class SubareaSpec(TypedDict, total=False):
    """
    Specification for a single sub-area in a composite watershed.

    Fields
    ------
    surface_kind : str
        Cover type string for ``runoff_coefficient_lookup()``.
        Required if ``C`` is not provided.
    C : float
        Runoff coefficient (0–1).  If omitted, looked up from ``surface_kind``.
    area_acres : float
        Sub-area drainage area [acres].  Required.
    length_ft : float, optional
        Flow path length [ft] for Tc computation.
    slope : float, optional
        Average slope [ft/ft] for Tc computation.
    """
    surface_kind: str
    C: float
    area_acres: float
    length_ft: float
    slope: float


# ---------------------------------------------------------------------------
# Composite design flow — HEC-22 §3.3
# ---------------------------------------------------------------------------

def compute_design_flow(
    watershed: list[SubareaSpec],
    return_period_years: int = 10,
    rainfall_intensity_i: float | None = None,
) -> dict[str, Any]:
    """
    Compute composite watershed peak design flow via the weighted-C method.

    Implements HEC-22 §3.3: the composite (area-weighted average) runoff
    coefficient for a watershed composed of subareas with different land
    covers is:

        C_w = Σ(C_j · A_j) / Σ(A_j)

    The peak flow is then:

        Q = C_w · i · A_total   [cfs]

    where i is the rainfall intensity for the design return period at the
    time of concentration of the entire watershed, and A_total is the sum
    of all sub-area drainage areas.

    Parameters
    ----------
    watershed : list[SubareaSpec]
        List of sub-area dictionaries.  Each must have:
            - ``area_acres`` : float  — sub-area [acres]
            - ``C``          : float  — runoff coefficient, OR
            - ``surface_kind``: str   — for automatic lookup from HEC-22 Table 3-1
    return_period_years : int
        Design storm return period [years].  Included in the output for
        documentation; IDF intensity must be supplied by the caller.
        Default 10.
    rainfall_intensity_i : float or None
        Rainfall intensity [in/hr] for the design return period and the
        watershed time of concentration.  If None, the result dict will
        include ``Q_cfs=None`` and note that intensity must be supplied.

    Returns
    -------
    dict with keys:
        ok               : bool
        weighted_C       : float   — composite runoff coefficient
        total_area_acres : float   — sum of all sub-area areas
        subareas         : list    — per-subarea C and area
        return_period_years : int
        Q_cfs            : float or None  — peak flow [cfs]; None if i not supplied
        Q_m3s            : float or None  — peak flow [m³/s]
        warnings         : list[str]
    """
    if not watershed:
        return {
            "ok": False,
            "reason": "watershed must contain at least one SubareaSpec",
        }

    warnings_out: list[str] = []
    subareas_out = []
    total_CA = 0.0
    total_A = 0.0

    for idx, spec in enumerate(watershed):
        # --- Resolve area ---
        area = spec.get("area_acres")
        if area is None:
            return {
                "ok": False,
                "reason": f"subareas[{idx}] missing 'area_acres'",
            }
        area = float(area)
        if area <= 0.0:
            return {
                "ok": False,
                "reason": f"subareas[{idx}].area_acres must be > 0, got {area!r}",
            }

        # --- Resolve C ---
        if "C" in spec and spec["C"] is not None:
            C = float(spec["C"])
            source = "explicit"
        elif "surface_kind" in spec and spec["surface_kind"]:
            try:
                C = runoff_coefficient_lookup(spec["surface_kind"])
                source = f"HEC-22 Table 3-1 ({spec['surface_kind']})"
            except ValueError as exc:
                return {
                    "ok": False,
                    "reason": f"subareas[{idx}]: {exc}",
                }
        else:
            return {
                "ok": False,
                "reason": (
                    f"subareas[{idx}] must supply either 'C' or 'surface_kind'"
                ),
            }

        if not (0.0 <= C <= 1.0):
            return {
                "ok": False,
                "reason": f"subareas[{idx}].C must be in [0, 1], got {C!r}",
            }

        total_CA += C * area
        total_A += area
        subareas_out.append({
            "C": round(C, 6),
            "area_acres": round(area, 6),
            "C_source": source,
        })

    # Composite weighted-C  (HEC-22 §3.3)
    C_w = total_CA / total_A

    if C_w > 1.0:
        # Floating-point artefact; clamp
        C_w = 1.0
        warnings_out.append("Composite C was clamped to 1.0 due to floating-point rounding.")

    # HEC-22 §3.3 advisory: if C_w > 0.90 treat as 0.90 for conservative design
    # (some agencies cap at 0.95)
    if C_w > 0.95:
        warnings_out.append(
            f"Composite runoff coefficient C_w = {C_w:.3f} > 0.95; verify with "
            "local stormwater authority — some codes cap at 0.95."
        )

    # Peak flow
    Q_cfs: float | None = None
    Q_m3s: float | None = None
    if rainfall_intensity_i is not None:
        if rainfall_intensity_i < 0.0:
            return {
                "ok": False,
                "reason": "rainfall_intensity_i must be >= 0",
            }
        Q_cfs = rational_method(C_w, rainfall_intensity_i, total_A)
        Q_m3s = Q_cfs * _CFS_TO_M3S
    else:
        warnings_out.append(
            "rainfall_intensity_i not supplied; Q_cfs and Q_m3s are None. "
            "Obtain i from local IDF curves at the watershed Tc and return period, "
            "then call rational_method(C_w, i, total_area_acres)."
        )

    return {
        "ok": True,
        "weighted_C": round(C_w, 6),
        "total_area_acres": round(total_A, 6),
        "subareas": subareas_out,
        "return_period_years": return_period_years,
        "Q_cfs": round(Q_cfs, 6) if Q_cfs is not None else None,
        "Q_m3s": round(Q_m3s, 6) if Q_m3s is not None else None,
        "warnings": warnings_out,
    }
