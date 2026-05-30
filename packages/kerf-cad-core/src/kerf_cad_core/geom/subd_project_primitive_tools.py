"""
subd_project_primitive_tools.py
================================
LLM tools for SUBD-CAGE-PROJECT-TO-PRIMITIVE:

  subd_project_cage_to_sphere   — snap cage vertices to a sphere surface
  subd_project_cage_to_cylinder — snap cage vertices to a cylinder surface
  subd_project_cage_to_plane    — snap cage vertices to a plane surface

See ``subd_project_primitive.py`` for algorithm details.
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

# ---------------------------------------------------------------------------
# Shared cage serialisation helper
# ---------------------------------------------------------------------------

def _cage_payload(cage, report) -> dict:
    return {
        "cage": {
            "vertices": cage.vertices,
            "faces": cage.faces,
            "num_vertices": cage.num_vertices,
            "num_faces": cage.num_faces,
        },
        "report": {
            "num_vertices": report.num_vertices,
            "max_projection_distance": report.max_projection_distance,
            "mean_projection_distance": report.mean_projection_distance,
            "honest_flag": report.honest_flag,
            "honest_note": report.honest_note,
        },
    }


# ---------------------------------------------------------------------------
# subd_project_cage_to_sphere
# ---------------------------------------------------------------------------

_sphere_spec = ToolSpec(
    name="subd_project_cage_to_sphere",
    description=(
        "Project every vertex of a SubD control cage onto a sphere surface.\n\n"
        "For each cage vertex **v**, the new position is:\n"
        "  v' = center + radius * (v - center) / |v - center|\n\n"
        "Vertices coincident with the center are left unchanged.\n\n"
        "**Use case**: clean up a coarse cage that approximates a sphere "
        "(e.g. a unit-cube cage) so that all control points sit exactly on the "
        "analytic sphere before Catmull-Clark subdivision.  Two levels of "
        "subdivision on the projected cage produce a limit surface whose "
        "deviation from the true sphere is dramatically smaller than the "
        "pre-projection approximation.\n\n"
        "**Honest flag**: face areas and edge lengths are NOT preserved — only "
        "vertex positions are snapped.  The report includes `max_projection_distance` "
        "(maximum vertex displacement) and `mean_projection_distance`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vertices": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "List of [x, y, z] cage vertex coordinates.",
            },
            "faces": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}},
                "description": "List of face vertex-index lists (quads or polygons).",
            },
            "center": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Sphere center [cx, cy, cz]. Default [0, 0, 0].",
            },
            "radius": {
                "type": "number",
                "description": "Sphere radius (positive). Default 1.0.",
            },
        },
        "required": ["vertices", "faces"],
    },
)


@register(_sphere_spec, write=False)
async def run_subd_project_cage_to_sphere(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        vertices = a.get("vertices")
        faces = a.get("faces")
        if not isinstance(vertices, list) or not isinstance(faces, list):
            return err_payload("vertices and faces must be arrays", "BAD_ARGS")
        center = a.get("center", [0.0, 0.0, 0.0])
        radius = float(a.get("radius", 1.0))

        from kerf_cad_core.geom.subd_authoring import SubDCage
        from kerf_cad_core.geom.subd_project_primitive import project_cage_to_sphere

        cage = SubDCage(vertices=vertices, faces=faces)
        projected, report = project_cage_to_sphere(cage, center=center, radius=radius)
        return ok_payload(_cage_payload(projected, report))

    except Exception as e:
        return err_payload(f"projection error: {e}", "PROJECT_ERROR")


# ---------------------------------------------------------------------------
# subd_project_cage_to_cylinder
# ---------------------------------------------------------------------------

_cylinder_spec = ToolSpec(
    name="subd_project_cage_to_cylinder",
    description=(
        "Project every vertex of a SubD control cage onto an infinite "
        "right-circular cylinder surface.\n\n"
        "Algorithm per vertex:\n"
        "  1. Project vertex onto the axis line to find the foot point.\n"
        "  2. Compute the radial vector (perpendicular to axis).\n"
        "  3. Scale the radial vector to `radius`.\n"
        "  4. New position = foot + scaled radial.\n\n"
        "Vertices on the axis (radial magnitude < 1e-12) are left unchanged.\n"
        "The cylinder is infinite — no height capping.\n\n"
        "**Honest flag**: face areas and edge lengths are NOT preserved — only "
        "vertex positions are snapped."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vertices": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "List of [x, y, z] cage vertex coordinates.",
            },
            "faces": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}},
                "description": "List of face vertex-index lists.",
            },
            "axis_origin": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "A point on the cylinder axis [ox, oy, oz]. Default [0, 0, 0].",
            },
            "axis_direction": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Direction vector of the cylinder axis [dx, dy, dz]. Default [0, 0, 1].",
            },
            "radius": {
                "type": "number",
                "description": "Cylinder radius (positive). Default 1.0.",
            },
        },
        "required": ["vertices", "faces"],
    },
)


@register(_cylinder_spec, write=False)
async def run_subd_project_cage_to_cylinder(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        vertices = a.get("vertices")
        faces = a.get("faces")
        if not isinstance(vertices, list) or not isinstance(faces, list):
            return err_payload("vertices and faces must be arrays", "BAD_ARGS")
        axis_origin = a.get("axis_origin", [0.0, 0.0, 0.0])
        axis_direction = a.get("axis_direction", [0.0, 0.0, 1.0])
        radius = float(a.get("radius", 1.0))

        from kerf_cad_core.geom.subd_authoring import SubDCage
        from kerf_cad_core.geom.subd_project_primitive import project_cage_to_cylinder

        cage = SubDCage(vertices=vertices, faces=faces)
        projected, report = project_cage_to_cylinder(
            cage,
            axis_origin=axis_origin,
            axis_direction=axis_direction,
            radius=radius,
        )
        return ok_payload(_cage_payload(projected, report))

    except Exception as e:
        return err_payload(f"projection error: {e}", "PROJECT_ERROR")


# ---------------------------------------------------------------------------
# subd_project_cage_to_plane
# ---------------------------------------------------------------------------

_plane_spec = ToolSpec(
    name="subd_project_cage_to_plane",
    description=(
        "Project every vertex of a SubD control cage onto a plane.\n\n"
        "Formula: p' = p - dot(p - origin, n_hat) * n_hat\n\n"
        "If the normal vector is zero, the cage is returned unchanged.\n\n"
        "**Honest flag**: face areas and edge lengths are NOT preserved — only "
        "vertex positions are snapped."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vertices": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "List of [x, y, z] cage vertex coordinates.",
            },
            "faces": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}},
                "description": "List of face vertex-index lists.",
            },
            "origin": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "A point on the plane [ox, oy, oz]. Default [0, 0, 0].",
            },
            "normal": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Plane normal vector [nx, ny, nz] (need not be unit length). Default [0, 0, 1].",
            },
        },
        "required": ["vertices", "faces"],
    },
)


@register(_plane_spec, write=False)
async def run_subd_project_cage_to_plane(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        vertices = a.get("vertices")
        faces = a.get("faces")
        if not isinstance(vertices, list) or not isinstance(faces, list):
            return err_payload("vertices and faces must be arrays", "BAD_ARGS")
        origin = a.get("origin", [0.0, 0.0, 0.0])
        normal = a.get("normal", [0.0, 0.0, 1.0])

        from kerf_cad_core.geom.subd_authoring import SubDCage
        from kerf_cad_core.geom.subd_project_primitive import project_cage_to_plane

        cage = SubDCage(vertices=vertices, faces=faces)
        projected, report = project_cage_to_plane(cage, origin=origin, normal=normal)
        return ok_payload(_cage_payload(projected, report))

    except Exception as e:
        return err_payload(f"projection error: {e}", "PROJECT_ERROR")
