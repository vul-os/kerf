# Author: imranparuk
"""
Flex and rigid-flex stackup manager.

Provides four LLM tools for modelling flex / rigid-flex PCB stackups and
validating bend regions against published IPC-2223 guidance.

Reference
---------
IPC-2223C *Sectional Design Standard for Flexible Printed Boards* (2013),
Sections 4.6 (static flex) and 4.7 (dynamic flex).

The minimum bend radius rules implemented here are standard published guidance
from IPC-2223:

  static  single-sided: r_min ≥ 6  × t
  static  double-sided: r_min ≥ 12 × t
  dynamic (any):        r_min ≥ 100 × t

where t is the total flex-zone laminate thickness at the bend, and r is the
inner bend radius.

Outer-fibre strain
------------------
Strain at the outer fibre is estimated by the standard beam-bending formula:

  ε = t / (2 × r)   (dimensionless; multiply by 100 for %)

Source: IPC-2223C §4.6; also derivable from elementary beam theory (see
Timoshenko, *Strength of Materials*, 2nd ed., §40).

Recommended strain limits applied here:
  static  : ε ≤ 0.003 (0.3 %)   — IPC-2223 guidance for static flex
  dynamic : ε ≤ 0.001 (0.1 %)   — conservative limit for dynamic cycling

Tools (registered via @register)
---------------------------------
flex_stackup_define  — build a stackup from a layer list
flex_bend_check      — IPC-2223 pass/fail for a bend region
flex_neutral_axis    — neutral-axis offset + outer-fibre strain
flex_fab_summary     — fabrication notes summary

Units
-----
All length/thickness inputs and outputs are in mm.
"""

from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

# ── IPC-2223 bend radius multipliers ─────────────────────────────────────────
# Source: IPC-2223C (2013) §4.6 and §4.7
_STATIC_SINGLE_MULTIPLIER = 6
_STATIC_DOUBLE_MULTIPLIER = 12
_DYNAMIC_MULTIPLIER = 100

# Outer-fibre strain limits (dimensionless)
_STRAIN_LIMIT_STATIC = 0.003   # 0.3 % — IPC-2223C §4.6
_STRAIN_LIMIT_DYNAMIC = 0.001  # 0.1 % — conservative for dynamic cycling

# Valid layer types and flex types
_VALID_LAYER_TYPES = {"copper", "PI", "adhesive", "coverlay", "stiffener"}
_VALID_FLEX_TYPES = {"single_sided", "double_sided", "dynamic"}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_layers(raw_layers: list) -> tuple[bool, str, list]:
    """Validate and normalise a raw layer list from JSON args.

    Returns (ok, error_msg, normalised_layers).
    Each normalised layer is a dict with keys:
      name, type, thickness_mm, er, zone
    """
    if not isinstance(raw_layers, list) or len(raw_layers) == 0:
        return False, "layers must be a non-empty list", []

    normalised = []
    for i, la in enumerate(raw_layers):
        if not isinstance(la, dict):
            return False, f"layers[{i}] must be an object", []
        ltype = la.get("type", "")
        if ltype not in _VALID_LAYER_TYPES:
            return (
                False,
                f"layers[{i}].type '{ltype}' is not valid; "
                f"choose from {sorted(_VALID_LAYER_TYPES)}",
                [],
            )
        t = la.get("thickness_mm")
        if not isinstance(t, (int, float)) or t <= 0:
            return False, f"layers[{i}].thickness_mm must be a positive number", []
        zone = la.get("zone", "flex")
        if zone not in ("flex", "rigid"):
            return False, f"layers[{i}].zone must be 'flex' or 'rigid'", []
        normalised.append(
            {
                "name": str(la.get("name", f"layer_{i}")),
                "type": ltype,
                "thickness_mm": float(t),
                "er": la.get("er"),
                "zone": zone,
            }
        )
    return True, "", normalised


def _copper_count(layers: list) -> int:
    return sum(1 for la in layers if la["type"] == "copper")


def _copper_count_zone(layers: list, zone: str) -> int:
    return sum(1 for la in layers if la["type"] == "copper" and la["zone"] == zone)


