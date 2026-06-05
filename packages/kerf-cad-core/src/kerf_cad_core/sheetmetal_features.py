"""
kerf-cad-core: GK-P17 — Sheet-metal features: parametric flanges, bends,
hem, jog, multi-flange, and unfold-to-flat-pattern.

Implements:
  - ``SheetMetalPart``              — dataclass describing a multi-bend blank
  - ``FlatPatternResult``           — dataclass returned by ``compute_flat_pattern``
  - ``compute_flat_pattern(part)``  — K-factor + bend-allowance + flat-pattern
  - ``HemSpec``                     — hem (flange folded back on itself)
  - ``HemResult``                   — returned by ``compute_hem_geometry``
  - ``compute_hem_geometry(spec)``  — open/closed/teardrop/rolled hem unfold
  - ``JogSpec``                     — jog (Z-offset, two opposing bends)
  - ``JogResult``                   — returned by ``compute_jog_geometry``
  - ``compute_jog_geometry(spec)``  — two-bend jog flat-length calculation
  - ``FlangeSpec``                  — single-flange descriptor for multi-flange
  - ``MultiFlangeSpec``             — sequence of N flanges
  - ``MultiFlangeResult``           — returned by ``compute_multi_flange_geometry``
  - ``compute_multi_flange_geometry(spec)`` — chained N-bend flat development

Formula reference
-----------------
Suchy "Handbook of Die Design" §3 + DIN 6935:
    K-factor (neutral-axis offset fraction, 0 < K < 1):
        r/t < 1   → K = 0.33   (severe bend — hard materials)
        r/t ≥ 3   → K = 0.44   (gentle bend — soft / typical mild steel)
        1 ≤ r/t < 3 → linear interpolation between 0.33 and 0.44

    Bend allowance (arc length of neutral axis through the bend):
        BA = (π · angle_deg / 180) · (r + K · t)

    Outside set-back (OSSB) per ANSI Y14.5M / DIN 6935:
        OSSB = (r + t) · tan(angle_deg / 2)

    Bend deduction (material removed from flat length by the bend):
        BD = 2 · OSSB − BA

    Flat length for each straight segment:
        flat_length = Σ flange_lengths − Σ BD
                    = Σ flange_lengths − Σ(2·OSSB − BA)

    NOTE: ``flange_lengths_mm`` in ``SheetMetalPart`` covers EVERY straight
    segment including the base panel; the bend count = len(flange_lengths) − 1.
    If only one flange length is provided the part has zero bends and the flat
    length equals that single panel length.

Material K-factor table
-----------------------
Material strings are normalised (lower, strip, replace spaces with dashes).
The lookup drives the linear interpolation bounds:

    "steel-cold-rolled"  K_min=0.33, K_max=0.44
    "stainless-304"      K_min=0.31, K_max=0.38
    "aluminum-5052"      K_min=0.40, K_max=0.50
    "copper"             K_min=0.40, K_max=0.50

Honest caveats
--------------
1. K-factor lookup is **empirical** (tabulated interpolation, DIN 6935).
   Measured press-brake data should be used when available.
2. Bend-deduction formula assumes **inside-set** bend geometry and air-bend
   process.  Bottoming and coining shift the neutral axis; use
   ``sheet_metal_bend_table.py`` for process-specific corrections.
3. **Spring-back not modelled.**  Apply process-specific overbend to
   compensate (typically 1–3° for mild steel; see DIN 6935 §4).
4. Multi-bend parts assume sequential, independent bends on a single blank.
   Interaction between closely-spaced bends (< 4×t apart) is not captured.
5. ``flat_width_mm`` is passed through unchanged; the module does NOT model
   notching, lancing, or width changes from corner reliefs.

LLM tools: ``sheetmetal_compute_flat_pattern``, ``sheetmetal_compute_hem``,
    ``sheetmetal_compute_jog``, ``sheetmetal_compute_multi_flange``
    Gated import of ``kerf_chat.tools.registry`` so the module loads cleanly
    in pure-Python test environments that lack the chat-server runtime.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List

# ---------------------------------------------------------------------------
# Material K-factor table
# ---------------------------------------------------------------------------

# (K_min, K_max) — both are DIN 6935 / Suchy §3 values
_MATERIAL_K: dict[str, tuple[float, float]] = {
    "steel-cold-rolled": (0.33, 0.44),
    "stainless-304":     (0.31, 0.38),
    "aluminum-5052":     (0.40, 0.50),
    "copper":            (0.40, 0.50),
}

# Normalised aliases
_MATERIAL_ALIASES: dict[str, str] = {
    "steel":             "steel-cold-rolled",
    "cold-rolled-steel": "steel-cold-rolled",
    "crs":               "steel-cold-rolled",
    "mild-steel":        "steel-cold-rolled",
    "stainless":         "stainless-304",
    "ss304":             "stainless-304",
    "304":               "stainless-304",
    "stainless-steel":   "stainless-304",
    "aluminum":          "aluminum-5052",
    "aluminium":         "aluminum-5052",
    "al5052":            "aluminum-5052",
    "5052":              "aluminum-5052",
    "aluminium-5052":    "aluminum-5052",
    "cu":                "copper",
}


def _resolve_material(material: str) -> str | None:
    """Return canonical material key or ``None`` if unrecognised."""
    key = material.strip().lower().replace(" ", "-")
    if key in _MATERIAL_K:
        return key
    return _MATERIAL_ALIASES.get(key)


def _k_factor_from_r_over_t(r_over_t: float, k_min: float, k_max: float) -> float:
    """
    Linear K-factor interpolation per DIN 6935 / Suchy §3:

    r/t < 1           → K = k_min   (severe / hard bend)
    1 ≤ r/t < 3       → K = linear interp from k_min to k_max
    r/t ≥ 3           → K = k_max   (gentle / soft bend)
    """
    if r_over_t < 1.0:
        return k_min
    if r_over_t >= 3.0:
        return k_max
    t = (r_over_t - 1.0) / 2.0          # 0..1 within the [1, 3) band
    return k_min + t * (k_max - k_min)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SheetMetalPart:
    """
    Describes a single-material sheet-metal blank with one or more bends.

    Parameters
    ----------
    material : str
        Material identifier.  Accepted (case-insensitive, spaces → dashes):
        "steel-cold-rolled", "stainless-304", "aluminum-5052", "copper".
        Common aliases are resolved automatically.
    thickness_mm : float
        Sheet thickness in mm.  Must be > 0.
    length_mm : float
        Overall folded length of the part in the bend direction (mm).
        For a single L-bracket this is the base-plate length.  For the flat
        pattern calculation this value is **not** used directly — the flat
        length is derived from ``flange_lengths_mm``.  Stored for reference.
    width_mm : float
        Width of the blank perpendicular to the bend lines (mm).  Passed
        through to ``FlatPatternResult.flat_width_mm`` unchanged.
    bend_radius_mm : float
        Inside bend radius applied to **every** bend in the part (mm).
        Must be > 0.  For parts with varying radii, use ``compute_flat_pattern``
        directly with per-bend overrides (not yet exposed in this dataclass).
    bend_angle_deg : float
        Bend angle applied to **every** bend in the part (degrees, 0 < θ ≤ 180).
        90° is a right-angle flange; 180° is a hem fold.
    flange_lengths_mm : list[float]
        Ordered list of straight-segment lengths (mm), one entry per panel
        (including the base).  For an L-bracket: ``[base_mm, flange_mm]``.
        For a U-channel: ``[side_mm, base_mm, side_mm]``.
        Number of bends = len(flange_lengths_mm) − 1.
        All values must be > 0.
    """
    material: str
    thickness_mm: float
    length_mm: float
    width_mm: float
    bend_radius_mm: float
    bend_angle_deg: float
    flange_lengths_mm: List[float] = field(default_factory=list)


@dataclass
class FlatPatternResult:
    """
    Result returned by ``compute_flat_pattern``.

    Attributes
    ----------
    flat_length_mm : float
        Developed flat length in the bend direction (mm).
        flat_length = Σ(flange_lengths) − Σ(BD) where BD = 2·OSSB − BA.
    flat_width_mm : float
        Flat width (mm) — passed through from ``SheetMetalPart.width_mm``.
    bend_allowances_mm : list[float]
        Per-bend arc length of the neutral axis (mm).
    k_factor : float
        Effective K-factor used (same for every bend; derived from r/t and
        material).
    total_bend_deduction_mm : float
        Sum of all bend deductions (Σ BD, mm).
    num_bends : int
        Number of bends = len(flange_lengths_mm) − 1.
    honest_caveat : str
        Human-readable caveat explaining limitations of this calculation.
    """
    flat_length_mm: float
    flat_width_mm: float
    bend_allowances_mm: List[float]
    k_factor: float
    total_bend_deduction_mm: float
    num_bends: int
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "K-factor lookup is empirical (DIN 6935 r/t interpolation); measured "
    "press-brake data should be used when available. "
    "Bend-deduction formula assumes inside-set air-bend geometry; bottoming / "
    "coining process shifts the neutral axis (see sheet_metal_bend_table.py). "
    "Spring-back is NOT modelled — apply overbend to compensate (typically "
    "1–3° for mild steel per DIN 6935 §4). "
    "Multi-bend interaction for closely-spaced bends (< 4×t apart) is not "
    "captured. flat_width_mm is passed through unchanged (no notch / relief "
    "geometry modelled)."
)


def compute_flat_pattern(part: SheetMetalPart) -> FlatPatternResult:
    """
    Compute the flat-pattern dimensions for a multi-bend sheet-metal blank.

    Parameters
    ----------
    part : SheetMetalPart
        Fully populated part dataclass.

    Returns
    -------
    FlatPatternResult

    Raises
    ------
    ValueError
        On invalid inputs (unknown material, non-positive dimensions,
        bend angle out of range, empty flange list).

    Notes
    -----
    Formula (DIN 6935 / Suchy §3 / ANSI Y14.5M):
        BA   = (π · θ / 180) · (r + K · t)
        OSSB = (r + t) · tan(θ / 2)
        BD   = 2·OSSB − BA
        flat_length = Σ flange_lengths − Σ BD
    """
    # --- Input validation ---
    mat_key = _resolve_material(part.material)
    if mat_key is None:
        known = sorted(_MATERIAL_K)
        raise ValueError(
            f"Unknown material '{part.material}'. "
            f"Known: {known}. "
            f"Aliases also accepted (e.g. 'steel', 'stainless', 'aluminum', 'copper')."
        )

    t = float(part.thickness_mm)
    if t <= 0:
        raise ValueError(f"thickness_mm must be > 0; got {t}")

    r = float(part.bend_radius_mm)
    if r <= 0:
        raise ValueError(f"bend_radius_mm must be > 0; got {r}")

    angle = float(part.bend_angle_deg)
    if angle <= 0 or angle > 180:
        raise ValueError(f"bend_angle_deg must be in (0, 180]; got {angle}")

    w = float(part.width_mm)
    if w <= 0:
        raise ValueError(f"width_mm must be > 0; got {w}")

    flanges = [float(f) for f in part.flange_lengths_mm]
    if len(flanges) == 0:
        raise ValueError("flange_lengths_mm must not be empty")
    for i, f in enumerate(flanges):
        if f <= 0:
            raise ValueError(f"flange_lengths_mm[{i}] must be > 0; got {f}")

    # --- K-factor ---
    k_min, k_max = _MATERIAL_K[mat_key]
    r_over_t = r / t
    k = _k_factor_from_r_over_t(r_over_t, k_min, k_max)

    # --- Per-bend BA and BD ---
    num_bends = len(flanges) - 1
    angle_rad = math.radians(angle)
    half_rad = math.radians(angle / 2.0)

    bend_allowances: list[float] = []
    bend_deductions: list[float] = []

    for _ in range(num_bends):
        ba = angle_rad * (r + k * t)
        ossb = (r + t) * math.tan(half_rad)
        bd = 2.0 * ossb - ba
        bend_allowances.append(round(ba, 6))
        bend_deductions.append(round(bd, 6))

    total_bd = sum(bend_deductions)
    flat_length = sum(flanges) - total_bd

    return FlatPatternResult(
        flat_length_mm=round(flat_length, 6),
        flat_width_mm=round(w, 6),
        bend_allowances_mm=bend_allowances,
        k_factor=round(k, 6),
        total_bend_deduction_mm=round(total_bd, 6),
        num_bends=num_bends,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# Hem dataclasses + computation
# ---------------------------------------------------------------------------

@dataclass
class HemSpec:
    """
    Describes a hem — a flange folded back onto itself along its free edge.

    Parameters
    ----------
    hem_type : str
        One of: ``"open"``, ``"closed"``, ``"teardrop"``, ``"rolled"``.

        * ``open``      — the hem leaves a gap equal to ``sheet_thickness_mm``
                          (Suchy §6.1, DIN 6935 §4.3 Type A).
        * ``closed``    — the hem presses flat (gap ≈ 0); tightest form.
        * ``teardrop``  — the folded edge forms a teardrop profile; radius
                          controlled by ``hem_radius_mm`` (Suchy §6.3).
        * ``rolled``    — a full-circle roll; the hem radius equals ≥ t/2
                          (Suchy §6.4).

    hem_radius_mm : float
        Inside radius of the hem fold (mm).  Must be ≥ 0.  Ignored for
        ``"closed"`` (treated as 0).  For ``"open"`` the effective radius is
        ``max(hem_radius_mm, sheet_thickness_mm / 2)``.
    hem_length_mm : float
        Leg length of the hem measured from the bend tangent point to the
        free edge (mm).  Must be > 0.
    sheet_thickness_mm : float
        Sheet thickness (mm).  Must be > 0.
    k_factor : float
        Neutral-axis offset fraction (0 < k < 1, default 0.4).
        Used for the 180° hem fold bend-allowance calculation per Suchy §6:
        BA_hem = π · (r + k · t).
    """
    hem_type: str
    hem_radius_mm: float
    hem_length_mm: float
    sheet_thickness_mm: float
    k_factor: float = 0.4


@dataclass
class HemResult:
    """
    Result returned by ``compute_hem_geometry``.

    Attributes
    ----------
    developed_length_mm : float
        Total flat blank length consumed by the hem (hem arc + leg), mm.
    flat_pattern_segments : list[dict]
        Ordered segments that make up the hem flat pattern.
        Each dict has ``{"type": "straight"|"bend", "length_mm": float}``.
    bend_allowance_mm : float
        Arc length of the neutral axis through the 180° fold, mm.
    gap_mm : float
        Resulting air gap between the two sheet surfaces after folding (mm).
        0.0 for ``"closed"``, ``sheet_thickness_mm`` for ``"open"``,
        ``2·hem_radius_mm + sheet_thickness_mm`` for ``"teardrop"``.
    honest_caveat : str
        Human-readable caveats about model limitations.
    """
    developed_length_mm: float
    flat_pattern_segments: List[dict]
    bend_allowance_mm: float
    gap_mm: float
    honest_caveat: str


_HEM_CAVEAT = (
    "Hem developed-length formula from Suchy 'Handbook of Die Design' §6 + DIN 6935 §4.3. "
    "BA_hem = π·(r + K·t) assumes 180° fold neutral-axis arc. "
    "K-factor default 0.4 is an empirical midpoint; measured press-brake data is preferred. "
    "Spring-back NOT modelled (hem tooling typically bottoms the fold). "
    "Closed hem gap is nominally 0 but in practice ≈0.1–0.3 mm due to spring-back "
    "unless coined. Rolled hem assumes r ≥ t/2; thicker stock requires a roller die. "
    "No corner-relief geometry is modelled."
)

# Minimum gap per Suchy §6.1: open hem gap = sheet_thickness
_HEM_OPEN_GAP_FACTOR = 1.0          # gap = 1 × t


def compute_hem_geometry(spec: HemSpec) -> HemResult:
    """
    Compute the flat-pattern developed length for a sheet-metal hem.

    Parameters
    ----------
    spec : HemSpec

    Returns
    -------
    HemResult

    Raises
    ------
    ValueError
        On invalid inputs or unrecognised hem_type.

    Notes
    -----
    Hem types and geometry (Suchy §6):
    ┌──────────┬────────────────────────────────────────────────────┐
    │ Type     │ Description                                        │
    ├──────────┼────────────────────────────────────────────────────┤
    │ open     │ gap = t; fold radius ≥ t/2                         │
    │ closed   │ gap = 0; radius → 0 (press flat)                   │
    │ teardrop │ gap = 2r + t; distinct teardrop profile            │
    │ rolled   │ full-circle roll; r ≥ t/2                          │
    └──────────┴────────────────────────────────────────────────────┘

    BA_hem = π · (r_effective + K · t)    (180° neutral-axis arc)
    developed_length = hem_length + BA_hem
    """
    valid_types = {"open", "closed", "teardrop", "rolled"}
    if spec.hem_type not in valid_types:
        raise ValueError(
            f"hem_type must be one of {sorted(valid_types)}; got '{spec.hem_type}'"
        )
    t = float(spec.sheet_thickness_mm)
    if t <= 0:
        raise ValueError(f"sheet_thickness_mm must be > 0; got {t}")
    hem_len = float(spec.hem_length_mm)
    if hem_len <= 0:
        raise ValueError(f"hem_length_mm must be > 0; got {hem_len}")
    r_input = float(spec.hem_radius_mm)
    if r_input < 0:
        raise ValueError(f"hem_radius_mm must be ≥ 0; got {r_input}")
    k = float(spec.k_factor)
    if not (0 < k < 1):
        raise ValueError(f"k_factor must be in (0, 1); got {k}")

    if spec.hem_type == "closed":
        # Closed hem: press flat — radius → 0, gap = 0
        r_eff = 0.0
        gap_mm = 0.0
    elif spec.hem_type == "open":
        # Open hem: gap = t; effective radius ≥ t/2 per DIN 6935
        r_eff = max(r_input, t / 2.0)
        gap_mm = _HEM_OPEN_GAP_FACTOR * t
    elif spec.hem_type == "teardrop":
        # Teardrop: user controls the radius; gap = 2r + t
        r_eff = r_input if r_input > 0 else t / 2.0
        gap_mm = 2.0 * r_eff + t
    else:  # rolled
        # Rolled (full circle): r ≥ t/2 mandatory
        r_eff = max(r_input, t / 2.0)
        gap_mm = 2.0 * r_eff + t  # the rolled tube OD minus sheet face

    # BA = π · (r_eff + K · t)  — 180° fold
    ba = math.pi * (r_eff + k * t)

    # Total developed length: straight leg + bend arc
    dev_len = hem_len + ba

    segments = [
        {"type": "straight", "length_mm": round(hem_len, 6)},
        {"type": "bend",     "length_mm": round(ba, 6)},
    ]

    return HemResult(
        developed_length_mm=round(dev_len, 6),
        flat_pattern_segments=segments,
        bend_allowance_mm=round(ba, 6),
        gap_mm=round(gap_mm, 6),
        honest_caveat=_HEM_CAVEAT,
    )


# ---------------------------------------------------------------------------
# Jog dataclasses + computation
# ---------------------------------------------------------------------------

@dataclass
class JogSpec:
    """
    Describes a jog (Z-offset feature) — two opposing bends placed close
    together so that one panel is shifted parallel to, but offset from, the
    original panel.

    Parameters
    ----------
    jog_height_mm : float
        Desired Z-offset (offset between the two parallel planes) in mm.
        Must be > 0.
    jog_length_mm : float
        Horizontal distance between the two bend tangent points (mm).
        Also called the "jog land" or "step length".  Must be > 0.
    sheet_thickness_mm : float
        Sheet thickness (mm).  Must be > 0.
    bend_radius_mm : float
        Inside bend radius applied to both bends (mm).  Must be > 0.
    k_factor : float
        K-factor (default 0.4).  Applied to both bends symmetrically.
    """
    jog_height_mm: float
    jog_length_mm: float
    sheet_thickness_mm: float
    bend_radius_mm: float
    k_factor: float = 0.4


@dataclass
class JogResult:
    """
    Result returned by ``compute_jog_geometry``.

    Attributes
    ----------
    flat_developed_length : float
        Total flat length consumed by the jog (2 × BA + jog_land), mm.
    bend_count : int
        Always 2 for a single jog.
    bend_allowances_mm : list[float]
        [BA_first_bend, BA_second_bend].  Both are identical for a symmetric
        jog.
    jog_angle_deg : float
        Actual bend angle (°) of each bend, derived from the geometry:
        θ = arctan(jog_height / jog_length).
    honest_caveat : str
        Human-readable caveats.
    """
    flat_developed_length: float
    bend_count: int
    bend_allowances_mm: List[float]
    jog_angle_deg: float
    honest_caveat: str


_JOG_CAVEAT = (
    "Jog geometry per Suchy 'Handbook of Die Design' §4.5 + DIN 6935 §4. "
    "Bend angle θ = arctan(h / L) where h = jog_height_mm, L = jog_length_mm. "
    "Both bends assumed identical (symmetric jog). "
    "BA = (π·θ/180)·(r + K·t) per DIN 6935. "
    "K-factor default 0.4 is empirical; measured press-brake data preferred. "
    "Minimum jog land L ≥ 4t recommended (DIN 6935 §4) to avoid "
    "bend-interaction effects — not enforced here. "
    "Spring-back NOT modelled."
)


def compute_jog_geometry(spec: JogSpec) -> JogResult:
    """
    Compute the flat-pattern developed length for a sheet-metal jog.

    Parameters
    ----------
    spec : JogSpec

    Returns
    -------
    JogResult

    Raises
    ------
    ValueError
        On invalid inputs.

    Notes
    -----
    Jog geometry (Suchy §4.5 / DIN 6935):
        θ   = arctan(jog_height / jog_length)   [bend angle of each opposing bend]
        BA  = (π·θ/180) · (r + K·t)
        flat_developed_length = jog_length + 2·BA
    """
    h = float(spec.jog_height_mm)
    if h <= 0:
        raise ValueError(f"jog_height_mm must be > 0; got {h}")
    L = float(spec.jog_length_mm)
    if L <= 0:
        raise ValueError(f"jog_length_mm must be > 0; got {L}")
    t = float(spec.sheet_thickness_mm)
    if t <= 0:
        raise ValueError(f"sheet_thickness_mm must be > 0; got {t}")
    r = float(spec.bend_radius_mm)
    if r <= 0:
        raise ValueError(f"bend_radius_mm must be > 0; got {r}")
    k = float(spec.k_factor)
    if not (0 < k < 1):
        raise ValueError(f"k_factor must be in (0, 1); got {k}")

    # Bend angle from jog geometry
    theta_rad = math.atan2(h, L)
    theta_deg = math.degrees(theta_rad)

    # Bend allowance — same formula as flat pattern
    ba = theta_rad * (r + k * t)

    # Two opposing bends + the jog land
    flat_len = L + 2.0 * ba

    return JogResult(
        flat_developed_length=round(flat_len, 6),
        bend_count=2,
        bend_allowances_mm=[round(ba, 6), round(ba, 6)],
        jog_angle_deg=round(theta_deg, 6),
        honest_caveat=_JOG_CAVEAT,
    )


# ---------------------------------------------------------------------------
# Multi-flange dataclasses + computation
# ---------------------------------------------------------------------------

@dataclass
class FlangeSpec:
    """
    Describes one flange segment in a multi-flange chain.

    Parameters
    ----------
    length_mm : float
        Straight-segment length of this flange (mm).  Must be > 0.
    angle_deg : float
        Bend angle at the trailing edge of this segment (degrees, 0–180].
        The bend follows *this* flange — the first flange has no leading bend.
    radius_mm : float
        Inside bend radius at the trailing edge (mm).  Must be > 0.
    k_factor : float
        K-factor for this bend (default 0.4).
    thickness_mm : float
        Sheet thickness for this bend (mm, default 1.0).
        Used in BA = angle_rad * (r + K * t).
    """
    length_mm: float
    angle_deg: float
    radius_mm: float
    k_factor: float = 0.4
    thickness_mm: float = 1.0


@dataclass
class MultiFlangeSpec:
    """
    Describes a chain of N straight-segment flanges joined by N−1 bends.

    Parameters
    ----------
    flanges : list[FlangeSpec]
        Ordered list of flange segments.  The bend after segment i uses
        segment i's ``angle_deg``, ``radius_mm``, and ``k_factor``.  The
        *last* flange's ``angle_deg`` and ``radius_mm`` are ignored (no
        trailing bend on the final segment).
        Length ≥ 1 required; a single entry produces a zero-bend flat blank.
    """
    flanges: List[FlangeSpec]


@dataclass
class MultiFlangeResult:
    """
    Result returned by ``compute_multi_flange_geometry``.

    Attributes
    ----------
    total_flat_length_mm : float
        Σ(flange lengths) − Σ(bend deductions), mm.
    bend_allowances_mm : list[float]
        Per-bend BA values (length = num_bends = len(flanges) − 1).
    total_bend_deduction_mm : float
        Σ BD = Σ(2·OSSB − BA) across all bends, mm.
    num_bends : int
        Number of bends = len(flanges) − 1.
    honest_caveat : str
        Human-readable caveats.
    """
    total_flat_length_mm: float
    bend_allowances_mm: List[float]
    total_bend_deduction_mm: float
    num_bends: int
    honest_caveat: str


_MULTI_FLANGE_CAVEAT = (
    "Multi-flange flat-development per Suchy 'Handbook of Die Design' §3 + DIN 6935. "
    "Each bend uses its own angle, radius, and K-factor independently. "
    "BA = (π·θ/180)·(r + K·t); OSSB = (r+t)·tan(θ/2); BD = 2·OSSB − BA. "
    "flat_length = Σflange_lengths − ΣBD. "
    "K-factor defaults 0.4 are empirical; measured press-brake data preferred. "
    "Spring-back NOT modelled. "
    "Bend-interaction for closely-spaced bends (< 4·t apart) is not captured. "
    "No corner-relief or notch geometry modelled."
)


def compute_multi_flange_geometry(spec: MultiFlangeSpec) -> MultiFlangeResult:
    """
    Compute the flat-pattern developed length for a multi-flange chain.

    Parameters
    ----------
    spec : MultiFlangeSpec

    Returns
    -------
    MultiFlangeResult

    Raises
    ------
    ValueError
        On invalid inputs (empty flanges, non-positive dimensions, angle
        out of range, invalid K-factor).

    Notes
    -----
    Formula (DIN 6935 / Suchy §3 — same as ``compute_flat_pattern`` but
    per-bend geometry is specified per flange rather than uniform):

        For each bend i (0 ≤ i < N−1):
            BA_i   = (π·θ_i/180) · (r_i + K_i·t_i)
            OSSB_i = (r_i + t_i) · tan(θ_i/2)
            BD_i   = 2·OSSB_i − BA_i

        flat_length = Σ(flange lengths) − Σ(BD_i)

    Each FlangeSpec carries its own ``thickness_mm`` (default 1.0 mm when
    omitted).  The function raises ``ValueError`` if any ``radius_mm <= 0``,
    ``angle_deg`` is out of range, ``thickness_mm <= 0``, or ``k_factor``
    is outside (0, 1).
    """
    flanges = list(spec.flanges)
    if len(flanges) == 0:
        raise ValueError("MultiFlangeSpec.flanges must not be empty")

    # Validate all flanges
    for i, fs in enumerate(flanges):
        if float(fs.length_mm) <= 0:
            raise ValueError(
                f"flanges[{i}].length_mm must be > 0; got {fs.length_mm}"
            )

    num_bends = len(flanges) - 1
    bend_allowances: list[float] = []
    bend_deductions: list[float] = []

    for i in range(num_bends):
        fs = flanges[i]
        angle = float(fs.angle_deg)
        if angle <= 0 or angle > 180:
            raise ValueError(
                f"flanges[{i}].angle_deg must be in (0, 180]; got {angle}"
            )
        r = float(fs.radius_mm)
        if r <= 0:
            raise ValueError(
                f"flanges[{i}].radius_mm must be > 0; got {r}"
            )
        k = float(fs.k_factor)
        if not (0 < k < 1):
            raise ValueError(
                f"flanges[{i}].k_factor must be in (0, 1); got {k}"
            )

        t = float(fs.thickness_mm)
        if t <= 0:
            raise ValueError(
                f"flanges[{i}].thickness_mm must be > 0; got {t}"
            )

        angle_rad = math.radians(angle)
        half_rad = math.radians(angle / 2.0)

        ba = angle_rad * (r + k * t)
        ossb = (r + t) * math.tan(half_rad)
        bd = 2.0 * ossb - ba

        bend_allowances.append(round(ba, 6))
        bend_deductions.append(round(bd, 6))

    total_bd = sum(bend_deductions)
    total_fl = sum(float(fs.length_mm) for fs in flanges)
    flat_len = total_fl - total_bd

    return MultiFlangeResult(
        total_flat_length_mm=round(flat_len, 6),
        bend_allowances_mm=bend_allowances,
        total_bend_deduction_mm=round(total_bd, 6),
        num_bends=num_bends,
        honest_caveat=_MULTI_FLANGE_CAVEAT,
    )


# ---------------------------------------------------------------------------
# auto_corner_relief  (GK-SM1) — corner-relief cut geometry
# ---------------------------------------------------------------------------
#
# Sheet-metal corners where two bend lines meet require a *corner relief* cut
# to prevent material tearing and stress concentration during bending.
# Three standard relief types are defined in Suchy "Handbook of Die Design"
# §7 and DIN 6935 §6:
#
#   "square"    — rectangular notch; width = r + t/2, depth = t/2 (Suchy §7.1)
#   "round"     — circular punch; radius ≥ t/2 (minimum notch rule, DIN 6935)
#   "lance"     — lance-and-form partial cut leaving a small tab
#                 (Suchy §7.3 — primarily for thin-gauge aluminium)
#
# The function returns the 2-D geometry (outline vertices in the flat-blank
# coordinate system) and a dimensional summary suitable for press tooling.
#
# Reference
# ---------
# Suchy "Handbook of Die Design" 2nd ed. §7, DIN 6935:2006-10 §6.
# Rule of thumb: relief depth ≥ bend radius + t / 2 to clear the bend zone.


@dataclass
class CornerReliefSpec:
    """
    Describes a single sheet-metal corner-relief cut.

    Parameters
    ----------
    relief_type : str
        One of: ``"square"``, ``"round"``, ``"lance"``.
    bend_radius_mm : float
        Inside bend radius (mm) at the corner.  Must be > 0.
    thickness_mm : float
        Sheet thickness (mm).  Must be > 0.
    bend_angle_deg : float
        Bend angle in degrees (default 90).  Used to scale the relief for
        obtuse bends (> 90°) or acute bends (< 90°).
    """
    relief_type: str
    bend_radius_mm: float
    thickness_mm: float
    bend_angle_deg: float = 90.0


@dataclass
class CornerReliefResult:
    """
    Result returned by ``compute_corner_relief``.

    Attributes
    ----------
    relief_type : str
    relief_width_mm : float
        Width of the relief cut perpendicular to the bend line (mm).
    relief_depth_mm : float
        Depth of the relief cut along the bend line (mm).
    min_punch_radius_mm : float
        Minimum recommended punch/tool radius (mm) to avoid tearing.
        Equals t/2 for square and lance; equals the relief radius for round.
    outline_xy : list[tuple[float, float]]
        2-D vertices of the relief outline in the flat-blank coordinate frame.
        Origin (0,0) is at the bend-line intersection; X points along one
        flange; Y points along the other.
    honest_caveat : str
    """
    relief_type: str
    relief_width_mm: float
    relief_depth_mm: float
    min_punch_radius_mm: float
    outline_xy: List[tuple]
    honest_caveat: str


_RELIEF_CAVEAT = (
    "Corner-relief geometry from Suchy 'Handbook of Die Design' §7 + DIN 6935 §6. "
    "Dimensions are minimum recommendations; actual tool size must account for material "
    "springback, press-brake accuracy, and DFM clearances (Boothroyd-Dewhurst §4). "
    "Lance relief is for thin-gauge aluminium only (< 1.2 mm); use square or round for steel. "
    "Relief depth rule: depth ≥ r + t/2 to clear the bend tangent zone."
)


def compute_corner_relief(spec: CornerReliefSpec) -> CornerReliefResult:
    """
    Compute the 2-D corner-relief cut geometry for a sheet-metal corner.

    Parameters
    ----------
    spec : CornerReliefSpec

    Returns
    -------
    CornerReliefResult

    Raises
    ------
    ValueError
        On invalid inputs or unrecognised relief_type.

    Notes
    -----
    Geometry rules (Suchy §7 / DIN 6935 §6):

    Square relief:
        width = r + t/2         (clears the outside bend radius + half-t)
        depth = r + t/2         (symmetric; minimum depth = t/2, typical = r + t/2)
        Outline: rectangular notch from (−w/2, 0) to (w/2, depth).

    Round relief:
        relief_radius = max(t/2, r/2)
        width = depth = 2 * relief_radius
        Outline: 16-sided polygon approximating a circle.

    Lance relief:
        width = t
        depth = r + t
        Outline: L-shaped partial cut (lance).
    """
    valid_types = {"square", "round", "lance"}
    if spec.relief_type not in valid_types:
        raise ValueError(
            f"relief_type must be one of {sorted(valid_types)}; got {spec.relief_type!r}"
        )

    t = float(spec.thickness_mm)
    if t <= 0:
        raise ValueError(f"thickness_mm must be > 0; got {t}")

    r = float(spec.bend_radius_mm)
    if r <= 0:
        raise ValueError(f"bend_radius_mm must be > 0; got {r}")

    angle = float(spec.bend_angle_deg)
    if angle <= 0 or angle > 180:
        raise ValueError(f"bend_angle_deg must be in (0, 180]; got {angle}")

    # Angle correction factor: for obtuse bends (> 90°) the relief can be
    # slightly narrower; for acute (< 90°) slightly wider.  Simple scaling:
    # f = sin(min(angle, 90°) / 90°) blended from 0.5 to 1.0.
    angle_factor = math.sin(math.radians(min(angle, 90.0)))

    if spec.relief_type == "square":
        # Minimum: depth ≥ r + t/2 (Suchy §7.1)
        base_depth = r + t / 2.0
        depth = round(base_depth * angle_factor, 6) if angle < 90 else round(base_depth, 6)
        depth = max(depth, t / 2.0)
        width = round(r + t / 2.0, 6)
        min_punch_r = round(t / 2.0, 6)
        hw = width / 2.0
        outline = [
            (-hw, 0.0),
            (hw, 0.0),
            (hw, depth),
            (-hw, depth),
            (-hw, 0.0),
        ]

    elif spec.relief_type == "round":
        rr = max(t / 2.0, r / 2.0)
        width = round(2.0 * rr, 6)
        depth = round(2.0 * rr, 6)
        min_punch_r = round(rr, 6)
        # 16-sided circle approximation centred at (0, rr)
        n_seg = 16
        outline = []
        for k in range(n_seg + 1):
            theta = math.pi * k / n_seg   # 0 → π (half circle)
            x = rr * math.cos(math.pi - theta)
            y = rr + rr * math.sin(math.pi - theta)
            outline.append((round(x, 8), round(y, 8)))
        # Close back to start
        outline.append(outline[0])

    else:  # lance
        # Lance-and-form: partial cut width = t, depth = r + t (Suchy §7.3)
        width = round(t, 6)
        depth = round(r + t, 6)
        min_punch_r = round(t / 2.0, 6)
        hw = width / 2.0
        # L-shaped lance outline
        outline = [
            (-hw, 0.0),
            (hw, 0.0),
            (hw, depth),
            (0.0, depth),
            (0.0, depth / 2.0),
            (-hw, depth / 2.0),
            (-hw, 0.0),
        ]

    return CornerReliefResult(
        relief_type=spec.relief_type,
        relief_width_mm=float(width),
        relief_depth_mm=float(depth),
        min_punch_radius_mm=float(min_punch_r),
        outline_xy=[(round(float(x), 8), round(float(y), 8)) for x, y in outline],
        honest_caveat=_RELIEF_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool (gated import — loads cleanly in pure-Python test envs)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload  # type: ignore[import]

    _sheetmetal_flat_pattern_spec = ToolSpec(
        name="sheetmetal_compute_flat_pattern",
        description=(
            "Compute the flat-pattern developed length for a parametric sheet-metal "
            "blank with one or more bends.  Returns bend allowances (BA), "
            "bend deductions (BD), effective K-factor, and total flat dimensions.  "
            "K-factor is interpolated from r/t per DIN 6935 / Suchy §3: "
            "K=0.33 at r/t<1 (severe bend), K=0.44 at r/t≥3 (mild steel gentle bend), "
            "linear interp between.  Formula: BA=(π·θ/180)·(r+K·t), "
            "OSSB=(r+t)·tan(θ/2), BD=2·OSSB−BA, flat_length=Σflange_lengths−ΣBD.  "
            "Supported materials: steel-cold-rolled, stainless-304, aluminum-5052, copper.  "
            "HONEST CAVEATS: K-factor is empirical (tabulated DIN 6935 interpolation); "
            "bend-deduction formula assumes inside-set air-bend; spring-back NOT modelled; "
            "use sheet_metal_bend_table for process-specific (bottoming/coining) corrections."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "material": {
                    "type": "string",
                    "description": (
                        "Sheet material. Accepted: 'steel-cold-rolled', 'stainless-304', "
                        "'aluminum-5052', 'copper'. Common aliases also accepted."
                    ),
                },
                "thickness_mm": {
                    "type": "number",
                    "description": "Sheet thickness in mm. Must be > 0.",
                },
                "length_mm": {
                    "type": "number",
                    "description": (
                        "Overall folded part length for reference (mm). "
                        "Does not affect flat-pattern calculation."
                    ),
                },
                "width_mm": {
                    "type": "number",
                    "description": "Blank width perpendicular to bend lines (mm). Must be > 0.",
                },
                "bend_radius_mm": {
                    "type": "number",
                    "description": "Inside bend radius (mm). Must be > 0.",
                },
                "bend_angle_deg": {
                    "type": "number",
                    "description": (
                        "Bend angle in degrees, (0, 180]. "
                        "90 = right-angle flange; 180 = hem fold."
                    ),
                },
                "flange_lengths_mm": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "Ordered straight-segment lengths (mm). "
                        "One entry per panel segment including the base. "
                        "Example: [50, 50] = L-bracket with 50 mm base + 50 mm flange. "
                        "Number of bends = len(flange_lengths_mm) − 1."
                    ),
                },
            },
            "required": [
                "material", "thickness_mm", "width_mm",
                "bend_radius_mm", "bend_angle_deg", "flange_lengths_mm",
            ],
        },
    )

    @register(_sheetmetal_flat_pattern_spec, write=False)
    async def run_sheetmetal_compute_flat_pattern(ctx, args: bytes) -> str:  # type: ignore[misc]
        import json as _json
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")

        material          = a.get("material", "")
        thickness_mm      = a.get("thickness_mm")
        length_mm         = a.get("length_mm", 0.0)
        width_mm          = a.get("width_mm")
        bend_radius_mm    = a.get("bend_radius_mm")
        bend_angle_deg    = a.get("bend_angle_deg")
        flange_lengths_mm = a.get("flange_lengths_mm")

        if not material:
            return err_payload("material is required", "BAD_ARGS")
        if thickness_mm is None:
            return err_payload("thickness_mm is required", "BAD_ARGS")
        if width_mm is None:
            return err_payload("width_mm is required", "BAD_ARGS")
        if bend_radius_mm is None:
            return err_payload("bend_radius_mm is required", "BAD_ARGS")
        if bend_angle_deg is None:
            return err_payload("bend_angle_deg is required", "BAD_ARGS")
        if not isinstance(flange_lengths_mm, list):
            return err_payload("flange_lengths_mm must be an array", "BAD_ARGS")

        try:
            part = SheetMetalPart(
                material=str(material),
                thickness_mm=float(thickness_mm),
                length_mm=float(length_mm),
                width_mm=float(width_mm),
                bend_radius_mm=float(bend_radius_mm),
                bend_angle_deg=float(bend_angle_deg),
                flange_lengths_mm=[float(f) for f in flange_lengths_mm],
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"numeric argument error: {exc}", "BAD_ARGS")

        try:
            result = compute_flat_pattern(part)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "flat_length_mm":          result.flat_length_mm,
            "flat_width_mm":           result.flat_width_mm,
            "bend_allowances_mm":      result.bend_allowances_mm,
            "k_factor":                result.k_factor,
            "total_bend_deduction_mm": result.total_bend_deduction_mm,
            "num_bends":               result.num_bends,
            "honest_caveat":           result.honest_caveat,
        })

    # ------------------------------------------------------------------
    # sheetmetal_compute_hem
    # ------------------------------------------------------------------

    _sheetmetal_hem_spec = ToolSpec(
        name="sheetmetal_compute_hem",
        description=(
            "Compute the flat-pattern developed length for a sheet-metal hem "
            "(flange folded 180° back on itself). "
            "Supports four hem types per Suchy §6 + DIN 6935 §4.3: "
            "'open' (gap = sheet_thickness), 'closed' (gap = 0, pressed flat), "
            "'teardrop' (gap = 2·radius + t, distinct teardrop profile), "
            "'rolled' (full-circle roll, r ≥ t/2). "
            "BA_hem = π·(r_eff + K·t). "
            "Returns: developed_length_mm, flat_pattern_segments, bend_allowance_mm, gap_mm. "
            "HONEST CAVEATS: BA formula is 180° neutral-axis arc (Suchy §6); "
            "spring-back not modelled; closed hem gap is nominally 0 but "
            "0.1–0.3 mm in practice without coining; rolled hem requires r ≥ t/2."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "hem_type": {
                    "type": "string",
                    "description": "Hem type: 'open', 'closed', 'teardrop', or 'rolled'.",
                },
                "hem_radius_mm": {
                    "type": "number",
                    "description": "Inside bend radius of the hem fold (mm). ≥ 0.",
                },
                "hem_length_mm": {
                    "type": "number",
                    "description": "Leg length of the hem from bend tangent to free edge (mm). > 0.",
                },
                "sheet_thickness_mm": {
                    "type": "number",
                    "description": "Sheet thickness (mm). > 0.",
                },
                "k_factor": {
                    "type": "number",
                    "description": "K-factor neutral-axis offset fraction (0–1, default 0.4).",
                },
            },
            "required": ["hem_type", "hem_radius_mm", "hem_length_mm", "sheet_thickness_mm"],
        },
    )

    @register(_sheetmetal_hem_spec, write=False)
    async def run_sheetmetal_compute_hem(ctx, args: bytes) -> str:  # type: ignore[misc]
        import json as _json
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")

        hem_type           = a.get("hem_type", "")
        hem_radius_mm      = a.get("hem_radius_mm")
        hem_length_mm      = a.get("hem_length_mm")
        sheet_thickness_mm = a.get("sheet_thickness_mm")
        k_factor           = a.get("k_factor", 0.4)

        if not hem_type:
            return err_payload("hem_type is required", "BAD_ARGS")
        if hem_radius_mm is None:
            return err_payload("hem_radius_mm is required", "BAD_ARGS")
        if hem_length_mm is None:
            return err_payload("hem_length_mm is required", "BAD_ARGS")
        if sheet_thickness_mm is None:
            return err_payload("sheet_thickness_mm is required", "BAD_ARGS")

        try:
            spec = HemSpec(
                hem_type=str(hem_type),
                hem_radius_mm=float(hem_radius_mm),
                hem_length_mm=float(hem_length_mm),
                sheet_thickness_mm=float(sheet_thickness_mm),
                k_factor=float(k_factor),
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"numeric argument error: {exc}", "BAD_ARGS")

        try:
            result = compute_hem_geometry(spec)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "developed_length_mm":  result.developed_length_mm,
            "flat_pattern_segments": result.flat_pattern_segments,
            "bend_allowance_mm":    result.bend_allowance_mm,
            "gap_mm":               result.gap_mm,
            "honest_caveat":        result.honest_caveat,
        })

    # ------------------------------------------------------------------
    # sheetmetal_compute_jog
    # ------------------------------------------------------------------

    _sheetmetal_jog_spec = ToolSpec(
        name="sheetmetal_compute_jog",
        description=(
            "Compute the flat-pattern developed length for a sheet-metal jog "
            "(Z-offset feature made from two opposing bends close together). "
            "Per Suchy §4.5 + DIN 6935 §4: θ = arctan(height / length); "
            "BA = (π·θ/180)·(r + K·t) applied to both bends; "
            "flat_developed_length = jog_length + 2·BA. "
            "Returns: flat_developed_length, bend_count=2, bend_allowances_mm, jog_angle_deg. "
            "HONEST CAVEATS: symmetric jog only (both bends identical); "
            "minimum jog land ≥ 4t recommended to avoid bend-interaction effects; "
            "spring-back NOT modelled."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "jog_height_mm": {
                    "type": "number",
                    "description": "Desired Z-offset between parallel panels (mm). > 0.",
                },
                "jog_length_mm": {
                    "type": "number",
                    "description": "Horizontal distance between the two bend tangent points (mm). > 0.",
                },
                "sheet_thickness_mm": {
                    "type": "number",
                    "description": "Sheet thickness (mm). > 0.",
                },
                "bend_radius_mm": {
                    "type": "number",
                    "description": "Inside bend radius (applied to both bends, mm). > 0.",
                },
                "k_factor": {
                    "type": "number",
                    "description": "K-factor neutral-axis offset fraction (0–1, default 0.4).",
                },
            },
            "required": ["jog_height_mm", "jog_length_mm", "sheet_thickness_mm", "bend_radius_mm"],
        },
    )

    @register(_sheetmetal_jog_spec, write=False)
    async def run_sheetmetal_compute_jog(ctx, args: bytes) -> str:  # type: ignore[misc]
        import json as _json
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")

        jog_height_mm      = a.get("jog_height_mm")
        jog_length_mm      = a.get("jog_length_mm")
        sheet_thickness_mm = a.get("sheet_thickness_mm")
        bend_radius_mm     = a.get("bend_radius_mm")
        k_factor           = a.get("k_factor", 0.4)

        if jog_height_mm is None:
            return err_payload("jog_height_mm is required", "BAD_ARGS")
        if jog_length_mm is None:
            return err_payload("jog_length_mm is required", "BAD_ARGS")
        if sheet_thickness_mm is None:
            return err_payload("sheet_thickness_mm is required", "BAD_ARGS")
        if bend_radius_mm is None:
            return err_payload("bend_radius_mm is required", "BAD_ARGS")

        try:
            spec = JogSpec(
                jog_height_mm=float(jog_height_mm),
                jog_length_mm=float(jog_length_mm),
                sheet_thickness_mm=float(sheet_thickness_mm),
                bend_radius_mm=float(bend_radius_mm),
                k_factor=float(k_factor),
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"numeric argument error: {exc}", "BAD_ARGS")

        try:
            result = compute_jog_geometry(spec)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "flat_developed_length": result.flat_developed_length,
            "bend_count":            result.bend_count,
            "bend_allowances_mm":    result.bend_allowances_mm,
            "jog_angle_deg":         result.jog_angle_deg,
            "honest_caveat":         result.honest_caveat,
        })

    # ------------------------------------------------------------------
    # sheetmetal_compute_multi_flange
    # ------------------------------------------------------------------

    _sheetmetal_multi_flange_spec = ToolSpec(
        name="sheetmetal_compute_multi_flange",
        description=(
            "Compute the flat-pattern developed length for a multi-flange "
            "sheet-metal part — a chain of N straight-segment flanges joined "
            "by N−1 bends, each with its own angle, radius, and K-factor. "
            "Per Suchy §3 + DIN 6935: "
            "BA_i = (π·θ_i/180)·(r_i + K_i·t); "
            "OSSB_i = (r_i + t)·tan(θ_i/2); BD_i = 2·OSSB_i − BA_i; "
            "flat_length = Σlengths − ΣBD. "
            "Returns: total_flat_length_mm, bend_allowances_mm (list), "
            "total_bend_deduction_mm, num_bends. "
            "Flanges array: each entry has length_mm, angle_deg, radius_mm, "
            "k_factor (opt, default 0.4), thickness_mm (opt, default 1.0). "
            "The last flange's angle/radius are ignored (no trailing bend). "
            "HONEST CAVEATS: K-factors empirical; spring-back NOT modelled; "
            "bend-interaction for closely-spaced bends (< 4t) not captured."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "flanges": {
                    "type": "array",
                    "description": (
                        "Ordered list of flange specs. Each entry: "
                        "{length_mm, angle_deg, radius_mm, k_factor (opt), thickness_mm (opt)}. "
                        "Minimum 1 entry. Last entry's angle/radius ignored."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "length_mm":    {"type": "number"},
                            "angle_deg":    {"type": "number"},
                            "radius_mm":    {"type": "number"},
                            "k_factor":     {"type": "number"},
                            "thickness_mm": {"type": "number"},
                        },
                        "required": ["length_mm", "angle_deg", "radius_mm"],
                    },
                },
            },
            "required": ["flanges"],
        },
    )

    @register(_sheetmetal_multi_flange_spec, write=False)
    async def run_sheetmetal_compute_multi_flange(ctx, args: bytes) -> str:  # type: ignore[misc]
        import json as _json
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")

        flanges_raw = a.get("flanges")
        if not isinstance(flanges_raw, list) or len(flanges_raw) == 0:
            return err_payload("flanges must be a non-empty array", "BAD_ARGS")

        try:
            flange_specs = []
            for fi, fd in enumerate(flanges_raw):
                if not isinstance(fd, dict):
                    return err_payload(f"flanges[{fi}] must be an object", "BAD_ARGS")
                fs = FlangeSpec(
                    length_mm=float(fd.get("length_mm", 0)),
                    angle_deg=float(fd.get("angle_deg", 90)),
                    radius_mm=float(fd.get("radius_mm", 1)),
                    k_factor=float(fd.get("k_factor", 0.4)),
                    thickness_mm=float(fd.get("thickness_mm", 1.0)),
                )
                flange_specs.append(fs)
        except (TypeError, ValueError) as exc:
            return err_payload(f"numeric argument error: {exc}", "BAD_ARGS")

        try:
            result = compute_multi_flange_geometry(MultiFlangeSpec(flanges=flange_specs))
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "total_flat_length_mm":     result.total_flat_length_mm,
            "bend_allowances_mm":       result.bend_allowances_mm,
            "total_bend_deduction_mm":  result.total_bend_deduction_mm,
            "num_bends":                result.num_bends,
            "honest_caveat":            result.honest_caveat,
        })

    # ------------------------------------------------------------------
    # sheetmetal_compute_corner_relief  — GK-SM1
    # ------------------------------------------------------------------

    _sheetmetal_corner_relief_spec = ToolSpec(
        name="sheetmetal_compute_corner_relief",
        description=(
            "Compute the 2-D corner-relief cut geometry for a sheet-metal corner "
            "where two bend lines meet.  Corner reliefs prevent tearing and stress "
            "concentration during bending.  Per Suchy 'Handbook of Die Design' §7 "
            "+ DIN 6935 §6.\n\n"
            "Three types:\n"
            "  'square' — rectangular notch; width = r+t/2, depth = r+t/2.\n"
            "  'round'  — circular punch; radius = max(t/2, r/2).\n"
            "  'lance'  — lance-and-form partial cut; width = t, depth = r+t "
            "(thin-gauge aluminium only).\n\n"
            "Returns: {ok, relief_type, relief_width_mm, relief_depth_mm, "
            "min_punch_radius_mm, outline_xy, honest_caveat}.\n"
            "Errors: {ok:false, reason}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "relief_type": {
                    "type": "string",
                    "description": "One of: 'square', 'round', 'lance'.",
                },
                "bend_radius_mm": {
                    "type": "number",
                    "description": "Inside bend radius at the corner (mm). Must be > 0.",
                },
                "thickness_mm": {
                    "type": "number",
                    "description": "Sheet thickness (mm). Must be > 0.",
                },
                "bend_angle_deg": {
                    "type": "number",
                    "description": "Bend angle in degrees (default 90).",
                },
            },
            "required": ["relief_type", "bend_radius_mm", "thickness_mm"],
        },
    )

    @register(_sheetmetal_corner_relief_spec, write=False)
    async def run_sheetmetal_compute_corner_relief(ctx, args: bytes) -> str:  # type: ignore[misc]
        import json as _json
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")

        try:
            spec = CornerReliefSpec(
                relief_type=str(a.get("relief_type", "square")),
                bend_radius_mm=float(a.get("bend_radius_mm", 1.0)),
                thickness_mm=float(a.get("thickness_mm", 1.0)),
                bend_angle_deg=float(a.get("bend_angle_deg", 90.0)),
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"numeric argument error: {exc}", "BAD_ARGS")

        try:
            result = compute_corner_relief(spec)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "relief_type":        result.relief_type,
            "relief_width_mm":    result.relief_width_mm,
            "relief_depth_mm":    result.relief_depth_mm,
            "min_punch_radius_mm": result.min_punch_radius_mm,
            "outline_xy":         result.outline_xy,
            "honest_caveat":      result.honest_caveat,
        })

except ImportError:
    # Pure-Python / test environment: tool not registered, but module is usable.
    pass
