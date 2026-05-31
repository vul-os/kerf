"""
kerf_cad_core — shared pythonOCC base layer for Kerf CAD compute plugins.

Downstream plugins import the public API from here:

    from kerf_cad_core import _OCC_AVAILABLE, convert_step_to_stl, load_step, mesh_shape, write_stl
"""

from kerf_cad_core.occ_helpers import (
    _OCC_AVAILABLE,
    convert_step_to_stl,
    load_step,
    mesh_shape,
    write_stl,
)
from kerf_cad_core.mesh_isotropic_remesh import (
    IsotropicRemeshReport,
    IsotropicRemeshSpec,
    TriangleMesh,
    isotropic_remesh,
)
from kerf_cad_core.mesh_sculpt_brushes import (
    MeshSculptResult,
    SculptStroke,
    apply_sculpt_brush,
)

__all__ = [
    "_OCC_AVAILABLE",
    "convert_step_to_stl",
    "load_step",
    "mesh_shape",
    "write_stl",
    # GK-P23: isotropic remesh
    "TriangleMesh",
    "IsotropicRemeshSpec",
    "IsotropicRemeshReport",
    "isotropic_remesh",
    # GK-P22: sculpt brushes (inflate/crease/smooth/pinch)
    "SculptStroke",
    "MeshSculptResult",
    "apply_sculpt_brush",
]
