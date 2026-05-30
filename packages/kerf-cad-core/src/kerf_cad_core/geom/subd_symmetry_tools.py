"""
subd_symmetry_tools.py
======================
LLM tools for SUBD-SYMMETRY-DETECT:

  subd_detect_symmetry  -- full PCA-based mirror + rotational + spherical
                           symmetry analysis for a SubD control cage
  subd_enforce_symmetry -- enforce mirror symmetry across a detected plane

References
----------
- Mitra N.J., Guibas L., Pauly M. 2006 "Partial and Approximate Symmetry
  Detection for 3D Geometry", ACM Trans. Graph. 25(3).
- Podolak J., Shilane P., Golovinskiy A., Rusinkiewicz S., Funkhouser T. 2006
  "A Planar-Reflective Symmetry Transform for 3D Shapes", ACM Trans. Graph.
  25(3).
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register


# ---------------------------------------------------------------------------
# subd_detect_symmetry
# ---------------------------------------------------------------------------

_detect_spec = ToolSpec(
    name="subd_detect_symmetry",
    description=(
        "Detect mirror-plane, rotational-axis, and spherical symmetry of a "
        "SubD control-cage vertex cloud.\n\n"
        "**Algorithm** (Mitra-Guibas-Pauly 2006 + Podolak et al. 2006):\n"
        "1. Compute centroid and 3x3 covariance matrix of the cage vertices.\n"
        "2. Jacobi-decompose the covariance matrix -> 3 principal axes.\n"
        "3. Test mirror planes normal to each principal axis (centroid-centred) "
        "plus the three axis-aligned planes (XY/XZ/YZ through origin).\n"
        "4. Test n-fold rotational symmetry about each principal axis for fold "
        "orders 2, 3, 4, 5, 6, 8, 10, 12.  Score = fraction of vertices whose "
        "rotation maps within `tol` of another vertex.\n"
        "5. Spherical flag: all three PCA eigenvalues approximately equal.  "
        "Honest-flag: heuristic only -- confirmed by radial-distance score.\n\n"
        "**Returns**:\n"
        "- `mirror_planes`: list of {normal, offset, label, score} sorted by "
        "score descending.\n"
        "- `rotation_axes`: list of {axis, center, fold_order, score, "
        "continuous, label} for best fold per principal axis.\n"
        "- `spherical`: bool -- all eigenvalues equal +/- 5%.\n"
        "- `spherical_score`: fraction of vertices at consistent radius.\n"
        "- `overall_score`: max across all symmetry types.\n"
        "- `deviation_per_axis`: mean vertex deviation per candidate.\n\n"
        "**Honest-flags**:\n"
        "- Continuous rotational symmetry (cylinder/sphere) cannot be confirmed "
        "by finite fold testing alone; `continuous=true` uses PCA eigenvalue "
        "equality (two transverse eigenvalues within 5%).\n"
        "- O(n^2) nearest-neighbour search; adequate for cages < 10 000 vertices."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vertices": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "List of [x, y, z] cage vertex coordinates.",
            },
            "faces": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}},
                "description": "List of face vertex-index lists (quads or polygons).",
            },
            "tol": {
                "type": "number",
                "description": "Vertex-matching tolerance for symmetry scoring.  Default 1e-4.",
            },
            "score_threshold": {
                "type": "number",
                "description": (
                    "Minimum score to include in the output (0-1).  "
                    "Default 0.0 (include all candidates)."
                ),
            },
        },
        "required": ["vertices", "faces"],
    },
)


@register(_detect_spec, write=False)
async def run_subd_detect_symmetry(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        vertices = a.get("vertices")
        faces = a.get("faces")
        if not isinstance(vertices, list) or not isinstance(faces, list):
            return err_payload("vertices and faces must be arrays", "BAD_ARGS")

        tol = float(a.get("tol", 1e-4))
        score_threshold = float(a.get("score_threshold", 0.0))

        from kerf_cad_core.geom.subd_authoring import SubDCage
        from kerf_cad_core.geom.subd_symmetry import detect_symmetry

        cage = SubDCage(vertices=vertices, faces=faces)
        report = detect_symmetry(cage, tol=tol, score_threshold=score_threshold)

        return ok_payload({
            "mirror_planes": [
                {
                    "normal": p.normal,
                    "offset": p.offset,
                    "label": p.label,
                    "score": p.score,
                }
                for p in report.mirror_planes
            ],
            "rotation_axes": [
                {
                    "axis": r.axis,
                    "center": r.center,
                    "fold_order": r.fold_order,
                    "score": r.score,
                    "continuous": r.continuous,
                    "label": r.label,
                }
                for r in report.rotation_axes
            ],
            "spherical": report.spherical,
            "spherical_score": report.spherical_score,
            "overall_score": report.overall_score,
            "deviation_per_axis": report.deviation_per_axis,
            "num_vertices": len(vertices),
            "honest_flag": (
                "continuous=true uses PCA eigenvalue equality heuristic; "
                "O(n^2) search; tol-sensitive"
            ),
        })

    except Exception as e:
        return err_payload(f"symmetry detection error: {e}", "DETECT_ERROR")


# ---------------------------------------------------------------------------
# subd_enforce_symmetry
# ---------------------------------------------------------------------------

_enforce_spec = ToolSpec(
    name="subd_enforce_symmetry",
    description=(
        "Enforce mirror symmetry across a given plane by copying vertex "
        "positions from the *keep* side to their mirror counterparts.\n\n"
        "For every vertex on the *opposite* half-space, the algorithm:\n"
        "1. Computes its ideal mirror position.\n"
        "2. Finds the nearest vertex on the *keep* side.\n"
        "3. Sets the vertex to ``reflect(nearest_keep_vertex, plane)``.\n\n"
        "Vertices on the plane (|signed_dist| < tol) are snapped to it.\n"
        "Topology is unchanged.  Use `subd_detect_symmetry` first to "
        "identify the best mirror plane.\n\n"
        "**Side convention**: 'left' = keep positive half-space "
        "(dot(n,p) >= 0); 'right' = keep negative."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vertices": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "List of [x, y, z] cage vertex coordinates.",
            },
            "faces": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}},
                "description": "List of face vertex-index lists.",
            },
            "plane_normal": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Symmetry plane unit normal [nx, ny, nz].",
            },
            "plane_offset": {
                "type": "number",
                "description": "Plane offset d such that dot(n,p)=d. Default 0.0.",
            },
            "side": {
                "type": "string",
                "enum": ["left", "right"],
                "description": "Which half-space to treat as authoritative. Default 'left'.",
            },
            "tol": {
                "type": "number",
                "description": "Plane-snapping tolerance. Default 1e-4.",
            },
        },
        "required": ["vertices", "faces", "plane_normal"],
    },
)


@register(_enforce_spec, write=True)
async def run_subd_enforce_symmetry(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        vertices = a.get("vertices")
        faces = a.get("faces")
        plane_normal = a.get("plane_normal")
        if (
            not isinstance(vertices, list)
            or not isinstance(faces, list)
            or not isinstance(plane_normal, list)
        ):
            return err_payload(
                "vertices, faces, and plane_normal must be arrays", "BAD_ARGS",
            )

        plane_offset = float(a.get("plane_offset", 0.0))
        side = str(a.get("side", "left"))
        tol = float(a.get("tol", 1e-4))

        from kerf_cad_core.geom.subd_authoring import SubDCage
        from kerf_cad_core.geom.subd_symmetry import (
            SymmetryPlane,
            detect_mirror_symmetry,
            enforce_mirror_symmetry,
        )

        cage = SubDCage(vertices=vertices, faces=faces)
        plane = SymmetryPlane(
            normal=[float(x) for x in plane_normal],
            offset=plane_offset,
            label="user",
        )
        result = enforce_mirror_symmetry(cage, plane, side=side, tol=tol)

        # Compute post-enforcement score
        post_res = detect_mirror_symmetry(result, tol=tol * 10)

        return ok_payload({
            "cage": {
                "vertices": result.vertices,
                "faces": result.faces,
                "num_vertices": result.num_vertices,
                "num_faces": result.num_faces,
            },
            "post_symmetry_score": post_res.score,
            "plane": {
                "normal": plane.normal,
                "offset": plane.offset,
            },
        })

    except Exception as e:
        return err_payload(f"enforce symmetry error: {e}", "ENFORCE_ERROR")
