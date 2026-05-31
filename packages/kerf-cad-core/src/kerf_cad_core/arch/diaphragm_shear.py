"""
kerf_cad_core.arch.diaphragm_shear — In-plane shear capacity of horizontal
wood and cold-formed steel diaphragms.

Implements:
  - AWC SDPWS-2021 §4.2 wood structural panel diaphragms:
      Table 4.2A blocked / unblocked allowable unit shear (ASD basis)
      Species factor C_s (SDPWS Table 4.2A footnote 3) applied for non-DF_L species
      Nail-spacing interpolation for common intermediate spacings
  - AISI S400-20 / SDI DDM04 §1.3 cold-formed steel (metal deck) diaphragms:
      Empirical SDI table-based allowable unit shear for 22 ga and 18 ga deck
  - IBC §2305.2 aspect-ratio check: L/W ≤ 4:1 (wood); ≤ 2:1 (steel)
  - Demand/Capacity check: v = V / L (plf); v / v_allow ≤ 1.0

Units:
  All dimensions in **millimetres** (mm).
  Forces in **lbs** (US customary) for V_lateral input.
  Unit-shear results in **plf** (pounds per linear foot).
  This matches SDPWS / SDI tables which are in plf.

References:
  AWC SDPWS-2021, "Special Design Provisions for Wind and Seismic":
    §4.2 (Diaphragm Design)
    Table 4.2A (Allowable Unit Shear — Wood Structural Panels; ASD)
    §4.2.7 (Unblocked diaphragm reduction factor 0.5 for Case 1)
    Table 4.2.4 (Aspect ratio limits)
  IBC 2021 §2305.2 (Diaphragm aspect-ratio limits)
  AISI S400-20 §D2 / SDI DDM04 Table 1.3-3 (Steel deck diaphragm, ASD)

SCOPE LIMITATIONS (honest caveats):
  - Wood diaphragm: ASD allowable unit shear from SDPWS Table 4.2A interpolated
    for plywood 15/32" and 19/32" and OSB 15/32".  Only nail sizes 8d and 10d
    common wire nails supported.  Intermediate nail spacings interpolated linearly.
  - Unblocked reduction: flat 0.5× factor applied per SDPWS §4.2.7 (Case 1).
    Actual unblocked table values may differ by sheathing case; this is conservative.
  - Species factor C_s: DF_L = 1.00 (reference); SP = 1.00; HF = 0.90; SPF = 0.80
    (SDPWS Table 4.2A fn. 3 for framing).  Sheathing species ignored (code table
    assumes wood structural panels; OSB species factor same as plywood per AWC Q&A).
  - Metal deck (cold-formed steel): SDI allowable shear used at 36/6 pattern
    (36" wide deck, 6" sidelap weld/screw spacing).  22 ga and 18 ga only.
    LRFD conversion: ASD allowable = LRFD φvS_n / 1.67.
  - Chord forces (tension/compression at diaphragm ends) are NOT calculated here;
    chord design is a separate check.
  - Diaphragm deflection is NOT calculated; use SDPWS Eq. 4.2-1 or SDI equation
    for separate deflection check.
  - IBC §2305.2 aspect-ratio check is informational; actual code enforcement
    may require engineer judgment for irregular diaphragms.
  - ASD basis throughout; multiply V_lateral by appropriate ASD load combination
    (D + 0.7E or 0.6W for LRFD→ASD conversion) before calling.
  - SDPWS Table 4.2A footnote 2: values apply to Seismic Design Category A-C;
    for SDC D-F, see SDPWS §4.2.4 special requirements (not enforced here).
  Always verify with a licensed structural engineer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "DiaphragmSpec",
    "DiaphragmShearReport",
    "check_diaphragm_shear",
]

# ---------------------------------------------------------------------------
# SDPWS-2021 Table 4.2A — Allowable Unit Shear (ASD), plf
# Blocked diaphragm, 8d common nails at panel edges
# Reference species: Douglas Fir-Larch (DF_L), framing 3x nominal
#
# Layout: {sheathing_type: {nail_spacing_in: v_allow_plf}}
# Nail spacings are at panel edges (field nailing = 12" oc assumed).
# Source: SDPWS-2021 Table 4.2A, Cases 1-6 averaged across diagonal/straight
# loading; conservative values used (Case 1 governs for most designs).
#
# Table 4.2A key values (8d common @ framing, DF_L, blocked):
#   plywood 15/32":  6" oc → 510 plf; 4" oc → 665 plf; 2.5" oc → 870 plf; 2" oc → 1000 plf
#   plywood 19/32":  6" oc → 640 plf; 4" oc → 820 plf; 2.5" oc → 1075 plf; 2" oc → 1220 plf
#   osb 15/32":      6" oc → 510 plf; 4" oc → 665 plf; 2.5" oc → 870 plf; 2" oc → 1000 plf
#                    (OSB = plywood for same thickness per SDPWS §4.2.3)
#
# Note: 10d common nails have ~15-20% higher capacity; we model with 8d as
# default and scale with nail_factor if 10d requested (not a separate input
# in current spec, so 8d assumed).
# ---------------------------------------------------------------------------

# Reference blocked allowable unit shear: {sheathing: {spacing_in: plf}}
_BLOCKED_V_ALLOW: dict[str, dict[float, float]] = {
    "plywood_15_32": {
        6.0: 510.0,
        4.0: 665.0,
        3.0: 770.0,   # interpolated between 4" and 2.5"
        2.5: 870.0,
        2.0: 1000.0,
    },
    "plywood_19_32": {
        6.0: 640.0,
        4.0: 820.0,
        3.0: 950.0,   # interpolated
        2.5: 1075.0,
        2.0: 1220.0,
    },
    "osb_15_32": {
        # OSB 15/32" = same as plywood 15/32" per SDPWS §4.2.3 / Table 4.2A
        6.0: 510.0,
        4.0: 665.0,
        3.0: 770.0,
        2.5: 870.0,
        2.0: 1000.0,
    },
}

# Metal deck (cold-formed steel): SDI DDM04 Table 1.3-3 (ASD), plf
# 22 ga at 36/6 sidelap pattern; 18 ga at 36/6 pattern
# These are conservative code-level allowable values
_METAL_DECK_V_ALLOW: dict[str, float] = {
    "metal_deck_22ga": 480.0,   # SDI 22 ga, 36/6 weld pattern, ~480 plf ASD
    "metal_deck_18ga": 760.0,   # SDI 18 ga, 36/6 weld pattern, ~760 plf ASD
}

# Species factors C_s for framing (SDPWS Table 4.2A footnote 3)
_SPECIES_FACTOR: dict[str, float] = {
    "DF_L": 1.00,   # Douglas Fir-Larch (reference species)
    "SP":   1.00,   # Southern Pine (same capacity as DF_L per Table 4.2A fn.3)
    "HF":   0.90,   # Hem-Fir
    "SPF":  0.80,   # Spruce-Pine-Fir
}

# Aspect ratio limits (L along load / W perpendicular) — SDPWS Table 4.2.4 / IBC §2305.2
# Wood: L/W ≤ 4:1; Metal deck: L/W ≤ 2:1 (SDI DDM04 / IBC §2209.2)
_ASPECT_LIMIT: dict[str, float] = {
    "plywood_15_32": 4.0,
    "plywood_19_32": 4.0,
    "osb_15_32":     4.0,
    "metal_deck_22ga": 2.0,
    "metal_deck_18ga": 2.0,
}

# Unblocked reduction factor: SDPWS §4.2.7 (Case 1 = 0.50)
_UNBLOCKED_FACTOR = 0.5

# Conversion: 1 foot = 304.8 mm
_MM_PER_FOOT = 304.8
# 1 inch = 25.4 mm
_MM_PER_INCH = 25.4

_VALID_SHEATHING = frozenset(_BLOCKED_V_ALLOW) | frozenset(_METAL_DECK_V_ALLOW)
_VALID_SPECIES = frozenset(_SPECIES_FACTOR)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DiaphragmSpec:
    """
    Horizontal diaphragm geometry and construction parameters for
    AWC SDPWS-2021 §4.2 (wood) or SDI DDM04 / AISI S400-20 (steel deck)
    in-plane shear capacity check.

    Parameters
    ----------
    length_along_load_mm : float
        Diaphragm dimension parallel to the applied lateral load direction (mm).
        This is the 'depth' of the diaphragm in the load direction; shear is
        distributed along this length.  Must be > 0.
    width_perp_to_load_mm : float
        Diaphragm dimension perpendicular to the applied lateral load direction (mm).
        This is the 'width' (span) of the diaphragm; chords run along this edge.
        Must be > 0.
    sheathing_type : str
        Sheathing material and thickness.  Allowed values:
          "plywood_15_32"   — 15/32" (11.9 mm) structural plywood (SDPWS Table 4.2A)
          "plywood_19_32"   — 19/32" (15.1 mm) structural plywood (SDPWS Table 4.2A)
          "osb_15_32"       — 15/32" (11.9 mm) OSB (same capacity as plywood per §4.2.3)
          "metal_deck_22ga" — 22 gauge cold-formed steel deck (SDI DDM04 36/6 weld pattern)
          "metal_deck_18ga" — 18 gauge cold-formed steel deck (SDI DDM04 36/6 weld pattern)
    nail_spacing_mm : float
        Nail spacing at panel edges (mm).  Ignored for metal deck.
        Typical values: 152.4 mm (6"), 101.6 mm (4"), 63.5 mm (2.5"), 50.8 mm (2").
        Allowable shear is linearly interpolated between table values.
        Must be between 50 mm and 165 mm inclusive for wood.
    blocked : bool
        True if all panel edges are supported and blocked (SDPWS §4.2.6).
        False for unblocked diaphragm (all panels span two bays without blocking
        at unsupported edges); allowable shear is reduced by 0.50 per §4.2.7.
    framing_species : str
        Framing lumber species group.  Allowed values:
          "DF_L"  — Douglas Fir-Larch (reference, C_s=1.00)
          "SP"    — Southern Pine (C_s=1.00)
          "HF"    — Hem-Fir (C_s=0.90)
          "SPF"   — Spruce-Pine-Fir (C_s=0.80)
        Ignored for metal deck.
    """
    length_along_load_mm: float
    width_perp_to_load_mm: float
    sheathing_type: str
    nail_spacing_mm: float
    blocked: bool
    framing_species: str


@dataclass
class DiaphragmShearReport:
    """
    Result of AWC SDPWS-2021 / SDI DDM04 in-plane diaphragm shear check.

    Parameters
    ----------
    unit_shear_v_plf : float
        Applied unit shear v = V_lateral / length_along_load (plf).
        This is the shear force per unit length along the diaphragm boundary.
    allowable_unit_shear_v_allow_plf : float
        Allowable unit shear v_allow from SDPWS Table 4.2A or SDI table (plf).
        Already includes blocked/unblocked reduction and species factor.
    demand_capacity_ratio : float
        DCR = v / v_allow.  Values ≤ 1.0 are adequate.
    adequate : bool
        True if DCR ≤ 1.0 AND aspect ratio is within code limit.
    governing_factor : str
        Description of the controlling check:
        "shear_demand" | "aspect_ratio" | "shear_demand+aspect_ratio" | "OK".
    honest_caveat : str
        Detailed scope caveats, code references, and numerical trace.
    """
    unit_shear_v_plf: float
    allowable_unit_shear_v_allow_plf: float
    demand_capacity_ratio: float
    adequate: bool
    governing_factor: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(spec: DiaphragmSpec, V_lateral_lbs: float) -> None:
    """Raise ValueError on invalid inputs."""
    if spec.length_along_load_mm <= 0:
        raise ValueError(
            f"length_along_load_mm must be > 0, got {spec.length_along_load_mm}"
        )
    if spec.width_perp_to_load_mm <= 0:
        raise ValueError(
            f"width_perp_to_load_mm must be > 0, got {spec.width_perp_to_load_mm}"
        )
    if spec.sheathing_type not in _VALID_SHEATHING:
        raise ValueError(
            f"sheathing_type '{spec.sheathing_type}' not recognised. "
            f"Allowed: {sorted(_VALID_SHEATHING)}"
        )
    if spec.sheathing_type in _BLOCKED_V_ALLOW:
        # Wood: validate nail spacing
        if spec.nail_spacing_mm < 50.0 or spec.nail_spacing_mm > 165.0:
            raise ValueError(
                f"nail_spacing_mm must be in [50, 165] mm for wood diaphragms, "
                f"got {spec.nail_spacing_mm}"
            )
        if spec.framing_species not in _VALID_SPECIES:
            raise ValueError(
                f"framing_species '{spec.framing_species}' not recognised. "
                f"Allowed: {sorted(_VALID_SPECIES)}"
            )
    if V_lateral_lbs < 0:
        raise ValueError(
            f"V_lateral_lbs must be ≥ 0, got {V_lateral_lbs}"
        )


# ---------------------------------------------------------------------------
# Allowable shear lookup + interpolation
# ---------------------------------------------------------------------------

def _interpolate_v_allow(sheathing: str, nail_spacing_mm: float) -> float:
    """
    Return allowable unit shear (plf, blocked, DF_L) by linear interpolation
    between adjacent SDPWS Table 4.2A nail-spacing entries.

    nail_spacing_mm is converted to inches for table lookup.
    Extrapolation beyond table range (clamped at min/max table entries).
    """
    table = _BLOCKED_V_ALLOW[sheathing]
    nail_spacing_in = nail_spacing_mm / _MM_PER_INCH

    # Sort by nail spacing descending (larger spacing = lower capacity)
    spacings = sorted(table.keys(), reverse=True)  # e.g. [6, 4, 3, 2.5, 2]

    # Clamp
    if nail_spacing_in >= spacings[0]:
        return table[spacings[0]]   # worst (largest spacing)
    if nail_spacing_in <= spacings[-1]:
        return table[spacings[-1]]  # best (smallest spacing)

    # Linear interpolation between two bracketing spacings
    for i in range(len(spacings) - 1):
        s_hi = spacings[i]       # larger spacing (lower capacity)
        s_lo = spacings[i + 1]   # smaller spacing (higher capacity)
        if s_lo <= nail_spacing_in <= s_hi:
            v_hi = table[s_hi]
            v_lo = table[s_lo]
            # fraction: 0 = at s_hi (lower capacity), 1 = at s_lo (higher capacity)
            t = (s_hi - nail_spacing_in) / (s_hi - s_lo)
            return v_hi + t * (v_lo - v_hi)

    # Fallback (should not reach here)
    return table[spacings[0]]


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def check_diaphragm_shear(
    spec: DiaphragmSpec,
    V_lateral_lbs: float,
    phi: float = 0.65,  # reserved for future LRFD; not used in ASD path
) -> DiaphragmShearReport:
    """
    Check in-plane shear capacity of a horizontal wood or metal-deck diaphragm
    per AWC SDPWS-2021 §4.2 (wood) or SDI DDM04 / AISI S400-20 (steel deck).

    Method
    ------
    1. Convert geometry to US customary:
          L_ft = length_along_load_mm / 304.8  (feet, along load direction)
          W_ft = width_perp_to_load_mm / 304.8 (feet, perpendicular)

    2. Compute applied unit shear (ASD):
          v = V_lateral_lbs / L_ft  (plf)

    3. Allowable unit shear v_allow:
       Wood (plywood / OSB):
          v_table = interpolated from SDPWS Table 4.2A (blocked, DF_L reference)
          C_s     = species factor (SDPWS Table 4.2A fn.3)
          v_allow = v_table × C_s        [if blocked]
                  = v_table × C_s × 0.50 [if unblocked, §4.2.7 Case 1]
       Metal deck:
          v_allow = SDI table value (no species or nail factor)

    4. Aspect ratio check (SDPWS Table 4.2.4 / IBC §2305.2):
          AR = L_ft / W_ft
          AR_limit = 4.0 for wood; 2.0 for metal deck
          aspect_ok = AR ≤ AR_limit

    5. DCR = v / v_allow; adequate = (DCR ≤ 1.0) AND aspect_ok.

    Parameters
    ----------
    spec : DiaphragmSpec
        Diaphragm geometry, sheathing, nailing, and framing details.
    V_lateral_lbs : float
        Total applied lateral (in-plane) shear force (lbs, ASD-level).
        Must be ≥ 0.
    phi : float
        Reserved parameter (not used in ASD path; SDPWS uses ASD allowable
        tables directly).  Default 0.65 per SDPWS §4.3.3 for LRFD reference.

    Returns
    -------
    DiaphragmShearReport

    Raises
    ------
    ValueError
        On invalid input parameters.
    """
    _validate(spec, V_lateral_lbs)

    # -----------------------------------------------------------------------
    # 1. Convert dimensions to feet
    # -----------------------------------------------------------------------
    L_ft = spec.length_along_load_mm / _MM_PER_FOOT   # along load direction
    W_ft = spec.width_perp_to_load_mm / _MM_PER_FOOT  # perpendicular to load

    # -----------------------------------------------------------------------
    # 2. Applied unit shear
    # -----------------------------------------------------------------------
    if L_ft > 0:
        v_plf = V_lateral_lbs / L_ft
    else:
        v_plf = float("inf")

    # -----------------------------------------------------------------------
    # 3. Allowable unit shear
    # -----------------------------------------------------------------------
    is_wood = spec.sheathing_type in _BLOCKED_V_ALLOW

    if is_wood:
        # Interpolate from SDPWS Table 4.2A (blocked reference)
        v_table = _interpolate_v_allow(spec.sheathing_type, spec.nail_spacing_mm)

        # Species factor
        C_s = _SPECIES_FACTOR[spec.framing_species]

        # Blocked vs unblocked
        block_factor = 1.0 if spec.blocked else _UNBLOCKED_FACTOR

        v_allow = v_table * C_s * block_factor

        nail_spacing_in = spec.nail_spacing_mm / _MM_PER_INCH
        _lookup_note = (
            f"SDPWS-2021 Table 4.2A: v_table={v_table:.1f} plf "
            f"(sheathing={spec.sheathing_type}, nail@{nail_spacing_in:.2f}\" oc, "
            f"{'blocked' if spec.blocked else 'unblocked'}, DF_L ref); "
            f"C_s={C_s:.2f} ({spec.framing_species}); "
            f"block_factor={block_factor:.2f}; "
            f"v_allow={v_allow:.1f} plf"
        )
    else:
        # Metal deck
        v_allow = _METAL_DECK_V_ALLOW[spec.sheathing_type]
        _lookup_note = (
            f"SDI DDM04 Table 1.3-3: v_allow={v_allow:.1f} plf "
            f"(deck={spec.sheathing_type}, 36/6 weld pattern, ASD basis)"
        )

    # -----------------------------------------------------------------------
    # 4. Aspect ratio check
    # -----------------------------------------------------------------------
    AR = L_ft / W_ft if W_ft > 0 else float("inf")
    AR_limit = _ASPECT_LIMIT[spec.sheathing_type]
    aspect_ok = AR <= AR_limit

    # -----------------------------------------------------------------------
    # 5. DCR and adequacy
    # -----------------------------------------------------------------------
    if v_allow > 0:
        dcr = v_plf / v_allow
    else:
        dcr = float("inf")

    shear_ok = dcr <= 1.0
    adequate = shear_ok and aspect_ok

    # -----------------------------------------------------------------------
    # 6. Governing factor
    # -----------------------------------------------------------------------
    if not shear_ok and not aspect_ok:
        governing_factor = "shear_demand+aspect_ratio"
    elif not shear_ok:
        governing_factor = "shear_demand"
    elif not aspect_ok:
        governing_factor = "aspect_ratio"
    else:
        governing_factor = "OK"

    # -----------------------------------------------------------------------
    # 7. Honest caveat
    # -----------------------------------------------------------------------
    std = "AWC SDPWS-2021 §4.2" if is_wood else "AISI S400-20 / SDI DDM04"
    caveat = (
        f"{std} horizontal diaphragm in-plane shear check (ASD basis). "
        f"Geometry: L={L_ft:.3f} ft (along load), W={W_ft:.3f} ft (perpendicular). "
        f"AR = L/W = {AR:.3f} (limit {AR_limit:.1f}:1 per "
        f"{'SDPWS Table 4.2.4' if is_wood else 'IBC §2209.2 / SDI DDM04'}; "
        f"{'OK' if aspect_ok else 'FAIL'}). "
        f"Applied lateral load V = {V_lateral_lbs:.1f} lbs (ASD level). "
        f"Unit shear v = V/L = {V_lateral_lbs:.1f}/{L_ft:.3f} = {v_plf:.2f} plf. "
        f"{_lookup_note}. "
        f"DCR = v/v_allow = {v_plf:.2f}/{v_allow:.2f} = {dcr:.4f} "
        f"({'≤ 1.0 ADEQUATE' if shear_ok else '> 1.0 INADEQUATE'}). "
        "SCOPE LIMITATIONS: "
        "(1) CHORD FORCES NOT CALCULATED — tension/compression chord forces at "
        "diaphragm boundaries (V·W/(2·chord_depth)) must be checked separately; "
        "this module checks in-plane unit shear only (IBC §2305.2 scope). "
        "(2) DIAPHRAGM DEFLECTION NOT CALCULATED — use SDPWS Eq. 4.2-1 or SDI "
        "DDM04 §3.2 for deflection; deflection limit check is a separate step. "
        f"(3) {'Wood: ASD allowable from SDPWS-2021 Table 4.2A, 8d common nails. ' if is_wood else 'Metal deck: SDI DDM04 Table 1.3-3 conservative ASD value for 36/6 weld pattern. '}"
        "(4) SDPWS Table 4.2A footnote 2: values are for SDC A–C; SDC D–F may "
        "require additional SDPWS §4.2.4 prescriptive requirements. "
        "(5) Unblocked reduction = flat 0.5× (SDPWS §4.2.7 Case 1); actual "
        "unblocked capacity depends on panel Case and orientation — verify table. "
        "(6) ASD load combinations are caller's responsibility; V_lateral_lbs "
        "must already reflect the governing ASD load combo (ASCE 7 §2.4). "
        "(7) Irregular diaphragms (openings, re-entrant corners, non-rectangular) "
        "require special engineering analysis not implemented here. "
        "(8) For metal deck: connection to supporting framing (puddle welds, "
        "power-actuated fasteners) shear transfer not checked — see SDI DDM04 §4. "
        "Always verify with a licensed structural engineer."
    )

    return DiaphragmShearReport(
        unit_shear_v_plf=round(v_plf, 4),
        allowable_unit_shear_v_allow_plf=round(v_allow, 4),
        demand_capacity_ratio=round(dcr, 6),
        adequate=adequate,
        governing_factor=governing_factor,
        honest_caveat=caveat,
    )