def _thickness_zone(layers: list, zone: str) -> float:
    return sum(la["thickness_mm"] for la in layers if la["zone"] == zone)


def _has_coverlay(layers: list, zone: str = "flex") -> bool:
    return any(la["type"] == "coverlay" and la["zone"] == zone for la in layers)


def _has_stiffener(layers: list) -> bool:
    return any(la["type"] == "stiffener" for la in layers)


def _bend_multiplier(flex_type: str, flex_copper_count: int) -> int:
    """Return IPC-2223 minimum bend radius multiplier.

    For static bends the multiplier depends on whether copper is present on
    one face (single-sided, 6×) or both faces (double-sided, 12×).
    Dynamic bends always require 100× regardless of construction.

    Reference: IPC-2223C (2013) §4.6 (static) / §4.7 (dynamic).
    """
    if flex_type == "dynamic":
        return _DYNAMIC_MULTIPLIER
    if flex_type == "double_sided" or flex_copper_count >= 2:
        return _STATIC_DOUBLE_MULTIPLIER
    return _STATIC_SINGLE_MULTIPLIER


def _strain_limit(flex_type: str) -> float:
    return _STRAIN_LIMIT_DYNAMIC if flex_type == "dynamic" else _STRAIN_LIMIT_STATIC


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 1: flex_stackup_define
# ═══════════════════════════════════════════════════════════════════════════════

_flex_stackup_define_spec = ToolSpec(
    name="flex_stackup_define",
    description=(
        "Build a flex / rigid-flex PCB stackup from an ordered layer list.  "
        "Returns total thickness, flex-section thickness, copper count, zone "
        "summary, and a validity check.  Layers must specify 'type' "
        "(copper | PI | adhesive | coverlay | stiffener), 'thickness_mm', "
        "and optionally 'name', 'er', 'zone' (flex | rigid, default: flex).  "
        "All dimensions in mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "layers": {
                "type": "array",
                "description": (
                    "Ordered list of layer objects from top to bottom.  "
                    "Each object: {name?, type, thickness_mm, er?, zone?}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["copper", "PI", "adhesive", "coverlay", "stiffener"],
                        },
                        "thickness_mm": {"type": "number"},
                        "er": {"type": "number"},
                        "zone": {"type": "string", "enum": ["flex", "rigid"]},
                    },
                    "required": ["type", "thickness_mm"],
                },
                "minItems": 1,
            },
            "stackup_name": {
                "type": "string",
                "description": "Optional descriptive name for the stackup.",
            },
        },
        "required": ["layers"],
    },
)


