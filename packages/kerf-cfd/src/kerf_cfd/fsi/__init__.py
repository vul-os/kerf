"""
kerf_cfd.fsi — moving mesh (ALE) and Fluid-Structure Interaction.

Implements Arbitrary Lagrangian-Eulerian (ALE) dynamic mesh deformation via
Laplacian smoothing (Lohner-Yang 1996), Geometric Conservation Law (GCL)
correction (Thomas-Lombard 1979), and one-way FSI coupling.

HONEST FLAG: Design-exploration accuracy only.  Not validated against
OpenFOAM or experimental benchmarks.  Do not use for safety-critical design.

References:
  Lohner, R., Yang, C. (1996). "Improved ALE mesh velocities for moving
  bodies." Comm. Num. Meth. Eng. 12(10), 599–608.

  Thomas, P.D., Lombard, C.K. (1979). "Geometric conservation law and its
  application to flow computations on moving grids." AIAA J. 17(10), 1030–1037.
"""

from kerf_cfd.fsi.dynamic_mesh import (
    DynamicMeshState,
    compute_geometric_conservation_law_correction,
    displace_mesh_rigid,
    fsi_one_way_coupling,
)

__all__ = [
    "DynamicMeshState",
    "compute_geometric_conservation_law_correction",
    "displace_mesh_rigid",
    "fsi_one_way_coupling",
]
