"""
kerf_bim.site_ifc — IFC export bridge for Toposolid (T-114).

Converts :class:`~kerf_bim.site.Toposolid` and
:class:`~kerf_bim.site.BuildingPad` objects to the dict format consumed
by :func:`~kerf_bim.export_ifc.writer.export_ifc`, and provides a
cut/fill earthwork report as a structured dict.

IFC mapping
-----------
- ``Toposolid`` → ``IfcGeographicElement`` (IFC4) / ``IfcSite`` extension
  with TIN geometry in ``IfcTriangulatedFaceSet``.  The writer emits a
  simplified ``IfcSlab(BASESLAB)`` for IFC2X3 compatibility.
- ``BuildingPad`` → ``IfcSlab(BASESLAB)`` with footprint boundary.

The geometry data is embedded in the model dict under the key
``"toposolids"`` and ``"building_pads"``; the standard IFC writer
emits them via the ``_emit_slab`` path with a ``function="BASESLAB"``
override.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = [
    "toposolid_to_ifc_dict",
    "building_pad_to_ifc_dict",
    "cut_fill_report",
    "site_model_dict",
]


def toposolid_to_ifc_dict(
    toposolid: Any,
    name: str = "Toposolid",
    level: str = "L1",
) -> dict:
    """Convert a :class:`~kerf_bim.site.Toposolid` to an IFC slab dict.

    The TIN vertices and simplices are embedded for downstream renderers /
    IFC writers that support ``IfcTriangulatedFaceSet``.  For the baseline
    IFC2X3 writer a bounding-box boundary is used for the slab profile.

    Parameters
    ----------
    toposolid:
        A :class:`kerf_bim.site.Toposolid` instance.
    name:
        Name for the IFC element.
    level:
        Level name to assign the element to.

    Returns
    -------
    dict — compatible with the ``slabs`` list in the IFC model dict,
    plus additional TIN geometry under ``"tin"``.
    """
    import numpy as np
    pts = toposolid.vertices  # (N, 3) in metres (site.py convention)
    simplices = toposolid.simplices  # (M, 3)

    # Bounding-box boundary polygon in mm for IFC writer
    xmin, xmax = float(pts[:, 0].min()), float(pts[:, 0].max())
    ymin, ymax = float(pts[:, 1].min()), float(pts[:, 1].max())
    # Site dimensions are in metres; IFC writer expects mm
    boundary_mm = [
        [xmin * 1000.0, ymin * 1000.0],
        [xmax * 1000.0, ymin * 1000.0],
        [xmax * 1000.0, ymax * 1000.0],
        [xmin * 1000.0, ymax * 1000.0],
    ]

    # Approximate thickness in mm
    thickness_mm = toposolid.thickness * 1000.0

    return {
        # Standard IFC slab keys (IFC2X3 compat)
        "boundary":  boundary_mm,
        "thickness": thickness_mm,
        "level":     level,
        "name":      name,
        "function":  "BASESLAB",
        # Extended TIN data for IFC4 writers / renderers
        "tin": {
            "vertices": pts.tolist(),       # metres
            "simplices": simplices.tolist(),
            "material": toposolid.material,
            "thickness_m": toposolid.thickness,
        },
        "plan_area_m2": toposolid.plan_area(),
        "surface_area_m2": toposolid.surface_area(),
    }


def building_pad_to_ifc_dict(
    pad: Any,
    name: str = "BuildingPad",
    level: str = "L1",
) -> dict:
    """Convert a :class:`~kerf_bim.site.BuildingPad` to an IFC slab dict.

    Parameters
    ----------
    pad:
        A :class:`kerf_bim.site.BuildingPad` instance.
    name:
        Element name.
    level:
        Level name.

    Returns
    -------
    dict — compatible with the ``slabs`` list in the IFC model dict.
    """
    # Footprint boundary in mm (footprint_curve is in metres)
    boundary_mm = [[x * 1000.0, y * 1000.0] for x, y in pad.footprint_curve]

    return {
        "boundary":  boundary_mm,
        "thickness": 300.0,   # nominal 300 mm pad thickness in mm
        "level":     level,
        "name":      name,
        "function":  "BASESLAB",
        "level_m":   pad.level,
        "side_slope": pad.side_slope,
        "pad_area_m2": pad.pad_area(),
    }


def cut_fill_report(
    existing: Any,
    proposed: Any,
    grid_spacing: float = 1.0,
) -> dict:
    """Compute and return an earthwork cut/fill volume report.

    Wraps :func:`~kerf_bim.site.cut_fill_volume` with provenance metadata.

    Parameters
    ----------
    existing:
        :class:`~kerf_bim.site.Toposolid` — existing terrain.
    proposed:
        :class:`~kerf_bim.site.Toposolid` — proposed terrain.
    grid_spacing:
        Integration grid spacing in metres.

    Returns
    -------
    dict with keys ``cut``, ``fill``, ``net`` (all in m³) plus provenance.
    """
    from kerf_bim.site import cut_fill_volume
    result = cut_fill_volume(existing, proposed, grid_spacing=grid_spacing)
    return {
        "cut_m3":         result["cut"],
        "fill_m3":        result["fill"],
        "net_m3":         result["net"],
        "grid_spacing_m": grid_spacing,
        "provenance":     "kerf_bim.site.cut_fill_volume — grid-integration method",
    }


def site_model_dict(
    toposolids: Optional[List[Any]] = None,
    building_pads: Optional[List[Any]] = None,
    site_name: str = "Site",
    level: str = "L1",
) -> dict:
    """Build a complete site model dict suitable for embedding in the BIM model.

    Parameters
    ----------
    toposolids:
        List of :class:`~kerf_bim.site.Toposolid` instances.
    building_pads:
        List of :class:`~kerf_bim.site.BuildingPad` instances.
    site_name:
        Site name string.
    level:
        Default level name.

    Returns
    -------
    dict with ``"toposolids"`` and ``"building_pads"`` slab-dict lists and
    a ``"site"`` metadata block compatible with the IFC exporter.
    """
    topo_dicts: List[dict] = []
    for i, ts in enumerate(toposolids or []):
        topo_dicts.append(
            toposolid_to_ifc_dict(ts, name=f"Toposolid-{i + 1}", level=level)
        )

    pad_dicts: List[dict] = []
    for i, pad in enumerate(building_pads or []):
        pad_dicts.append(
            building_pad_to_ifc_dict(pad, name=f"BuildingPad-{i + 1}", level=level)
        )

    return {
        "site": {"name": site_name},
        "toposolids":    topo_dicts,
        "building_pads": pad_dicts,
        # Merged slab list for IFC exporter
        "slabs": topo_dicts + pad_dicts,
    }
