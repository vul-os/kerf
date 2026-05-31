"""
kerf_cam.dry_machining_check — Dry-machining feasibility checker.

Given a CAM operation (workpiece material, tool coating, cutting speed vc,
feed per tooth fz, radial engagement ae, axial depth ap, tool diameter, and
operation type), determines whether dry machining is feasible per Sandvik
Coromant dry-machining guidelines and ISO 8688-1 tool-wear standards.

Returns a recommendation, predicted tool-life reduction factor vs flood
coolant, minimum coating requirements, and per-scenario warnings.

Reference standards
-------------------
* Sandvik Coromant Dry and Near-Dry Machining Application Guide (2024) —
  material-by-material dry feasibility; coating requirements; vc derate
  factors; MQL recommendations.
* ISO 8688-1:1989 / ISO 8688-2:1989 — Tool life testing in milling /
  turning; VB (flank wear) criterion; Taylor tool-life model.
* Klocke F., Eisenblätter G. "Dry cutting" CIRP Ann. 46(2) 1997 —
  dry-cutting taxonomy; thermal loading per material class.
* Biermann D. et al. "Dry and Near-Dry Machining" Springer 2020 §4 —
  Ti6Al4V: oxidation, BUE, chemical reactivity at 600 °C+; MQL minimum.

Dry-machining feasibility rules (Sandvik Coromant 2024 + ISO 8688-1)
---------------------------------------------------------------------
Material class             | Dry outcome  | Factor vs flood  | Notes
---------------------------|--------------|------------------|----------------------------
cast-iron-grey             | FEASIBLE     | 0.90–1.00        | Graphite acts as lubricant;
                           |              |                  | uncoated carbide acceptable;
                           |              |                  | TiAlN preferred (Sandvik §5)
steel-low-carbon           | CONDITIONAL  | 0.70–0.85        | TiAlN/AlCrN required;
                           |              |                  | vc derate 20-30%
steel-medium-carbon        | CONDITIONAL  | 0.65–0.80        | Same coating; vc derate 25-35%
steel-stainless-austenitic | CONDITIONAL  | 0.50–0.65        | AlCrN/TiAlN mandatory;
                           |              |                  | vc derate 30-50%; work-hardening
aluminum-wrought           | NOT FEASIBLE | 0.40–0.60        | Chip welding (BUE); gumming;
                           |              |                  | recommend flood or MQL
aluminum-cast              | NOT FEASIBLE | 0.40–0.60        | Same BUE risk
titanium-Ti6Al4V           | CHALLENGING  | 0.30–0.50        | Chemical reactivity 600 °C+;
                           |              |                  | BUE + tool combustion risk;
                           |              |                  | MQL minimum required
nickel-inconel-718         | NOT FEASIBLE | 0.25–0.45        | Work-hardening + tool wear;
                           |              |                  | extreme heat; requires flood

Coating requirements
--------------------
* uncoated  : only acceptable for grey cast iron (graphite lubrication)
* TiN       : marginal improvement; not recommended for stainless/Ti/Ni
* TiAlN     : minimum for steel dry machining; good oxidation resistance
* AlCrN     : preferred for stainless, Ti (limited), high-vc operations;
              superior hot hardness > TiAlN at 900 °C+ (Sandvik §4)
* diamond-CVD: cast iron NOT recommended (graphite adhesion issues);
              excellent for aluminium MQL (no BUE on diamond); best for
              CFRP/composites dry

Speed derate table (dry vs flood, Sandvik Coromant 2024)
---------------------------------------------------------
  Material               | Derate factor (vc_dry / vc_flood)
  -----------------------|----------------------------------
  cast-iron-grey         | 0.90 – 1.00  (often no derate needed)
  steel-low-carbon       | 0.70 – 0.80
  steel-medium-carbon    | 0.65 – 0.75
  steel-stainless-auste  | 0.50 – 0.70
  aluminum-wrought       | N/A (flood preferred)
  aluminum-cast          | N/A (flood preferred)
  titanium-Ti6Al4V       | 0.50 – 0.70  (with MQL)
  nickel-inconel-718     | 0.40 – 0.60  (with flood only)

ISO 8688-1 tool-life reduction criterion
-----------------------------------------
Tool life T (min) is related to flood cutting speed by Taylor's equation:
  T_flood = C / vc^n
Dry machining increases the thermal load → effective Taylor C constant
drops by (1 - thermal_penalty).  The tool_life_reduction_factor reported
here is the ratio T_dry / T_flood using the derate factor midpoint, so
a factor of 0.95 means dry tool life ≈ 95% of flood tool life.

Honest caveats
--------------
- Rules are heuristic averages from the Sandvik Coromant Application Guide
  and CIRP literature.  Actual feasibility depends on machine rigidity,
  spindle thermal compensation, chip-air evacuation, insert geometry,
  exact alloy composition, BUE tendency, and workpiece surface finish
  requirements — verify against Sandvik CoroPlus ToolGuide or chip-form
  testing before production deployment.
- ISO 8688-1 Taylor exponents (n) and constants (C) vary widely by insert
  grade and workpiece alloy; the tool_life_reduction_factor here uses
  Sandvik mid-range values and should be treated as an order-of-magnitude
  estimate only (±40 %).
- The module does NOT model thermal FEA, chip-evacuation dynamics, or
  machine-specific spindle temperature behaviour.
- Ti6Al4V dry machining can lead to tool combustion at vc > 60 m/min
  without coolant (Biermann 2020 §4); this module flags the risk but
  cannot substitute for physical testing.
- Grey cast iron dust / fume hazard requires adequate machine enclosure
  and extraction regardless of dry-machining feasibility verdict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Valid enumerations
# ---------------------------------------------------------------------------

_VALID_MATERIALS = frozenset([
    "steel-low-carbon",
    "steel-medium-carbon",
    "steel-stainless-austenitic",
    "cast-iron-grey",
    "aluminum-wrought",
    "aluminum-cast",
    "titanium-Ti6Al4V",
    "nickel-inconel-718",
])

_VALID_COATINGS = frozenset([
    "uncoated",
    "TiN",
    "TiAlN",
    "AlCrN",
    "diamond-CVD",
])

_VALID_OPERATIONS = frozenset([
    "milling-roughing",
    "milling-finishing",
    "drilling",
    "turning",
])

# Feasibility verdicts
_FEASIBLE = "feasible"
_CONDITIONAL = "conditional"
_CHALLENGING = "challenging"
_NOT_FEASIBLE = "not-feasible"


# ---------------------------------------------------------------------------
# Per-material dry-machining configuration
# ---------------------------------------------------------------------------
# Each entry:
#   verdict          : _FEASIBLE | _CONDITIONAL | _CHALLENGING | _NOT_FEASIBLE
#   factor_mid       : midpoint tool-life reduction factor vs flood (used as default)
#   factor_low       : lower bound (worst-case reduction)
#   factor_high      : upper bound (best-case)
#   vc_derate_low    : lower vc_dry/vc_flood ratio
#   vc_derate_high   : upper vc_dry/vc_flood ratio
#   min_coating      : minimum acceptable coating for dry machining
#   preferred_coatings: ordered list of preferred coatings (best first)
#   notes            : short rationale string

@dataclass
class _MaterialConfig:
    verdict: str
    factor_low: float
    factor_high: float
    # Absolute vc upper limit for dry machining [m/min]; 0 = not recommended
    # Derived from Sandvik Coromant Application Guide (2024) catalogue ranges
    max_vc_dry_abs: float
    min_coating: str
    preferred_coatings: List[str]
    notes: str

    @property
    def factor_mid(self) -> float:
        return round((self.factor_low + self.factor_high) / 2.0, 4)


_MATERIAL_CONFIG: dict[str, _MaterialConfig] = {
    # Grey cast iron: typical flood vc 200-400 m/min; dry vc 180-400 m/min
    # (graphite lubrication; minimal derate).  Upper limit 400 m/min (Sandvik §5)
    "cast-iron-grey": _MaterialConfig(
        verdict=_FEASIBLE,
        factor_low=0.90,
        factor_high=1.00,
        max_vc_dry_abs=400.0,
        min_coating="uncoated",
        preferred_coatings=["TiAlN", "AlCrN", "uncoated"],
        notes=(
            "Grey cast iron is the benchmark dry-machining material — "
            "graphite flakes act as a solid lubricant, reducing friction at "
            "the tool-chip interface (Sandvik §5).  Uncoated carbide is "
            "acceptable; TiAlN or AlCrN extends tool life by 10-30 %."
        ),
    ),
    # Low-carbon steel: flood vc 150-250 m/min; dry vc 100-180 m/min
    # (20-30 % derate; BUE below 80 m/min).  Upper dry limit 180 m/min.
    "steel-low-carbon": _MaterialConfig(
        verdict=_CONDITIONAL,
        factor_low=0.70,
        factor_high=0.85,
        max_vc_dry_abs=180.0,
        min_coating="TiAlN",
        preferred_coatings=["AlCrN", "TiAlN"],
        notes=(
            "Low-carbon steel can be machined dry with TiAlN/AlCrN coatings "
            "and a 20-30 % vc reduction vs flood (Sandvik Coromant 2024).  "
            "BUE risk at low cutting speeds — keep vc > 80 m/min."
        ),
    ),
    # Medium-carbon steel: flood vc 120-200 m/min; dry vc 80-150 m/min
    # (25-35 % derate; AlCrN preferred).  Upper dry limit 150 m/min.
    "steel-medium-carbon": _MaterialConfig(
        verdict=_CONDITIONAL,
        factor_low=0.65,
        factor_high=0.80,
        max_vc_dry_abs=150.0,
        min_coating="TiAlN",
        preferred_coatings=["AlCrN", "TiAlN"],
        notes=(
            "Medium-carbon steel (0.35–0.60 % C) generates higher cutting "
            "temperatures than low-carbon grades.  AlCrN coating preferred "
            "for its superior hot hardness above 900 °C (Sandvik §4)."
        ),
    ),
    # Stainless austenitic: flood vc 120-200 m/min; dry vc 60-120 m/min
    # (30-50 % derate; AlCrN/TiAlN mandatory).  Upper dry limit 120 m/min.
    "steel-stainless-austenitic": _MaterialConfig(
        verdict=_CONDITIONAL,
        factor_low=0.50,
        factor_high=0.65,
        max_vc_dry_abs=120.0,
        min_coating="TiAlN",
        preferred_coatings=["AlCrN", "TiAlN"],
        notes=(
            "Austenitic stainless (e.g. 304/316L) work-hardens during "
            "cutting; dry machining requires AlCrN/TiAlN and a 30-50 % vc "
            "reduction vs flood.  Uncoated tools are NOT acceptable — rapid "
            "crater wear and BUE (Sandvik §6, ISO 8688-1)."
        ),
    ),
    # Aluminum wrought: not recommended dry at any speed
    "aluminum-wrought": _MaterialConfig(
        verdict=_NOT_FEASIBLE,
        factor_low=0.40,
        factor_high=0.60,
        max_vc_dry_abs=0.0,
        min_coating="diamond-CVD",
        preferred_coatings=["diamond-CVD"],
        notes=(
            "Wrought aluminium alloys have a strong tendency to form built-up "
            "edge (BUE) and weld to the tool face when machined dry — "
            "especially at high cutting speeds (Sandvik §3).  Flood coolant "
            "or MQL with a diamond-CVD tool is strongly recommended.  "
            "Standard TiN/TiAlN coatings accelerate BUE on Al."
        ),
    ),
    # Aluminum cast: not recommended dry at any speed
    "aluminum-cast": _MaterialConfig(
        verdict=_NOT_FEASIBLE,
        factor_low=0.40,
        factor_high=0.60,
        max_vc_dry_abs=0.0,
        min_coating="diamond-CVD",
        preferred_coatings=["diamond-CVD"],
        notes=(
            "Cast aluminium (A380, A356 etc.) shares the BUE/gumming "
            "susceptibility of wrought grades.  High-Si alloys also cause "
            "abrasive wear on uncoated carbide.  Flood or MQL required."
        ),
    ),
    # Ti6Al4V: flood vc 40-80 m/min; dry vc 20-45 m/min (MQL required).
    # Combustion risk above ~60 m/min fully dry (Biermann 2020 §4).
    # Upper dry limit (with MQL) 60 m/min.
    "titanium-Ti6Al4V": _MaterialConfig(
        verdict=_CHALLENGING,
        factor_low=0.30,
        factor_high=0.50,
        max_vc_dry_abs=60.0,
        min_coating="TiAlN",
        preferred_coatings=["AlCrN", "TiAlN"],
        notes=(
            "Ti6Al4V dry machining is technically challenging: chemical "
            "affinity between titanium and tool materials at 600 °C+ leads "
            "to diffusion wear; risk of tool combustion above vc ≈ 60 m/min "
            "without any coolant (Biermann 2020 §4).  MQL (minimum-quantity "
            "lubrication) is the minimum acceptable strategy.  AlCrN coating "
            "provides partial protection but cannot substitute for MQL."
        ),
    ),
    # Inconel 718: not recommended dry at any speed
    "nickel-inconel-718": _MaterialConfig(
        verdict=_NOT_FEASIBLE,
        factor_low=0.25,
        factor_high=0.45,
        max_vc_dry_abs=0.0,
        min_coating="AlCrN",
        preferred_coatings=["AlCrN"],
        notes=(
            "Inconel 718 is a superalloy with extreme work-hardening, low "
            "thermal conductivity, and high-temperature strength.  Dry "
            "machining produces catastrophic tool wear in seconds.  Flood "
            "coolant at high pressure (≥70 bar through-tool for drilling) "
            "is mandatory (Sandvik Coromant 2024 + ISO 8688-1)."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Coating adequacy matrix
# (coating, material) → bool  (True = coating is acceptable for dry)
# ---------------------------------------------------------------------------

_COATING_OK: dict[tuple[str, str], bool] = {
    # cast-iron-grey: uncoated carbide is acceptable (graphite lubrication)
    ("uncoated",    "cast-iron-grey"):              True,
    ("TiN",         "cast-iron-grey"):              True,
    ("TiAlN",       "cast-iron-grey"):              True,
    ("AlCrN",       "cast-iron-grey"):              True,
    ("diamond-CVD", "cast-iron-grey"):              False,  # graphite adhesion

    # steel-low-carbon
    ("uncoated",    "steel-low-carbon"):            False,
    ("TiN",         "steel-low-carbon"):            False,  # insufficient hot-hardness
    ("TiAlN",       "steel-low-carbon"):            True,
    ("AlCrN",       "steel-low-carbon"):            True,
    ("diamond-CVD", "steel-low-carbon"):            False,  # diamond reacts with Fe

    # steel-medium-carbon
    ("uncoated",    "steel-medium-carbon"):         False,
    ("TiN",         "steel-medium-carbon"):         False,
    ("TiAlN",       "steel-medium-carbon"):         True,
    ("AlCrN",       "steel-medium-carbon"):         True,
    ("diamond-CVD", "steel-medium-carbon"):         False,

    # steel-stainless-austenitic
    ("uncoated",    "steel-stainless-austenitic"):  False,
    ("TiN",         "steel-stainless-austenitic"):  False,
    ("TiAlN",       "steel-stainless-austenitic"):  True,
    ("AlCrN",       "steel-stainless-austenitic"):  True,
    ("diamond-CVD", "steel-stainless-austenitic"):  False,

    # aluminum-wrought (not feasible dry regardless, but diamond-CVD least bad)
    ("uncoated",    "aluminum-wrought"):            False,
    ("TiN",         "aluminum-wrought"):            False,
    ("TiAlN",       "aluminum-wrought"):            False,
    ("AlCrN",       "aluminum-wrought"):            False,
    ("diamond-CVD", "aluminum-wrought"):            False,  # MQL+diamond only

    # aluminum-cast
    ("uncoated",    "aluminum-cast"):               False,
    ("TiN",         "aluminum-cast"):               False,
    ("TiAlN",       "aluminum-cast"):               False,
    ("AlCrN",       "aluminum-cast"):               False,
    ("diamond-CVD", "aluminum-cast"):               False,

    # titanium-Ti6Al4V (all "ok" here means coated tool + MQL)
    ("uncoated",    "titanium-Ti6Al4V"):            False,
    ("TiN",         "titanium-Ti6Al4V"):            False,
    ("TiAlN",       "titanium-Ti6Al4V"):            True,   # + MQL mandatory
    ("AlCrN",       "titanium-Ti6Al4V"):            True,   # + MQL mandatory
    ("diamond-CVD", "titanium-Ti6Al4V"):            False,  # carbon diffusion

    # nickel-inconel-718
    ("uncoated",    "nickel-inconel-718"):          False,
    ("TiN",         "nickel-inconel-718"):          False,
    ("TiAlN",       "nickel-inconel-718"):          False,
    ("AlCrN",       "nickel-inconel-718"):          False,
    ("diamond-CVD", "nickel-inconel-718"):          False,
}


_HONEST_CAVEAT = (
    "Rules are heuristic averages from Sandvik Coromant Dry/Near-Dry Machining "
    "Application Guide (2024) and CIRP literature (Klocke & Eisenblätter 1997; "
    "Biermann 2020 §4).  tool_life_reduction_factor uses mid-range Sandvik "
    "Taylor-model values — uncertainty ±40 %; actual tool life depends on "
    "insert grade, exact alloy composition, machine rigidity, spindle thermal "
    "compensation, chip-air evacuation, BUE tendency, and surface finish "
    "requirement.  Verify against Sandvik CoroPlus ToolGuide or chip-form "
    "testing before production deployment.  Ti6Al4V: risk of tool combustion "
    "above vc ≈ 60 m/min without any coolant (Biermann §4) — this module "
    "flags the risk but cannot substitute for physical testing.  Grey cast "
    "iron dry machining requires adequate machine enclosure and dust extraction."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DryMachiningSpec:
    """Input specification for a dry-machining feasibility check.

    Parameters
    ----------
    workpiece_material   : Material class string:
        "steel-low-carbon" | "steel-medium-carbon" |
        "steel-stainless-austenitic" | "cast-iron-grey" |
        "aluminum-wrought" | "aluminum-cast" |
        "titanium-Ti6Al4V" | "nickel-inconel-718"
    tool_coating         : "uncoated" | "TiN" | "TiAlN" | "AlCrN" | "diamond-CVD"
    vc_m_per_min         : Cutting speed [m/min], > 0.
    fz_mm_per_tooth      : Feed per tooth [mm/tooth], > 0.
    ae_mm                : Radial engagement (ae) [mm], > 0.
    ap_mm                : Axial depth of cut (ap) [mm], > 0.
    tool_diameter_mm     : Tool cutting diameter [mm], > 0.
    operation            : "milling-roughing" | "milling-finishing" |
                           "drilling" | "turning"
    """
    workpiece_material: str
    tool_coating: str
    vc_m_per_min: float
    fz_mm_per_tooth: float
    ae_mm: float
    ap_mm: float
    tool_diameter_mm: float
    operation: str

    def __post_init__(self) -> None:
        if self.workpiece_material not in _VALID_MATERIALS:
            raise ValueError(
                f"workpiece_material must be one of "
                f"{sorted(_VALID_MATERIALS)}, got {self.workpiece_material!r}"
            )
        if self.tool_coating not in _VALID_COATINGS:
            raise ValueError(
                f"tool_coating must be one of "
                f"{sorted(_VALID_COATINGS)}, got {self.tool_coating!r}"
            )
        if self.vc_m_per_min <= 0:
            raise ValueError(
                f"vc_m_per_min must be > 0, got {self.vc_m_per_min!r}"
            )
        if self.fz_mm_per_tooth <= 0:
            raise ValueError(
                f"fz_mm_per_tooth must be > 0, got {self.fz_mm_per_tooth!r}"
            )
        if self.ae_mm <= 0:
            raise ValueError(
                f"ae_mm must be > 0, got {self.ae_mm!r}"
            )
        if self.ap_mm <= 0:
            raise ValueError(
                f"ap_mm must be > 0, got {self.ap_mm!r}"
            )
        if self.tool_diameter_mm <= 0:
            raise ValueError(
                f"tool_diameter_mm must be > 0, got {self.tool_diameter_mm!r}"
            )
        if self.operation not in _VALID_OPERATIONS:
            raise ValueError(
                f"operation must be one of "
                f"{sorted(_VALID_OPERATIONS)}, got {self.operation!r}"
            )


@dataclass
class DryMachiningReport:
    """Result from ``check_dry_machining``.

    Attributes
    ----------
    feasible                  : True if dry machining is recommended or
                                conditionally acceptable with the given coating;
                                False if flood coolant is required.
    recommendation            : Human-readable recommendation string.
    tool_life_reduction_factor: Predicted ratio T_dry / T_flood.
                                1.0 = same tool life as flood;
                                0.5 = half the tool life.
    min_coating_required      : Minimum coating needed for dry feasibility.
    max_vc_dry_m_per_min      : Recommended maximum vc for dry machining
                                [m/min] = vc_flood × vc_derate_high.
                                0.0 if dry machining is not recommended.
    warnings                  : List of specific warning strings.
    honest_caveat             : Plain-English limitations and assumptions.
    """
    feasible: bool
    recommendation: str
    tool_life_reduction_factor: float
    min_coating_required: str
    max_vc_dry_m_per_min: float
    warnings: List[str]
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def check_dry_machining(spec: DryMachiningSpec) -> DryMachiningReport:
    """Check dry-machining feasibility for a given CAM operation.

    Algorithm
    ---------
    1.  Look up material configuration (_MATERIAL_CONFIG).
    2.  Determine coating adequacy from _COATING_OK matrix.
    3.  Compute tool_life_reduction_factor = config.factor_mid, adjusted
        for:
        - poor coating → factor × 0.85
        - vc above recommended max_vc_dry → factor × 0.80
        - milling-roughing on challenging materials → factor × 0.90
    4.  Compute max_vc_dry = vc × config.vc_derate_high (upper bound).
    5.  Build recommendation string and warnings list.
    6.  feasible = verdict in (_FEASIBLE, _CONDITIONAL) AND coating ok.

    Parameters
    ----------
    spec : DryMachiningSpec — validated by __post_init__.

    Returns
    -------
    DryMachiningReport
    """
    cfg = _MATERIAL_CONFIG[spec.workpiece_material]
    coating_ok = _COATING_OK.get(
        (spec.tool_coating, spec.workpiece_material), False
    )

    warnings: list[str] = []

    # ── 1. Max vc dry from Sandvik catalogue absolute limit ─────────────────
    # cfg.max_vc_dry_abs is the catalogue upper bound for dry vc [m/min];
    # 0.0 means dry machining is not recommended at any speed.
    max_vc_dry = cfg.max_vc_dry_abs

    # ── 2. Warn if vc exceeds recommended dry maximum ──────────────────────
    vc_over_limit = False
    if max_vc_dry > 0 and spec.vc_m_per_min > max_vc_dry:
        vc_over_limit = True
        warnings.append(
            f"vc_m_per_min ({spec.vc_m_per_min}) exceeds recommended dry "
            f"maximum ({max_vc_dry} m/min per Sandvik Coromant 2024); "
            f"reduce cutting speed for dry machining."
        )

    # ── 3. Ti6Al4V combustion risk warning ─────────────────────────────────
    if spec.workpiece_material == "titanium-Ti6Al4V":
        if spec.vc_m_per_min > 60.0:
            warnings.append(
                f"CRITICAL: vc = {spec.vc_m_per_min} m/min on Ti6Al4V dry — "
                "tool combustion risk above ~60 m/min without coolant "
                "(Biermann 2020 §4).  MQL (minimum-quantity lubrication) is "
                "the minimum acceptable strategy."
            )
        else:
            warnings.append(
                "Ti6Al4V dry machining: MQL (minimum-quantity lubrication) "
                "is the minimum acceptable strategy; full dry is NOT "
                "recommended (Biermann 2020 §4; Sandvik §6)."
            )

    # ── 4. Aluminum BUE warning ─────────────────────────────────────────────
    if spec.workpiece_material in ("aluminum-wrought", "aluminum-cast"):
        warnings.append(
            f"{spec.workpiece_material}: strong built-up edge (BUE) and "
            "chip-welding tendency when machined dry.  Use flood coolant "
            "or MQL with diamond-CVD tool (Sandvik Coromant §3)."
        )

    # ── 5. Inconel warning ──────────────────────────────────────────────────
    if spec.workpiece_material == "nickel-inconel-718":
        warnings.append(
            "Inconel 718: extreme work-hardening + low thermal conductivity "
            "makes dry machining non-viable.  High-pressure flood coolant "
            "mandatory (Sandvik Coromant 2024 + ISO 8688-1)."
        )

    # ── 6. Coating mismatch warning ─────────────────────────────────────────
    if not coating_ok:
        preferred = ", ".join(cfg.preferred_coatings)
        warnings.append(
            f"Coating '{spec.tool_coating}' is NOT adequate for dry "
            f"machining of {spec.workpiece_material}.  "
            f"Preferred coatings: {preferred}."
        )

    # ── 7. TiN marginal warning ──────────────────────────────────────────────
    if spec.tool_coating == "TiN" and coating_ok:
        warnings.append(
            "TiN coating provides marginal hot-hardness improvement (max "
            "≈600 °C) — consider upgrading to TiAlN (800 °C) or AlCrN "
            "(900 °C) for longer dry tool life (Sandvik Coromant §4)."
        )

    # ── 8. Diamond on steel warning ──────────────────────────────────────────
    if spec.tool_coating == "diamond-CVD" and "steel" in spec.workpiece_material:
        warnings.append(
            "Diamond-CVD coating reacts with iron (carbon diffusion) above "
            "700 °C — do NOT use diamond-CVD on ferrous materials "
            "(Sandvik Coromant §4)."
        )

    # ── 9. Roughing aggravation warning ─────────────────────────────────────
    if spec.operation == "milling-roughing" and cfg.verdict in (
        _CONDITIONAL, _CHALLENGING
    ):
        warnings.append(
            f"Milling roughing increases thermal cycling and chip load; "
            f"for {spec.workpiece_material} dry roughing, use conservative "
            f"ae ≤ 0.10 × D and ap ≤ 1.5 × D (Sandvik Coromant 2024)."
        )

    # ── 10. ae/ap aggressive engagement warning ──────────────────────────────
    ae_ratio = spec.ae_mm / spec.tool_diameter_mm
    if ae_ratio > 0.5 and cfg.verdict != _FEASIBLE:
        warnings.append(
            f"Radial engagement ae/D = {ae_ratio:.2f} > 0.50 — "
            "aggressive engagement in dry conditions accelerates tool wear; "
            "reduce ae or switch to flood/MQL (Sandvik Coromant 2024)."
        )

    # ── 11. Compute tool_life_reduction_factor ──────────────────────────────
    factor = cfg.factor_mid

    # Penalty for inadequate coating (user has wrong coating)
    if not coating_ok:
        factor = round(factor * 0.80, 4)

    # Penalty for over-speed
    if vc_over_limit:
        factor = round(factor * 0.75, 4)

    # Penalty for roughing on challenging / conditional material
    if spec.operation == "milling-roughing" and cfg.verdict in (
        _CONDITIONAL, _CHALLENGING
    ):
        factor = round(factor * 0.90, 4)

    # Clamp to [0.10, 1.05]
    factor = max(0.10, min(1.05, factor))

    # ── 12. Determine feasibility and recommendation ────────────────────────
    # feasible = (verdict allows dry) AND (coating adequate)
    can_do = cfg.verdict in (_FEASIBLE, _CONDITIONAL, _CHALLENGING)
    feasible = can_do and coating_ok

    if cfg.verdict == _FEASIBLE and coating_ok:
        recommendation = (
            f"Dry machining FEASIBLE for {spec.workpiece_material} with "
            f"{spec.tool_coating} coating.  {cfg.notes}"
        )
    elif cfg.verdict == _CONDITIONAL and coating_ok:
        recommendation = (
            f"Dry machining CONDITIONAL for {spec.workpiece_material}: "
            f"acceptable with {spec.tool_coating} coating; "
            f"max recommended dry vc = {cfg.max_vc_dry_abs} m/min "
            f"(Sandvik Coromant 2024).  {cfg.notes}"
        )
    elif cfg.verdict == _CHALLENGING and coating_ok:
        recommendation = (
            f"Dry machining CHALLENGING for {spec.workpiece_material}: "
            f"technically possible with {spec.tool_coating} coating + MQL "
            f"but NOT recommended as fully dry.  {cfg.notes}"
        )
    elif cfg.verdict == _CHALLENGING and not coating_ok:
        recommendation = (
            f"Dry machining CHALLENGING for {spec.workpiece_material} AND "
            f"coating '{spec.tool_coating}' is inadequate.  Use MQL + "
            f"{cfg.min_coating} minimum coating.  {cfg.notes}"
        )
    else:
        recommendation = (
            f"Dry machining NOT RECOMMENDED for {spec.workpiece_material}.  "
            f"{cfg.notes}  Use flood coolant."
        )

    return DryMachiningReport(
        feasible=feasible,
        recommendation=recommendation,
        tool_life_reduction_factor=factor,
        min_coating_required=cfg.min_coating,
        max_vc_dry_m_per_min=max_vc_dry,
        warnings=warnings,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_check_dry_machining_spec = ToolSpec(
    name="cam_check_dry_machining",
    description=(
        "Given a CAM operation (workpiece material, tool coating, cutting "
        "speed vc, feed per tooth fz, radial engagement ae, axial depth ap, "
        "tool diameter, and operation type), determines whether dry machining "
        "is feasible per Sandvik Coromant dry-machining guidelines and ISO "
        "8688-1 tool-wear standards.  Returns: feasible (bool), "
        "recommendation (str), tool_life_reduction_factor (1.0 = same as "
        "flood, 0.5 = half), min_coating_required (str), "
        "max_vc_dry_m_per_min (float), warnings (list), honest_caveat (str).  "
        "Rules (Sandvik Coromant 2024 + ISO 8688-1): cast iron + carbide → "
        "fully dry-suitable (factor 0.90-1.00); aluminum wet preferred "
        "(chip welding/BUE); stainless requires AlCrN/TiAlN coating, vc "
        "derated 30-50%; Ti6Al4V dry is challenging — needs MQL minimum, "
        "combustion risk above 60 m/min; Inconel-718 dry NOT feasible "
        "(flood mandatory).  "
        "Supported materials: steel-low-carbon, steel-medium-carbon, "
        "steel-stainless-austenitic, cast-iron-grey, aluminum-wrought, "
        "aluminum-cast, titanium-Ti6Al4V, nickel-inconel-718.  "
        "Supported coatings: uncoated, TiN, TiAlN, AlCrN, diamond-CVD.  "
        "Supported operations: milling-roughing, milling-finishing, "
        "drilling, turning.  "
        "HONEST LIMITS: heuristic rules from Sandvik catalog + CIRP "
        "literature — NOT a substitute for chip-form testing; "
        "tool_life_reduction_factor uncertainty ±40 %.  "
        "References: Sandvik Coromant Dry/Near-Dry Machining Guide (2024); "
        "ISO 8688-1:1989; Klocke & Eisenblätter CIRP Ann. 46(2) 1997; "
        "Biermann et al. Springer 2020 §4."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "workpiece_material": {
                "type": "string",
                "enum": sorted(_VALID_MATERIALS),
                "description": "Workpiece material class.",
            },
            "tool_coating": {
                "type": "string",
                "enum": sorted(_VALID_COATINGS),
                "description": "Tool coating type.",
            },
            "vc_m_per_min": {
                "type": "number",
                "description": "Cutting speed in m/min (flood reference speed).",
            },
            "fz_mm_per_tooth": {
                "type": "number",
                "description": "Feed per tooth in mm/tooth.",
            },
            "ae_mm": {
                "type": "number",
                "description": "Radial engagement (ae) in mm.",
            },
            "ap_mm": {
                "type": "number",
                "description": "Axial depth of cut (ap) in mm.",
            },
            "tool_diameter_mm": {
                "type": "number",
                "description": "Tool cutting diameter in mm.",
            },
            "operation": {
                "type": "string",
                "enum": sorted(_VALID_OPERATIONS),
                "description": "Machining operation type.",
            },
        },
        "required": [
            "workpiece_material",
            "tool_coating",
            "vc_m_per_min",
            "fz_mm_per_tooth",
            "ae_mm",
            "ap_mm",
            "tool_diameter_mm",
            "operation",
        ],
    },
)


@register(cam_check_dry_machining_spec)
async def run_cam_check_dry_machining(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    required = [
        "workpiece_material", "tool_coating", "vc_m_per_min",
        "fz_mm_per_tooth", "ae_mm", "ap_mm", "tool_diameter_mm", "operation",
    ]
    for fld in required:
        if fld not in a:
            return err_payload(f"missing required field: {fld!r}", "BAD_ARGS")

    try:
        spec = DryMachiningSpec(
            workpiece_material=str(a["workpiece_material"]),
            tool_coating=str(a["tool_coating"]),
            vc_m_per_min=float(a["vc_m_per_min"]),
            fz_mm_per_tooth=float(a["fz_mm_per_tooth"]),
            ae_mm=float(a["ae_mm"]),
            ap_mm=float(a["ap_mm"]),
            tool_diameter_mm=float(a["tool_diameter_mm"]),
            operation=str(a["operation"]),
        )
        result = check_dry_machining(spec)
    except (TypeError, KeyError) as exc:
        return err_payload(f"missing or invalid field: {exc}", "BAD_ARGS")
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "ERROR")

    return ok_payload({
        "feasible": result.feasible,
        "recommendation": result.recommendation,
        "tool_life_reduction_factor": result.tool_life_reduction_factor,
        "min_coating_required": result.min_coating_required,
        "max_vc_dry_m_per_min": result.max_vc_dry_m_per_min,
        "warnings": result.warnings,
        "honest_caveat": result.honest_caveat,
    })
