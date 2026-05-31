"""
PLM Variant Configuration — PTC Windchill variant management + ISO 10303-44 §6.

Manages product variants by selecting which parts/components are active for a given
variant (color, region, market segment), and resolves the variant-specific BOM.

References
----------
* ISO 10303-44:2000 §6 — "Product structure configuration": product variant
  identification, configuration effectivity, and instance-level selection.
* PTC Windchill Variant Management: variant attribute key-value dimensions
  (e.g. "color", "region"), include/exclude rules per part, and resolved
  100%-BOM per variant selection.
* Saaksvuori & Immonen, "Product Lifecycle Management" (2008) §4.3 — variant
  management as attribute-gated BOM selection.

Honest caveats (v1)
-------------------
* Rule application is first-match per part: rules are evaluated in declaration
  order; the FIRST matching rule for a given part determines include/exclude.
  If no rule matches a part it is always INCLUDED (open-world default).
* Rule matching is exact-match on attribute key=value only.  Complex expressions
  (range comparisons, OR across values, NOT) are NOT supported.
* No formal feature-model solver (no constraint propagation, no cardinality
  constraints, no mutual-exclusion groups).  Use a dedicated feature-model
  engine (e.g. FeatureIDE, SPLOT) for full ISO 10303-44 §6 constraint solving.
* Multi-attribute rules require ALL specified attributes to match (implicit AND).
* No rule priority / conflict resolution: first match wins; order your rules
  carefully for deterministic results.
"""

from __future__ import annotations

HONEST_CAVEAT = (
    "PLM-VARIANT-CONFIG v1: rule matching is exact-match key=value, implicit AND. "
    "First-match-per-part wins. No constraint propagation, no feature-model solver, "
    "no mutual-exclusion groups. Parts with no matching rule are always INCLUDED. "
    "Complex AND/OR/NOT variant expressions are NOT supported. "
    "References: ISO 10303-44 §6; PTC Windchill Variant Management."
)

from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class VariantRule:
    """A single include/exclude rule for a part under a variant attribute condition.

    Parameters
    ----------
    part_number:
        The part number this rule applies to (exact match).
    variant_attribute_key:
        The variant attribute dimension key, e.g. "color", "region",
        "market_segment".
    variant_attribute_value:
        The value the attribute must equal for this rule to fire, e.g.
        "red", "EU", "automotive".
    condition:
        "include" — include this part when the attribute matches.
        "exclude" — exclude this part when the attribute matches.

    Notes
    -----
    If *condition* is "include" the part will be EXPLICITLY included when the
    variant attribute matches.  If "exclude" the part will be EXCLUDED.
    Parts with NO matching rules are always included by default (open-world
    assumption per ISO 10303-44 §6.2 opt-in/opt-out effectivity).
    """

    part_number: str
    variant_attribute_key: str
    variant_attribute_value: str
    condition: Literal["include", "exclude"] = "include"

    def __post_init__(self) -> None:
        if self.condition not in ("include", "exclude"):
            raise ValueError(
                f"VariantRule.condition must be 'include' or 'exclude', "
                f"got {self.condition!r}"
            )


@dataclass
class VariantSelection:
    """A concrete variant selection: a named variant with its attribute dict.

    Parameters
    ----------
    variant_id:
        Human-readable variant identifier, e.g. "RED_EU" or "STANDARD_US".
    attributes:
        Dict mapping attribute keys to selected values, e.g.
        {"color": "red", "region": "EU", "market_segment": "automotive"}.
        Keys not present are treated as unset — rules requiring those keys
        will not match.
    """

    variant_id: str
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class VariantResolvedBomEntry:
    """One line in the variant-resolved BOM.

    Parameters
    ----------
    part_number:
        Part identifier.
    qty:
        Quantity in the base BOM.
    included:
        Whether this part is included in the resolved variant BOM.
    reason:
        Human-readable explanation for the include/exclude decision.
    """

    part_number: str
    qty: float
    included: bool
    reason: str