@register(_flex_stackup_define_spec, write=False)
async def flex_stackup_define(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    raw_layers = a.get("layers")
    ok, msg, layers = _parse_layers(raw_layers)
    if not ok:
        return err_payload(msg, "BAD_ARGS")

    total_cu = _copper_count(layers)
    if total_cu == 0:
        return err_payload(
            "stackup has no copper layers — at least one copper layer is required",
            "BAD_ARGS",
        )

    total_t = sum(la["thickness_mm"] for la in layers)
    flex_t = _thickness_zone(layers, "flex")
    rigid_t = _thickness_zone(layers, "rigid")
    flex_cu = _copper_count_zone(layers, "flex")
    rigid_cu = _copper_count_zone(layers, "rigid")

    zones: list[dict] = []
    current_zone = None
    current_layers: list[dict] = []
    for la in layers:
        if la["zone"] != current_zone:
            if current_zone is not None:
                zones.append(
                    {
                        "zone": current_zone,
                        "layer_count": len(current_layers),
                        "thickness_mm": round(
                            sum(cl["thickness_mm"] for cl in current_layers), 6
                        ),
                        "copper_count": sum(
                            1 for cl in current_layers if cl["type"] == "copper"
                        ),
                    }
                )
            current_zone = la["zone"]
            current_layers = [la]
        else:
            current_layers.append(la)
    if current_zone is not None:
        zones.append(
            {
                "zone": current_zone,
                "layer_count": len(current_layers),
                "thickness_mm": round(
                    sum(cl["thickness_mm"] for cl in current_layers), 6
                ),
                "copper_count": sum(
                    1 for cl in current_layers if cl["type"] == "copper"
                ),
            }
        )

    is_rigid_flex = rigid_t > 0 and flex_t > 0

    return ok_payload(
        {
            "ok": True,
            "stackup_name": str(a.get("stackup_name") or ""),
            "layers": layers,
            "total_thickness_mm": round(total_t, 6),
            "flex_thickness_mm": round(flex_t, 6),
            "rigid_thickness_mm": round(rigid_t, 6),
            "copper_count": total_cu,
            "flex_copper_count": flex_cu,
            "rigid_copper_count": rigid_cu,
            "is_rigid_flex": is_rigid_flex,
            "zones": zones,
            "layer_count": len(layers),
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 2: flex_bend_check
# ═══════════════════════════════════════════════════════════════════════════════

_flex_bend_check_spec = ToolSpec(
    name="flex_bend_check",
    description=(
        "Check whether a proposed bend region meets IPC-2223C (2013) minimum "
        "bend radius requirements.  Accepts the flex-zone total thickness t, "
        "the inner bend radius r, and the flex type "
        "(single_sided | double_sided | dynamic).  "
        "Returns pass/fail and the recommended minimum radius.  "
        "Rules (IPC-2223C §4.6 / §4.7): "
        "static single-sided r ≥ 6t; "
        "static double-sided r ≥ 12t; "
        "dynamic r ≥ 100t.  "
        "Units mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "inner_radius_mm": {
                "type": "number",
                "description": "Proposed inner bend radius r in mm.",
            },
            "flex_thickness_mm": {
                "type": "number",
                "description": (
                    "Total flex-zone laminate thickness t in mm.  "
                    "Use flex_thickness_mm from flex_stackup_define."
                ),
            },
            "flex_type": {
                "type": "string",
                "enum": ["single_sided", "double_sided", "dynamic"],
                "description": (
                    "single_sided = copper on one face (6t rule); "
                    "double_sided = copper on both faces (12t rule); "
                    "dynamic = cyclically flexed (100t rule)."
                ),
            },
            "flex_copper_count": {
                "type": "integer",
                "description": (
                    "Number of copper layers in the flex zone.  "
                    "If provided and ≥ 2, the double-sided multiplier applies "
                    "even when flex_type is 'single_sided'.  Optional."
                ),
            },
        },
        "required": ["inner_radius_mm", "flex_thickness_mm", "flex_type"],
    },
)


@register(_flex_bend_check_spec, write=False)
async def flex_bend_check(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    r = a.get("inner_radius_mm")
    t = a.get("flex_thickness_mm")
    flex_type = (a.get("flex_type") or "").strip()
    flex_cu = a.get("flex_copper_count")

    if not isinstance(r, (int, float)) or r <= 0:
        return err_payload("inner_radius_mm must be a positive number", "BAD_ARGS")
    if not isinstance(t, (int, float)) or t <= 0:
        return err_payload("flex_thickness_mm must be a positive number", "BAD_ARGS")
    if flex_type not in _VALID_FLEX_TYPES:
        return err_payload(
            f"flex_type must be one of {sorted(_VALID_FLEX_TYPES)}", "BAD_ARGS"
        )

    r = float(r)
    t = float(t)

    cu_count = int(flex_cu) if isinstance(flex_cu, (int, float)) else 1
    multiplier = _bend_multiplier(flex_type, cu_count)
    r_min = multiplier * t

    passed = r >= r_min
    margin_mm = r - r_min

    return ok_payload(
        {
            "ok": True,
            "passed": passed,
            "inner_radius_mm": r,
            "flex_thickness_mm": t,
            "flex_type": flex_type,
            "multiplier": multiplier,
            "recommended_min_radius_mm": round(r_min, 6),
            "margin_mm": round(margin_mm, 6),
            "message": (
                f"PASS: inner radius {r:.4f} mm ≥ {multiplier}t = {r_min:.4f} mm "
                f"(IPC-2223C {flex_type})"
                if passed
                else f"FAIL: inner radius {r:.4f} mm < {multiplier}t = {r_min:.4f} mm "
                f"— increase to ≥ {r_min:.4f} mm (IPC-2223C {flex_type})"
            ),
            "reference": "IPC-2223C (2013) §4.6 (static) / §4.7 (dynamic)",
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 3: flex_neutral_axis
# ═══════════════════════════════════════════════════════════════════════════════

_flex_neutral_axis_spec = ToolSpec(
    name="flex_neutral_axis",
    description=(
        "Calculate the neutral bend axis position and outer-fibre strain for a "
        "flex bend region.  For a uniform laminate the neutral axis lies at the "
        "mid-thickness (t/2 from inner surface).  Outer-fibre strain is "
        "ε = t / (2r) (IPC-2223C §4.6; elementary beam bending theory).  "
        "Warns if strain exceeds recommended limits: "
        "0.3 % for static flex, 0.1 % for dynamic.  "
        "Units mm; strain dimensionless (also expressed as %)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "inner_radius_mm": {
                "type": "number",
                "description": "Inner bend radius r in mm.",
            },
            "flex_thickness_mm": {
                "type": "number",
                "description": "Total flex-zone thickness t in mm.",
            },
            "flex_type": {
                "type": "string",
                "enum": ["single_sided", "double_sided", "dynamic"],
                "description": "Flex type (governs strain limit).",
            },
            "layers": {
                "type": "array",
                "description": (
                    "Optional ordered flex layer list (same format as "
                    "flex_stackup_define).  When provided, the weighted "
                    "neutral-axis offset from the inner surface is calculated "
                    "using layer thicknesses (uniform E assumed).  "
                    "When omitted, t/2 is used."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "thickness_mm": {"type": "number"},
                        "zone": {"type": "string"},
                    },
                    "required": ["type", "thickness_mm"],
                },
            },
        },
        "required": ["inner_radius_mm", "flex_thickness_mm", "flex_type"],
    },
)


def _neutral_axis_offset(layers: list | None, total_t: float) -> float:
    """Return neutral-axis offset from inner surface in mm.

    For a uniform laminate (or when no layer list is provided) this is t/2.
    When a layer list is provided the position of the area centroid is returned
    (assuming equal elastic modulus for all layers — a conservative estimate).
    """
    if not layers:
        return total_t / 2.0
    # Area-weighted centroid (uniform E)
    cumulative = 0.0
    moment = 0.0
    for la in layers:
        t_la = float(la.get("thickness_mm", 0))
        moment += (cumulative + t_la / 2.0) * t_la
        cumulative += t_la
    if cumulative <= 0:
        return total_t / 2.0
    return moment / cumulative


@register(_flex_neutral_axis_spec, write=False)
async def flex_neutral_axis(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    r = a.get("inner_radius_mm")
    t = a.get("flex_thickness_mm")
    flex_type = (a.get("flex_type") or "").strip()
    raw_layers = a.get("layers")

    if not isinstance(r, (int, float)) or r <= 0:
        return err_payload("inner_radius_mm must be a positive number", "BAD_ARGS")
    if not isinstance(t, (int, float)) or t <= 0:
        return err_payload("flex_thickness_mm must be a positive number", "BAD_ARGS")
    if flex_type not in _VALID_FLEX_TYPES:
        return err_payload(
            f"flex_type must be one of {sorted(_VALID_FLEX_TYPES)}", "BAD_ARGS"
        )

    r = float(r)
    t = float(t)

    # Neutral axis offset from inner surface
    if isinstance(raw_layers, list) and raw_layers:
        ok_l, msg_l, layers_norm = _parse_layers(raw_layers)
        flex_layers = (
            [la for la in layers_norm if la["zone"] == "flex"] if ok_l else []
        )
    else:
        flex_layers = []

    na_offset = _neutral_axis_offset(flex_layers or None, t)

    # Outer-fibre strain: ε = t / (2r)
    # Derivation: outer fibre is at radius (r + t); arc length ratio to neutral
    # axis at (r + na_offset): (r+t)/(r+na_offset) − 1 ≈ t/(2r) for small t/r.
    # Standard simplified form per IPC-2223C §4.6.
    strain = t / (2.0 * r)
    strain_pct = strain * 100.0

    limit = _strain_limit(flex_type)
    within_limit = strain <= limit

    warnings = []
    if not within_limit:
        warnings.append(
            f"Outer-fibre strain {strain_pct:.3f}% exceeds "
            f"{'dynamic' if flex_type == 'dynamic' else 'static'} limit "
            f"{limit * 100:.1f}% — increase inner radius."
        )

    return ok_payload(
        {
            "ok": True,
            "inner_radius_mm": r,
            "flex_thickness_mm": t,
            "flex_type": flex_type,
            "neutral_axis_offset_from_inner_mm": round(na_offset, 6),
            "outer_fibre_strain": round(strain, 8),
            "outer_fibre_strain_pct": round(strain_pct, 4),
            "strain_limit": limit,
            "strain_limit_pct": round(limit * 100, 3),
            "within_strain_limit": within_limit,
            "warnings": warnings,
            "formula": "ε = t / (2r)  [IPC-2223C §4.6; beam bending theory]",
            "reference": "IPC-2223C (2013) §4.6",
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 4: flex_fab_summary
# ═══════════════════════════════════════════════════════════════════════════════

_flex_fab_summary_spec = ToolSpec(
    name="flex_fab_summary",
    description=(
        "Generate a fabrication summary for a flex / rigid-flex design.  "
        "Accepts a stackup (same layer list as flex_stackup_define) and a list "
        "of bend region results (from flex_bend_check).  "
        "Returns fab notes covering: coverlay coverage status, stiffener "
        "placement recommendation, controlled-impedance feasibility, "
        "and an overall design-rule summary.  "
        "Units mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "layers": {
                "type": "array",
                "description": "Ordered layer list (same format as flex_stackup_define).",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "thickness_mm": {"type": "number"},
                        "er": {"type": "number"},
                        "zone": {"type": "string"},
                    },
                    "required": ["type", "thickness_mm"],
                },
                "minItems": 1,
            },
            "bend_results": {
                "type": "array",
                "description": (
                    "Optional list of bend check result objects (from "
                    "flex_bend_check).  Each should have 'passed', "
                    "'inner_radius_mm', 'flex_thickness_mm', 'flex_type'."
                ),
                "items": {"type": "object"},
            },
            "stackup_name": {
                "type": "string",
                "description": "Optional stackup name for the report header.",
            },
        },
        "required": ["layers"],
    },
)


