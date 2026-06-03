"""kerf_cad_core.sculpt — Mesh sculpt brush engine.

Public API:

    BrushKind, BrushStroke, MeshDelta, SculptMesh
    apply_brush(mesh, stroke) -> MeshDelta
    revert_delta(mesh, delta) -> None
    falloff_weight(distance, radius, kind) -> float
"""

from kerf_cad_core.sculpt.brush import (
    BrushKind,
    BrushStroke,
    MeshDelta,
    SculptMesh,
    apply_brush,
    falloff_weight,
    revert_delta,
)

__all__ = [
    "BrushKind",
    "BrushStroke",
    "MeshDelta",
    "SculptMesh",
    "apply_brush",
    "falloff_weight",
    "revert_delta",
]
