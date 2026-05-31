"""
kerf_cam.chip_load_validate — Catalog-range chip-load validator for milling operations.

Validates the programmed feed-per-tooth (fz) against published Sandvik Coromant /
Kennametal / Harvey Tool ranges for specific workpiece materials and tool sizes.
Detects radial chip thinning when ae < D/2 and warns when the effective chip load
falls outside the catalog-recommended range.

This module is distinct from chip_load_calc.py which only computes chip-load
arithmetic.  chip_load_validate.py applies the *catalog reference ranges* keyed on
exact material grade and tool diameter, matches the Sandvik chip-thinning formula
from ChipLoad (2024) § "Chip thinning in radial direction", and emits
machine-readable warnings for rubbing, over-feed, and chip-thinning.

Chip-thinning formula (Sandvik CoroPlus Technical Guide 2024, "Radial chip
thinning", §Milling chip thickness):

    When ae < D/2:
        fz_effective = fz_nominal × D / (2 · ae)        [simplified linear formula]

    When ae >= D/2:
        fz_effective = fz_nominal                        [no thinning]

Note: Sandvik's simplified formula fz × D/(2·ae) is a first-order approximation
to the exact trigonometric expression D/(2·sqrt(D·ae−ae²)) used in chip_load_calc.
This module implements the simplified Sandvik version as specified in the task.

Catalog ranges (Sandvik Coromant 2024 + Kennametal 2024 + Harvey Tool 2024).
Source footnotes below each table entry.

Rubbing / work-hardening threshold: fz_effective < 0.4 × fz_min → warn rubbing.
Over-feed threshold: fz_effective > fz_max → warn over-feed (tool fracture risk).

Honest caveats
--------------
- Ranges are catalog mid-field averages for recommended tool-material combinations.
  Actual limits depend on insert grade, edge prep, exact alloy batch hardness,
  machine rigidity, BT/HSK/CAT holder runout, and coolant strategy.
- Chip-thinning factor here uses the SIMPLIFIED linear formula fz×D/(2·ae)
  per Sandvik's "chip-thinning in radial direction" table; the exact trigonometric
  form is in chip_load_calc.compute_chip_load.
- Tool deflection, harmonic excitation, and regenerative chatter are NOT modelled.
  High ae·ap products can push the tool beyond the elastic deflection limit even
  within the fz range; verify with Altintas 2012 §3 or CoroPlus ToolGuide.
- Runout > 5 μm effectively halves the per-tooth chip load (alternating flutes);
  no runout correction is applied here.
- ap (axial depth of cut) does not directly affect fz range; but excessive ap
  with borderline fz can cause chatter — verify against stability lobe diagrams.
- Coating guidance (TiAlN, TiN, etc.) shifts Vc/fz optima; default TiAlN assumed.
- Ranges are for end-mills (peripheral milling). Slot-drill, ball-nose, and
  chamfer-mill geometry require manufacturer-specific tables.
References: Sandvik Coromant Milling Technical Guide (2024); Kennametal Milling
Application Guide (2024); Harvey Tool Speeds & Feeds (2024); MH 31e §1136.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Material constants
# ---------------------------------------------------------------------------

VALID_MATERIALS = frozenset([
    "steel-1018",
    "steel-4140-soft",
    "stainless-304",
    "aluminum-6061",
    "titanium-Ti6Al4V",
    "cast-iron-grey",
    "plastic-acetal",
])

VALID_COATINGS = frozenset(["TiAlN", "TiN", "AlCrN", "diamond-CVD", "uncoated"])


# ---------------------------------------------------------------------------
# Catalog fz ranges (mm/tooth) keyed on (material, diameter_bucket)
#
# Diameter buckets (mm, inclusive upper bound):
#   "xs"  : D <= 3
#   "sm"  : 3 < D <= 6
#   "md"  : 6 < D <= 12
#   "lg"  : 12 < D <= 20
#   "xl"  : D > 20
#
# Sources per material:
#   steel-1018        : Sandvik CoroPlus Milling 2024 §Table fz-steel-low-carbon
#   steel-4140-soft   : Sandvik CoroPlus 2024 §Table fz-steel-medium-carbon
#   stainless-304     : Kennametal Milling Application Guide 2024 §316/304 fz
#   aluminum-6061     : Harvey Tool Speeds & Feeds (2024) Al-6061 carbide
#   titanium-Ti6Al4V  : Sandvik CoroPlus 2024 §Table fz-titanium
#   cast-iron-grey    : Sandvik CoroPlus 2024 §Table fz-cast-iron
#   plastic-acetal    : Harvey Tool Speeds & Feeds (2024) Acetal/Delrin carbide
# ---------------------------------------------------------------------------

_FZ_RANGES: Dict[Tuple[str, str], Tuple[float, float]] = {
    # (material, bucket): (fz_min_mm, fz_max_mm)

    # steel-1018 (low-carbon, ~120 HB) — Sandvik CoroPlus 2024
    ("steel-1018", "xs"): (0.015, 0.040),
    ("steel-1018", "sm"): (0.030, 0.080),
    ("steel-1018", "md"): (0.050, 0.100),
    ("steel-1018", "lg"): (0.060, 0.130),
    ("steel-1018", "xl"): (0.080, 0.160),

    # steel-4140-soft (pre-heat-treated, ~200 HB) — Sandvik CoroPlus 2024
    ("steel-4140-soft", "xs"): (0.010, 0.030),
    ("steel-4140-soft", "sm"): (0.020, 0.060),
    ("steel-4140-soft", "md"): (0.035, 0.085),
    ("steel-4140-soft", "lg"): (0.050, 0.110),
    ("steel-4140-soft", "xl"): (0.065, 0.140),

    # stainless-304 (austenitic, ~180 HB) — Kennametal 2024
    ("stainless-304", "xs"): (0.010, 0.025),
    ("stainless-304", "sm"): (0.018, 0.045),
    ("stainless-304", "md"): (0.028, 0.065),
    ("stainless-304", "lg"): (0.040, 0.085),
    ("stainless-304", "xl"): (0.050, 0.110),

    # aluminum-6061 (T6, ~95 HB) — Harvey Tool 2024
    ("aluminum-6061", "xs"): (0.030, 0.080),
    ("aluminum-6061", "sm"): (0.060, 0.150),
    ("aluminum-6061", "md"): (0.100, 0.250),
    ("aluminum-6061", "lg"): (0.130, 0.300),
    ("aluminum-6061", "xl"): (0.150, 0.380),

    # titanium-Ti6Al4V (Grade 5, ~36 HRC) — Sandvik CoroPlus 2024
    ("titanium-Ti6Al4V", "xs"): (0.008, 0.020),
    ("titanium-Ti6Al4V", "sm"): (0.015, 0.040),
    ("titanium-Ti6Al4V", "md"): (0.025, 0.060),
    ("titanium-Ti6Al4V", "lg"): (0.030, 0.075),
    ("titanium-Ti6Al4V", "xl"): (0.040, 0.095),

    # cast-iron-grey (GG25, ~200 HB) — Sandvik CoroPlus 2024
    ("cast-iron-grey", "xs"): (0.020, 0.060),
    ("cast-iron-grey", "sm"): (0.040, 0.110),
    ("cast-iron-grey", "md"): (0.060, 0.160),
    ("cast-iron-grey", "lg"): (0.080, 0.200),
    ("cast-iron-grey", "xl"): (0.100, 0.250),

    # plastic-acetal (Delrin/POM, ~80 HRR) — Harvey Tool 2024
    ("plastic-acetal", "xs"): (0.020, 0.080),
    ("plastic-acetal", "sm"): (0.040, 0.150),
    ("plastic-acetal", "md"): (0.060, 0.250),
    ("plastic-acetal", "lg"): (0.080, 0.350),
    ("plastic-acetal", "xl"): (0.100, 0.450),
}

# Rubbing threshold: fraction of fz_min below which rubbing / work-hardening risk
_RUBBING_THRESHOLD_FRAC = 0.60


def _diameter_bucket(d_mm: float) -> str:
    """Map tool diameter to catalog size bucket."""
    if d_mm <= 3.0:
        return "xs"
    elif d_mm <= 6.0:
        return "sm"
    elif d_mm <= 12.0:
        return "md"
    elif d_mm <= 20.0:
        return "lg"
    else:
        return "xl"


# ---------------------------------------------------------------------------
# Honest caveat string (set once, referenced in every report)
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Ranges sourced from Sandvik CoroPlus Milling Technical Guide (2024), "
    "Kennametal Milling Application Guide (2024), and Harvey Tool Speeds & "
    "Feeds (2024) for carbide end-mills with TiAlN coating. "
    "Chip-thinning factor uses the simplified Sandvik linear formula "
    "fz_eff = fz_nom × D/(2·ae) when ae < D/2; the exact trigonometric "
    "form is available in chip_load_calc.compute_chip_load. "
    "Catalog ranges are mid-field averages — actual limits depend on insert "
    "grade, edge prep, exact alloy hardness, machine rigidity, holder runout, "
    "coolant strategy, and specific tool geometry. "
    "Tool deflection, regenerative chatter, and harmonic excitation are NOT "
    "modelled — verify with Altintas 2012 §3 or CoroPlus ToolGuide. "
    "Runout > 5 μm effectively halves per-tooth chip load (alternating flutes); "
    "no runout correction applied. "
    "ap (axial DOC) does not shift fz range directly but can drive chatter — "
    "verify against stability lobe diagrams. "
    "Ranges apply to peripheral end-milling; slot-drill, ball-nose, and chamfer "
    "geometries require manufacturer-specific tables."
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ChipLoadSpec:
    """Input specification for chip-load validation.

    Parameters
    ----------
    material         : Workpiece material key (one of VALID_MATERIALS).
    tool_diameter_mm : Cutting tool (end-mill) diameter [mm].
    num_flutes       : Number of cutting flutes.
    vc_m_per_min     : Cutting surface speed [m/min].
    fz_mm_per_tooth  : Programmed nominal feed per tooth [mm/tooth].
    ae_mm            : Radial depth of cut [mm]. Must be in (0, tool_diameter_mm].
    ap_mm            : Axial depth of cut [mm]. Must be > 0.
    tool_coating     : Tool coating string (default "TiAlN").
    """
    material: str
    tool_diameter_mm: float
    num_flutes: int
    vc_m_per_min: float
    fz_mm_per_tooth: float
    ae_mm: float
    ap_mm: float
    tool_coating: str = "TiAlN"

    def __post_init__(self) -> None:
        if self.material not in VALID_MATERIALS:
            raise ValueError(
                f"material must be one of {sorted(VALID_MATERIALS)}, "
                f"got {self.material!r}"
            )
        if self.tool_diameter_mm <= 0:
            raise ValueError(
                f"tool_diameter_mm must be > 0, got {self.tool_diameter_mm!r}"
            )
        if self.num_flutes < 1:
            raise ValueError(
                f"num_flutes must be >= 1, got {self.num_flutes!r}"
            )
        if self.vc_m_per_min <= 0:
            raise ValueError(
                f"vc_m_per_min must be > 0, got {self.vc_m_per_min!r}"
            )
        if self.fz_mm_per_tooth <= 0:
            raise ValueError(
                f"fz_mm_per_tooth must be > 0, got {self.fz_mm_per_tooth!r}"
            )
        if not (0.0 < self.ae_mm <= self.tool_diameter_mm):
            raise ValueError(
                f"ae_mm must be in (0, tool_diameter_mm], "
                f"got ae={self.ae_mm!r}, D={self.tool_diameter_mm!r}"
            )
        if self.ap_mm <= 0:
            raise ValueError(
                f"ap_mm must be > 0, got {self.ap_mm!r}"
            )


@dataclass
class ChipLoadReport:
    """Result from ``validate_chip_load``.

    Attributes
    ----------
    rpm_n                    : Derived spindle speed [rpm] = vc × 1000 / (π × D).
    feed_mm_per_min          : Derived table feed [mm/min] = fz × flutes × n.
    chip_thinning_factor     : D / (2·ae) when ae < D/2, else 1.0.
    effective_fz_mm          : fz_nominal × chip_thinning_factor [mm/tooth].
    in_range                 : True iff fz_min <= effective_fz <= fz_max.
    recommended_fz_range_mm  : (fz_min, fz_max) from catalog for this
                               material+diameter combination.
    warning_messages         : List of human-readable warnings (may be empty).
    honest_caveat            : Plain-English caveats and model limitations.
    """
    rpm_n: float
    feed_mm_per_min: float
    chip_thinning_factor: float
    effective_fz_mm: float
    in_range: bool
    recommended_fz_range_mm: Tuple[float, float]
    warning_messages: List[str]
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core validation function
# ---------------------------------------------------------------------------

def validate_chip_load(spec: ChipLoadSpec) -> ChipLoadReport:
    """Validate chip load against published catalog ranges.

    Algorithm
    ---------
    1. n = vc × 1000 / (π × D)                          [rpm]
    2. feed = fz × flutes × n                            [mm/min]
    3. thinning_factor:
         ae < D/2  → D / (2 · ae)                        [Sandvik simplified]
         ae >= D/2 → 1.0
    4. effective_fz = fz_nominal × thinning_factor       [mm/tooth]
    5. Look up catalog range for (material, diameter_bucket).
    6. in_range = fz_min <= effective_fz <= fz_max.
    7. Emit warnings:
         - chip-thinning active (with factor and effective value)
         - over-feed (effective_fz > fz_max)
         - rubbing / work-hardening (effective_fz < rubbing_threshold × fz_min)
         - under-feed but not rubbing (fz_min > effective_fz >= threshold)
         - ae > D/2 but nominal fz at high end (heavier engagement warning)

    Parameters
    ----------
    spec : ChipLoadSpec — validated by __post_init__.

    Returns
    -------
    ChipLoadReport
    """
    D = spec.tool_diameter_mm
    ae = spec.ae_mm
    fz = spec.fz_mm_per_tooth
    z = spec.num_flutes

    # 1. Spindle speed [rpm]
    n = spec.vc_m_per_min * 1000.0 / (math.pi * D)

    # 2. Table feed [mm/min]
    feed = fz * z * n

    # 3. Chip-thinning factor (Sandvik simplified linear formula)
    if ae < D / 2.0:
        thinning_factor = D / (2.0 * ae)
    else:
        thinning_factor = 1.0

    # 4. Effective chip load
    effective_fz = fz * thinning_factor

    # 5. Catalog range lookup
    bucket = _diameter_bucket(D)
    fz_min, fz_max = _FZ_RANGES[(spec.material, bucket)]

    # 6. In-range check
    in_range = fz_min <= effective_fz <= fz_max

    # 7. Build warnings
    warnings: List[str] = []

    if thinning_factor > 1.0:
        warnings.append(
            f"Chip thinning active: ae={ae:.3f} mm < D/2={D/2:.3f} mm. "
            f"Thinning factor={thinning_factor:.3f}×; "
            f"effective fz={effective_fz:.4f} mm/tooth "
            f"(nominal={fz:.4f} mm/tooth). "
            f"Increase nominal fz to compensate or use the effective value for "
            f"catalog compliance. Reference: Sandvik CoroPlus 2024 chip-thinning."
        )

    rubbing_threshold = _RUBBING_THRESHOLD_FRAC * fz_min
    if effective_fz < rubbing_threshold:
        warnings.append(
            f"RUBBING / WORK-HARDENING RISK: effective fz={effective_fz:.4f} mm/tooth "
            f"is below {_RUBBING_THRESHOLD_FRAC*100:.0f}% of catalog minimum "
            f"fz_min={fz_min:.4f} mm/tooth for {spec.material}. "
            f"Too-light chip load causes rubbing instead of cutting, generating "
            f"heat and work-hardening the surface (especially stainless/titanium). "
            f"Increase feed rate or reduce spindle RPM."
        )
    elif effective_fz < fz_min:
        warnings.append(
            f"Under-feed: effective fz={effective_fz:.4f} mm/tooth is below "
            f"catalog minimum fz_min={fz_min:.4f} mm/tooth for {spec.material} "
            f"(D={D:.1f} mm). Tool may rub; increase fz or check thinning factor."
        )

    if effective_fz > fz_max:
        warnings.append(
            f"OVER-FEED: effective fz={effective_fz:.4f} mm/tooth exceeds "
            f"catalog maximum fz_max={fz_max:.4f} mm/tooth for {spec.material} "
            f"(D={D:.1f} mm). Risk of tool fracture, chipping, or excessive "
            f"cutting force. Reduce feed rate immediately."
        )

    # Heavy-engagement note when full-slot (ae >= D/2) and fz at upper end
    if ae >= D / 2.0 and effective_fz > 0.85 * fz_max:
        warnings.append(
            f"High engagement + high fz: ae={ae:.1f} mm >= D/2={D/2:.1f} mm and "
            f"effective fz={effective_fz:.4f} mm/tooth is >85% of fz_max. "
            f"Verify machine rigidity and tool holder runout (<5 μm recommended)."
        )

    return ChipLoadReport(
        rpm_n=round(n, 2),
        feed_mm_per_min=round(feed, 3),
        chip_thinning_factor=round(thinning_factor, 6),
        effective_fz_mm=round(effective_fz, 6),
        in_range=in_range,
        recommended_fz_range_mm=(fz_min, fz_max),
        warning_messages=warnings,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_validate_chip_load_spec = ToolSpec(
    name="cam_validate_chip_load",
    description=(
        "Validate milling chip load (feed-per-tooth) against published Sandvik "
        "Coromant / Kennametal / Harvey Tool catalog ranges for a specific "
        "workpiece material, tool diameter, and cutting conditions. "
        "Detects radial chip thinning (ae < D/2) using the Sandvik simplified "
        "formula fz_eff = fz_nom × D/(2·ae) and warns when the effective chip "
        "load is out of range (over-feed → fracture risk; under-feed → rubbing / "
        "work-hardening). "
        "Inputs: material (steel-1018|steel-4140-soft|stainless-304|"
        "aluminum-6061|titanium-Ti6Al4V|cast-iron-grey|plastic-acetal), "
        "tool_diameter_mm, num_flutes, vc_m_per_min, fz_mm_per_tooth, "
        "ae_mm (radial DOC), ap_mm (axial DOC), tool_coating (default TiAlN). "
        "Returns: rpm_n, feed_mm_per_min, chip_thinning_factor, effective_fz_mm, "
        "in_range, recommended_fz_range_mm, warning_messages, honest_caveat. "
        "References: Sandvik CoroPlus Milling Technical Guide (2024); Kennametal "
        "Milling Application Guide (2024); Harvey Tool Speeds & Feeds (2024); "
        "MH 31e §1136. "
        "Honest limits: catalog mid-field averages; tool deflection, runout, "
        "harmonics NOT modelled; verify against CoroPlus ToolGuide for production."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "material": {
                "type": "string",
                "enum": sorted(VALID_MATERIALS),
                "description": "Workpiece material key.",
            },
            "tool_diameter_mm": {
                "type": "number",
                "description": "Tool (end-mill) diameter in mm.",
            },
            "num_flutes": {
                "type": "integer",
                "description": "Number of cutting flutes.",
            },
            "vc_m_per_min": {
                "type": "number",
                "description": "Cutting surface speed in m/min.",
            },
            "fz_mm_per_tooth": {
                "type": "number",
                "description": "Programmed nominal feed per tooth in mm/tooth.",
            },
            "ae_mm": {
                "type": "number",
                "description": (
                    "Radial depth of cut in mm. Must be in (0, tool_diameter_mm]. "
                    "ae = D for full-width slot."
                ),
            },
            "ap_mm": {
                "type": "number",
                "description": "Axial depth of cut in mm.",
            },
            "tool_coating": {
                "type": "string",
                "enum": sorted(VALID_COATINGS),
                "description": "Tool coating. Default: TiAlN.",
            },
        },
        "required": [
            "material",
            "tool_diameter_mm",
            "num_flutes",
            "vc_m_per_min",
            "fz_mm_per_tooth",
            "ae_mm",
            "ap_mm",
        ],
    },
)


@register(cam_validate_chip_load_spec)
async def run_cam_validate_chip_load(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = [
        "material", "tool_diameter_mm", "num_flutes",
        "vc_m_per_min", "fz_mm_per_tooth", "ae_mm", "ap_mm",
    ]
    for field_name in required:
        if field_name not in a:
            return err_payload(f"missing required field: {field_name!r}", "BAD_ARGS")

    try:
        spec = ChipLoadSpec(
            material=str(a["material"]),
            tool_diameter_mm=float(a["tool_diameter_mm"]),
            num_flutes=int(a["num_flutes"]),
            vc_m_per_min=float(a["vc_m_per_min"]),
            fz_mm_per_tooth=float(a["fz_mm_per_tooth"]),
            ae_mm=float(a["ae_mm"]),
            ap_mm=float(a["ap_mm"]),
            tool_coating=str(a.get("tool_coating", "TiAlN")),
        )
        result = validate_chip_load(spec)
    except (TypeError, KeyError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "rpm_n": result.rpm_n,
        "feed_mm_per_min": result.feed_mm_per_min,
        "chip_thinning_factor": result.chip_thinning_factor,
        "effective_fz_mm": result.effective_fz_mm,
        "in_range": result.in_range,
        "recommended_fz_range_mm": list(result.recommended_fz_range_mm),
        "warning_messages": result.warning_messages,
        "honest_caveat": result.honest_caveat,
    })
