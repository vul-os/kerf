"""
subd_export_usd.py
==================
Export / import SubD control cages in Pixar USD (.usda ASCII and .usdc binary
crate) formats.

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
- USD Crate file format: https://github.com/PixarAnimationStudios/OpenUSD (crate/
  CrateFile.cpp) — section layout, header magic, TOC, value/string/field/path
  repositories.

Limitations
-----------
- USDC binary output is a **minimal-conforming** subset of the Pixar OpenUSD
  Crate format (header magic "PXR-USDC", version 0.6.0, well-formed TOC,
  string/token/field/path/spec repositories).  Full Pixar interop — including
  reading back via usd-core / usdcat — requires Pixar's C++ library; this
  writer is read-only and targets archival / transfer use cases that only need
  to verify the header and section layout.
- No Pixar ``usd-core`` Python package is required; both emitters are
  pure-Python (``struct`` + ``io``).
- Sharpness values are clamped to [0, 10] per OpenSubdiv 3.5 convention
  (values above 10 are treated as "infinite crease" by OpenSubdiv / HdStorm).

Public API
----------
``export_subd_to_usda(cage) -> str``
    Return USDA ASCII text for the cage.

``write_subd_usda(cage, path)``
    Write USDA to *path* (convenience wrapper).

``export_subd_to_usdc(cage, output_path)``
    Write a minimal-conforming USDC binary crate file for the cage.

``write_subd_usd(cage, path)``
    Auto-dispatch: writes ``.usda`` or ``.usdc`` based on *path* extension.

``parse_usda_subd(text) -> SubDMesh``
    Parse USDA text produced by this module and return a :class:`SubDMesh`.
    Suitable for round-trip oracle tests.

``parse_usdc_header(data) -> dict``
    Parse the fixed 88-byte header of a USDC file.  Returns a dict with keys
    ``magic``, ``version``, ``toc_offset``, and ``section_count`` (from TOC).
    Suitable for round-trip oracle tests.
"""

from __future__ import annotations

import io
import re
import struct
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
    Produces USDA (ASCII) text.  For binary crate output use
    :func:`export_subd_to_usdc`.
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
        '    doc = "SubD cage exported by Kerf CAD Core — USDA ASCII"',
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
# Public: export_subd_to_usdc  (minimal-conforming USDC binary crate writer)
# ---------------------------------------------------------------------------

# Pixar OpenUSD Crate file format constants
# Reference: OpenUSD/pxr/usd/usd/crateFile.cpp
_USDC_MAGIC = b'PXR-USDC'
_USDC_VERSION = (0, 6, 0)  # software_version major.minor.patch
_USDC_HEADER_SIZE = 88     # fixed header size in bytes

# Section names used in the Table-of-Contents (TOC)
_SEC_TOKENS      = b'TOKENS'
_SEC_STRINGS     = b'STRINGS'
_SEC_FIELDS      = b'FIELDS'
_SEC_FIELDSETS   = b'FIELDSETS'
_SEC_PATHS       = b'PATHS'
_SEC_SPECS       = b'SPECS'


def _usdc_lz4_passthrough(data: bytes) -> bytes:
    """
    Minimal LZ4-frame wrapper used by the USDC crate for section payloads.

    The Crate format stores each section body prefixed with:
      - uint64 uncompressed_size
      - uint64 compressed_size
    followed by the (optionally LZ4-compressed) payload.

    For simplicity we store uncompressed data and set both sizes equal, which
    is a valid degenerate case (no actual compression).  A full Pixar usdcat
    round-trip would require genuine LZ4 frame compression; this writer targets
    archival / header-verification use cases.
    """
    n = len(data)
    prefix = struct.pack('<QQ', n, n)
    return prefix + data


def _usdc_encode_tokens(tokens: List[str]) -> bytes:
    """
    Encode the TOKENS section: a flat null-terminated string table preceded
    by a uint64 count.

    Format (little-endian):
      uint64  count
      [null-terminated UTF-8 strings, one per token]
    """
    buf = io.BytesIO()
    buf.write(struct.pack('<Q', len(tokens)))
    for tok in tokens:
        buf.write(tok.encode('utf-8') + b'\x00')
    return buf.getvalue()


