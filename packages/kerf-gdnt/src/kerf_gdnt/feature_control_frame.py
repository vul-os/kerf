"""
Feature Control Frame (FCF) data model.

An FCF encodes a single geometric tolerance callout in the form:

    |<symbol>|<diameter?><value><modifier?>|<datumA><modA?>|<datumB><modB?>|<datumC><modC?>|

Reference:
  ISO 1101:2017 §16; ASME Y14.5-2018 §3.3.1

Canonical textual rendering (used in tests and serialisation)::

    ⏐⌖⏐∅0.5 Ⓜ ⏐A⏐B⏐C⏐

The leading/trailing ⏐ marks are frame compartment dividers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from kerf_gdnt.symbols import (
    GDTSymbol,
    Modifier,
    ALL_SYMBOLS,
    ALL_MODIFIERS,
    MODIFIER_DIAMETER,
)


@dataclass
class DatumReference:
    """A single datum reference inside an FCF datum compartment."""
    label: str               # e.g. "A", "B", "C", "A1"
    modifier: Optional[str] = None  # modifier code, e.g. "M", "L", "S"

    def render(self) -> str:
        mod_str = ""
        if self.modifier:
            mod = ALL_MODIFIERS.get(self.modifier)
            mod_str = f" {mod.unicode}" if mod else f" {self.modifier}"
        return f"{self.label}{mod_str}"


@dataclass
class FeatureControlFrame:
    """
    Full Feature Control Frame.

    Parameters
    ----------
    symbol_code:
        One of the codes from :data:`kerf_gdnt.symbols.ALL_SYMBOLS`,
        e.g. ``"position"``, ``"flatness"``.
    tolerance_value:
        Numeric tolerance (in drawing units, typically mm or inches).
    diameter_zone:
        If ``True``, prefix the tolerance with the diameter symbol ⌀
        (used for cylindrical tolerance zones per ASME Y14.5-2018 §3.3.17).
    tolerance_modifier:
        Modifier code applied to the tolerance value compartment:
        ``"M"`` (MMC), ``"L"`` (LMC), ``"S"`` (RFS), ``"P"`` (projected), etc.
    datum_refs:
        Ordered list of datum references (primary, secondary, tertiary).
        Most tolerance types allow 0–3 datum references.
    note:
        Optional free-text annotation (not part of the standard FCF frame).
    """

    symbol_code: str
    tolerance_value: float
    diameter_zone: bool = False
    tolerance_modifier: Optional[str] = None   # "M", "L", "S", "F", "P", "T"
    datum_refs: list[DatumReference] = field(default_factory=list)
    note: Optional[str] = None

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @property
    def symbol(self) -> GDTSymbol:
        """Resolved :class:`~kerf_gdnt.symbols.GDTSymbol`."""
        try:
            return ALL_SYMBOLS[self.symbol_code]
        except KeyError as exc:
            raise ValueError(f"Unknown GD&T symbol code: {self.symbol_code!r}") from exc

    def validate(self) -> list[str]:
        """Return a (possibly empty) list of validation issues."""
        issues: list[str] = []
        if self.symbol_code not in ALL_SYMBOLS:
            issues.append(f"Unknown symbol code: {self.symbol_code!r}")
        if self.tolerance_value < 0:
            issues.append("Tolerance value must be non-negative.")
        if self.tolerance_modifier and self.tolerance_modifier not in ALL_MODIFIERS:
            issues.append(f"Unknown tolerance modifier: {self.tolerance_modifier!r}")
        if len(self.datum_refs) > 3:
            issues.append("An FCF may reference at most three datums (primary, secondary, tertiary).")
        for dr in self.datum_refs:
            if dr.modifier and dr.modifier not in ALL_MODIFIERS:
                issues.append(f"Unknown datum modifier: {dr.modifier!r}")
        return issues

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def render(self, *, precision: int = 4) -> str:
        """
        Render the FCF to its canonical Unicode text form.

        Example::

            ⏐⌖⏐∅0.5 Ⓜ ⏐A⏐B⏐C⏐
        """
        sym_char = self.symbol.unicode
        dia_prefix = MODIFIER_DIAMETER.unicode if self.diameter_zone else ""
        tol_str = f"{self.tolerance_value:.{precision}g}"
        mod_str = ""
        if self.tolerance_modifier:
            mod = ALL_MODIFIERS.get(self.tolerance_modifier)
            if mod:
                mod_str = f" {mod.unicode}"

        # tolerance compartment: |dia?tol modifier?|
        tol_compartment = f"{dia_prefix}{tol_str}{mod_str}"

        # datum compartments
        datum_compartments = "".join(
            f"⏐{dr.render()}" for dr in self.datum_refs
        )

        # Final form: ⏐symbol⏐tol_compartment⏐datumA⏐datumB...⏐
        # (no trailing separator if no datums)
        trailing = "⏐" if self.datum_refs else ""
        return f"⏐{sym_char}⏐{tol_compartment}{datum_compartments}{trailing}"

    def to_dict(self) -> dict:
        """Serialise to a plain ``dict`` for JSON transport."""
        return {
            "symbol_code": self.symbol_code,
            "symbol_unicode": self.symbol.unicode,
            "symbol_name": self.symbol.name,
            "tolerance_value": self.tolerance_value,
            "diameter_zone": self.diameter_zone,
            "tolerance_modifier": self.tolerance_modifier,
            "datum_refs": [
                {"label": dr.label, "modifier": dr.modifier}
                for dr in self.datum_refs
            ],
            "rendered": self.render(),
            "note": self.note,
        }

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "FeatureControlFrame":
        """Deserialise from a plain ``dict``."""
        datum_refs = [
            DatumReference(label=dr["label"], modifier=dr.get("modifier"))
            for dr in data.get("datum_refs", [])
        ]
        return cls(
            symbol_code=data["symbol_code"],
            tolerance_value=float(data["tolerance_value"]),
            diameter_zone=bool(data.get("diameter_zone", False)),
            tolerance_modifier=data.get("tolerance_modifier"),
            datum_refs=datum_refs,
            note=data.get("note"),
        )
