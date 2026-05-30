"""
kerf_cad_core.manufacturing_tooling_catalog — Manufacturing tooling catalog match engine.

Given a machining operation requirement (e.g. "mill a 0.5 mm slot in aluminium"),
look up matching tools from an embedded catalog covering Sandvik Coromant, Iscar,
Kennametal, OSG, and Tungaloy.

Public API
----------
    match_tooling(operation, material, dimension_mm) -> ToolingMatchResult

    manufacturing_match_tooling   — LLM tool (registered via @register)

HONEST FLAG
-----------
This is a small embedded catalog (~50 tools) for illustration and first-approximation
tooling selection. It is NOT a live manufacturer product database. Speeds/feeds are
representative mid-range starting points derived from:

    Sandvik Coromant "Cutting Data Recommendations" (2024 ed.)
    Drozda, T.J. & Wick, C. "Tool and Manufacturing Engineers Handbook" §3 (SME, 4th ed.)

For production use, verify against CoroPlus, Iscar ITA, Kennametal NOVO, or OSG e-Catalog.
Apply a ±20% tolerance to all speed/feed values as a starting point; machine, coolant,
and workholding conditions alter these materially.

Author: imranparuk

References
----------
Sandvik Coromant Cutting Data Recommendations (2024 ed.).
Drozda, T.J. & Wick, C. "Tool and Manufacturing Engineers Handbook" §3 (SME, 4th ed., 1983).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import List, Optional

from kerf_cad_core.tooling_catalog_data import (
    CATALOG,
    CatalogTool,
    FeedSpeedEntry,
    normalise_material,
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ToolingMatchResult:
    """Result from :func:`match_tooling`.

    Attributes
    ----------
    ok : bool
        True on success, False on error.
    tool_id : str
        Manufacturer catalog ID of the best-match tool (empty on error).
    manufacturer : str
        Manufacturer name.
    tool_type : str
        "end_mill", "drill", "tap", "reamer", or "insert".
    diameter_mm : float
        Nominal diameter of selected tool (mm).
    material : str
        Tool material (e.g. "coated_carbide").
    coating : Optional[str]
        Coating designation or None.
    description : str
        Human-readable tool description.
    recommended_speed_sfm : float
        Recommended cutting speed (SFM) for the given workpiece material.
    recommended_speed_m_min : float
        Same speed in m/min.
    recommended_feed_ipt : float
        Recommended feed (inches per tooth / per rev).
    recommended_feed_mm_rev : float
        Feed in mm/tooth or mm/rev.
    depth_of_cut_mm : float
        Suggested axial depth of cut (mm).
    workpiece_material_key : str
        Normalised workpiece material key used for lookup.
    notes : str
        Source/advisory notes.
    alternatives : List[str]
        Tool IDs of up to 3 alternative matching tools.
    reason : str
        Error reason (set when ok=False).
    honest_flag : str
        Always set; warns that this is a static embedded catalog.
    """
    ok: bool
    tool_id: str = ""
    manufacturer: str = ""
    tool_type: str = ""
    diameter_mm: float = 0.0
    material: str = ""
    coating: Optional[str] = None
    description: str = ""
    recommended_speed_sfm: float = 0.0
    recommended_speed_m_min: float = 0.0
    recommended_feed_ipt: float = 0.0
    recommended_feed_mm_rev: float = 0.0
    depth_of_cut_mm: float = 0.0
    workpiece_material_key: str = ""
    notes: str = ""
    alternatives: List[str] = field(default_factory=list)
    reason: str = ""
    honest_flag: str = (
        "SMALL EMBEDDED CATALOG (~50 tools). Representative mid-range starting values. "
        "Verify against CoroPlus / Iscar ITA / Kennametal NOVO before production. "
        "Apply ±20% tolerance. Ref: Sandvik Cutting Data Rec. 2024; Drozda-Wick §3."
    )


# ---------------------------------------------------------------------------
# Operation → tool_type mapping
# ---------------------------------------------------------------------------

import re as _re

# Word-boundary patterns keyed by tool type.
# Order matters: first match wins.
# Uses whole-word matching (\b) to avoid "surface"→"face" false positives.
# Priority: reamer > drill > tap (because "drill M8 tap hole" = drill op).
_OP_PATTERNS: list[tuple[list[str], str]] = [
    # Reaming — unambiguous
    (["\\bream(?:ing|ed)?\\b", "\\breamer\\b"], "reamer"),
    # Drilling — "drill" verb takes priority over "tap" noun in same phrase
    (["\\bdrill(?:ing|ed)?\\b", "\\bthrough.hole\\b", "\\bblind.hole\\b"], "drill"),
    # Tapping — tap/thread verb, OR standalone M-thread designation without drill verb
    (["\\btap(?:ping)?\\b", "\\bthread(?:ing|ed)?\\b", "\\btapping\\b"], "tap"),
    # Milling / slotting (word-boundary; avoid "surface" → "face" match)
    (["\\bmill(?:ing|ed)?\\b", "\\bslot(?:ting)?\\b", "\\bpocket(?:ing)?\\b",
      "\\bface\\s+mill\\b", "\\bcontour\\b", "\\bprofile\\b", "\\bprofil(?:ing|ed)\\b"], "end_mill"),
    # Turning — requires whole-word "turn" or "lathe"
    (["\\bturn(?:ing|ed)?\\b", "\\blathe\\b"], "insert"),
    # Drilling fallback for bare "hole" or "bore" keyword (without drill verb)
    (["\\bhole\\b", "\\bbore\\b"], "drill"),
]


def _classify_operation(operation: str) -> Optional[str]:
    """Map free-text operation description to a tool_type key.

    Uses word-boundary regex matching to avoid false positives like
    "surface"→end_mill (via substring "face").  Drill verb takes priority
    over tap noun so "drill M8 tap hole" resolves to drill, not tap.

    References
    ----------
    Drozda-Wick §3-1: machining operation taxonomy.
    """
    low = operation.lower()
    for patterns, tool_type in _OP_PATTERNS:
        if any(_re.search(pat, low) for pat in patterns):
            return tool_type
    return None


# ---------------------------------------------------------------------------
# Scoring / selection logic
# ---------------------------------------------------------------------------

def _diameter_score(tool: CatalogTool, target_mm: float) -> float:
    """0..1 score — best for exact match, degrades for miss beyond tolerance.

    References
    ----------
    Drozda-Wick §3-1: tool diameter selection principle (within ±10% acceptable).
    """
    if target_mm <= 0:
        return 0.5  # no diameter constraint given
    diff = abs(tool.diameter_mm - target_mm)
    rel = diff / max(target_mm, 0.001)
    if rel <= 0.05:       # within 5%
        return 1.0
    if rel <= 0.15:       # within 15%
        return 0.6
    if rel <= 0.30:       # within 30%
        return 0.3
    return 0.0


def _material_score(tool: CatalogTool, mat_key: str) -> float:
    """1.0 if workpiece material is explicitly in tool's list; else 0."""
    return 1.0 if mat_key in tool.workpiece_materials else 0.0


