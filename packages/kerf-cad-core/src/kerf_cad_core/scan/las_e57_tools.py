"""
kerf_cad_core.scan.las_e57_tools — LLM tools for LAS / E57 point cloud ingestion.

Registers two tools:

  scan_load_las   — Read a LAS 1.2/1.4 binary file (bytes-as-base64 or path)
                    and return point count, bbox, intensity stats.
  scan_load_e57   — Read an ASTM E2807 E57 file and return the same summary.

Both tools accept either a ``path`` string (server-side file) or a
``data_base64`` string (client-uploaded raw bytes, base64-encoded).

Output schema (same for both):
  {
    ok: true,
    n_points: int,
    source_format: "las" | "e57",
    bbox: {
      x_min, x_max, y_min, y_max, z_min, z_max,
      extent_x, extent_y, extent_z
    },
    intensity: {
      present: bool,
      min: float | null,
      max: float | null,
      mean: float | null
    },
    classification: {
      present: bool,
      unique_classes: [int, ...] | null   # max 32 classes listed
    }
  }

Errors returned as {ok: false, reason: "..."} — tools never raise.

Wave 9A: LAS / E57 point cloud readers

Author: imranparuk
"""
from __future__ import annotations

import base64
import json

import numpy as np

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _bbox_payload(bbox: tuple) -> dict:
    (x_min, y_min, z_min), (x_max, y_max, z_max) = bbox
    return {
        "x_min": x_min, "x_max": x_max,
        "y_min": y_min, "y_max": y_max,
        "z_min": z_min, "z_max": z_max,
        "extent_x": x_max - x_min,
        "extent_y": y_max - y_min,
        "extent_z": z_max - z_min,
    }


def _intensity_payload(arr: "np.ndarray | None") -> dict:
    if arr is None or len(arr) == 0:
        return {"present": False, "min": None, "max": None, "mean": None}
    return {
        "present": True,
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
    }


def _classification_payload(arr: "np.ndarray | None") -> dict:
    if arr is None or len(arr) == 0:
        return {"present": False, "unique_classes": None}
    unique = sorted(int(v) for v in np.unique(arr)[:32])
    return {"present": True, "unique_classes": unique}


def _cloud_to_payload(cloud) -> dict:
    """Convert a PointCloud to a JSON-serialisable result dict."""
    return {
        "ok": True,
        "n_points": cloud.n_points,
        "source_format": cloud.source_format,
        "bbox": _bbox_payload(cloud.bbox),
        "intensity": _intensity_payload(cloud.intensity),
        "classification": _classification_payload(cloud.classification),
    }


# ---------------------------------------------------------------------------
# Tool: scan_load_las
# ---------------------------------------------------------------------------

_scan_load_las_spec = ToolSpec(
    name="scan_load_las",
    description=(
        "Read a LAS 1.2 / 1.4 binary point cloud file and return summary statistics.\n"
        "\n"
        "Accepts either:\n"
        "  • path: server-side file system path to a .las file.\n"
        "  • data_base64: base64-encoded raw .las file bytes (max ~128 MB before encoding).\n"
        "\n"
        "Decodes XYZ coordinates using scale factors and offsets from the LAS header,\n"
        "returning world coordinates in whatever units the file uses (usually metres).\n"
        "\n"
        "Supported point record formats: 0, 1, 2, 3, 6, 7 (XYZ int32 + intensity + class).\n"
        "LASzip (.laz) compressed files are NOT supported.\n"
        "\n"
        "Output: {\n"
        "  ok, n_points, source_format: 'las',\n"
        "  bbox: {x_min, x_max, y_min, y_max, z_min, z_max, extent_x, extent_y, extent_z},\n"
        "  intensity: {present, min, max, mean},\n"
        "  classification: {present, unique_classes: [int,...]}\n"
        "}\n"
        "\n"
        "Civil + AVEVA E3D integration: use this tool to ingest terrestrial scanner\n"
        "exports before running scan_fit_plane / scan_fit_cylinder on the XYZ data.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Server-side file system path to the .las file.",
            },
            "data_base64": {
                "type": "string",
                "description": (
                    "Base64-encoded raw bytes of a .las file "
                    "(use when the file is uploaded directly)."
                ),
            },
        },
        "oneOf": [
            {"required": ["path"]},
            {"required": ["data_base64"]},
        ],
    },
)


@register(_scan_load_las_spec, write=False)
async def run_scan_load_las(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # Late import to avoid circular at module load time
    from kerf_cad_core.scan.las_reader import read_las, read_las_bytes

    try:
        if "path" in a:
            cloud = read_las(str(a["path"]))
        elif "data_base64" in a:
            raw = base64.b64decode(a["data_base64"])
            cloud = read_las_bytes(raw)
        else:
            return err_payload("provide 'path' or 'data_base64'", "BAD_ARGS")
    except (ValueError, OSError) as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload(_cloud_to_payload(cloud))


# ---------------------------------------------------------------------------
# Tool: scan_load_e57
# ---------------------------------------------------------------------------

_scan_load_e57_spec = ToolSpec(
    name="scan_load_e57",
    description=(
        "Read an ASTM E2807-11 (.e57) point cloud file and return summary statistics.\n"
        "\n"
        "Accepts either:\n"
        "  • path: server-side file system path to a .e57 file.\n"
        "  • data_base64: base64-encoded raw .e57 file bytes.\n"
        "\n"
        "Decodes the XML descriptor inside the E57 container to find Data3D scan\n"
        "structures, then reads the associated CompressedVector binary blocks\n"
        "(uncompressed / flat float32 XYZ and uint16 intensity only; bitPack /\n"
        "zlib-compressed variants are not supported in this reader).\n"
        "\n"
        "Multiple scans within the file are concatenated into a single PointCloud.\n"
        "\n"
        "Output: {\n"
        "  ok, n_points, source_format: 'e57',\n"
        "  bbox: {x_min, x_max, y_min, y_max, z_min, z_max, extent_x, extent_y, extent_z},\n"
        "  intensity: {present, min, max, mean},\n"
        "  classification: {present, unique_classes: null}\n"
        "}\n"
        "\n"
        "Civil + AVEVA E3D integration: use this tool to ingest scanner exports\n"
        "before running scan_fit_plane / scan_fit_cylinder on the XYZ data.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Server-side file system path to the .e57 file.",
            },
            "data_base64": {
                "type": "string",
                "description": (
                    "Base64-encoded raw bytes of a .e57 file "
                    "(use when the file is uploaded directly)."
                ),
            },
        },
        "oneOf": [
            {"required": ["path"]},
            {"required": ["data_base64"]},
        ],
    },
)


@register(_scan_load_e57_spec, write=False)
async def run_scan_load_e57(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    from kerf_cad_core.scan.e57_reader import read_e57, read_e57_bytes

    try:
        if "path" in a:
            cloud = read_e57(str(a["path"]))
        elif "data_base64" in a:
            raw = base64.b64decode(a["data_base64"])
            cloud = read_e57_bytes(raw)
        else:
            return err_payload("provide 'path' or 'data_base64'", "BAD_ARGS")
    except (ValueError, OSError) as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload(_cloud_to_payload(cloud))
