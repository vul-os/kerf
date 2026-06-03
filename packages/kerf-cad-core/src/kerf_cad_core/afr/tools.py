"""
kerf_cad_core.afr.tools — Wave 8 LLM tool for AFR topology DAG ordering.

Wave 8 module
-------------
  kerf_cad_core.afr.dag_order

Tool registered
---------------
  afr_topology_dag — Convert a flat list of recognized features into a
    replay-able parametric DAG ordered by ISO 10303-224 precedence.

References
----------
Han, J., Pratt, M. & Regli, W.C. (2000). "Manufacturing Feature Recognition
    from Solid Models: A Status Report." IEEE Trans. Robotics and Automation
    16(6):782–796.
Joshi, S. & Chang, T.C. (1988). "Graph-Based Heuristics for Recognition of
    Machined Features from a 3D Solid Model." Computer-Aided Design 20(2):58–66.
ISO 10303-224:2006 §4.3 — AP224 feature dependency order.
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.afr.dag_order import (
    FeatureKind,
    ParametricDAG,
    RecognizedFeature,
    order_features_to_dag,
    recognized_feature_from_dict,
)


# ---------------------------------------------------------------------------
# Tool: afr_topology_dag
# ---------------------------------------------------------------------------

_FEATURE_KINDS = [k.value for k in FeatureKind]

_afr_topology_dag_spec = ToolSpec(
    name="afr_topology_dag",
    description=(
        "Convert a flat list of recognized manufacturing features into a\n"
        "replay-able parametric DAG using Han-Pratt-Regli 2000 precedence rules\n"
        "and ISO 10303-224 AP224 feature dependency ordering.\n"
        "\n"
        "Feature kind hierarchy (lower layer = executed first):\n"
        "  Layer 0: extrude, revolve  (base body creation)\n"
        "  Layer 1: boss, rib         (additive)\n"
        "  Layer 2: step              (semi-additive)\n"
        "  Layer 3: pocket, slot      (subtractive)\n"
        "  Layer 4: through_hole, blind_hole, counterbore, countersink\n"
        "  Layer 5: fillet, chamfer   (dress-up / finishing)\n"
        "\n"
        "Within a layer, features are ordered by bounding-box intersection:\n"
        "features that intersect are made spatially dependent.\n"
        "\n"
        "Returns:\n"
        "  nodes   — list of {feature_id, kind, layer, dependents: [ids]}\n"
        "  ordered — topologically sorted feature_id list (root → leaves)\n"
        "  depths  — {feature_id: depth_in_dag}\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "features": {
                "type": "array",
                "description": (
                    "List of recognized feature dicts. Each must have:\n"
                    "  type: one of the feature kind strings\n"
                    "  face_ids: [int, ...] (may be empty)\n"
                    "  params: {position: [x,y,z], axis: [x,y,z], ...} (optional)\n"
                    "  bbox: [[xmin,ymin,zmin],[xmax,ymax,zmax]] (optional; "
                    "synthesized if absent)"
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["features"],
    },
)


@register(_afr_topology_dag_spec, write=False)
async def run_afr_topology_dag(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    features_raw = a.get("features")
    if not isinstance(features_raw, list):
        return err_payload("features must be an array", "BAD_ARGS")

    try:
        features: list[RecognizedFeature] = []
        for i, fd in enumerate(features_raw):
            if not isinstance(fd, dict):
                return err_payload(f"features[{i}] must be an object", "BAD_ARGS")
            feat = recognized_feature_from_dict(fd)
            features.append(feat)
    except Exception as exc:
        return err_payload(f"invalid feature data: {exc}", "BAD_ARGS")

    try:
        dag: ParametricDAG = order_features_to_dag(features)
    except Exception as exc:
        return err_payload(f"DAG ordering error: {exc}", "EVAL_ERROR")

    nodes_out = []
    for node in dag.nodes:
        nodes_out.append({
            "feature_id": node.feature.feature_id,
            "kind": node.feature.kind.value,
            "depth_in_tree": node.depth_in_tree,
            "depends_on": list(node.depends_on),
        })

    replay_order = dag.replay_order()

    edges_out = [{"parent": e[0], "child": e[1]} for e in dag.edges]

    return ok_payload({
        "nodes": nodes_out,
        "edges": edges_out,
        "replay_order": replay_order,
        "n_features": len(features),
        "max_depth": max((n.depth_in_tree for n in dag.nodes), default=0) if dag.nodes else 0,
    })


__all__ = ["run_afr_topology_dag"]
