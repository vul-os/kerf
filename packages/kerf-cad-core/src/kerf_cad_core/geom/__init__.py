"""
kerf_cad_core.geom — stable public façade for the geometry kernel.

Architecture split
------------------
OCCT-backed (requires OCC runtime, wrapped via kerf_cad_core.geom.brep_build /
boolean / sew):
    surface_to_face, surfaces_to_shell, closed_shell_to_solid
    *_to_body primitives (box, cylinder, sphere, revolve, extrude, loft, sweep1,
        sweep2, extrude_face)
    sew_faces, sew_into_solid
    body_union, body_intersection, body_difference
    shell_body, draft_body, rib_body, wirecut_body, pipe_body
    surface_boolean_robust (OCCT primary path; pure-Python fallback in GK-72)
    STEP / IGES I/O (read_step, write_step, read_iges, write_iges)

Pure-Python (no OCCT dependency, hermetic):
    NurbsCurve / NurbsSurface evaluation, knot insertion, degree elevation
    closest_point_curve, closest_point_surface  (Newton inversion, GK-06/07)
    curve / surface intersection (GK-11/12)
    sweep1 / sweep2 / network_srf / blend_srf / patch_srf / coons
    trim_curve / trim_validation
    curve_toolkit (fairing, curvature comb)
    surface_analysis (Hausdorff, zebra, adaptive refinement)
    surface_fillet (variable-radius G1)
    SubD authoring + SubD↔NURBS conversion (GK-52/53)
    mesh utilities (mesh_autosurface, mesh_boolean_sealed)
    region2d (2-D boolean on planar loops)
    mass_props (body_mass_props)
"""

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    de_boor,
    curve_derivative,
    surface_evaluate,
    surface_derivative,
    surface_derivatives,
    surface_normal,
    knot_insertion,
    degree_elevation,
    curve_curve_intersection,
    make_circle_nurbs,
    make_line_nurbs,
    nurbs_to_occt_curve,
    occt_curve_to_nurbs,
    nurbs_to_occt_surface,
    occt_surface_to_nurbs,
)

from kerf_cad_core.geom.sweep1 import (
    sweep1,
    sweep1_rmf,
    sweep1_with_twist,
    sweep1_variable_scale,
    sweep1_helical,
    profile_along_path,
    compute_rmf_frames,
    # 2-rail API (formerly sweep2.py)
    sweep2,
    sweep2_rmf,
    sweep2_with_scaling,
    sweep2_with_twist,
    check_rail_compatibility,
    normalize_rails,
    # unified dispatcher
    sweep_along_rails,
)

# Variable-section extrude / morphing sweep (Piegl §10.5 skinning).
from kerf_cad_core.geom.variable_extrude import (
    extrude_variable_section,
    extrude_with_scaling_curve,
    extrude_morph_via_rail_pair,
)

from kerf_cad_core.geom.network_srf import (
    network_srf,
    network_srf_with_compatibility,
    network_srf_global,
    network_srf_from_cross_sections,
    approximate_network_srf,
    validate_curves_for_skinning,
    gordon_network_srf,
    loft_surface,  # GK-P16: guided loft
)

# GK-P-D: loft with multiple guide rails (Gordon surface)
from kerf_cad_core.geom.loft_rails import (
    loft_with_rails,
    _gordon_loft_surface,
)

from kerf_cad_core.geom.blend_srf import (
    blend_srf,
    blend_srf_g1,
    blend_srf_g2,
    blend_srf_g3,
    blend_srf_with_curves,
    blend_srf_fillet,
    validate_surface_blend,
    compute_blend_surface_isocurves,
    # GK-62: G3 trim+sew to Body
    g3_blend_trim_sew,
)

from kerf_cad_core.geom.surface_boolean_robust import (
    surface_health_check,
    surface_boolean_robust,
)

from kerf_cad_core.geom.brep_build import (
    BuildError,
    surface_to_face,
    surfaces_to_shell,
    closed_shell_to_solid,
    box_to_body,
    cylinder_to_body,
    sphere_to_body,
    revolve_to_body,
    extrude_to_body,
    # GK-57: planar region (with holes) → extruded solid
    extrude_face_to_body,
    # GK-16: loft / sweep1 / sweep2 → open Shell Body
    loft_to_body,
    sweep1_to_body,
    sweep2_to_body,
)

from kerf_cad_core.geom.subd_authoring import (
    SubDCage,
    SubDSurface,
    create_subd_primitive,
    subd_extrude,
    subd_bevel,
    subd_loop_cut,
    subd_set_crease,
    to_subd_surface,
)
# T-104e: pure-Python trim side-selection + validation contract.
from kerf_cad_core.geom.trim_validation import (
    AmbiguousPoint,
    select_side,
    validate_body_post_trim,
)
# GK-45: shell/hollow a Body (offset faces inward, re-sew).
from kerf_cad_core.geom.solid_features import shell_body
# GK-120: uniform body offset (grow/shrink whole solid).
from kerf_cad_core.geom.solid_features import offset_body
# GK-46: draft/rib/wirecut/pipe as validated Body-producing ops.
from kerf_cad_core.geom.solid_features import (
    draft_body,
    rib_body,
    wirecut_body,
    pipe_body,
)
# GK-44: match-surface analytic G1/G2 verification.
from kerf_cad_core.geom.match_srf import (
    MatchResult,
    match_surface_edge,
    verify_seam_g1_analytic,
    verify_seam_g2_analytic,
    verify_seam_g3_analytic,
)
# GK-P10: MatchSrf G3 (curvature-rate / dκ/ds continuity).
# Piegl & Tiller §11.4; Patrikalakis & Maekawa §6.5; Hoschek & Lasser §14.2.
# Requires degree >= 3 and >= 4 CP rows; G3 is best-effort for arbitrary pairs.
from kerf_cad_core.geom.match_srf_g3 import (
    MatchSrfG3Spec,
    MatchSrfG3Report,
    match_srf_g3,
)

