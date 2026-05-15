"""
kerf_imports.dxf
================
Pure-Python DXF reader (T-5) and entity-to-Kerf mapper (T-6).

No third-party dependencies — parses DXF group-code format with stdlib only.

Public API::

    from kerf_imports.dxf.reader import read_dxf
    from kerf_imports.dxf.mapper import dxf_to_sketch, dxf_to_drawing
"""
from kerf_imports.dxf.reader import read_dxf  # noqa: F401
from kerf_imports.dxf.entities import (  # noqa: F401
    DxfDocument,
    DxfLine,
    DxfLwPolyline,
    DxfPolyline,
    DxfCircle,
    DxfArc,
    DxfText,
    DxfInsert,
    DxfBlock,
)
