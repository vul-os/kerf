"""
kerf-cad-core plugin entry point.

Registers the ``POST /run-quad-remesh`` HTTP route and CAD-core LLM tools
(feature_cut_from_sketch, cam_layered, quad_remesh, etc.) into the tool
registry so the chat agent can invoke them.

Entry-point (pyproject.toml):
    [project.entry-points."kerf.plugins"]
    cad-core = "kerf_cad_core.plugin:register"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# ── LLM tool modules provided by this plugin ─────────────────────────────────
_TOOL_MODULES = [
    "kerf_cad_core.feature_cut_from_sketch",
    "kerf_cad_core.feature_hole_pattern_from_sketch",
    "kerf_cad_core.feature_loft",
    "kerf_cad_core.feature_section",
    "kerf_cad_core.cam_layered",
    "kerf_cad_core.cam_toolpath_collision",  # cam_verify_toolpath_collision
    "kerf_cad_core.cam_feedrate_lookahead",  # cam_optimize_feedrate_lookahead (Altintas 2012 §5.7)
    "kerf_cad_core.cam_gcode_emit",          # cam_emit_gcode (RS-274/NGC → Fanuc G-code from toolpath)
    "kerf_cad_core.cam_lathe_profile",      # cam_emit_lathe_gcode (G71/G70 lathe profile → Fanuc G-code)
    "kerf_cad_core.cam_wire_edm_path",      # cam_emit_wire_edm_gcode (Fanuc wire-EDM G41/G42 + G01/G02/G03)
    "kerf_cad_core.extrude_sketch_to_jscad",
    "kerf_cad_core.surfacing",
    "kerf_cad_core.quad_remesh",
    "kerf_cad_core.jewelry.gemstones",
    "kerf_cad_core.jewelry.gem_seat",
    "kerf_cad_core.jewelry.settings",
    "kerf_cad_core.jewelry.ring",
    "kerf_cad_core.jewelry.tool_metal_cost",
    "kerf_cad_core.jewelry.chain",
    "kerf_cad_core.jewelry.findings",
    "kerf_cad_core.jewelry.decorative",
    "kerf_cad_core.jewelry.pieces",
    "kerf_cad_core.jewelry.casting_export",
    "kerf_cad_core.jewelry.templates",
    "kerf_cad_core.jewelry.pave_wizard",
    "kerf_cad_core.jewelry.setter_checklist",
    "kerf_cad_core.sheet_metal",
    "kerf_cad_core.gdt.tools",
    "kerf_cad_core.gdt.composite_tolerance_check",  # gdt_validate_composite_frame (§10.5.2 + §11.6)
    "kerf_cad_core.arch.tools",
    "kerf_cad_core.struct.tools",
    "kerf_cad_core.feature_thread",
    "kerf_cad_core.assembly.tools",
    "kerf_cad_core.assembly.perf",
    "kerf_cad_core.weldment",
    "kerf_cad_core.civil.tools",
    "kerf_cad_core.civil.alignment_tools",
    "kerf_cad_core.gears",
    "kerf_cad_core.geom.surface_boolean_robust",
    "kerf_cad_core.geom.nurbs_boolean",
    # NURBS-CURVE-FOOTPRINT-ON-PLANE: orthographic projection of a 3-D NurbsCurve onto a plane
    # (Piegl & Tiller §6.1; Mortenson §4.4) — nurbs_curve_project_to_plane LLM tool
    "kerf_cad_core.geom.curve_footprint_on_plane",
    # NURBS-CURVE-CURVATURE-OSCULATING-CIRCLE: osculating circle at param t
    "kerf_cad_core.geom.osculating_circle",
    # BREP-FACE-DEVELOPABLE-CHECK: K=0 sampling test (do Carmo §3.6; Pottmann-Wallner §4)
    "kerf_cad_core.geom.face_developable_check",
    # NURBS-CURVE-FRESNEL-PARAMETERIZE: κ(s)≈αs clothoid re-parameterization (Walton-Meek 2009; Bertolazzi-Frego 2015)
    "kerf_cad_core.geom.fresnel_parameterize",
    # NURBS-CURVE-EVOLUTE: locus of osculating-circle centres E(t)=C(t)+n̂/κ
    # (do Carmo §1.6; Mortenson §4.2) — 2D only; 3D Frenet-Serret not yet supported
    "kerf_cad_core.geom.curve_evolute",
    # GK-P Wave 4P: far-offset robustness (Maekawa 1999) — nurbs_surface_offset_robust
    "kerf_cad_core.geom.offset_far_tools",
    "kerf_cad_core.geom.trim_curve",
    "kerf_cad_core.geom.trim_loop_heal",   # GK-P: nurbs_trim_loop_heal tool
    "kerf_cad_core.geom.subd_decimate_to_cage_tool",
    "kerf_cad_core.geom.subd_project_primitive_tools",  # SUBD-CAGE-PROJECT-TO-PRIMITIVE
    "kerf_cad_core.geom.subd_export_gltf",  # SUBD-EXPORT-GLTF: CC limit-surface → glTF 2.0 (json + struct; no third-party)
    "kerf_cad_core.geom.subd_export_step",  # SUBD-EXPORT-STEP: CC limit-surface → STEP AP242 faceted B-rep (ISO 10303-242:2020)
    "kerf_cad_core.nesting.tools",
    "kerf_cad_core.nesting.optimize_nest_tool",  # manufacturing_optimize_nest — NFP+GA (Burke 2006, Kovacs 2002)
    "kerf_cad_core.harness.tools",
    "kerf_cad_core.clash.tools",
    "kerf_cad_core.marine.tools",
    "kerf_cad_core.scan.tools",
    "kerf_cad_core.scan.nurbs_fit_tools",    # scan_fit_nurbs_surface — NURBS freeform fit
    "kerf_cad_core.gdt_callouts.tools",
    "kerf_cad_core.family.tools",
    "kerf_cad_core.shaft.tools",
    "kerf_cad_core.gearbox.tools",
    "kerf_cad_core.arch.spaces_tools",
    "kerf_cad_core.arch.column_load_check_tools",  # arch_check_column_load: AISC 360-22 §E3 + ACI 318-19 §22.4
    "kerf_cad_core.arch.beam_deflection_tools",    # arch_compute_beam_deflection: Roark 9e §8 + AISC Table 3-23
    "kerf_cad_core.arch.footing_bearing_tools",   # arch_compute_bearing_capacity: Meyerhof 1963 general equation (Bowles 5e §4; Das 8e §3)
    "kerf_cad_core.arch.slab_deflection_tools",  # arch_compute_slab_deflection: Timoshenko §44 Tables 41–42 + Roark 9e Table 11.4
    "kerf_cad_core.arch.wind_load_asce7_tools",  # arch_compute_wind_load: ASCE 7-22 §26–27 Directional Procedure MWFRS wall pressures
    "kerf_cad_core.arch.lateral_bracing_check_tools",  # arch_check_lateral_bracing: AISC 360-22 §F2 LTB (compact doubly symmetric I-shapes)
    "kerf_cad_core.arch.punching_shear_tools",  # arch_check_punching_shear: ACI 318-19 §22.6 two-way (punching) shear (no shear reinforcement)
    "kerf_cad_core.arch.wind_component_cladding_tools",  # arch_compute_wind_cc_pressure: ASCE 7-22 §30.3 C&C windows/doors/roof panels (enclosed buildings, h≤60 ft)
    "kerf_cad_core.civil.hydraulics_tools",
    "kerf_cad_core.tolstack.tools",
    "kerf_cad_core.kinematics.tools",
    "kerf_cad_core.fea.tools",
    "kerf_cad_core.springs.tools",
    "kerf_cad_core.piping.tools",
    "kerf_cad_core.hvac.tools",
    "kerf_cad_core.turning.tools",
    "kerf_cad_core.steelconn.tools",
    "kerf_cad_core.pressvessel.tools",
    "kerf_cad_core.fasteners.tools",
    "kerf_cad_core.fluidpower.tools",
    "kerf_cad_core.gearstrength.tools",
    "kerf_cad_core.vibration.tools",
    "kerf_cad_core.fatigue.tools",
    "kerf_cad_core.matsel.tools",
    "kerf_cad_core.pneumatics.tools",
    "kerf_cad_core.heatxfer.tools",
    "kerf_cad_core.beam.tools",
    "kerf_cad_core.casting.tools",
    "kerf_cad_core.injection.tools",
    "kerf_cad_core.surveying.tools",
    "kerf_cad_core.geotech.tools",
    "kerf_cad_core.hydrology.tools",
    "kerf_cad_core.welding.tools",
    "kerf_cad_core.tolfits.tools",
    "kerf_cad_core.cncfeeds.tools",
    "kerf_cad_core.clutchbrake.tools",
    "kerf_cad_core.pumpsys.tools",
    "kerf_cad_core.beltchain.tools",
    "kerf_cad_core.acoustics.tools",
    "kerf_cad_core.bearings.tools",
    "kerf_cad_core.thermocycle.tools",
    "kerf_cad_core.robotics.tools",
    "kerf_cad_core.aero.tools",
    "kerf_cad_core.optics.tools",
    "kerf_cad_core.composites.tools",
    "kerf_cad_core.navalarch.tools",
    "kerf_cad_core.lubrication.tools",
    "kerf_cad_core.windload.tools",
    "kerf_cad_core.controls.tools",
    "kerf_cad_core.seismic.tools",
    "kerf_cad_core.concrete.tools",
    "kerf_cad_core.solarpv.tools",
    "kerf_cad_core.timber.tools",
    "kerf_cad_core.costing.tools",
    "kerf_cad_core.conveyor.tools",
    "kerf_cad_core.additive.tools",
    "kerf_cad_core.wormbevel.tools",
    "kerf_cad_core.psychro.tools",
    "kerf_cad_core.rigging.tools",
    "kerf_cad_core.packaging.tools",
    "kerf_cad_core.combustion.tools",
    "kerf_cad_core.corrosion.tools",
    "kerf_cad_core.flowmeter.tools",
    "kerf_cad_core.turbo.tools",
    "kerf_cad_core.ergonomics.tools",
    "kerf_cad_core.channel.tools",
    "kerf_cad_core.gcode.tools",
    "kerf_cad_core.cmm.tools",
    "kerf_cad_core.fiveaxis.tools",
    "kerf_cad_core.dynamics.tools",
    "kerf_cad_core.tank.tools",
    "kerf_cad_core.railway.tools",
    "kerf_cad_core.cuttingtool.tools",
    "kerf_cad_core.boiler.tools",
    "kerf_cad_core.spillway.tools",
    "kerf_cad_core.refrigeration.tools",
    "kerf_cad_core.vacuum.tools",
    "kerf_cad_core.windturbine.tools",
    "kerf_cad_core.hydroturbine.tools",
    "kerf_cad_core.forming.tools",
    "kerf_cad_core.reliability.tools",
    "kerf_cad_core.thermalcut.tools",
    "kerf_cad_core.heattreat.tools",
    "kerf_cad_core.waterhammer.tools",
    "kerf_cad_core.pavement.tools",
    "kerf_cad_core.buildingenergy.tools",
    "kerf_cad_core.firesafety.tools",
    "kerf_cad_core.mooring.tools",
    "kerf_cad_core.geodesy.tools",
    "kerf_cad_core.elevator.tools",
    "kerf_cad_core.lighting.tools",
    "kerf_cad_core.crane.tools",
    "kerf_cad_core.elecpower.tools",
    "kerf_cad_core.plumbing.tools",
    "kerf_cad_core.earthworks.tools",
    # GK-P-NURBS-OFFSET: nurbs_surface_offset LLM tool
    "kerf_cad_core.geom.surface_offset",
    "kerf_cad_core.geom.mass_props_multi",
    "kerf_cad_core.geom.mass_props_mesh",   # BREP-MESH-MASS-PROPS: triangle-mesh volume/CG/inertia
    "kerf_cad_core.geom.make2d",
    "kerf_cad_core.geom.reparam_tools",  # GK-P: chord-length + centripetal + Foley-Nielsen reparametrisation
    "kerf_cad_core.geom.curve_offset_2d",
    "kerf_cad_core.geom.mass_props_mesh",   # BREP-MESH-MASS-PROPS: triangle-mesh volume/CG/inertia
    "kerf_cad_core.geom.curve_toolkit",
    "kerf_cad_core.geom.surface_analysis",
    "kerf_cad_core.geom.wall_thickness",   # GK-P: brep_analyze_wall_thickness + brep_check_moldability
    "kerf_cad_core.geom.shell_wall_check", # BREP-SHELL-WALL-CHECK: brep_check_shell_walls (Menges 2001 §3.3; BD §5)
    "kerf_cad_core.geom.curvature_heatmap",
    # NURBS-CURVE-CURVATURE-PROFILE-EXPORT: κ(t) CSV/SVG/PNG export (Farin §11.6; Sapidis §3)
    "kerf_cad_core.geom.curvature_profile_export",
    "kerf_cad_core.geom.mesh_repair",
    # GK-82 ext: body-body imprint with edge tagging
    "kerf_cad_core.geom.imprint_body_tool",
    # GK-NM: non-manifold detection + repair (brep_non_manifold_check, brep_non_manifold_repair)
    "kerf_cad_core.geom.non_manifold_tools",
    "kerf_cad_core.geom.unroll_srf",
    "kerf_cad_core.geom.solid_features",
    # GK-P: Hollow compound operator (shell + blend + fillet + port + ribs)
    "kerf_cad_core.geom.body_hollow",
    "kerf_cad_core.geom.patch_srf",
    "kerf_cad_core.geom.revolve_srf",
    # GK-P: N-sided Coons + Gregory + Hosaka-Kimura patch fit
    "kerf_cad_core.geom.network_surface_tools",
    "kerf_cad_core.jewelry.production",
    "kerf_cad_core.jewelry.gem_studio",
    "kerf_cad_core.jewelry.gallery",
    "kerf_cad_core.jewelry.head_wizard",
    "kerf_cad_core.geom.subd",
    # GK-P SubD/mesh: SubD-cage boolean (transversal case, Cohen-Or-Sheffer 2003)
    "kerf_cad_core.geom.subd_csg_tools",
    # SUBD-CAGE-SUBDIVIDE-EDGE: localized single-edge refinement (Catmull-Clark 1978; Stam 1998 §4; Maya polySplit)
    "kerf_cad_core.geom.subd_subdivide_edge_tool",
    "kerf_cad_core.geom.blocks",
    "kerf_cad_core.geom.mesh_to_nurbs",
    "kerf_cad_core.geom.nurbs_param_optimal",   # GK-P50: nurbs_reparametrize_optimal
    "kerf_cad_core.geom.section_contour",
    "kerf_cad_core.geom.section_cutaway",  # brep_section_view — ISO 128-30 section cutaway + hatch
    "kerf_cad_core.geom.surface_cross_section",  # nurbs_compute_surface_cross_section (Sederberg §7.3)
    "kerf_cad_core.jewelry.eternity_auto",
    "kerf_cad_core.geom.surface_fillet",
    "kerf_cad_core.geom.auto_chamfer",      # brep_recommend_chamfers, brep_apply_chamfer_recommendations (ISO 13715)
    "kerf_cad_core.jewelry.bangle",
    "kerf_cad_core.jewelry.hollowing",
    "kerf_cad_core.jewelry.engraving",
    "kerf_cad_core.geom.match_srf",
    "kerf_cad_core.geom.intersection",
    "kerf_cad_core.geom.curve_projection",  # GK-P: nurbs_project_point (Newton + arc-length)
    "kerf_cad_core.geom.edge_curve_from_face_pair",
    # BREP-CURVE-ON-SURFACE-PROJECTION: Newton-Raphson UV-trace (P&T §6.1 / PM §3.3)
    "kerf_cad_core.geom.curve_on_surface_robust",  # nurbs_project_curve_to_surface
    "kerf_cad_core.jewelry.bezel_auto",
    "kerf_cad_core.jewelry.plating",
    "kerf_cad_core.jewelry.gem_cert",
    "kerf_cad_core.jewelry.bas_relief",
    "kerf_cad_core.jewelry.print_presets",
    "kerf_cad_core.jewelry.tech_drawing",
    "kerf_cad_core.jewelry.cam_wax",
    "kerf_cad_core.jewelry.filigree_advanced",
    "kerf_cad_core.quoting.fab_quote",
    "kerf_cad_core.dfm.checks",
    "kerf_cad_core.cam_wizard.stock_setup",
    "kerf_cad_core.drawings.auto_dimension",
    "kerf_cad_core.mbd.tools",
    "kerf_cad_core.afr.recognize",
    # GK-133 / ISO 10303-224: brep_feature_recognition + brep_feature_to_machining
    "kerf_cad_core.geom.feature_recognition",
    "kerf_cad_core.sysml1d.network",
    "kerf_cad_core.frep.sdf",
    "kerf_cad_core.sheet_metal_bend_table",
    "kerf_cad_core.procsim.solidification",
    "kerf_cad_core.procsim.am_residual",
    "kerf_cad_core.jewelry.repair",
    "kerf_cad_core.jewelry.appraisal",
    "kerf_cad_core.jewelry.stringing",
    "kerf_cad_core.jewelry.watch",
    "kerf_cad_core.procsim.toolpath_verify",
    "kerf_cad_core.procsim.forming_sim",
    "kerf_cad_core.procsim.weld_distortion",
    "kerf_cad_core.procsim.moldflow",
    "kerf_cad_core.jewelry.mount_finder",
    "kerf_cad_core.jewelry.cad_qc",
    "kerf_cad_core.jewelry.wax_carving",
    "kerf_cad_core.jewelry.family_ring",
    "kerf_cad_core.jewelry.enamel",
    "kerf_cad_core.simple_parametric.tools",
    "kerf_cad_core.spc.tools",
    # SUBD-LIMIT-WALK-CROSS-CURVE: walk CC limit surface + planar cross-section (Stam 1998 + 5-iter bisection)
    "kerf_cad_core.subd.limit_walk_cross_curve",
    # SUBD-CAGE-EDGE-LOOP-SELECT: directional edge-loop walk on quad cage; stops at irregular vertex (Bommes-Lévy-Pietroni 2013 §3.2)
    "kerf_cad_core.subd.edge_loop_select",
    # SUBD-LIMIT-NORMAL-FIT: sample CC limit-surface normal n̂(u,v) at uniform grid; residuals vs bilinear approx (Stam 1998 §3.2; Halstead-Kass-DeRose 1993)
    "kerf_cad_core.subd.limit_normal_fit",
    # SUBD-CAGE-EDGE-COLLAPSE: collapse a quad cage edge to midpoint; merge v_a+v_b→v_m; remove degenerate faces (Hoppe 1996 §3.2; Bommes-Lévy-Pietroni 2013 §4)
    "kerf_cad_core.subd.edge_collapse",
    # GK-P-B: Stam exact limit-position + limit-tangent evaluation (subd_eval_limit tool)
    "kerf_cad_core.geom.subd_stam",
    # GK-P45: SubD/mesh authoring ops (subd_poke, subd_extrude_along, sculpt_brush, multires_evaluate)
    "kerf_cad_core.subd_tools",
    # GK-P-C: multires displacement (subd_apply_displacement, subd_extract_displacement)
    "kerf_cad_core.multires_displacement_tools",
    # GK-P49: SubD deformation cage with mean-value coordinates (subd_deform_with_cage)
    "kerf_cad_core.subd_deform_tools",
    # Wave 4AA: harmonic coordinates for cage deformation (Joshi et al. 2007)
    "kerf_cad_core.geom.subd_harmonic",
    # GK-P: SubD edge flow optimization (Bommes 2009 Mixed-Integer Quadrangulation)
    "kerf_cad_core.geom.subd_edge_flow",
    # GK-P46: mesh/implicit ops (sdf_csg, uv_unwrap, isotropic_remesh, retopo_snap)
    "kerf_cad_core.mesh_implicit_tools",
    # GK-P58: B-rep UV unwrap atlas (brep_uv_unwrap, brep_uv_distortion_report)
    "kerf_cad_core.geom.brep_uv_tools",
    # GK-P47: isophote analysis (feature_isophote_analysis added to surfacing module above)
    # GK-P47: match_srf G3 is in geom.match_srf (already in _TOOL_MODULES above)
    # GK-P47: feature_loft guide_curves is in feature_loft (already in _TOOL_MODULES above)
    # GK-P48: construction verbs (hem_sheet, jog_sheet, multi_flange, delete_face, push_pull, gusset_plate, cope_notch)
    "kerf_cad_core.construction_verbs_tools",
    # GK-P (B-rep heal + inertia): industrial STEP-import clean-up pass
    "kerf_cad_core.geom.brep_heal",                     # brep_heal, brep_compute_inertia — industrial heal pipeline + inertia tensor
    # GK-P: degree raise + lower (Cohen-Lyche-Schumaker 1985)
    "kerf_cad_core.geom.degree_op",
    # GK-P49: geodesic distance via heat method (Crane, Weischedel & Wardetzky 2013)
    "kerf_cad_core.geom.subd_geodesic",
    # GK-P: fillet chain propagation (Vida-Martin-Varady 1994) — brep_fillet_chain + brep_auto_fillet_all
    "kerf_cad_core.geom.fillet_chain",
    # BREP-FACE-COMPATIBLE-RESPLIT: knot-union insertion on shared edge (P-T §6.5; Hoffmann 1989 §6)
    "kerf_cad_core.geom.face_compatible_resplit",
    # Coverage sweep: modules with @register that were not yet in _TOOL_MODULES
    "kerf_cad_core.heal",                               # heal_geometry — body heal + repair
    "kerf_cad_core.sketch",                             # sketch_add_entity/constraint, sketch_set_constraint_value, sketch_delete_entity, sketch_carbon_copy, sketch_validate
    "kerf_cad_core.concrete.eurocode2",                 # ec2_design_strengths, ec2_flexure, ec2_punching_shear, ec2_shear_design
    "kerf_cad_core.concrete.punching_torsion_tools",    # rc_critical_perimeter, rc_two_way_shear_strength, rc_punching_shear_check, rc_cracking_torsion, rc_torsion_capacity
    "kerf_cad_core.civil.transient_pipes",              # transient_pipe_network_moc, transient_pipe_network_quasi_steady, transient_surge_tank_validation
    "kerf_cad_core.cuttingtool.tool_life",              # taylor_tool_life, gilbert_economic_speed
    "kerf_cad_core.cuttingtool.cutting_speed_tools",   # manufacturing_query_cutting_speed
    "kerf_cad_core.struct.eurocode5",                   # ec5_strength_class, ec5_kmod, ec5_design_strength, ec5_beam_bending, ec5_combined_nm, ec5_column_buckling, ec5_shear
    "kerf_cad_core.struct.eurocode8",                   # ec8_spectrum, ec8_lateral_force, ec8_rsa
    "kerf_cad_core.struct.frame",                       # struct_frame_solve_2d, struct_story_drift
    "kerf_cad_core.fluids.iapws_if97",                  # fluids_steam_if97 — water/steam properties
    "kerf_cad_core.fem_capabilities",                   # fem_list_capabilities
    "kerf_cad_core.acoustics.wave",                     # wave_image_source_ir, wave_rt60_from_ir, wave_room_modes, wave_sea_two_rooms_tl
    "kerf_cad_core.buildingenergy.transient_tools",     # be_sol_air_temp, be_cltd_wall, be_cltd_roof, be_correct_cltd, be_wall_cooling_load, + 3 more
    "kerf_cad_core.casting.detail_tools",               # casting_shrinkage_factor, casting_pattern_dimensions, casting_chvorinov_time, casting_riser_diameter, casting_design_package
    "kerf_cad_core.controls.statespace_tools",          # controls_ss_model, controls_controllability, controls_observability, controls_pole_placement, controls_lqr, + 4 more
    "kerf_cad_core.elecpower.power_tools",              # elecpower_loadflow, elecpower_relay_trip, elecpower_coordinate, elecpower_arcflash
    "kerf_cad_core.fatigue.multiaxial_tools",           # fatigue_findley, fatigue_swt3d, fatigue_brown_miller, fatigue_multiaxial_critical_plane
    "kerf_cad_core.frep.csg",                           # csg_union, csg_intersect, csg_difference, csg_union_smooth, csg_intersect_smooth, + 11 more
    "kerf_cad_core.gearbox.planetary_tools",            # planetary_stage_design, compound_planetary_design, planetary_module_select
    "kerf_cad_core.geotech.liq_tools",                  # liq_csr, liq_crr_spt, liq_crr_cpt, liq_safety_factor, liq_settlement
    "kerf_cad_core.matsel.multi_objective_tools",       # matsel_pareto, matsel_weighted, matsel_tradeoff
    "kerf_cad_core.seismic.rsa_tools",                  # seismic_build_asce7_spectrum, seismic_rsa_sdof, seismic_rsa_mdof, seismic_newmark_sdof, seismic_newmark_mdof
    "kerf_cad_core.solarpv.shading_tools",              # pv_cell_iv, pv_module_shaded_iv, pv_mppt_mismatch_loss
    "kerf_cad_core.jewelry.profile_lib",                # jewelry_list_profiles, jewelry_get_profile, jewelry_compare_comfort
    # GK-P: Bezier extraction (B-spline → multi-Bezier, Piegl & Tiller §5.6)
    "kerf_cad_core.geom.bezier_extract",
    # STEP import auto-heal pipeline (GK-P: STEP import + heal wiring)
    "kerf_cad_core.io.step_import_tool",               # step_import_brep — STEP import with auto-heal
    # GK-P49: assembly-level interference detection (Möller 1997 + AABB broad-phase)
    "kerf_cad_core.geom.assembly_interference_tools",   # brep_assembly_interference, brep_check_clearance
    # GK-P06: NURBS curve/surface split at parameter (nurbs_split_curve, nurbs_split_surface)
    "kerf_cad_core.geom.curve_split",
    # GK-P: NURBS rational conic detection + simplification (Lee 1987 / Piegl-Tiller §7.2)
    "kerf_cad_core.geom.conic_detect",                 # nurbs_detect_conic, nurbs_simplify_conic
    # GK-P auto-fillet: smart fillet recommendation (Peterson 1974 + Boothroyd-Dewhurst 2002)
    "kerf_cad_core.geom.auto_fillet",                  # brep_recommend_fillets, brep_apply_fillet_recommendations
    # GK-P: Auto-lightweight (Lyche-Mørken knot removal + rational simplification)
    "kerf_cad_core.geom.auto_lightweight",              # brep_auto_lightweight
    # GK-P: Quadratic → cubic NURBS elevation (Piegl-Tiller §5.5 specialisation)
    "kerf_cad_core.geom.degree_2_to_3",                 # nurbs_elevate_to_cubic — degree-2 B-spline → degree-3, shape-preserving
    # BREP-CONNECT-INSPECTOR: radial-edge valence + shell connectivity
    # (Weiler 1985 §3 + Mantyla 1988 §6) — brep_inspect_connectivity, brep_is_manifold
    "kerf_cad_core.geom.brep_connect_inspector_tools",
    # GK-P NURBS-DERIVATIVE-FIELD-VISUAL: 1st partial-derivative arrow-plot PNG/SVG
    "kerf_cad_core.geom.derivative_field_viz",           # nurbs_derivative_field_png, nurbs_derivative_field_svg
    # NURBS-CONVERT-TO-IGES-144: IGES 5.3 entity-144 export (§4.27 + §4.26 + §4.23 + §4.22)
    "kerf_cad_core.geom.io.iges_144_tool",               # nurbs_export_iges_144
    # BREP-SUM-EDGE-LENGTHS: total edge length + kind/curve-type breakdowns for cutting-cost
    # (Weiler 1985 §3 radial-edge + Gauss-Legendre arc integration) — brep_total_edge_length, brep_edge_length_by_kind
    "kerf_cad_core.geom.brep_edge_metrics",
    # GK-SUBD-LIMIT-INTEGRAL-METRIC: exact-as-feasible ∫∫dA, ∫HdA, ∫KdA over CC limit surface
    "kerf_cad_core.geom.subd_limit_integrals",          # subd_integrate_area, subd_integrate_mean_curvature, subd_integrate_gaussian_curvature
    # BREP-FACE-AREA-WEIGHTED-CENTROID: surface centroid of shell/solid (GL 16x16 per face)
    "kerf_cad_core.geom.face_centroid",                  # brep_surface_centroid
    # NURBS-EXTRACT-ISO-CURVES: Piegl-Tiller §5.3 knot-insertion iso extraction
    "kerf_cad_core.geom.iso_curve_extract",             # nurbs_extract_iso_u, nurbs_extract_iso_v
    # SUBD-EXPORT-OPENSUBDIV-USD: USD Mesh prim (.usda ASCII) — catmullClark + creases
    "kerf_cad_core.geom.subd_export_usd",               # subd_export_to_usd
    # SUBD-LIMIT-MESH-EXPORT-OBJ: CC limit-surface → Wavefront OBJ (v/vn/f; geometry only)
    "kerf_cad_core.geom.subd_export_obj",               # subd_export_limit_to_obj
    # SUBD-EXPORT-PLY: CC limit-surface → Stanford PLY (ASCII + binary_little_endian)
    "kerf_cad_core.geom.subd_export_ply",               # subd_export_limit_to_ply
    # MANUFACTURING-AUTO-FIXTURE-LAYOUT: 3-2-1 fixture placement (Asada-By 1985)
    "kerf_cad_core.manufacturing_fixture_layout",       # manufacturing_auto_fixture_layout
    # BREP-FACE-NEIGHBOR-WALK: face-adjacency graph + BFS traversal for CNC routing /
    # geodesic shortest-path / paint-area planning (Weiler 1985 §3 edge-sharing adjacency)
    "kerf_cad_core.geom.face_neighbor_walk",            # brep_face_neighbors, brep_shortest_face_path
    # BREP-FACE-PLANARITY-CHECK: SVD best-fit plane + max deviation + planarity score
    # (Pratt 1987 §3; Eberly §6.6) — brep_check_face_planarity
    "kerf_cad_core.geom.face_planarity_tools",
    # SUBD-LIMIT-WALK-ALONG-EDGES: CC limit-surface curve along a cage edge chain
    "kerf_cad_core.geom.subd_edge_walk",               # subd_walk_edge_chain
    "kerf_cad_core.geom.half_space_volume",             # brep_volume_above_plane
    # NURBS-COMPOSITE-TANGENT-MATCH: G1/G2 seam CP adjustment for composite curve chains
    # (Klass 1980 §3; Farin §8.4; Piegl-Tiller §7.3) — nurbs_match_composite_tangents
    "kerf_cad_core.geom.composite_tangent_match",
    # BREP-EDGE-CONVEX-CONCAVE-CLASSIFY: dihedral-angle edge classification
    # (Hoffmann 1989 §5.3; Mantyla 1988 §7.4) — brep_classify_edges
    "kerf_cad_core.geom.edge_convexity",
    # BREP-HOLE-RECOGNITION-FROM-LOOPS: AAG-based recognition of through-hole, blind hole,
    # counterbore, countersink, possibly-threaded holes from B-rep inner loops
    # (Joshi-Chang 1988; Han-Pratt-Regli 2000) — brep_recognize_holes
    "kerf_cad_core.geom.hole_recognition",
    # SUBD-SYMMETRY-DETECT: PCA mirror + rotational + spherical symmetry
    # (Mitra-Guibas-Pauly 2006; Podolak et al. 2006) -- subd_detect_symmetry, subd_enforce_symmetry
    "kerf_cad_core.geom.subd_symmetry_tools",
    # NURBS-FAIR-COMPOSITE-CURVE: global curvature-variance fairing for poly-NURBS chains
    # (Greiner-Hormann 1996; Sapidis-Farin 1990 §3; Klass 1980 §3) — nurbs_fair_composite
    "kerf_cad_core.geom.composite_fair",
    # BREP-FILLET-RECOMMEND-RADIUS: per-edge radius recommendation combining
    # face-size rule, Peterson Kt notch formula, material stress-relief floor,
    # tool constraint, and sharp-edge preservation
    # (Peterson 1974 §2.3; Boothroyd-Dewhurst 2002 §4) — brep_recommend_fillet_radius
    "kerf_cad_core.geom.fillet_recommend_radius",
    # SUBD-CAGE-RING-FROM-EDGE: edge ring traversal (opposite edges across quad faces)
    # Pure-Python; honest degenerate flag for non-quad faces.
    "kerf_cad_core.geom.subd_edge_ring",          # subd_compute_edge_ring
    # SUBD-LIMIT-CRITICAL-POINTS: discrete Morse critical points on CC limit surface
    # (Edelsbrunner-Harer 2010 §1) — subd_find_critical_points
    "kerf_cad_core.geom.subd_critical_points",
    # BREP-CHAMFER-RECOMMEND-SIZE: per-edge chamfer offset+angle recommendation
    # (Drozda-Wick §3-7; DIN 74:1974 Form A/B; ISO 13715:2017) — brep_recommend_chamfer_size
    "kerf_cad_core.geom.chamfer_recommend_size",
    # NURBS-NORMAL-CURVATURE-AT-POINT: Meusnier's theorem; κ_n, κ_1, κ_2, K, H,
    # principal directions (do Carmo §3.2 / Mortenson §10.4)
    "kerf_cad_core.geom.normal_curvature",
    # BREP-TOPOLOGY-EULER-CHECK: generalised Euler-Poincaré formula verifier
    # (Mantyla 1988 §6 + Hoffmann 1989 §5) — brep_verify_euler_topology
    "kerf_cad_core.geom.topology_euler_check_tools",
    # GK-SUBD-LIMIT-INTEGRAL-METRIC: exact-as-feasible integrals over CC limit surface
    "kerf_cad_core.geom.subd_limit_integrals",          # subd_integrate_area, subd_integrate_mean_curvature, subd_integrate_gaussian_curvature
    # SUBD-LIMIT-INTEGRAL-GAUSS-BONNET-CHECK: verify ∫∫K dA = 2π·χ on closed CC limit surface
    # (do Carmo §4.5; Edelsbrunner-Harer 2010 §1) — subd_verify_gauss_bonnet
    "kerf_cad_core.geom.subd_gauss_bonnet_check",
    # BREP-SOLID-CONTAINS-POINT: ray-casting Jordan-curve inside/outside test on B-rep solids
    # (Mortenson §11.5; Ericson 2005 §5.1; O'Rourke §7.4) — brep_solid_contains_point
    "kerf_cad_core.geom.solid_contains_point",
    # SUBD-EXPORT-PLY: CC limit-surface → Stanford PLY (ASCII + binary_little_endian)
    "kerf_cad_core.geom.subd_export_ply",               # subd_export_limit_to_ply
    # MANUFACTURING-TOOLING-CATALOG-MATCH: tool lookup from embedded Sandvik/Iscar/KMT/OSG/Tungaloy catalog
    # (Sandvik Cutting Data Rec. 2024; Drozda-Wick §3) — manufacturing_match_tooling
    "kerf_cad_core.manufacturing_tooling_catalog",
    # NURBS-CURVE-RESAMPLE-UNIFORM: resample a NurbsCurve at uniform arc-length intervals
    # (Piegl-Tiller §9.4 + Patrikalakis-Maekawa §3.5) — nurbs_curve_resample_uniform
    "kerf_cad_core.geom.curve_resample_uniform",
    # GK-140: NURBS-surface offset distance field (Maekawa 1999; Piegl & Tiller §11.3)
    "kerf_cad_core.geom.offset_distance_field",         # nurbs_offset_distance_field
    # NURBS-SURFACE-AREA-EXACT: exact area via first-fundamental-form integrand
    # A = ∫∫ sqrt(EG-F²) du dv (do Carmo §2.5 / Mortenson §10.4)
    "kerf_cad_core.geom.surface_area_exact",            # nurbs_surface_area_exact
    # BREP-FACE-AREA-EXACT: exact area of a B-rep Face (NurbsSurface + analytic surfaces)
    # via first-fundamental-form A = ∫∫ sqrt(EG-F²) du dv
    # (do Carmo §2.5; Piegl & Tiller §10.3; Farin §11.2)
    # CAVEAT: trimmed faces (inner loops) use bounding-rectangle approximation (v1)
    "kerf_cad_core.geom.face_area_exact",               # brep_compute_face_area_exact
    # BREP-FACE-PRINCIPAL-CURVATURE-VIZ: sample κ₁, κ₂ over a B-rep Face UV grid;
    # SVG/PNG heatmap overlay (do Carmo §3.4 / Mortenson §6.5 / Pottmann-Wallner §4)
    "kerf_cad_core.geom.principal_curvature_viz",       # brep_face_principal_curvature_viz
    # GK-P50: arc-length inversion (Newton–Raphson, chord-length param, even-spaced CAM)
    "kerf_cad_core.geom.arc_length_invert",
    # BREP-EDGE-CURVE-EXTEND: extend B-rep edge NurbsCurve beyond domain by ΔL mm,
    # G1 tangent-continuous join (Piegl & Tiller §10.4; Mortenson §3.7)
    "kerf_cad_core.geom.edge_curve_extend",
    # BREP-EDGE-CHAMFER-VARIABLE: variable-width chamfer strip along a 2D edge curve;
    # width ramps linearly from width_start_mm to width_end_mm (Piegl-Tiller §10.5;
    # Mortenson §9.3). LLM tool: brep_generate_variable_chamfer.
    # Honest: 2D polyline only; 3D B-rep solid edge chamfer is P2/P3 scope.
    "kerf_cad_core.geom.edge_chamfer_variable",
    # NURBS-CURVE-CIRCLE-FIT: snap-to-circle + circular region detection
    "kerf_cad_core.geom.curve_circle_fit",              # nurbs_fit_circle_to_curve
]
# NOTE: optics_compute_sagitta_arrow_chart is registered via kerf_cad_core.optics.tools
# (already in _TOOL_MODULES above at line 128); sagitta_arrow_chart module is imported
# from within tools.py via gated import at module bottom.
# NOTE: optics_compute_sagitta_arrow_chart is registered via kerf_cad_core.optics.tools
# (already in _TOOL_MODULES above); sagitta_arrow_chart module imported from tools.py bottom.

# ── kerf_core contract (built by kerf-core agent in parallel) ─────────────────
# Import lazily so this plugin boots even before kerf_core is installed.
try:
    from kerf_core.plugin import PluginContext, PluginManifest  # type: ignore[import]
    _KERF_CORE_AVAILABLE = True
except ImportError:
    _KERF_CORE_AVAILABLE = False

    # Minimal stubs so the rest of this file type-checks cleanly at runtime.
    class PluginManifest:  # type: ignore[no-redef]
        def __init__(self, *, name: str, version: str, provides: list, depends: list):
            self.name = name
            self.version = version
            self.provides = provides
            self.depends = depends

    class PluginContext:  # type: ignore[no-redef]
        pass


# ── OCC availability ──────────────────────────────────────────────────────────
from kerf_cad_core.occ_helpers import _OCC_AVAILABLE

# Import the feature tools so the @register decorators fire on plugin load.
try:
    import kerf_cad_core.feature_boss_with_draft  # noqa: F401 — side-effect import
except Exception as _import_err:
    logger.warning("kerf-cad-core: could not load feature_boss_with_draft: %s", _import_err)

try:
    import kerf_cad_core.feature_hole_pattern_from_sketch  # noqa: F401 — side-effect import
except Exception as _import_err:
    logger.warning("kerf-cad-core: could not load feature_hole_pattern_from_sketch: %s", _import_err)

try:
    import kerf_cad_core.feature_loft  # noqa: F401 — side-effect import
except Exception as _import_err:
    logger.warning("kerf-cad-core: could not load feature_loft: %s", _import_err)

_PROVIDES_FULL = [
    "cad.step-io",
    "cad.brep-mesh",
    "cad.wire-extract",
    "cad.nurbs",
]


async def register(app, ctx: "PluginContext") -> "PluginManifest":
    """Plugin entry-point.

    Mounts the quad-remesh HTTP route and returns a manifest advertising
    which CAD capabilities are available (empty list when pythonOCC is not
    installed so /health/capabilities shows "cad-core dormant").
    """
    if _OCC_AVAILABLE:
        provides = _PROVIDES_FULL
        logger.info("kerf-cad-core: pythonOCC available — %s", provides)
    else:
        provides = []
        logger.warning(
            "kerf-cad-core: pythonOCC not installed — plugin dormant. "
            "Install: conda install -c conda-forge pythonocc-core"
        )

    # ── Mount HTTP routes ─────────────────────────────────────────────────
    try:
        from kerf_cad_core.routes import router as cad_router
        app.include_router(cad_router, tags=["cad-core"])
    except Exception as _route_err:  # pragma: no cover
        logger.warning("kerf-cad-core: could not mount routes: %s", _route_err)

    # ── Register LLM tools ────────────────────────────────────────────────
    _register_tools()

    return PluginManifest(
        name="cad-core",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools() -> None:
    """Import tool modules so their @register decorators fire."""
    import importlib
    for module_path in _TOOL_MODULES:
        try:
            importlib.import_module(module_path)
        except Exception as exc:  # pragma: no cover
            logger.warning("kerf-cad-core: failed to load tool %s: %s", module_path, exc)