# GK-39: untrim / shrink trimmed surface.
# GK-P44: general NURBS × NURBS pure-Python trim via robust SSI.
from kerf_cad_core.geom.trim_curve import (
    trim_face_by_ssi,
    trim_face_by_nurbs_ssi,
    trim_face_analytic,
    SsiTrimResult,
    AnalyticTrimLoop,
    TrimmedSurface,
    untrim,
    shrink,
)
# GK-35: energy-minimising, knot-preserving curve fairing
# GK-65: curvature comb / porcupine numeric export
# GK-98: arc-length parameterization + curve length
# GK-99: mid-curve (average of two NURBS curves)
# GK-100: composite curve (poly-NURBS chain + continuity tags)
# GK-101: curve-on-surface geodesic (iterative straightening)
# GK-103: text-on-curve / text-on-surface (engraving outlines)
from kerf_cad_core.geom.curve_toolkit import (
    fair_curve,
    curvature_variance,
    curvature_comb,
    curve_length,
    arc_length_param,
    mid_curve,
    composite_curve,
    split_composite,
    text_on_curve,
    text_on_surface,
    extend_curve,
    geodesic,
)
# GK-P: composite curve G2 audit + auto-blending
from kerf_cad_core.geom.composite_g2 import (
    audit_composite_g2,
    upgrade_to_g2,
    composite_curvature_profile,
    CompositeAuditResult,
    JointAudit,
)
# GK-P: Precise NURBS arc-length (Gauss-Legendre + adaptive subdivision)
from kerf_cad_core.geom.arc_length_gauss import (
    arc_length_precise,
    arc_length_parametrize as arc_length_parametrize_gauss,
    reparametrize_arclength as reparametrize_arclength_gauss,
)
# GK-P50: arc-length inversion — Newton–Raphson parameter solve for target arc length
from kerf_cad_core.geom.arc_length_invert import (
    ArcLengthInvertResult,
    invert_arc_length,
)
# GK-11: curve-curve intersection hardening
from kerf_cad_core.geom.intersection import (
    curve_curve_intersect,
    curve_surface_intersect,
    surface_surface_intersect,
)
# GK-34: surface fit-to-tolerance (lofted/grid least-squares + knot placement)
# GK-99: mid-surface (average of two NURBS surfaces)
from kerf_cad_core.geom.patch_srf import fit_surface, mid_surface, extend_surface
# GK-12: curve self-intersection
from kerf_cad_core.geom.intersection import curve_self_intersect
# GK-49: IGES 144 trimmed-surface reader/writer
# NURBS-CONVERT-TO-IGES-144: bytes-returning API + TrimmedSurfaceRecord
from kerf_cad_core.geom.io.iges import (
    write_iges,
    read_iges,
    IgesReadError,
    IgesWriteError,
    write_iges_trimmed_surface,
    read_iges_trimmed_surface,
    TrimmedSurfaceRecord,
)
# GK-37: certified Hausdorff surface deviation
from kerf_cad_core.geom.surface_fillet import (
    variable_radius_fillet_g1,
    # GK-62: G3 curvature-rate residual oracle
    curvature_rate_continuity_residual,
)
from kerf_cad_core.geom.surface_analysis import (
    hausdorff_deviation, zebra_stripe, zebra_stripe_continuity_analyser,
    # GK-64: Class-A acceptance harness
    class_a_acceptance_harness,
)
# GK-63: deviation-driven adaptive surface refinement
# GK-65: isocurve curvature comb
from kerf_cad_core.geom.surface_analysis import adaptive_refine_surface, isocurve_curvature_comb
# GK-92: draft analysis overlay (angle to pull direction)
from kerf_cad_core.geom.surface_analysis import draft_analysis, curvature_heatmap
# GK-95: reflection-line + highlight-line analysis
from kerf_cad_core.geom.surface_analysis import reflection_lines
# GK-P11: isophote / environment-map (EMap) analyser
from kerf_cad_core.geom.surface_analysis import (
    isophote_analysis,
    isophote_continuity_analyser,
)
# GK-P11: dedicated isophote analyser dataclass API (IsophoteSpec / IsophoteReport)
from kerf_cad_core.geom.isophote_analyzer import (
    IsophoteSpec,
    IsophoteReport,
    analyze_isophotes,
)
# GK-138: global continuity audit
from kerf_cad_core.geom.surface_analysis import continuity_audit
# GK-P: Gauss-Bonnet integrity + per-face chord-deviation reporting
from kerf_cad_core.geom.surface_analysis import (
    gauss_bonnet_residual,
    chord_deviation_per_face,
)
# GK-P43: best-effort OCCT-path G3 (analyzer + pole round-trip)
from kerf_cad_core.geom.surface_analysis import (
    occt_g3_residual_from_poles,
    occt_g3_pole_roundtrip,
)
# GK-P: post-Boolean continuity recovery (G1/G2 seam blending)
from kerf_cad_core.geom.continuity_recovery import (
    ContinuityRecoveryResult,
    recover_continuity_at_seam,
    recover_continuity_body,
)
# GK-P (curvature-comb): peak detection + variance metrics (Farin 1990)
from kerf_cad_core.geom.curvature_metrics import (
    CurvaturePeak,
    CurvaturePeakReport,
    curvature_comb_peaks,
    curvature_variance_metric,
    isophote_density_metric,
)
# GK-P (curvature gradient field + ridge/valley lines — Pottmann-Wallner §11)
from kerf_cad_core.geom.curvature_gradient import (
    CurvatureGradientResult,
    RidgeLine,
    compute_curvature_gradient,
    compute_ridge_lines,
    compute_valley_lines,
    curvature_gradient_field_visualization,
)
# GK-47: STEP reader
from kerf_cad_core.geom.io.step_read import read_step, StepReadError
# GK-48: STEP writer
from kerf_cad_core.geom.io.step_write import write_step, StepWriteError
# GK-23: body mass properties
from kerf_cad_core.geom.mass_props import body_mass_props
# GK-P-VWC: volume-weighted centroid + inertia for non-uniform density (Mortenson §11.5)
from kerf_cad_core.geom.volume_weighted_centroid import (
    compute_centroid_density_field,
    compute_inertia_density_field,
    functionally_graded_centroid,
    CentroidResult,
    InertiaResult,
)
# GK-54: mesh -> NURBS autosurface
from kerf_cad_core.geom.mesh_to_nurbs import mesh_autosurface
# GK-P51: NURBS↔Mesh reconciliation with fidelity tracking (Lévy 2009)
from kerf_cad_core.geom.mesh_reconciliation import (
    ReconciliationResult,
    RoundTripResult,
    fidelity_report,
    reconcile_nurbs_mesh,
    round_trip_nurbs_mesh,
    reconcile_mesh_to_nurbs_with_features,
)
# GK-55: mesh boolean sealed-manifold
from kerf_cad_core.geom.mesh_repair import mesh_boolean_sealed, boolean_volume_oracle
# GK-109: mesh decimate (QEM edge collapse)
from kerf_cad_core.geom.mesh_repair import mesh_decimate
# GK-110: mesh repair (hole-fill / weld / manifold / normal-consistency)
from kerf_cad_core.geom.mesh_repair import mesh_repair
# GK-111: mesh smoothing (Laplacian + Taubin λ|μ no-shrink)
from kerf_cad_core.geom.mesh_repair import mesh_smooth
# GK-56: 2D region boolean on planar curve loops
from kerf_cad_core.geom.region2d import (
    region_union,
    region_intersection,
    region_difference,
    region_area,
    make_rect_loop,
    make_circle_loop,
    # GK-P32: hatch fill
    hatch_region,
    HatchResult,
    HatchLine,
    material_hatch_pattern,
)
# GK-06/07: point inversion (closest-point on curve / surface)
from kerf_cad_core.geom.inversion import (
    closest_point_curve,
    closest_point_surface,
    project_point_to_curve,
    pull_curve_to_surface,
)
# GK-18: pure-Python sew (sew faces into shell / solid)
from kerf_cad_core.geom.sew import (
    sew_faces,
    sew_into_solid,
)
# GK-18: pure-Python boolean (body union / intersection / difference)
from kerf_cad_core.geom.boolean import (
    body_union,
    body_intersection,
    body_difference,
)
# GK-73: inset face (SubD + B-rep)
from kerf_cad_core.geom.inset_face import inset_face, InsetResult
# GK-76 / GK-P: wall-thickness map + high-level analysis API
from kerf_cad_core.geom.wall_thickness import (
    wall_thickness_map,
    ThicknessReport,
    ThinWallWarning,
    analyze_wall_thickness,
    material_thickness_guideline,
    flag_thin_walls,
)
# GK-29: solid edge/corner blend (concave/convex; degree-3 cylinder/sphere faces)
from kerf_cad_core.geom.blend_solid import (
    BlendResult,
    blend_edge,
    blend_edges,
    blend_corner_vertex,
    blend_edge_chain_g3,
)
# GK-52: SubD cage → watertight NURBS Body (Catmull-Clark limit surface)
# GK-53: NURBS Body → SubD cage (reverse, quad-dominant)
from kerf_cad_core.geom.subd_to_nurbs import (
    SubdToNurbsError,
    subd_limit_positions,
    subd_cage_to_limit_nurbs_body,
    subd_cage_to_nurbs_body,
    subd_cage_to_nurbs_patches,
    nurbs_body_volume,
    subd_mesh_volume,
    NurbsToSubdError,
    nurbs_body_to_subd_cage,
    nurbs_to_subd_cage,
)
# GK-75: hole feature wrapper (drill / counterbore / countersink / tapped)
from kerf_cad_core.geom.hole_feature import (
    drill_hole,
    counterbore,
    countersink,
    tapped_hole,
)

# GK-74: bridge two open boundary edge loops with a quad strip.
from kerf_cad_core.geom.bridge_loops import (
    BridgeResult,
    bridge_loops,
)
# GK-78: 3MF read/write (sealed manifold + materials + colour + thumbnail)
from kerf_cad_core.geom.io.threemf import (
    read_threemf,
    write_threemf,
    ThreeMFReadError,
    ThreeMFWriteError,
)
# GK-79: glTF 2.0 / GLB read + write (mesh + PBR materials)
from kerf_cad_core.geom.io.gltf import (
    read_gltf,
    write_gltf,
    GltfReadError,
    GltfWriteError,
)
# GK-80: Wavefront OBJ read + write (mesh + groups + mtllib)
from kerf_cad_core.geom.io.obj import (
    read_obj,
    write_obj,
    ObjReadError,
    ObjWriteError,
)
# GK-81: STL read (binary + ASCII) + write
from kerf_cad_core.geom.io.stl import (
    read_stl,
    write_stl,
    StlReadError,
    StlWriteError,
)
# GK-126: PLY read + write (mesh + per-vertex colour; ASCII + binary)
from kerf_cad_core.geom.io.ply import (
    read_ply,
    write_ply,
    PlyReadError,
    PlyWriteError,
)
# GK-88: loop slide (SubD)
from kerf_cad_core.geom.subd_authoring import subd_loop_slide, subd_edge_slide
# GK-105: vertex slide (SubD)
from kerf_cad_core.geom.subd_authoring import subd_vertex_slide
# GK-106: edge split at parameter (SubD)
from kerf_cad_core.geom.subd_authoring import subd_edge_split
# GK-107: bevel weight per edge (graded crease 0..1)
from kerf_cad_core.geom.subd_authoring import subd_set_bevel_weight
# GK-108: Loop subdivision scheme (triangle mesh)
from kerf_cad_core.geom.subd_authoring import loop_subdivide
# GK-P SubD boundary→curve snap
from kerf_cad_core.geom.subd_boundary_replace import (
    BoundaryLoop,
    BoundarySnapResult,
    extract_boundary_loops,
    snap_boundary_to_curve,
)
# GK-87: pattern (linear / circular / path)
from kerf_cad_core.geom.pattern import (
    linear_pattern,
    circular_pattern,
    path_pattern,
)

# GK-83 / GK-P-NURBS-OFFSET: surface_offset (legacy alias) + Tiller-Hanson offset_surface
# with detect_self_intersection + trim_self_intersection_loops.
from kerf_cad_core.geom.surface_offset import (
    surface_offset,
    offset_surface,
    detect_self_intersection,
    trim_self_intersection_loops,
)
# GK-P Wave 4P: far-offset robustness (Maekawa 1999 §6; Hoschek-Lasser 1993 §17)
from kerf_cad_core.geom.offset_far_correction import (
    UnsafeRegion,
    GracefulOffsetResult,
    safe_offset_distance,
    offset_with_local_refinement,
    graceful_offset,
)
# GK-P: 2D in-plane NURBS curve offset (Tiller-Hanson 1984) + self-intersection trim
from kerf_cad_core.geom.curve_offset_2d import (
    Offset2DResult,
    offset_curve_2d,
    offset_nurbs_curve_2d,
    detect_self_intersection_2d,
    trim_self_intersections_2d,
    offset_loop_2d,
)
# GK-96: reverse curve/surface direction
from kerf_cad_core.geom.nurbs import reverse_curve, reverse_surface
# GK-97: reparametrize curve/surface (normalize knots, domain rescale, arc-length)
from kerf_cad_core.geom.nurbs import normalize_knots, reparametrize_curve, reparametrize_arclength
# GK-P: chord-length + centripetal + Foley-Nielsen point-cloud parametrisation (Piegl-Tiller §9.2.2)
from kerf_cad_core.geom.reparam import (
    parametrize_chord_length,
    parametrize_centripetal,
    parametrize_foley_nielsen,
)
# GK-135: degree reduction (curve + surface)
from kerf_cad_core.geom.nurbs import reduce_degree_curve, reduce_degree_surface
# GK-P: degree raise + lower (Cohen-Lyche-Schumaker 1985)
from kerf_cad_core.geom.degree_op import (
    degree_raise_curve,
    degree_raise_surface,
    degree_lower_curve,
    degree_lower_surface,
    elevate_to_match,
)
# NURBS-CURVE-DEGREE-LOWER: Piegl-Tiller §6.5 + Schumaker §6 degree reduction with deviation reporting
from kerf_cad_core.geom.curve_degree_lower import (
    DegreeLowerResult,
    lower_curve_degree,
)
# GK-102: knot removal / minimal-CP refit
from kerf_cad_core.geom.nurbs import remove_knot, minimal_cp_refit
# GK-P: NURBS seam control for periodic (closed) surfaces
from kerf_cad_core.geom.seam_control import (
    SeamInfo,
    detect_seam,
    shift_seam,
    align_seam_to_curve,
)
# GK-84: split body by plane / surface (no-fill cut)
from kerf_cad_core.geom.split_body import (
    split_body_by_plane,
    split_body_by_surface,
)
# GK-89: knife / cut face by 3D curve (B-rep + SubD)
from kerf_cad_core.geom.knife import knife_face

