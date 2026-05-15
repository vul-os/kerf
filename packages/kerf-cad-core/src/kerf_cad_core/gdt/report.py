"""
kerf_cad_core.gdt.report — GD&T callout report builder.

``gdt_callout_report(features)`` accepts a list of dicts (each describing a
GeometricTolerance) and returns a structured report: a formatted text callout
list plus a machine-readable summary list.

No OCC dependency; no DB access required.
"""
from __future__ import annotations

from typing import Any

from kerf_cad_core.gdt.tolerances import GeometricTolerance, ToleranceSymbol
from kerf_cad_core.gdt.modifiers import ToleranceModifier


# ── Symbol → drawing character mapping ───────────────────────────────────────

_SYMBOL_CHARS: dict[ToleranceSymbol, str] = {
    ToleranceSymbol.FLATNESS:           "⏥",
    ToleranceSymbol.STRAIGHTNESS:       "⏤",
    ToleranceSymbol.CIRCULARITY:        "○",
    ToleranceSymbol.CYLINDRICITY:       "⌭",
    ToleranceSymbol.PROFILE_LINE:       "⌒",
    ToleranceSymbol.PROFILE_SURFACE:    "⌓",
    ToleranceSymbol.PARALLELISM:        "∥",
    ToleranceSymbol.PERPENDICULARITY:   "⊥",
    ToleranceSymbol.ANGULARITY:         "∠",
    ToleranceSymbol.POSITION:           "⊕",
    ToleranceSymbol.CONCENTRICITY:      "◎",
    ToleranceSymbol.SYMMETRY:           "≡",
    ToleranceSymbol.RUNOUT:             "↗",
    ToleranceSymbol.TOTAL_RUNOUT:       "⟿",
}

_MODIFIER_CHARS: dict[ToleranceModifier, str] = {
    ToleranceModifier.MMC:              "(M)",
    ToleranceModifier.LMC:              "(L)",
    ToleranceModifier.RFS:              "(S)",
    ToleranceModifier.PROJECTED:        "(P)",
    ToleranceModifier.TANGENT:          "(T)",
    ToleranceModifier.FREE_STATE:       "(F)",
    ToleranceModifier.STATISTICAL:      "<ST>",
    ToleranceModifier.CONTINUOUS_FEATURE: "CF",
    ToleranceModifier.INDEPENDENCY:     "(I)",
    ToleranceModifier.UNEQUAL_BILATERAL: "UZ",
}


def _format_callout(tol: GeometricTolerance) -> str:
    """
    Render a single feature control frame as a text callout.

    Format:
        | symbol | [⌀]tol_value [modifier...] | [datum_labels] |

    Example:
        ⊕ | ⌀0.050 (M) | A | B | C
    """
    sym_char = _SYMBOL_CHARS.get(tol.symbol, tol.symbol.value)

    zone_prefix = "⌀" if tol.diameter_zone else ""
    tol_str = f"{zone_prefix}{tol.tolerance_value:.4g}"

    mod_parts: list[str] = []
    for mod in tol.modifiers:
        mod_parts.append(_MODIFIER_CHARS.get(mod, mod.value))
        if mod == ToleranceModifier.PROJECTED and tol.projected_zone_height is not None:
            mod_parts.append(f"{tol.projected_zone_height:.4g}")

    datum_parts = tol.datum_ref.labels

    compartments = [sym_char, tol_str + (" " + " ".join(mod_parts) if mod_parts else "")]
    compartments.extend(datum_parts)

    frame = " | ".join(compartments)
    return f"[{frame}]  ← {tol.feature_name}"


def gdt_callout_report(features: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Build a GD&T callout report from a list of feature dicts.

    Parameters
    ----------
    features:
        List of dicts, each serialisable to a GeometricTolerance via
        ``GeometricTolerance.from_dict()``.

    Returns
    -------
    dict with keys:
        ``callouts``    — list of formatted callout strings (one per feature)
        ``summary``     — list of machine-readable dicts (GeometricTolerance.to_dict())
        ``count``       — total number of callouts
        ``by_category`` — dict mapping category name → count
        ``text``        — full formatted report as a single newline-joined string
    """
    if not isinstance(features, list):
        raise TypeError("features must be a list of dicts")

    parsed: list[GeometricTolerance] = []
    errors: list[str] = []

    for i, raw in enumerate(features):
        try:
            t = GeometricTolerance.from_dict(raw)
            parsed.append(t)
        except Exception as exc:
            errors.append(f"feature[{i}]: {exc}")

    callouts: list[str] = [_format_callout(t) for t in parsed]
    summary: list[dict] = [t.to_dict() for t in parsed]

    by_category: dict[str, int] = {}
    for t in parsed:
        cat = t.category
        by_category[cat] = by_category.get(cat, 0) + 1

    lines = ["GD&T Callout Report", "=" * 40]
    for callout in callouts:
        lines.append(callout)
    if errors:
        lines.append("")
        lines.append("Parse errors:")
        lines.extend(f"  {e}" for e in errors)
    lines.append("")
    lines.append(f"Total: {len(parsed)} callout(s)")
    for cat, cnt in sorted(by_category.items()):
        lines.append(f"  {cat}: {cnt}")

    return {
        "callouts": callouts,
        "summary": summary,
        "count": len(parsed),
        "by_category": by_category,
        "text": "\n".join(lines),
        "parse_errors": errors,
    }
