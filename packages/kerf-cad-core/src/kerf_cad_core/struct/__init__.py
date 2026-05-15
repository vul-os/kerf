"""
kerf_cad_core.struct — structural grid, levels, and column/beam framing layer.

A pure-Python parametric layer for civil/structural building layout.
No OCC dependency; all geometry is 3-D point arithmetic.

Submodules:
  grid      — StructGrid (named X axes A, B, C… + numbered Y axes 1, 2, 3…,
               spacings), Level (name + elevation in mm)
  framing   — Column, Beam, and a built-in catalog of common steel sections
               (IPE / HEA / UB / W nominal published dimensions)
  tools     — LLM tool wrappers registered with the tool registry

Units: all lengths in mm, mass in kg.
"""
from __future__ import annotations

from kerf_cad_core.struct.grid import StructGrid, Level, GridPoint
from kerf_cad_core.struct.framing import Column, Beam, SECTION_CATALOG, get_section

__all__ = [
    "StructGrid",
    "Level",
    "GridPoint",
    "Column",
    "Beam",
    "SECTION_CATALOG",
    "get_section",
]