from kerf_cad_core.geom.replace_face import replace_face
# GK-93: symmetry detection (reflective + rotational)
from kerf_cad_core.geom.symmetry import detect_symmetry
# GK-85: body simplify / heal (remove sub-tol faces/edges, weld verts, close gaps)
from kerf_cad_core.geom.body_heal import simplify_body, heal_body
# GK-82: imprint 3D curve on face → split face creating new edges
# GK-82 ext: body-body imprint with edge tagging
from kerf_cad_core.geom.imprint import imprint_curve_on_face, imprint_body, ImprintTag, ImprintResult
# GK-90: N-rail sweep (3+ rails) — now in sweep1.py
from kerf_cad_core.geom.sweep1 import sweep_n, loft_with_guides_sweep_n  # GK-P16
# GK-P (variable rail-tangent): variable-tangent Gordon loft (Piegl-Tiller §10.4.3)
from kerf_cad_core.geom.loft_rails_variable import (
    loft_with_rails_variable,
    extract_rail_tangents,
    validate_rail_tangent_compatibility,
)
# GK-91: sheet metal bend / unfold (K-factor + bend tables)
from kerf_cad_core.geom.sheet_metal import (
    K_FACTOR_TABLE,
    bend_allowance,
    bend_sheet,
    unfold_sheet,
)
# GK-129: helical thread profiles (ISO metric + Acme)
# GK-130: spring / coil generator
from kerf_cad_core.geom.threads import (
    iso_metric_thread,
    acme_thread,
    coil_spring,
)

# GK-118: parting line generation
# GK-119: cavity / core mould split
from kerf_cad_core.geom.mold import parting_line, undercut_faces, mold_split

# GK-P: parting-line extraction + undercut detection (Ahn-Cho-Kim 2002)
from kerf_cad_core.geom.parting_line import (
    PartingLineResult,
    extract_parting_line,
    detect_undercuts,
    optimal_pull_direction,
)
# GK-P Wave 4T: mold parting-surface construction (Yu-Fan 2003 §6)
from kerf_cad_core.geom.mold_parting_surface import (
    construct_parting_surface,
    construct_with_shutoff_inserts,
    validate_parting_surface,
)

# GK-125: DXF read+write
from kerf_cad_core.geom.io.dxf import read_dxf, write_dxf, DxfReadError, DxfWriteError

# GK-128: gear tooth profile generator
from kerf_cad_core.geom.gears import involute_gear, cycloid_gear

# SUBD-DENSE-TO-LOW-POLY-CONVERT: QEM decimation + quad recovery → SubD cage
from kerf_cad_core.geom.subd_decimate_to_cage import (
    dense_mesh_to_subd_cage,
    DecimationReport,
)

# SUBD-CAGE-PROJECT-TO-PRIMITIVE: snap cage vertices to sphere / cylinder / plane
from kerf_cad_core.geom.subd_project_primitive import (
    ProjectionReport,
    project_cage_to_sphere,
    project_cage_to_cylinder,
    project_cage_to_plane,
)
# BREP-EDGE-CURVE-FROM-FACE-PAIR: SSI edge curve extraction (Sederberg-Parry 1986 / PM §7)
from kerf_cad_core.geom.edge_curve_from_face_pair import (
    EdgeCurveResult,
    extract_edge_curve,
)

# BREP-EDGE-CURVE-EXTEND: extend a B-rep edge's NurbsCurve beyond its domain by ΔL mm,
# preserving G1 continuity at the join (Piegl & Tiller §10.4; Mortenson §3.7).
from kerf_cad_core.geom.edge_curve_extend import (
    EdgeExtendResult,
    extend_edge_curve,
)

# NURBS-NORMAL-CURVATURE-AT-POINT: normal curvature + principal curvatures (do Carmo §3 / Mortenson §10.4)
from kerf_cad_core.geom.normal_curvature import (
    NormalCurvatureReport,
    normal_curvature_at,
)
# GK-140: NURBS-surface offset distance field (Maekawa 1999; Piegl & Tiller §11.3)
from kerf_cad_core.geom.offset_distance_field import (
    DistanceFieldResult,
    compute_offset_distance_field,
)
# NURBS-CURVE-FOOTPRINT-ON-PLANE: orthographic projection of a 3-D NurbsCurve onto a plane
# (Piegl & Tiller §6.1; Mortenson §4.4) — drawing-projection, CNC toolpath flattening, PV layout
from kerf_cad_core.geom.curve_footprint_on_plane import (
    FootprintResult,
    project_curve_to_plane,
    lift_footprint_to_3d,
)

# BREP-FACE-PRINCIPAL-CURVATURE-VIZ: sample κ₁, κ₂ over a B-rep Face UV grid +
# SVG/PNG heatmap overlay (do Carmo §3.4 / Mortenson §6.5 / Pottmann-Wallner §4)
from kerf_cad_core.geom.principal_curvature_viz import (
    PrincipalCurvatureSample,
    PrincipalCurvatureVizResult,
    sample_principal_curvatures,
)

# NURBS-SURFACE-CURVATURE-MAP: scalar Gaussian/mean/|κ₁|/|κ₂| heatmap
# Complementary to principal_curvature_viz (scalar field vs per-sample κ₁/κ₂)
# (do Carmo §3.3 / Mortenson §6.5) — nurbs_sample_surface_curvature_map LLM tool
from kerf_cad_core.geom.surface_curvature_map import (
    CurvatureMapSpec,
    CurvatureMapResult,
    sample_surface_curvature_map,
)

# BREP-WIRE-CLOSED-CHECK: ordered edge-list closure + planarity (Mantyla §3; Hoffmann §4)
from kerf_cad_core.geom.wire_closed_check import (
    EdgeSegment,
    WireCheckReport,
    check_wire_closed,
)

