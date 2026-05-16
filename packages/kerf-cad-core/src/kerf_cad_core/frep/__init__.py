"""
kerf_cad_core.frep — Implicit / function-representation (F-rep / SDF) modelling.

Sub-modules
-----------
sdf     — SDF primitives, CSG ops, transforms, TPMS lattices, marching-cubes
          mesh extraction, volume / surface-area integration, and LLM tool wrappers.

All calculations are pure-Python (math only); no OCC dependency.
"""
from __future__ import annotations

__all__ = ["sdf"]