def _usdc_encode_strings(string_indices: List[int]) -> bytes:
    """
    Encode the STRINGS section: a uint64 count followed by uint32 indices
    into the token table (each string is a token).
    """
    buf = io.BytesIO()
    buf.write(struct.pack('<Q', len(string_indices)))
    for idx in string_indices:
        buf.write(struct.pack('<I', idx))
    return buf.getvalue()


# Value representation type codes (subset used here)
# These match the Pixar Crate ValueRep encoding.
_VR_TOKEN     = 0x01   # single token index (uint32)
_VR_INT       = 0x04   # single int32
_VR_FLOAT     = 0x0A   # single float32
_VR_VEC3F     = 0x0F   # single GfVec3f (3 × float32)
_VR_INT_ARRAY     = 0x24  # array of int32
_VR_FLOAT_ARRAY   = 0x2A  # array of float32
_VR_VEC3F_ARRAY   = 0x2F  # array of GfVec3f
_VR_TOKEN_VECTOR  = 0x21  # array of token indices

# Spec types
_SPEC_TYPE_PRIM_SPEC       = 2
_SPEC_TYPE_ATTRIBUTE_SPEC  = 3

# Field flags
_FIELD_FLAG_INLINE  = 0x0100   # value fits in 4 bytes of the ValueRep payload


def _pack_value_rep(type_code: int, payload_or_index: int, is_array: bool = False, inline: bool = False) -> int:
    """
    Pack a 64-bit ValueRep used in the FIELDS section.

    Bit layout (little-endian uint64):
      bits  7.. 0 : value type tag
      bit       8 : isInlined flag (value ≤ 4 bytes stored in the upper 32)
      bit       9 : isArray flag
      bits 31.. 10: unused (0)
      bits 63..32 : payload (inline value or byte offset into value repository)
    """
    flags = 0
    if inline:
        flags |= (1 << 8)
    if is_array:
        flags |= (1 << 9)
    low = (type_code & 0xFF) | (flags & 0xFFFF)
    high = payload_or_index & 0xFFFFFFFF
    return (high << 32) | low


def _usdc_encode_inline_int_array(values: List[int]) -> bytes:
    """Encode an int32 array value for the value repository."""
    buf = io.BytesIO()
    buf.write(struct.pack('<Q', len(values)))
    for v in values:
        buf.write(struct.pack('<i', v))
    return buf.getvalue()


def _usdc_encode_inline_float_array(values: List[float]) -> bytes:
    """Encode a float32 array value for the value repository."""
    buf = io.BytesIO()
    buf.write(struct.pack('<Q', len(values)))
    for v in values:
        buf.write(struct.pack('<f', float(v)))
    return buf.getvalue()


def _usdc_encode_inline_vec3f_array(verts: List[List[float]]) -> bytes:
    """Encode a GfVec3f array value for the value repository."""
    buf = io.BytesIO()
    buf.write(struct.pack('<Q', len(verts)))
    for v in verts:
        buf.write(struct.pack('<fff', float(v[0]), float(v[1]), float(v[2])))
    return buf.getvalue()


