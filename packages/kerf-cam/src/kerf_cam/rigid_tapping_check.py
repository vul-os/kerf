"""
kerf_cam.rigid_tapping_check — Rigid-tap operation validator.

Verifies a rigid-tap operation against machine spindle synchronisation
capability and tap-strength limits given material/tool/spindle parameters.
Returns recommended feed override + warning flags.

Reference standards
-------------------
* Sandvik CoroPlus Technical Guide (2024) — rigid tapping torque coefficients,
  recommended speeds by material/tool combination.
* Machinery's Handbook 31e §1934 — rigid tapping force/torque limits,
  feed coupling F = pitch × rpm.
* NIST RS-274/NGC §3.8.4 — G84/G74 rigid tapping coupling constraints.

Torque model
------------
Empirical approximation (Sandvik CoroPlus + MH 31e §1934 data):

    T = K · D³

where:
  T — tapping torque [N·m]
  D — nominal thread diameter [mm]
  K — empirical coefficient (material × tool):

  | Tool    | Material            | K      |
  |---------|---------------------|--------|
  | HSS     | steel_1018          | 0.35   |
  | cobalt  | steel_1018          | 0.30   |
  | carbide | steel_1018          | 0.25   |
  | HSS     | stainless_303       | 0.50   |
  | cobalt  | stainless_303       | 0.42   |
  | carbide | stainless_303       | 0.35   |
  | HSS     | aluminum_6061       | 0.10   |
  | cobalt  | aluminum_6061       | 0.09   |
  | carbide | aluminum_6061       | 0.08   |
  | HSS     | brass               | 0.15   |
  | cobalt  | brass               | 0.13   |
  | carbide | brass               | 0.11   |

Feed coupling
-------------
F (mm/min) = pitch × rpm — the ONLY correct rigid-tap relationship.
Any mismatch will strip threads or break the tap.

Breakage risk heuristic
-----------------------
Risk score accumulates from three independent factors:
  1. Deep hole: depth_mm > 3 × D → +1
  2. Spindle too fast for material/tool: rpm > rpm_limit(material, tool) → +1
  3. Stainless or above + HSS at high torque level → +1

Score 0   → "low"
Score 1   → "medium"
Score ≥ 2 → "high"

Feed override recommendation
-----------------------------
If sync_compliant is False (rpm > machine_max_sync_rpm):
    recommended_feed_override_pct = (machine_max_sync_rpm / rpm) × 100

Otherwise:
    recommended_feed_override_pct = 100.0  (no override needed)

Caveats (honest_caveat)
------------------------
K coefficients are empirical curve-fits from Sandvik CoroPlus 2024 and MH 31e
§1934 sample data. They ignore:
  - Coolant/lubricant effects (flood vs mist vs dry — can reduce torque 20–40 %)
  - Tap geometry variations (spiral-flute, spiral-point, hand-flute — torque can
    vary ±30 % for the same nominal tap diameter)
  - Thread engagement length (through-hole vs blind), thread-fit class (2B vs 3B)
  - Work hardening (stainless 303 vs 316 — 316 runs ~20 % higher torque)
  - Worn tool state, chip packing in blind holes, tap coating (TiN/TiAlN)

Treat T = K·D³ as ±35 % guidance only. Verify against tap manufacturer data
before production runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Tuple

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Constants — empirical K coefficients (Sandvik CoroPlus 2024 + MH 31e §1934)
# ---------------------------------------------------------------------------

# (material, tool_material) → K coefficient for T = K · D³  [N·m / mm³]
_K_TABLE: dict[tuple[str, str], float] = {
    # steel_1018
    ("steel_1018",    "HSS"):     0.35,
    ("steel_1018",    "cobalt"):  0.30,
    ("steel_1018",    "carbide"): 0.25,
    # stainless_303
    ("stainless_303", "HSS"):     0.50,
    ("stainless_303", "cobalt"):  0.42,
    ("stainless_303", "carbide"): 0.35,
    # aluminum_6061
    ("aluminum_6061", "HSS"):     0.10,
    ("aluminum_6061", "cobalt"):  0.09,
    ("aluminum_6061", "carbide"): 0.08,
    # brass
    ("brass",         "HSS"):     0.15,
    ("brass",         "cobalt"):  0.13,
    ("brass",         "carbide"): 0.11,
}

# Recommended maximum RPM per (material, tool_material) for rigid tapping
# Based on Sandvik CoroPlus 2024 tapping guidelines
_RPM_LIMIT: dict[tuple[str, str], int] = {
    ("steel_1018",    "HSS"):     1500,
    ("steel_1018",    "cobalt"):  2000,
    ("steel_1018",    "carbide"): 3000,
    ("stainless_303", "HSS"):     800,
    ("stainless_303", "cobalt"):  1200,
    ("stainless_303", "carbide"): 2000,
    ("aluminum_6061", "HSS"):     3000,
    ("aluminum_6061", "cobalt"):  4000,
    ("aluminum_6061", "carbide"): 6000,
    ("brass",         "HSS"):     2000,
    ("brass",         "cobalt"):  2500,
    ("brass",         "carbide"): 3500,
}

_VALID_MATERIALS = frozenset(["steel_1018", "aluminum_6061", "stainless_303", "brass"])
_VALID_TOOLS = frozenset(["HSS", "cobalt", "carbide"])


# ---------------------------------------------------------------------------
# Thread size parser
# ---------------------------------------------------------------------------

def _parse_thread_size(thread_size: str) -> Tuple[float, float]:
    """Parse thread size string → (diameter_mm, pitch_mm).

    Supports:
    - Metric: "M6x1.0", "M6X1.0", "M10x1.5", "M4x0.7"
    - UNC/UNF inch: "1/4-20", "3/8-16", "1/2-13", "1/4-28"

    Returns (nominal_diameter_mm, pitch_mm).

    Raises ValueError for unrecognised formats.
    """
    s = thread_size.strip()

    # Metric: M<diameter>x<pitch> or M<diameter>X<pitch>
    m = re.match(r'^[Mm](\d+(?:\.\d+)?)[xX](\d+(?:\.\d+)?)$', s)
    if m:
        d_mm = float(m.group(1))
        p_mm = float(m.group(2))
        if d_mm <= 0 or p_mm <= 0:
            raise ValueError(f"Thread size values must be > 0: {thread_size!r}")
        return d_mm, p_mm

    # UNC/UNF inch: numerator/denominator-tpi  e.g. "1/4-20", "3/8-16"
    m = re.match(r'^(\d+)/(\d+)-(\d+(?:\.\d+)?)$', s)
    if m:
        num = float(m.group(1))
        den = float(m.group(2))
        tpi = float(m.group(3))
        if den == 0:
            raise ValueError(f"Thread size denominator must not be zero: {thread_size!r}")
        if tpi <= 0:
            raise ValueError(f"TPI must be > 0: {thread_size!r}")
        d_inch = num / den
        d_mm = d_inch * 25.4
        p_mm = 25.4 / tpi
        return d_mm, p_mm

    # UNC/UNF with whole-inch numerator: "1-8", "2-4.5" (rare but legal)
    m = re.match(r'^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$', s)
    if m:
        d_inch = float(m.group(1))
        tpi = float(m.group(2))
        if tpi <= 0:
            raise ValueError(f"TPI must be > 0: {thread_size!r}")
        d_mm = d_inch * 25.4
        p_mm = 25.4 / tpi
        return d_mm, p_mm

    raise ValueError(
        f"Unrecognised thread_size format {thread_size!r}. "
        f"Use 'M6x1.0' (metric) or '1/4-20' (inch UNC/UNF)."
    )


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RigidTapSpec:
    """Input specification for a rigid-tap operation check.

    Parameters
    ----------
    thread_size         : Thread designation, e.g. "M6x1.0", "M10x1.5", "1/4-20".
    material            : Work material — one of "steel_1018", "aluminum_6061",
                          "stainless_303", "brass".
    hole_depth_mm       : Tapping depth in mm (positive value).
    spindle_rpm         : Programmed spindle speed (rpm).
    machine_max_sync_rpm: Machine spindle synchronisation limit (rpm).
                          Exceeding this breaks the rigid-tap F = pitch × rpm
                          coupling — the controller cannot maintain synchronisation.
    tap_tool_material   : Tap material — "HSS", "cobalt", or "carbide".
    """
    thread_size: str
    material: str
    hole_depth_mm: float
    spindle_rpm: float
    machine_max_sync_rpm: int
    tap_tool_material: str

    def __post_init__(self):
        if self.hole_depth_mm <= 0:
            raise ValueError(f"hole_depth_mm must be > 0, got {self.hole_depth_mm!r}")
        if self.spindle_rpm <= 0:
            raise ValueError(f"spindle_rpm must be > 0, got {self.spindle_rpm!r}")
        if self.machine_max_sync_rpm <= 0:
            raise ValueError(
                f"machine_max_sync_rpm must be > 0, got {self.machine_max_sync_rpm!r}"
            )
        if self.material not in _VALID_MATERIALS:
            raise ValueError(
                f"material must be one of {sorted(_VALID_MATERIALS)}, "
                f"got {self.material!r}"
            )
        if self.tap_tool_material not in _VALID_TOOLS:
            raise ValueError(
                f"tap_tool_material must be one of {sorted(_VALID_TOOLS)}, "
                f"got {self.tap_tool_material!r}"
            )
        # Validate thread_size format eagerly
        _parse_thread_size(self.thread_size)


@dataclass
class RigidTapReport:
    """Result from ``check_rigid_tap``.

    Attributes
    ----------
    recommended_torque_Nm        : Estimated tapping torque [N·m] via T = K · D³.
    computed_feed_mm_per_min     : Rigid-tap feed rate [mm/min] = pitch × rpm.
    sync_compliant               : True if spindle_rpm ≤ machine_max_sync_rpm.
    tap_breakage_risk            : "low", "medium", or "high".
    recommended_feed_override_pct: Suggested feed override % (100 = no change;
                                   < 100 indicates the operator should reduce
                                   feed to stay within sync limit).
    honest_caveat                : Plain-English limitations.
    """
    recommended_torque_Nm: float
    computed_feed_mm_per_min: float
    sync_compliant: bool
    tap_breakage_risk: str          # "low" | "medium" | "high"
    recommended_feed_override_pct: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def check_rigid_tap(spec: RigidTapSpec) -> RigidTapReport:
    """Verify a rigid-tap operation and return the RigidTapReport.

    Algorithm
    ---------
    1. Parse thread_size → (D_mm, pitch_mm).
    2. Look up K from _K_TABLE[(material, tap_tool_material)].
    3. T = K × D³  [N·m]
    4. F = pitch × rpm  [mm/min]
    5. sync_compliant = (rpm ≤ machine_max_sync_rpm)
    6. Breakage risk heuristic (score 0=low, 1=medium, ≥2=high):
       - depth_mm > 3 × D → +1
       - rpm > _RPM_LIMIT[(material, tool)] → +1
       - material in {stainless_303} AND tool == "HSS" AND D < 8 mm → +1
    7. Feed override = min(100, (machine_max_sync_rpm / rpm) × 100) when not
       sync_compliant; else 100.

    Parameters
    ----------
    spec : RigidTapSpec — validated by its __post_init__.

    Returns
    -------
    RigidTapReport
    """
    d_mm, pitch_mm = _parse_thread_size(spec.thread_size)

    key = (spec.material, spec.tap_tool_material)
    k = _K_TABLE[key]  # always present — validated by __post_init__

    # Torque [N·m] — T = K · D³ where D is in mm
    # Note: K is in units of N·m / mm³ so result is directly in N·m.
    torque_Nm = k * (d_mm ** 3)

    # Feed [mm/min] — rigid-tap coupling (MH 31e §1934)
    feed_mm_per_min = pitch_mm * spec.spindle_rpm

    # Sync compliance
    sync_compliant = spec.spindle_rpm <= spec.machine_max_sync_rpm

    # Breakage risk score
    risk_score = 0
    rpm_limit = _RPM_LIMIT[key]

    if spec.hole_depth_mm > 3.0 * d_mm:
        risk_score += 1

    if spec.spindle_rpm > rpm_limit:
        risk_score += 1

    # Stainless + small HSS tap is particularly prone to breakage
    if spec.material == "stainless_303" and spec.tap_tool_material == "HSS" and d_mm < 8.0:
        risk_score += 1

    if risk_score == 0:
        tap_breakage_risk = "low"
    elif risk_score == 1:
        tap_breakage_risk = "medium"
    else:
        tap_breakage_risk = "high"

    # Feed override recommendation
    if sync_compliant:
        recommended_feed_override_pct = 100.0
    else:
        recommended_feed_override_pct = round(
            (spec.machine_max_sync_rpm / spec.spindle_rpm) * 100.0, 1
        )

    honest_caveat = (
        "Torque estimate T = K·D³ uses empirical K coefficients from Sandvik CoroPlus "
        "2024 and MH 31e §1934. Accuracy is ±35 %: coolant/lubricant effects "
        "(flood vs dry can reduce torque 20–40 %), tap geometry (spiral-flute vs "
        "spiral-point vs hand-flute, ±30 %), thread engagement and fit class, work "
        "hardening (303 vs 316 stainless ~20 % difference), worn tool state, chip "
        "packing in blind holes, and TiN/TiAlN coatings are all NOT modelled. "
        "Feed coupling F = pitch × rpm (MH 31e §1934) is exact for rigid tapping; "
        "any mismatch will strip threads or break the tap — verify F and S against "
        "your controller documentation. sync_compliant checks only the programmed "
        "rpm against machine_max_sync_rpm; actual sync quality also depends on "
        "encoder resolution and servo bandwidth. Treat recommended_feed_override_pct "
        "as a starting point — verify on a test coupon before production."
    )

    return RigidTapReport(
        recommended_torque_Nm=round(torque_Nm, 4),
        computed_feed_mm_per_min=round(feed_mm_per_min, 4),
        sync_compliant=sync_compliant,
        tap_breakage_risk=tap_breakage_risk,
        recommended_feed_override_pct=recommended_feed_override_pct,
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_check_rigid_tap_spec = ToolSpec(
    name="cam_check_rigid_tap",
    description=(
        "Verify a rigid-tap operation against machine spindle synchronisation "
        "capability and tap-strength limits given material/tool/spindle parameters. "
        "Returns: recommended tapping torque (T = K·D³, Sandvik CoroPlus 2024 / "
        "MH 31e §1934); computed feed rate (pitch × rpm); sync_compliant flag "
        "(rpm ≤ machine_max_sync_rpm); tap breakage risk ('low'|'medium'|'high'); "
        "recommended feed override % (< 100 if rpm exceeds machine sync limit); "
        "and an honest caveat on the empirical K coefficient limitations. "
        "Supports metric threads (M6x1.0, M10x1.5) and inch UNC/UNF (1/4-20, 3/8-16). "
        "Materials: steel_1018, aluminum_6061, stainless_303, brass. "
        "Tap materials: HSS, cobalt, carbide."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "thread_size": {
                "type": "string",
                "description": (
                    "Thread designation: metric 'M6x1.0' / 'M10x1.5' or "
                    "inch UNC/UNF '1/4-20' / '3/8-16'."
                ),
            },
            "material": {
                "type": "string",
                "enum": ["steel_1018", "aluminum_6061", "stainless_303", "brass"],
                "description": "Work material.",
            },
            "hole_depth_mm": {
                "type": "number",
                "description": "Tapping depth in mm (positive).",
            },
            "spindle_rpm": {
                "type": "number",
                "description": "Programmed spindle speed in rpm.",
            },
            "machine_max_sync_rpm": {
                "type": "integer",
                "description": (
                    "Machine spindle synchronisation RPM limit. "
                    "Exceeding this breaks the F = pitch × rpm coupling."
                ),
            },
            "tap_tool_material": {
                "type": "string",
                "enum": ["HSS", "cobalt", "carbide"],
                "description": "Tap material.",
            },
        },
        "required": [
            "thread_size",
            "material",
            "hole_depth_mm",
            "spindle_rpm",
            "machine_max_sync_rpm",
            "tap_tool_material",
        ],
    },
)


@register(cam_check_rigid_tap_spec)
async def run_cam_check_rigid_tap(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = [
        "thread_size", "material", "hole_depth_mm",
        "spindle_rpm", "machine_max_sync_rpm", "tap_tool_material",
    ]
    for field in required:
        if field not in a:
            return err_payload(f"missing required field: {field!r}", "BAD_ARGS")

    try:
        spec = RigidTapSpec(
            thread_size=str(a["thread_size"]),
            material=str(a["material"]),
            hole_depth_mm=float(a["hole_depth_mm"]),
            spindle_rpm=float(a["spindle_rpm"]),
            machine_max_sync_rpm=int(a["machine_max_sync_rpm"]),
            tap_tool_material=str(a["tap_tool_material"]),
        )
        result = check_rigid_tap(spec)
    except (KeyError, TypeError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "recommended_torque_Nm": result.recommended_torque_Nm,
        "computed_feed_mm_per_min": result.computed_feed_mm_per_min,
        "sync_compliant": result.sync_compliant,
        "tap_breakage_risk": result.tap_breakage_risk,
        "recommended_feed_override_pct": result.recommended_feed_override_pct,
        "honest_caveat": result.honest_caveat,
    })
