"""
Composite Tolerance Frame parser and validator — ASME Y14.5-2018 §10.5.

A composite tolerance frame has TWO LINES in a single feature control frame:

  Upper line (PLTZF — Pattern-Locating Tolerance Zone Framework):
      Controls the location of the entire pattern of features relative to
      the datum reference frame.  All datums from the drawing DRF may appear.

  Lower line (FRTZF — Feature-Relating Tolerance Zone Framework):
      Controls feature-to-feature (within-pattern) relationships.  The
      tolerance zone must be ≤ PLTZF tolerance (§10.5.1 Note 2).  The
      primary datum in FRTZF MUST match the primary datum in PLTZF
      (§10.5.1(a)).  Secondary/tertiary datums in FRTZF are optional but,
      if present, must be a subset of PLTZF datums in precedence order
      (§10.5.1(b)).

Text format accepted by :func:`parse_composite_frame`
------------------------------------------------------
The parser accepts a *simplified canonical text* — full ASCII GD&T needs
extensive Unicode work and is out of scope.

Format (case-insensitive, both lines separated by ``/``)::

    <symbol>|<tol>[M|L|S]|<datum>... / <symbol>|<tol>[M|L|S]|<datum>...

Where each compartment separator is ``|``.  Examples::

    "position|D0.5|A|B|C / position|D0.2|A"
    "position|D0.5M|A|B|C / position|D0.2M|A|B"

``D`` prefix on tolerance indicates a diameter zone.

HONEST FLAG: This parser recognises one canonical text form only.  Full
production ASCII/Unicode GD&T parsing (with ∅, ⌀, ©, MMC circles etc.)
requires a dedicated lexer and is NOT implemented here.

Rules implemented (ASME Y14.5-2018 §10.5)
------------------------------------------
R1  §10.5.1       -- Two lines required (PLTZF + FRTZF).
R2  §10.5.1 Note2 -- FRTZF tolerance ≤ PLTZF tolerance.
R3  §10.5.1(a)    -- FRTZF primary datum must match PLTZF primary datum.
R4  §10.5.1(b)    -- FRTZF datums must be a subset of PLTZF datums in
                     the same precedence order (no new datums; skipping
                     is allowed).
R5  §10.5.1       -- Symbol must match between PLTZF and FRTZF (both
                     position, or both profile, etc.).

Kerf is not ASME-certified; this is engineering support software.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ToleranceFrameLine:
    """
    One line of a composite tolerance frame.

    Parameters
    ----------
    symbol:
        GD&T symbol code string, e.g. ``"position"``.
    tolerance_value:
        Numeric tolerance value.
    diameter_zone:
        True if the tolerance zone is cylindrical (diameter prefix).
    modifier:
        Material-condition modifier on the tolerance value: ``"M"`` (MMC),
        ``"L"`` (LMC), ``"S"`` (RFS), or ``None``.
    datums:
        Ordered list of datum labels.  Position 0 = primary.
    """
    symbol: str
    tolerance_value: float
    diameter_zone: bool = False
    modifier: Optional[str] = None
    datums: list[str] = field(default_factory=list)

    def render(self) -> str:
        dia = "D" if self.diameter_zone else ""
        mod = self.modifier or ""
        datum_part = "|".join(self.datums)
        datum_str = f"|{datum_part}" if self.datums else ""
        return f"{self.symbol}|{dia}{self.tolerance_value}{mod}{datum_str}"


@dataclass
class CompositeFrame:
    """
    A composite position tolerance frame per ASME Y14.5-2018 §10.5.

    Attributes
    ----------
    pltzf:
        Upper line — Pattern-Locating Tolerance Zone Framework.
    frtzf:
        Lower line — Feature-Relating Tolerance Zone Framework.
    raw_text:
        Original text passed to :func:`parse_composite_frame`, for diagnostics.
    """
    pltzf: ToleranceFrameLine
    frtzf: ToleranceFrameLine
    raw_text: str = ""


@dataclass
class CompositeViolation:
    """A single §10.5 rule violation."""
    code: str          # machine-readable
    message: str       # human-readable
    rule: str          # ASME Y14.5-2018 citation

    def __str__(self) -> str:
        return f"[{self.code}] {self.message} ({self.rule})"


@dataclass
class CompositeValidationReport:
    """
    Result of :func:`validate_composite_frame`.

    Attributes
    ----------
    valid:
        True when no violations are found.
    pltzf_ok:
        Structural check for PLTZF line (always True when parsed).
    frtzf_ok:
        Structural check for FRTZF line.
    violations:
        List of :class:`CompositeViolation` objects — empty on success.
    warnings:
        Non-fatal notes.
    """
    valid: bool
    pltzf_ok: bool = True
    frtzf_ok: bool = True
    violations: list[CompositeViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "pltzf_ok": self.pltzf_ok,
            "frtzf_ok": self.frtzf_ok,
            "violations": [
                {"code": v.code, "message": v.message, "rule": v.rule}
                for v in self.violations
            ],
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

#: Pattern for one tolerance frame line:
#:   symbol | [D]value[M|L|S] | datum... (datums separated by |)
_LINE_RE = re.compile(
    r"^\s*(?P<symbol>[a-zA-Z_]+)"       # symbol name (no spaces)
    r"\s*\|\s*"                          # first separator
    r"(?P<dia>D?)"                       # optional diameter flag
    r"(?P<value>[0-9]*\.?[0-9]+)"       # tolerance value
    r"(?P<mod>[MLS]?)"                   # optional modifier
    r"(?P<datums>(?:\s*\|\s*[A-Za-z0-9]+)*)"  # zero or more |datum
    r"\s*$",
    re.IGNORECASE,
)

_DATUM_SPLIT_RE = re.compile(r"\s*\|\s*")


def _parse_line(text: str) -> ToleranceFrameLine:
    """Parse one line of a composite frame text."""
    m = _LINE_RE.match(text.strip())
    if not m:
        raise ValueError(
            f"Cannot parse tolerance frame line: {text!r}. "
            "Expected format: 'symbol|[D]value[M|L|S]|datum1|datum2...'. "
            "HONEST FLAG: this parser supports one canonical text form only — "
            "full Unicode/ASCII GD&T requires a dedicated lexer."
        )
    symbol = m.group("symbol").lower()
    dia = m.group("dia").upper() == "D"
    value = float(m.group("value"))
    mod_raw = m.group("mod").upper()
    modifier: Optional[str] = mod_raw if mod_raw else None

    datums_str = m.group("datums")
    datums: list[str] = []
    if datums_str.strip():
        parts = _DATUM_SPLIT_RE.split(datums_str.strip())
        datums = [p.strip().upper() for p in parts if p.strip()]

    return ToleranceFrameLine(
        symbol=symbol,
        tolerance_value=value,
        diameter_zone=dia,
        modifier=modifier,
        datums=datums,
    )


def parse_composite_frame(text: str) -> CompositeFrame:
    """
    Parse a composite tolerance frame from its canonical text representation.

    The two lines (PLTZF / FRTZF) must be separated by a forward slash ``/``.

    Parameters
    ----------
    text:
        E.g. ``"position|D0.5|A|B|C / position|D0.2|A"``.

    Returns
    -------
    CompositeFrame

    Raises
    ------
    ValueError
        If the text cannot be parsed (see HONEST FLAG in module docstring).

    Notes
    -----
    ASME Y14.5-2018 §10.5 composite frames have two rows sharing one symbol
    compartment.  The ``/`` separator is a text convention, not an ASME
    symbol — the standard shows the two lines stacked in a single frame box.
    """
    parts = text.split("/")
    if len(parts) < 2:
        raise ValueError(
            "Composite tolerance frame requires two lines separated by '/'. "
            f"Got: {text!r}. "
            "Expected: 'symbol|tol|datums / symbol|tol|datums' "
            "(ASME Y14.5-2018 §10.5: PLTZF upper line / FRTZF lower line)."
        )
    if len(parts) > 2:
        raise ValueError(
            f"Composite tolerance frame must have exactly two lines (PLTZF / FRTZF). "
            f"Found {len(parts)} '/' separators in: {text!r}. "
            "(ASME Y14.5-2018 §10.5)"
        )

    pltzf = _parse_line(parts[0])
    frtzf = _parse_line(parts[1])
    return CompositeFrame(pltzf=pltzf, frtzf=frtzf, raw_text=text)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_composite_frame(frame: CompositeFrame) -> CompositeValidationReport:
    """
    Validate a composite tolerance frame against ASME Y14.5-2018 §10.5 rules.

    Parameters
    ----------
    frame:
        A :class:`CompositeFrame` produced by :func:`parse_composite_frame`
        (or constructed directly).

    Returns
    -------
    CompositeValidationReport
        ``valid=True`` when all §10.5 rules pass.

    Rules
    -----
    R1  §10.5.1       -- Both PLTZF and FRTZF lines must be present.
    R2  §10.5.1 Note2 -- FRTZF tolerance ≤ PLTZF tolerance.
    R3  §10.5.1(a)    -- FRTZF primary datum must match PLTZF primary datum.
    R4  §10.5.1(b)    -- FRTZF datums must be a subset of PLTZF datums in
                         precedence order; no new datums introduced.
    R5  §10.5.1       -- PLTZF and FRTZF symbol must match.
    """
    violations: list[CompositeViolation] = []
    warnings: list[str] = []
    pltzf = frame.pltzf
    frtzf = frame.frtzf

    # R1: Both lines present (structural — always satisfied after parse,
    #     but guard for direct construction with None).
    if pltzf is None or frtzf is None:
        violations.append(CompositeViolation(
            code="MISSING_FRAME_LINE",
            message=(
                "Composite tolerance frame requires both a PLTZF (upper) line "
                "and a FRTZF (lower) line."
            ),
            rule="ASME Y14.5-2018 §10.5.1",
        ))
        return CompositeValidationReport(
            valid=False,
            violations=violations,
            warnings=warnings,
        )

    # R5: Symbols must match.
    if pltzf.symbol != frtzf.symbol:
        violations.append(CompositeViolation(
            code="SYMBOL_MISMATCH",
            message=(
                f"PLTZF symbol '{pltzf.symbol}' does not match FRTZF symbol "
                f"'{frtzf.symbol}'. Both lines of a composite frame must carry "
                "the same geometric characteristic symbol."
            ),
            rule="ASME Y14.5-2018 §10.5.1",
        ))

    # R2: FRTZF tolerance ≤ PLTZF tolerance (§10.5.1 Note 2).
    if frtzf.tolerance_value > pltzf.tolerance_value:
        violations.append(CompositeViolation(
            code="FRTZF_TOL_EXCEEDS_PLTZF",
            message=(
                f"FRTZF tolerance ({frtzf.tolerance_value}) exceeds PLTZF "
                f"tolerance ({pltzf.tolerance_value}). The feature-relating "
                "tolerance zone must be equal to or smaller than the "
                "pattern-locating tolerance zone."
            ),
            rule="ASME Y14.5-2018 §10.5.1 Note 2",
        ))

    # R3 + R4 only apply when FRTZF has datum references.
    if frtzf.datums:
        # R3: FRTZF primary datum must match PLTZF primary datum (§10.5.1(a)).
        if not pltzf.datums:
            violations.append(CompositeViolation(
                code="PLTZF_NO_PRIMARY_DATUM",
                message=(
                    "FRTZF references datums but PLTZF has no datum references. "
                    "Cannot verify §10.5.1(a) primary-datum matching."
                ),
                rule="ASME Y14.5-2018 §10.5.1(a)",
            ))
        else:
            pltzf_primary = pltzf.datums[0]
            frtzf_primary = frtzf.datums[0]
            if frtzf_primary != pltzf_primary:
                violations.append(CompositeViolation(
                    code="FRTZF_PRIMARY_DATUM_MISMATCH",
                    message=(
                        f"FRTZF primary datum '{frtzf_primary}' does not match "
                        f"PLTZF primary datum '{pltzf_primary}'. Per §10.5.1(a), "
                        "the primary datum in the FRTZF must be the same as the "
                        "primary datum in the PLTZF."
                    ),
                    rule="ASME Y14.5-2018 §10.5.1(a)",
                ))

        # R4: FRTZF datums must be a precedence-ordered subset of PLTZF datums
        #     (§10.5.1(b)).  FRTZF may omit secondary/tertiary (less restrictive),
        #     but must not introduce datums absent from PLTZF or change order.
        pltzf_datum_set = set(pltzf.datums)
        pltzf_order = {label: i for i, label in enumerate(pltzf.datums)}

        for frtzf_datum in frtzf.datums:
            if frtzf_datum not in pltzf_datum_set:
                violations.append(CompositeViolation(
                    code="FRTZF_DATUM_NOT_IN_PLTZF",
                    message=(
                        f"FRTZF datum '{frtzf_datum}' does not appear in the "
                        f"PLTZF datum reference frame ({pltzf.datums}). "
                        "Per §10.5.1(b), the FRTZF may only reference datums "
                        "already established in the PLTZF."
                    ),
                    rule="ASME Y14.5-2018 §10.5.1(b)",
                ))

        # Check that FRTZF datums preserve the precedence order from PLTZF.
        frtzf_in_pltzf = [d for d in frtzf.datums if d in pltzf_order]
        frtzf_positions = [pltzf_order[d] for d in frtzf_in_pltzf]
        if frtzf_positions != sorted(frtzf_positions):
            violations.append(CompositeViolation(
                code="FRTZF_DATUM_ORDER_VIOLATION",
                message=(
                    f"FRTZF datums {frtzf.datums} do not maintain the precedence "
                    f"order established by PLTZF {pltzf.datums}. Per §10.5.1(b), "
                    "datum precedence order must be preserved across both lines."
                ),
                rule="ASME Y14.5-2018 §10.5.1(b)",
            ))
    else:
        # FRTZF with no datums is permitted — it controls only feature-to-feature
        # relationships with no datum constraint (§10.5.1 Fig. 10-27).
        warnings.append(
            "FRTZF has no datum references. The feature-relating tolerance zone "
            "framework will float freely within the PLTZF zone. This is permitted "
            "per ASME Y14.5-2018 §10.5.1 (Fig. 10-27) but provides only "
            "feature-to-feature control, not datum-relative control."
        )

    # Modifier cross-check: warn if FRTZF modifier differs from PLTZF (not a
    # hard violation, but notable per §10.5 intent).
    if pltzf.modifier != frtzf.modifier:
        warnings.append(
            f"PLTZF modifier '{pltzf.modifier}' differs from FRTZF modifier "
            f"'{frtzf.modifier}'. ASME Y14.5-2018 §10.5 permits independent "
            "modifiers per line, but mismatches should be intentional."
        )

    valid = len(violations) == 0
    return CompositeValidationReport(
        valid=valid,
        violations=violations,
        warnings=warnings,
    )