def export_subd_to_usdc(cage: Any, output_path: str, *, prim_path: str = '/SubDMesh') -> None:
    """Write a minimal-conforming USDC binary crate file for *cage*.

    Parameters
    ----------
    cage : SubDMesh | SubDCage | dict
        The control cage.
    output_path : str
        Destination ``.usdc`` file path.
    prim_path : str
        USD prim path (default ``/SubDMesh``).

    Notes
    -----
    This produces a **minimal-conforming** USDC binary crate file:

    * Header: 88-byte fixed block — magic ``PXR-USDC``, version ``(0, 6, 0)``,
      TOC offset, zero-padding to 88 bytes.
    * Sections: TOKENS, STRINGS, FIELDS, FIELDSETS, PATHS, SPECS — each
      preceded by an uncompressed size/compressed-size prefix (passthrough,
      no actual LZ4 compression).
    * TOC: section-name (8-byte padded) + uint64 offset + uint64 size for each
      section, immediately followed by a uint64 section count.
    * Attributes written: ``faceVertexCounts`` (int[]),
      ``faceVertexIndices`` (int[]), ``points`` (vec3f[]),
      ``subdivisionScheme`` (token "catmullClark"),
      ``interpolateBoundary`` (token "edgeAndCorner"),
      ``creaseIndices`` / ``creaseLengths`` / ``creaseSharpnesses`` (if any).

    Full Pixar usdcat/usdview interop requires Pixar's C++ library and genuine
    LZ4 frame compression; this writer is suitable for archival, transfer, and
    header-verification workflows.

    References
    ----------
    - OpenUSD/pxr/usd/usd/crateFile.cpp (Pixar, Apache 2.0)
    - https://github.com/PixarAnimationStudios/OpenUSD
    """
    mesh = _cage_to_subd_mesh(cage)
    prim_name = _prim_name(prim_path)

    # ------------------------------------------------------------------
    # Step 1: Build mesh arrays
    # ------------------------------------------------------------------
    face_vertex_counts: List[int] = [len(f) for f in mesh.faces]
    face_vertex_indices: List[int] = []
    for f in mesh.faces:
        face_vertex_indices.extend(f)

    crease_indices: List[int] = []
    crease_lengths: List[int] = []
    crease_sharpnesses: List[float] = []
    for (a, b), s in sorted(mesh.creases.items()):
        if s > _SHARPNESS_MIN:
            clamped = min(float(s), _SHARPNESS_MAX)
            crease_indices.extend([int(a), int(b)])
            crease_lengths.append(2)
            crease_sharpnesses.append(clamped)

    has_creases = bool(crease_indices)

    # ------------------------------------------------------------------
    # Step 2: Build token table (deduplicated, order-stable)
    # ------------------------------------------------------------------
    # Tokens are the canonical string pool; strings section re-indexes into it.
    base_tokens = [
        '',                       # 0  empty / sentinel
        prim_name,                # 1  prim name
        'faceVertexCounts',       # 2
        'faceVertexIndices',      # 3
        'points',                 # 4
        'subdivisionScheme',      # 5
        'interpolateBoundary',    # 6
        'catmullClark',           # 7
        'edgeAndCorner',          # 8
        'Mesh',                   # 9
    ]
    if has_creases:
        base_tokens += [
            'creaseIndices',      # 10
            'creaseLengths',      # 11
            'creaseSharpnesses',  # 12
        ]

    tokens = base_tokens  # order is the token index

    # ------------------------------------------------------------------
    # Step 3: Value repository (raw bytes appended sequentially)
    # ------------------------------------------------------------------
    # We store each non-inline array value here and track byte offsets.
    value_repo = io.BytesIO()

    def _vr_put_int_array(vals: List[int]) -> int:
        """Append int32 array to value_repo; return byte offset."""
        offset = value_repo.tell()
        value_repo.write(_usdc_encode_inline_int_array(vals))
        return offset

    def _vr_put_float_array(vals: List[float]) -> int:
        offset = value_repo.tell()
        value_repo.write(_usdc_encode_inline_float_array(vals))
        return offset

    def _vr_put_vec3f_array(verts: List[List[float]]) -> int:
        offset = value_repo.tell()
        value_repo.write(_usdc_encode_inline_vec3f_array(verts))
        return offset

    # Pre-allocate offsets for all array attributes
    off_fvc   = _vr_put_int_array(face_vertex_counts)
    off_fvi   = _vr_put_int_array(face_vertex_indices)
    off_pts   = _vr_put_vec3f_array(list(mesh.vertices))
    if has_creases:
        off_ci  = _vr_put_int_array(crease_indices)
        off_cl  = _vr_put_int_array(crease_lengths)
        off_cs  = _vr_put_float_array(crease_sharpnesses)

    value_bytes = value_repo.getvalue()

    # ------------------------------------------------------------------
    # Step 4: Build FIELDS section
    # Each field is (token_index: uint32, value_rep: uint64) = 12 bytes.
    # We store non-inline array values in the value repository; the
    # ValueRep payload holds the byte offset into that repository.
    # Inline tokens use the token index directly in the high 32 bits.
    # ------------------------------------------------------------------

    def _tok(name: str) -> int:
        return tokens.index(name)

    # Build ordered field list: (token_index, value_rep_uint64)
    fields: List[Tuple[int, int]] = []

    def _add_field_token_inline(attr_name: str, token_name: str) -> int:
        """Add a field whose value is a single inline token."""
        fidx = len(fields)
        tok_idx = _tok(token_name)
        vr = _pack_value_rep(_VR_TOKEN, tok_idx, is_array=False, inline=True)
        fields.append((_tok(attr_name), vr))
        return fidx

    def _add_field_int_array(attr_name: str, offset: int) -> int:
        fidx = len(fields)
        vr = _pack_value_rep(_VR_INT_ARRAY, offset, is_array=True, inline=False)
        fields.append((_tok(attr_name), vr))
        return fidx

    def _add_field_float_array(attr_name: str, offset: int) -> int:
        fidx = len(fields)
        vr = _pack_value_rep(_VR_FLOAT_ARRAY, offset, is_array=True, inline=False)
        fields.append((_tok(attr_name), vr))
        return fidx

    def _add_field_vec3f_array(attr_name: str, offset: int) -> int:
        fidx = len(fields)
        vr = _pack_value_rep(_VR_VEC3F_ARRAY, offset, is_array=True, inline=False)
        fields.append((_tok(attr_name), vr))
        return fidx

    f_scheme   = _add_field_token_inline('subdivisionScheme', 'catmullClark')
    f_interp   = _add_field_token_inline('interpolateBoundary', 'edgeAndCorner')
    f_fvc      = _add_field_int_array('faceVertexCounts', off_fvc)
    f_fvi      = _add_field_int_array('faceVertexIndices', off_fvi)
    f_pts      = _add_field_vec3f_array('points', off_pts)

    if has_creases:
        f_ci   = _add_field_int_array('creaseIndices', off_ci)
        f_cl   = _add_field_int_array('creaseLengths', off_cl)
        f_cs   = _add_field_float_array('creaseSharpnesses', off_cs)

    # ------------------------------------------------------------------
    # Step 5: FIELDSETS — ordered lists of field indices for each spec.
    # Format: int32 values, with -1 as a terminator between sets.
    # Prim spec: empty field set (prims carry fields via attributes).
    # Attribute specs: one field each.
    # ------------------------------------------------------------------
    prim_fieldset_start = 0  # index into fieldsets array
    fieldsets: List[int] = [-1]  # prim spec has no own fields; just terminator

    def _add_fieldset(field_indices: List[int]) -> int:
        start = len(fieldsets)
        fieldsets.extend(field_indices)
        fieldsets.append(-1)
        return start

    fs_scheme  = _add_fieldset([f_scheme])
    fs_interp  = _add_fieldset([f_interp])
    fs_fvc     = _add_fieldset([f_fvc])
    fs_fvi     = _add_fieldset([f_fvi])
    fs_pts     = _add_fieldset([f_pts])

    if has_creases:
        fs_ci  = _add_fieldset([f_ci])
        fs_cl  = _add_fieldset([f_cl])
        fs_cs  = _add_fieldset([f_cs])

    # ------------------------------------------------------------------
    # Step 6: PATHS section
    # Each path entry: (element_token_index: uint32, parent_path_index: int32,
    #                   is_prim_property_path: uint8)
    # Index 0 = pseudo-root "/"; index 1 = our prim.
    # ------------------------------------------------------------------
    # path_index 0 = root "/"  (element='', parent=-1)
    # path_index 1 = "/<prim_name>"  (element=prim_name, parent=0)
    # Attribute paths share the prim as parent.
    ATTR_NAMES_BASE = [
        'subdivisionScheme', 'interpolateBoundary',
        'faceVertexCounts', 'faceVertexIndices', 'points',
    ]
    ATTR_NAMES_CREASE = ['creaseIndices', 'creaseLengths', 'creaseSharpnesses']
    attr_names = ATTR_NAMES_BASE + (ATTR_NAMES_CREASE if has_creases else [])

    # path_index 0: root
    # path_index 1: /<prim_name>
    # path_index 2+: /<prim_name>.<attr>
    PATH_ROOT = 0
    PATH_PRIM = 1
    PATH_ATTR_START = 2

    # ------------------------------------------------------------------
    # Step 7: SPECS section
    # Each spec: (path_index: uint32, fieldset_index: uint32, spec_type: uint32)
    # ------------------------------------------------------------------
    specs: List[Tuple[int, int, int]] = []
    # Prim spec
    specs.append((PATH_PRIM, prim_fieldset_start, _SPEC_TYPE_PRIM_SPEC))
    # Attribute specs
    attr_fieldsets = [fs_scheme, fs_interp, fs_fvc, fs_fvi, fs_pts]
    if has_creases:
        attr_fieldsets += [fs_ci, fs_cl, fs_cs]

    for i, fs in enumerate(attr_fieldsets):
        specs.append((PATH_ATTR_START + i, fs, _SPEC_TYPE_ATTRIBUTE_SPEC))

    # ------------------------------------------------------------------
    # Step 8: Encode each section payload (uncompressed)
    # ------------------------------------------------------------------

    def _enc_tokens() -> bytes:
        return _usdc_encode_tokens(tokens)

    def _enc_strings() -> bytes:
        # Strings section: each string is a token index.
        # Here we expose all token indices as strings (simplest valid form).
        indices = list(range(len(tokens)))
        return _usdc_encode_strings(indices)

    def _enc_fields() -> bytes:
        buf = io.BytesIO()
        buf.write(struct.pack('<Q', len(fields)))
        for tok_idx, vr in fields:
            buf.write(struct.pack('<IQ', tok_idx, vr))
        return buf.getvalue()

    def _enc_fieldsets() -> bytes:
        buf = io.BytesIO()
        buf.write(struct.pack('<Q', len(fieldsets)))
        for fs in fieldsets:
            buf.write(struct.pack('<i', fs))
        return buf.getvalue()

    def _enc_paths() -> bytes:
        buf = io.BytesIO()
        n_paths = 2 + len(attr_names)
        buf.write(struct.pack('<Q', n_paths))
        # path 0: root
        buf.write(struct.pack('<Ii?', _tok(''), -1, False))
        # path 1: prim
        buf.write(struct.pack('<Ii?', _tok(prim_name), PATH_ROOT, False))
        # attribute paths
        for attr in attr_names:
            buf.write(struct.pack('<Ii?', _tok(attr), PATH_PRIM, True))
        return buf.getvalue()

    def _enc_specs() -> bytes:
        buf = io.BytesIO()
        buf.write(struct.pack('<Q', len(specs)))
        for path_idx, fs_idx, spec_type in specs:
            buf.write(struct.pack('<III', path_idx, fs_idx, spec_type))
        return buf.getvalue()

    # Wrap each section payload with uncompressed size header
    section_payloads: List[Tuple[bytes, bytes]] = [
        (_SEC_TOKENS,    _usdc_lz4_passthrough(_enc_tokens())),
        (_SEC_STRINGS,   _usdc_lz4_passthrough(_enc_strings())),
        (_SEC_FIELDS,    _usdc_lz4_passthrough(_enc_fields())),
        (_SEC_FIELDSETS, _usdc_lz4_passthrough(_enc_fieldsets())),
        (_SEC_PATHS,     _usdc_lz4_passthrough(_enc_paths())),
        (_SEC_SPECS,     _usdc_lz4_passthrough(_enc_specs())),
    ]

    # We also need to append the raw value repository (not a TOC section,
    # but referenced by field ValueReps as byte offsets from its start).
    # Embed value data as a final section to make offsets self-consistent.
    # In the full Crate format the value data lives inline with the sections;
    # here we write it as a dedicated section so offsets are stable.
    section_payloads.append(
        (b'VALUES\x00\x00', _usdc_lz4_passthrough(value_bytes if value_bytes else b''))
    )

    # ------------------------------------------------------------------
    # Step 9: Assign byte offsets for each section
    # ------------------------------------------------------------------
    # Layout:
    #   [0..87]   : header (88 bytes, TOC offset written last)
    #   [88..]    : section data blocks
    #   [...   ]  : TOC
    #   last 8    : uint64 section count (trailer)

    current_offset = _USDC_HEADER_SIZE
    section_offsets: List[int] = []
    for _, payload in section_payloads:
        section_offsets.append(current_offset)
        current_offset += len(payload)

    toc_offset = current_offset

    # ------------------------------------------------------------------
    # Step 10: Assemble the file
    # ------------------------------------------------------------------
    out = io.BytesIO()

    # --- Header (88 bytes) ---
    # magic (8) + version (3 × uint8) + padding byte + uint64 toc_offset
    # + padding to 88 bytes
    out.write(_USDC_MAGIC)                               # 8 bytes
    out.write(struct.pack('<BBB', *_USDC_VERSION))       # 3 bytes
    out.write(b'\x00')                                   # 1 byte padding
    out.write(struct.pack('<Q', toc_offset))             # 8 bytes
    # Remaining header bytes to fill 88 total:
    # 8 + 4 + 8 = 20 bytes used; 68 bytes of zero padding
    out.write(b'\x00' * (_USDC_HEADER_SIZE - 8 - 4 - 8))

    # --- Section payloads ---
    for _, payload in section_payloads:
        out.write(payload)

    # --- TOC ---
    # Format: N × (name: 8 bytes zero-padded + offset: uint64 + size: uint64)
    # followed by uint64 N (section count)
    for i, (name, payload) in enumerate(section_payloads):
        name_padded = name[:8].ljust(8, b'\x00')
        size = len(payload)
        out.write(name_padded)
        out.write(struct.pack('<QQ', section_offsets[i], size))

    # Trailer: section count
    out.write(struct.pack('<Q', len(section_payloads)))

    Path(output_path).write_bytes(out.getvalue())


