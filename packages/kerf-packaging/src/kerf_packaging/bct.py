"""
kerf_packaging.bct — Box Compression Test (BCT) estimator for corrugated cartons.

Implements the McKee formula (1963) and its refined variants commonly used in
the packaging industry to estimate the top-to-bottom compression strength of a
Regular Slotted Container (RSC) made from corrugated board.

References
----------
McKee, R.C., Gander, J.W., Wachuta, J.R. (1963).
    "Compression strength formula for corrugated boxes."
    Paperboard Packaging 48(8), pp. 149–159.

Maltenfort, G.G. (1956).
    "Compression strength of corrugated containers."
    Fibre Containers 41(10).

TAPPI T 801 cm-16: Compression test of fiberboard shipping containers.

Formulas
--------
McKee simplified (most common industry version):

    BCT = k · ECT · √(b · h)

where:
    ECT   = edge crush test of the board (N/m  or  lbf/in)
    b     = box perimeter (m  or  in)
    h     = box height (m  or  in)
    k     = empirical constant ≈ 5.876 (SI, N·m units) or 0.215 (US customary)

McKee full formula (more accurate for non-square cross-sections):

    BCT = k · ECT · (b/4)^α · h^β

where α ≈ 0.492, β ≈ 0.508 (empirical exponents, McKee 1963).

Dimensions
----------
All inputs in SI: mm for lengths, N/m for ECT.
Output BCT in Newtons.

Stacking model
--------------
For a stack of n identical boxes with a safety factor SF:

    max_stack_height = BCT · (1/SF - 1/(n·BCT/load_kg/g))

The simple stacking formula used here:

    n_boxes = floor(BCT / (SF · load_N))

where load_N = product_weight_kg × g, and SF is typically 2.0–4.0 for
warehouse storage depending on humidity and storage duration.

Public API
----------
``bct_mckee(ect_N_per_m, length_mm, width_mm, depth_mm, k, full_formula) -> BCTResult``
``stack_count(bct_N, load_kg, safety_factor) -> int``
``bct_to_dict(result) -> dict``
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# McKee simplified constant (SI: N·m^0.5 scale with ECT in N/m, dims in m)
_MCKEE_K_SIMPLE = 5.876

# McKee full-formula exponents
_MCKEE_ALPHA = 0.492   # perimeter exponent
_MCKEE_BETA  = 0.508   # height exponent
_MCKEE_K_FULL = 5.874  # empirical constant for full formula (SI)

# Gravity
_G = 9.80665  # m/s²

# Humidity correction factors (multiplicative derating)
_HUMIDITY_FACTORS = {
    "dry":   1.00,   # <50% RH — no correction
    "normal": 0.90,  # 50–65% RH — 10% derating
    "humid": 0.75,   # 65–80% RH — 25% derating (TAPPI guidance)
    "wet":   0.55,   # >80% RH — 45% derating (outdoor/refrigerated storage)
}

# Typical ECT values by board grade (N/m) — informational defaults
ECT_DEFAULTS = {
    "flute_b":  2800.0,   # single-wall B-flute, medium weight
    "flute_c":  3200.0,   # single-wall C-flute, medium weight
    "flute_bc": 4500.0,   # double-wall BC-flute
    "flute_e":  2200.0,   # E-flute (microflute), thin
    "sbs":      2000.0,   # solid bleached sulphate (folding carton — not corrugated)
    "crb":      1800.0,   # coated recycled board
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class BCTResult:
    """
    Result of a BCT estimation.

    Attributes
    ----------
    bct_N : float
        Estimated box compression strength in Newtons.
    bct_kgf : float
        Same value converted to kgf (1 kgf = 9.80665 N).
    formula : str
        Formula used: "mckee_simplified" or "mckee_full".
    inputs : dict
        Echo of all inputs for traceability.
    warnings : list[str]
        Engineering warnings (e.g., aspect ratio out of validated range).
    stacking : dict
        Stacking analysis if load_kg was supplied, else empty dict.
    """
    bct_N: float
    bct_kgf: float
    formula: str
    inputs: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    stacking: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def bct_mckee(
    ect_N_per_m: float,
    length_mm: float,
    width_mm: float,
    depth_mm: float,
    *,
    board_t_mm: float = 4.5,
    k: Optional[float] = None,
    full_formula: bool = False,
    humidity: str = "normal",
    load_kg: Optional[float] = None,
    safety_factor: float = 3.0,
) -> BCTResult:
    """
    Estimate box compression strength (BCT) using the McKee formula.

    Parameters
    ----------
    ect_N_per_m : float
        Edge Crush Test value of the corrugated board (N/m).
        Typical values: B-flute ≈ 2800, C-flute ≈ 3200, BC ≈ 4500 N/m.
    length_mm : float
        Internal box length (mm).
    width_mm : float
        Internal box width (mm).
    depth_mm : float
        Box height (mm) — the dimension under compression.
    board_t_mm : float
        Board caliper / thickness (mm).  Used in the perimeter correction.
        Typical: B-flute ≈ 3.0, C-flute ≈ 4.5, BC ≈ 7.0 mm.
    k : float or None
        Override the McKee constant.  If None, uses 5.876 (simplified) or
        5.874 (full formula).
    full_formula : bool
        If True, use the full McKee formula with empirical exponents α and β.
        If False (default), use the simplified square-root formula.
    humidity : str
        Storage humidity condition: "dry" | "normal" | "humid" | "wet".
        Applies a multiplicative derating factor to the BCT estimate.
    load_kg : float or None
        Product weight in kg for stacking analysis.  If supplied, the result
        includes a stacking dict with maximum stack height and box count.
    safety_factor : float
        Safety factor for stacking (default 3.0).  Typical warehouse values:
        2.0 (short-term dry), 3.0 (medium-term), 4.0 (long-term humid).

    Returns
    -------
    BCTResult

    Notes
    -----
    McKee simplified:   BCT = k · ECT · √(b · h)
    McKee full:         BCT = k · ECT · (b/4)^α · h^β

    Perimeter b = 2(L + W) + 4·board_t (external perimeter — McKee uses
    external box dimensions; internal dimensions are L, W here, so we add
    2·board_t to each dimension).

    The formula is validated for RSC corrugated boxes with:
        - Perimeter 0.4–2.5 m
        - Height 0.1–0.8 m
        - ECT 1500–6000 N/m

    Results outside these ranges generate warnings.
    """
    if ect_N_per_m <= 0:
        raise ValueError(f"ect_N_per_m must be positive, got {ect_N_per_m}")
    if length_mm <= 0 or width_mm <= 0 or depth_mm <= 0:
        raise ValueError("Box dimensions must be positive")
    if board_t_mm < 0:
        raise ValueError("board_t_mm must be non-negative")
    if humidity not in _HUMIDITY_FACTORS:
        raise ValueError(
            f"humidity must be one of {list(_HUMIDITY_FACTORS)}, got '{humidity}'"
        )
    if safety_factor <= 0:
        raise ValueError("safety_factor must be positive")

    warnings_out: list[str] = []

    # External dimensions (McKee uses external box dimensions)
    # For an RSC the external perimeter = 2*(L + board_t) + 2*(W + board_t)
    L_ext = length_mm + 2.0 * board_t_mm   # external length (mm)
    W_ext = width_mm  + 2.0 * board_t_mm   # external width  (mm)
    H_ext = depth_mm  + board_t_mm          # external height (board on base only for McKee)

    # Perimeter in metres
    perimeter_m = 2.0 * (L_ext + W_ext) / 1000.0
    height_m    = H_ext / 1000.0

    # Validation range checks
    if perimeter_m < 0.4 or perimeter_m > 2.5:
        warnings_out.append(
            f"Box perimeter {perimeter_m:.3f} m is outside McKee validated range "
            "[0.4, 2.5] m; BCT estimate may be less accurate."
        )
    if height_m < 0.1 or height_m > 0.8:
        warnings_out.append(
            f"Box height {height_m:.3f} m is outside McKee validated range "
            "[0.1, 0.8] m; BCT estimate may be less accurate."
        )
    if ect_N_per_m < 1500 or ect_N_per_m > 6000:
        warnings_out.append(
            f"ECT {ect_N_per_m:.0f} N/m is outside McKee validated range "
            "[1500, 6000] N/m."
        )

    # Choose formula
    if full_formula:
        _k = k if k is not None else _MCKEE_K_FULL
        bct_raw = _k * ect_N_per_m * ((perimeter_m / 4.0) ** _MCKEE_ALPHA) * (height_m ** _MCKEE_BETA)
        formula_name = "mckee_full"
    else:
        _k = k if k is not None else _MCKEE_K_SIMPLE
        bct_raw = _k * ect_N_per_m * math.sqrt(perimeter_m * height_m)
        formula_name = "mckee_simplified"

    # Apply humidity derating
    humidity_factor = _HUMIDITY_FACTORS[humidity]
    bct_corrected = bct_raw * humidity_factor

    if humidity != "dry":
        warnings_out.append(
            f"Humidity correction applied: {humidity} → ×{humidity_factor} "
            f"(BCT derated from {bct_raw:.0f} N to {bct_corrected:.0f} N)."
        )

    bct_kgf = bct_corrected / _G

    # Stacking analysis
    stacking: dict = {}
    if load_kg is not None and load_kg > 0:
        load_N = load_kg * _G
        # Maximum number of boxes that can be stacked (BCT / (SF * load_per_box))
        # The bottom box carries all boxes above it.
        # BCT ≥ SF * (n-1) * load_N  →  n ≤ 1 + BCT/(SF * load_N)
        max_stack = int(1 + bct_corrected / (safety_factor * load_N))
        if max_stack < 1:
            max_stack = 1
        # Maximum pallet stack height
        box_height_m = depth_mm / 1000.0
        max_height_m = max_stack * box_height_m

        stacking = {
            "load_kg":          load_kg,
            "load_N":           round(load_N, 2),
            "safety_factor":    safety_factor,
            "max_boxes_stacked": max_stack,
            "max_stack_height_m": round(max_height_m, 3),
            "method": "BCT / (SF × load_N) + 1 (bottom box excluded from load)",
        }

    inputs_echo = {
        "ect_N_per_m":    ect_N_per_m,
        "length_mm":      length_mm,
        "width_mm":       width_mm,
        "depth_mm":       depth_mm,
        "board_t_mm":     board_t_mm,
        "perimeter_m":    round(perimeter_m, 4),
        "height_m":       round(height_m, 4),
        "k":              _k,
        "humidity":       humidity,
        "humidity_factor": humidity_factor,
        "full_formula":   full_formula,
    }

    return BCTResult(
        bct_N=round(bct_corrected, 1),
        bct_kgf=round(bct_kgf, 2),
        formula=formula_name,
        inputs=inputs_echo,
        warnings=warnings_out,
        stacking=stacking,
    )


def stack_count(bct_N: float, load_kg: float, safety_factor: float = 3.0) -> int:
    """
    Return the maximum number of boxes that can be safely stacked.

    Parameters
    ----------
    bct_N : float
        Estimated box BCT in Newtons.
    load_kg : float
        Weight of contents per box (kg).
    safety_factor : float
        Warehouse safety factor (default 3.0).

    Returns
    -------
    int
        Maximum stack count (minimum 1).
    """
    if load_kg <= 0:
        return 1
    load_N = load_kg * _G
    n = int(1 + bct_N / (safety_factor * load_N))
    return max(1, n)


def bct_to_dict(result: BCTResult) -> dict:
    """Serialise a BCTResult to a plain JSON-safe dict."""
    return {
        "bct_N":     result.bct_N,
        "bct_kgf":   result.bct_kgf,
        "formula":   result.formula,
        "inputs":    result.inputs,
        "warnings":  result.warnings,
        "stacking":  result.stacking,
    }