def _get_feed_speed(tool: CatalogTool, mat_key: str) -> Optional[FeedSpeedEntry]:
    """Return FeedSpeedEntry for mat_key, or the first entry as fallback."""
    for fs in tool.feed_speeds:
        if fs.workpiece_material == mat_key:
            return fs
    return tool.feed_speeds[0] if tool.feed_speeds else None


def match_tooling(
    operation: str,
    material: str,
    dimension_mm: float = 0.0,
) -> ToolingMatchResult:
    """Match a machining operation to catalog tools.

    Parameters
    ----------
    operation:
        Free-text description of the operation, e.g. "mill a 0.5 mm slot" or
        "drill M8 tap hole" or "ream ø10 hole" or "M6 tap in aluminium".
    material:
        Workpiece material description. Normalised via MATERIAL_ALIASES.
    dimension_mm:
        Target tool diameter (mm). If 0 or omitted the matcher parses the
        operation string for a numeric diameter.

    Returns
    -------
    ToolingMatchResult
        Best match with speeds/feeds; or ok=False on failure.

    References
    ----------
    Sandvik Coromant Cutting Data Recommendations (2024 ed.).
    Drozda-Wick §3-1..§3-7 tool selection principles.
    """
    if not operation or not operation.strip():
        return ToolingMatchResult(ok=False, reason="operation must not be empty")

    # Normalise material
    mat_key = normalise_material(material) if material and material.strip() else ""

    # Classify operation
    tool_type = _classify_operation(operation)
    if tool_type is None:
        return ToolingMatchResult(
            ok=False,
            reason=(
                f"Cannot classify operation '{operation}'. Supported keywords: "
                "mill/slot/pocket, drill/hole, tap/thread, ream/reamer, turn/lathe."
            ),
        )

    # Extract dimension from operation string if not provided
    if dimension_mm <= 0:
        dimension_mm = _parse_dimension(operation)

    # Filter catalog by tool type
    candidates = [t for t in CATALOG if t.tool_type == tool_type]
    if not candidates:
        return ToolingMatchResult(
            ok=False, reason=f"No tools of type '{tool_type}' in embedded catalog."
        )

    # Score candidates
    scored: list[tuple[float, CatalogTool]] = []
    for tool in candidates:
        d_score = _diameter_score(tool, dimension_mm)
        m_score = _material_score(tool, mat_key)
        # Diameter must be at least a weak match (don't return wildly wrong sizes)
        if d_score == 0.0:
            continue
        total = d_score * 0.6 + m_score * 0.4
        scored.append((total, tool))

    if not scored:
        # Relax: accept any diameter
        for tool in candidates:
            m_score = _material_score(tool, mat_key)
            scored.append((m_score * 0.4, tool))

    if not scored:
        return ToolingMatchResult(
            ok=False,
            reason=f"No matching tools found for operation='{operation}', material='{material}', dim={dimension_mm} mm.",
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_tool = scored[0]

    # Get speed/feed
    fs = _get_feed_speed(best_tool, mat_key)
    if fs is None:
        return ToolingMatchResult(
            ok=False,
            reason=f"Tool {best_tool.tool_id} has no speed/feed data for material '{mat_key}'.",
        )

    # Alternatives
    alternatives = [t.tool_id for _, t in scored[1:4] if t.tool_id != best_tool.tool_id]

    return ToolingMatchResult(
        ok=True,
        tool_id=best_tool.tool_id,
        manufacturer=best_tool.manufacturer,
        tool_type=best_tool.tool_type,
        diameter_mm=best_tool.diameter_mm,
        material=best_tool.material,
        coating=best_tool.coating,
        description=best_tool.description,
        recommended_speed_sfm=fs.speed_sfm,
        recommended_speed_m_min=fs.speed_m_min,
        recommended_feed_ipt=fs.feed_ipt,
        recommended_feed_mm_rev=fs.feed_mm_rev,
        depth_of_cut_mm=fs.depth_of_cut_mm,
        workpiece_material_key=mat_key if mat_key else "(unknown)",
        notes=fs.notes,
        alternatives=alternatives,
    )


def _parse_dimension(text: str) -> float:
    """Scan text for a numeric value likely to be a diameter or thread size.

    Understands:
      "0.5 mm", "ø10", "M8", "6.8", etc.

    Returns 0.0 if no numeric found.

    References
    ----------
    Drozda-Wick §3-1: standard nomenclature for tool-size specification.
    """
    import re
    # M-thread: extract major diameter from standard thread designation
    # Handles: M6, M8, M6x1.0, M8x1.25 — \b after digits, allowing 'x' pitch separator
    m = re.search(r'\bM(\d+(?:\.\d+)?)(?:[xX]\d+(?:\.\d+)?)?\b', text, re.IGNORECASE)
    if m:
        md = float(m.group(1))
        # If this is a drill/hole operation, return the ISO 965-1 §5 tap-drill diameter.
        # For tapping operations, return the nominal thread diameter (tool selection key).
        low = text.lower()
        is_drill_op = bool(re.search(r'\bdrill(?:ing)?\b|\bhole\b|\bbore\b', low))
        _tap_drill = {4: 3.3, 5: 4.2, 6: 5.0, 8: 6.8, 10: 8.5, 12: 10.2, 16: 14.0}
        if is_drill_op and md in _tap_drill:
            return _tap_drill[md]
        return md
    # ø-notation or plain number + optional "mm"
    m2 = re.search(r'[ø∅]?\s*([\d]+(?:\.[\d]+)?)\s*mm', text, re.IGNORECASE)
    if m2:
        return float(m2.group(1))
    m3 = re.search(r'[ø∅]\s*([\d]+(?:\.[\d]+)?)', text)
    if m3:
        return float(m3.group(1))
    # bare float (first numeric token)
    m4 = re.search(r'\b([\d]+(?:\.[\d]+)?)\b', text)
    if m4:
        return float(m4.group(1))
    return 0.0


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # noqa: E402
from kerf_core.utils.context import ProjectCtx  # noqa: E402, F401

_spec = ToolSpec(
    name="manufacturing_match_tooling",
    description=(
        "Look up matching cutting tools from an embedded manufacturer catalog "
        "(Sandvik Coromant, Iscar, Kennametal, OSG, Tungaloy; ~50 tools) given a "
        "machining operation requirement, workpiece material, and target dimension.\n"
        "\n"
        "Returns the best-match tool with:\n"
        "  • Manufacturer part number / catalog ID\n"
        "  • Tool type (end_mill, drill, tap, reamer, insert)\n"
        "  • Diameter (mm)\n"
        "  • Recommended surface speed (SFM and m/min)\n"
        "  • Recommended feed (IPT and mm/tooth)\n"
        "  • Up to 3 alternatives\n"
        "\n"
        "Example operations: 'mill a 0.5 mm slot', 'drill M8 tap hole',\n"
        "  'tap M6 thread', 'ream ø10 bore', 'turn OD in stainless'.\n"
        "\n"
        "HONEST FLAG: small embedded catalog (~50 tools); representative starting "
        "speeds/feeds only. Verify against CoroPlus / Iscar ITA for production. "
        "±20% tolerance on all speed/feed values.\n"
        "\n"
        "References: Sandvik Cutting Data Rec. (2024); Drozda-Wick §3 (SME 4th ed.)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "description": (
                    "Machining operation description. Examples: "
                    "'mill a 0.5 mm slot', 'drill M8 tap hole in steel', "
                    "'ream ø10 hole', 'tap M6 in aluminium'. "
                    "Include the tool diameter or thread size for best results."
                ),
            },
            "material": {
                "type": "string",
                "description": (
                    "Workpiece material. Examples: 'aluminium 6061', 'steel', "
                    "'stainless 304', 'titanium Ti6Al4V', 'cast iron', "
                    "'Inconel 718'. Leave empty for generic match."
                ),
            },
            "dimension_mm": {
                "type": "number",
                "description": (
                    "Tool diameter (mm). If omitted, parsed from the operation string. "
                    "For taps supply the thread minor diameter (e.g. 5.0 for M6)."
                ),
            },
        },
        "required": ["operation", "material"],
    },
)