__all__ = [
    "read_3dm","write_3dm","Rhino3dmReadError",
    "read_dxf","write_dxf","DxfReadError","DxfWriteError",
    "parting_line","undercut_faces","mold_split",
    # GK-P parting-line module
    "PartingLineResult","extract_parting_line","detect_undercuts","optimal_pull_direction",
    # GK-P Wave 4T
    "construct_parting_surface","construct_with_shutoff_inserts","validate_parting_surface",
    "dense_mesh_to_subd_cage",
    "DecimationReport",
    # SUBD-CAGE-PROJECT-TO-PRIMITIVE
    "ProjectionReport",
    "project_cage_to_sphere",
    "project_cage_to_cylinder",
    "project_cage_to_plane",
    "NurbsCurve",
    "NurbsSurface",
    "de_boor",
    "curve_derivative",
    "surface_evaluate",
    "surface_derivative",
    "surface_derivatives",
    "surface_normal",
    "knot_insertion",
    "degree_elevation",
    "curve_curve_intersection",
    "make_circle_nurbs",
    "make_line_nurbs",
    "nurbs_to_occt_curve",
    "occt_curve_to_nurbs",
    "nurbs_to_occt_surface",
    "occt_surface_to_nurbs",
    "sweep1",
    "sweep1_rmf",
    "sweep1_with_twist",
    "sweep1_variable_scale",
    # GK-77
    "sweep1_helical",
    "profile_along_path",
    "compute_rmf_frames",
    "sweep2",
    "sweep2_rmf",
    "sweep2_with_scaling",
    "sweep2_with_twist",
    "check_rail_compatibility",
    "normalize_rails",
    # unified dispatcher (GK-90 consolidation)
    "sweep_along_rails",
    "network_srf",
    "network_srf_with_compatibility",
    "network_srf_global",
    "network_srf_from_cross_sections",
    "approximate_network_srf",
    "validate_curves_for_skinning",
    "gordon_network_srf",
    "loft_surface",  # GK-P16
    "blend_srf",
    "blend_srf_g1",
    "blend_srf_g2","blend_srf_g3",
    # GK-62
    "g3_blend_trim_sew",
    "blend_srf_with_curves",
    "blend_srf_fillet",
    "validate_surface_blend",
    "compute_blend_surface_isocurves",
    "surface_health_check",
    "surface_boolean_robust",
    "BuildError",
    "surface_to_face",
    "surfaces_to_shell",
    "closed_shell_to_solid",
    "box_to_body",
    "cylinder_to_body",
    "sphere_to_body",
    "revolve_to_body",
    "extrude_to_body",
    # GK-57
    "extrude_face_to_body",
    # GK-16
    "loft_to_body",
    "sweep1_to_body",
    "sweep2_to_body",
    "SubDCage",
    "SubDSurface",
    "create_subd_primitive",
    "subd_extrude",
    "subd_bevel",
    "subd_loop_cut",
    "subd_set_crease",
    "to_subd_surface",
    "AmbiguousPoint",
    "select_side",
    "validate_body_post_trim",
    "TrimmedSurface",
    "trim_face_by_ssi","trim_face_by_nurbs_ssi","trim_face_analytic","SsiTrimResult","AnalyticTrimLoop",
    "untrim",
    "shrink",
    "fair_curve",
    "curvature_variance",
    "curvature_comb",
    # GK-98
    "curve_length",
    "arc_length_param",
    # GK-P: Precise NURBS arc-length (Gauss-Legendre + adaptive subdivision)
    "arc_length_precise",
    "arc_length_parametrize_gauss",
    "reparametrize_arclength_gauss",
    # GK-99
    "mid_curve",
    # GK-100
    "composite_curve",
    "split_composite",
    # GK-P: composite curve G2 audit + auto-blending
    "audit_composite_g2",
    "upgrade_to_g2",
    "composite_curvature_profile",
    "CompositeAuditResult",
    "JointAudit",
    # GK-101
    "geodesic",
    # GK-103
    "text_on_curve",
    "text_on_surface",
    # GK-P50: arc-length inversion
    "ArcLengthInvertResult",
    "invert_arc_length",
    # GK-11
    "curve_curve_intersect",
    "curve_surface_intersect",
    "surface_surface_intersect",
    # GK-34
    "fit_surface",
    # GK-99
    "mid_surface",
    # GK-12
    "curve_self_intersect",
    # GK-49 / NURBS-CONVERT-TO-IGES-144
    "write_iges",
    "read_iges",
    "IgesReadError",
    "IgesWriteError",
    "write_iges_trimmed_surface",
    "read_iges_trimmed_surface",
    "TrimmedSurfaceRecord",
    # GK-37
    "variable_radius_fillet_g1",
    # GK-62 oracle
    "curvature_rate_continuity_residual",
    "hausdorff_deviation","zebra_stripe","zebra_stripe_continuity_analyser",
    # GK-64
    "class_a_acceptance_harness",
    # GK-63
    "adaptive_refine_surface",
    # GK-65
    "isocurve_curvature_comb",
    # GK-92
    "draft_analysis","curvature_heatmap",
    # GK-95
    "reflection_lines",
    # GK-P11: isophote / environment-map analyser
    "isophote_analysis","isophote_continuity_analyser",
    # GK-138
    "continuity_audit",
    "occt_g3_residual_from_poles",
    "occt_g3_pole_roundtrip",
    # GK-P: post-Boolean continuity recovery
    "ContinuityRecoveryResult",
    "recover_continuity_at_seam",
    "recover_continuity_body",
    # GK-P curvature-comb
    "CurvaturePeak","CurvaturePeakReport",
    "curvature_comb_peaks","curvature_variance_metric","isophote_density_metric",
    # GK-P: curvature gradient field + ridge/valley tracing (Pottmann-Wallner §11)
    "CurvatureGradientResult","RidgeLine",
    "compute_curvature_gradient","compute_ridge_lines","compute_valley_lines",
    "curvature_gradient_field_visualization",
    "read_step","StepReadError",
    "write_step","StepWriteError",
    # GK-23
    "body_mass_props",
    # GK-P-VWC: volume-weighted centroid + inertia for non-uniform density
    "compute_centroid_density_field",
    "compute_inertia_density_field",
    "functionally_graded_centroid",
    "CentroidResult",
    "InertiaResult",
    # GK-54
    "mesh_autosurface",
    # GK-55
    "mesh_boolean_sealed","boolean_volume_oracle",
    # GK-109
    "mesh_decimate",
    # GK-110
    "mesh_repair",
    # GK-111
    "mesh_smooth",
    # GK-56
    "region_union","region_intersection","region_difference",
    "region_area","make_rect_loop","make_circle_loop",
    # GK-P32
    "hatch_region","HatchResult","HatchLine","material_hatch_pattern",
    # GK-44
    "MatchResult","match_surface_edge","verify_seam_g1_analytic","verify_seam_g2_analytic",
    "verify_seam_g3_analytic",
    # GK-45
    "shell_body",
    # GK-120
    "offset_body",
    # GK-46
    "draft_body",
    "rib_body",
    "wirecut_body",
    "pipe_body",
    # GK-06/07: closest-point / inversion
    "closest_point_curve",
    "closest_point_surface",
    "project_point_to_curve",
    "pull_curve_to_surface",
    # GK-18: sew
    "sew_faces",
    "sew_into_solid",
    # GK-18: boolean
    "body_union",
    "body_intersection",
    "body_difference",
    # GK-52
    "SubdToNurbsError",
    "subd_limit_positions",
    "subd_cage_to_limit_nurbs_body",
    "subd_cage_to_nurbs_body",
    "subd_cage_to_nurbs_patches",
    "nurbs_body_volume",
    "subd_mesh_volume",
    # GK-53
    "NurbsToSubdError",
    "nurbs_body_to_subd_cage",
    "nurbs_to_subd_cage",
    # GK-73
    "inset_face","InsetResult",
    # GK-76 / GK-P
    "wall_thickness_map",
    "ThicknessReport",
    "ThinWallWarning",
    "analyze_wall_thickness",
    "material_thickness_guideline",
    "flag_thin_walls",
    # GK-29
    "BlendResult",
    "blend_edge",
    "blend_edges",
    "blend_corner_vertex",
    # GK-132
    "blend_edge_chain_g3",
    # GK-74
    "BridgeResult",
    "bridge_loops",
    # GK-78
    "read_threemf",
    "write_threemf",
    "ThreeMFReadError",
    "ThreeMFWriteError",
    # GK-79
    "read_gltf",
    "write_gltf",
    "GltfReadError",
    "GltfWriteError",
    # GK-80
    "read_obj",
    "write_obj",
    "ObjReadError",
    "ObjWriteError",
    # GK-81
    "read_stl",
    "write_stl",
    "StlReadError",
    "StlWriteError",
    # GK-126
    "read_ply",
    "write_ply",
    "PlyReadError",
    "PlyWriteError",
    # GK-96
    "reverse_curve","reverse_surface",
    # GK-97
    "normalize_knots","reparametrize_curve","reparametrize_arclength",
    # GK-P: point-cloud parametrisation
    "parametrize_chord_length","parametrize_centripetal","parametrize_foley_nielsen",
    # GK-135
    "reduce_degree_curve","reduce_degree_surface",
    # GK-P: degree raise + lower (Cohen-Lyche-Schumaker 1985)
    "degree_raise_curve","degree_raise_surface",
    "degree_lower_curve","degree_lower_surface",
    "elevate_to_match",
    # NURBS-CURVE-DEGREE-LOWER: Piegl-Tiller §6.5 + Schumaker §6
    "DegreeLowerResult","lower_curve_degree",
    # GK-102
    "remove_knot","minimal_cp_refit",
    # GK-83 / GK-P-NURBS-OFFSET
    # GK-P: NURBS seam control
    "SeamInfo","detect_seam","shift_seam","align_seam_to_curve",
    # GK-83
    "surface_offset",
    "offset_surface",
    "detect_self_intersection",
    "trim_self_intersection_loops",
    # GK-P Wave 4P
    "UnsafeRegion",
    "GracefulOffsetResult",
    "safe_offset_distance",
    "offset_with_local_refinement",
    "graceful_offset",
    # GK-P: 2D curve offset (Tiller-Hanson 1984 + Piegl-Tiller §10.7 approx)
    "Offset2DResult",
    "offset_curve_2d",
    "offset_nurbs_curve_2d",
    "detect_self_intersection_2d",
    "trim_self_intersections_2d",
    "offset_loop_2d",
    # GK-87
    "linear_pattern",
    "circular_pattern",
    "path_pattern",
    # GK-84
    "split_body_by_plane",
    "split_body_by_surface",
    # GK-89
    "knife_face",
    # GK-86
    "replace_face",
    # GK-88
    "subd_loop_slide",
    "subd_edge_slide",
    # GK-105
    "subd_vertex_slide",
    # GK-106
    "subd_edge_split",
    # GK-107
    "subd_set_bevel_weight",
    # GK-108
    "loop_subdivide",
    # GK-P SubD boundary→curve snap
    "BoundaryLoop",
    "BoundarySnapResult",
    "extract_boundary_loops",
    "snap_boundary_to_curve",
    # GK-93
    "detect_symmetry",
    # GK-85
    "simplify_body",
    "heal_body",
    # GK-82
    "imprint_curve_on_face",
    "imprint_body",
    "ImprintTag",
    "ImprintResult",
    # GK-90
    "sweep_n",
    "loft_with_guides_sweep_n",  # GK-P16
    # GK-P variable rail-tangent Gordon loft (Piegl-Tiller §10.4.3)
    "loft_with_rails_variable",
    "extract_rail_tangents",
    "validate_rail_tangent_compatibility",
    # GK-91
    "K_FACTOR_TABLE",
    "bend_allowance",
    "bend_sheet",
    "unfold_sheet",
    # GK-75
    "drill_hole",
    "counterbore",
    "countersink",
    "tapped_hole",
    # GK-122
    "interference",
    # GK-129
    "iso_metric_thread",
    "acme_thread",
    # GK-130
    "coil_spring",
    # GK-112
    "body_sdf",
    "sdf_sample",
    # GK-113
    "marching_cubes",
    # GK-114
    "voxel_union",
    "voxel_intersection",
    "voxel_difference",
    # GK-128
    "involute_gear","cycloid_gear",
    # GK-SUBD-LIMIT-INTEGRAL-METRIC
    "SubDIntegralReport",
    "integrate_area",
    "integrate_mean_curvature",
    "integrate_gaussian_curvature",
    "compute_subd_integrals",
    # GK-115
    "gyroid","schwarz_p","octet_truss","kelvin_cell",
    "fischer_koch_s","iwp","f_rd","bcc_lattice","fcc_lattice",
    # GK-116
    "lattice_fill",
    # GK-117
    "tpms_sheet",
    # GK-123
    "clearance",
    # GK-124
    "solve_mate",
    # GK-131
    "tangent_edge_chain",
    # GK-P fillet chain propagation
    "EdgeChain",
    "identify_fillet_chains",
    "apply_fillet_chain",
    "auto_fillet_all_edges",
    # GK-136
    "tetrahedralize",
    # GK-133 / ISO 10303-224
    "recognize_features",
    "recognize_features_iso",
    "classify_hole",
    "feature_to_machining_op",
    "Feature",
    "HoleInfo",
    "FeatureRecognitionResult",
    # GK-134
    "push_pull_face",
    "move_face",
    # GK-137
    "reconstruct_mesh",
    # GK-64: Class-A leading pass
    "LeadingReport",
    "run_leading_pass",
    # GK-140: NURBS freeform-surface fit (reverse-engineering)
    "nurbs_surface_fit",
    "FitError",
    "FitReport",
    # GK-P: Bezier extraction
    "BezierCurve",
    "BezierSurface",
    "extract_bezier_curve",
    "extract_bezier_surface",
    "reconstruct_from_beziers",
    # Variable-section edge blend (Vida-Martin-Varady 1994)
    "CrossSection",
    "variable_section_blend",
    "morph_cross_sections",
    "blend_cross_section_at",
    "blend_volume_estimate",
    # GK-P: N-sided patch
    "fit_network_patch",
    "fit_n_sided_g1_blend",
    "fairness_metric",
    # GK-P49: assembly interference detection (Möller 1997)
    "AABB",
    "InterferenceResult",
    "AssemblyInterferenceReport",
    "detect_interference_pair",
    "detect_interference_assembly",
    "compute_assembly_aabb",
    # GK-P49: geodesic distance via heat method
    "compute_geodesic_heat_method",
    "compute_geodesic_to_point",
    "compute_geodesic_path",
    # GK-P: NURBS rational conic detection + simplification
    "ConicInfo",
    "CircleParams",
    "detect_conic",
    "extract_canonical_circle",
    "simplify_conic_curve",
    # GK-P50: optimal NURBS surface reparametrization (LSCM + ARAP)
    "reparametrize_lscm",
    "reparametrize_arap",
    "distortion_metric",
    "reparam_compare",
    # GK-P49: characteristic curve extraction (Pottmann-Wallner §11)
    "CharacteristicCurves",
    "Curve2D",
    "extract_characteristic_curves",
    "trace_curve_from_seed",
    # GK-P SubD LOD chain + progressive mesh
    "SubdLodChain",
    "ProgressiveMesh",
    "EdgeCollapseRecord",
    "VertexSplitRecord",
    "generate_subd_lod_chain",
    "generate_progressive_mesh",
    "pick_lod_for_view",
    # GK-P: arc-length-preserving offset (Klass 1980 / Maekawa 1999)
    "offset_curve_arclength_preserving",
    "exact_arclength_match_error",
    "compare_offsets",
    # GK-P: NURBS↔mesh max deviation
    "SurfaceMeshDeviation",
    "hausdorff_surface_to_mesh",
    "bidirectional_hausdorff",
    "max_deviation_visualization",
    # GK-P: SubD cage derivation from dense mesh
    "CageResult",
    "derive_cage_from_mesh",
    "fit_subd_to_mesh",
    "recommend_subd_topology",
    # GK-P-IV: interference volume metric
    "InterferenceVolume",
    "compute_interference_volume",
    "interference_severity_score",
    "pairwise_interference_assembly",
    # GK-P-normap: SubD normal-color map + GLB vertex-color export
    "compute_normal_color_map",
    "compute_face_color_from_normals",
    "export_subd_with_normals_glb",
    # GK-P-MI: Assembly mate inspector
    "MateConstraint",
    "MateValidation",
    "AssemblyValidation",
    "validate_mate",
    "auto_detect_potential_mates",
    "validate_assembly_mates",
    # GK-P: Curvature heatmap PNG/SVG export
    "render_curvature_heatmap",
    "export_heatmap_png",
    "export_heatmap_svg",
    "generate_curvature_legend",
    # BREP-CONNECT-INSPECTOR: radial-edge connectivity (Weiler 1985 + Mantyla 1988)
    "ConnectivityReport",
    "inspect_connectivity",
    "is_manifold_closed",
    # SUBD-CAGE-RING-FROM-EDGE
    "EdgeRingResult",
    "compute_edge_ring",
    # SUBD-LIMIT-MESH-EXPORT-OBJ
    "export_limit_to_obj",
    "parse_subd_obj",
    # NURBS-CURVE-FOOTPRINT-ON-PLANE: orthographic projection → 2-D UV footprint
    "FootprintResult",
    "project_curve_to_plane",
    "lift_footprint_to_3d",
    # BREP-FACE-PRINCIPAL-CURVATURE-VIZ: κ₁/κ₂ grid + SVG/PNG heatmap
    "PrincipalCurvatureSample",
    "PrincipalCurvatureVizResult",
    "sample_principal_curvatures",
    # NURBS-CURVE-CIRCLE-FIT: Kasa (1976) + Taubin (1991) algebraic circle fit
    "CircleFitResult",
    "fit_circle_to_curve",
    # NURBS-CURVE-INFLECTION: κ-sign change inflection point detection (v2 + legacy)
    "InflectionPoint",
    "CurveInflectionReport",
    "find_curve_inflections",
    "InflectionResult",
    "find_curve_inflections_v1",
    # NURBS-SURFACE-CURVATURE-MAP: scalar K/H/|κ₁|/|κ₂| heatmap (do Carmo §3.3 / Mortenson §6.5)
    "CurvatureMapSpec",
    "CurvatureMapResult",
    "sample_surface_curvature_map",
    # BREP-WIRE-CLOSED-CHECK: ordered edge-list closure + planarity (Mantyla §3; Hoffmann §4)
    "EdgeSegment",
    "WireCheckReport",
    "check_wire_closed",
]

