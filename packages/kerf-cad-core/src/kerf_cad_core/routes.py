"""
kerf-cad-core HTTP routes.

POST /run-quad-remesh
---------------------
Run Instant Meshes quad remeshing on a provided OBJ mesh.

Body (JSON):
    {
        "obj_b64":            str,   # base64-encoded OBJ source
        "target_vertex_count": int,  # default 5000
        "smoothness_iters":   int,   # default 2
        "align_to_boundary":  bool,  # default true
    }

Returns (JSON):
    {
        "vertices":  [[x, y, z], ...],
        "quads":     [[a, b, c, d], ...],
        "triangles": [[a, b, c], ...],
        "stats":     { vertex_count, quad_count, tri_count, elapsed_s, ... },
    }

When the ``instant-meshes`` binary is absent the route returns HTTP 503 with
a user-friendly message and an install hint — the frontend QuadMeshView
surfaces this as a banner rather than a hard error so the user knows how to
fix it.
"""

from __future__ import annotations

import base64
import os
import tempfile

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

router = APIRouter()


class QuadRemeshRequest(BaseModel):
    obj_b64: str = Field(
        default="",
        description="Base64-encoded OBJ file content to remesh.",
    )
    target_vertex_count: int = Field(
        default=5000,
        ge=1,
        description="Approximate number of vertices in the output mesh.",
    )
    smoothness_iters: int = Field(
        default=2,
        ge=0,
        le=6,
        description="Instant Meshes smoothing iterations (0–6).",
    )
    align_to_boundary: bool = Field(
        default=True,
        description="Align edge loops to sharp boundary curves.",
    )


@router.post("/run-quad-remesh")
async def run_quad_remesh_route(req: QuadRemeshRequest) -> dict:
    """
    Run Instant Meshes quad remeshing on a provided OBJ mesh.

    Returns structured mesh data (vertices, quads, triangles, stats).
    Returns HTTP 503 with a friendly message when the binary is missing.
    """
    from kerf_cad_core.instant_meshes_runner import (
        InstantMeshesNotInstalledError,
        run_instant_meshes,
    )

    # Decode the input OBJ.
    try:
        obj_bytes = base64.b64decode(req.obj_b64) if req.obj_b64 else b""
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"obj_b64 is not valid base64: {exc}")

    if not obj_bytes:
        raise HTTPException(status_code=400, detail="obj_b64 must be a non-empty base64 OBJ string")

    with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as fh:
        fh.write(obj_bytes)
        tmp_path = fh.name

    try:
        result = run_instant_meshes(
            tmp_path,
            target_verts=req.target_vertex_count,
            smoothness=req.smoothness_iters,
            align_to_boundary=req.align_to_boundary,
        )
    except InstantMeshesNotInstalledError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "instant-meshes binary not found on PATH. "
                "Install Instant Meshes and ensure the 'instant-meshes' command "
                "is accessible: https://github.com/wjakob/instant-meshes/releases"
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return result
