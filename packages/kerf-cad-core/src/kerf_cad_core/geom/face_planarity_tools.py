"""LLM tool registration for BREP-FACE-PLANARITY-CHECK.

Exposes brep_check_face_planarity to the Kerf chat agent.
Algorithm: uniform UV-grid sampling + SVD orthogonal regression
(Pratt 1987 s3; Eberly s6.6). Default tolerance = 1e-4 * bbox diagonal.
CAVEAT (v1): inner trim loops not excluded from sampling.
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

__all__ = ["run_brep_check_face_planarity"]


def _make_uniform_knots(n, degree):
    knots = [0.0] * (degree + 1)
    interior = (n + degree + 1) - 2 * (degree + 1)
    for i in range(1, interior + 1):
        knots.append(float(i) / float(interior + 1))
    knots += [1.0] * (degree + 1)
    return knots


_spec = ToolSpec(
    name="brep_check_face_planarity",
    description=(
        "Determine whether a B-rep face is planar (within tolerance), fit the "
        "best-fit plane via SVD (Pratt 1987 / Eberly s6.6), and report: "
        "is_planar, plane_origin [x,y,z], plane_normal [nx,ny,nz], "
        "max_deviation, planarity_score (0=flat), tolerance, samples_used. "
        "surface_type: nurbs | plane | cylinder | sphere. "
        "CAVEAT: v1 full UV-domain sampling -- inner trim loops not excluded."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surface_type": {"type": "string", "enum": ["nurbs", "plane", "cylinder", "sphere"]},
            "control_points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
            "num_u": {"type": "integer"},
            "num_v": {"type": "integer"},
            "degree_u": {"type": "integer"},
            "degree_v": {"type": "integer"},
            "knots_u": {"type": "array", "items": {"type": "number"}},
            "knots_v": {"type": "array", "items": {"type": "number"}},
            "origin": {"type": "array", "items": {"type": "number"}},
            "x_axis": {"type": "array", "items": {"type": "number"}},
            "y_axis": {"type": "array", "items": {"type": "number"}},
            "radius": {"type": "number"},
            "axis": {"type": "array", "items": {"type": "number"}},
            "tolerance": {"type": "number"},
            "samples": {"type": "integer", "minimum": 2, "maximum": 50},
        },
        "required": [],
    },
)


@register(_spec, write=False)
async def run_brep_check_face_planarity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")
    try:
        import numpy as np
        from kerf_cad_core.geom.brep import CylinderSurface, Face, Plane, SphereSurface
        from kerf_cad_core.geom.face_planarity import check_face_planarity
        from kerf_cad_core.geom.nurbs import NurbsSurface

        stype = str(a.get("surface_type", "nurbs")).lower()
        if stype == "nurbs":
            cp_raw = a.get("control_points")
            if not cp_raw:
                return err_payload("control_points required for nurbs", "BAD_ARGS")
            nu = int(a.get("num_u", 0))
            nv = int(a.get("num_v", 0))
            if nu < 2 or nv < 2:
                return err_payload("num_u and num_v must be >= 2", "BAD_ARGS")
            cp_flat = np.array(cp_raw, dtype=float)
            if cp_flat.shape != (nu * nv, 3):
                return err_payload(f"control_points length != num_u*num_v={nu*nv}", "BAD_ARGS")
            cp = cp_flat.reshape(nu, nv, 3)
            du = max(1, min(int(a.get("degree_u", 3)), nu - 1))
            dv = max(1, min(int(a.get("degree_v", 3)), nv - 1))
            ku = list(a["knots_u"]) if "knots_u" in a else _make_uniform_knots(nu, du)
            kv = list(a["knots_v"]) if "knots_v" in a else _make_uniform_knots(nv, dv)
            surface = NurbsSurface(degree_u=du, degree_v=dv, control_points=cp,
                                   knots_u=np.array(ku, dtype=float),
                                   knots_v=np.array(kv, dtype=float))
        elif stype == "plane":
            origin = np.array(a.get("origin", [0.0, 0.0, 0.0]), dtype=float)
            x_axis = np.array(a.get("x_axis", [1.0, 0.0, 0.0]), dtype=float)
            y_axis = np.array(a.get("y_axis", [0.0, 1.0, 0.0]), dtype=float)
            surface = Plane(origin=origin, x_axis=x_axis, y_axis=y_axis)
        elif stype == "sphere":
            center = np.array(a.get("origin", [0.0, 0.0, 0.0]), dtype=float)
            surface = SphereSurface(center=center, radius=float(a.get("radius", 1.0)))
        elif stype == "cylinder":
            center = np.array(a.get("origin", [0.0, 0.0, 0.0]), dtype=float)
            axis = np.array(a.get("axis", [0.0, 0.0, 1.0]), dtype=float)
            surface = CylinderSurface(center=center, axis=axis, radius=float(a.get("radius", 1.0)))
        else:
            return err_payload(f"Unknown surface_type: {stype!r}", "BAD_ARGS")

        face = Face(surface=surface)
        tolerance = float(a["tolerance"]) if "tolerance" in a else None
        samples = int(a.get("samples", 10))
        report = check_face_planarity(face, tolerance=tolerance, samples=samples)
    except (ValueError, TypeError, KeyError) as exc:
        return err_payload(f"bad arguments: {exc}", "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"planarity check failed: {exc}", "ERROR")

    return ok_payload({
        "is_planar": report.is_planar,
        "plane_origin": report.plane_origin.tolist() if report.plane_origin is not None else None,
        "plane_normal": report.plane_normal.tolist() if report.plane_normal is not None else None,
        "max_deviation": report.max_deviation,
        "planarity_score": report.planarity_score,
        "tolerance": report.tolerance,
        "samples_used": report.samples_used,
        "caveat": report.caveat,
    })
