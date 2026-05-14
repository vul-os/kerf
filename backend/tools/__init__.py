from . import (
    file_ops,
    object_ops,
    validation,
    scaffold,
    equations,
    configurations,
    revisions,
    surfacing,
    feature_draft,
    feature_mirror,
    assembly,
    tolerance,
    docs,
    material,
    project_layers,
    sketch,
    # Moved to plugin packages:
    # fem -> kerf-fem
    # cam -> kerf-cam
    # topo -> kerf-topo
    # bim, bim_categories, family, schedule, view, sheet, stairs, railings,
    # mep, curtain_wall, element_types -> kerf-bim
    # rf, autoroute, pour, erc, net_classes, buses, via_stitching, shove_router,
    # pad_overrides, hier_schematic, length_tuning, pcb_drc, pcb_layer_tools,
    # routing, sim -> kerf-electronics
    # subd, mesh, curve_ops, draft, inspection, graph, import_3dm,
    # feature_helix, feature_multi_transform, feature_rib, sheet_revisions -> kerf-imports
    # render -> kerf-render
)

from .registry import Tool, ToolSpec, err_payload, ok_payload
from .context import ProjectCtx
from .executor import Registry, specs, find, execute

__all__ = [
    "Tool",
    "ToolSpec",
    "err_payload",
    "ok_payload",
    "ProjectCtx",
    "Registry",
    "specs",
    "find",
    "execute",
]
