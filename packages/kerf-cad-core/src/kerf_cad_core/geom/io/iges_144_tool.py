"""
geom/io/iges_144_tool.py
========================
LLM tool ``nurbs_export_iges_144`` — export a NURBS surface with one outer
trimming boundary (mandatory) and zero or more inner hole boundaries to an
IGES 5.3 file using entity type 144 (Trimmed Parametric Surface).

IGES 5.3 references
-------------------
* §4.22 — Rational B-Spline Curve (entity 126): UV-space trim curves.
* §4.23 — Curve on a Parametric Surface (entity 142): links UV curve to surface.
* §4.26 — Rational B-Spline Surface (entity 128): the underlying NURBS patch.
* §4.27 — Trimmed (Parametric) Surface (entity 144): wraps 128 + 142 loops.

Entity-144 Form 0 is written (outer boundary is an explicit trimming curve).
Model-space 3-D curve pointers (entity-142 CPTR) are set equal to BPTR when
no separate 3-D curve is provided — readers must treat CPTR == BPTR as
degenerate 3D per the honest-flag caveat in the writer docstring.
"""

from __future__ import annotations

import logging
from typing import List

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.io.iges import (
    IgesWriteError,
    write_iges_trimmed_surface,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    def _build_surface(a: dict):  # type: ignore[type-arg]
        """Build NurbsSurface from tool args.  Returns (NurbsSurface | None, err_str)."""
        degree_u = a.get("degree_u")
        degree_v = a.get("degree_v")
        raw_cp = a.get("control_points", [])
        num_u = a.get("num_u")
        num_v = a.get("num_v")

        if any(x is None for x in [degree_u, degree_v, num_u, num_v]) or not raw_cp:
            return None, "degree_u, degree_v, control_points, num_u, num_v are required"

        try:
            degree_u = int(degree_u)
            degree_v = int(degree_v)
            num_u = int(num_u)
            num_v = int(num_v)
        except (TypeError, ValueError) as exc:
            return None, f"degree/num must be integers: {exc}"

        if degree_u < 1 or degree_v < 1:
            return None, "degree_u and degree_v must be >= 1"
        if num_u < 2 or num_v < 2:
            return None, "num_u and num_v must be >= 2"
        if len(raw_cp) != num_u * num_v:
            return None, (
                f"control_points length {len(raw_cp)} != num_u*num_v={num_u * num_v}"
            )

        try:
            cp_flat = [np.asarray(p, dtype=float) for p in raw_cp]
            dim = cp_flat[0].size
            cp = np.array(
                [p.tolist()[:dim] for p in cp_flat], dtype=float
            ).reshape(num_u, num_v, dim)
        except Exception as exc:
            return None, f"invalid control_points: {exc}"

        def _make_knots(n: int, deg: int) -> np.ndarray:
            inner = max(0, n - deg - 1)
            return np.concatenate([
                np.zeros(deg + 1),
                np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                np.ones(deg + 1),
            ])

        try:
            surface = NurbsSurface(
                degree_u=degree_u,
                degree_v=degree_v,
                control_points=cp,
                knots_u=_make_knots(num_u, degree_u),
                knots_v=_make_knots(num_v, degree_v),
            )
        except Exception as exc:
            return None, f"failed to build NurbsSurface: {exc}"

        return surface, ""

    def _build_loop(loop_data: list) -> tuple:  # type: ignore[type-arg]
        """Build a list of NurbsCurve from a loop spec.

        Each entry is a dict with:
            degree : int
            control_points : list of [u, v] pairs
            knots : optional list of floats (clamped uniform if omitted)

        Returns (list[NurbsCurve] | None, err_str).
        """
        curves: List[NurbsCurve] = []
        for i, seg in enumerate(loop_data):
            deg = seg.get("degree")
            raw_pts = seg.get("control_points", [])
            if deg is None or not raw_pts:
                return None, f"loop segment {i}: degree and control_points are required"
            try:
                deg = int(deg)
            except (TypeError, ValueError) as exc:
                return None, f"loop segment {i}: degree must be integer: {exc}"

            try:
                pts = np.array(raw_pts, dtype=float)
            except Exception as exc:
                return None, f"loop segment {i}: invalid control_points: {exc}"

            if pts.ndim != 2 or pts.shape[1] < 2:
                return None, (
                    f"loop segment {i}: control_points must be 2-D [[u,v], ...]; "
                    f"got shape {pts.shape}"
                )
            pts = pts[:, :2]
            n_cp = pts.shape[0]

            raw_knots = seg.get("knots")
            if raw_knots is not None:
                try:
                    knots = np.array(raw_knots, dtype=float)
                except Exception as exc:
                    return None, f"loop segment {i}: invalid knots: {exc}"
            else:
                inner = max(0, n_cp - deg - 1)
                knots = np.concatenate([
                    np.zeros(deg + 1),
                    np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                    np.ones(deg + 1),
                ])

            expected_n_knots = n_cp + deg + 1
            if len(knots) != expected_n_knots:
                return None, (
                    f"loop segment {i}: knot vector length {len(knots)} != "
                    f"n_cp + deg + 1 = {expected_n_knots}"
                )

            try:
                curves.append(NurbsCurve(degree=deg, control_points=pts, knots=knots))
            except Exception as exc:
                return None, f"loop segment {i}: failed to build NurbsCurve: {exc}"

        return curves, ""

    _spec = ToolSpec(
        name="nurbs_export_iges_144",
        description=(
            "Export a NURBS surface with an outer trimming boundary (mandatory) and optional "
            "inner hole boundaries to an IGES 5.3 file using entity type 144 "
            "(Trimmed Parametric Surface, §4.27), entity 128 (NURBS surface, §4.26), "
            "entity 142 (Curve on Parametric Surface, §4.23), and entity 126 "
            "(Rational B-Spline Curve, §4.22).  Writes Form 0 (outer boundary is an "
            "explicit trimming curve).  Returns the output file path and entity counts.\n\n"
            "Model-space 3D curve caveat: entity-142 CPTR is set equal to BPTR "
            "(the UV-space curve DE pointer) when no separate 3D curve is provided."
        ),
        parameters={
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "Absolute path where the .igs file will be written.",
                },
                "surface": {
                    "type": "object",
                    "description": (
                        "NURBS surface to export.  Fields: "
                        "degree_u (int), degree_v (int), num_u (int), num_v (int), "
                        "control_points (flat list of num_u*num_v [x,y,z] points, row-major U first)."
                    ),
                    "properties": {
                        "degree_u": {"type": "integer"},
                        "degree_v": {"type": "integer"},
                        "num_u": {"type": "integer"},
                        "num_v": {"type": "integer"},
                        "control_points": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                    "required": ["degree_u", "degree_v", "num_u", "num_v", "control_points"],
                },
                "outer_loop": {
                    "type": "array",
                    "description": (
                        "Outer trimming boundary — ordered list of UV-space curve segments.  "
                        "Each segment: {degree: int, control_points: [[u,v], ...], "
                        "knots: [float, ...] (optional)}."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "degree": {"type": "integer"},
                            "control_points": {
                                "type": "array",
                                "items": {"type": "array", "items": {"type": "number"}},
                            },
                            "knots": {
                                "type": "array",
                                "items": {"type": "number"},
                            },
                        },
                        "required": ["degree", "control_points"],
                    },
                },
                "inner_loops": {
                    "type": "array",
                    "description": (
                        "Optional inner (hole) boundary loops.  Each element is a list of "
                        "curve segments.  Omit or pass [] for no holes."
                    ),
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "degree": {"type": "integer"},
                                "control_points": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                    },
                                },
                                "knots": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                },
                            },
                            "required": ["degree", "control_points"],
                        },
                    },
                },
            },
            "required": ["output_path", "surface", "outer_loop"],
        },
    )

    @register(_spec)
    def nurbs_export_iges_144(args: dict) -> dict:  # type: ignore[type-arg]
        """LLM tool: export NURBS surface + trim loops to IGES entity-144.

        IGES 5.3 §4.27 (entity 144), §4.26 (entity 128), §4.23 (entity 142),
        §4.22 (entity 126).
        """
        try:
            output_path = str(args.get("output_path", ""))
            surf_args = args.get("surface")
            outer_raw = args.get("outer_loop", [])
            inner_raw = args.get("inner_loops", [])
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        if not output_path:
            return err_payload("output_path is required", "BAD_ARGS")
        if not surf_args:
            return err_payload("surface is required", "BAD_ARGS")
        if not outer_raw:
            return err_payload("outer_loop must contain at least one curve segment", "BAD_ARGS")

        srf, err = _build_surface(surf_args)
        if err:
            return err_payload(f"surface: {err}", "BAD_ARGS")

        outer_loop, err = _build_loop(outer_raw)
        if err:
            return err_payload(f"outer_loop: {err}", "BAD_ARGS")

        inner_loops: List[List[NurbsCurve]] = []
        for li, raw_inner in enumerate(inner_raw):
            curves, err = _build_loop(raw_inner)
            if err:
                return err_payload(f"inner_loops[{li}]: {err}", "BAD_ARGS")
            inner_loops.append(curves)

        try:
            iges_bytes = write_iges_trimmed_surface(srf, outer_loop, inner_loops)
        except IgesWriteError as exc:
            return err_payload(str(exc), "OP_FAILED")
        except Exception as exc:
            return err_payload(f"IGES write error: {exc}", "OP_FAILED")

        try:
            with open(output_path, "wb") as f:
                f.write(iges_bytes)
        except OSError as exc:
            return err_payload(f"cannot write file {output_path!r}: {exc}", "IO_ERROR")

        n_outer_segs = len(outer_loop)
        n_inner_loops = len(inner_loops)
        n_inner_segs = sum(len(ll) for ll in inner_loops)

        return ok_payload({
            "output_path": output_path,
            "bytes_written": len(iges_bytes),
            "entity_counts": {
                "128_nurbs_surface": 1,
                "126_nurbs_curve": n_outer_segs + n_inner_segs,
                "142_curve_on_surface": n_outer_segs + n_inner_segs,
                "144_trimmed_surface": 1,
            },
            "outer_loop_segments": n_outer_segs,
            "inner_loops": n_inner_loops,
            "inner_loop_segments": n_inner_segs,
            "caveats": (
                "entity-142 CPTR == BPTR (model-space 3D curve degenerate/omitted); "
                "Form 0 written (outer boundary is an explicit trimming curve)."
            ),
        })
