"""
kerf-cad-core: GK-P17 — Sheet-metal features: parametric flanges, bends,
and unfold-to-flat-pattern.

Implements:
  - ``SheetMetalPart``     — dataclass describing a multi-bend blank
  - ``FlatPatternResult``  — dataclass returned by ``compute_flat_pattern``
  - ``compute_flat_pattern(part)``  — K-factor + bend-allowance + flat-pattern

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

LLM tool: ``sheetmetal_compute_flat_pattern``
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

except ImportError:
    # Pure-Python / test environment: tool not registered, but module is usable.
    pass
