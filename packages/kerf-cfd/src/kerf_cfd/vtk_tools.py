"""
LLM tools for VTK/VTU export and ParaView-style post-processing.

Registers:
  cfd_export_vtk          — write CFD fields to .vtk (legacy ASCII) or
                            .vtu (XML, ASCII or base64 binary)
  cfd_postprocess_filter  — server-side ParaView filters:
                            slice | contour | streamline | integral | probe | derived

References
----------
VTK file formats: Schroeder W., Martin K., Lorensen B. (2006)
  "The Visualization Toolkit" 4th ed. Appendix B.
Hunt J.C.R., Wray A.A., Moin P. (1988) "Eddies, Streams, and
  Convergence Zones" CTR-S88 (Q-criterion).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cfd._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_cfd.vtk_export import (
    CFDMesh,
    PostProcessor,
    read_legacy_vtk,
    write_legacy_vtk,
    write_vtu,
)


# ---------------------------------------------------------------------------
# Helper: build CFDMesh from LLM tool args
# ---------------------------------------------------------------------------

def _build_mesh_from_args(a: dict) -> CFDMesh | None:
    """
    Build a CFDMesh from structured args dict.

    Expected keys (see tool spec):
      points        [[x,y,z], ...]
      cells         [[v0, v1, ...], ...]
      cell_types    [int, ...]  (optional)
      point_data    {name: [[…]] or [...]}  (optional)
      cell_data     {name: [[…]] or [...]}  (optional)
    """
    pts_raw = a.get("points")
    cells_raw = a.get("cells")
    if pts_raw is None or cells_raw is None:
        return None
    points = np.array(pts_raw, dtype=float)
    cells = [list(c) for c in cells_raw]
    cell_types = a.get("cell_types") or None

    point_data: dict[str, np.ndarray] = {}
    for name, arr in (a.get("point_data") or {}).items():
        point_data[name] = np.array(arr, dtype=float)

    cell_data: dict[str, np.ndarray] = {}
    for name, arr in (a.get("cell_data") or {}).items():
        cell_data[name] = np.array(arr, dtype=float)

    return CFDMesh(
        points,
        cells,
        cell_types=cell_types,
        point_data=point_data,
        cell_data=cell_data,
    )


# ---------------------------------------------------------------------------
# Tool 1: cfd_export_vtk
# ---------------------------------------------------------------------------

_export_vtk_spec = ToolSpec(
    name="cfd_export_vtk",
    description=(
        "Export CFD simulation fields to ParaView-compatible VTK formats.\n\n"
        "Formats:\n"
        "  vtk  — VTK DataFile v4.0 legacy ASCII (DATASET UNSTRUCTURED_GRID).\n"
        "          Universally readable by ParaView, VisIt, Tecplot, MATLAB.\n"
        "  vtu  — VTK XML Unstructured Grid (.vtu). ASCII or base64-binary.\n"
        "          ParaView native; supports parallel I/O extensions.\n\n"
        "Fields supported:\n"
        "  point_data / cell_data — scalars (1 component) and vectors (3 components).\n"
        "  Typical CFD: velocity U (vector), pressure p (scalar), temperature T,\n"
        "  turbulent kinetic energy k, dissipation epsilon/omega.\n\n"
        "The exported file can be opened directly in ParaView to apply any native\n"
        "filter (Slice, Contour, Glyph, StreamTracer, Calculator, etc.).\n\n"
        "References: Schroeder (2006) VTK 4th ed., Appendix B."
    ),
    input_schema={
        "type": "object",
        "required": ["points", "cells"],
        "properties": {
            "points": {
                "type": "array",
                "description": "Node coordinates [[x,y,z], ...]. Shape (N_pts, 3).",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 3,
                },
            },
            "cells": {
                "type": "array",
                "description": (
                    "Cell connectivity [[v0,v1,...], ...]. "
                    "Each entry lists node indices for that cell. "
                    "Tet=4 nodes, Hex=8, Wedge=6, Pyramid=5, Tri=3."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 3,
                },
            },
            "cell_types": {
                "type": "array",
                "description": (
                    "VTK cell type codes [int, ...]. Optional. "
                    "If omitted, inferred from connectivity: "
                    "4→VTK_TETRA(10), 8→VTK_HEXAHEDRON(12), "
                    "6→VTK_WEDGE(13), 5→VTK_PYRAMID(14), 3→VTK_TRIANGLE(5)."
                ),
                "items": {"type": "integer"},
            },
            "point_data": {
                "type": "object",
                "description": (
                    "Point-centred field arrays. "
                    "Scalar: {name: [v0, v1, ...]} (length = N_pts). "
                    "Vector: {name: [[vx,vy,vz], ...]} (shape N_pts×3)."
                ),
                "additionalProperties": True,
            },
            "cell_data": {
                "type": "object",
                "description": (
                    "Cell-centred field arrays (same convention as point_data). "
                    "Length / first dim = number of cells."
                ),
                "additionalProperties": True,
            },
            "format": {
                "type": "string",
                "enum": ["vtk", "vtu"],
                "description": "Output format: 'vtk' (legacy ASCII) or 'vtu' (XML). Default: 'vtu'.",
                "default": "vtu",
            },
            "binary": {
                "type": "boolean",
                "description": "For vtu: True=base64 binary (compact), False=ASCII. Default True.",
                "default": True,
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Absolute path to write the file. "
                    "If omitted, writes to a temp file and returns the path."
                ),
            },
        },
    },
)


def _export_vtk_sync(a: dict) -> dict:
    mesh = _build_mesh_from_args(a)
    if mesh is None:
        return {"ok": False, "error": "points and cells are required", "code": "BAD_ARGS"}

    fmt = a.get("format", "vtu")
    binary = bool(a.get("binary", True))
    out_path = a.get("output_path")

    if out_path is None:
        suffix = ".vtk" if fmt == "vtk" else ".vtu"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        out_path = tmp.name
        tmp.close()

    if fmt == "vtk":
        write_legacy_vtk(mesh, path=out_path)
        fmt_label = "VTK legacy ASCII"
    else:
        write_vtu(mesh, path=out_path, binary=binary)
        fmt_label = f"VTK XML ({('base64 binary' if binary else 'ASCII')})"

    file_size = Path(out_path).stat().st_size

    return {
        "ok": True,
        "format": fmt,
        "format_label": fmt_label,
        "output_path": out_path,
        "file_size_bytes": file_size,
        "n_points": mesh.n_points,
        "n_cells": mesh.n_cells,
        "point_data_fields": list(mesh.point_data.keys()),
        "cell_data_fields": list(mesh.cell_data.keys()),
        "paraview_note": (
            "Open in ParaView: File → Open → select this file. "
            "Apply Slice, Contour, StreamTracer, or Glyph filters directly."
        ),
    }


@register(_export_vtk_spec)
async def cfd_export_vtk(ctx: ProjectCtx, args: bytes) -> str:
    import asyncio
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    if not a.get("points") or not a.get("cells"):
        return err_payload("points and cells are required", "BAD_ARGS")
    result = await asyncio.to_thread(_export_vtk_sync, a)
    if not result.get("ok"):
        return err_payload(result.get("error", "unknown"), result.get("code", "ERROR"))
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool 2: cfd_postprocess_filter
# ---------------------------------------------------------------------------

_filter_spec = ToolSpec(
    name="cfd_postprocess_filter",
    description=(
        "Apply ParaView-style server-side post-processing filters to CFD field data.\n\n"
        "All filters run in Python (NumPy) — no ParaView install required.\n"
        "Results are returned as JSON; export with cfd_export_vtk to open in ParaView.\n\n"
        "Filters\n"
        "-------\n"
        "slice       — Cut-plane extraction: field values for cells near a plane\n"
        "              defined by (normal, origin).  Returns cell centres + values.\n"
        "contour     — Iso-surface: cells straddling a scalar iso-value.\n"
        "streamline  — RK4 streamline integration through velocity field from seeds.\n"
        "              Direction: forward | backward | both.\n"
        "integral    — volume_average | volume_integral | min | max | mean | rms.\n"
        "probe       — Interpolate field at arbitrary [x,y,z] points (nearest-cell).\n"
        "derived     — Compute: vorticity | q_criterion | gradient_p |\n"
        "              pressure_coeff | divergence | strain_rate.\n\n"
        "References\n"
        "----------\n"
        "Schroeder (2006) VTK 4th ed. (filter pipeline).\n"
        "Hunt et al. (1988) CTR-S88 (Q-criterion).\n"
        "White (2011) §3 (pressure coefficient).\n"
        "Blazek (2015) §5.3 (unstructured gradient).\n"
        "Press et al. (2007) §17.1 (RK4)."
    ),
    input_schema={
        "type": "object",
        "required": ["filter", "points", "cells"],
        "properties": {
            # ── Mesh ──────────────────────────────────────────────────────
            "points": {
                "type": "array",
                "description": "Node coordinates [[x,y,z], ...].",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3},
            },
            "cells": {
                "type": "array",
                "description": "Cell connectivity [[v0,v1,...], ...].",
                "items": {"type": "array", "items": {"type": "integer"}, "minItems": 3},
            },
            "cell_types": {
                "type": "array",
                "description": "VTK cell type codes (optional).",
                "items": {"type": "integer"},
            },
            "point_data": {
                "type": "object",
                "description": "Point-centred field arrays {name: values}.",
                "additionalProperties": True,
            },
            "cell_data": {
                "type": "object",
                "description": "Cell-centred field arrays {name: values}.",
                "additionalProperties": True,
            },
            # ── Filter ────────────────────────────────────────────────────
            "filter": {
                "type": "string",
                "enum": ["slice", "contour", "streamline", "integral", "probe", "derived"],
                "description": "Filter type to apply.",
            },
            # slice params
            "normal": {
                "type": "array",
                "description": "Slice plane normal [nx, ny, nz]. Required for slice.",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "origin": {
                "type": "array",
                "description": "Point on slice plane [x, y, z]. Required for slice.",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "tolerance": {
                "type": "number",
                "description": "Slice band half-width [m]. Default: auto (1.5× mean spacing).",
            },
            # contour / iso-surface params
            "iso_value": {
                "type": "number",
                "description": "Iso-surface scalar value. Required for contour.",
            },
            # streamline params
            "seed_points": {
                "type": "array",
                "description": "Streamline seed points [[x,y,z], ...]. Required for streamline.",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3},
            },
            "max_steps": {
                "type": "integer",
                "description": "Max integration steps per streamline (default 500).",
                "default": 500,
            },
            "step_size": {
                "type": "number",
                "description": "RK4 step size [m]. Default: 10% of mean cell spacing.",
            },
            "direction": {
                "type": "string",
                "enum": ["forward", "backward", "both"],
                "description": "Streamline direction. Default: 'forward'.",
                "default": "forward",
            },
            # integral params
            "operation": {
                "type": "string",
                "enum": ["volume_average", "volume_integral", "min", "max", "mean", "rms"],
                "description": "Integral operation. Required for integral filter.",
            },
            "cell_volumes": {
                "type": "array",
                "description": "Cell volumes [m³] for accurate integral. If omitted, estimated.",
                "items": {"type": "number"},
            },
            # probe params
            "probe_points": {
                "type": "array",
                "description": "Probe point coordinates [[x,y,z], ...]. Required for probe.",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3},
            },
            # derived params
            "quantity": {
                "type": "string",
                "enum": [
                    "vorticity", "q_criterion", "gradient_p",
                    "pressure_coeff", "divergence", "strain_rate",
                ],
                "description": "Derived quantity. Required for derived filter.",
            },
            "rho": {
                "type": "number",
                "description": "Fluid density [kg/m³] for pressure_coeff (default 1.225 air).",
                "default": 1.225,
            },
            "U_ref": {
                "type": "number",
                "description": "Reference velocity [m/s] for pressure_coeff.",
            },
            "p_ref": {
                "type": "number",
                "description": "Reference pressure [Pa] for pressure_coeff. Default: min(p).",
            },
            # shared field name overrides
            "field": {
                "type": "string",
                "description": (
                    "Field to operate on (default depends on filter: "
                    "'U' for slice/streamline, 'p' for gradient_p, etc.)."
                ),
            },
            "velocity_field": {
                "type": "string",
                "description": "Velocity field name (default 'U').",
                "default": "U",
            },
            "pressure_field": {
                "type": "string",
                "description": "Pressure field name (default 'p').",
                "default": "p",
            },
        },
    },
)


def _filter_sync(a: dict) -> dict:
    mesh = _build_mesh_from_args(a)
    if mesh is None:
        return {"ok": False, "error": "points and cells are required", "code": "BAD_ARGS"}

    ftype = a.get("filter", "")
    pp = PostProcessor()

    if ftype == "slice":
        normal = a.get("normal")
        origin = a.get("origin")
        if normal is None or origin is None:
            return {"ok": False, "error": "normal and origin required for slice", "code": "BAD_ARGS"}
        field = a.get("field", "U")
        tol = a.get("tolerance")
        result = pp.slice_plane(mesh, tuple(normal), tuple(origin),
                                field=field, tolerance=tol)
        result["ok"] = True
        return result

    if ftype == "contour":
        field = a.get("field", "p")
        iso_value = a.get("iso_value")
        if iso_value is None:
            return {"ok": False, "error": "iso_value required for contour", "code": "BAD_ARGS"}
        result = pp.contour(mesh, field, float(iso_value))
        if "error" in result:
            result["ok"] = False
            return result
        result["ok"] = True
        return result

    if ftype == "streamline":
        seeds = a.get("seed_points")
        if not seeds:
            return {"ok": False, "error": "seed_points required for streamline", "code": "BAD_ARGS"}
        result = pp.streamline(
            mesh,
            seeds,
            velocity_field=a.get("velocity_field", "U"),
            max_steps=int(a.get("max_steps", 500)),
            step_size=a.get("step_size"),
            direction=a.get("direction", "forward"),
        )
        if "error" in result:
            result["ok"] = False
            return result
        result["ok"] = True
        return result

    if ftype == "integral":
        field = a.get("field", "U")
        op = a.get("operation", "volume_average")
        cell_vols = a.get("cell_volumes")
        vols_arr = np.array(cell_vols, dtype=float) if cell_vols else None
        result = pp.integral(mesh, field, operation=op, cell_volumes=vols_arr)
        if "error" in result:
            result["ok"] = False
            return result
        result["ok"] = True
        return result

    if ftype == "probe":
        probe_pts = a.get("probe_points")
        if not probe_pts:
            return {"ok": False, "error": "probe_points required for probe", "code": "BAD_ARGS"}
        fields = a.get("fields") or None
        result = pp.probe(mesh, probe_pts, fields=fields)
        result["ok"] = True
        return result

    if ftype == "derived":
        quantity = a.get("quantity")
        if not quantity:
            return {"ok": False, "error": "quantity required for derived", "code": "BAD_ARGS"}
        result = pp.derived(
            mesh,
            quantity,
            velocity_field=a.get("velocity_field", "U"),
            pressure_field=a.get("pressure_field", "p"),
            rho=float(a.get("rho", 1.225)),
            U_ref=a.get("U_ref"),
            p_ref=a.get("p_ref"),
        )
        if "error" in result:
            result["ok"] = False
            return result
        result["ok"] = True
        return result

    return {"ok": False, "error": f"unknown filter '{ftype}'", "code": "BAD_ARGS"}


@register(_filter_spec)
async def cfd_postprocess_filter(ctx: ProjectCtx, args: bytes) -> str:
    import asyncio
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    ftype = a.get("filter")
    if not ftype:
        return err_payload("filter is required", "BAD_ARGS")
    if not a.get("points") or not a.get("cells"):
        return err_payload("points and cells are required", "BAD_ARGS")
    result = await asyncio.to_thread(_filter_sync, a)
    if not result.get("ok"):
        return err_payload(result.get("error", "unknown"), result.get("code", "ERROR"))
    return ok_payload(result)
