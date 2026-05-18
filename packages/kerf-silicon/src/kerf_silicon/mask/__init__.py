"""kerf_silicon.mask — photolithography mask generation.

Public API
----------
fracture_polygon(polygon, max_dim_nm=100_000) -> list[Trapezoid]
    Convert an arbitrary polygon (list of (x, y) vertex tuples, in nm) into
    a list of non-overlapping trapezoids suitable for an e-beam writer.

apply_opc(shapes, design_rules) -> list[Shape]
    Optical Proximity Correction stub: add hammerhead extensions at line-ends
    and serif features at inside corners.

Shape types are exported directly from the sub-modules so callers need only
import from this package.
"""

from .fracture import Trapezoid, fracture_polygon
from .opc import Shape, apply_opc

__all__ = [
    "Trapezoid",
    "fracture_polygon",
    "Shape",
    "apply_opc",
]
