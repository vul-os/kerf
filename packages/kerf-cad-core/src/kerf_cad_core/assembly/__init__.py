"""
kerf_cad_core.assembly — pure-Python assembly constraint layer.

Units:    mm  (millimetres)
Handedness: right-handed coordinate system (X right, Y forward, Z up)
Transforms: 4x4 column-major homogeneous matrices stored as flat list[float]
            of length 16, row-major order (row 0 = [m00,m01,m02,m03], …).

Sub-modules
-----------
model   — Component, Assembly data model
mates   — Mate types + deterministic DOF solver
tools   — LLM tool wrappers (assembly_create, assembly_add_component, …)
"""

from kerf_cad_core.assembly.model import Assembly, Component
from kerf_cad_core.assembly.mates import Mate, MateType, solve_assembly

__all__ = [
    "Assembly",
    "Component",
    "Mate",
    "MateType",
    "solve_assembly",
]
