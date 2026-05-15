"""
instant_meshes_runner — subprocess wrapper for the Instant Meshes binary.

Public entry point
------------------
    run_instant_meshes(
        obj_path,
        target_verts,
        smoothness,
        align_to_boundary,
    ) -> dict

The return dict contains:
    {
        "vertices":   [[x, y, z], ...],   # float triples
        "quads":      [[a, b, c, d], ...], # 0-based face indices (quad faces)
        "triangles":  [[a, b, c], ...],    # 0-based face indices (tri faces)
        "stats": {
            "vertex_count":   int,
            "quad_count":     int,
            "tri_count":      int,
            "elapsed_s":      float,
            "target_verts":   int,
            "smoothness":     int,
            "align_boundary": bool,
        },
    }

CLI targeted
------------
Instant Meshes 1.0.x (https://github.com/wjakob/instant-meshes).
The binary is installed separately as ``instant-meshes`` on PATH.

    instant-meshes input.obj -o output.obj -v <target> -s <smooth> --boundaries

Raised exceptions
-----------------
InstantMeshesNotInstalledError
    When the ``instant-meshes`` binary cannot be found on PATH.

RuntimeError
    When the binary exits with a non-zero status or the output OBJ cannot
    be parsed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Optional


BINARY_NAME = "instant-meshes"
TIMEOUT_SECONDS = 30


class InstantMeshesNotInstalledError(RuntimeError):
    """Raised when the ``instant-meshes`` binary is not on PATH."""


# ---------------------------------------------------------------------------
# OBJ parser helpers
# ---------------------------------------------------------------------------

def _parse_obj(text: str) -> tuple[list, list, list]:
    """
    Parse a subset of the OBJ format produced by Instant Meshes.

    Returns (vertices, quads, tris) where:
        vertices  = [[x, y, z], ...]
        quads     = [[a, b, c, d], ...]  (0-based indices)
        tris      = [[a, b, c], ...]     (0-based indices)

    Instant Meshes always emits ``f`` lines with 3 or 4 vertex references.
    Texture / normal indices (``v/vt/vn``) are handled by taking the first
    slash-separated component only.
    """
    vertices: list = []
    quads: list = []
    tris: list = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
                except ValueError:
                    pass

        elif line.startswith("f "):
            parts = line.split()[1:]  # drop the leading "f"
            # Strip texture/normal indices: "3/1/2" -> "3"
            indices = []
            for p in parts:
                idx_str = p.split("/")[0]
                try:
                    # OBJ uses 1-based indexing
                    indices.append(int(idx_str) - 1)
                except ValueError:
                    pass

            if len(indices) == 4:
                quads.append(indices)
            elif len(indices) == 3:
                tris.append(indices)
            # Ignore n-gons with n > 4 (shouldn't appear in IM output)

    return vertices, quads, tris


# ---------------------------------------------------------------------------
# CLI builder
# ---------------------------------------------------------------------------

def _build_cli(
    input_path: str,
    output_path: str,
    target_verts: int,
    smoothness: int,
    align_to_boundary: bool,
) -> list:
    """Build the Instant Meshes command line."""
    cmd = [
        BINARY_NAME,
        input_path,
        "-o", output_path,
        "-v", str(int(target_verts)),
        "-s", str(int(smoothness)),
    ]
    if align_to_boundary:
        cmd.append("--boundaries")
    return cmd


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_instant_meshes(
    obj_path: str,
    target_verts: int = 5000,
    smoothness: int = 2,
    align_to_boundary: bool = True,
) -> dict:
    """
    Run Instant Meshes on *obj_path* and return structured mesh data.

    Parameters
    ----------
    obj_path:
        Absolute path to the input OBJ file.
    target_verts:
        Target vertex count for the output mesh.  Instant Meshes treats
        this as a hint; actual count may differ by ±20%.
    smoothness:
        Number of smoothing iterations (``-s`` flag).  Range 0–6.
        Higher values produce more regular faces but may lose fine details.
    align_to_boundary:
        When True, passes ``--boundaries`` so edge loops snap to boundary
        curves in the source mesh.

    Returns
    -------
    dict with keys ``vertices``, ``quads``, ``triangles``, and ``stats``.

    Raises
    ------
    InstantMeshesNotInstalledError
        When ``instant-meshes`` is absent from PATH.
    RuntimeError
        On non-zero exit code or parse failure.
    """
    if shutil.which(BINARY_NAME) is None:
        raise InstantMeshesNotInstalledError(
            f"'{BINARY_NAME}' binary not found on PATH. "
            "Install Instant Meshes and ensure the binary is accessible. "
            "See https://github.com/wjakob/instant-meshes for pre-built "
            "releases or build from source (MIT license)."
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "remeshed.obj")
        cmd = _build_cli(obj_path, output_path, target_verts, smoothness, align_to_boundary)

        t0 = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            raise InstantMeshesNotInstalledError(
                f"'{BINARY_NAME}' binary not found on PATH."
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Instant Meshes timed out after {TIMEOUT_SECONDS}s. "
                "Consider reducing target_verts or simplifying the input mesh."
            )
        elapsed = time.time() - t0

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(
                f"Instant Meshes exited with code {result.returncode}. "
                f"stderr: {stderr or '(empty)'}"
            )

        if not os.path.exists(output_path):
            raise RuntimeError(
                "Instant Meshes completed but produced no output file. "
                f"stdout: {(result.stdout or '').strip()[:500]}"
            )

        with open(output_path, "r", encoding="utf-8", errors="replace") as fh:
            obj_text = fh.read()

    vertices, quads, tris = _parse_obj(obj_text)

    return {
        "vertices":  vertices,
        "quads":     quads,
        "triangles": tris,
        "stats": {
            "vertex_count":   len(vertices),
            "quad_count":     len(quads),
            "tri_count":      len(tris),
            "elapsed_s":      round(elapsed, 3),
            "target_verts":   target_verts,
            "smoothness":     smoothness,
            "align_boundary": align_to_boundary,
        },
    }
