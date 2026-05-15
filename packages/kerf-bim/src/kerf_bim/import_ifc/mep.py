"""
mep.py — IfcDistributionElement subtypes → .bim mep[] node.

IFC MEP entities
----------------
IfcDistributionElement is the abstract parent of all MEP elements.
The concrete subtypes we handle:

  IfcFlowSegment      — duct / pipe / conduit straight runs
  IfcFlowFitting      — elbows, tees, reducers
  IfcFlowTerminal     — diffusers, grilles, sinks, fixtures, sockets
  IfcFlowController   — dampers, valves, switches
  IfcEnergyConversionDevice — AHUs, boilers, chillers

.bim mep[] node schema
-----------------------
{
    "kind": "segment" | "fitting" | "terminal" | "controller" | "equipment",
    "ifc_class": "IfcFlowSegment",   # raw IFC class for reference
    "name": "...",
    "level": "L1",
    "position": [x, y, z],           # mm, world-space origin
    "ifc_guid": "...",
    "system_name": "...",             # from IfcDistributionSystem if resolvable
    "predefined_type": "...",         # PredefinedType attribute if present
}

Routing / geometry are not extracted at Tier 2 — full routing lives in
the .duct.json / .pipe.json / .conduit.json MEP file types. This module
populates the elements catalogue in the .bim file so editors can
cross-reference them; full geometry import is Tier 3.
"""
from __future__ import annotations

from typing import Any


# Map from IFC class name fragment to our kind label
_CLASS_KIND_MAP: dict[str, str] = {
    "FlowSegment":             "segment",
    "FlowFitting":             "fitting",
    "FlowTerminal":            "terminal",
    "FlowController":          "controller",
    "EnergyConversionDevice":  "equipment",
    "FlowMovingDevice":        "equipment",   # fans, pumps
    "FlowStorageDevice":       "equipment",   # tanks, vessels
    "DistributionChamberElement": "fitting",  # manholes, chambers
}

_KNOWN_DISTRIBUTION_TYPES = tuple(_CLASS_KIND_MAP.keys())


def _placement_origin(ifc_entity) -> tuple[float, float, float]:
    """Return (x, y, z) world-space origin via placement chain. (0,0,0) on failure."""
    try:
        from ifcopenshell.util.placement import get_local_placement  # type: ignore
        placement = getattr(ifc_entity, "ObjectPlacement", None)
        if placement is None:
            return (0.0, 0.0, 0.0)
        matrix = get_local_placement(placement)
        return (float(matrix[0, 3]), float(matrix[1, 3]), float(matrix[2, 3]))
    except Exception:
        return (0.0, 0.0, 0.0)


def _storey_name_for(ifc_element, level_guid_to_name: dict[str, str]) -> str:
    """Walk ContainedInStructure to find the parent storey name."""
    try:
        rels = getattr(ifc_element, "ContainedInStructure", None) or []
        for rel in rels:
            structure = getattr(rel, "RelatingStructure", None)
            if structure is None:
                continue
            ifc_type = getattr(structure, "is_a", lambda: "")()
            if ifc_type == "IfcBuildingStorey":
                gid = getattr(structure, "GlobalId", "")
                return level_guid_to_name.get(gid, getattr(structure, "Name", "") or "")
    except Exception:
        pass
    return ""


def _system_name_for(ifc_element) -> str:
    """
    Try to resolve the MEP system name via HasAssignments →
    IfcRelAssignsToGroup → RelatingGroup (IfcDistributionSystem / IfcSystem).
    """
    try:
        assignments = getattr(ifc_element, "HasAssignments", None) or []
        for rel in assignments:
            rel_type = getattr(rel, "is_a", lambda: "")()
            if "AssignsToGroup" in rel_type:
                group = getattr(rel, "RelatingGroup", None)
                if group is None:
                    continue
                group_type = getattr(group, "is_a", lambda: "")()
                if "System" in group_type or "Distribution" in group_type:
                    sys_name = getattr(group, "Name", None) or getattr(group, "LongName", None)
                    if sys_name:
                        return str(sys_name)
    except Exception:
        pass
    return ""


def _kind_from_ifc_class(ifc_class: str) -> str:
    """Map an IFC class name to our kind label."""
    for fragment, kind in _CLASS_KIND_MAP.items():
        if fragment in ifc_class:
            return kind
    return "distribution"


def translate_mep_element(
    ifc_element,
    level_guid_to_name: dict[str, str],
    warnings: list[str],
) -> dict[str, Any]:
    """
    Translate one IfcDistributionElement subtype into a .bim mep dict.

    Args:
        ifc_element:        The IFC distribution element entity.
        level_guid_to_name: GlobalId → level name map.
        warnings:           Mutable list; non-fatal issues appended here.

    Returns:
        A dict matching the .bim mep node schema, or {} on hard failure.
    """
    ifc_class = getattr(ifc_element, "is_a", lambda: "")()
    gid = getattr(ifc_element, "GlobalId", "")
    name = str(getattr(ifc_element, "Name", None) or gid)
    predefined_type = str(getattr(ifc_element, "PredefinedType", None) or "")

    kind = _kind_from_ifc_class(ifc_class)
    position = _placement_origin(ifc_element)
    level_name = _storey_name_for(ifc_element, level_guid_to_name)
    system_name = _system_name_for(ifc_element)

    return {
        "kind": kind,
        "ifc_class": ifc_class,
        "name": name,
        "level": level_name,
        "position": [round(position[0], 3), round(position[1], 3), round(position[2], 3)],
        "ifc_guid": gid,
        "system_name": system_name,
        "predefined_type": predefined_type,
    }


# IFC entity types to query for MEP elements, in query order.
# IfcDistributionElement is the abstract supertype; querying by_type() with
# include_subtypes=True (the ifcopenshell default) returns all concrete
# instances.  We enumerate the concrete types explicitly to allow Tier-2
# partial coverage and clear skip warnings.
MEP_QUERY_TYPES = (
    "IfcFlowSegment",
    "IfcFlowFitting",
    "IfcFlowTerminal",
    "IfcFlowController",
    "IfcEnergyConversionDevice",
    "IfcFlowMovingDevice",
    "IfcFlowStorageDevice",
    "IfcDistributionChamberElement",
)