@dataclass
class VariantConfigReport:
    """Result of resolving a variant BOM.

    Attributes
    ----------
    variant_id:
        The variant identifier from the VariantSelection.
    num_total_parts:
        Total number of parts in the base BOM.
    num_included_parts:
        Number of parts included in the resolved variant BOM.
    num_excluded_parts:
        Number of parts excluded from the resolved variant BOM.
    resolved_bom:
        Full list of VariantResolvedBomEntry — one per base-BOM part.
    honest_caveat:
        Module-level caveat string describing limitations.
    """

    variant_id: str
    num_total_parts: int
    num_included_parts: int
    num_excluded_parts: int
    resolved_bom: list[VariantResolvedBomEntry]
    honest_caveat: str = HONEST_CAVEAT

    def included_parts(self) -> list[tuple[str, float]]:
        """Return list of (part_number, qty) for included parts only."""
        return [(e.part_number, e.qty) for e in self.resolved_bom if e.included]

    def excluded_parts(self) -> list[str]:
        """Return list of part_numbers for excluded parts."""
        return [e.part_number for e in self.resolved_bom if not e.included]


# ---------------------------------------------------------------------------
# Core resolution logic
# ---------------------------------------------------------------------------

def _rule_matches(rule: VariantRule, variant: VariantSelection) -> bool:
    """Return True iff the variant selection satisfies the rule's attribute condition.

    Matching is exact-match: variant.attributes[rule.variant_attribute_key] must
    equal rule.variant_attribute_value exactly (case-sensitive).
    """
    actual = variant.attributes.get(rule.variant_attribute_key)
    return actual == rule.variant_attribute_value


def resolve_variant_bom(
    base_bom: list[tuple[str, float]],
    variant_rules: list[VariantRule],
    variant: VariantSelection,
) -> VariantConfigReport:
    """Resolve the variant-specific BOM given a base BOM, rules, and a variant selection.

    For each part in *base_bom*:
      1. Collect all rules whose ``part_number`` matches the part AND whose
         attribute condition matches the variant selection.
      2. Apply FIRST-MATCH semantics: the first matching rule (in *variant_rules*
         declaration order) determines whether the part is included or excluded.
      3. If NO rule matches the part it is ALWAYS INCLUDED (open-world default
         per ISO 10303-44 §6.2).

    Parameters
    ----------
    base_bom:
        List of (part_number, qty) tuples representing the 100% base BOM
        (the superset of all possible parts across all variants).
    variant_rules:
        List of VariantRule objects.  Evaluated in list order per part;
        first matching rule wins.
    variant:
        The VariantSelection specifying which variant we are resolving.

    Returns
    -------
    VariantConfigReport
        Resolved BOM with include/exclude decisions and summary counts.

    Examples
    --------
    >>> base = [("P-001", 1), ("P-002", 2), ("P-003", 1)]
    >>> rules = [VariantRule("P-002", "color", "red", "exclude")]
    >>> sel = VariantSelection("BLUE", {"color": "blue"})
    >>> report = resolve_variant_bom(base, rules, sel)
    >>> report.num_included_parts
    3  # P-002 exclude rule doesn't match "blue"

    >>> sel2 = VariantSelection("RED", {"color": "red"})
    >>> report2 = resolve_variant_bom(base, rules, sel2)
    >>> report2.num_included_parts
    2  # P-002 is excluded for color=red
    """
    resolved: list[VariantResolvedBomEntry] = []

    for part_number, qty in base_bom:
        # Find all rules that target this part
        part_rules = [r for r in variant_rules if r.part_number == part_number]

        included = True  # default: open-world — include if no matching rule
        reason = "no matching rule — included by default"

        for rule in part_rules:
            if _rule_matches(rule, variant):
                if rule.condition == "exclude":
                    included = False
                    reason = (
                        f"excluded by rule: {rule.variant_attribute_key}="
                        f"{rule.variant_attribute_value!r}"
                    )
                else:
                    included = True
                    reason = (
                        f"included by rule: {rule.variant_attribute_key}="
                        f"{rule.variant_attribute_value!r}"
                    )
                break  # first-match wins

        resolved.append(VariantResolvedBomEntry(
            part_number=part_number,
            qty=qty,
            included=included,
            reason=reason,
        ))

    num_included = sum(1 for e in resolved if e.included)
    num_excluded = len(resolved) - num_included

    return VariantConfigReport(
        variant_id=variant.variant_id,
        num_total_parts=len(resolved),
        num_included_parts=num_included,
        num_excluded_parts=num_excluded,
        resolved_bom=resolved,
        honest_caveat=HONEST_CAVEAT,
    )