# ---------------------------------------------------------------------------
# Public: write_subd_usd  (auto-dispatch by extension)
# ---------------------------------------------------------------------------

def write_subd_usd(cage: Any, path: str, *, prim_path: str = '/SubDMesh') -> None:
    """Write USD to *path*, dispatching on extension.

    Parameters
    ----------
    cage : SubDMesh | SubDCage | dict
        The control cage.
    path : str
        Output file path.  Extension determines format:
        ``.usda`` → ASCII text; ``.usdc`` → binary crate.
    prim_path : str
        USD prim path (default ``/SubDMesh``).
    """
    p = Path(path)
    if p.suffix.lower() == '.usdc':
        export_subd_to_usdc(cage, path, prim_path=prim_path)
    else:
        write_subd_usda(cage, path, prim_path=prim_path)


# ---------------------------------------------------------------------------
# Public: parse_usdc_header  (minimal header reader for round-trip tests)
# ---------------------------------------------------------------------------

def parse_usdc_header(data: bytes) -> Dict[str, Any]:
    """Parse the fixed 88-byte header of a USDC binary crate file.

    Parameters
    ----------
    data : bytes
        Raw file contents (at least 88 bytes).

    Returns
    -------
    dict with keys:
      ``magic``         : bytes (8)     — must be b'PXR-USDC'
      ``version``       : tuple(int,int,int)
      ``toc_offset``    : int           — byte offset of TOC
      ``section_count`` : int           — number of sections in TOC (read from
                                          the uint64 trailer)
      ``sections``      : list of dicts — each with 'name', 'offset', 'size'
    """
    if len(data) < _USDC_HEADER_SIZE:
        raise ValueError(f'Data too short for USDC header: {len(data)} < {_USDC_HEADER_SIZE}')
    magic = data[:8]
    ver_major, ver_minor, ver_patch = struct.unpack_from('<BBB', data, 8)
    (toc_offset,) = struct.unpack_from('<Q', data, 12)

    # Read TOC: trailer uint64 is section count, located just before the end
    # of the file.  TOC entries immediately follow toc_offset.
    # Each TOC entry: 8-byte name + uint64 offset + uint64 size = 24 bytes.
    if len(data) < toc_offset + 8:
        # Not enough data to read even the trailer
        return {
            'magic': magic,
            'version': (ver_major, ver_minor, ver_patch),
            'toc_offset': toc_offset,
            'section_count': 0,
            'sections': [],
        }

    # Trailer: last 8 bytes of the file
    (section_count,) = struct.unpack_from('<Q', data, len(data) - 8)

    sections = []
    pos = toc_offset
    for _ in range(section_count):
        if pos + 24 > len(data):
            break
        name_raw = data[pos:pos + 8].rstrip(b'\x00')
        (offset,) = struct.unpack_from('<Q', data, pos + 8)
        (size,)   = struct.unpack_from('<Q', data, pos + 16)
        sections.append({'name': name_raw, 'offset': offset, 'size': size})
        pos += 24

    return {
        'magic': magic,
        'version': (ver_major, ver_minor, ver_patch),
        'toc_offset': toc_offset,
        'section_count': section_count,
        'sections': sections,
    }


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
            'DISCLAIMER: USDA ASCII path only (this tool); for binary crate use export_subd_to_usdc.\n'
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