@register(_flex_fab_summary_spec, write=False)
async def flex_fab_summary(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    raw_layers = a.get("layers")
    bend_results = a.get("bend_results") or []
    stackup_name = str(a.get("stackup_name") or "")

    ok_l, msg_l, layers = _parse_layers(raw_layers)
    if not ok_l:
        return err_payload(msg_l, "BAD_ARGS")

    total_cu = _copper_count(layers)
    if total_cu == 0:
        return err_payload(
            "stackup has no copper layers — at least one copper layer is required",
            "BAD_ARGS",
        )

    total_t = sum(la["thickness_mm"] for la in layers)
    flex_t = _thickness_zone(layers, "flex")
    rigid_t = _thickness_zone(layers, "rigid")
    flex_cu = _copper_count_zone(layers, "flex")
    is_rigid_flex = rigid_t > 0 and flex_t > 0

    notes: list[str] = []
    warnings: list[str] = []

    # ── Coverlay check ──────────────────────────────────────────────────────
    has_cov_flex = _has_coverlay(layers, zone="flex")
    has_cov_rigid = _has_coverlay(layers, zone="rigid")

    if flex_t > 0:
        if has_cov_flex:
            notes.append(
                "Coverlay present on flex zone — provides environmental protection "
                "and mechanical relief at conductor edges."
            )
        else:
            warnings.append(
                "No coverlay defined for flex zone.  IPC-2223 recommends coverlay "
                "on all flex copper layers to prevent cracking during bending."
            )

    if is_rigid_flex and not has_cov_rigid:
        notes.append(
            "Rigid zone has no coverlay layer — solder mask or LPI should be "
            "applied to rigid sections before final bond."
        )

    # ── Stiffener check ─────────────────────────────────────────────────────
    has_stiff = _has_stiffener(layers)
    if is_rigid_flex:
        if has_stiff:
            notes.append(
                "Stiffener layer present — ensure stiffener is applied only to "
                "rigid zones and terminates at least 0.5 mm from the flex bend area."
            )
        else:
            notes.append(
                "No stiffener layer defined.  For connectors or SMT pads in the "
                "flex zone, add an FR4 or stainless-steel stiffener in the rigid "
                "zones adjacent to the component footprints."
            )

    # ── Controlled-impedance feasibility ────────────────────────────────────
    # Impedance control is feasible when at least two copper layers are present
    # in the flex zone (for stripline reference) or when PI dielectric layers
    # with known εr are defined.
    pi_layers = [la for la in layers if la["type"] == "PI" and la["zone"] == "flex"]
    pi_with_er = [la for la in pi_layers if la.get("er") is not None]

    if flex_cu >= 2 and pi_layers:
        if pi_with_er:
            ci_flag = "feasible"
            notes.append(
                f"Controlled impedance: feasible.  {len(pi_with_er)} PI layer(s) "
                "have εr defined — use flex_neutral_axis / diffpair calc_impedance "
                "for trace width sizing."
            )
        else:
            ci_flag = "possible_no_er"
            warnings.append(
                "Controlled impedance may be possible but PI layers lack εr values.  "
                "Specify er for PI layers to enable impedance calculations."
            )
    elif flex_cu == 1:
        ci_flag = "limited"
        notes.append(
            "Single copper layer in flex zone — controlled impedance requires a "
            "reference plane; consider adding a second flex copper layer."
        )
    else:
        ci_flag = "not_feasible"
        notes.append("No PI dielectric layers in flex zone — impedance control not modelled.")

    # ── Bend summary ────────────────────────────────────────────────────────
    bend_summary: list[dict] = []
    all_bends_pass = True
    for br in bend_results:
        if not isinstance(br, dict):
            continue
        passed = bool(br.get("passed", False))
        if not passed:
            all_bends_pass = False
        bend_summary.append(
            {
                "passed": passed,
                "inner_radius_mm": br.get("inner_radius_mm"),
                "flex_type": br.get("flex_type"),
                "recommended_min_radius_mm": br.get("recommended_min_radius_mm"),
                "message": br.get("message", ""),
            }
        )
    if bend_results and not all_bends_pass:
        warnings.append(
            "One or more bend regions FAIL IPC-2223C minimum radius rules — "
            "review flex_bend_check results and increase inner radius."
        )
    elif bend_results and all_bends_pass:
        notes.append(
            f"All {len(bend_results)} bend region(s) PASS IPC-2223C minimum radius check."
        )

    # ── Layer stack summary ─────────────────────────────────────────────────
    layer_types_present = sorted({la["type"] for la in layers})

    return ok_payload(
        {
            "ok": True,
            "stackup_name": stackup_name,
            "is_rigid_flex": is_rigid_flex,
            "total_thickness_mm": round(total_t, 6),
            "flex_thickness_mm": round(flex_t, 6),
            "rigid_thickness_mm": round(rigid_t, 6),
            "copper_count": total_cu,
            "flex_copper_count": flex_cu,
            "controlled_impedance": ci_flag,
            "coverlay_flex": has_cov_flex,
            "coverlay_rigid": has_cov_rigid,
            "stiffener_present": has_stiff,
            "all_bends_pass": all_bends_pass,
            "bend_summary": bend_summary,
            "layer_types_present": layer_types_present,
            "notes": notes,
            "warnings": warnings,
            "reference": "IPC-2223C (2013); IPC-6013D",
        }
    )


# ── TOOLS registry list (consumed by plugin.py loader) ───────────────────────

TOOLS = [
    (
        "flex_stackup_define",
        _flex_stackup_define_spec,
        flex_stackup_define,
    ),
    (
        "flex_bend_check",
        _flex_bend_check_spec,
        flex_bend_check,
    ),
    (
        "flex_neutral_axis",
        _flex_neutral_axis_spec,
        flex_neutral_axis,
    ),
    (
        "flex_fab_summary",
        _flex_fab_summary_spec,
        flex_fab_summary,
    ),
]
