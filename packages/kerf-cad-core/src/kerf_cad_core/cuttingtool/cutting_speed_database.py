"""
kerf_cad_core.cuttingtool.cutting_speed_database
=================================================

Queryable cutting-speed database: workpiece material × tool material ×
operation → recommended SFM range and feed range.

Public API
----------
query_cutting_speed(material, tool_material, operation) -> CuttingSpeedResult

Sources
-------
Machinery's Handbook, 31st ed., Industrial Press, §1100
  "Cutting Speeds and Feeds" (pp. 1075–1115).
Sandvik Coromant Cutting Data Recommendations, CoroKey 2023/2024.

Honest disclaimer
-----------------
This module contains an **illustrative subset** of cutting-speed data.
Production machining programs should validate against the tool manufacturer's
cutting-data application (Sandvik CoroPlus® ToolGuide, Kennametal NOVO,
Iscar iMachining, etc.) which account for specific insert grade, coating,
coolant strategy, depth-of-cut and machine rigidity.

SFM → m/min conversion:  m_min = sfm / 3.281
m/min → SFM conversion:  sfm = m_min × 3.281

Author: imranparuk
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from kerf_cad_core.cuttingtool.cutting_speeds_data import (
    CUTTING_SPEED_TABLE,
    VALID_WORKPIECE_MATERIALS,
    VALID_TOOL_MATERIALS,
    VALID_OPERATIONS,
    CutRecord,
)


@dataclass
class CuttingSpeedResult:
    """
    Result of a cutting-speed database query.

    Attributes
    ----------
    ok : bool
        True if a matching combination exists and is technically feasible.
    material : str
        Workpiece material key (normalised).
    tool_material : str
        Tool material key (normalised).
    operation : str
        Operation type key (normalised).
    sfm_min : float
        Conservative recommended surface feet per minute.
    sfm_typical : float
        Typical / recommended SFM for the combination.
    sfm_max : float
        Aggressive upper bound SFM (rigid setup, correct coolant).
    sfm_min_m_min : float
        sfm_min converted to m/min (÷ 3.281).
    sfm_typical_m_min : float
        sfm_typical converted to m/min.
    sfm_max_m_min : float
        sfm_max converted to m/min.
    ipt_or_ipr_lo : float
        Lower feed bound in IPT (milling) or IPR (turning/drilling/reaming).
    ipt_or_ipr_hi : float
        Upper feed bound.
    feed_unit : str
        'ipt' | 'ipr' | 'n/a'.
    notes : str
        Application note from the source table.
    source : str
        Primary reference citation.
    feasible : bool
        False when sfm_typical == 0 (combination not recommended).
    reason : str
        Human-readable reason when ok=False or feasible=False.
    """
    ok: bool
    material: str
    tool_material: str
    operation: str
    sfm_min: float
    sfm_typical: float
    sfm_max: float
    sfm_min_m_min: float
    sfm_typical_m_min: float
    sfm_max_m_min: float
    ipt_or_ipr_lo: float
    ipt_or_ipr_hi: float
    feed_unit: str
    notes: str
    source: str
    feasible: bool
    reason: str

    def to_dict(self) -> dict:
        """Return a plain dict suitable for JSON serialisation."""
        return {
            "ok": self.ok,
            "material": self.material,
            "tool_material": self.tool_material,
            "operation": self.operation,
            "sfm_min": self.sfm_min,
            "sfm_typical": self.sfm_typical,
            "sfm_max": self.sfm_max,
            "sfm_min_m_min": self.sfm_min_m_min,
            "sfm_typical_m_min": self.sfm_typical_m_min,
            "sfm_max_m_min": self.sfm_max_m_min,
            "ipt_or_ipr_lo": self.ipt_or_ipr_lo,
            "ipt_or_ipr_hi": self.ipt_or_ipr_hi,
            "feed_unit": self.feed_unit,
            "notes": self.notes,
            "source": self.source,
            "feasible": self.feasible,
            "reason": self.reason,
        }


_SFM_TO_M_MIN = 1.0 / 3.281

_SOURCE_CITATION = (
    "Machinery's Handbook 31e §1100 (cutting speeds pp. 1075–1115); "
    "Sandvik Coromant CoroKey 2023/2024 cutting-data recommendations. "
    "ILLUSTRATIVE SUBSET — validate against manufacturer live-data tools for production."
)


def _normalise(s: str) -> str:
    """Lower-case, strip, replace spaces/hyphens with underscores."""
    return s.strip().lower().replace("-", "_").replace(" ", "_")


def query_cutting_speed(
    material: str,
    tool_material: str,
    operation: str,
) -> CuttingSpeedResult:
    """
    Query recommended cutting speed for a workpiece/tool/operation combination.

    Parameters
    ----------
    material : str
        Workpiece material key. See VALID_WORKPIECE_MATERIALS for accepted values.
        Case-insensitive; spaces and hyphens normalised to underscores.
        Examples: ``"aluminum_6061"``, ``"steel_1018"``, ``"titanium_6al4v"``.
    tool_material : str
        Tool material key. Accepted: ``"hss"``, ``"carbide"``, ``"ceramic"``,
        ``"diamond"``.
    operation : str
        Machining operation. Accepted: ``"turning"``, ``"milling"``,
        ``"drilling"``, ``"reaming"``.

    Returns
    -------
    CuttingSpeedResult
        Dataclass with SFM range, feed range, units, source citation, and
        feasibility flag.

        - ``ok=True, feasible=True``  — usable data found.
        - ``ok=True, feasible=False`` — combination not recommended
          (e.g. PCD on steel); ``reason`` explains why.
        - ``ok=False`` — unknown material, tool, or operation key.

    References
    ----------
    Machinery's Handbook, 31st ed. §1100 (Industrial Press, 2020).
    Sandvik Coromant CoroKey 2023/2024 Cutting Data Recommendations.

    Notes
    -----
    All SFM values are surface feet per minute.  Divide by 3.281 to get m/min
    (equivalently, multiply m/min by 3.281 for SFM).  The dataclass includes
    pre-converted *_m_min fields.

    This database is an illustrative subset.  For production programmes,
    use Sandvik CoroPlus® ToolGuide, Kennametal NOVO, or equivalent live data.

    Examples
    --------
    >>> r = query_cutting_speed("aluminum_6061", "carbide", "milling")
    >>> r.sfm_typical
    1500
    >>> r = query_cutting_speed("titanium_6al4v", "carbide", "turning")
    >>> r.sfm_typical
    250
    >>> r = query_cutting_speed("steel_1018", "hss", "drilling")
    >>> r.sfm_typical
    80
    """
    mat = _normalise(material)
    tool = _normalise(tool_material)
    op = _normalise(operation)

    # Validate keys
    if mat not in VALID_WORKPIECE_MATERIALS:
        return CuttingSpeedResult(
            ok=False, material=mat, tool_material=tool, operation=op,
            sfm_min=0, sfm_typical=0, sfm_max=0,
            sfm_min_m_min=0, sfm_typical_m_min=0, sfm_max_m_min=0,
            ipt_or_ipr_lo=0, ipt_or_ipr_hi=0, feed_unit="n/a",
            notes="",
            source=_SOURCE_CITATION,
            feasible=False,
            reason=(
                f"Unknown workpiece material '{material}'. "
                f"Valid keys: {sorted(VALID_WORKPIECE_MATERIALS)}"
            ),
        )

    if tool not in VALID_TOOL_MATERIALS:
        return CuttingSpeedResult(
            ok=False, material=mat, tool_material=tool, operation=op,
            sfm_min=0, sfm_typical=0, sfm_max=0,
            sfm_min_m_min=0, sfm_typical_m_min=0, sfm_max_m_min=0,
            ipt_or_ipr_lo=0, ipt_or_ipr_hi=0, feed_unit="n/a",
            notes="",
            source=_SOURCE_CITATION,
            feasible=False,
            reason=(
                f"Unknown tool material '{tool_material}'. "
                f"Valid keys: {sorted(VALID_TOOL_MATERIALS)}"
            ),
        )

    if op not in VALID_OPERATIONS:
        return CuttingSpeedResult(
            ok=False, material=mat, tool_material=tool, operation=op,
            sfm_min=0, sfm_typical=0, sfm_max=0,
            sfm_min_m_min=0, sfm_typical_m_min=0, sfm_max_m_min=0,
            ipt_or_ipr_lo=0, ipt_or_ipr_hi=0, feed_unit="n/a",
            notes="",
            source=_SOURCE_CITATION,
            feasible=False,
            reason=(
                f"Unknown operation '{operation}'. "
                f"Valid keys: {sorted(VALID_OPERATIONS)}"
            ),
        )

    rec: CutRecord = CUTTING_SPEED_TABLE[(mat, tool, op)]

    feasible = rec.sfm_typical > 0
    reason = "" if feasible else rec.notes

    return CuttingSpeedResult(
        ok=True,
        material=mat,
        tool_material=tool,
        operation=op,
        sfm_min=rec.sfm_min,
        sfm_typical=rec.sfm_typical,
        sfm_max=rec.sfm_max,
        sfm_min_m_min=round(rec.sfm_min * _SFM_TO_M_MIN, 1),
        sfm_typical_m_min=round(rec.sfm_typical * _SFM_TO_M_MIN, 1),
        sfm_max_m_min=round(rec.sfm_max * _SFM_TO_M_MIN, 1),
        ipt_or_ipr_lo=rec.feed_lo,
        ipt_or_ipr_hi=rec.feed_hi,
        feed_unit=rec.feed_unit,
        notes=rec.notes,
        source=_SOURCE_CITATION,
        feasible=feasible,
        reason=reason,
    )


def list_materials() -> list[str]:
    """Return sorted list of all valid workpiece material keys."""
    return sorted(VALID_WORKPIECE_MATERIALS)


def list_tool_materials() -> list[str]:
    """Return sorted list of all valid tool material keys."""
    return sorted(VALID_TOOL_MATERIALS)


def list_operations() -> list[str]:
    """Return sorted list of all valid operation keys."""
    return sorted(VALID_OPERATIONS)
