"""
kerf_cam.turning_depth_calc — Optimal depth-of-cut (DOC) per pass + total roughing
passes for a lathe turning operation.

Given stock OD, final OD, tool nose radius, material, and process parameters,
this module computes:

  * radial stock removal = (D_stock - D_final) / 2
  * number of roughing passes (equal DOC, never exceeds max_roughing_doc)
  * number of finishing passes (one by default)
  * total machining time estimate (assuming cylindrical workpiece, constant feed)

Reference standards
-------------------
* Machinery's Handbook 31e §1148 — Turning depth-of-cut guidelines, roughing vs
  finishing, and the relationship between nose radius, feed rate, and surface finish.
* Sandvik Coromant CoroPlus Turning Catalogue (2024) — DOC-per-material recommended
  ranges, nose-radius constraints, and time-in-cut formula.

Depth-of-cut selection (MH 31e §1148 + Sandvik CoroPlus)
----------------------------------------------------------
Material-class maximum recommended roughing DOC (a_p, radial, from centre-line):

  steel_1018        : 2.0 – 4.0 mm  (recommended midpoint: 3.0 mm)
  aluminum_6061     : 4.0 – 8.0 mm  (recommended midpoint: 6.0 mm)
  stainless_303     : 1.5 – 2.5 mm  (recommended midpoint: 2.0 mm)

These are conservative guidance ranges for coated carbide inserts at moderate
cutting speed; they assume a rigid lathe setup, adequate coolant, and a
workpiece L/D ratio ≤ 6.  Verify against CoroPlus ToolGuide for production.

Nose-radius constraint (MH 31e §1148)
---------------------------------------
Minimum practical DOC:  a_p_min ≥ 0.5 × r_ε  (Sandvik CoroPlus rule-of-thumb)
  where r_ε = tool_nose_radius_mm

If the requested finish_pass_doc falls below 0.5×r_ε the report raises a warning
(not an error) in honest_caveat.

Roughing-pass count algorithm
-------------------------------
  radial_stock = (D_stock − D_final) / 2              [mm, always > 0]
  stock_for_roughing = radial_stock − finish_pass_doc  [mm]
  if stock_for_roughing <= 0:
      num_roughing_passes = 0
  else:
      num_roughing_passes = ceil(stock_for_roughing / max_roughing_doc)
      roughing_doc = stock_for_roughing / num_roughing_passes  ← equal spacing

Total passes:  total_passes = num_roughing_passes + num_finishing_passes
  num_finishing_passes is always 1 (configurable via the spec in future).

Time-per-pass estimate
-----------------------
This model approximates the workpiece as a pure cylinder of length
workpiece_length_mm (defaults to a user-supplied value; we use 100 mm if not
supplied to provide a relative metric).  Actual part geometry is not modelled.

  circumferential_distance_per_rev = π × D_mean  (not needed; length-only model)
  time_per_pass [s] = workpiece_length_mm / (feed_mm_per_rev × spindle_rpm / 60)

  total_machining_time_s = time_per_pass × total_passes

This is a first-order estimate for a straight-turning (no taper, no profile)
operation at constant spindle speed.  Constant Surface Speed (CSS / G96) is
NOT modelled here; the caller must convert surface speed to RPM externally.

Honest caveats
--------------
- Roughing strategy assumes straight (cylindrical) turning only — no taper,
  no profile turning, no facing, no threading.
- Constant Surface Speed (CSS / G96 mode) NOT implemented here; spindle_rpm is
  treated as a fixed value throughout all passes.
- MH 31e nose-radius rule: finish_pass_doc ≥ 0.5×r_ε to avoid rubbing.  If
  this condition is violated the caveat field will contain a warning.
- Time estimate uses a constant-feed/constant-RPM cylindrical model; rapid
  traverse between passes, tool change time, and acceleration ramps are excluded.
- Recommended DOC ranges are Sandvik CoroPlus / MH 31e conservative averages;
  actual limits depend on insert grade, coating, workpiece alloy hardness,
  machine rigidity, coolant strategy, and L/D ratio.
- Profile turning, face grooving, parting, and threading are out of scope.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Material-class recommended DOC ranges
# (min_roughing_doc_mm, max_roughing_doc_mm, recommended_midpoint_mm)
# Reference: MH 31e §1148 + Sandvik CoroPlus 2024
# ---------------------------------------------------------------------------

_VALID_MATERIALS = frozenset(["steel_1018", "aluminum_6061", "stainless_303"])

# (min, max, recommended) — all radial DOC, mm
_MATERIAL_DOC_RANGES: dict[str, tuple[float, float, float]] = {
    "steel_1018":    (2.0, 4.0, 3.0),
    "aluminum_6061": (4.0, 8.0, 6.0),
    "stainless_303": (1.5, 2.5, 2.0),
}

_HONEST_CAVEAT = (
    "Roughing strategy assumes straight (cylindrical) turning only — "
    "no taper, no profile turning, no facing, no threading. "
    "Constant Surface Speed (CSS / G96 mode) NOT implemented; spindle_rpm is "
    "treated as a fixed value throughout all passes. "
    "Time estimate uses a constant-feed/constant-RPM cylindrical model; "
    "rapid traverse between passes, tool change time, and acceleration ramps "
    "are excluded. "
    "Recommended DOC ranges are Sandvik CoroPlus 2024 / MH 31e §1148 conservative "
    "averages (steel_1018: 2–4 mm; aluminum_6061: 4–8 mm; stainless_303: 1.5–2.5 mm) "
    "for coated carbide inserts at moderate cutting speed; actual limits depend on "
    "insert grade, coating, workpiece hardness, machine rigidity, coolant, and L/D ratio. "
    "Profile turning, face grooving, parting, and threading are out of scope."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TurningSpec:
    """Input specification for a lathe turning depth-of-cut calculation.

    Parameters
    ----------
    stock_diameter_mm       : Workpiece stock outer diameter [mm].  Must be
                              > final_diameter_mm.
    final_diameter_mm       : Target final outer diameter after machining [mm].
                              Must be > 0.
    material                : Work material: "steel_1018" | "aluminum_6061" |
                              "stainless_303".
    tool_nose_radius_mm     : Insert nose radius r_ε [mm].  Used to validate
                              finish_pass_doc (must be ≥ 0.5 × r_ε).
    feed_mm_per_rev         : Programmed feed rate [mm/rev].
    spindle_rpm             : Spindle speed [rpm].
    finish_pass_doc_mm      : Radial depth of cut for the finishing pass [mm].
                              Default 0.5 mm.
    max_roughing_doc_mm     : Maximum radial depth of cut per roughing pass [mm].
                              Default 3.0 mm.  Overridden to material recommended
                              max if this value exceeds it.
    workpiece_length_mm     : Axial length of cut used for time estimation [mm].
                              Default 100.0 mm.
    """
    stock_diameter_mm: float
    final_diameter_mm: float
    material: str
    tool_nose_radius_mm: float
    feed_mm_per_rev: float
    spindle_rpm: float
    finish_pass_doc_mm: float = 0.5
    max_roughing_doc_mm: float = 3.0
    workpiece_length_mm: float = 100.0

    def __post_init__(self) -> None:
        if self.final_diameter_mm <= 0:
            raise ValueError(
                f"final_diameter_mm must be > 0, got {self.final_diameter_mm!r}"
            )
        if self.stock_diameter_mm <= self.final_diameter_mm:
            raise ValueError(
                f"stock_diameter_mm ({self.stock_diameter_mm!r}) must be > "
                f"final_diameter_mm ({self.final_diameter_mm!r})"
            )
        if self.material not in _VALID_MATERIALS:
            raise ValueError(
                f"material must be one of {sorted(_VALID_MATERIALS)}, "
                f"got {self.material!r}"
            )
        if self.tool_nose_radius_mm <= 0:
            raise ValueError(
                f"tool_nose_radius_mm must be > 0, got {self.tool_nose_radius_mm!r}"
            )
        if self.feed_mm_per_rev <= 0:
            raise ValueError(
                f"feed_mm_per_rev must be > 0, got {self.feed_mm_per_rev!r}"
            )
        if self.spindle_rpm <= 0:
            raise ValueError(
                f"spindle_rpm must be > 0, got {self.spindle_rpm!r}"
            )
        if self.finish_pass_doc_mm <= 0:
            raise ValueError(
                f"finish_pass_doc_mm must be > 0, got {self.finish_pass_doc_mm!r}"
            )
        if self.max_roughing_doc_mm <= 0:
            raise ValueError(
                f"max_roughing_doc_mm must be > 0, got {self.max_roughing_doc_mm!r}"
            )
        if self.workpiece_length_mm <= 0:
            raise ValueError(
                f"workpiece_length_mm must be > 0, got {self.workpiece_length_mm!r}"
            )


@dataclass
class TurningDepthReport:
    """Result from ``compute_turning_depth``.

    Attributes
    ----------
    num_roughing_passes         : Number of roughing passes computed.
    num_finishing_passes        : Number of finishing passes (always 1).
    total_passes                : num_roughing_passes + num_finishing_passes.
    roughing_doc_mm             : Actual radial DOC per roughing pass [mm].
                                  Equal for all roughing passes.  0.0 when
                                  num_roughing_passes == 0.
    total_machining_time_s      : Estimated total cutting time [s] for all
                                  passes at constant feed and RPM.
    recommended_doc_for_material : Sandvik CoroPlus / MH 31e §1148 midpoint
                                  recommended roughing DOC for the specified
                                  material [mm].
    honest_caveat               : Plain-English limitations and assumptions.
    """
    num_roughing_passes: int
    num_finishing_passes: int
    total_passes: int
    roughing_doc_mm: float
    total_machining_time_s: float
    recommended_doc_for_material: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_turning_depth(spec: TurningSpec) -> TurningDepthReport:
    """Compute optimal depth-of-cut and pass count for a lathe turning operation.

    Algorithm
    ---------
    1.  radial_stock = (D_stock − D_final) / 2
    2.  stock_for_roughing = radial_stock − finish_pass_doc
        (if <= 0 → 0 roughing passes)
    3.  Clamp max_roughing_doc to material recommended max (MH 31e §1148).
    4.  num_roughing_passes = ceil(stock_for_roughing / effective_max_doc)
    5.  roughing_doc = stock_for_roughing / num_roughing_passes (equal passes)
    6.  time_per_pass [s] = workpiece_length / (feed_mm_per_rev × spindle_rpm / 60)
    7.  total_time = time_per_pass × total_passes
    8.  Nose-radius check: finish_pass_doc < 0.5×r_ε → caveat warning.

    Parameters
    ----------
    spec : TurningSpec — validated by its __post_init__.

    Returns
    -------
    TurningDepthReport
    """
    # 1. Radial stock removal
    radial_stock = (spec.stock_diameter_mm - spec.final_diameter_mm) / 2.0

    # 2. Stock remaining after finish pass
    stock_for_roughing = radial_stock - spec.finish_pass_doc_mm

    # 3. Clamp max_roughing_doc to material recommended max
    _doc_min, _doc_max, recommended_doc = _MATERIAL_DOC_RANGES[spec.material]
    effective_max_doc = min(spec.max_roughing_doc_mm, _doc_max)

    # 4 & 5. Roughing pass count and actual DOC per pass
    if stock_for_roughing <= 0:
        num_roughing_passes = 0
        roughing_doc = 0.0
    else:
        num_roughing_passes = math.ceil(stock_for_roughing / effective_max_doc)
        roughing_doc = stock_for_roughing / num_roughing_passes

    num_finishing_passes = 1
    total_passes = num_roughing_passes + num_finishing_passes

    # 6. Time per pass [s]
    # feed_rate [mm/s] = feed_mm_per_rev × spindle_rpm / 60
    feed_rate_mm_per_s = spec.feed_mm_per_rev * spec.spindle_rpm / 60.0
    time_per_pass_s = spec.workpiece_length_mm / feed_rate_mm_per_s

    # 7. Total machining time
    total_machining_time_s = round(time_per_pass_s * total_passes, 6)

    # 8. Build caveat — append nose-radius warning if needed
    caveat = _HONEST_CAVEAT
    min_finish_doc = 0.5 * spec.tool_nose_radius_mm
    if spec.finish_pass_doc_mm < min_finish_doc:
        caveat = (
            f"WARNING: finish_pass_doc_mm ({spec.finish_pass_doc_mm:.3f} mm) is "
            f"below the MH 31e §1148 minimum of 0.5 × r_ε = "
            f"{min_finish_doc:.3f} mm (nose radius {spec.tool_nose_radius_mm:.3f} mm). "
            f"Risk of rubbing / poor surface finish. "
            + caveat
        )

    return TurningDepthReport(
        num_roughing_passes=num_roughing_passes,
        num_finishing_passes=num_finishing_passes,
        total_passes=total_passes,
        roughing_doc_mm=round(roughing_doc, 6),
        total_machining_time_s=total_machining_time_s,
        recommended_doc_for_material=recommended_doc,
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_compute_turning_depth_spec = ToolSpec(
    name="cam_compute_turning_depth",
    description=(
        "Compute optimal radial depth-of-cut (DOC) per pass and total number of "
        "roughing passes for a lathe turning operation. "
        "Inputs: stock OD, final OD, material (steel_1018|aluminum_6061|stainless_303), "
        "tool nose radius, feed (mm/rev), spindle RPM, optional finish_pass_doc (default 0.5 mm), "
        "optional max_roughing_doc (default 3.0 mm), optional workpiece_length_mm (default 100 mm). "
        "Returns: num_roughing_passes, num_finishing_passes, total_passes, roughing_doc_mm "
        "(equal DOC per roughing pass), total_machining_time_s, recommended_doc_for_material, "
        "and an honest caveat. "
        "Algorithm: radial_stock = (D_stock − D_final)/2; "
        "num_roughing = ceil((radial_stock − finish_doc) / effective_max_doc); "
        "roughing_doc = (radial_stock − finish_doc) / num_roughing; "
        "time = workpiece_length / (feed × rpm/60) × total_passes. "
        "DOC clamped to Sandvik CoroPlus 2024 / MH 31e §1148 material maximums. "
        "References: MH 31e §1148; Sandvik CoroPlus Turning Catalogue (2024). "
        "Honest limits: straight (cylindrical) turning only; no CSS/G96; no profile, "
        "taper, threading, or facing; time estimate excludes rapids and tool changes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stock_diameter_mm": {
                "type": "number",
                "description": "Stock outer diameter in mm.",
            },
            "final_diameter_mm": {
                "type": "number",
                "description": "Target final outer diameter in mm.",
            },
            "material": {
                "type": "string",
                "enum": ["steel_1018", "aluminum_6061", "stainless_303"],
                "description": "Work material class.",
            },
            "tool_nose_radius_mm": {
                "type": "number",
                "description": "Insert nose radius r_ε in mm (e.g. 0.4, 0.8, 1.2).",
            },
            "feed_mm_per_rev": {
                "type": "number",
                "description": "Programmed feed rate in mm/rev.",
            },
            "spindle_rpm": {
                "type": "number",
                "description": "Spindle speed in rpm.",
            },
            "finish_pass_doc_mm": {
                "type": "number",
                "description": (
                    "Radial depth of cut for the single finishing pass in mm. "
                    "Default 0.5 mm.  Should be ≥ 0.5 × tool_nose_radius_mm "
                    "(MH 31e §1148)."
                ),
            },
            "max_roughing_doc_mm": {
                "type": "number",
                "description": (
                    "Maximum radial depth of cut per roughing pass in mm. "
                    "Default 3.0 mm.  Clamped to material recommended max."
                ),
            },
            "workpiece_length_mm": {
                "type": "number",
                "description": (
                    "Axial length of cut used for machining time estimate in mm. "
                    "Default 100 mm."
                ),
            },
        },
        "required": [
            "stock_diameter_mm",
            "final_diameter_mm",
            "material",
            "tool_nose_radius_mm",
            "feed_mm_per_rev",
            "spindle_rpm",
        ],
    },
)


@register(cam_compute_turning_depth_spec)
async def run_cam_compute_turning_depth(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = [
        "stock_diameter_mm", "final_diameter_mm", "material",
        "tool_nose_radius_mm", "feed_mm_per_rev", "spindle_rpm",
    ]
    for field_name in required:
        if field_name not in a:
            return err_payload(f"missing required field: {field_name!r}", "BAD_ARGS")

    try:
        spec = TurningSpec(
            stock_diameter_mm=float(a["stock_diameter_mm"]),
            final_diameter_mm=float(a["final_diameter_mm"]),
            material=str(a["material"]),
            tool_nose_radius_mm=float(a["tool_nose_radius_mm"]),
            feed_mm_per_rev=float(a["feed_mm_per_rev"]),
            spindle_rpm=float(a["spindle_rpm"]),
            finish_pass_doc_mm=float(a.get("finish_pass_doc_mm", 0.5)),
            max_roughing_doc_mm=float(a.get("max_roughing_doc_mm", 3.0)),
            workpiece_length_mm=float(a.get("workpiece_length_mm", 100.0)),
        )
        result = compute_turning_depth(spec)
    except (TypeError, KeyError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "num_roughing_passes": result.num_roughing_passes,
        "num_finishing_passes": result.num_finishing_passes,
        "total_passes": result.total_passes,
        "roughing_doc_mm": result.roughing_doc_mm,
        "total_machining_time_s": result.total_machining_time_s,
        "recommended_doc_for_material": result.recommended_doc_for_material,
        "honest_caveat": result.honest_caveat,
    })
