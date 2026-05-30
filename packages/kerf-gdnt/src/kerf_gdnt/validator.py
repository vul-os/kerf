"""
ASME Y14.5-2018 Feature Control Frame validator.

Implements structural validation per ASME Y14.5-2018:
  - §3.4   Feature control frame structure
  - §3.4.1 Required compartments (symbol, tolerance, datums)
  - §6     Material condition modifiers (M/L/T)
  - §9.4   Position — datum requirements
  - §10.x  Orientation — datum requirements
  - §11.x  Profile — applicability (all-around / between / any-surface)
  - §12.x  Form — no datums permitted

NOTE: This module implements ASME Y14.5-2018 *structural* validation only.
      Kerf is not ASME-certified; this is engineering software, not a
      certification body.

Canonical text form (round-trip safe)::

    [⌖][⌀0.05][M][A][B][C]

where each bracket is a compartment.  Absent compartments are omitted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from kerf_gdnt.symbols import ALL_SYMBOLS, ALL_MODIFIERS, MODIFIER_DIAMETER
from kerf_gdnt.feature_control_frame import DatumReference, FeatureControlFrame


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """A single structured validation error."""
    code: str           # machine-readable error code
    message: str        # human-readable message
    clause: str = ""    # ASME Y14.5-2018 clause reference, if known

    def __str__(self) -> str:
        if self.clause:
            return f"[{self.code}] {self.message} (ref: {self.clause})"
        return f"[{self.code}] {self.message}"


@dataclass
class ValidationResult:
    """Outcome of :func:`validate_frame`."""
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": [
                {"code": e.code, "message": e.message, "clause": e.clause}
                for e in self.errors
            ],
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Symbol category classification helpers
# ---------------------------------------------------------------------------

# Symbols that control a *size feature* — eligible for M/L modifiers (§6.3)
_SIZE_CONTROLLING_SYMBOLS: frozenset[str] = frozenset({
    "straightness",    # §12.4 — on a surface of revolution (axis straightness)
    "position",        # §9.4
    "concentricity",   # §9.9
    "symmetry",        # §9.10
    "circular_runout", # §13.4
    "total_runout",    # §13.5
    "profile_line",    # §11.5 — when applied to size features
    "profile_surface", # §11.6 — when applied to size features
})

# Orientation tolerances — require ≥1 datum (§10.x)
_ORIENTATION_SYMBOLS: frozenset[str] = frozenset({
    "angularity",
    "perpendicularity",
    "parallelism",
})

# Location tolerances — require ≥1 datum (§9.x)
_LOCATION_SYMBOLS: frozenset[str] = frozenset({
    "position",
    "concentricity",
    "symmetry",
})

# Runout tolerances — require ≥1 datum (§13.x)
_RUNOUT_SYMBOLS: frozenset[str] = frozenset({
    "circular_runout",
    "total_runout",
})

# Form tolerances — datums are *prohibited* (§12.x, §3.4.3)
_FORM_SYMBOLS_NO_DATUM: frozenset[str] = frozenset({
    "flatness",
    "circularity",
    "cylindricity",
    # straightness — can have datum when applied as axis (§12.4.1), so excluded here
})

# Tangent-plane modifier is only valid for orientation tolerances (§6.6)
_TANGENT_PLANE_ELIGIBLE: frozenset[str] = frozenset({
    "angularity",
    "perpendicularity",
    "parallelism",
    "flatness",
})


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

def validate_frame(
    frame: FeatureControlFrame,
    standard: str = "ASME Y14.5-2018",
) -> ValidationResult:
    """
    Validate a :class:`~kerf_gdnt.feature_control_frame.FeatureControlFrame`
    against ASME Y14.5-2018 structural rules.

    Parameters
    ----------
    frame:
        The feature control frame to validate.
    standard:
        Standard identifier string — currently only ``'ASME Y14.5-2018'`` is
        supported; anything else raises ``ValueError``.

    Returns
    -------
    ValidationResult
        ``valid=True`` when no errors are found.  Warnings are non-fatal
        observations (e.g. unusual but not prohibited combinations).

    Notes
    -----
    This implements *structural* (well-formedness) checks only.
    Contextual/semantic rules that require knowledge of the full drawing or
    3-D model (e.g. whether a referenced datum is actually defined) are
    outside the scope of this module.
    """
    if standard != "ASME Y14.5-2018":
        raise ValueError(
            f"Unsupported standard {standard!r}. "
            "Only 'ASME Y14.5-2018' is currently implemented."
        )

    errors: list[ValidationError] = []
    warnings: list[str] = []

    sym_code = frame.symbol_code

    # ------------------------------------------------------------------ #
    # 1. Symbol code must be known (§3.4 — symbol compartment required)   #
    # ------------------------------------------------------------------ #
    if sym_code not in ALL_SYMBOLS:
        errors.append(ValidationError(
            code="UNKNOWN_SYMBOL",
            message=f"Unknown GD&T symbol code {sym_code!r}. "
                    f"Valid codes: {sorted(ALL_SYMBOLS)}",
            clause="ASME Y14.5-2018 §3.4",
        ))
        # Cannot continue meaningfully without a valid symbol
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    sym = ALL_SYMBOLS[sym_code]

    # ------------------------------------------------------------------ #
    # 2. Tolerance value must be strictly positive (§3.4.2)               #
    # ------------------------------------------------------------------ #
    if frame.tolerance_value <= 0:
        errors.append(ValidationError(
            code="NON_POSITIVE_TOLERANCE",
            message=f"Tolerance value must be a positive number; got {frame.tolerance_value}.",
            clause="ASME Y14.5-2018 §3.4.2",
        ))

    # ------------------------------------------------------------------ #
    # 3. Tolerance modifier validity                                       #
    # ------------------------------------------------------------------ #
    mod = frame.tolerance_modifier
    if mod is not None:
        if mod not in ALL_MODIFIERS:
            errors.append(ValidationError(
                code="UNKNOWN_MODIFIER",
                message=f"Unknown tolerance modifier {mod!r}.",
                clause="ASME Y14.5-2018 §6",
            ))
        elif mod in ("M", "L"):
            # M/L only valid on size-controlling symbols (§6.3)
            if sym_code not in _SIZE_CONTROLLING_SYMBOLS:
                errors.append(ValidationError(
                    code="MODIFIER_NOT_APPLICABLE",
                    message=(
                        f"Material condition modifier {mod!r} (MMC/LMC) is only "
                        f"applicable to size-controlling tolerances; "
                        f"'{sym_code}' ({sym.category}) does not control size."
                    ),
                    clause="ASME Y14.5-2018 §6.3",
                ))
        elif mod == "T":
            # Tangent-plane modifier only valid on orientation/flatness (§6.6)
            if sym_code not in _TANGENT_PLANE_ELIGIBLE:
                errors.append(ValidationError(
                    code="TANGENT_PLANE_NOT_APPLICABLE",
                    message=(
                        f"Tangent plane modifier 'T' is only applicable to "
                        f"orientation tolerances and flatness; not '{sym_code}'."
                    ),
                    clause="ASME Y14.5-2018 §6.6",
                ))

    # ------------------------------------------------------------------ #
    # 4. Datum reference count (§3.4.1 — max three compartments)          #
    # ------------------------------------------------------------------ #
    if len(frame.datum_refs) > 3:
        errors.append(ValidationError(
            code="TOO_MANY_DATUMS",
            message=(
                f"An FCF may reference at most three datums "
                f"(primary, secondary, tertiary); found {len(frame.datum_refs)}."
            ),
            clause="ASME Y14.5-2018 §3.4.1",
        ))

    # ------------------------------------------------------------------ #
    # 5. Duplicate datum labels within the same frame (§3.4.1)            #
    # ------------------------------------------------------------------ #
    datum_labels = [dr.label for dr in frame.datum_refs]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for lbl in datum_labels:
        if lbl in seen:
            duplicates.add(lbl)
        seen.add(lbl)
    if duplicates:
        errors.append(ValidationError(
            code="DUPLICATE_DATUM",
            message=(
                f"Duplicate datum reference(s) in the same FCF: "
                f"{sorted(duplicates)}. Each datum label must appear at most once."
            ),
            clause="ASME Y14.5-2018 §3.4.1",
        ))

    # ------------------------------------------------------------------ #
    # 6. Datum modifier validity                                           #
    # ------------------------------------------------------------------ #
    for dr in frame.datum_refs:
        if dr.modifier is not None and dr.modifier not in ALL_MODIFIERS:
            errors.append(ValidationError(
                code="UNKNOWN_DATUM_MODIFIER",
                message=f"Unknown modifier {dr.modifier!r} on datum {dr.label!r}.",
                clause="ASME Y14.5-2018 §6",
            ))

    # ------------------------------------------------------------------ #
    # 7. Orientation tolerances require ≥1 datum reference (§10.x)        #
    # ------------------------------------------------------------------ #
    if sym_code in _ORIENTATION_SYMBOLS and len(frame.datum_refs) == 0:
        errors.append(ValidationError(
            code="ORIENTATION_REQUIRES_DATUM",
            message=(
                f"Orientation tolerances require at least one datum reference; "
                f"'{sym_code}' has none."
            ),
            clause="ASME Y14.5-2018 §10.1",
        ))

    # ------------------------------------------------------------------ #
    # 8. Location tolerances require ≥1 datum reference (§9.x)            #
    # ------------------------------------------------------------------ #
    if sym_code in _LOCATION_SYMBOLS and len(frame.datum_refs) == 0:
        errors.append(ValidationError(
            code="LOCATION_REQUIRES_DATUM",
            message=(
                f"Location tolerances require at least one datum reference; "
                f"'{sym_code}' (position/concentricity/symmetry) has none."
            ),
            clause="ASME Y14.5-2018 §9.1",
        ))

    # ------------------------------------------------------------------ #
    # 9. Runout tolerances require ≥1 datum reference (§13.x)             #
    # ------------------------------------------------------------------ #
    if sym_code in _RUNOUT_SYMBOLS and len(frame.datum_refs) == 0:
        errors.append(ValidationError(
            code="RUNOUT_REQUIRES_DATUM",
            message=(
                f"Runout tolerances require at least one datum axis/point; "
                f"'{sym_code}' has none."
            ),
            clause="ASME Y14.5-2018 §13.1",
        ))

    # ------------------------------------------------------------------ #
    # 10. Form tolerances — datums prohibited (§12.x)                     #
    # ------------------------------------------------------------------ #
    if sym_code in _FORM_SYMBOLS_NO_DATUM and len(frame.datum_refs) > 0:
        errors.append(ValidationError(
            code="FORM_TOL_NO_DATUM_ALLOWED",
            message=(
                f"Form tolerances (flatness/circularity/cylindricity) must not "
                f"reference datums; '{sym_code}' has {len(frame.datum_refs)} "
                f"datum reference(s)."
            ),
            clause="ASME Y14.5-2018 §12.1",
        ))

    # ------------------------------------------------------------------ #
    # 11. Diameter zone applicability                                      #
    # ------------------------------------------------------------------ #
    if frame.diameter_zone:
        # Diameter zone is used for cylindrical zones (axis straightness,
        # position, etc.).  Warn if used on form tolerances that normally
        # use a width zone.
        if sym_code in ("flatness", "angularity"):
            warnings.append(
                f"Diameter zone (⌀) is unusual for '{sym_code}'; "
                f"verify this is intentional per ASME Y14.5-2018 §3.3.17."
            )

    # ------------------------------------------------------------------ #
    # 12. Projected tolerance zone requires position symbol (§9.8)        #
    # ------------------------------------------------------------------ #
    if mod == "P" and sym_code != "position":
        errors.append(ValidationError(
            code="PROJECTED_ZONE_POSITION_ONLY",
            message=(
                "Projected tolerance zone modifier 'P' is only valid for "
                f"position tolerances; found '{sym_code}'."
            ),
            clause="ASME Y14.5-2018 §9.8",
        ))

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Canonical string form
# ---------------------------------------------------------------------------

# Maps modifier codes to their canonical single-character text tokens
_MOD_CODE_TO_TOKEN: dict[str, str] = {
    "M": "M",
    "L": "L",
    "S": "S",
    "F": "F",
    "P": "P",
    "T": "T",
}

# Reverse map — token back to modifier code
_TOKEN_TO_MOD_CODE: dict[str, str] = {v: k for k, v in _MOD_CODE_TO_TOKEN.items()}


def canonical_frame_string(frame: FeatureControlFrame) -> str:
    """
    Produce a round-trip-safe canonical ASCII text form of a feature control
    frame.

    Format::

        [symbol_code][dia?tolerance_value][modifier?][zone_note?][datum_A?][datum_B?][datum_C?]

    Where:
    - Each compartment is enclosed in ``[...]``
    - ``dia?`` is literal ``dia:`` when ``diameter_zone`` is True
    - Datum modifier appended after datum label with ``/``, e.g. ``[A/M]``

    Example::

        [position][dia:0.05][M][A][B][C]
        [perpendicularity][0.1][A]
        [flatness][0.05]

    This form is designed for programmatic use and storage — the rendered
    Unicode form (``render()``) is preferred for display.
    """
    parts: list[str] = []

    # Symbol compartment
    parts.append(f"[{frame.symbol_code}]")

    # Tolerance compartment
    tol_str = f"{frame.tolerance_value:g}"
    dia_prefix = "dia:" if frame.diameter_zone else ""
    parts.append(f"[{dia_prefix}{tol_str}]")

    # Modifier compartment (optional)
    if frame.tolerance_modifier:
        parts.append(f"[{frame.tolerance_modifier}]")

    # Datum compartments
    for dr in frame.datum_refs:
        if dr.modifier:
            parts.append(f"[{dr.label}/{dr.modifier}]")
        else:
            parts.append(f"[{dr.label}]")

    return "".join(parts)


# Regex for parsing one canonical compartment
_COMPARTMENT_RE = re.compile(r"\[([^\]]*)\]")

# Known symbol codes (for distinguishing symbol from other compartments)
_ALL_SYMBOL_CODES: frozenset[str] = frozenset(ALL_SYMBOLS.keys())

# Known modifier codes
_ALL_MODIFIER_CODES: frozenset[str] = frozenset(ALL_MODIFIERS.keys()) - {"dia"}


def parse_canonical_frame(text: str) -> FeatureControlFrame:
    """
    Parse a canonical frame string produced by :func:`canonical_frame_string`
    back into a :class:`~kerf_gdnt.feature_control_frame.FeatureControlFrame`.

    Raises
    ------
    ValueError
        If *text* cannot be parsed into a well-structured FCF.
    """
    compartments = _COMPARTMENT_RE.findall(text.strip())
    if len(compartments) < 2:
        raise ValueError(
            f"Cannot parse canonical frame {text!r}: "
            "expected at least [symbol][tolerance] compartments."
        )

    # First compartment is always the symbol code
    sym_code = compartments[0]
    if sym_code not in _ALL_SYMBOL_CODES:
        raise ValueError(
            f"Unknown symbol code {sym_code!r} in canonical frame {text!r}."
        )

    # Second compartment is the tolerance (optionally prefixed with 'dia:')
    tol_raw = compartments[1]
    diameter_zone = False
    if tol_raw.startswith("dia:"):
        diameter_zone = True
        tol_raw = tol_raw[4:]
    try:
        tolerance_value = float(tol_raw)
    except ValueError:
        raise ValueError(
            f"Cannot parse tolerance value {tol_raw!r} in canonical frame {text!r}."
        )

    # Remaining compartments: optional modifier, then datums
    tolerance_modifier: Optional[str] = None
    datum_refs: list[DatumReference] = []

    for compartment in compartments[2:]:
        # Single-char modifier codes
        if compartment in _ALL_MODIFIER_CODES:
            tolerance_modifier = compartment
        elif "/" in compartment:
            # Datum with modifier: "A/M"
            label, mod_code = compartment.split("/", 1)
            datum_refs.append(DatumReference(label=label.strip(), modifier=mod_code.strip() or None))
        else:
            # Plain datum label
            datum_refs.append(DatumReference(label=compartment.strip()))

    return FeatureControlFrame(
        symbol_code=sym_code,
        tolerance_value=tolerance_value,
        diameter_zone=diameter_zone,
        tolerance_modifier=tolerance_modifier,
        datum_refs=datum_refs,
    )


# ---------------------------------------------------------------------------
# Tolerance zone calculation (§6.3 bonus tolerance)
# ---------------------------------------------------------------------------

def zone_for_position_tol(
    diameter_tol: float,
    mmc: bool = False,
    lmc: bool = False,
    feature_mmc_size: Optional[float] = None,
    feature_lmc_size: Optional[float] = None,
    actual_feature_size: Optional[float] = None,
) -> dict:
    """
    Calculate the effective position tolerance zone diameter, including MMC/LMC
    bonus tolerance per ASME Y14.5-2018 §6.3.

    Parameters
    ----------
    diameter_tol:
        The stated (drawing) position tolerance zone diameter.
    mmc:
        If True, the MMC modifier is applied; bonus tolerance accrues as the
        feature departs from MMC toward LMC.
    lmc:
        If True, the LMC modifier is applied; bonus tolerance accrues as the
        feature departs from LMC toward MMC.
    feature_mmc_size:
        Maximum Material Condition size of the feature (smallest hole /
        largest pin).  Required when *mmc* is True and *actual_feature_size*
        is provided.
    feature_lmc_size:
        Least Material Condition size.  Required when *lmc* is True.
    actual_feature_size:
        Actual measured size of the feature.  When supplied the bonus
        tolerance is computed; otherwise only the stated zone is returned.

    Returns
    -------
    dict with keys:
      - ``stated_tol``: the drawing tolerance value
      - ``bonus_tol``: bonus tolerance (0 when not applicable)
      - ``total_zone_diameter``: stated + bonus
      - ``modifier``: ``"MMC"``, ``"LMC"``, or ``"RFS"``

    Notes
    -----
    Bonus tolerance (§6.3.2)::

        bonus = |actual_size − MMC_size|   (for MMC modifier)
        bonus = |actual_size − LMC_size|   (for LMC modifier)

    The actual tolerance zone diameter the feature must lie within is::

        T_actual = T_stated + bonus
    """
    if mmc and lmc:
        raise ValueError("Cannot apply both MMC and LMC modifiers simultaneously.")

    bonus = 0.0
    modifier_label = "RFS"

    if mmc:
        modifier_label = "MMC"
        if actual_feature_size is not None and feature_mmc_size is not None:
            bonus = abs(actual_feature_size - feature_mmc_size)
    elif lmc:
        modifier_label = "LMC"
        if actual_feature_size is not None and feature_lmc_size is not None:
            bonus = abs(actual_feature_size - feature_lmc_size)

    total = diameter_tol + bonus

    return {
        "stated_tol": diameter_tol,
        "bonus_tol": round(bonus, 10),
        "total_zone_diameter": round(total, 10),
        "modifier": modifier_label,
    }
