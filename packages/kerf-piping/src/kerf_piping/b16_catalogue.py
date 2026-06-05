"""
kerf_piping.b16_catalogue — ASME B16 fitting dimension catalogue.

Implements dimensional data and engineering functions for:
  - ASME B16.9-2018 Factory-Made Wrought Butt-Welding Fittings
    (90° LR elbows, 45° elbows, 180° returns, reducers, caps)
  - ASME B16.5-2017 Pipe Flanges and Flanged Fittings (flange class/rating)
  - ASME B16.11-2021 Forged Fittings (socket-weld and threaded)

DISCLAIMER
----------
Dimensional data reproduced from publicly available engineering references.
NOT a replacement for the primary ASME standard.  For procurement and
fabrication always use the current ASME publication.

Key functions
-------------
lr_elbow_dims(dn)            Long-radius elbow center-to-end (A) + face-to-face (B).
sr_elbow_dims(dn)            Short-radius elbow dimensions.
reducer_dims(dn_large, dn_small) Concentric reducer overall length (H).
cap_dims(dn)                 Cap end-to-end (E).
flange_rating(class_, dn, material_group) ASME B16.5 pressure-temperature rating (psi).
fitting_weight_kg(fitting_type, dn) Approximate fitting weight.
select_fittings(dn, route_type) Bill of materials for a piping route.

References
----------
ASME B16.9-2018, Table 1 — Butt-welding fitting dimensions, NPS ½" through 48".
ASME B16.5-2017, Table 2 — Pressure-temperature ratings, Class 150 through 2500.
ASME B16.11-2021, Table 2 — Socket-weld and threaded forged fitting dimensions.
Crane TP-410, Appendix A — Fitting weights (approximate).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# ASME B16.9-2018 Table 1 — Long-radius elbow, centre-to-face dimension (mm)
# DN (mm) → A_mm
# A = 1.5 × NPS (in) × 25.4 mm  for LR (long-radius R = 1.5D)
# These values match B16.9-2018 Table 1 exactly for standard LR sizes.
# ---------------------------------------------------------------------------

_LR_ELBOW_A_MM: Dict[int, float] = {
    15:   38,     # NPS ½" — 1.5 × 25.4 = 38.1
    20:   51,     # NPS ¾"
    25:   38,     # NPS 1"  — NOTE B16.9 standard: A = 38 mm (not 1.5D exactly for small sizes)
    32:   51,
    40:   57,
    50:   76,
    65:   95,
    80:   114,
    100:  152,
    125:  190,
    150:  229,
    200:  305,
    250:  381,
    300:  457,
    350:  533,
    400:  610,
    450:  686,
    500:  762,
    600:  914,
}

# Short-radius elbow centre-to-face (mm): R = 1.0D
_SR_ELBOW_A_MM: Dict[int, float] = {
    25:   25,
    32:   32,
    40:   38,
    50:   51,
    65:   64,
    80:   76,
    100:  102,
    125:  127,
    150:  152,
    200:  203,
    250:  254,
    300:  305,
    350:  356,
    400:  406,
    450:  457,
    500:  508,
    600:  610,
}

# 45° LR elbow centre-to-face (mm) per B16.9 Table 1
_ELBOW_45_A_MM: Dict[int, float] = {
    15:   22,
    20:   25,
    25:   29,
    32:   35,
    40:   38,
    50:   51,
    65:   64,
    80:   76,
    100:  102,
    125:  127,
    150:  152,
    200:  203,
    250:  254,
    300:  305,
}

# Concentric reducer overall length H (mm) per B16.9 Table 1
_REDUCER_H_MM: Dict[int, float] = {
    25:   76,
    32:   76,
    40:   89,
    50:   89,
    65:   102,
    80:   102,
    100:  127,
    125:  140,
    150:  152,
    200:  203,
    250:  254,
    300:  305,
    350:  356,
    400:  381,
    450:  406,
    500:  432,
    600:  508,
}

# Cap end-to-end E (mm) per B16.9 Table 1
_CAP_E_MM: Dict[int, float] = {
    15:   38,
    20:   44,
    25:   51,
    32:   57,
    40:   60,
    50:   67,
    65:   73,
    80:   83,
    100:  102,
    125:  117,
    150:  133,
    200:  159,
    250:  184,
    300:  203,
}

# ---------------------------------------------------------------------------
# ASME B16.5-2017 — Pressure ratings (psi) at ambient temperature
# Class 150, 300, 600, 900, 1500, 2500
# Material Group 1.1 (carbon steel A105, A216 WCB) at 100°F (38°C)
# Source: ASME B16.5-2017 Table 2-1.1
# ---------------------------------------------------------------------------

_B16_5_RATING_PSI: Dict[int, float] = {
    150:   285.0,   # Class 150 at 100°F, Group 1.1
    300:   740.0,   # Class 300
    600:  1480.0,   # Class 600
    900:  2220.0,   # Class 900
   1500:  3705.0,   # Class 1500
   2500:  6170.0,   # Class 2500
}

# Derating factor vs temperature for carbon steel (Group 1.1)
# Source: ASME B16.5-2017 Table 2-1.1 (simplified linear)
# Key: temperature_F → derating factor (relative to 100°F rating)
_B16_5_DERATE_CS: Dict[float, float] = {
    100:  1.00,
    200:  0.96,
    300:  0.91,
    400:  0.87,
    500:  0.84,
    600:  0.81,
    650:  0.79,
    700:  0.74,
    750:  0.68,
    800:  0.62,
}

# ---------------------------------------------------------------------------
# Approximate fitting weights (kg) per Crane TP-410 App. A (carbon steel)
# Key: (fitting_type_key, dn_mm)
# ---------------------------------------------------------------------------

_FITTING_WEIGHT_KG: Dict[Tuple[str, int], float] = {
    # 90° LR elbows (BW)
    ("90lr_elbow", 25):    0.14,
    ("90lr_elbow", 40):    0.22,
    ("90lr_elbow", 50):    0.41,
    ("90lr_elbow", 80):    0.84,
    ("90lr_elbow", 100):   1.66,
    ("90lr_elbow", 150):   4.17,
    ("90lr_elbow", 200):   9.75,
    ("90lr_elbow", 250):  18.60,
    ("90lr_elbow", 300):  34.00,
    # 45° elbows (BW)
    ("45_elbow", 25):    0.09,
    ("45_elbow", 50):    0.21,
    ("45_elbow", 100):   0.91,
    ("45_elbow", 150):   2.22,
    ("45_elbow", 200):   5.80,
    # Tees equal (BW)
    ("tee_equal", 25):    0.25,
    ("tee_equal", 50):    0.84,
    ("tee_equal", 100):   3.15,
    ("tee_equal", 150):   8.30,
    ("tee_equal", 200):  20.40,
    ("tee_equal", 250):  39.00,
    # Caps
    ("cap", 50):    0.22,
    ("cap", 100):   0.73,
    ("cap", 150):   1.68,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ElbowDims:
    """ASME B16.9 elbow dimensions."""
    dn: int
    angle_deg: float
    radius_type: str          # 'LR' (long radius) or 'SR' (short radius)
    center_to_face_mm: float  # dimension A (B16.9 Table 1)
    od_mm: float


@dataclass
class ReducerDims:
    """ASME B16.9 concentric/eccentric reducer dimensions."""
    dn_large: int
    dn_small: int
    overall_length_mm: float  # dimension H (B16.9 Table 1)
    concentric: bool = True


@dataclass
class FlangeDims:
    """ASME B16.5 flange rating summary."""
    dn: int
    class_: int
    material_group: str
    rating_psi: float   # ambient rating
    rating_bar: float   # ambient rating in bar
    derating_note: str


@dataclass
class FittingBOM:
    """Bill of materials entry for a piping fitting."""
    fitting_type: str
    dn: int
    quantity: int
    description: str
    weight_kg_each: Optional[float] = None
    dimension_key: str = ""  # e.g. 'center_to_face_mm=152'


# ---------------------------------------------------------------------------
# Public API — dimensions
# ---------------------------------------------------------------------------

def lr_elbow_dims(dn: int) -> ElbowDims:
    """
    ASME B16.9-2018 long-radius 90° elbow centre-to-face dimension (A).

    Parameters
    ----------
    dn : Nominal pipe diameter (DN, mm).

    Returns
    -------
    ElbowDims with center_to_face_mm = A per B16.9 Table 1.

    Raises
    ------
    KeyError if DN not in B16.9 LR elbow table.
    """
    from kerf_piping.pipe_spec import NOMINAL_OD_MM
    if dn not in _LR_ELBOW_A_MM:
        raise KeyError(
            f"DN{dn} not in ASME B16.9 LR elbow table. "
            f"Available: {sorted(_LR_ELBOW_A_MM.keys())}"
        )
    od = NOMINAL_OD_MM.get(dn, 0.0)
    return ElbowDims(
        dn=dn,
        angle_deg=90.0,
        radius_type="LR",
        center_to_face_mm=float(_LR_ELBOW_A_MM[dn]),
        od_mm=od,
    )


def sr_elbow_dims(dn: int) -> ElbowDims:
    """
    ASME B16.9-2018 short-radius 90° elbow centre-to-face dimension.

    Parameters
    ----------
    dn : Nominal pipe diameter (DN, mm).

    Raises
    ------
    KeyError if DN not in B16.9 SR elbow table.
    """
    from kerf_piping.pipe_spec import NOMINAL_OD_MM
    if dn not in _SR_ELBOW_A_MM:
        raise KeyError(
            f"DN{dn} not in ASME B16.9 SR elbow table. "
            f"Available: {sorted(_SR_ELBOW_A_MM.keys())}"
        )
    od = NOMINAL_OD_MM.get(dn, 0.0)
    return ElbowDims(
        dn=dn,
        angle_deg=90.0,
        radius_type="SR",
        center_to_face_mm=float(_SR_ELBOW_A_MM[dn]),
        od_mm=od,
    )


def elbow_45_dims(dn: int) -> ElbowDims:
    """
    ASME B16.9-2018 long-radius 45° elbow centre-to-face dimension.

    Raises
    ------
    KeyError if DN not in B16.9 45° elbow table.
    """
    from kerf_piping.pipe_spec import NOMINAL_OD_MM
    if dn not in _ELBOW_45_A_MM:
        raise KeyError(
            f"DN{dn} not in ASME B16.9 45° elbow table. "
            f"Available: {sorted(_ELBOW_45_A_MM.keys())}"
        )
    od = NOMINAL_OD_MM.get(dn, 0.0)
    return ElbowDims(
        dn=dn,
        angle_deg=45.0,
        radius_type="LR",
        center_to_face_mm=float(_ELBOW_45_A_MM[dn]),
        od_mm=od,
    )


def reducer_dims(dn_large: int, dn_small: int) -> ReducerDims:
    """
    ASME B16.9-2018 concentric reducer overall length H.

    The reducer length is driven by the larger end DN.

    Parameters
    ----------
    dn_large : Larger end nominal diameter (DN, mm).
    dn_small : Smaller end nominal diameter (DN, mm).

    Raises
    ------
    KeyError  if dn_large not in the reducer length table.
    ValueError if dn_small >= dn_large.
    """
    if dn_small >= dn_large:
        raise ValueError(
            f"dn_small ({dn_small}) must be < dn_large ({dn_large})"
        )
    if dn_large not in _REDUCER_H_MM:
        raise KeyError(
            f"DN{dn_large} not in ASME B16.9 reducer table. "
            f"Available: {sorted(_REDUCER_H_MM.keys())}"
        )
    return ReducerDims(
        dn_large=dn_large,
        dn_small=dn_small,
        overall_length_mm=float(_REDUCER_H_MM[dn_large]),
        concentric=True,
    )


def cap_dims(dn: int) -> float:
    """
    ASME B16.9-2018 cap end-to-end dimension E (mm).

    Raises
    ------
    KeyError if DN not in cap table.
    """
    if dn not in _CAP_E_MM:
        raise KeyError(
            f"DN{dn} not in ASME B16.9 cap table. "
            f"Available: {sorted(_CAP_E_MM.keys())}"
        )
    return float(_CAP_E_MM[dn])


# ---------------------------------------------------------------------------
# Public API — flange rating
# ---------------------------------------------------------------------------

def flange_rating(
    class_: int,
    dn: int,
    temp_F: float = 100.0,
    material_group: str = "1.1",
) -> FlangeDims:
    """
    ASME B16.5-2017 flange pressure-temperature rating.

    Implements Group 1.1 (carbon steel, A105 / A216 WCB) ratings per
    ASME B16.5-2017 Table 2-1.1.

    Parameters
    ----------
    class_         : Flange class: 150, 300, 600, 900, 1500, or 2500.
    dn             : Nominal pipe diameter (DN, mm) — used in the return only.
    temp_F         : Design temperature (°F). Default 100°F (ambient).
    material_group : Material group code per B16.5 (currently only '1.1' supported).

    Returns
    -------
    FlangeDims with ambient and temperature-derated ratings.

    Raises
    ------
    KeyError  if class_ is not 150/300/600/900/1500/2500.
    ValueError if temp_F is outside 100–800°F range.
    NotImplementedError if material_group is not '1.1'.
    """
    if material_group != "1.1":
        raise NotImplementedError(
            f"Only material group 1.1 (carbon steel) is currently tabulated. "
            f"Got: {material_group!r}"
        )

    if class_ not in _B16_5_RATING_PSI:
        raise KeyError(
            f"Flange class {class_!r} not in ASME B16.5 table. "
            f"Supported: {sorted(_B16_5_RATING_PSI.keys())}"
        )

    ambient_rating_psi = _B16_5_RATING_PSI[class_]

    # Interpolate derating factor
    bins = sorted(_B16_5_DERATE_CS.keys())
    t_min, t_max = bins[0], bins[-1]
    if temp_F < t_min:
        df = _B16_5_DERATE_CS[t_min]
    elif temp_F > t_max:
        raise ValueError(
            f"Temperature {temp_F:.0f}°F exceeds maximum tabled temperature "
            f"{t_max:.0f}°F for B16.5 Group 1.1 derating. "
            "Consult full ASME B16.5 Table 2 for higher temperatures."
        )
    else:
        lo = max(b for b in bins if b <= temp_F)
        hi = min(b for b in bins if b >= temp_F)
        if lo == hi:
            df = _B16_5_DERATE_CS[lo]
        else:
            df_lo = _B16_5_DERATE_CS[lo]
            df_hi = _B16_5_DERATE_CS[hi]
            df = df_lo + (df_hi - df_lo) * (temp_F - lo) / (hi - lo)

    rated_psi = ambient_rating_psi * df
    rated_bar = rated_psi * 0.0689476  # 1 psi = 0.0689476 bar

    note = (
        f"ASME B16.5-2017 Class {class_} Material Group 1.1 "
        f"(carbon steel A105/A216 WCB) at {temp_F:.0f}°F. "
        f"Derating factor = {df:.3f} vs ambient."
    )

    return FlangeDims(
        dn=dn,
        class_=class_,
        material_group=material_group,
        rating_psi=round(rated_psi, 1),
        rating_bar=round(rated_bar, 2),
        derating_note=note,
    )


# ---------------------------------------------------------------------------
# Public API — fitting weight
# ---------------------------------------------------------------------------

def fitting_weight_kg(fitting_type: str, dn: int) -> float:
    """
    Approximate fitting weight (kg) per Crane TP-410 App. A.

    Interpolates linearly between the nearest tabled DN sizes.

    Parameters
    ----------
    fitting_type : One of '90lr_elbow', '45_elbow', 'tee_equal', 'cap'.
    dn           : Nominal diameter (DN, mm).

    Returns
    -------
    Approximate weight in kg.  Returns 0.0 if type not in table.
    """
    relevant = {
        k_dn: w for (ft, k_dn), w in _FITTING_WEIGHT_KG.items()
        if ft == fitting_type
    }
    if not relevant:
        return 0.0

    dns_sorted = sorted(relevant.keys())
    if dn <= dns_sorted[0]:
        return relevant[dns_sorted[0]]
    if dn >= dns_sorted[-1]:
        return relevant[dns_sorted[-1]]

    lo = max(d for d in dns_sorted if d <= dn)
    hi = min(d for d in dns_sorted if d >= dn)
    if lo == hi:
        return relevant[lo]
    frac = (dn - lo) / (hi - lo)
    return relevant[lo] + frac * (relevant[hi] - relevant[lo])


# ---------------------------------------------------------------------------
# Public API — select fittings BOM
# ---------------------------------------------------------------------------

def select_fittings(
    dn: int,
    elbows_90lr: int = 0,
    elbows_90sr: int = 0,
    elbows_45: int = 0,
    tees_equal: int = 0,
    reducers: Optional[list[Tuple[int, int]]] = None,
    caps: int = 0,
    flange_class: Optional[int] = None,
    flanges: int = 0,
    temp_F: float = 100.0,
) -> dict:
    """
    Select ASME B16.9 / B16.5 fittings for a piping route and return a BOM.

    Parameters
    ----------
    dn            : Nominal pipe diameter (DN, mm) for standard fittings.
    elbows_90lr   : Number of 90° long-radius elbows (B16.9).
    elbows_90sr   : Number of 90° short-radius elbows (B16.9).
    elbows_45     : Number of 45° long-radius elbows (B16.9).
    tees_equal    : Number of equal tees (B16.9).
    reducers      : List of (dn_large, dn_small) reducer pairs.
    caps          : Number of caps (B16.9).
    flange_class  : Flange class (150/300/600/900/1500/2500) or None.
    flanges       : Number of flanges (B16.5).
    temp_F        : Design temperature for flange rating.

    Returns
    -------
    dict with:
        'bom'            list of FittingBOM dicts
        'total_weight_kg' approximate total fitting weight
        'flange_rating'  FlangeDims dict (if flange_class provided)
        'disclaimer'     engineering notice
    """
    bom: list[dict] = []
    total_weight = 0.0

    if elbows_90lr > 0:
        try:
            dims = lr_elbow_dims(dn)
            w = fitting_weight_kg("90lr_elbow", dn)
            bom.append({
                "fitting_type": "90_LR_elbow",
                "dn": dn,
                "quantity": elbows_90lr,
                "description": f"ASME B16.9 90° LR elbow DN{dn}",
                "center_to_face_mm": dims.center_to_face_mm,
                "weight_kg_each": round(w, 3),
                "standard": "ASME B16.9-2018",
            })
            total_weight += w * elbows_90lr
        except KeyError as exc:
            bom.append({"fitting_type": "90_LR_elbow", "error": str(exc), "quantity": elbows_90lr})

    if elbows_90sr > 0:
        try:
            dims = sr_elbow_dims(dn)
            bom.append({
                "fitting_type": "90_SR_elbow",
                "dn": dn,
                "quantity": elbows_90sr,
                "description": f"ASME B16.9 90° SR elbow DN{dn}",
                "center_to_face_mm": dims.center_to_face_mm,
                "weight_kg_each": None,
                "standard": "ASME B16.9-2018",
            })
        except KeyError as exc:
            bom.append({"fitting_type": "90_SR_elbow", "error": str(exc), "quantity": elbows_90sr})

    if elbows_45 > 0:
        try:
            dims = elbow_45_dims(dn)
            w = fitting_weight_kg("45_elbow", dn)
            bom.append({
                "fitting_type": "45_elbow",
                "dn": dn,
                "quantity": elbows_45,
                "description": f"ASME B16.9 45° LR elbow DN{dn}",
                "center_to_face_mm": dims.center_to_face_mm,
                "weight_kg_each": round(w, 3),
                "standard": "ASME B16.9-2018",
            })
            total_weight += w * elbows_45
        except KeyError as exc:
            bom.append({"fitting_type": "45_elbow", "error": str(exc), "quantity": elbows_45})

    if tees_equal > 0:
        w = fitting_weight_kg("tee_equal", dn)
        bom.append({
            "fitting_type": "tee_equal",
            "dn": dn,
            "quantity": tees_equal,
            "description": f"ASME B16.9 equal tee DN{dn}",
            "weight_kg_each": round(w, 3),
            "standard": "ASME B16.9-2018",
        })
        total_weight += w * tees_equal

    for dn_lg, dn_sm in (reducers or []):
        try:
            dims = reducer_dims(dn_lg, dn_sm)
            bom.append({
                "fitting_type": "reducer",
                "dn_large": dn_lg,
                "dn_small": dn_sm,
                "quantity": 1,
                "description": f"ASME B16.9 concentric reducer DN{dn_lg}×DN{dn_sm}",
                "overall_length_mm": dims.overall_length_mm,
                "standard": "ASME B16.9-2018",
            })
        except (KeyError, ValueError) as exc:
            bom.append({"fitting_type": "reducer", "error": str(exc)})

    if caps > 0:
        try:
            e = cap_dims(dn)
            w = fitting_weight_kg("cap", dn)
            bom.append({
                "fitting_type": "cap",
                "dn": dn,
                "quantity": caps,
                "description": f"ASME B16.9 cap DN{dn}",
                "end_to_end_mm": e,
                "weight_kg_each": round(w, 3),
                "standard": "ASME B16.9-2018",
            })
            total_weight += w * caps
        except KeyError as exc:
            bom.append({"fitting_type": "cap", "error": str(exc), "quantity": caps})

    flange_result = None
    if flanges > 0 and flange_class is not None:
        try:
            fd = flange_rating(flange_class, dn, temp_F)
            bom.append({
                "fitting_type": "flange",
                "dn": dn,
                "class": flange_class,
                "quantity": flanges,
                "description": f"ASME B16.5 Class {flange_class} flange DN{dn}",
                "rating_psi": fd.rating_psi,
                "rating_bar": fd.rating_bar,
                "standard": "ASME B16.5-2017",
            })
            flange_result = {
                "dn": fd.dn,
                "class": fd.class_,
                "material_group": fd.material_group,
                "rating_psi": fd.rating_psi,
                "rating_bar": fd.rating_bar,
                "note": fd.derating_note,
            }
        except (KeyError, ValueError, NotImplementedError) as exc:
            bom.append({"fitting_type": "flange", "error": str(exc), "quantity": flanges})

    return {
        "bom": bom,
        "total_weight_kg": round(total_weight, 3),
        "flange_rating": flange_result,
        "disclaimer": (
            "ASME B16.9-2018 / B16.5-2017 dimensional data — "
            "NOT a replacement for the primary ASME standard. "
            "For procurement and fabrication verify against the current ASME publication."
        ),
    }
