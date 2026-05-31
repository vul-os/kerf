"""
kerf_cad_core.gdt.datum_shift_check — ASME Y14.5-2018 Datum Shift (MMC/LMC) checker.

Computes datum shift (bonus tolerance on datum features) for a Datum Reference
Frame (DRF) where datum features carry MMC or LMC material condition modifiers.

ASME Y14.5-2018 references:
  §4.5   — Datum Shift: when a datum feature of size is referenced at MMC (or LMC)
            in the feature control frame, the datum feature axis (or centre plane)
            may shift relative to the datum reference frame by the amount the
            datum feature departs from its MMC (or LMC) size.
  §7.3.5 — Effect of Material Condition Modifiers on Datum Features of Size:
            the datum shift allowance equals the difference between the MMC/LMC
            size of the datum feature and its actual mating size.

Physics recap
--------------
Given a datum feature of size with:
  - MMC size  = D_mmc   (smallest hole or largest shaft at maximum material)
  - LMC size  = D_lmc   (largest hole or smallest shaft at least material)
  - Measured actual size = D_actual

MMC modifier (most common — "bonus tolerance at MMC"):
  shift = |D_actual - D_mmc|
  total = base_position_tolerance + shift

LMC modifier (inner-boundary protection):
  shift = |D_actual - D_lmc|
  total = base_position_tolerance + shift

RFS modifier (regardless of feature size):
  shift = 0
  total = base_position_tolerance

Honest caveat
-------------
This module computes per-datum shift for a single datum feature of size.
Multi-datum DRF interactions (secondary shift constrained by primary fixation,
tertiary by secondary — §4.11.4) are computed datum-by-datum independently.
Composite DRF frame validation (PLTZF/FRTZF subset rules) is handled separately
in ``kerf_cad_core.gdt.composite_tolerance_check``.  Geometric constraint
propagation through a full 3-D fixture simulation is out of scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_VALID_MATERIAL_CONDITIONS = frozenset({"MMC", "LMC", "RFS"})

_CODE_SECTION = "ASME Y14.5-2018 §4.5 (Datum Shift) + §7.3.5 (MMC/LMC on datum features)"

_HONEST_CAVEAT = (
    "Per-datum shift computed independently (§4.5 + §7.3.5): "
    "shift = |measured - MMC| for MMC modifier, |measured - LMC| for LMC modifier, "
    "0 for RFS. Multi-datum DRF secondary/tertiary cascade interactions are computed "
    "datum-by-datum; full 3-D DRF fixture constraint propagation is out of scope. "
    "Composite frame validation (PLTZF/FRTZF) is in gdt.composite_tolerance_check."
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DatumFeatureSpec:
    """
    Specification for a datum feature of size referenced in a DRF.

    Attributes
    ----------
    datum_letter:
        Datum identifier letter, e.g. "A", "B", "C".
    mmc_size_mm:
        Maximum Material Condition size in mm.
        For a hole: smallest acceptable diameter (most material → smallest hole).
        For a shaft: largest acceptable diameter (most material → largest shaft).
    lmc_size_mm:
        Least Material Condition size in mm.
        For a hole: largest acceptable diameter.
        For a shaft: smallest acceptable diameter.
    measured_size_mm:
        Actual measured mating size of the datum feature (mm).
    material_condition_modifier:
        Material condition modifier applied to the datum feature reference:
        "MMC" | "LMC" | "RFS".
    """
    datum_letter: str
    mmc_size_mm: float
    lmc_size_mm: float
    measured_size_mm: float
    material_condition_modifier: str

    def __post_init__(self) -> None:
        letter = str(self.datum_letter).strip().upper()
        if not letter:
            raise ValueError("DatumFeatureSpec: datum_letter must not be empty")
        self.datum_letter = letter

        try:
            mmc = float(self.mmc_size_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"DatumFeatureSpec: mmc_size_mm must be numeric, got '{self.mmc_size_mm}'"
            ) from exc
        if mmc <= 0:
            raise ValueError(
                f"DatumFeatureSpec: mmc_size_mm must be > 0, got {mmc}"
            )
        self.mmc_size_mm = mmc

        try:
            lmc = float(self.lmc_size_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"DatumFeatureSpec: lmc_size_mm must be numeric, got '{self.lmc_size_mm}'"
            ) from exc
        if lmc <= 0:
            raise ValueError(
                f"DatumFeatureSpec: lmc_size_mm must be > 0, got {lmc}"
            )
        self.lmc_size_mm = lmc

        try:
            measured = float(self.measured_size_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"DatumFeatureSpec: measured_size_mm must be numeric, "
                f"got '{self.measured_size_mm}'"
            ) from exc
        if measured <= 0:
            raise ValueError(
                f"DatumFeatureSpec: measured_size_mm must be > 0, got {measured}"
            )
        self.measured_size_mm = measured

        mc = str(self.material_condition_modifier).strip().upper()
        if mc not in _VALID_MATERIAL_CONDITIONS:
            raise ValueError(
                f"DatumFeatureSpec: material_condition_modifier must be one of "
                f"{sorted(_VALID_MATERIAL_CONDITIONS)}, got '{self.material_condition_modifier}'"
            )
        self.material_condition_modifier = mc

    def to_dict(self) -> dict[str, Any]:
        return {
            "datum_letter": self.datum_letter,
            "mmc_size_mm": self.mmc_size_mm,
            "lmc_size_mm": self.lmc_size_mm,
            "measured_size_mm": self.measured_size_mm,
            "material_condition_modifier": self.material_condition_modifier,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatumFeatureSpec":
        return cls(
            datum_letter=d["datum_letter"],
            mmc_size_mm=d["mmc_size_mm"],
            lmc_size_mm=d["lmc_size_mm"],
            measured_size_mm=d["measured_size_mm"],
            material_condition_modifier=d.get("material_condition_modifier", "RFS"),
        )


@dataclass
class DatumShiftReport:
    """
    Result of computing datum shift for one datum feature in a DRF.

    Attributes
    ----------
    datum_letter:
        Datum identifier letter.
    base_tolerance_zone_mm:
        The stated position (or other) tolerance from the feature control frame (mm).
    bonus_shift_mm:
        Datum shift allowance (mm).  Zero when modifier is RFS or when the
        datum feature is at its MMC/LMC boundary.
    total_available_tolerance_mm:
        Effective total tolerance: base_tolerance_zone_mm + bonus_shift_mm.
    shift_allowed:
        True when the material condition modifier permits datum shift
        (MMC or LMC); False for RFS.
    code_section:
        Applicable ASME Y14.5-2018 section references.
    honest_caveat:
        Scope limitation notice.
    """
    datum_letter: str
    base_tolerance_zone_mm: float
    bonus_shift_mm: float
    total_available_tolerance_mm: float
    shift_allowed: bool
    code_section: str = _CODE_SECTION
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "datum_letter": self.datum_letter,
            "base_tolerance_zone_mm": self.base_tolerance_zone_mm,
            "bonus_shift_mm": self.bonus_shift_mm,
            "total_available_tolerance_mm": self.total_available_tolerance_mm,
            "shift_allowed": self.shift_allowed,
            "code_section": self.code_section,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_datum_shift(
    datum: DatumFeatureSpec,
    base_position_tolerance_mm: float,
) -> DatumShiftReport:
    """
    Compute datum shift (bonus tolerance) for a datum feature of size.

    Per ASME Y14.5-2018 §4.5 + §7.3.5:
    - MMC modifier: shift = |measured_size - mmc_size|
    - LMC modifier: shift = |measured_size - lmc_size|
    - RFS modifier: shift = 0 (no shift, regardless of departure from MMC/LMC)

    The total available tolerance zone for the toleranced feature is:
        total = base_position_tolerance + bonus_shift

    Parameters
    ----------
    datum:
        DatumFeatureSpec describing the datum feature dimensions and modifier.
    base_position_tolerance_mm:
        The stated position tolerance value from the feature control frame (mm).
        Must be > 0.

    Returns
    -------
    DatumShiftReport
        Contains bonus_shift_mm, total_available_tolerance_mm, and shift_allowed.

    Raises
    ------
    ValueError
        If base_position_tolerance_mm is not positive.
    """
    try:
        base = float(base_position_tolerance_mm)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"compute_datum_shift: base_position_tolerance_mm must be numeric, "
            f"got '{base_position_tolerance_mm}'"
        ) from exc
    if base <= 0:
        raise ValueError(
            f"compute_datum_shift: base_position_tolerance_mm must be > 0, got {base}"
        )

    mc = datum.material_condition_modifier  # already normalised in __post_init__

    if mc == "RFS":
        bonus_shift = 0.0
        shift_allowed = False
    elif mc == "MMC":
        # §4.5: datum shift = departure from MMC
        bonus_shift = abs(datum.measured_size_mm - datum.mmc_size_mm)
        shift_allowed = True
    elif mc == "LMC":
        # §7.3.5: datum shift = departure from LMC
        bonus_shift = abs(datum.measured_size_mm - datum.lmc_size_mm)
        shift_allowed = True
    else:
        # Should not reach here — validated in DatumFeatureSpec.__post_init__
        bonus_shift = 0.0
        shift_allowed = False

    # Round to avoid floating-point accumulation noise (< 1 nm resolution)
    bonus_shift = round(bonus_shift, 10)
    total = round(base + bonus_shift, 10)

    return DatumShiftReport(
        datum_letter=datum.datum_letter,
        base_tolerance_zone_mm=base,
        bonus_shift_mm=bonus_shift,
        total_available_tolerance_mm=total,
        shift_allowed=shift_allowed,
    )


# ---------------------------------------------------------------------------
# LLM tool wrapper (gated import — registry not available in unit-test context)
# ---------------------------------------------------------------------------

try:
    import json as _json
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]  # noqa: F401

    _gdt_compute_datum_shift_spec = ToolSpec(
        name="gdt_compute_datum_shift",
        description=(
            "Compute ASME Y14.5-2018 datum shift (bonus tolerance) for a datum "
            "feature of size referenced in a Datum Reference Frame (DRF) with an "
            "MMC or LMC material condition modifier.\n"
            "\n"
            "Datum shift (§4.5 + §7.3.5) is the extra tolerance available to the "
            "toleranced feature when the datum feature departs from its MMC or LMC "
            "boundary:\n"
            "  MMC modifier: shift = |measured_size - mmc_size|\n"
            "  LMC modifier: shift = |measured_size - lmc_size|\n"
            "  RFS modifier: shift = 0 (no bonus regardless of departure)\n"
            "\n"
            "total_available_tolerance = base_position_tolerance + bonus_shift\n"
            "\n"
            "material_condition_modifier options: MMC | LMC | RFS\n"
            "\n"
            "Returns {datum_letter, base_tolerance_zone_mm, bonus_shift_mm, "
            "total_available_tolerance_mm, shift_allowed, code_section, honest_caveat}.\n"
            "\n"
            "HONEST FLAG: per-datum shift only — multi-datum DRF cascade interactions "
            "(secondary shift constrained by primary fixation, §4.11.4) are computed "
            "datum-by-datum; composite frame validation (§10.5.2 PLTZF/FRTZF) is "
            "separate (use gdt_validate_composite_frame)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "datum_letter": {
                    "type": "string",
                    "description": "Datum identifier letter, e.g. 'A', 'B', 'C'.",
                },
                "mmc_size_mm": {
                    "type": "number",
                    "description": (
                        "Maximum Material Condition size in mm (> 0). "
                        "For a hole: smallest acceptable diameter. "
                        "For a shaft: largest acceptable diameter."
                    ),
                },
                "lmc_size_mm": {
                    "type": "number",
                    "description": (
                        "Least Material Condition size in mm (> 0). "
                        "For a hole: largest acceptable diameter. "
                        "For a shaft: smallest acceptable diameter."
                    ),
                },
                "measured_size_mm": {
                    "type": "number",
                    "description": "Actual measured mating size of the datum feature (mm, > 0).",
                },
                "material_condition_modifier": {
                    "type": "string",
                    "enum": ["MMC", "LMC", "RFS"],
                    "description": (
                        "Material condition modifier on the datum feature reference. "
                        "MMC: bonus when feature departs from MMC (most common for holes). "
                        "LMC: bonus when feature departs from LMC (inner-boundary protection). "
                        "RFS: no datum shift (zero bonus, always)."
                    ),
                },
                "base_position_tolerance_mm": {
                    "type": "number",
                    "description": (
                        "Stated position (or other geometric) tolerance from the "
                        "feature control frame (mm, > 0)."
                    ),
                },
            },
            "required": [
                "datum_letter",
                "mmc_size_mm",
                "lmc_size_mm",
                "measured_size_mm",
                "material_condition_modifier",
                "base_position_tolerance_mm",
            ],
        },
    )

    @register(_gdt_compute_datum_shift_spec, write=False)
    async def run_gdt_compute_datum_shift(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        # Validate required fields
        for field_name in (
            "datum_letter",
            "mmc_size_mm",
            "lmc_size_mm",
            "measured_size_mm",
            "material_condition_modifier",
            "base_position_tolerance_mm",
        ):
            if field_name not in a:
                return err_payload(f"'{field_name}' is required", "BAD_ARGS")

        try:
            datum = DatumFeatureSpec.from_dict(a)
        except (ValueError, KeyError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        base_tol = a.get("base_position_tolerance_mm")
        if base_tol is None:
            return err_payload("'base_position_tolerance_mm' is required", "BAD_ARGS")
        try:
            base_tol = float(base_tol)
        except (TypeError, ValueError):
            return err_payload(
                "base_position_tolerance_mm must be a number", "BAD_ARGS"
            )

        try:
            report = compute_datum_shift(datum, base_tol)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(report.to_dict())

    _TOOL_REGISTERED = True

except ImportError:
    # Registry not available (pure unit-test context or kerf_chat not installed).
    # DatumFeatureSpec, DatumShiftReport, and compute_datum_shift() remain fully usable.
    _TOOL_REGISTERED = False
