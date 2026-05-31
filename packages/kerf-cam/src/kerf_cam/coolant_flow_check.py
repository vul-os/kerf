"""
kerf_cam.coolant_flow_check — Coolant flow-rate and pressure adequacy checker.

Given a CNC machining operation (MRR, tool diameter, material, coolant type,
available flow and pressure), recommends the minimum required coolant flow rate
[L/min] and pressure [bar], and verifies the spindle/through-tool coolant
system can deliver it.

Reference standards
-------------------
* Sandvik CoroPlus Coolant Application Guide §3 (2024) — flow rate heuristics
  per material; through-tool minimum pressures; titanium high-pressure
  requirement (≥70 bar).
* Machinery's Handbook 31e §1140 (Coolant application) — flood vs through-tool
  vs mist strategies; general flow guidelines.

Flow heuristics (Sandvik CoroPlus §3 / MH 31e §1140)
------------------------------------------------------
Required flow [L/min] = flow_factor × MRR [cm³/min]

  material         flow_factor
  --------         -----------
  steel            0.50
  stainless        0.60   (austenitic work-hardening → extra cooling)
  aluminum         0.30   (good thermal conductivity → lower demand)
  titanium         0.50   (but must use high-pressure through-tool)
  composite        0.20   (CFRP/GFRP — low heat, dust extraction primary)

Pressure heuristics (Sandvik CoroPlus §3)
-----------------------------------------
  coolant_type     tool_diameter_mm   min_pressure_bar
  ------------     ----------------   ----------------
  through_tool     any > 8            ≥ 20 bar (spindle coolant minimums)
  through_tool     any ≤ 8            ≥ 10 bar
  flood            any                ≥ 2 bar (pump delivery; advisory)
  mist             any                ≥ 4 bar
  MQL              any                ≥ 5 bar (atomising air)

  titanium (any coolant type)          ≥ 70 bar  (Sandvik CoroPlus §3 Ti
                                        high-pressure through-tool mandate)

Recommended coolant type
-------------------------
Rules (Sandvik CoroPlus §3 + MH 31e §1140):
  titanium → through_tool (always; high-pressure mandatory)
  stainless → through_tool preferred (chip breaking + heat evacuation)
  steel → flood adequate; through_tool improves tool life on deep ops
  aluminum → flood or MQL acceptable
  composite → MQL or mist (water-based coolant can delaminate CFRP)

Honest caveats
--------------
- Flow factors are heuristic averages from Sandvik CoroPlus §3 guidance;
  actual requirements depend on cut geometry (ae/ap ratio), specific alloy
  heat conductivity, insert grade, and chip volume.
- Coolant chemistry (water-soluble oil concentration, biocide, pH) and
  chip-evacuation effectiveness are NOT modelled here.
- High-pressure through-tool channels in the spindle and toolholder must be
  physically present and rated for the required pressure; this module only
  checks the *available* pressure against the *required* threshold — it does
  NOT verify mechanical pressure-seal integrity.
- MQL and mist strategies require separate near-dry machining setup; the flow
  figure is a volumetric lubricant flow, not a coolant flood flow.
- Composite materials may require positive-pressure air purge to prevent
  moisture ingress into delaminated fibres; water-based coolant is often
  contraindicated regardless of flow rate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Material flow factors: L/min per cm³/min MRR (Sandvik CoroPlus §3)
_FLOW_FACTORS: dict[str, float] = {
    "steel":      0.50,
    "stainless":  0.60,
    "aluminum":   0.30,
    "titanium":   0.50,
    "composite":  0.20,
}

_VALID_MATERIALS = frozenset(_FLOW_FACTORS.keys())
_VALID_COOLANT_TYPES = frozenset(["flood", "through_tool", "mist", "MQL"])

# Through-tool minimum pressure thresholds (Sandvik CoroPlus §3)
_THROUGH_TOOL_PRESSURE_LARGE_MM = 8.0   # threshold: d > 8 mm
_THROUGH_TOOL_PRESSURE_LARGE_BAR = 20.0
_THROUGH_TOOL_PRESSURE_SMALL_BAR = 10.0

# Minimum pressure for each coolant type (Sandvik CoroPlus §3 / advisory)
_MIN_PRESSURE_BY_TYPE: dict[str, float] = {
    "flood":        2.0,
    "through_tool": _THROUGH_TOOL_PRESSURE_SMALL_BAR,  # base; overridden by d>8mm
    "mist":         4.0,
    "MQL":          5.0,
}

# Titanium high-pressure mandate (Sandvik CoroPlus §3)
_TITANIUM_MIN_PRESSURE_BAR = 70.0

_HONEST_CAVEAT = (
    "Flow factors are heuristic averages from Sandvik CoroPlus Coolant Guide §3; "
    "actual requirements depend on radial/axial engagement ratio, specific alloy "
    "thermal conductivity, insert grade, and chip volume — verify against "
    "CoroPlus ToolGuide for production settings. "
    "Coolant chemistry (concentration, pH, biocide), chip-evacuation "
    "effectiveness, and nozzle positioning are NOT modelled. "
    "High-pressure through-tool delivery requires a spindle and toolholder "
    "physically rated for the specified pressure; this module verifies only "
    "available vs required pressure, not mechanical seal integrity. "
    "MQL/mist flow figures are lubricant volumetric flow — not coolant flood; "
    "these strategies require separate near-dry machining setup. "
    "Composite (CFRP/GFRP) may require dry or MQL-only machining; water-based "
    "coolant can promote delamination regardless of flow rate."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MachiningOpForCoolant:
    """Input specification for a coolant flow check.

    Parameters
    ----------
    mrr_cm3_per_min       : Material-removal rate [cm³/min].
    tool_diameter_mm      : Tool cutting diameter [mm].
    axial_depth_mm        : Axial depth of cut (ap) [mm].  Informational;
                            feeds the MRR context but does not alter the
                            flow heuristic directly.
    material              : Workpiece material class:
                            "steel" | "aluminum" | "stainless" | "titanium"
                            | "composite".
    coolant_type          : Current/intended coolant delivery:
                            "flood" | "through_tool" | "mist" | "MQL".
    available_flow_L_per_min  : Coolant flow the machine can deliver [L/min].
    available_pressure_bar    : Coolant pressure the machine can deliver [bar].
    """
    mrr_cm3_per_min: float
    tool_diameter_mm: float
    axial_depth_mm: float
    material: str
    coolant_type: str
    available_flow_L_per_min: float
    available_pressure_bar: float

    def __post_init__(self) -> None:
        if self.mrr_cm3_per_min <= 0:
            raise ValueError(
                f"mrr_cm3_per_min must be > 0, got {self.mrr_cm3_per_min!r}"
            )
        if self.tool_diameter_mm <= 0:
            raise ValueError(
                f"tool_diameter_mm must be > 0, got {self.tool_diameter_mm!r}"
            )
        if self.axial_depth_mm <= 0:
            raise ValueError(
                f"axial_depth_mm must be > 0, got {self.axial_depth_mm!r}"
            )
        if self.material not in _VALID_MATERIALS:
            raise ValueError(
                f"material must be one of {sorted(_VALID_MATERIALS)}, "
                f"got {self.material!r}"
            )
        if self.coolant_type not in _VALID_COOLANT_TYPES:
            raise ValueError(
                f"coolant_type must be one of {sorted(_VALID_COOLANT_TYPES)}, "
                f"got {self.coolant_type!r}"
            )
        if self.available_flow_L_per_min < 0:
            raise ValueError(
                f"available_flow_L_per_min must be >= 0, "
                f"got {self.available_flow_L_per_min!r}"
            )
        if self.available_pressure_bar < 0:
            raise ValueError(
                f"available_pressure_bar must be >= 0, "
                f"got {self.available_pressure_bar!r}"
            )


@dataclass
class CoolantFlowReport:
    """Result from ``check_coolant_flow``.

    Attributes
    ----------
    required_flow_L_per_min     : Minimum required coolant flow [L/min].
    required_pressure_bar       : Minimum required coolant pressure [bar].
    flow_adequate               : True if available_flow >= required_flow.
    pressure_adequate           : True if available_pressure >= required_pressure.
    recommended_coolant_type    : Sandvik-recommended delivery strategy for
                                  the specified material.
    honest_caveat               : Plain-English limitations and assumptions.
    """
    required_flow_L_per_min: float
    required_pressure_bar: float
    flow_adequate: bool
    pressure_adequate: bool
    recommended_coolant_type: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Recommended coolant type per material
# ---------------------------------------------------------------------------

_RECOMMENDED_COOLANT: dict[str, str] = {
    "titanium":   "through_tool",    # mandatory high-pressure through-tool
    "stainless":  "through_tool",    # preferred for chip breaking + heat
    "steel":      "flood",           # flood adequate; through-tool improves life
    "aluminum":   "flood",           # flood or MQL acceptable
    "composite":  "MQL",             # MQL/mist; water-based can delaminate
}


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def check_coolant_flow(spec: MachiningOpForCoolant) -> CoolantFlowReport:
    """Check coolant flow and pressure adequacy for a machining operation.

    Algorithm
    ---------
    1.  required_flow = flow_factor[material] × mrr_cm3_per_min  [L/min]
        flow_factor: steel=0.50, aluminum=0.30, stainless=0.60,
                     titanium=0.50, composite=0.20

    2.  required_pressure:
        - titanium (any coolant): 70 bar  (Sandvik CoroPlus §3 mandate)
        - through_tool, d > 8 mm: 20 bar
        - through_tool, d ≤ 8 mm: 10 bar
        - flood:                   2 bar
        - mist:                    4 bar
        - MQL:                     5 bar

    3.  flow_adequate     = available_flow     >= required_flow
        pressure_adequate = available_pressure >= required_pressure

    4.  recommended_coolant_type from material-specific Sandvik §3 guidance.

    Parameters
    ----------
    spec : MachiningOpForCoolant — validated by __post_init__.

    Returns
    -------
    CoolantFlowReport
    """
    # 1. Required flow
    factor = _FLOW_FACTORS[spec.material]
    required_flow = round(factor * spec.mrr_cm3_per_min, 4)

    # 2. Required pressure
    if spec.material == "titanium":
        required_pressure = _TITANIUM_MIN_PRESSURE_BAR
    elif spec.coolant_type == "through_tool":
        if spec.tool_diameter_mm > _THROUGH_TOOL_PRESSURE_LARGE_MM:
            required_pressure = _THROUGH_TOOL_PRESSURE_LARGE_BAR
        else:
            required_pressure = _THROUGH_TOOL_PRESSURE_SMALL_BAR
    else:
        required_pressure = _MIN_PRESSURE_BY_TYPE[spec.coolant_type]

    # 3. Adequacy checks
    flow_adequate = spec.available_flow_L_per_min >= required_flow
    pressure_adequate = spec.available_pressure_bar >= required_pressure

    # 4. Recommended coolant type
    recommended = _RECOMMENDED_COOLANT[spec.material]

    return CoolantFlowReport(
        required_flow_L_per_min=required_flow,
        required_pressure_bar=required_pressure,
        flow_adequate=flow_adequate,
        pressure_adequate=pressure_adequate,
        recommended_coolant_type=recommended,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_check_coolant_flow_spec = ToolSpec(
    name="cam_check_coolant_flow",
    description=(
        "Given a CNC machining operation (MRR, tool diameter, material, "
        "coolant type, available flow and pressure), recommends the minimum "
        "required coolant flow rate [L/min] and verifies the spindle / "
        "through-tool coolant system can deliver it. "
        "Flow heuristic: required_flow = flow_factor × MRR; factors: "
        "steel=0.50, stainless=0.60, aluminum=0.30, titanium=0.50, "
        "composite=0.20 L/min per cm³/min (Sandvik CoroPlus Coolant Guide §3). "
        "Pressure thresholds: titanium any coolant ≥70 bar; through-tool "
        "d>8mm ≥20 bar; through-tool d≤8mm ≥10 bar; flood ≥2 bar; "
        "mist ≥4 bar; MQL ≥5 bar (Sandvik CoroPlus §3). "
        "Returns: required_flow_L_per_min, required_pressure_bar, "
        "flow_adequate, pressure_adequate, recommended_coolant_type, "
        "honest_caveat. "
        "Honest limits: flow factors are heuristic averages — coolant "
        "chemistry, concentration, and chip-evacuation effectiveness are "
        "out of scope. "
        "References: Sandvik CoroPlus Coolant Guide §3 (2024); "
        "MH 31e §1140 (Coolant application)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mrr_cm3_per_min": {
                "type": "number",
                "description": "Material-removal rate in cm³/min.",
            },
            "tool_diameter_mm": {
                "type": "number",
                "description": "Tool cutting diameter in mm.",
            },
            "axial_depth_mm": {
                "type": "number",
                "description": "Axial depth of cut (ap) in mm.",
            },
            "material": {
                "type": "string",
                "enum": ["steel", "aluminum", "stainless", "titanium", "composite"],
                "description": "Workpiece material class.",
            },
            "coolant_type": {
                "type": "string",
                "enum": ["flood", "through_tool", "mist", "MQL"],
                "description": "Coolant delivery strategy.",
            },
            "available_flow_L_per_min": {
                "type": "number",
                "description": "Coolant flow the machine can deliver [L/min].",
            },
            "available_pressure_bar": {
                "type": "number",
                "description": "Coolant pressure the machine can deliver [bar].",
            },
        },
        "required": [
            "mrr_cm3_per_min",
            "tool_diameter_mm",
            "axial_depth_mm",
            "material",
            "coolant_type",
            "available_flow_L_per_min",
            "available_pressure_bar",
        ],
    },
)


@register(cam_check_coolant_flow_spec)
async def run_cam_check_coolant_flow(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required_fields = [
        "mrr_cm3_per_min", "tool_diameter_mm", "axial_depth_mm",
        "material", "coolant_type",
        "available_flow_L_per_min", "available_pressure_bar",
    ]
    for field in required_fields:
        if field not in a:
            return err_payload(f"missing required field: {field!r}", "BAD_ARGS")

    try:
        spec = MachiningOpForCoolant(
            mrr_cm3_per_min=float(a["mrr_cm3_per_min"]),
            tool_diameter_mm=float(a["tool_diameter_mm"]),
            axial_depth_mm=float(a["axial_depth_mm"]),
            material=str(a["material"]),
            coolant_type=str(a["coolant_type"]),
            available_flow_L_per_min=float(a["available_flow_L_per_min"]),
            available_pressure_bar=float(a["available_pressure_bar"]),
        )
        result = check_coolant_flow(spec)
    except (TypeError, KeyError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "required_flow_L_per_min": result.required_flow_L_per_min,
        "required_pressure_bar": result.required_pressure_bar,
        "flow_adequate": result.flow_adequate,
        "pressure_adequate": result.pressure_adequate,
        "recommended_coolant_type": result.recommended_coolant_type,
        "honest_caveat": result.honest_caveat,
    })
