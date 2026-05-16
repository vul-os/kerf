"""
kerf_cad_core.quoting.fab_quote — one-click fabrication quote engine.

Given a part's geometry summary (bounding-box, volume, surface area, feature
inventory) this module:

1. ``analyze_part(geometry_summary)``
       Parses the raw dict into a ``PartGeometry`` dataclass.

2. ``viable_processes(part)``
       Applies manufacturing heuristics and returns a list of dicts:
           {process, viability_score, blockers, advantages}
       Processes considered: CNC, casting, injection, sheet_metal, 3d_print, forging.

3. ``cost_per_process(part, processes, quantity)``
       Calls into kerf_cad_core.costing.estimate for each viable process,
       returns a list of per-process cost dicts sorted by unit_total_cost ascending.

4. ``recommend(quotes)``
       Picks best process: lowest cost that meets tolerance class, otherwise
       best score on cost + quality + lead-time tradeoff.

5. ``quote_report(part, quotes, recommendation)``
       Returns a formatted multi-line string suitable for chat output.

All functions are pure Python and never raise.  Errors/edge cases are
communicated via the "ok" field or embedded warnings.

Units
-----
    lengths / dimensions  — mm
    volume                — cm³
    area                  — cm²
    mass                  — kg
    cost                  — USD (caller's currency, treated as opaque scalar)

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# PartGeometry dataclass
# ---------------------------------------------------------------------------

@dataclass
class PartGeometry:
    """Parsed geometry summary for a mechanical part.

    All fields have safe defaults so callers can omit unknown properties
    without breaking downstream logic.

    Parameters
    ----------
    bbox_x, bbox_y, bbox_z : float
        Bounding-box dimensions (mm).  All > 0.
    volume_cm3 : float
        Solid volume (cm³).  > 0.
    surface_area_cm2 : float
        Total surface area (cm²).  > 0.
    mass_kg : float
        Estimated mass (kg).  > 0.
    num_holes : int
        Total hole count (any diameter).
    num_threads : int
        Threaded feature count.
    num_undercuts : int
        Undercut feature count (relevant to injection moulding & casting).
    thin_wall_count : int
        Number of thin-wall regions (wall thickness < 2 mm).
    min_wall_mm : float
        Thinnest wall thickness (mm).  0 if none.
    draft_angle_deg : float
        Minimum draft angle present on the part (degrees).  0 if none.
    is_flat_blank : bool
        True if the part can be produced entirely from a flat blank (sheet-
        metal compatible).
    num_bends : int
        Number of bend features (sheet-metal).
    complexity_score : float
        Normalised complexity score in [0, 1].  0 = trivial, 1 = very complex.
    requires_high_strength : bool
        True if the application demands high-strength (forging indicator).
    is_symmetric : bool
        True if the part is rotationally or mirror symmetric.
    tolerance_class : str
        One of "coarse", "medium", "fine", "precision".
    finish_quality : str
        One of "rough", "standard", "fine", "optical".
    material_cost_per_kg : float
        Raw material cost per kg (USD).
    """

    bbox_x: float = 100.0
    bbox_y: float = 100.0
    bbox_z: float = 100.0
    volume_cm3: float = 100.0
    surface_area_cm2: float = 200.0
    mass_kg: float = 0.5
    num_holes: int = 0
    num_threads: int = 0
    num_undercuts: int = 0
    thin_wall_count: int = 0
    min_wall_mm: float = 3.0
    draft_angle_deg: float = 0.0
    is_flat_blank: bool = False
    num_bends: int = 0
    complexity_score: float = 0.3
    requires_high_strength: bool = False
    is_symmetric: bool = False
    tolerance_class: str = "medium"
    finish_quality: str = "standard"
    material_cost_per_kg: float = 5.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_float(val: Any, default: float) -> float:
    try:
        v = float(val)
        if math.isfinite(v):
            return v
    except (TypeError, ValueError):
        pass
    return default


def _safe_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_bool(val: Any, default: bool) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return default


def _safe_str(val: Any, allowed: list[str], default: str) -> str:
    if isinstance(val, str) and val in allowed:
        return val
    return default


_TOLERANCE_CLASSES = ["coarse", "medium", "fine", "precision"]
_FINISH_CLASSES = ["rough", "standard", "fine", "optical"]


# ---------------------------------------------------------------------------
# 1. analyze_part
# ---------------------------------------------------------------------------

def analyze_part(geometry_summary: dict) -> PartGeometry:
    """Parse a raw geometry-summary dict into a ``PartGeometry``.

    Unknown or invalid fields are silently replaced with safe defaults.
    Never raises.

    Parameters
    ----------
    geometry_summary : dict
        Keys map directly to ``PartGeometry`` field names.  Any extra keys
        are ignored.

    Returns
    -------
    PartGeometry
    """
    if not isinstance(geometry_summary, dict):
        geometry_summary = {}

    g = geometry_summary

    bbox_x = _safe_float(g.get("bbox_x"), 100.0)
    bbox_y = _safe_float(g.get("bbox_y"), 100.0)
    bbox_z = _safe_float(g.get("bbox_z"), 100.0)

    # Ensure positive bbox
    bbox_x = max(bbox_x, 0.01)
    bbox_y = max(bbox_y, 0.01)
    bbox_z = max(bbox_z, 0.01)

    volume_cm3 = max(_safe_float(g.get("volume_cm3"), 100.0), 0.001)
    surface_area_cm2 = max(_safe_float(g.get("surface_area_cm2"), 200.0), 0.001)
    mass_kg = max(_safe_float(g.get("mass_kg"), 0.5), 1e-6)

    return PartGeometry(
        bbox_x=bbox_x,
        bbox_y=bbox_y,
        bbox_z=bbox_z,
        volume_cm3=volume_cm3,
        surface_area_cm2=surface_area_cm2,
        mass_kg=mass_kg,
        num_holes=max(_safe_int(g.get("num_holes"), 0), 0),
        num_threads=max(_safe_int(g.get("num_threads"), 0), 0),
        num_undercuts=max(_safe_int(g.get("num_undercuts"), 0), 0),
        thin_wall_count=max(_safe_int(g.get("thin_wall_count"), 0), 0),
        min_wall_mm=max(_safe_float(g.get("min_wall_mm"), 3.0), 0.0),
        draft_angle_deg=max(_safe_float(g.get("draft_angle_deg"), 0.0), 0.0),
        is_flat_blank=_safe_bool(g.get("is_flat_blank"), False),
        num_bends=max(_safe_int(g.get("num_bends"), 0), 0),
        complexity_score=_clamp(_safe_float(g.get("complexity_score"), 0.3), 0.0, 1.0),
        requires_high_strength=_safe_bool(g.get("requires_high_strength"), False),
        is_symmetric=_safe_bool(g.get("is_symmetric"), False),
        tolerance_class=_safe_str(g.get("tolerance_class"), _TOLERANCE_CLASSES, "medium"),
        finish_quality=_safe_str(g.get("finish_quality"), _FINISH_CLASSES, "standard"),
        material_cost_per_kg=max(_safe_float(g.get("material_cost_per_kg"), 5.0), 0.0),
    )


# ---------------------------------------------------------------------------
# 2. viable_processes
# ---------------------------------------------------------------------------

# Process viability heuristic thresholds
_MIN_WALL_CASTING_MM = 2.5       # sand / investment casting minimum wall
_MIN_WALL_INJECTION_MM = 0.8     # injection moulding minimum wall
_MIN_WALL_SHEET_MM = 0.5         # sheet metal minimum thickness
_MIN_DRAFT_CASTING_DEG = 0.5     # minimum draft for casting
_MIN_DRAFT_INJECTION_DEG = 1.0   # minimum draft for injection
_MIN_QTY_INJECTION = 1000        # injection tooling only viable at high qty
_MAX_COMPLEXITY_FORGING = 0.4    # forging restricted to simple parts

_PROCESS_NAMES = ["CNC", "casting", "injection", "sheet_metal", "3d_print", "forging"]


def viable_processes(part: PartGeometry, quantity: int = 1) -> list[dict]:
    """Classify which manufacturing processes are viable for this part.

    Returns a list of dicts (one per process), each containing:
        process         str   — process name
        viability_score float — 0..1 (higher = more viable)
        blockers        list  — reasons that make the process impractical
        advantages      list  — reasons favouring this process

    Never raises.  All processes are always returned; blockers drive low scores.

    Parameters
    ----------
    part : PartGeometry
    quantity : int
        Production quantity (affects injection / casting economics).
    """
    results = []
    qty = max(int(quantity), 1)

    # ── CNC ──────────────────────────────────────────────────────────────────
    cnc_blockers: list[str] = []
    cnc_advantages: list[str] = ["viable for any geometry", "tight tolerances achievable"]
    cnc_score = 0.75

    if part.complexity_score > 0.7:
        cnc_score -= 0.15
        cnc_blockers.append("high complexity increases CNC cycle time significantly")
    if part.num_undercuts > 2:
        cnc_score -= 0.10
        cnc_blockers.append(f"{part.num_undercuts} undercuts require multi-axis or special tooling")
    if part.volume_cm3 < 1.0 and part.complexity_score > 0.5:
        cnc_score -= 0.15
        cnc_blockers.append("very small complex features may require EDM or micro-machining")
    if qty > 5000:
        cnc_score -= 0.20
        cnc_blockers.append("high quantity: CNC unit cost uncompetitive vs. moulding/casting")
    if part.tolerance_class in ("fine", "precision"):
        cnc_advantages.append("preferred process for fine/precision tolerances")
        cnc_score = min(cnc_score + 0.10, 1.0)
    if part.num_threads > 0:
        cnc_advantages.append("threads easily produced by CNC tapping/milling")
    cnc_score = _clamp(cnc_score, 0.0, 1.0)

    results.append({
        "process": "CNC",
        "viability_score": round(cnc_score, 3),
        "blockers": cnc_blockers,
        "advantages": cnc_advantages,
    })

    # ── Casting ───────────────────────────────────────────────────────────────
    cast_blockers: list[str] = []
    cast_advantages: list[str] = ["good for complex external geometry", "low per-unit cost at scale"]
    cast_score = 0.65

    if part.min_wall_mm < _MIN_WALL_CASTING_MM and part.min_wall_mm > 0:
        cast_blockers.append(
            f"min wall {part.min_wall_mm:.1f} mm < {_MIN_WALL_CASTING_MM} mm required for casting"
        )
        cast_score -= 0.25
    if part.draft_angle_deg < _MIN_DRAFT_CASTING_DEG and part.draft_angle_deg == 0.0:
        cast_blockers.append("no draft angle — add ≥ 0.5° draft for casting")
        cast_score -= 0.15
    if part.num_threads > 2:
        cast_blockers.append("threads must be machined post-cast")
        cast_score -= 0.05
    if part.tolerance_class in ("fine", "precision"):
        cast_blockers.append("cast surfaces require machining to meet fine tolerances")
        cast_score -= 0.10
    if part.num_undercuts > 1:
        cast_blockers.append(f"{part.num_undercuts} undercuts require cores or splits")
        cast_score -= 0.10
    if qty >= 100:
        cast_advantages.append("tooling amortised over moderate/high quantities")
        cast_score = min(cast_score + 0.10, 1.0)
    if part.mass_kg > 0.5:
        cast_advantages.append("casting efficient for medium-to-large mass parts")
    cast_score = _clamp(cast_score, 0.0, 1.0)

    results.append({
        "process": "casting",
        "viability_score": round(cast_score, 3),
        "blockers": cast_blockers,
        "advantages": cast_advantages,
    })

    # ── Injection moulding ────────────────────────────────────────────────────
    inj_blockers: list[str] = []
    inj_advantages: list[str] = ["very low unit cost at high volume", "repeatable finish"]
    inj_score = 0.50

    if qty < _MIN_QTY_INJECTION:
        inj_blockers.append(
            f"quantity {qty} < {_MIN_QTY_INJECTION} needed to amortise mould tooling"
        )
        inj_score -= 0.40
    if part.num_undercuts > 0:
        inj_blockers.append(
            f"{part.num_undercuts} undercut(s) require side-actions or collapsible cores"
        )
        inj_score -= 0.20
    if part.draft_angle_deg < _MIN_DRAFT_INJECTION_DEG and part.draft_angle_deg == 0.0:
        inj_blockers.append("no draft angle — injection moulding requires ≥ 1° draft on all surfaces")
        inj_score -= 0.20
    if part.min_wall_mm < _MIN_WALL_INJECTION_MM and part.min_wall_mm > 0:
        inj_blockers.append(
            f"min wall {part.min_wall_mm:.1f} mm < {_MIN_WALL_INJECTION_MM} mm for injection"
        )
        inj_score -= 0.15
    if part.tolerance_class in ("fine", "precision"):
        inj_blockers.append("injection moulding tolerances limited to ~±0.1 mm (medium class)")
        inj_score -= 0.10
    if qty >= _MIN_QTY_INJECTION:
        inj_advantages.append(f"quantity {qty} supports tooling amortisation")
        inj_score = min(inj_score + 0.20, 1.0)
    if part.num_undercuts == 0 and part.draft_angle_deg >= _MIN_DRAFT_INJECTION_DEG:
        inj_advantages.append("clean draft and no undercuts: excellent mouldability")
    inj_score = _clamp(inj_score, 0.0, 1.0)

    results.append({
        "process": "injection",
        "viability_score": round(inj_score, 3),
        "blockers": inj_blockers,
        "advantages": inj_advantages,
    })

    # ── Sheet metal ───────────────────────────────────────────────────────────
    sm_blockers: list[str] = []
    sm_advantages: list[str] = ["fast turnaround", "low material waste", "excellent strength/weight"]
    sm_score = 0.30

    if part.is_flat_blank:
        sm_score += 0.50
        sm_advantages.append("part is a flat blank — ideal sheet-metal candidate")
    else:
        sm_blockers.append("part is not a flat blank; sheet metal requires flat-blank geometry")
        sm_score -= 0.20

    if part.num_bends > 0:
        sm_score = min(sm_score + 0.10, 1.0)
        sm_advantages.append(f"{part.num_bends} bend(s) straightforward on press brake")

    if part.volume_cm3 > 500 and not part.is_flat_blank:
        sm_blockers.append("large 3D volume not compatible with sheet-metal forming alone")
        sm_score -= 0.15

    if part.num_undercuts > 0:
        sm_blockers.append("undercuts incompatible with sheet-metal forming")
        sm_score -= 0.20

    if part.tolerance_class in ("fine", "precision"):
        sm_blockers.append("sheet-metal tolerances typically ±0.1–0.3 mm; precision needs secondary ops")
        sm_score -= 0.10

    sm_score = _clamp(sm_score, 0.0, 1.0)

    results.append({
        "process": "sheet_metal",
        "viability_score": round(sm_score, 3),
        "blockers": sm_blockers,
        "advantages": sm_advantages,
    })

    # ── 3D printing ───────────────────────────────────────────────────────────
    print_blockers: list[str] = []
    print_advantages: list[str] = [
        "no tooling cost",
        "handles any complexity",
        "fastest for prototypes and low volumes",
    ]
    print_score = 0.70  # always viable; cost may be high for large qty

    if qty > 500:
        print_blockers.append(
            f"quantity {qty} → 3D printing unit cost exceeds injection/casting at scale"
        )
        print_score -= 0.25
    if part.volume_cm3 > 1000:
        print_blockers.append("large volume (> 1000 cm³) → high material + machine time cost")
        print_score -= 0.15
    if part.tolerance_class in ("fine", "precision"):
        print_blockers.append("SLS/DMLS can achieve fine tolerance but adds cost")
        print_score -= 0.10
    if part.finish_quality in ("fine", "optical"):
        print_blockers.append("3D-printed surface finish requires post-processing for fine/optical quality")
        print_score -= 0.10
    if qty <= 10:
        print_advantages.append("very low quantities: no tooling break-even concern")
    if part.complexity_score > 0.6:
        print_advantages.append("complex geometry printed directly — no DFM redesign needed")
    if part.num_undercuts > 0:
        print_advantages.append("undercuts printed without additional setup")

    print_score = _clamp(print_score, 0.0, 1.0)

    results.append({
        "process": "3d_print",
        "viability_score": round(print_score, 3),
        "blockers": print_blockers,
        "advantages": print_advantages,
    })

    # ── Forging ───────────────────────────────────────────────────────────────
    forge_blockers: list[str] = []
    forge_advantages: list[str] = ["highest strength-to-weight ratio", "excellent fatigue life"]
    forge_score = 0.30

    if part.requires_high_strength:
        forge_score += 0.35
        forge_advantages.append("high-strength requirement is primary forging indicator")
    else:
        forge_blockers.append("application does not specify high-strength requirement")
        forge_score -= 0.10

    if part.is_symmetric:
        forge_score = min(forge_score + 0.15, 1.0)
        forge_advantages.append("symmetric geometry well-suited to closed-die forging")
    else:
        forge_blockers.append("asymmetric geometry complicates die design")
        forge_score -= 0.10

    if part.complexity_score > _MAX_COMPLEXITY_FORGING:
        forge_blockers.append(
            f"complexity score {part.complexity_score:.2f} > {_MAX_COMPLEXITY_FORGING} — "
            "forging limited to simple-to-moderate geometry"
        )
        forge_score -= 0.20

    if part.num_undercuts > 0:
        forge_blockers.append("undercuts are not producible by forging")
        forge_score -= 0.30

    if qty < 500:
        forge_blockers.append("forging dies expensive; qty < 500 rarely economic")
        forge_score -= 0.20

    if qty >= 1000:
        forge_advantages.append("die cost amortised over high volume")
        forge_score = min(forge_score + 0.10, 1.0)

    forge_score = _clamp(forge_score, 0.0, 1.0)

    results.append({
        "process": "forging",
        "viability_score": round(forge_score, 3),
        "blockers": forge_blockers,
        "advantages": forge_advantages,
    })

    # Sort descending by viability score
    results.sort(key=lambda x: x["viability_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# 3. cost_per_process
# ---------------------------------------------------------------------------

# Default costing parameters — conservative mid-market rates
_DEFAULT_MACHINE_RATE_CNC = 95.0        # $/hr
_DEFAULT_MACHINE_RATE_CASTING = 80.0    # $/hr
_DEFAULT_MACHINE_RATE_INJECTION = 120.0 # $/hr
_DEFAULT_PRESS_RATE_SM = 60.0           # $/hr
_DEFAULT_LASER_RATE_SM = 80.0           # $/hr
_DEFAULT_MACHINE_RATE_PRINT = 20.0      # $/hr (FDM)
_DEFAULT_MATERIAL_COST_PER_CM3_PRINT = 0.05  # $/cm³ PLA/PETG
_MATERIAL_DENSITY_STEEL_KG_M3 = 7850.0
_DEFAULT_FORGING_MATERIAL_UPLIFT = 1.20  # forging stock costs ~20% more than cast
_DEFAULT_MOULD_COST = 15000.0            # injection mould tooling (USD)
_DEFAULT_MOULD_LIFE_SHOTS = 100_000


def _estimate_cnc_cost(part: PartGeometry, qty: int) -> dict:
    """Parametric CNC cost from part geometry."""
    from kerf_cad_core.costing.estimate import cnc_cost

    mat_cost = part.mass_kg * part.material_cost_per_kg

    # Cycle time heuristic: base proportional to volume + complexity
    # ~0.5 hr per 100 cm³ of material removed, scaled by complexity
    cycle_hr = max(0.1, (part.volume_cm3 / 100.0) * (0.5 + part.complexity_score))

    # Setup per batch: 0.5 hr base + 5 min per undercut/thread
    setup_hr = 0.5 + 0.08 * (part.num_undercuts + part.num_threads)

    # Tooling: $200 base + $50/thread + $30/hole
    tooling = 200.0 + 50.0 * part.num_threads + 30.0 * part.num_holes

    return cnc_cost(
        material_cost=mat_cost,
        cycle_time_hr=cycle_hr,
        machine_rate_per_hr=_DEFAULT_MACHINE_RATE_CNC,
        setup_time_hr=setup_hr,
        batch_size=qty,
        tooling_cost=tooling,
        tooling_life_parts=max(1, qty * 5),
        overhead_rate=0.15,
    )


def _estimate_casting_cost(part: PartGeometry, qty: int) -> dict:
    """Parametric sand/investment casting cost."""
    from kerf_cad_core.costing.estimate import casting_cost

    mat_per_kg = part.material_cost_per_kg
    # Pattern/tooling: ~$500 for small parts, scaling with mass
    pattern = max(500.0, 500.0 * math.sqrt(part.mass_kg))

    return casting_cost(
        material_cost_per_kg=mat_per_kg,
        part_mass_kg=part.mass_kg,
        yield_fraction=0.70,
        pattern_cost=pattern,
        pattern_life_parts=500,
        finishing_cost_per_part=5.0 + 2.0 * part.complexity_score * 10.0,
        machine_rate_per_hr=_DEFAULT_MACHINE_RATE_CASTING,
        pour_time_hr=max(0.02, part.mass_kg * 0.05),
        batch_size=qty,
        overhead_rate=0.20,
    )


def _estimate_injection_cost(part: PartGeometry, qty: int) -> dict:
    """Parametric injection moulding cost."""
    from kerf_cad_core.costing.estimate import injection_cost

    mat_per_kg = max(part.material_cost_per_kg, 2.0)  # polymers typically ≥ $2/kg
    shot_mass_kg = part.mass_kg * 1.08  # 8% runner allowance

    return injection_cost(
        material_cost_per_kg=mat_per_kg,
        shot_mass_kg=shot_mass_kg,
        scrap_rate=0.03,
        cycle_time_hr=max(0.002, part.volume_cm3 / 1000.0 * 0.02),
        machine_rate_per_hr=_DEFAULT_MACHINE_RATE_INJECTION,
        mould_cost=_DEFAULT_MOULD_COST,
        mould_life_shots=_DEFAULT_MOULD_LIFE_SHOTS,
        cavities=1,
        batch_size=qty,
        overhead_rate=0.15,
    )


def _estimate_sheet_metal_cost(part: PartGeometry, qty: int) -> dict:
    """Parametric sheet-metal cost."""
    from kerf_cad_core.costing.estimate import sheet_metal_cost

    # Blank area from bbox assuming the part unfolds from one principal plane
    blank_area_m2 = max(
        (part.bbox_x * part.bbox_y) / 1_000_000.0,
        0.0001,
    )
    thickness_m = max(part.min_wall_mm / 1000.0, 0.001)
    perimeter_m = 2.0 * (part.bbox_x + part.bbox_y) / 1000.0

    return sheet_metal_cost(
        blank_area_m2=blank_area_m2,
        material_cost_per_kg=part.material_cost_per_kg,
        material_density_kg_m3=_MATERIAL_DENSITY_STEEL_KG_M3,
        sheet_thickness_m=thickness_m,
        num_bends=max(part.num_bends, 0),
        bend_time_hr=0.02,
        press_rate_per_hr=_DEFAULT_PRESS_RATE_SM,
        laser_cut_rate_per_hr=_DEFAULT_LASER_RATE_SM,
        cut_perimeter_m=perimeter_m,
        cut_speed_m_per_hr=10.0,
        setup_cost=50.0,
        batch_size=qty,
        overhead_rate=0.15,
    )


def _estimate_printing_cost(part: PartGeometry, qty: int) -> dict:
    """Parametric FDM/SLA printing cost."""
    from kerf_cad_core.costing.estimate import printing_cost

    build_time_hr = max(0.5, part.volume_cm3 / 20.0)  # ~50 cm³/hr effective rate
    mat_cost_cm3 = max(_DEFAULT_MATERIAL_COST_PER_CM3_PRINT, part.material_cost_per_kg / 1000.0)

    return printing_cost(
        material_volume_cm3=part.volume_cm3,
        material_cost_per_cm3=mat_cost_cm3,
        build_time_hr=build_time_hr,
        machine_rate_per_hr=_DEFAULT_MACHINE_RATE_PRINT,
        support_volume_fraction=min(0.30, part.complexity_score * 0.30),
        post_processing_cost=2.0 + part.complexity_score * 5.0,
        batch_size=qty,
        machine_utilisation=0.80,
        overhead_rate=0.15,
    )


def _estimate_forging_cost(part: PartGeometry, qty: int) -> dict:
    """Parametric forging cost (uses cnc_cost as a proxy with forging parameters)."""
    from kerf_cad_core.costing.estimate import casting_cost

    # Forging modelled as casting with: higher material cost (billet stock),
    # lower yield fraction (flash), higher machine rate, no finishing
    mat_per_kg = part.material_cost_per_kg * _DEFAULT_FORGING_MATERIAL_UPLIFT
    die_cost = max(2000.0, 2000.0 * math.sqrt(part.mass_kg))

    return casting_cost(
        material_cost_per_kg=mat_per_kg,
        part_mass_kg=part.mass_kg,
        yield_fraction=0.85,        # forging yield better than casting
        pattern_cost=die_cost,
        pattern_life_parts=20000,   # forging dies last longer than patterns
        finishing_cost_per_part=8.0,
        machine_rate_per_hr=150.0,  # forging press rate
        pour_time_hr=max(0.01, part.mass_kg * 0.02),
        batch_size=qty,
        overhead_rate=0.20,
    )


def cost_per_process(
    part: PartGeometry,
    processes: list[dict],
    quantity: int = 1,
) -> list[dict]:
    """Compute unit cost for each process in *processes*.

    Only processes with ``viability_score > 0`` are costed; others are
    included with a sentinel cost entry.

    Parameters
    ----------
    part : PartGeometry
    processes : list[dict]
        Output of ``viable_processes()``.
    quantity : int
        Production quantity.

    Returns
    -------
    list[dict]
        Sorted ascending by ``unit_total_cost``.  Each entry:
            process         str
            viability_score float
            blockers        list
            advantages      list
            cost            dict  — costing result (ok, unit_total_cost, …)
            unit_total_cost float — convenience scalar (inf if costing failed)
    """
    qty = max(int(quantity), 1)
    estimators = {
        "CNC": _estimate_cnc_cost,
        "casting": _estimate_casting_cost,
        "injection": _estimate_injection_cost,
        "sheet_metal": _estimate_sheet_metal_cost,
        "3d_print": _estimate_printing_cost,
        "forging": _estimate_forging_cost,
    }

    results = []
    for proc in processes:
        pname = proc.get("process", "")
        entry = dict(proc)

        estimator = estimators.get(pname)
        if estimator is None:
            entry["cost"] = {"ok": False, "reason": f"no estimator for process '{pname}'"}
            entry["unit_total_cost"] = float("inf")
        else:
            try:
                cost = estimator(part, qty)
            except Exception as exc:  # pragma: no cover
                cost = {"ok": False, "reason": str(exc)}
            entry["cost"] = cost
            if cost.get("ok"):
                entry["unit_total_cost"] = float(cost.get("unit_total_cost", float("inf")))
            else:
                entry["unit_total_cost"] = float("inf")

        results.append(entry)

    results.sort(key=lambda x: x["unit_total_cost"])
    return results


# ---------------------------------------------------------------------------
# 4. recommend
# ---------------------------------------------------------------------------

# Minimum viability score to be considered for recommendation
_MIN_VIABILITY_FOR_RECOMMENDATION = 0.25

# Tolerance-class compatibility matrix: which processes can meet which class
_TOLERANCE_PROCESS_COMPAT: dict[str, set[str]] = {
    "coarse":    {"CNC", "casting", "injection", "sheet_metal", "3d_print", "forging"},
    "medium":    {"CNC", "casting", "injection", "sheet_metal", "3d_print", "forging"},
    "fine":      {"CNC", "casting", "sheet_metal"},
    "precision": {"CNC"},
}


def recommend(quotes: list[dict]) -> dict:
    """Pick the best manufacturing process from the costed quote list.

    Selection criteria (in priority order):
    1. Process must meet the tolerance class (derived from blockers).
    2. Among tolerance-compatible processes with viability_score >= threshold,
       prefer lowest unit_total_cost.
    3. If no tolerance-compatible process exists, fall back to lowest cost.

    Parameters
    ----------
    quotes : list[dict]
        Output of ``cost_per_process()``.

    Returns
    -------
    dict
        ok            bool
        process       str   — recommended process name
        unit_cost     float
        reason        str   — human-readable rationale
        runner_up     str | None
        warnings      list
    """
    if not quotes:
        return {
            "ok": False,
            "reason": "no quotes provided",
            "process": None,
            "unit_cost": None,
            "runner_up": None,
            "warnings": [],
        }

    warnings: list[str] = []

    # Filter to those with finite cost
    finite = [q for q in quotes if q.get("unit_total_cost", float("inf")) < float("inf")]
    if not finite:
        return {
            "ok": False,
            "reason": "all process cost estimates failed",
            "process": None,
            "unit_cost": None,
            "runner_up": None,
            "warnings": warnings,
        }

    # Determine tolerance class from first quote (all quotes share same part)
    # We infer it from the "injection" entry's blockers (if present)
    tol_class = "medium"  # default; will be overridden if inferable
    for q in quotes:
        blockers = q.get("blockers", [])
        for b in blockers:
            if "precision" in b.lower():
                tol_class = "precision"
                break
            if "fine tolerance" in b.lower() or "fine tolerances" in b.lower():
                tol_class = "fine"
                break

    compatible_procs = _TOLERANCE_PROCESS_COMPAT.get(tol_class, set(_TOLERANCE_PROCESS_COMPAT["medium"]))

    # Candidates: viable + tolerance-compatible + finite cost
    viable_threshold = _MIN_VIABILITY_FOR_RECOMMENDATION
    candidates = [
        q for q in finite
        if q.get("process") in compatible_procs
        and q.get("viability_score", 0.0) >= viable_threshold
    ]

    if not candidates:
        # Fallback: use any finite-cost process
        candidates = finite
        warnings.append(
            "no process passed both viability and tolerance filters; "
            "falling back to lowest-cost option"
        )

    # Sort by cost, pick lowest
    candidates.sort(key=lambda x: x["unit_total_cost"])
    best = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None

    reason_parts = [
        f"{best['process']} selected as lowest-cost viable option "
        f"(unit cost ${best['unit_total_cost']:.2f})"
    ]
    if best.get("viability_score", 0) >= 0.7:
        reason_parts.append(f"viability score {best['viability_score']:.2f} (high).")
    else:
        reason_parts.append(f"viability score {best['viability_score']:.2f}.")
    if best.get("advantages"):
        reason_parts.append("Advantages: " + "; ".join(best["advantages"][:2]) + ".")

    return {
        "ok": True,
        "process": best["process"],
        "unit_cost": best["unit_total_cost"],
        "reason": " ".join(reason_parts),
        "runner_up": runner_up["process"] if runner_up else None,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 5. quote_report
# ---------------------------------------------------------------------------

def quote_report(
    part: PartGeometry,
    quotes: list[dict],
    recommendation: dict,
) -> str:
    """Format a fab-quote summary as a multi-line string for chat output.

    Parameters
    ----------
    part : PartGeometry
    quotes : list[dict]
        Output of ``cost_per_process()``.
    recommendation : dict
        Output of ``recommend()``.

    Returns
    -------
    str
        Formatted report.  Never raises.
    """
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("FAB QUOTE REPORT")
    lines.append("=" * 60)

    # Part summary
    lines.append("")
    lines.append("PART GEOMETRY SUMMARY")
    lines.append(f"  Bounding box      : {part.bbox_x:.1f} x {part.bbox_y:.1f} x {part.bbox_z:.1f} mm")
    lines.append(f"  Volume            : {part.volume_cm3:.2f} cm³")
    lines.append(f"  Mass              : {part.mass_kg:.3f} kg")
    lines.append(f"  Holes / Threads   : {part.num_holes} / {part.num_threads}")
    lines.append(f"  Undercuts         : {part.num_undercuts}")
    lines.append(f"  Min wall          : {part.min_wall_mm:.2f} mm")
    lines.append(f"  Draft angle       : {part.draft_angle_deg:.1f}°")
    lines.append(f"  Complexity score  : {part.complexity_score:.2f}")
    lines.append(f"  Tolerance class   : {part.tolerance_class}")
    lines.append(f"  Finish quality    : {part.finish_quality}")
    lines.append(f"  Flat blank        : {'yes' if part.is_flat_blank else 'no'}")

    # Process cost table
    lines.append("")
    lines.append("PROCESS COST TABLE  (sorted by unit cost)")
    lines.append(f"  {'Process':<14}  {'Viability':>9}  {'Unit cost':>10}  Status")
    lines.append(f"  {'-'*14}  {'-'*9}  {'-'*10}  {'-'*20}")

    for q in quotes:
        pname = q.get("process", "?")
        vis = q.get("viability_score", 0.0)
        utc = q.get("unit_total_cost", float("inf"))
        if utc < float("inf"):
            cost_str = f"${utc:>9.2f}"
        else:
            cost_str = "    N/A   "
        ok_flag = q.get("cost", {}).get("ok", False)
        status = "ok" if ok_flag else q.get("cost", {}).get("reason", "failed")[:20]
        lines.append(f"  {pname:<14}  {vis:>9.3f}  {cost_str}  {status}")

    # Blockers summary
    lines.append("")
    lines.append("KEY BLOCKERS")
    has_blockers = False
    for q in quotes:
        blockers = q.get("blockers", [])
        if blockers:
            has_blockers = True
            lines.append(f"  [{q['process']}]")
            for b in blockers[:3]:
                lines.append(f"    - {b}")
    if not has_blockers:
        lines.append("  None — all processes fully viable.")

    # Recommendation
    lines.append("")
    lines.append("RECOMMENDATION")
    if recommendation.get("ok"):
        lines.append(f"  Process   : {recommendation['process']}")
        lines.append(f"  Unit cost : ${recommendation['unit_cost']:.2f}")
        if recommendation.get("runner_up"):
            lines.append(f"  Runner-up : {recommendation['runner_up']}")
        lines.append(f"  Reason    : {recommendation['reason']}")
    else:
        lines.append(f"  Could not determine recommendation: {recommendation.get('reason', 'unknown')}")

    if recommendation.get("warnings"):
        lines.append("")
        lines.append("WARNINGS")
        for w in recommendation["warnings"]:
            lines.append(f"  ! {w}")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM tool wrappers  (@register pattern)
# ---------------------------------------------------------------------------

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _fab_quote_spec = ToolSpec(
        name="fab_quote",
        description=(
            "One-click fabrication quote: given a part geometry summary, "
            "classify viable manufacturing processes (CNC, casting, injection, "
            "sheet metal, 3D printing, forging), estimate cost per process "
            "from the costing module, and return a ranked recommendation "
            "with a formatted chat report.\n"
            "\n"
            "geometry_summary fields (all optional, safe defaults used if omitted):\n"
            "  bbox_x/y/z (mm), volume_cm3, surface_area_cm2, mass_kg,\n"
            "  num_holes, num_threads, num_undercuts, thin_wall_count,\n"
            "  min_wall_mm, draft_angle_deg, is_flat_blank, num_bends,\n"
            "  complexity_score [0–1], requires_high_strength (bool),\n"
            "  is_symmetric (bool), tolerance_class (coarse/medium/fine/precision),\n"
            "  finish_quality (rough/standard/fine/optical),\n"
            "  material_cost_per_kg.\n"
            "\n"
            "Returns: ok, part_summary, viable_processes, cost_table, "
            "recommendation, report_text.\n"
            "\n"
            "Errors: {ok:false, reason}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "geometry_summary": {
                    "type": "object",
                    "description": "Part geometry / feature inventory dict.",
                },
                "quantity": {
                    "type": "integer",
                    "description": "Production quantity (default 1). >= 1.",
                },
            },
            "required": ["geometry_summary"],
        },
    )

    @register(_fab_quote_spec, write=False)
    async def run_fab_quote(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        geo = a.get("geometry_summary")
        if geo is None:
            return json.dumps({"ok": False, "reason": "geometry_summary is required"})
        if not isinstance(geo, dict):
            return err_payload("geometry_summary must be a JSON object", "BAD_ARGS")

        qty = max(int(a.get("quantity", 1)), 1)

        part = analyze_part(geo)
        vp = viable_processes(part, quantity=qty)
        quotes = cost_per_process(part, vp, quantity=qty)
        rec = recommend(quotes)
        report = quote_report(part, quotes, rec)

        result = {
            "ok": True,
            "warnings": rec.get("warnings", []),
            "part_summary": {
                "bbox_mm": [part.bbox_x, part.bbox_y, part.bbox_z],
                "volume_cm3": part.volume_cm3,
                "mass_kg": part.mass_kg,
                "tolerance_class": part.tolerance_class,
                "complexity_score": part.complexity_score,
            },
            "viable_processes": vp,
            "cost_table": [
                {
                    "process": q["process"],
                    "viability_score": q["viability_score"],
                    "unit_total_cost": q["unit_total_cost"] if q["unit_total_cost"] < 1e30 else None,
                }
                for q in quotes
            ],
            "recommendation": rec,
            "report_text": report,
        }
        return ok_payload(result)
