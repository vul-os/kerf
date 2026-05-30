"""
subd_export_usd.py
==================
Export / import SubD control cages in Pixar USD (.usda ASCII) format.

This module targets **USD Mesh prim** format consumed by Pixar HdStorm,
Houdini, and Maya — **not** the OpenSubdiv-native OBJ/JSON/binary formats
implemented in ``subd_opensubdiv_export.py``.

USD SubD conventions (catmullClark scheme)
------------------------------------------
- ``subdivisionScheme = "catmullClark"``
- Cage stored as ``UsdGeom.Mesh`` prim.
- Points array: ``float3[] points``
- Topology: ``int[] faceVertexCounts`` + ``int[] faceVertexIndices``
- Boundary interpolation: ``uniform token subdivisionScheme = "catmullClark"``
  and ``uniform token interpolateBoundary = "edgeAndCorner"`` (USD spec default
  for production rendering).
- Creased edges: ``int[] creaseIndices`` + ``int[] creaseLengths`` +
  ``float[] creaseSharpnesses``
- Sharp corners (vertex sharpness): ``int[] cornerIndices`` +
  ``float[] cornerSharpnesses``

References
----------
- USD Mesh schema: https://openusd.org/release/api/class_usd_geom_mesh.html
- OpenSubdiv tutorial §3 (Pixar, 2023) — crease conventions.
- USDA grammar: https://openusd.org/release/api/_usd__page__datatypes.html

Limitations
-----------
- **USDA (ASCII) only** — USDC (binary crate format) is out of scope; this
  module produces human-readable ``.usda`` text only.
- No Pixar ``usd-core`` Python package is required; the emitter is pure-Python.
- Sharpness values are clamped to [0, 10] per OpenSubdiv 3.5 convention
  (values above 10 are treated as "infinite crease" by OpenSubdiv / HdStorm).

Public API
----------
``export_subd_to_usda(cage) -> str``
    Return USDA ASCII text for the cage.

``write_subd_usda(cage, path)``
    Write USDA to *path* (convenience wrapper).

``parse_usda_subd(text) -> SubDMesh``
    Parse USDA text produced by this module and return a :class:`SubDMesh`.
    Suitable for round-trip oracle tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kerf_cad_core.geom.subd import SubDMesh

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_USDA_HEADER = '#usda 1.0'
_SHARPNESS_MAX: float = 10.0
_SHARPNESS_MIN: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cage_to_subd_mesh(cage: Any) -> SubDMesh:
    """Accept SubDMesh, SubDCage, or dict with 'vertices'+'faces'."""
    if isinstance(cage, SubDMesh):
        return cage
    if hasattr(cage, 'to_subd_mesh'):
        return cage.to_subd_mesh()
    if isinstance(cage, dict):
        verts = [[float(x) for x in v] for v in cage.get('vertices', [])]
        faces = [[int(i) for i in f] for f in cage.get('faces', [])]
        mesh = SubDMesh(vertices=verts, faces=faces)
        for k, v in cage.get('creases', {}).items():
            if isinstance(k, (list, tuple)) and len(k) == 2:
                mesh.set_crease(int(k[0]), int(k[1]), float(v))
        return mesh
    # duck-type
    verts = [[float(x) for x in v] for v in getattr(cage, 'vertices', [])]
    faces = [[int(i) for i in f] for f in getattr(cage, 'faces', [])]
    mesh = SubDMesh(vertices=verts, faces=faces)
    for k, v in getattr(cage, 'creases', {}).items():
        mesh.creases[k] = float(v)
    return mesh


def _fmt_float(f: float) -> str:
    """Format float for USDA: 6 significant figures, no trailing zeros."""
    s = f'{f:.6g}'
    return s


def _fmt_vec3_array(verts: List[List[float]]) -> str:
    """Render float3[] array body for USDA, one vertex per line."""
    parts = []
    for v in verts:
        x, y, z = float(v[0]), float(v[1]), float(v[2])
        parts.append(f'            ({_fmt_float(x)}, {_fmt_float(y)}, {_fmt_float(z)})')
    return '[\n' + ',\n'.join(parts) + '\n        ]'


def _fmt_int_array(ints: List[int], indent: int = 8) -> str:
    """Render int[] array body for USDA."""
    pad = ' ' * indent
    inner = ', '.join(str(i) for i in ints)
    return f'[{inner}]'


def _fmt_float_array(floats: List[float], indent: int = 8) -> str:
    """Render float[] array body for USDA."""
    inner = ', '.join(_fmt_float(f) for f in floats)
    return f'[{inner}]'


# ---------------------------------------------------------------------------
# Public: export_subd_to_usda
# ---------------------------------------------------------------------------

def export_subd_to_usda(cage: Any, *, prim_path: str = '/SubDMesh') -> str:
    """Emit a USDA ASCII string for *cage*.

    Parameters
    ----------
    cage : SubDMesh | SubDCage | dict
        The control cage.
    prim_path : str
        USD prim path for the Mesh prim (default ``/SubDMesh``).

    Returns
    -------
    str
        USDA ASCII text.  Always valid USDA 1.0 if the input cage is valid.

    Notes
    -----
    Only USDA (ASCII) is produced.  USDC binary is out of scope.
    Sharpness values are clamped to [0, 10].
    ``interpolateBoundary = "edgeAndCorner"`` is set per USD production default.
    """
    mesh = _cage_to_subd_mesh(cage)
    n_verts = len(mesh.vertices)
    n_faces = len(mesh.faces)

    # Build topology arrays
    face_vertex_counts: List[int] = [len(f) for f in mesh.faces]
    face_vertex_indices: List[int] = []
    for f in mesh.faces:
        face_vertex_indices.extend(f)

    # Build crease arrays per USD Mesh schema:
    #   creaseIndices   : flat list of vertex index pairs [v0a, v0b, v1a, v1b, ...]
    #   creaseLengths   : number of vertices per chain (2 for single edges)
    #   creaseSharpnesses: one float per chain
    crease_indices: List[int] = []
    crease_lengths: List[int] = []
    crease_sharpnesses: List[float] = []
    for (a, b), s in sorted(mesh.creases.items()):
        if s > _SHARPNESS_MIN:
            clamped = min(float(s), _SHARPNESS_MAX)
            crease_indices.extend([int(a), int(b)])
            crease_lengths.append(2)
            crease_sharpnesses.append(clamped)

    # Corner (vertex) sharpness arrays — USD schema uses cornerIndices +
    # cornerSharpnesses.  SubDMesh does not have per-vertex sharpness yet;
    # we emit empty arrays so the prim is always schema-valid.
    corner_indices: List[int] = []
    corner_sharpnesses: List[float] = []

    lines: List[str] = [
        '#usda 1.0',
        '(',
        '    doc = "SubD cage exported by Kerf CAD Core — USDA ASCII only, no USDC"',
        '    metersPerUnit = 0.001',
        '    upAxis = "Y"',
        ')',
        '',
        f'def Mesh "{_prim_name(prim_path)}"',
        '{',
        '    uniform token subdivisionScheme = "catmullClark"',
        '    uniform token interpolateBoundary = "edgeAndCorner"',
        '',
        f'    int[] faceVertexCounts = {_fmt_int_array(face_vertex_counts)}',
        f'    int[] faceVertexIndices = {_fmt_int_array(face_vertex_indices)}',
        '',
        f'    point3f[] points = {_fmt_vec3_array(mesh.vertices)}',
    ]

    if crease_indices:
        lines += [
            '',
            f'    int[] creaseIndices = {_fmt_int_array(crease_indices)}',
            f'    int[] creaseLengths = {_fmt_int_array(crease_lengths)}',
            f'    float[] creaseSharpnesses = {_fmt_float_array(crease_sharpnesses)}',
        ]

    if corner_indices:
        lines += [
            '',
            f'    int[] cornerIndices = {_fmt_int_array(corner_indices)}',
            f'    float[] cornerSharpnesses = {_fmt_float_array(corner_sharpnesses)}',
        ]

    lines += [
        '}',
        '',
    ]

    return '\n'.join(lines)


def _prim_name(prim_path: str) -> str:
    """Extract the last component of a prim path for 'def Mesh "<name>"'."""
    return prim_path.rstrip('/').rsplit('/', 1)[-1] or 'SubDMesh'


# ---------------------------------------------------------------------------
# Public: write_subd_usda
# ---------------------------------------------------------------------------

def write_subd_usda(cage: Any, path: str, *, prim_path: str = '/SubDMesh') -> None:
    """Write USDA to *path*.

    Parameters
    ----------
    cage : SubDMesh | SubDCage | dict
        The control cage.
    path : str
        Output file path.  Should use a ``.usda`` extension.
    prim_path : str
        USD prim path (default ``/SubDMesh``).
    """
    text = export_subd_to_usda(cage, prim_path=prim_path)
    Path(path).write_text(text, encoding='utf-8')


# ---------------------------------------------------------------------------
# Public: parse_usda_subd
# ---------------------------------------------------------------------------

def parse_usda_subd(text: str) -> SubDMesh:
    """Parse USDA text produced by :func:`export_subd_to_usda`.

    This is a lightweight parser for the specific USDA dialect emitted by this
    module.  It is intentionally narrow — it only handles the prim structure
    emitted here and is **not** a general-purpose USDA parser.

    Parameters
    ----------
    text : str
        USDA ASCII text.

    Returns
    -------
    SubDMesh
        Reconstructed control cage.  Returns an empty :class:`SubDMesh` if
        parsing fails.
    """
    try:
        return _parse_usda(text)
    except Exception:
        return SubDMesh()


def _parse_usda(text: str) -> SubDMesh:
    """Internal parser — may raise on malformed input."""
    # Extract faceVertexCounts
    fvc_match = re.search(
        r'int\[\]\s+faceVertexCounts\s*=\s*\[([^\]]*)\]', text, re.DOTALL
    )
    fvc: List[int] = []
    if fvc_match:
        fvc = [int(x.strip()) for x in fvc_match.group(1).split(',') if x.strip()]

    # Extract faceVertexIndices
    fvi_match = re.search(
        r'int\[\]\s+faceVertexIndices\s*=\s*\[([^\]]*)\]', text, re.DOTALL
    )
    fvi: List[int] = []
    if fvi_match:
        fvi = [int(x.strip()) for x in fvi_match.group(1).split(',') if x.strip()]

    # Rebuild faces from counts
    faces: List[List[int]] = []
    cursor = 0
    for count in fvc:
        faces.append(fvi[cursor:cursor + count])
        cursor += count

    # Extract points — float3[] or point3f[]
    pts_match = re.search(
        r'(?:float3|point3f)\[\]\s+points\s*=\s*\[(.*?)\]',
        text,
        re.DOTALL,
    )
    verts: List[List[float]] = []
    if pts_match:
        # Each vertex is "(x, y, z)"
        for m in re.finditer(r'\(\s*([^)]+)\s*\)', pts_match.group(1)):
            nums = [float(v.strip()) for v in m.group(1).split(',')]
            verts.append(nums)

    # Extract creases
    ci_match = re.search(r'int\[\]\s+creaseIndices\s*=\s*\[([^\]]*)\]', text)
    cl_match = re.search(r'int\[\]\s+creaseLengths\s*=\s*\[([^\]]*)\]', text)
    cs_match = re.search(r'float\[\]\s+creaseSharpnesses\s*=\s*\[([^\]]*)\]', text)

    mesh = SubDMesh(vertices=verts, faces=faces)

    if ci_match and cl_match and cs_match:
        ci = [int(x.strip()) for x in ci_match.group(1).split(',') if x.strip()]
        cl = [int(x.strip()) for x in cl_match.group(1).split(',') if x.strip()]
        cs = [float(x.strip()) for x in cs_match.group(1).split(',') if x.strip()]
        # Rebuild per-edge creases from chains
        offset = 0
        for length, sharpness in zip(cl, cs):
            chain = ci[offset:offset + length]
            # Each adjacent pair in the chain forms a crease edge
            for i in range(len(chain) - 1):
                mesh.set_crease(chain[i], chain[i + 1], sharpness)
            offset += length

    return mesh


# ---------------------------------------------------------------------------
# LLM tool registration (gated)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    import tempfile as _tempfile
    import os as _os
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    _subd_export_to_usd_spec = ToolSpec(
        name='subd_export_to_usd',
        description=(
            'Export a SubD control cage to Pixar USD Mesh format (.usda ASCII).\n'
            '\n'
            'Produces a valid USDA 1.0 file with subdivisionScheme="catmullClark",\n'
            'interpolateBoundary="edgeAndCorner" (USD production default), and\n'
            'creased edges encoded via creaseIndices + creaseLengths + creaseSharpnesses\n'
            'per the USD Mesh schema.\n'
            '\n'
            'DISCLAIMER: USDA ASCII only — USDC (binary crate) is out of scope.\n'
            'Compatible with Pixar HdStorm, Houdini, and Maya USD workflows.\n'
            'NOT certified by Pixar.\n'
            '\n'
            'Returns:\n'
            '  ok           : bool\n'
            '  path         : str  — absolute path of the written .usda file\n'
            '  usda_text    : str  — full USDA ASCII content\n'
            '  n_vertices   : int\n'
            '  n_faces      : int\n'
            '  n_creases    : int\n'
            '\n'
            'Errors: {ok: false, reason}.  Never raises.'
        ),
        input_schema={
            'type': 'object',
            'properties': {
                'vertices': {
                    'type': 'array',
                    'description': 'Control-mesh vertices [[x, y, z], ...].',
                    'items': {'type': 'array', 'items': {'type': 'number'}},
                },
                'faces': {
                    'type': 'array',
                    'description': 'Face vertex-index lists [[i, j, k, l], ...].',
                    'items': {'type': 'array', 'items': {'type': 'integer'}},
                },
                'creases': {
                    'type': 'array',
                    'description': 'Crease list [{v1, v2, value}, ...].',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'v1': {'type': 'integer'},
                            'v2': {'type': 'integer'},
                            'value': {'type': 'number'},
                        },
                        'required': ['v1', 'v2', 'value'],
                    },
                },
                'path': {
                    'type': 'string',
                    'description': (
                        'Output file path (should end in .usda).  '
                        'If omitted, a temp file is created.'
                    ),
                },
                'prim_path': {
                    'type': 'string',
                    'description': 'USD prim path (default "/SubDMesh").',
                },
            },
            'required': ['vertices', 'faces'],
        },
    )

    @register(_subd_export_to_usd_spec)
    async def run_subd_export_to_usd(ctx: 'ProjectCtx', args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f'invalid args: {exc}', 'BAD_ARGS')

        raw_verts = a.get('vertices', [])
        raw_faces = a.get('faces', [])
        raw_creases = a.get('creases', [])
        out_path = a.get('path', '').strip()
        prim_path = a.get('prim_path', '/SubDMesh').strip() or '/SubDMesh'

        if not raw_verts:
            return err_payload('vertices is required', 'BAD_ARGS')
        if not raw_faces:
            return err_payload('faces is required', 'BAD_ARGS')

        try:
            mesh = SubDMesh(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f'invalid mesh: {exc}', 'BAD_ARGS')

        for ce in raw_creases:
            try:
                mesh.set_crease(int(ce['v1']), int(ce['v2']), float(ce['value']))
            except Exception:
                pass

        if not out_path:
            tmp = _tempfile.NamedTemporaryFile(
                suffix='.usda', delete=False, prefix='kerf_usd_'
            )
            out_path = tmp.name
            tmp.close()

        try:
            usda_text = export_subd_to_usda(mesh, prim_path=prim_path)
            Path(out_path).write_text(usda_text, encoding='utf-8')
        except Exception as exc:
            return err_payload(f'export failed: {exc}', 'EXPORT_ERROR')

        if not _os.path.exists(out_path):
            return err_payload('export produced no output file', 'EXPORT_ERROR')

        n_creases = sum(1 for s in mesh.creases.values() if s > 0)
        return ok_payload({
            'ok': True,
            'path': out_path,
            'usda_text': usda_text,
            'n_vertices': mesh.num_vertices,
            'n_faces': mesh.num_faces,
            'n_creases': n_creases,
        })
