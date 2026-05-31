"""
kerf_cad_core.gdt.composite_tolerance_check — Composite tolerance frame validator.

Validates ASME Y14.5-2018 composite (stacked) feature control frames consisting of
a PLTZF (Pattern-Locating Tolerance Zone Framework) on top of one or more FRTZF
(Feature-Relating Tolerance Zone Framework) segments.

ASME Y14.5-2018 references:
  §10.5.2  — Composite Position Tolerance
  §11.6    — Composite Profile Tolerance

Validation rules enforced
--------------------------
R1  All segments must share the same geometric symbol (§10.5.2(a) / §11.6).
R2  Each lower segment tolerance value must be ≤ the segment above it
    (FRTZF tol ≤ PLTZF tol — §10.5.1 Note 2; multi-tier: each tol[i+1] ≤ tol[i]).
R3  Each lower segment's datum references must be a subset of the segment above it
    (FRTZF datums ⊆ PLTZF datums, in precedence order — §10.5.1(b) / §11.6).
    A lower segment may not introduce new datum letters that do not appear in
    the PLTZF segment; doing so would imply location constraint, which is reserved
    for the PLTZF.  The lower segment may only refine orientation.

Honest caveat
-------------
This module validates composite frame *structure* only — it checks that the declared
tolerance values and datum subsets are internally consistent per §10.5.2 / §11.6.
It does NOT measure or verify inspection data against the tolerance zones, does NOT
parse feature control frame text strings from drawings, and does NOT verify that the
declared datums are geometrically compatible with the part model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_VALID_SYMBOLS = frozenset({"position", "profile_surface", "profile_line"})

_VALID_MATERIAL_CONDITIONS = frozenset({"MMC", "LMC", "RFS"})

_HONEST_CAVEAT = (
    "Validates composite frame structure only (symbol consistency, tolerance "
    "monotonicity, datum subset rule per ASME Y14.5-2018 §10.5.2 / §11.6). "
    "Does NOT verify inspection measurement data against tolerance zones, does NOT "
    "parse drawing text, and does NOT check geometric compatibility with the part model."
)

_STANDARD_SECTION = "ASME Y14.5-2018 §10.5.2 (Composite Position) + §11.6 (Composite Profile)"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CompositeTolSegment:
    """
    One segment (one line) of a composite feature control frame.

    Attributes
    ----------
    symbol:
        Geometric characteristic: "position", "profile_surface", or "profile_line".
    tol_value_mm:
        Tolerance zone size in millimetres (> 0).
    datum_refs:
        Ordered list of datum reference letters, e.g. ["A", "B", "C"].
        Empty list is valid for a lower segment that carries no datum references
        (orientation-only or freely-relating segments, §10.5.2).
    material_condition:
        "MMC", "LMC", or "RFS".  Defaults to "RFS".
    """
    symbol: str
    tol_value_mm: float
    datum_refs: list[str] = field(default_factory=list)
    material_condition: str = "RFS"

    def __post_init__(self) -> None:
        sym = self.symbol.strip().lower()
        if sym not in _VALID_SYMBOLS:
            raise ValueError(
                f"CompositeTolSegment: symbol must be one of "
                f"{sorted(_VALID_SYMBOLS)}, got '{self.symbol}'"
            )
        self.symbol = sym

        try:
            val = float(self.tol_value_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"CompositeTolSegment: tol_value_mm must be numeric, got "
                f"'{self.tol_value_mm}'"
            ) from exc
        if val <= 0:
            raise ValueError(
                f"CompositeTolSegment: tol_value_mm must be > 0, got {val}"
            )
        self.tol_value_mm = val

        # Normalise datum refs — strip whitespace, upper-case
        self.datum_refs = [str(d).strip().upper() for d in self.datum_refs]

        mc = str(self.material_condition).strip().upper()
        if mc not in _VALID_MATERIAL_CONDITIONS:
            raise ValueError(
                f"CompositeTolSegment: material_condition must be one of "
                f"{sorted(_VALID_MATERIAL_CONDITIONS)}, got '{self.material_condition}'"
            )
        self.material_condition = mc

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "tol_value_mm": self.tol_value_mm,
            "datum_refs": list(self.datum_refs),
            "material_condition": self.material_condition,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CompositeTolSegment":
        return cls(
            symbol=d["symbol"],
            tol_value_mm=d["tol_value_mm"],
            datum_refs=list(d.get("datum_refs") or []),
            material_condition=d.get("material_condition", "RFS"),
        )


@dataclass
class CompositeFrameSpec:
    """
    A complete composite feature control frame.

    Attributes
    ----------
    feature_id:
        Identifier for the feature being toleranced (e.g. "hole-pattern-A").
    segments:
        Ordered list of segments, top to bottom on the drawing.
        segments[0] is the PLTZF (Pattern-Locating Tolerance Zone Framework).
        segments[1] is the primary FRTZF (Feature-Relating Tolerance Zone Framework).
        segments[2+] are additional refinement segments (multi-tier composite).
        Minimum 2 segments required for a valid composite frame.
    """
    feature_id: str
    segments: list[CompositeTolSegment] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not str(self.feature_id).strip():
            raise ValueError("CompositeFrameSpec: feature_id must not be empty")
        self.feature_id = str(self.feature_id).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "segments": [s.to_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CompositeFrameSpec":
        segments = [
            CompositeTolSegment.from_dict(s)
            for s in (d.get("segments") or [])
        ]
        return cls(
            feature_id=d["feature_id"],
            segments=segments,
        )


@dataclass
class CompositeFrameValidationReport:
    """
    Result of validating a composite feature control frame.

    Attributes
    ----------
    valid:
        True when all rule checks pass; False on any violation.
    violations:
        List of human-readable violation messages, each citing the ASME Y14.5
        rule that was violated.
    standard_section:
        Applicable standard sections.
    honest_caveat:
        Scope limitation notice.
    """
    valid: bool
    violations: list[str] = field(default_factory=list)
    standard_section: str = _STANDARD_SECTION
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "violations": list(self.violations),
            "standard_section": self.standard_section,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

def validate_composite_frame(spec: CompositeFrameSpec) -> CompositeFrameValidationReport:
    """
    Validate a composite feature control frame against ASME Y14.5-2018 §10.5.2
    (Composite Position) and §11.6 (Composite Profile).

    Rules applied
    -------------
    R1  All segments must share the same geometric symbol.
        (§10.5.2(a): "both tolerance zones are described by the same symbol.")
    R2  Segment[i+1].tol_value_mm ≤ Segment[i].tol_value_mm for every i.
        (§10.5.1 Note 2: FRTZF tolerance ≤ PLTZF tolerance.)
    R3  Segment[i+1].datum_refs ⊆ Segment[i].datum_refs (as an ordered set check:
        every datum in the lower segment must appear in the upper segment).
        (§10.5.1(b): "The datum reference letters … of the FRTZF … must be a
        subset of the datum reference frame of the PLTZF.")

    Returns a CompositeFrameValidationReport. Never raises on bad/incomplete input.
    """
    violations: list[str] = []

    # Need at least 2 segments to form a composite frame
    if len(spec.segments) < 2:
        violations.append(
            f"Composite frame for '{spec.feature_id}' has {len(spec.segments)} "
            "segment(s); at least 2 are required (PLTZF + FRTZF). "
            "(ASME Y14.5-2018 §10.5.2)"
        )
        return CompositeFrameValidationReport(valid=False, violations=violations)

    pltzf = spec.segments[0]

    # ── R1: All segments must share the same symbol ────────────────────────
    for i, seg in enumerate(spec.segments[1:], start=1):
        if seg.symbol != pltzf.symbol:
            violations.append(
                f"R1 (symbol mismatch): segment[{i}] symbol '{seg.symbol}' differs "
                f"from PLTZF (segment[0]) symbol '{pltzf.symbol}'. All segments of a "
                "composite frame must use the same geometric characteristic symbol. "
                "(ASME Y14.5-2018 §10.5.2(a) / §11.6)"
            )

    # ── R2: Each lower segment tolerance ≤ segment above it ───────────────
    for i in range(1, len(spec.segments)):
        upper = spec.segments[i - 1]
        lower = spec.segments[i]
        if lower.tol_value_mm > upper.tol_value_mm:
            violations.append(
                f"R2 (tolerance not shrinking): segment[{i}] tol_value_mm "
                f"{lower.tol_value_mm} > segment[{i - 1}] tol_value_mm "
                f"{upper.tol_value_mm}. Each lower segment must have a tolerance "
                "value ≤ the segment above it (FRTZF tol ≤ PLTZF tol). "
                "(ASME Y14.5-2018 §10.5.1 Note 2)"
            )

    # ── R3: Lower segment datum refs must be subset of segment above ────────
    # §10.5.1(b): FRTZF datums must be a subset of PLTZF datums (no new datums).
    # For multi-tier: segment[i+1].datums ⊆ segment[i].datums.
    for i in range(1, len(spec.segments)):
        upper = spec.segments[i - 1]
        lower = spec.segments[i]
        upper_set = set(upper.datum_refs)
        lower_set = set(lower.datum_refs)
        extra_datums = lower_set - upper_set
        if extra_datums:
            violations.append(
                f"R3 (datum not a subset): segment[{i}] introduces datum(s) "
                f"{sorted(extra_datums)} that do not appear in segment[{i - 1}] "
                f"datums {sorted(upper.datum_refs)}. A lower segment may only "
                "reference datums that are already in the segment above it — "
                "new datums would imply location constraint, which is reserved "
                "for the PLTZF (FRTZF may only refine orientation). "
                "(ASME Y14.5-2018 §10.5.1(b) / §11.6)"
            )

    return CompositeFrameValidationReport(
        valid=len(violations) == 0,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# LLM tool wrapper (gated import)
# ---------------------------------------------------------------------------

try:
    import json as _json
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]  # noqa: F401

    _gdt_validate_composite_frame_spec = ToolSpec(
        name="gdt_validate_composite_frame",
        description=(
            "Validate an ASME Y14.5-2018 composite (stacked) feature control frame "
            "consisting of a PLTZF (Pattern-Locating Tolerance Zone Framework) "
            "on top of one or more FRTZF (Feature-Relating Tolerance Zone Framework) "
            "segments.\n"
            "\n"
            "Rules checked (§10.5.2 Composite Position + §11.6 Composite Profile):\n"
            "  R1  All segments share the same geometric symbol (position / "
            "profile_surface / profile_line).\n"
            "  R2  Each lower segment tolerance ≤ the segment above it "
            "(FRTZF tol ≤ PLTZF tol, §10.5.1 Note 2).\n"
            "  R3  Lower segment datum_refs ⊆ upper segment datum_refs — no new "
            "datums allowed below the PLTZF (§10.5.1(b)).\n"
            "\n"
            "symbol options: position | profile_surface | profile_line\n"
            "material_condition options: MMC | LMC | RFS (default RFS)\n"
            "\n"
            "Returns {valid, violations, standard_section, honest_caveat}.\n"
            "HONEST FLAG: validates frame structure only — does not verify inspection "
            "measurement data against the tolerance zones."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "feature_id": {
                    "type": "string",
                    "description": "Identifier for the feature being toleranced.",
                },
                "segments": {
                    "type": "array",
                    "description": (
                        "Ordered list of composite frame segments, top to bottom. "
                        "Index 0 = PLTZF, index 1 = FRTZF, index 2+ = additional "
                        "refinement segments (multi-tier). Minimum 2 segments."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol": {
                                "type": "string",
                                "enum": ["position", "profile_surface", "profile_line"],
                                "description": "Geometric characteristic (same for all segments).",
                            },
                            "tol_value_mm": {
                                "type": "number",
                                "description": "Tolerance zone size in mm (> 0).",
                            },
                            "datum_refs": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Ordered datum reference letters (e.g. ['A','B','C']). "
                                    "Lower segments must be a subset of the segment above."
                                ),
                            },
                            "material_condition": {
                                "type": "string",
                                "enum": ["MMC", "LMC", "RFS"],
                                "description": "Material condition modifier. Default RFS.",
                            },
                        },
                        "required": ["symbol", "tol_value_mm"],
                    },
                    "minItems": 2,
                },
            },
            "required": ["feature_id", "segments"],
        },
    )

    @register(_gdt_validate_composite_frame_spec, write=False)
    async def run_gdt_validate_composite_frame(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        feature_id = str(a.get("feature_id", "")).strip()
        if not feature_id:
            return err_payload("feature_id is required", "BAD_ARGS")

        raw_segments = a.get("segments")
        if not isinstance(raw_segments, list) or len(raw_segments) < 2:
            return err_payload(
                "segments must be an array with at least 2 items "
                "(PLTZF + FRTZF)",
                "BAD_ARGS",
            )

        segments: list[CompositeTolSegment] = []
        for i, s in enumerate(raw_segments):
            if not isinstance(s, dict):
                return err_payload(f"segments[{i}] must be an object", "BAD_ARGS")
            try:
                segments.append(CompositeTolSegment.from_dict(s))
            except (ValueError, KeyError) as exc:
                return err_payload(f"segments[{i}]: {exc}", "BAD_ARGS")

        try:
            spec = CompositeFrameSpec(feature_id=feature_id, segments=segments)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        report = validate_composite_frame(spec)
        return ok_payload(report.to_dict())

    _TOOL_REGISTERED = True

except ImportError:
    # Registry not available (pure unit-test context or kerf_chat not installed).
    # The data model and validate_composite_frame() remain fully usable.
    _TOOL_REGISTERED = False