# Variable-section edge blend (Vida-Martin-Varady 1994 §4)
from kerf_cad_core.geom.edge_blend import (  # noqa: E402
    CrossSection,
    variable_section_blend,
    morph_cross_sections,
    blend_cross_section_at,
    blend_volume_estimate,
)

# GK-122: interference / collision detection
from kerf_cad_core.geom.assembly import interference  # noqa: E402

# GK-112: signed distance field from a B-rep Body + trilinear sampler.
# GK-113: marching cubes (SDF / scalar grid → watertight mesh).
# GK-114: voxel boolean / CSG (union / intersection / difference on SDF grids).
from kerf_cad_core.geom.sdf import body_sdf, sdf_sample, marching_cubes, voxel_union, voxel_intersection, voxel_difference

# GK-115: lattice unit-cell library (gyroid, Schwarz-P, octet truss, Kelvin cell,
#          Fischer-Koch S, IWP, F-RD, BCC, FCC)
# GK-116: lattice fill of a Body to a target relative density
# GK-117: TPMS implicit sheet (triply-periodic minimal surface meshed at thickness)
from kerf_cad_core.geom.lattice import (
    gyroid, schwarz_p, octet_truss, kelvin_cell, lattice_fill, tpms_sheet,
    fischer_koch_s, iwp, f_rd, bcc_lattice, fcc_lattice,
)
# GK-123: clearance / minimum-gap analysis
from kerf_cad_core.geom.assembly import clearance  # noqa: E402
# GK-124: mate constraint solver
from kerf_cad_core.geom.assembly import solve_mate  # noqa: E402

# GK-131: tangent-chain edge auto-select
from kerf_cad_core.geom.fillet_solid import tangent_edge_chain
# GK-P (fillet chain propagation — Vida-Martin-Varady 1994)
from kerf_cad_core.geom.fillet_chain import (
    EdgeChain,
    identify_fillet_chains,
    apply_fillet_chain,
    auto_fillet_all_edges,
)
# GK-136: Delaunay volume mesh (tetrahedralization) for FEM hand-off
from kerf_cad_core.geom.tetmesh import tetrahedralize
# GK-133 / ISO 10303-224: feature recognition (hole / pocket / boss / fillet / chamfer)
from kerf_cad_core.geom.feature_recognition import (  # noqa: E402
    recognize_features,
    recognize_features_iso,
    classify_hole,
    feature_to_machining_op,
    Feature,
    HoleInfo,
    FeatureRecognitionResult,
)

# NURBS dependency graph + smart-edit propagation (Hoffmann-Joan-Arinyo 2002)
from kerf_cad_core.geom.dependency_graph import (
    NodeKind,
    GraphNode,
    DependencyGraph,
    build_graph_for_body,
    smart_edit,
)

# GK-127 / GK-P39: 3DM (Rhino OpenNURBS) read + write
from kerf_cad_core.geom.io.rhino3dm import (
    read_3dm,
    write_3dm,
    Rhino3dmReadError,
)
# GK-134 / GK-P18: direct modelling — push-pull / move-face / delete-face
from kerf_cad_core.geom.direct_edit import push_pull_face, move_face, delete_face
# GK-137: point-cloud → mesh reconstruction (ball-pivoting / Poisson-lite)
from kerf_cad_core.geom.recon import reconstruct_mesh  # noqa: E402
# GK-140: NURBS freeform-surface fit from segmented point clouds (reverse-engineering)
from kerf_cad_core.geom.nurbs_surface_fit import (  # noqa: E402
    nurbs_surface_fit,
    FitError,
    FitReport,
)
# SUBD-EXPORT-PLY: CC limit-surface → Stanford PLY (ASCII + binary little-endian)
# Ref: https://en.wikipedia.org/wiki/PLY_(file_format); Turk (1994) Stanford.
# Honest (v1): geometry only — no colour, normals, texture coords; no big-endian.
from kerf_cad_core.geom.subd_export_ply import (  # noqa: E402
    export_limit_to_ply,
    parse_ply as parse_subd_ply,
)
# GK-64: Class-A leading quality pass (comb-peak + zebra-break + G3-dropout)
from kerf_cad_core.geom.leading import LeadingReport, run_leading_pass

