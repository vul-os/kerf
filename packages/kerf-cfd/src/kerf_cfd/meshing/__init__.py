"""
kerf_cfd.meshing — Cartesian hex mesh generation (snappyHexMesh-style).

Implements a 3-phase Cartesian + snapping pipeline equivalent to OpenFOAM's
snappyHexMesh utility:

  1. CASTELLATED — build a background Cartesian mesh; subdivide cells in
     user-specified refinement regions; remove cells exterior to the
     boundary geometry.
  2. SNAP — iteratively project boundary vertices onto the nearest surface
     point via Laplacian smoothing.
  3. ADDLAYERS — prismatic boundary-layer extrusion (not implemented in v1).

HONEST FLAG: Simplified reference implementation.  Production CFD meshing
requires anisotropic refinement, prism-layer extrusion, and cell-quality
enforcement that are beyond the scope of this module.  Do not use for
safety-critical CFD without validation against OpenFOAM or a commercial mesher.

References
----------
Aftosmis, M.J., Berger, M.J., Melton, J.E. (1998). "Robust and Efficient
Cartesian Mesh Generation for Component-Based Geometry." AIAA J. 36(6), 952–960.

Hirt, C.W., Nichols, B.D. (1981). "Volume of Fluid (VOF) Method for the
Dynamics of Free Boundaries." J. Comput. Phys. 39(1), 201–225.

OpenFOAM snappyHexMesh User Guide (public),
https://www.openfoam.com/documentation/user-guide/snappyhexmesh.
"""

from kerf_cfd.meshing.snappy_hex import (
    HexMesh,
    HexMeshSpec,
    estimate_mesh_quality,
    snappy_hex_mesh,
)

__all__ = [
    "HexMeshSpec",
    "HexMesh",
    "snappy_hex_mesh",
    "estimate_mesh_quality",
]