@register(_spec, write=False)
async def run_manufacturing_match_tooling(ctx: ProjectCtx, args: bytes) -> str:
    """LLM tool entry-point for manufacturing_match_tooling.

    References
    ----------
    Sandvik Coromant Cutting Data Recommendations (2024 ed.).
    Drozda-Wick §3 (SME 4th ed., 1983).
    """
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    operation = a.get("operation", "")
    material = a.get("material", "")
    dimension_mm = float(a.get("dimension_mm", 0.0))

    if not operation:
        return err_payload("'operation' is required", "BAD_ARGS")

    result = match_tooling(operation, material, dimension_mm)

    if not result.ok:
        return err_payload(result.reason, "NO_MATCH")

    payload = {
        "ok": True,
        "tool_id": result.tool_id,
        "manufacturer": result.manufacturer,
        "tool_type": result.tool_type,
        "diameter_mm": result.diameter_mm,
        "material": result.material,
        "coating": result.coating,
        "description": result.description,
        "recommended_speed_sfm": result.recommended_speed_sfm,
        "recommended_speed_m_min": result.recommended_speed_m_min,
        "recommended_feed_ipt": result.recommended_feed_ipt,
        "recommended_feed_mm_rev": result.recommended_feed_mm_rev,
        "depth_of_cut_mm": result.depth_of_cut_mm,
        "workpiece_material_key": result.workpiece_material_key,
        "notes": result.notes,
        "alternatives": result.alternatives,
        "honest_flag": result.honest_flag,
    }
    return ok_payload(payload)
