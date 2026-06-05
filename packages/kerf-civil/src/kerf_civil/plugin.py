"""
kerf-civil plugin entry-point.

Registers:
  - LLM tools: civil_horizontal_alignment, civil_vertical_alignment,
               civil_corridor_sections, civil_earthwork_volume,
               civil_tin_terrain, civil_crs_transform,
               civil_water_network_solve, civil_sewer_manning_capacity,
               civil_storm_rational, civil_culvert_capacity,
               civil_drainage_rational_method, civil_time_of_concentration,
               civil_gravity_sewer_profile, civil_gravity_network_solve,
               civil_landxml_import, civil_landxml_export,
               pointcloud_import, pointcloud_deviation_check, pointcloud_fit_plane
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_civil.tools import (
        civil_horizontal_alignment_spec,
        run_civil_horizontal_alignment,
        civil_vertical_alignment_spec,
        run_civil_vertical_alignment,
        civil_corridor_sections_spec,
        run_civil_corridor_sections,
        civil_earthwork_volume_spec,
        run_civil_earthwork_volume,
    )

    ctx.tools.register(
        "civil_horizontal_alignment",
        civil_horizontal_alignment_spec,
        run_civil_horizontal_alignment,
    )
    ctx.tools.register(
        "civil_vertical_alignment",
        civil_vertical_alignment_spec,
        run_civil_vertical_alignment,
    )
    ctx.tools.register(
        "civil_corridor_sections",
        civil_corridor_sections_spec,
        run_civil_corridor_sections,
    )
    ctx.tools.register(
        "civil_earthwork_volume",
        civil_earthwork_volume_spec,
        run_civil_earthwork_volume,
    )

    # GK-P49: corridor B-rep / volume / IFC alignment
    try:
        from kerf_civil.tools_corridor import TOOLS as _corridor_tools
        for tool_name, tool_spec, tool_handler in _corridor_tools:
            ctx.tools.register(tool_name, tool_spec, tool_handler)
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "kerf-civil: failed to load tools_corridor: %s", _exc
        )

    # TIN terrain model + CRS transforms (coverage sweep 2026-05-25)
    try:
        from kerf_civil.tools_terrain import TOOLS as _terrain_tools
        for _tool_name, _tool_spec, _tool_handler in _terrain_tools:
            ctx.tools.register(_tool_name, _tool_spec, _tool_handler)
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "kerf-civil: failed to load tools_terrain: %s", _exc
        )

    # LandXML I/O + hydraulics engines (2026-05-25)
    try:
        from kerf_civil.tools_hydraulics import TOOLS as _hydraulics_tools
        for _tool_name, _tool_spec, _tool_handler in _hydraulics_tools:
            ctx.tools.register(_tool_name, _tool_spec, _tool_handler)
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "kerf-civil: failed to load tools_hydraulics: %s", _exc
        )

    # Parcels + point-cloud + plan-profile sheets (2026-06-05)
    try:
        from kerf_civil.tools_parcels_pointcloud_sheets import TOOLS as _gap_tools
        for _tool_name, _tool_spec, _tool_handler in _gap_tools:
            ctx.tools.register(_tool_name, _tool_spec, _tool_handler)
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "kerf-civil: failed to load tools_parcels_pointcloud_sheets: %s", _exc
        )

    # Dry utilities: gas / electrical duct banks / telecom (2026-06-05)
    try:
        from kerf_civil.tools_dry_utilities import TOOLS as _dry_util_tools
        for _tool_name, _tool_spec, _tool_handler in _dry_util_tools:
            ctx.tools.register(_tool_name, _tool_spec, _tool_handler)
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "kerf-civil: failed to load tools_dry_utilities: %s", _exc
        )

    # Plant/infrastructure point-cloud: laser-scan import, deviation check, RANSAC (2026-06-05)
    try:
        from kerf_civil.tools_pointcloud_plant import TOOLS as _pc_plant_tools
        for _tool_name, _tool_spec, _tool_handler in _pc_plant_tools:
            ctx.tools.register(_tool_name, _tool_spec, _tool_handler)
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "kerf-civil: failed to load tools_pointcloud_plant: %s", _exc
        )

    provides = [
        "civil.horizontal_alignment",
        "civil.vertical_alignment",
        "civil.corridor",
        "civil.earthwork",
        "civil.corridor-brep",
        "civil.corridor-volume",
        "civil.corridor-ifc",
        "civil.tin-terrain",
        "civil.tin-breaklines",
        "civil.tin-boundary",
        "civil.tin-volume-between",
        "civil.tin-interpolate-z",
        "civil.crs-transform",
        "civil.landxml",
        "civil.hydraulics-pressure",
        "civil.hydraulics-pressure-minor-losses",
        "civil.hydraulics-pressure-pump-fop",
        "civil.hydraulics-pressure-residuals",
        "civil.hydraulics-gravity",
        "civil.hydraulics-gravity-hgl-egl",
        "civil.hydraulics-gravity-network",
        "civil.storm",
        "civil.drainage-rational-hec22",
        "civil.parcel-subdivision",
        "civil.pointcloud-ingest",
        "civil.pointcloud-downsample",
        "civil.pointcloud-pmf-ground",
        "civil.pointcloud-surface",
        "civil.plan-profile-sheets",
        "civil.corridor-model",
        "civil.corridor-daylight",
        "civil.corridor-earthwork",
        "civil.corridor-mass-haul",
        "civil.corridor-strings",
        "civil.dry-utilities-gas",
        "civil.dry-utilities-electrical",
        "civil.dry-utilities-telecom",
        "civil.dry-utilities-clearance",
        "plant.pointcloud-import",
        "plant.pointcloud-ply-binary",
        "plant.pointcloud-sor-filter",
        "plant.pointcloud-deviation",
        "plant.pointcloud-ransac-plane",
        "plant.pointcloud-aabb",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="civil",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "civil",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
