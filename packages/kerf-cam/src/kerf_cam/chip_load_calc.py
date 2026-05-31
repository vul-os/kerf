"""
kerf_cam.chip_load_calc — Chip-load and chip-thinning calculator for milling operations.

Computes the actual feed-per-tooth (chip load) and the radial chip-thinning
factor for a given tool diameter, spindle speed, feed rate, and radial
engagement (ae).  Used to verify that a CAM operation matches the tool
manufacturer's recommended chip-load range before sending the job to the
machine.

Reference standards
-------------------
* Machinery's Handbook 31e §1136 — Chip load (feed per tooth), MRR formula.
* Sandvik CoroPlus Technical Guide (2024) — Milling feed-per-tooth recommended
  ranges per tool material and workpiece material; chip thinning Krad formula.
* Stephenson & Agapiou "Metal Cutting Theory and Practice" (3rd ed.) §6 —
  Radial chip thinning; circular tool engagement geometry.

Chip-load formula
-----------------
    fz = Vf / (n × z)

where:
  fz  — feed per tooth [mm/tooth]
  Vf  — table feed (feed_mm_per_min) [mm/min]
  n   — spindle speed (spindle_rpm) [rpm]
  z   — number of cutting flutes (num_flutes)

Radial chip-thinning factor (Sandvik CoroPlus 2024; Stephenson-Agapiou §6)
---------------------------------------------------------------------------
When ae < D/2 (less than half-width engagement), the chip is thinner than fz
because the arc of engagement is less than 90°.  The correction factor is:

    Krad = D / (2 · sqrt(D · ae − ae²))   when ae < D/2
    Krad = 1.0                              when ae >= D/2

This is derived from the chord-to-arc ratio of a circular cutter at radial
engagement ae in a cutter of diameter D.

Actual (equivalent) chip load
------------------------------
    fz_actual = fz × Krad

The actual chip load fz_actual is what the cutting edge effectively experiences
and should be compared with the tool manufacturer's fz recommendation.

Material-removal rate
---------------------
    MRR = ae × ap × Vf / 1000   [cm³/min]

where:
  ae  — radial engagement [mm]
  ap  — axial depth [mm]
  Vf  — table feed [mm/min]
  /1000 converts mm³/min → cm³/min

Sandvik CoroPlus typical chip-load ranges (fz_actual, selected materials)
--------------------------------------------------------------------------
  carbide on aluminium :  0.05 – 0.15 mm/tooth
  carbide on steel     :  0.05 – 0.20 mm/tooth
  HSS    on aluminium  :  0.03 – 0.10 mm/tooth
  HSS    on steel      :  0.03 – 0.12 mm/tooth
  ceramic (Al₂O₃/SiN)  :  0.10 – 0.30 mm/tooth (high-speed finishing only)

These are broad guidance ranges only; verify against CoroPlus ToolGuide for
the specific insert grade, coating, workpiece alloy, and machine rigidity.

Honest caveats
--------------
- The thinning formula Krad = D / (2·sqrt(D·ae − ae²)) assumes **circular**
  arc-of-engagement (i.e. a flat workpiece surface, peripheral end-mill).
  Curved workpieces, ball-nose tools, and profiling passes change the geometry.
- No distinction between **climb milling** (ae advances into the cutter) and
  **conventional milling** (ae retreats); both use the same Krad formula even
  though chip thickness profiles differ.
- **Tool deflection** and its effect on effective ae/fz is NOT modelled.  At
  high MRR (deep ae + high fz) deflection can significantly reduce actual chip
  thickness; refer to Altintas 2012 §3.6 or CoroPlus ToolGuide for deflection.
- Recommended fz ranges are material-class averages (aluminium / steel).
  Actual limits depend on insert geometry, coating, workpiece alloy, machine
  rigidity, and coolant strategy — use CoroPlus ToolGuide / Kennametal NOVO
  for production certification.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Dict, Tuple

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Sandvik CoroPlus 2024 typical fz ranges
# (tool_material, material_class) → (min_mm, max_mm)
# material_class: "aluminium" | "steel"
# ---------------------------------------------------------------------------

_VALID_TOOL_MATERIALS = frozenset(["HSS", "carbide", "ceramic"])

_FZ_RANGES: Dict[Tuple[str, str], Tuple[float, float]] = {
    ("carbide", "aluminium"): (0.05, 0.15),
    ("carbide", "steel"):     (0.05, 0.20),
    ("HSS",     "aluminium"): (0.03, 0.10),
    ("HSS",     "steel"):     (0.03, 0.12),
    ("ceramic", "aluminium"): (0.10, 0.30),
    ("ceramic", "steel"):     (0.10, 0.30),
}

# Map common tool_material keywords to material class for range lookup
_MATERIAL_CLASS_MAP: Dict[str, str] = {
    # aluminium / aluminum keywords
    "aluminium":      "aluminium",
    "aluminum":       "aluminium",
    "aluminium_6061": "aluminium",
    "aluminum_6061":  "aluminium",
    "al":             "aluminium",
    # steel / stainless
    "steel":          "steel",
    "steel_1018":     "steel",
    "stainless":      "steel",
    "stainless_303":  "steel",
    "stainless_316":  "steel",
    "titanium":       "steel",
    "cast_iron":      "steel",
}

_HONEST_CAVEAT = (
    "Chip-thinning formula Krad = D/(2·sqrt(D·ae − ae²)) assumes circular "
    "arc-of-engagement on a flat workpiece surface (peripheral end-mill). "
    "Ball-nose tools, curved workpieces, and profiling passes change the "
    "engagement geometry and this formula no longer applies directly. "
    "No climb/conventional distinction: both strategies use identical Krad "
    "even though chip-thickness profiles differ (climb: thick-to-thin entry; "
    "conventional: thin-to-thick entry). "
    "Tool deflection is NOT modelled — at high MRR, deflection reduces "
    "effective ae and chip thickness; see Altintas 2012 §3.6. "
    "Recommended fz ranges are Sandvik CoroPlus 2024 material-class averages "
    "(carbide/aluminium: 0.05–0.15, carbide/steel: 0.05–0.20 mm/tooth); "
    "actual limits depend on insert grade, coating, workpiece alloy, machine "
    "rigidity, and coolant — verify against CoroPlus ToolGuide for production."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MillingOpSpec:
    """Input specification for a milling chip-load calculation.

    Parameters
    ----------
    tool_diameter_mm      : Cutter diameter [mm], e.g. 12.0.
    num_flutes            : Number of cutting flutes (teeth), e.g. 2 or 4.
    spindle_rpm           : Programmed spindle speed [rpm].
    feed_mm_per_min       : Programmed table feed (Vf) [mm/min].
    radial_engagement_mm  : Radial depth of cut (ae) [mm].  Must be in
                            (0, tool_diameter_mm].
    axial_depth_mm        : Axial depth of cut (ap) [mm].  Must be > 0.
    tool_material         : Tool material class: "HSS", "carbide", or "ceramic".
    work_material         : Work material keyword used for range lookup, e.g.
                            "aluminium", "aluminum_6061", "steel", "steel_1018",
                            "stainless_303".  Optional — if omitted or
                            unrecognised, recommended_min/max are set to None
                            and compliant is None.
    """
    tool_diameter_mm: float
    num_flutes: int
    spindle_rpm: float
    feed_mm_per_min: float
    radial_engagement_mm: float
    axial_depth_mm: float
    tool_material: str
    work_material: str = ""

    def __post_init__(self) -> None:
        if self.tool_diameter_mm <= 0:
            raise ValueError(
                f"tool_diameter_mm must be > 0, got {self.tool_diameter_mm!r}"
            )
        if self.num_flutes < 1:
            raise ValueError(
                f"num_flutes must be >= 1, got {self.num_flutes!r}"
            )
        if self.spindle_rpm <= 0:
            raise ValueError(
                f"spindle_rpm must be > 0, got {self.spindle_rpm!r}"
            )
        if self.feed_mm_per_min <= 0:
            raise ValueError(
                f"feed_mm_per_min must be > 0, got {self.feed_mm_per_min!r}"
            )
        if not (0 < self.radial_engagement_mm <= self.tool_diameter_mm):
            raise ValueError(
                f"radial_engagement_mm must be in (0, tool_diameter_mm], "
                f"got ae={self.radial_engagement_mm!r}, D={self.tool_diameter_mm!r}"
            )
        if self.axial_depth_mm <= 0:
            raise ValueError(
                f"axial_depth_mm must be > 0, got {self.axial_depth_mm!r}"
            )
        if self.tool_material not in _VALID_TOOL_MATERIALS:
            raise ValueError(
                f"tool_material must be one of {sorted(_VALID_TOOL_MATERIALS)}, "
                f"got {self.tool_material!r}"
            )


@dataclass
class ChipLoadReport:
    """Result from ``compute_chip_load``.

    Attributes
    ----------
    chip_load_per_tooth_mm  : Feed per tooth fz [mm/tooth] = Vf / (n × z).
    chip_thinning_factor    : Krad — 1.0 when ae >= D/2; > 1.0 when ae < D/2.
    actual_chip_load_mm     : fz × Krad [mm/tooth] — effective chip thickness
                              experienced by the cutting edge.
    recommended_min_mm      : Sandvik CoroPlus 2024 lower fz bound for this
                              tool_material / work_material combination
                              (None if work_material not recognised).
    recommended_max_mm      : Sandvik CoroPlus 2024 upper fz bound (None if
                              work_material not recognised).
    compliant               : True if recommended_min <= actual_chip_load_mm
                              <= recommended_max (None if ranges unknown).
    mrr_cm3_per_min         : Material-removal rate [cm³/min] = ae × ap × Vf / 1000.
    honest_caveat           : Plain-English limitations and assumptions.
    """
    chip_load_per_tooth_mm: float
    chip_thinning_factor: float
    actual_chip_load_mm: float
    recommended_min_mm: float | None
    recommended_max_mm: float | None
    compliant: bool | None
    mrr_cm3_per_min: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_chip_load(spec: MillingOpSpec) -> ChipLoadReport:
    """Compute chip load and chip-thinning factor for a milling operation.

    Algorithm
    ---------
    1. fz = Vf / (n × z)                                    [mm/tooth]
    2. Krad:
         ae < D/2 → D / (2 · sqrt(D·ae − ae²))
         ae >= D/2 → 1.0
    3. fz_actual = fz × Krad
    4. MRR = ae × ap × Vf / 1000                            [cm³/min]
    5. Look up Sandvik recommended range for (tool_material, material_class).
    6. compliant = (rec_min <= fz_actual <= rec_max) if range known, else None.

    Parameters
    ----------
    spec : MillingOpSpec — validated by its __post_init__.

    Returns
    -------
    ChipLoadReport
    """
    D = spec.tool_diameter_mm
    ae = spec.radial_engagement_mm
    ap = spec.axial_depth_mm
    n = spec.spindle_rpm
    z = spec.num_flutes
    Vf = spec.feed_mm_per_min

    # 1. Feed per tooth [mm/tooth]
    fz = Vf / (n * z)

    # 2. Chip-thinning factor
    if ae < D / 2.0:
        # Krad = D / (2·sqrt(D·ae - ae²))
        # The expression D·ae − ae² = ae·(D − ae) is always positive when
        # 0 < ae < D, so the sqrt is always real.
        krad = D / (2.0 * math.sqrt(D * ae - ae * ae))
    else:
        krad = 1.0

    # 3. Actual chip load
    fz_actual = fz * krad

    # 4. MRR [cm³/min]
    mrr = ae * ap * Vf / 1000.0

    # 5. Recommended range lookup
    mat_class = _MATERIAL_CLASS_MAP.get(spec.work_material.lower().strip(), None)
    rec_min: float | None = None
    rec_max: float | None = None
    if mat_class is not None:
        key = (spec.tool_material, mat_class)
        bounds = _FZ_RANGES.get(key)
        if bounds is not None:
            rec_min, rec_max = bounds

    # 6. Compliance
    if rec_min is not None and rec_max is not None:
        compliant: bool | None = rec_min <= fz_actual <= rec_max
    else:
        compliant = None

    return ChipLoadReport(
        chip_load_per_tooth_mm=round(fz, 9),
        chip_thinning_factor=round(krad, 6),
        actual_chip_load_mm=round(fz_actual, 9),
        recommended_min_mm=rec_min,
        recommended_max_mm=rec_max,
        compliant=compliant,
        mrr_cm3_per_min=round(mrr, 6),
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_compute_chip_load_spec = ToolSpec(
    name="cam_compute_chip_load",
    description=(
        "Compute actual feed-per-tooth (chip load) and radial chip-thinning "
        "factor for a milling operation, and verify against Sandvik CoroPlus "
        "recommended chip-load range. "
        "Inputs: tool diameter, number of flutes, spindle RPM, table feed "
        "(mm/min), radial engagement (ae), axial depth (ap), tool material "
        "(HSS|carbide|ceramic), optional work material keyword. "
        "Returns: fz [mm/tooth], chip_thinning_factor Krad, actual_chip_load "
        "(fz × Krad), recommended min/max fz from Sandvik CoroPlus 2024, "
        "compliant flag, MRR [cm³/min], and an honest caveat. "
        "Formula: fz = Vf/(n×z); Krad = D/(2·sqrt(D·ae−ae²)) when ae<D/2 "
        "else 1.0 (Sandvik CoroPlus 2024; Stephenson-Agapiou §6); "
        "MRR = ae×ap×Vf/1000. "
        "References: MH 31e §1136; Sandvik CoroPlus Milling/feed-per-tooth; "
        "Stephenson-Agapiou §6. "
        "Honest limits: thinning formula assumes circular tool engagement on "
        "flat workpiece (peripheral end-mill only); no climb/conventional "
        "distinction; tool deflection NOT modelled."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tool_diameter_mm": {
                "type": "number",
                "description": "Cutter diameter in mm (e.g. 12.0).",
            },
            "num_flutes": {
                "type": "integer",
                "description": "Number of cutting flutes/teeth.",
            },
            "spindle_rpm": {
                "type": "number",
                "description": "Programmed spindle speed in rpm.",
            },
            "feed_mm_per_min": {
                "type": "number",
                "description": "Programmed table feed Vf in mm/min.",
            },
            "radial_engagement_mm": {
                "type": "number",
                "description": (
                    "Radial depth of cut ae in mm.  Must be in "
                    "(0, tool_diameter_mm].  ae = D for full-width slot."
                ),
            },
            "axial_depth_mm": {
                "type": "number",
                "description": "Axial depth of cut ap in mm.",
            },
            "tool_material": {
                "type": "string",
                "enum": ["HSS", "carbide", "ceramic"],
                "description": "Tool material class.",
            },
            "work_material": {
                "type": "string",
                "description": (
                    "Work material keyword for range lookup, e.g. "
                    "'aluminium', 'aluminum_6061', 'steel', 'steel_1018', "
                    "'stainless_303'.  Optional — omit if unknown."
                ),
            },
        },
        "required": [
            "tool_diameter_mm",
            "num_flutes",
            "spindle_rpm",
            "feed_mm_per_min",
            "radial_engagement_mm",
            "axial_depth_mm",
            "tool_material",
        ],
    },
)


@register(cam_compute_chip_load_spec)
async def run_cam_compute_chip_load(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = [
        "tool_diameter_mm", "num_flutes", "spindle_rpm",
        "feed_mm_per_min", "radial_engagement_mm", "axial_depth_mm",
        "tool_material",
    ]
    for field in required:
        if field not in a:
            return err_payload(f"missing required field: {field!r}", "BAD_ARGS")

    try:
        spec = MillingOpSpec(
            tool_diameter_mm=float(a["tool_diameter_mm"]),
            num_flutes=int(a["num_flutes"]),
            spindle_rpm=float(a["spindle_rpm"]),
            feed_mm_per_min=float(a["feed_mm_per_min"]),
            radial_engagement_mm=float(a["radial_engagement_mm"]),
            axial_depth_mm=float(a["axial_depth_mm"]),
            tool_material=str(a["tool_material"]),
            work_material=str(a.get("work_material", "")),
        )
        result = compute_chip_load(spec)
    except (TypeError, KeyError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "chip_load_per_tooth_mm": result.chip_load_per_tooth_mm,
        "chip_thinning_factor": result.chip_thinning_factor,
        "actual_chip_load_mm": result.actual_chip_load_mm,
        "recommended_min_mm": result.recommended_min_mm,
        "recommended_max_mm": result.recommended_max_mm,
        "compliant": result.compliant,
        "mrr_cm3_per_min": result.mrr_cm3_per_min,
        "honest_caveat": result.honest_caveat,
    })
