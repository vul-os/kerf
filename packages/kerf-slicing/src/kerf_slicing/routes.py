"""
3D-print slicing route.

POST /run-print-slice
Body:  { "stl_path": "<abs-path>", "settings": { ... } }
Returns:
  {
    "gcode": "<full G-code string>",
    "layer_count": <int>,
    "print_time_s": <int | null>,
    "filament_mm": <float | null>,
    "gcode_bytes": <int>,
    "warnings": ["..."]
  }
  or on error:
  { "gcode": null, "warnings": ["<message>"], "error": "<message>" }

The route never crashes even when CuraEngine is not installed — it returns a
descriptive error payload instead so the frontend can surface a helpful message.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/run-print-slice")
async def run_print_slice_route(req: dict) -> dict:
    """Slice an STL file to G-code via CuraEngine subprocess."""
    stl_path = req.get("stl_path", "")
    settings = req.get("settings") or {}

    if not stl_path or not isinstance(stl_path, str):
        return {
            "gcode": None,
            "layer_count": 0,
            "print_time_s": None,
            "filament_mm": None,
            "gcode_bytes": 0,
            "warnings": ["'stl_path' must be a non-empty string"],
            "error": "BAD_ARGS",
        }

    from kerf_slicing.cura_runner import (
        CuraEngineError,
        CuraEngineNotInstalledError,
        run_cura_slice,
    )

    try:
        result = run_cura_slice(stl_path, settings)
    except CuraEngineNotInstalledError as exc:
        return {
            "gcode": None,
            "layer_count": 0,
            "print_time_s": None,
            "filament_mm": None,
            "gcode_bytes": 0,
            "warnings": [str(exc)],
            "error": "CURA_NOT_INSTALLED",
        }
    except FileNotFoundError:
        return {
            "gcode": None,
            "layer_count": 0,
            "print_time_s": None,
            "filament_mm": None,
            "gcode_bytes": 0,
            "warnings": [f"STL file not found: {stl_path}"],
            "error": "STL_NOT_FOUND",
        }
    except CuraEngineError as exc:
        return {
            "gcode": None,
            "layer_count": 0,
            "print_time_s": None,
            "filament_mm": None,
            "gcode_bytes": 0,
            "warnings": [str(exc)],
            "error": "CURA_ERROR",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "gcode": None,
            "layer_count": 0,
            "print_time_s": None,
            "filament_mm": None,
            "gcode_bytes": 0,
            "warnings": [f"Unexpected error: {exc}"],
            "error": "ERROR",
        }

    return {
        "gcode": result.gcode,
        "layer_count": result.layer_count,
        "print_time_s": result.print_time_s,
        "filament_mm": result.filament_mm,
        "gcode_bytes": result.gcode_bytes,
        "warnings": result.warnings,
        "error": None,
    }
