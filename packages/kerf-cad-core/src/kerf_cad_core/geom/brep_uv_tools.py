"""brep_uv_tools.py — GK-P58: LLM tools for B-rep UV unwrap + atlas.

Registers two LLM-callable tools via kerf_chat.tools.registry:

  ``brep_uv_unwrap``
      UV unwrap all faces of a B-rep body using LSCM, ARAP, or mesh_atlas;
      returns per-face UV regions packed into a square atlas.

  ``brep_uv_distortion_report``
      Compute per-face angle + area distortion for a previously run unwrap.

Both tools operate on structured dicts that describe a B-rep body (via its
faces' surface type and boundary vertices) — no file-system dependency.

Reference
---------
B. Lévy, S. Petitjean, N. Ray, J. Maillot — "Least Squares Conformal Maps
for Automatic Texture Atlas Generation", SIGGRAPH 2002.
A. Sheffer, E. Praun, K. Rose — "Mesh Parameterization Methods and Their
Applications", NOW Publishers 2006.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Graceful import of the tool registry
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

    def register(spec, **kw):  # type: ignore[misc]
        def _dec(fn):
            return fn
        return _dec

    def ok_payload(d):  # type: ignore[misc]
        return json.dumps({"ok": True, **d})

    def err_payload(msg, code="ERROR"):  # type: ignore[misc]
        return json.dumps({"ok": False, "error": msg, "code": code})

    class ToolSpec:  # type: ignore[misc]
        def __init__(self, *, name, description, input_schema):
            self.name = name


# ---------------------------------------------------------------------------
# Internal: construct a Body-like object from a plain dict
# ---------------------------------------------------------------------------


def _body_from_dict(body_dict: Dict[str, Any]):
    """Reconstruct a lightweight brep.Body from a plain serialised dict.

    The dict format is::

        {
          "faces": [
            {
              "surface_type": "plane" | "sphere" | "cylinder" | "torus" | "generic",
              // For "plane":
              "origin": [x, y, z],
              "x_axis": [x, y, z],
              "y_axis": [x, y, z],
              // For "sphere":
              "center": [x, y, z],
              "radius": float,
              // For "cylinder":
              "center": [x, y, z],
              "axis": [x, y, z],
              "radius": float,
              "height": float,
              // For "torus":
              "center": [x, y, z],
              "axis": [x, y, z],
              "major_radius": float,
              "minor_radius": float,
              // Common (optional):
              "vertices": [[x,y,z], ...],   // boundary vertex positions
            },
            ...
          ]
        }

    Returns a list of face-like objects with a ``.surface`` attribute.
    """
    from kerf_cad_core.geom.brep import Plane, SphereSurface, CylinderSurface, TorusSurface

    class _SimpleFace:
        def __init__(self, surface, vertices=None):
            self.surface = surface
            self._vertices = vertices or []
            self.loops = []

        def all_vertices(self):
            return self._vertices

    class _SimpleBody:
        def __init__(self, faces):
            self._faces = faces

        def all_faces(self):
            return self._faces

    faces = []
    for fd in body_dict.get("faces", []):
        stype = fd.get("surface_type", "generic").lower()
        surf = None
        try:
            if stype == "plane":
                surf = Plane(
                    origin=np.array(fd["origin"], dtype=float),
                    x_axis=np.array(fd["x_axis"], dtype=float),
                    y_axis=np.array(fd["y_axis"], dtype=float),
                )
            elif stype == "sphere":
                surf = SphereSurface(
                    center=np.array(fd["center"], dtype=float),
                    radius=float(fd["radius"]),
                )
            elif stype == "cylinder":
                surf = CylinderSurface(
                    center=np.array(fd["center"], dtype=float),
                    axis=np.array(fd["axis"], dtype=float),
                    radius=float(fd["radius"]),
                )
            elif stype == "torus":
                surf = TorusSurface(
                    center=np.array(fd["center"], dtype=float),
                    axis=np.array(fd["axis"], dtype=float),
                    major_radius=float(fd["major_radius"]),
                    minor_radius=float(fd["minor_radius"]),
                )
            else:
                # Generic: provide a trivial evaluator that returns zeros
                class _GenericSurface:
                    def evaluate(self, u, v):
                        return np.zeros(3)
                surf = _GenericSurface()
        except Exception:
            class _GenericSurface:  # type: ignore[misc]
                def evaluate(self, u, v):
                    return np.zeros(3)
            surf = _GenericSurface()

        verts = [np.array(v, dtype=float) for v in fd.get("vertices", [])]
        f = _SimpleFace(surf, verts)
        # Attach coedge-like loop so tessellation can pick up boundary verts
        if verts and stype == "plane":
            class _FakeCoedge:
                def __init__(self, pt):
                    self._pt = pt
                def start_point(self):
                    return self._pt
            class _FakeLoop:
                def __init__(self, coedges):
                    self.coedges = coedges
                    self.is_outer = True
            ces = [_FakeCoedge(v) for v in verts]
            f.loops = [_FakeLoop(ces)]
        faces.append(f)

    return _SimpleBody(faces)


# ---------------------------------------------------------------------------
# Tool 1: brep_uv_unwrap
# ---------------------------------------------------------------------------

_brep_uv_unwrap_spec = ToolSpec(
    name="brep_uv_unwrap",
    description=(
        "UV unwrap all faces of a B-rep body, packing the results into a "
        "square atlas. "
        "\n\n"
        "**Methods:**\n"
        "- ``lscm`` (default) — Least-Squares Conformal Mapping (Lévy 2002); "
        "  minimises angle distortion; best for texture mapping.\n"
        "- ``arap`` — As-Rigid-As-Possible (Sorkine-Hornung 2007); "
        "  lower area distortion than LSCM on curved surfaces.\n"
        "- ``mesh_atlas`` — trivial per-face natural UV rectangle; fastest.\n"
        "\n\n"
        "**Input:** a ``body`` dict describing faces via their surface type "
        "(plane / sphere / cylinder / torus / generic) with boundary vertex "
        "positions. "
        "\n\n"
        "**Output:** "
        "``{face_uv_regions, total_uv_area, distortion_per_face}`` — "
        "one entry per face with ``uv_coords``, atlas offsets, and "
        "distortion metrics. "
        "\n\n"
        "Pure-Python + NumPy / SciPy. No OCCT required."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "body": {
                "type": "object",
                "description": (
                    "B-rep body description. Must contain a ``faces`` array. "
                    "Each face entry needs ``surface_type`` (plane/sphere/"
                    "cylinder/torus/generic) and the corresponding geometric "
                    "parameters (origin/x_axis/y_axis for plane; center/radius "
                    "for sphere; etc.).  Optional ``vertices`` array gives "
                    "boundary corner positions for planar faces."
                ),
            },
            "method": {
                "type": "string",
                "description": "Parametrization method: 'lscm' | 'arap' | 'mesh_atlas'.",
                "enum": ["lscm", "arap", "mesh_atlas"],
                "default": "lscm",
            },
        },
        "required": ["body"],
    },
)


@register(_brep_uv_unwrap_spec)
async def run_brep_uv_unwrap(ctx: Any, args: bytes) -> str:  # type: ignore[misc]
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    body_dict = a.get("body")
    if not body_dict or not isinstance(body_dict, dict):
        return err_payload("'body' dict is required", "BAD_ARGS")

    method = a.get("method", "lscm")
    if method not in ("lscm", "arap", "mesh_atlas"):
        return err_payload(
            f"method must be 'lscm', 'arap', or 'mesh_atlas'; got '{method}'",
            "BAD_ARGS",
        )

    try:
        from kerf_cad_core.geom.uv_unwrap import uv_unwrap_body
        body = _body_from_dict(body_dict)
        result = uv_unwrap_body(body, method=method)
    except Exception as exc:
        return err_payload(f"uv_unwrap_body failed: {exc}", "OP_FAILED")

    return ok_payload({
        "face_uv_regions": result.face_uv_regions,
        "total_uv_area": result.total_uv_area,
        "distortion_per_face": result.distortion_per_face,
        "method": method,
        "face_count": len(result.face_uv_regions),
    })


# ---------------------------------------------------------------------------
# Tool 2: brep_uv_distortion_report
# ---------------------------------------------------------------------------

_brep_uv_distortion_report_spec = ToolSpec(
    name="brep_uv_distortion_report",
    description=(
        "Generate a per-face distortion report for a UV-unwrapped B-rep body. "
        "\n\n"
        "Pass the same ``body`` dict and the ``distortion_per_face`` list "
        "from a prior ``brep_uv_unwrap`` call. "
        "\n\n"
        "Returns per-face angle distortion (degrees, Sheffer 2006 conformal "
        "energy metric) and area distortion (std-dev of per-triangle area "
        "ratio), plus aggregate mean / max values. "
        "\n\n"
        "Use this to compare LSCM vs ARAP: LSCM yields lower angle distortion; "
        "ARAP yields lower area distortion on non-developable surfaces."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "body": {
                "type": "object",
                "description": "Same B-rep body dict passed to brep_uv_unwrap.",
            },
            "distortion_per_face": {
                "type": "array",
                "description": (
                    "The ``distortion_per_face`` list from a brep_uv_unwrap result. "
                    "Each entry: {face_idx, angle_distortion, area_distortion}."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["body", "distortion_per_face"],
    },
)


@register(_brep_uv_distortion_report_spec)
async def run_brep_uv_distortion_report(ctx: Any, args: bytes) -> str:  # type: ignore[misc]
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    body_dict = a.get("body")
    if not body_dict or not isinstance(body_dict, dict):
        return err_payload("'body' dict is required", "BAD_ARGS")

    distortion_per_face = a.get("distortion_per_face")
    if not isinstance(distortion_per_face, list):
        return err_payload("'distortion_per_face' list is required", "BAD_ARGS")

    try:
        from kerf_cad_core.geom.uv_unwrap import UvUnwrapResult, uv_distortion_report
        body = _body_from_dict(body_dict)
        dummy_result = UvUnwrapResult(
            face_uv_regions=[],
            total_uv_area=0.0,
            distortion_per_face=distortion_per_face,
        )
        report = uv_distortion_report(body, dummy_result)
    except Exception as exc:
        return err_payload(f"uv_distortion_report failed: {exc}", "OP_FAILED")

    return ok_payload(report)
