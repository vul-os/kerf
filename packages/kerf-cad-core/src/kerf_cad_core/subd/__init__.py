"""kerf_cad_core.subd — Catmull-Clark SubD limit-surface analysis utilities.

This subpackage collects higher-level SubD operations that build on the
foundational evaluators in ``kerf_cad_core.geom.subd`` and
``kerf_cad_core.geom.subd_stam``.

Modules
-------
limit_walk_cross_curve
    SUBD-LIMIT-WALK-CROSS-CURVE: walk a parametric path on the CC limit
    surface and intersect with a planar cut (Stam 1998 evaluator + 5-iter
    bisection refinement).
edge_loop_select
    SUBD-CAGE-EDGE-LOOP-SELECT: directional edge-loop walk on a quad cage;
    stops at irregular vertex (valence≠4) or loop closure
    (Bommes-Lévy-Pietroni 2013 §3.2).
face_loop_select
    SUBD-CAGE-FACE-LOOP: walk a face loop on a quad cage by hopping through
    opposite-edge adjacent quads; stops at non-quad face, boundary edge, or
    loop closure. walk_direction 0/1 gives orthogonal rings.
    (Bommes-Lévy-Pietroni 2013 §3.2; Hoppe 1996).
limit_normal_fit
    SUBD-LIMIT-NORMAL-FIT: sample the CC limit-surface normal n̂(u,v) at
    a uniform (u,v) grid on each cage face using Stam (1998) exact tangents;
    compute residuals vs bilinear face-corner approximation for shading use.
edge_collapse
    SUBD-CAGE-EDGE-COLLAPSE: collapse a cage edge (merge v_keep and v_remove
    into one vertex) while maintaining mesh validity; midpoint or endpoint
    placement; degenerate faces removed; non-edge pairs rejected with
    became_invalid=True (Hoppe 1993/1996 §3.2; Garland-Heckbert 1997 QEM §3).
vertex_merge
    SUBD-CAGE-VERTEX-MERGE: merge a list of cage vertices (by index) into
    their centroid, updating all adjacent face indices and removing
    degenerate faces. Generalisation of edge collapse to N vertices
    (Hoppe 1996 §3.2; Garland-Heckbert 1997 QEM §3).
dual_mesh
    SUBD-CAGE-DUAL-MESH: compute the combinatorial dual mesh of a quad
    subdivision cage; each face becomes a dual vertex (at its centroid),
    each primal vertex becomes a dual face whose corners are the neighboring
    face centroids ordered CCW. Used for ringing analysis, mesh smoothing,
    and visualization (Bossen-Heckbert 1996; Bommes-Lévy-Pietroni 2013 §3.2).
edge_flip
    SUBD-CAGE-EDGE-FLIP: flip the shared edge of two adjacent triangles,
    replacing (v_a, v_b) with (v_c, v_d) where v_c and v_d are the opposite
    vertices. Purely topological — no Delaunay in-circle test. Triangles only.
    (Bommes-Lévy-Pietroni 2013 §3; Edelsbrunner 2001 §2).
cage_area
    SUBD-CAGE-AREA: compute total surface area of the control polygon and
    estimate the asymptotic Catmull-Clark limit-surface area via empirical
    0.94× cage-shrinkage ratio; per-face area distribution; degenerate face
    flagging (area < 1e-6 mm²).
    (Catmull-Clark 1978; Stam 1998 §2; Zorin-Schröder 2000 §3).
stam_limit_tangents
    GK-P12 SUBD-STAM-LIMIT-TANGENTS: exact limit tangent vectors at
    extraordinary Catmull-Clark vertices (valence n != 4) using the
    eigenstructure decomposition from Stam (1998) §3.2-3.3.
    T_u = Σ cos(2πi/n)·(P_i − V_inf); T_v = Σ sin(2πi/n)·(P_i − V_inf);
    N = T_u × T_v; approximate Gaussian and mean curvature estimates.
    (Stam 1998 §3.2-3.3; Reif 1995; Meyer et al. 2003).
"""

from kerf_cad_core.subd.limit_walk_cross_curve import (
    CrossCurveResult,
    walk_subd_limit_cross_plane,
)
from kerf_cad_core.subd.edge_loop_select import (
    EdgeLoopResult,
    select_edge_loop,
)
from kerf_cad_core.subd.face_loop_select import (
    FaceLoopResult,
    select_face_loop,
)
from kerf_cad_core.subd.limit_normal_fit import (
    LimitNormalFitResult,
    sample_subd_limit_normals,
)
from kerf_cad_core.subd.edge_collapse import (
    EdgeCollapseResult,
    collapse_edge,
)
from kerf_cad_core.subd.vertex_merge import (
    VertexMergeResult,
    merge_vertices,
)
from kerf_cad_core.subd.dual_mesh import (
    DualMeshResult,
    compute_dual_mesh,
)
from kerf_cad_core.subd.edge_flip import (
    EdgeFlipResult,
    flip_edge,
)
from kerf_cad_core.subd.cage_area import (
    SubdCage,
    CageAreaReport,
    compute_cage_area,
)
from kerf_cad_core.subd.stam_limit_tangents import (
    ExtraordinaryVertex,
    LimitTangentReport,
    compute_stam_limit_tangents,
)
from kerf_cad_core.subd.crease_fractional_decay import (
    CreasedEdge,
    FractionalCreaseSpec,
    CreaseDecayResult,
    apply_fractional_crease_decay,
)
from kerf_cad_core.subd.g1_extraordinary_patches import (
    ExtraordinaryPatchSpec,
    G1PatchResult,
    convert_subd_to_g1_patches,
)
from kerf_cad_core.subd.feature_curves import (
    FeatureCurveSpec,
    FeatureCurve,
    FeatureCurveResult,
    extract_feature_curves,
)

__all__ = [
    "CrossCurveResult",
    "walk_subd_limit_cross_plane",
    "EdgeLoopResult",
    "select_edge_loop",
    "FaceLoopResult",
    "select_face_loop",
    "LimitNormalFitResult",
    "sample_subd_limit_normals",
    "EdgeCollapseResult",
    "collapse_edge",
    "VertexMergeResult",
    "merge_vertices",
    "DualMeshResult",
    "compute_dual_mesh",
    "EdgeFlipResult",
    "flip_edge",
    "SubdCage",
    "CageAreaReport",
    "compute_cage_area",
    "ExtraordinaryVertex",
    "LimitTangentReport",
    "compute_stam_limit_tangents",
    "CreasedEdge",
    "FractionalCreaseSpec",
    "CreaseDecayResult",
    "apply_fractional_crease_decay",
    "ExtraordinaryPatchSpec",
    "G1PatchResult",
    "convert_subd_to_g1_patches",
    "FeatureCurveSpec",
    "FeatureCurve",
    "FeatureCurveResult",
    "extract_feature_curves",
]