# GK-P: Bezier extraction — B-spline → multi-Bezier patch decomposition
# (Piegl & Tiller §5.6; foundational for FEA mesh handoff, GPU rendering, IGES)
from kerf_cad_core.geom.bezier_extract import (
    BezierCurve,
    BezierSurface,
    extract_bezier_curve,
    extract_bezier_surface,
    reconstruct_from_beziers,
)
# GK-P (N-sided patch): Coons + Gregory + Hosaka-Kimura N-sided patch fit
from kerf_cad_core.geom.network_surface import (
    fit_network_patch,
    fit_n_sided_g1_blend,
    fairness_metric,
)
# GK-P49: assembly-level interference detection (Möller 1997 + AABB broad-phase)
from kerf_cad_core.geom.assembly_interference import (  # noqa: E402
    AABB,
    InterferenceResult,
    AssemblyInterferenceReport,
    detect_interference_pair,
    detect_interference_assembly,
    compute_assembly_aabb,
)
# GK-P49: geodesic distance via heat method (Crane, Weischedel & Wardetzky 2013)
from kerf_cad_core.geom.subd_geodesic import (
    compute_geodesic_heat_method,
    compute_geodesic_to_point,
    compute_geodesic_path,
)
# GK-P: NURBS rational conic detection + simplification (Lee 1987 / Piegl-Tiller §7.2)
from kerf_cad_core.geom.conic_detect import (
    ConicInfo,
    CircleParams,
    detect_conic,
    extract_canonical_circle,
    simplify_curve as simplify_conic_curve,
)
# GK-P50: optimal NURBS surface reparametrization (LSCM + ARAP)
from kerf_cad_core.geom.nurbs_param_optimal import (
    reparametrize_lscm,
    reparametrize_arap,
    distortion_metric,
    reparam_compare,
)
# GK-P49: characteristic curve extraction (Pottmann-Wallner §11)
from kerf_cad_core.geom.characteristic_curves import (
    CharacteristicCurves,
    Curve2D,
    extract_characteristic_curves,
    trace_curve_from_seed,
)
# GK-P (SubD LOD): automatic LOD chain + progressive mesh (Hoppe 1996)
from kerf_cad_core.geom.subd_automatic_lod import (
    SubdLodChain,
    ProgressiveMesh,
    EdgeCollapseRecord,
    VertexSplitRecord,
    generate_subd_lod_chain,
    generate_progressive_mesh,
    pick_lod_for_view,
)
# GK-P (arc-length-preserving offset): Klass 1980 / Maekawa 1999
from kerf_cad_core.geom.exact_length_offset import (
    offset_curve_arclength_preserving,
    exact_arclength_match_error,
    compare_offsets,
)
# GK-P: NURBS↔mesh max deviation (Aspert 2002 / Cignoni 1998) — class-A RE acceptance
from kerf_cad_core.geom.surface_mesh_deviation import (
    SurfaceMeshDeviation,
    hausdorff_surface_to_mesh,
    bidirectional_hausdorff,
    max_deviation_visualization,
)
# GK-P: SubD cage derivation from dense mesh (Lee-Moreton-Hoppe 2000)
from kerf_cad_core.geom.subd_from_mesh import (
    CageResult,
    derive_cage_from_mesh,
    fit_subd_to_mesh,
    recommend_subd_topology,
)
# GK-P-IV: interference volume metric (Stroud-Nagy §10)
from kerf_cad_core.geom.interference_volume import (  # noqa: E402
    InterferenceVolume,
    compute_interference_volume,
    interference_severity_score,
    pairwise_interference_assembly,
)
# GK-P-normap: SubD limit-surface normal-to-color map + GLB vertex-color export
from kerf_cad_core.geom.subd_normal_color import (
    compute_normal_color_map,
    compute_face_color_from_normals,
    export_subd_with_normals_glb,
)
# GK-P-MI: Assembly mate inspector + joint geometry validation
from kerf_cad_core.geom.mate_inspector import (
    MateConstraint,
    MateValidation,
    AssemblyValidation,
    validate_mate,
    auto_detect_potential_mates,
    validate_assembly_mates,
)
# GK-P: Curvature heatmap PNG/SVG export (Wave 4DD extension)
from kerf_cad_core.geom.curvature_heatmap import (
    render_curvature_heatmap,
    export_heatmap_png,
    export_heatmap_svg,
    generate_curvature_legend,
)
# Restore the curvature_heatmap *function* from surface_analysis (the submodule
# import above sets the attribute to the module object; we need the function).
from kerf_cad_core.geom.surface_analysis import curvature_heatmap  # noqa: E402 (re-bind)
# BREP-CONNECT-INSPECTOR: radial-edge connectivity classification
# (Weiler 1985 §3 + Mantyla 1988 §6 Euler operators) — pure-Python, no OCCT.
from kerf_cad_core.geom.brep_connect_inspector import (  # noqa: E402
    ConnectivityReport,
    inspect_connectivity,
    is_manifold_closed,
)
# GK-P NURBS-DERIVATIVE-FIELD-VISUAL: 1st partial-derivative vector-field arrow-plot PNG/SVG
from kerf_cad_core.geom.derivative_field_viz import (
    render_derivative_field_png,
    render_derivative_field_svg,
)
# BREP-SUM-EDGE-LENGTHS: total edge length + kind/curve-type breakdowns for cutting-cost
# (Weiler 1985 §3 radial-edge classification + Gauss-Legendre arc integration)
from kerf_cad_core.geom.brep_edge_metrics import (  # noqa: E402
    EdgeKindMetrics,
    EdgeCurveTypeMetrics,
    EdgeMetricsReport,
    total_edge_length,
    edge_length_by_kind,
    edges_by_curve_type,
    compute_edge_metrics,
)
# GK-SUBD-LIMIT-INTEGRAL-METRIC: exact-as-feasible integrals over CC limit surface
from kerf_cad_core.geom.subd_limit_integrals import (  # noqa: E402
    SubDIntegralReport,
    integrate_area,
    integrate_mean_curvature,
    integrate_gaussian_curvature,
    compute_subd_integrals,
)
# BREP-FACE-AREA-WEIGHTED-CENTROID: surface centroid of a B-rep shell/solid
# (Gauss-Legendre 16×16 per face; distinct from volumetric body_mass_props centroid)
# BREP-FACE-AREA-WEIGHTED-CENTROID: surface centroid of a B-rep shell/solid
# (Gauss-Legendre 16x16 per face; distinct from volumetric body_mass_props centroid)
from kerf_cad_core.geom.face_centroid import (  # noqa: E402
    face_area,
    face_centroid,
    surface_centroid,
)
# NURBS-EXTRACT-ISO-CURVES: Piegl-Tiller §5.3 knot-insertion iso-curve extraction
from kerf_cad_core.geom.iso_curve_extract import (
    extract_iso_curve_u,
    extract_iso_curve_v,
    extract_iso_grid,
)
# SUBD-EXPORT-OPENSUBDIV-USD: USD Mesh prim (.usda ASCII) — catmullClark + creases
# (Pixar HdStorm / Houdini / Maya; USDA ASCII only, no USDC binary)
from kerf_cad_core.geom.subd_export_usd import (
    export_subd_to_usda,
    write_subd_usda,
    parse_usda_subd,
)
# NURBS-CURVE-CURVATURE-OSCULATING-CIRCLE: osculating circle at parameter t
# (do Carmo §1.5; κ = |C′×C″|/|C′|³; center = C(t) + (1/κ)·N(t))
from kerf_cad_core.geom.osculating_circle import (
    OsculatingCircle,
    osculating_circle,
    osculating_circles_along,
)
# BREP-FACE-NEIGHBOR-WALK: face-adjacency traversal for CNC routing, geodesic
# shortest-path, paint-area planning; edge-sharing adjacency only (Weiler 1985 §3)
from kerf_cad_core.geom.face_neighbor_walk import (  # noqa: E402
    FaceAdjacencyGraph,
    face_adjacency_graph,
    face_neighbors,
    bfs_from_face,
    shortest_face_path,
)
# SUBD-LIMIT-WALK-ALONG-EDGES: sample CC limit-surface curve along cage-edge chain
# (boundary=cage, creased=crease curve, smooth=limit surface arc; arc_length via segment sum)
from kerf_cad_core.geom.subd_edge_walk import (  # noqa: E402
    SubDEdgeWalk,
    walk_along_cage_edges,
)
# BREP-FACE-PLANARITY-CHECK: SVD best-fit plane + max deviation + score
# (Pratt 1987 §3; Eberly §6.6 orthogonal regression) — check_face_planarity / PlanarityReport
from kerf_cad_core.geom.face_planarity import (
    PlanarityReport,
    check_face_planarity,
)
# BREP-VOLUME-OF-HALF-SPACE-INTERSECTION: divergence theorem (Mortenson §11.6)
from kerf_cad_core.geom.half_space_volume import (
    HalfSpaceVolumeReport,
    compute_half_space_volume,
    volume_above_plane,
    volume_below_plane,
)
# NURBS-COMPOSITE-TANGENT-MATCH: G1/G2 seam matching for composite curve chains
# (Klass 1980 §3; Farin §8.4; Piegl-Tiller §7.3)
from kerf_cad_core.geom.composite_tangent_match import (
    CompositeMatchResult,
    match_composite_tangents,
)
# BREP-EDGE-CONVEX-CONCAVE-CLASSIFY: dihedral-angle classification of interior edges
# (Hoffmann 1989 §5.3; Mantyla 1988 §7.4) — classify_edges / EdgeConvexityReport
# BREP-EDGE-CONVEXITY: sampled-normals classify_edge_convexity / EdgeSample
# (Mantyla 1988 §5) — classify_edge_convexity / SampledEdgeConvexityReport
from kerf_cad_core.geom.edge_convexity import (  # noqa: E402
    EdgeClass,
    EdgeConvexityReport,
    classify_edges,
    classify_body_edges,
    EdgeSample,
    SampledEdgeConvexityReport,
    classify_edge_convexity,
)
# BREP-HOLE-RECOGNITION-FROM-LOOPS: AAG-based recognition of through-hole, blind hole,
# counterbore, countersink, possibly-threaded holes from B-rep inner loops
# (Joshi-Chang 1988; Han-Pratt-Regli 2000) — recognize_holes / HoleFeature
from kerf_cad_core.geom.hole_recognition import (  # noqa: E402
    HoleFeature,
    recognize_holes,
    recognize_holes_in_body,
)
# SUBD-SYMMETRY-DETECT: PCA mirror + rotational + spherical symmetry
# (Mitra-Guibas-Pauly 2006; Podolak et al. 2006)
from kerf_cad_core.geom.subd_symmetry import (
    SymmetryPlane,
    RotationAxis,
    SymmetryReport,
    SymmetryResult,
    detect_symmetry as subd_detect_symmetry_full,
    detect_mirror_symmetry,
    enforce_mirror_symmetry,
    mirror_edit,
)
# BREP-FILLET-RECOMMEND-RADIUS: per-edge fillet radius recommendation engine
# (Peterson 1974 §2.3; Boothroyd-Dewhurst 2002 §4) — recommend_fillet_radius / RadiusRecommendation
from kerf_cad_core.geom.fillet_recommend_radius import (  # noqa: E402
    FilletRadiusContext,
    RadiusRecommendation,
    recommend_fillet_radius,
    recommend_fillet_radii_for_body,
)
# NURBS-FAIR-COMPOSITE-CURVE: global curvature-variance fairing for poly-NURBS chains
# (Greiner-Hormann 1996; Sapidis-Farin 1990 §3; Klass 1980 §3 seam G1)
# NURBS-FAIR-COMPOSITE-CURVE: global curvature-variance fairing for poly-NURBS chains
# (Greiner-Hormann 1996 §3.2; Sapidis-Farin 1990 §3; Klass 1980 §3 G1 seam)
from kerf_cad_core.geom.composite_fair import (
    CompositeFairResult,
    fair_composite,
)
# SUBD-CAGE-RING-FROM-EDGE: edge ring traversal on CC quad cages
# (Maya/Blender Bridge ring pattern — opposite edges across each quad face)
# Honest caveat: pure-quad cages only; non-quad face → is_degenerate=True.
from kerf_cad_core.geom.subd_edge_ring import (  # noqa: E402
    EdgeRingResult,
    compute_edge_ring,
)
# BREP-SHELL-WALL-CHECK: post-shell wall-thickness verification vs process spec
# (Menges 2001 §3.3; Boothroyd-Dewhurst §5; FDM/SLA nozzle-diameter rules)
# Honest caveat: static rule-based only — no CFD or mould-fill simulation.
from kerf_cad_core.geom.shell_wall_check import (  # noqa: E402
    FaceWallResult,
    ShellWallReport,
    check_shell_walls,
)
# BREP-CHAMFER-RECOMMEND-SIZE: per-edge chamfer dimension recommendation engine
# (Drozda-Wick §3-7/§3-7.3; DIN 74:1974 Form A/B; ISO 13715:2017 §5)
# Criteria: deburring 0.5mm×45°; chamfer mill; DIN 74 countersink; cosmetic 1.5mm×45°.
# Asymmetric chamfers (e.g. 30°×60°, 1×2 leg ratio) supported via
# recommend_asymmetric_chamfer() and the ratio= parameter on recommend_chamfer_size().
from kerf_cad_core.geom.chamfer_recommend_size import (  # noqa: E402
    AsymmetricChamferRecommendation,
    ChamferContext,
    ChamferRecommendation,
    DIN74_COUNTERSINK_TABLE,
    recommend_asymmetric_chamfer,
    recommend_chamfer_size,
    recommend_chamfer_sizes_for_body,
)
# SUBD-LIMIT-MESH-EXPORT-OBJ: CC limit-surface → Wavefront OBJ (v/vn/f; geometry only)
# Ref: https://en.wikipedia.org/wiki/Wavefront_.obj_file
# Honest: geometry only — no MTL, no vt; vertex normals via area-weighted cross-product,
# not Stam exact eigenbasis.
from kerf_cad_core.geom.subd_export_obj import (  # noqa: E402
    export_limit_to_obj,
    parse_obj as parse_subd_obj,
)
# BREP-TOPOLOGY-EULER-CHECK: generalised Euler-Poincaré formula verifier
# (Mantyla 1988 §6 + Hoffmann 1989 §5) — verify_euler_topology,
# verify_euler_topology_from_dict, EulerCheckReport
from kerf_cad_core.geom.topology_euler_check import (
    EulerCheckReport,
    verify_euler_topology,
    verify_euler_topology_from_dict,
)
# SUBD-LIMIT-INTEGRAL-GAUSS-BONNET-CHECK: verify ∫∫K dA = 2π·χ on a closed
# Catmull-Clark limit surface (do Carmo §4.5; Edelsbrunner-Harer 2010 §1).
# Honest: valid=False for surfaces with boundary (geodesic-curvature term excluded).
from kerf_cad_core.geom.subd_gauss_bonnet_check import (  # noqa: E402
    GaussBonnetCheckReport,
    verify_gauss_bonnet,
)
# SUBD-EXPORT-PLY: CC limit-surface → Stanford PLY (ASCII + binary little-endian)
# Ref: https://en.wikipedia.org/wiki/PLY_(file_format); Turk (1994) Stanford.
# Honest (v1): geometry only — no colour, normals, texture coords; no big-endian.
from kerf_cad_core.geom.subd_export_ply import (  # noqa: E402
    export_limit_to_ply,
    parse_ply as parse_subd_ply,
)
# BREP-SOLID-CONTAINS-POINT: ray-casting Jordan-curve inside/outside test on B-rep solids.
# (Mortenson §11.5; Ericson 2005 §5.1; O'Rourke §7.4)
# Honest: degenerate ray hits handled by fallback direction; parametric faces use
# UV-grid triangulation approximation (uv_samples²); non-manifold shells may give
# unreliable parity.
from kerf_cad_core.geom.solid_contains_point import (  # noqa: E402
    ContainmentResult,
    solid_contains_point,
)
# SUBD-EXPORT-GLTF: CC limit-surface → glTF 2.0 (.gltf JSON + base64 buffer or .glb binary container)
# Ref: Khronos glTF 2.0 — https://www.khronos.org/gltf/ (§5.1 asset, §5.9 buffers/accessors, §5.12 meshes)
# Honest (v1): geometry only — no materials, normals, textures, animations, skinning; quads fan-triangulated;
# pure-Python (json + struct); no Draco compression.
from kerf_cad_core.geom.subd_export_gltf import (  # noqa: E402
    export_limit_to_gltf,
    parse_gltf as parse_subd_gltf,
)
# BREP-MESH-MASS-PROPS: volume, centroid, inertia tensor from triangle mesh.
# (Mirtich 1996 §3; Mortenson §11.4)
# BREP-MESH-MASS-PROPS: volume, centroid, inertia tensor from triangle mesh.
# (Mirtich 1996 §3; Mortenson §11.4; Eberly 2002)
# Honest: closed orientable mesh with outward normals required; open/inverted → ValueError.
from kerf_cad_core.geom.mass_props_mesh import (  # noqa: E402
    MassPropsReport,
    compute_mesh_mass_props,
)
# SUBD-EXPORT-STEP: CC limit-surface → STEP AP242 faceted B-rep (.stp ASCII)
# Ref: ISO 10303-242:2020 (AP242 ed. 2), ISO 10303-42:2022, ISO 10303-21:2016.
# Honest: each subdivided polygon is a flat PLANE face (not smooth NURBS).
# STEP has no native SubD primitive; this emits a polyhedral B-rep.
# LLM tool: subd_export_limit_to_step.
from kerf_cad_core.geom.subd_export_step import (  # noqa: E402
    export_limit_to_step,
    parse_step_subd,
)
# BREP-FACE-COMPATIBLE-RESPLIT: insert knots into two adjacent NURBS faces so
# their shared-edge knot vectors become identical — prerequisite for surface
# sewing, BREP repair, and Boolean operations.
# (Piegl-Tiller §6.5 "Compatibility of Surfaces"; Hoffmann 1989 §6)
# LLM tool: brep_make_faces_compatible.
from kerf_cad_core.geom.face_compatible_resplit import (  # noqa: E402
    CompatibilityResult,
    make_faces_compatible,
)
# NURBS-CURVE-RESAMPLE-UNIFORM: resample a NurbsCurve at uniform arc-length
# intervals via arc-length parameterisation inversion (Piegl-Tiller §9.4 +
# Patrikalakis-Maekawa §3.5; Gauss-Legendre quadrature for length).
# LLM tool: nurbs_curve_resample_uniform.
from kerf_cad_core.geom.curve_resample_uniform import (  # noqa: E402
    ResampleResult,
    resample_uniform_arc_length,
)
# SUBD-CAGE-SUBDIVIDE-EDGE: localized single-edge refinement (not a full CC pass).
# Ref: Catmull & Clark 1978; Stam 1998 §4 local refinement; Maya polySplit API.
# Honest: quad-cage only for clean topology; non-quad sets has_non_quad_input flag.
# LLM tool: subd_subdivide_edge.
from kerf_cad_core.geom.subd_subdivide_edge import (  # noqa: E402
    SubdivideEdgeResult,
    subdivide_edge,
)
# BREP-CURVE-ON-SURFACE-PROJECTION: Newton-Raphson UV projection (P&T §6.1 / PM §3.3)
from kerf_cad_core.geom.curve_on_surface_robust import (
    CurveOnSurfaceResult,
    project_curve_to_surface,
)
# NURBS-SURFACE-AREA-EXACT: exact surface area via first-fundamental-form integrand
# A = ∫∫ sqrt(EG-F²) du dv (do Carmo §2.5 / Mortenson §10.4).
# 5×5 Gauss-Legendre per knot-span cell + adaptive subdivision.
# LLM tool: nurbs_surface_area_exact.
from kerf_cad_core.geom.surface_area_exact import (  # noqa: E402
    SurfaceAreaReport,
    compute_exact_surface_area,
)
# BREP-FACE-AREA-EXACT: exact area of a B-rep Face (NurbsSurface) via first-fundamental-form
# A = ∫∫ sqrt(EG-F²) du dv (do Carmo §2.5; Piegl & Tiller §10.3; Farin §11.2).
# gauss_order×gauss_order GL per knot-span cell + adaptive subdivision.
# LLM tool: brep_compute_face_area_exact.
# CAVEAT: trimmed faces use bounding-rectangle approximation (v1 — trim curves not respected).
from kerf_cad_core.geom.face_area_exact import (  # noqa: E402
    FaceAreaResult,
    compute_face_area_exact,
)
# NURBS-CURVE-CURVATURE-PROFILE-EXPORT: κ(t) → CSV/SVG/PNG (Farin §11.6; Sapidis §3)
from kerf_cad_core.geom.curvature_profile_export import (  # noqa: E402
    CurvatureProfileResult,
    export_curvature_profile,
    export_curvature_profile_result,
    export_curvature_profile_csv,
)
# BREP-FACE-DEVELOPABLE-CHECK: Gaussian curvature sampling test for developability
# (do Carmo §3.6 "Ruled and Developable Surfaces"; Pottmann-Wallner §4)
# K = κ_1·κ_2 = 0 everywhere ↔ developable. LLM tool: brep_check_face_developable.
from kerf_cad_core.geom.face_developable_check import (  # noqa: E402
    DevelopabilityReport,
    check_face_developable,
)
# NURBS-CURVE-FRESNEL-PARAMETERIZE: re-parameterize a NurbsCurve so κ(s) ≈ α·s
# (Euler spiral / clothoid law). Road/rail transition curves, CNC toolpaths.
# Refs: Walton & Meek (2009); Bertolazzi & Frego (2015).
# LLM tool: nurbs_fresnel_parameterize_curve.
from kerf_cad_core.geom.fresnel_parameterize import (  # noqa: E402
    FresnelParameterizationResult,
    fresnel_parameterize_curve,
)
# NURBS-CURVE-EVOLUTE: locus of centres of osculating circles E(t)=C(t)+n̂(t)/κ(t).
# 2D curves only (3D Frenet-Serret evolutes not yet supported).
# Applications: cycloidal-gear design, cam-profile cusps, CNC offset analysis.
# Refs: do Carmo §1.6; Mortenson §4.2.
# LLM tool: nurbs_compute_curve_evolute.
from kerf_cad_core.geom.curve_evolute import (  # noqa: E402
    EvoluteResult,
    compute_curve_evolute,
)
from kerf_cad_core.geom.surface_cross_section import (  # noqa: E402
    SurfaceCrossSectionResult,
    compute_surface_cross_section,
)
# BREP-EDGE-CHAMFER-VARIABLE: linear-ramp chamfer strip along a 2D edge curve.
# (Piegl & Tiller §10.5 — Variable offsets; Mortenson §9.3 — Edge blends)
# HONEST: 2D polyline input only; 3D B-rep solid edge chamfer is P2/P3 scope.
# LLM tool: brep_generate_variable_chamfer.
from kerf_cad_core.geom.edge_chamfer_variable import (  # noqa: E402
    ChamferVariableSpec,
    ChamferVariableResult,
    generate_variable_chamfer,
)
# NURBS-CURVE-CIRCLE-FIT: Kasa (1976) + Taubin (1991) circle fit for 2D NurbsCurves
# — snap-to-circle in sketcher, circular region detection, near-arc classification.
from kerf_cad_core.geom.curve_circle_fit import CircleFitResult, fit_circle_to_curve
# NURBS-CURVE-LINE-FIT: total-least-squares (TLS/SVD) straight-line fit for 2D NurbsCurves
# — linear-segment detection, snap-to-line, near-straight edge classification.
# Refs: Press §15.7 (TLS); Lawson-Hanson §6 (SVD geometric fitting).
from kerf_cad_core.geom.curve_line_fit import LineFitResult, fit_line_to_curve
# BREP-EDGE-FACE-NORMAL-FLIP: detect and fix B-rep faces with inconsistent outward normals.
# Iterative neighbour-consensus voting: for each edge with two adjacent faces, check normal
# compatibility; BFS-propagate flip signal from seed face (Mantyla §6.4 / Hoffmann §3).
# Returns corrected normals + list of flipped face indices.
# HONEST: isolated faces (no neighbours) cannot be voted; absolute orientation seeded
# from seed face; not a geometric B-rep heal.
# LLM tool: brep_detect_and_flip_face_normals.
from kerf_cad_core.geom.face_normal_flip import (  # noqa: E402
    FaceNormalFlipResult,
    detect_and_flip_face_normals,
)
# NURBS-CURVE-CONIC-DETECT: classify a 2-D NurbsCurve (or raw point set) as
# circle|ellipse|parabola|hyperbola|line|free_form via algebraic conic fitting
# (general conic Ax²+Bxy+Cy²+Dx+Ey+F=0, SVD null-space) and discriminant B²−4AC.
# HONEST: algebraic fit is susceptible to noise bias; for production-quality circle
# detection use Pratt/Taubin in curve_circle_fit.py.
# Refs: Pratt (1987) SIGGRAPH §3; Fitzgibbon-Pilu-Fisher (1999) IEEE TPAMI 21(5):476–480.
# LLM tool: nurbs_detect_conic_type.
from kerf_cad_core.geom.curve_conic_detect import (  # noqa: E402
    ConicDetectResult,
    detect_conic_type,
)
# NURBS-CURVE-INFLECTION: inflection points of a 2D NurbsCurve where κ_signed
# changes sign (Piegl-Tiller §5.3; Farin §10.6; do Carmo §1.5; Sapidis §3).
# Used for Class-A fairness analysis (naval/automotive), sketch QC, toolpath
# transitions. v2 API: InflectionPoint + CurveInflectionReport with fairness flag.
# LLM tool: nurbs_find_curve_inflections.
from kerf_cad_core.geom.curve_inflection import (  # noqa: E402
    InflectionPoint,
    CurveInflectionReport,
    find_curve_inflections,
    InflectionResult,
    find_curve_inflections_v1,
)
# BREP-VERTEX-DEGREE-CHECK: count incident edges per vertex; flag boundary
# (degree < expected) and non-manifold (degree > expected + 2) vertices.
# Degree histogram + irregular vertex list for topology repair triage.
# HONEST: edge-based degree only; does NOT analyse face-fan angular order
# or non-manifold edges. Refs: Mantyla 1988 §3.4; Hoffmann 1989 §4.
# LLM tool: brep_check_vertex_degrees.
from kerf_cad_core.geom.vertex_degree_check import (  # noqa: E402
    VertexDegreeReport,
    check_vertex_degrees,
)
# NURBS-SURFACE-SHEAR-OFFSET: global linear shear transform on NurbsSurface
# control points (Mortenson §4.8; Piegl & Tiller §6.1).  Useful for
# compensating workpiece warp during finish-machining post-processing.
# HONEST: linear shear only — non-uniform warp needs per-point deformation.
# LLM tool: nurbs_apply_surface_shear_offset.
from kerf_cad_core.geom.surface_shear_offset import (  # noqa: E402
    ShearMatrix,
    SurfaceShearOffsetResult,
    apply_shear_offset,
)
# NURBS-CURVE-FIT-G2: degree-5 B-spline fit with G2 (curvature-continuous)
# end conditions (Piegl & Tiller §9.4; Farin "CAGD" Ch 10).
# Prescribe tangent + curvature vectors at both endpoints for surface blending.
# HONEST: chord-length parameterisation only; centripetal may be better for
# high-aspect-ratio data.  Curvature vectors are parametric C''(t), not κ·n̂.
# LLM tool: nurbs_fit_curve_g2.
from kerf_cad_core.geom.curve_fit_g2 import (  # noqa: E402
    G2FitSpec,
    G2FitResult,
    fit_curve_g2,
)
# BREP-FACE-PLANE-DEVIATION: SVD least-squares best-fit plane from pre-sampled points;
# max/RMS deviation + 4-tier planarity classification (Pratt 1987 §3; Eberly §6.6).
# Used for STEP/IGES import validation and surface flatness QC.
# HONEST: least-squares only — no robust outlier rejection.
# LLM tool: geom_check_face_planarity.
from kerf_cad_core.geom.face_plane_deviation import (  # noqa: E402
    FaceSamplePoint,
    PlaneFit,
    FacePlaneDeviationReport,
    compute_face_plane_deviation,
)
# NURBS-SURFACE-ANALYTIC-DERIVATIVES (GK-P15): closed-form ∂S/∂u, ∂S/∂v,
# ∂²S/∂u², ∂²S/∂u∂v, ∂²S/∂v² via Piegl & Tiller A3.6 + rational A4.4.
# Gaussian K = (LN-M²)/(EG-F²); mean H = (EN-2FM+GL)/(2(EG-F²)).
# SSIHardenedMarcher: near-tangent bisection fallback (Patrikalakis & Maekawa §5).
# HONEST: curvature NaN at degenerate points; rational quotient rule may have
# large condition number for near-zero weights.
# LLM tool: nurbs_surface_derivatives_analytic.
from kerf_cad_core.geom.surface_analytic_derivatives import (  # noqa: E402
    SurfaceDerivativeResult,
    compute_analytic_derivatives,
    SSIHardenedMarcher,
)
# GK-P16: NURBS loft with cross-section curves + guide rails
# (Piegl & Tiller §10.3 skinning + guide-deformation blend).
# HONEST: approximate guide-rail constraint (Gaussian displacement blend);
# NOT an exact constrained-NURBS solver; deviations reported for QC.
# LLM tool: nurbs_loft_with_guide_rails.
from kerf_cad_core.geom.loft_guide_rails import (  # noqa: E402
    GuideRailLoftSpec,
    GuideRailLoftReport,
    loft_with_guide_rails,
)
# GK-P09: general pure-Python solid boolean for convex planar polyhedra.
# Extends the limited-primitive boolean (boolean.py) to arbitrary trimmed-plane
# body pairs.  Algorithm: Mantyla §6 + Hoffmann "Geometric & Solid Modeling" §3.
# HONEST: convex planar faces only — non-convex / curved-face bodies need OCCT.
# LLM tool: brep_general_boolean.
from kerf_cad_core.geom.general_boolean import (  # noqa: E402
    PlanarPolyhedron,
    BooleanResult,
    boolean_polyhedra,
    polyhedron_volume,
)
# GK-P20: UV-unwrap post-processing — seam-cut + chart pack + distortion stats.
# Sander et al. (2003) Multi-Chart Geometry Images + Lévy et al. (2002) LSCM.
# HONEST: shelf packing only; 90°-increment rotation; sampling-based distortion.
# LLM tool: nurbs_harden_uv_unwrap.
from kerf_cad_core.geom.uv_unwrap_hardening import (  # noqa: E402
    UVUnwrapHardeningSpec,
    UVChart,
    HardenedUVResult,
    harden_uv_unwrap,
)
