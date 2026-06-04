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
    "kerf_cad_core.gdt.datum_shift_check",          # gdt_compute_datum_shift (§4.5 + §7.3.5 MMC/LMC datum shift)
    "kerf_cad_core.gdt.feature_of_size_dof",        # gdt_compute_fos_dof (§4.7 + §7.3 FOS DOF enumerator)
    "kerf_cad_core.gdt.runout_check",               # gdt_check_runout (§13 circular + total runout / ISO 1101 §18)
    "kerf_cad_core.gdt.runout_circular",            # gdt_check_circular_runout (§12.4 single-plane circular runout FIM)
    "kerf_cad_core.gdt.dimension_chain",            # gdt_compute_dimension_chain (§5.3 WC + RSS tolerance stack-up)
    "kerf_cad_core.gdt.composite_position",         # gdt_check_composite_position (§10.5 PLTZF+FRTZF vs measured points)
    "kerf_cad_core.arch.tools",
    "kerf_cad_core.struct.tools",
    "kerf_cad_core.feature_thread",
    "kerf_cad_core.assembly.tools",
    "kerf_cad_core.assembly.perf",
    "kerf_cad_core.weldment",
    "kerf_cad_core.civil.tools",
    "kerf_cad_core.civil.alignment_tools",
    "kerf_cad_core.civil.corridor_sheet_tools",
    "kerf_cad_core.gears",
    "kerf_cad_core.geom.surface_boolean_robust",
    "kerf_cad_core.geom.nurbs_boolean",
    # GK-P09: general pure-Python solid boolean for convex planar polyhedra
    # (Mantyla §6 + Hoffmann §3 — brep_general_boolean LLM tool)
    "kerf_cad_core.geom.general_boolean",
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
    # NURBS-CURVE-INFLECTION: inflection points where κ_signed changes sign
    # (do Carmo §1.5; Sapidis §3) — fairness QC, sketch QC, toolpath transitions
    "kerf_cad_core.geom.curve_inflection",
    # GK-P Wave 4P: far-offset robustness (Maekawa 1999) — nurbs_surface_offset_robust
    "kerf_cad_core.geom.offset_far_correction",
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
    # Wave 8D: RE freeform NURBS fit
    "kerf_cad_core.reverse_engineering.tools",  # re_fit_freeform_nurbs — freeform cluster → NURBS (P&T §9.2/§9.4 + Hausdorff oracle)
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
    "kerf_cad_core.arch.base_plate_aisc_tools",  # arch_design_base_plate: AISC DG-1 §3.1 + AISC 360-22 §J8 column base plate (concentric axial load only)
    "kerf_cad_core.arch.shear_wall_oop_tools",   # arch_check_shear_wall_oop: ACI 318-19 §11.7 RC shear wall OOP flexural + slenderness (h/t≤30 §11.5.3)
    "kerf_cad_core.arch.diaphragm_shear_tools",  # arch_check_diaphragm_shear: AWC SDPWS-2021 §4.2 wood + SDI DDM04 metal-deck in-plane shear (chord forces + deflection separate)
    "kerf_cad_core.arch.retaining_wall_stability_tools",  # arch_check_retaining_wall_stability: Rankine active Ka=tan²(45-φ/2); FoS_overt/slide/bearing (Bowles 5e §12.3; Das §13)
    "kerf_cad_core.arch.pier_axial_capacity_tools",     # arch_check_pier_axial: TMS 402-22 §8.3 + ACI 318-19 §22.4.2.2 masonry/RC pier axial capacity with h/r slenderness factor
    "kerf_cad_core.arch.bearing_wall_axial_tools",     # arch_check_bearing_wall_axial: ACI 318-19 §11.5.3.1 + TMS 402-22 §8.3 plain/masonry bearing wall axial capacity + DCR
    "kerf_cad_core.arch.lintel_design_tools",          # arch_design_lintel: AISC Table 3-23 + ACI 318-19 §9 + TMS 402-22 §5 lintel design (steel/RC/RM; 45° arching; L/240 or L/360)
    "kerf_cad_core.arch.anchor_bolt_pullout_tools",   # arch_check_anchor_pullout: ACI 318-19 §17.6 cast-in-place headed bolt tension — steel §17.6.1 + concrete breakout §17.6.2 + pullout §17.6.3
    "kerf_cad_core.arch.opening_in_wall_tools",       # arch_check_opening_in_wall: IBC §2308.4 + ACI 318-19 §11.5.3.1 + TMS 402-22 §8.3 wall opening tributary jamb load + capacity + lintel DCR
    "kerf_cad_core.arch.slab_on_grade_tools",        # arch_check_slab_on_grade: ACI 360R-10 + Westergaard (1948) slab-on-grade concentrated interior load; l, σ_max, MR, DCR, joint spacing (30·h PCA rule)
    "kerf_cad_core.arch.bolt_shear_aisc",     # arch_check_bolt_shear: AISC 360-22 §J3.6 bolt-group shear (bearing-type/slip-critical; single/double shear; bearing §J3.10a + tearout §J3.10b + slip §J3.8)
    "kerf_cad_core.arch.stair_stringer_tools",      # arch_design_stair_stringer: IBC §1011.5.2 rise/tread + AWC NDS-2018 §3.3 wood bending + AISC 360-22 §F2 steel bending; DCR bending + L/360 deflection
    "kerf_cad_core.civil.hydraulics_tools",
    "kerf_cad_core.tolstack.tools",
    "kerf_cad_core.kinematics.tools",
    "kerf_cad_core.fea.tools",
    "kerf_cad_core.springs.tools",
    "kerf_cad_core.piping.tools",
    # Wave 12B: AVEVA E3D parity (piping catalog + multi-discipline + concurrent)
    "kerf_cad_core.piping.piping_advanced_tools",
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
    # OPTICS-SCHMIDT-CORRECTOR-PLATE: Schmidt corrector plate aspheric sag profile
    # z(r) = r²·(r² − 2·κ·ρ_n²) / [8·(n−1)·R³] (Schmidt 1932 / Born & Wolf §6.3)
    # LLM tool: optics_design_schmidt_corrector
    "kerf_cad_core.optics.schmidt_corrector",
    # OPTICS-COMA-COEFFICIENT: Seidel S_II + Hopkins W_131 for a single thin lens
    # via Welford §7.4 closed-form polynomial (shape factor q, conjugate factor p)
    # LLM tool: optics_compute_coma_coefficient
    "kerf_cad_core.optics.coma_coefficient",
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
    # NURBS-CURVE-LINE-FIT: fit straight line to 2D NurbsCurve via TLS/SVD (Press §15.7; Lawson-Hanson §6)
    "kerf_cad_core.geom.curve_line_fit",
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
    "kerf_cad_core.geom.network_surface",
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
    # GK-P17: parametric sheet-metal flanges/bends/unfold + flat-pattern (Suchy §3 + DIN 6935)
    "kerf_cad_core.sheetmetal_features",
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
    # SUBD-CAGE-FACE-LOOP: face loop walk on quad cage; hops through opposite-edge adjacent quads; walk_direction 0/1 for orthogonal rings (Bommes-Lévy-Pietroni 2013 §3.2; Hoppe 1996)
    "kerf_cad_core.subd.face_loop_select",
    # SUBD-LIMIT-NORMAL-FIT: sample CC limit-surface normal n̂(u,v) at uniform grid; residuals vs bilinear approx (Stam 1998 §3.2; Halstead-Kass-DeRose 1993)
    "kerf_cad_core.subd.limit_normal_fit",
    # SUBD-CAGE-EDGE-COLLAPSE: collapse a quad cage edge to midpoint; merge v_a+v_b→v_m; remove degenerate faces (Hoppe 1996 §3.2; Bommes-Lévy-Pietroni 2013 §4)
    "kerf_cad_core.subd.edge_collapse",
    # SUBD-CAGE-VERTEX-MERGE: merge N cage vertices by index into centroid; N-vertex generalisation of edge collapse; remove degenerate faces (Hoppe 1996 §3.2; Garland-Heckbert 1997 QEM §3)
    "kerf_cad_core.subd.vertex_merge",
    # SUBD-CAGE-DUAL-MESH: dual mesh of quad cage — face centroids become dual verts; vertex star becomes dual face (CCW angular sort); ringing analysis + mesh smoothing (Bossen-Heckbert 1996 §3.1; Bommes-Lévy-Pietroni 2013 §3.2)
    "kerf_cad_core.subd.dual_mesh",
    # SUBD-CAGE-EDGE-FLIP: topological edge flip for two adjacent triangles sharing an edge; replace (v_a,v_b) with (v_c,v_d) opposite vertices; triangles only; no Delaunay in-circle test (Bommes-Lévy-Pietroni 2013 §3; Edelsbrunner 2001 §2)
    "kerf_cad_core.subd.edge_flip",
    # SUBD-CAGE-AREA: total surface area of control polygon; limit-surface estimate ×0.94 (empirical Catmull-Clark shrinkage; Catmull-Clark 1978; Stam 1998 §2; Zorin-Schröder 2000 §3); per-face distribution; degenerate face flagging (area < 1e-6 mm²)
    "kerf_cad_core.subd.cage_area",
    # GK-P12: Stam exact limit tangents at extraordinary CC vertices (valence n!=4) via eigenstructure (Stam 1998 §3.2-3.3; Reif 1995; Meyer et al. 2003)
    "kerf_cad_core.subd.stam_limit_tangents",
    # GK-P13: G1 continuity at extraordinary-vertex SubD→NURBS conversion (Loop 1987 §4; Stam 1998 §3.1-3.3; Peters-Reif 2008 §7.4)
    "kerf_cad_core.subd.g1_extraordinary_patches",
    # GK-P14: fractional crease sharpness decay s_new=max(0,s-1) per level (DeRose-Kass-Truong 1998 §4; OpenSubdiv hierarchical edits)
    "kerf_cad_core.subd.crease_fractional_decay",
    # GK-P19: SubD feature curves — ridge/valley polylines from CC limit surface via discrete principal-curvature analysis (Ohtake et al. 2004 SIGGRAPH; Meyer et al. 2003 cotangent Laplacian; Taubin 1995 curvature tensor)
    "kerf_cad_core.subd.feature_curves",
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
    # GK-P23: in-process isotropic remesh fallback (Botsch-Kobbelt 2004) — dataclass API
    "kerf_cad_core.mesh_isotropic_remesh",
    # GK-P58: B-rep UV unwrap atlas (brep_uv_unwrap, brep_uv_distortion_report)
    "kerf_cad_core.geom.brep_uv_tools",
    # GK-P11: isophote / EMap continuity analyser (IsophoteSpec / IsophoteReport / analyze_isophotes)
    # nurbs_analyze_isophotes LLM tool — marching-squares isolines + fairness score
    "kerf_cad_core.geom.isophote_analyzer",
    # GK-P10: MatchSrf G3 — curvature-rate (dκ/ds) continuity; MatchSrfG3Spec/Report/match_srf_g3
    # nurbs_match_srf_g3 LLM tool; requires degree >= 3 and >= 4 CP rows
    "kerf_cad_core.geom.match_srf_g3",
    # GK-P47: isophote analysis (feature_isophote_analysis added to surfacing module above)
    # GK-P47: match_srf G3 is in geom.match_srf (also in match_srf_g3 above for dedicated API)
    # GK-P47: feature_loft guide_curves is in feature_loft (already in _TOOL_MODULES above)
    # GK-P48: construction verbs (hem_sheet, jog_sheet, multi_flange, delete_face, push_pull, gusset_plate, cope_notch)
    "kerf_cad_core.construction_verbs_tools",
    # GK-P (B-rep heal + inertia): industrial STEP-import clean-up pass
    "kerf_cad_core.geom.brep_heal",                     # brep_heal, brep_compute_inertia — industrial heal pipeline + inertia tensor
    # GK-P: degree raise + lower (Cohen-Lyche-Schumaker 1985)
    "kerf_cad_core.geom.degree_op",
    # NURBS-CURVE-DEGREE-LOWER: Piegl-Tiller §6.5 + Schumaker §6 degree reduction with deviation reporting
    "kerf_cad_core.geom.curve_degree_lower",
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
    "kerf_cad_core.geom.assembly_interference",   # brep_assembly_interference, brep_check_clearance
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
    "kerf_cad_core.geom.brep_connect_inspector",
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
    "kerf_cad_core.geom.face_planarity",
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
    "kerf_cad_core.geom.topology_euler_check",
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
    # NURBS-SURFACE-CURVATURE-MAP: scalar Gaussian/mean/|κ₁|/|κ₂| heatmap over UV grid;
    # viridis or RdBu colourmap; complements principal_curvature_viz (scalar field only)
    # (do Carmo §3.3 / Mortenson §6.5) — nurbs_sample_surface_curvature_map LLM tool
    "kerf_cad_core.geom.surface_curvature_map",         # nurbs_sample_surface_curvature_map
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
    # BREP-EDGE-FACE-NORMAL-FLIP: detect and fix inconsistently-oriented B-rep face normals
    # via iterative neighbour-consensus voting (Mantyla §6.4; Hoffmann §3).
    # LLM tool: brep_detect_and_flip_face_normals
    "kerf_cad_core.geom.face_normal_flip",
    # NURBS-CURVE-CONIC-DETECT: classify 2-D NurbsCurve/point-set as conic via algebraic LS
    # (Pratt 1987 SIGGRAPH + Fitzgibbon-Pilu-Fisher 1999 IEEE TPAMI).
    # Classifies: circle|ellipse|parabola|hyperbola|line|free_form.
    # LLM tool: nurbs_detect_conic_type
    "kerf_cad_core.geom.curve_conic_detect",
    # BREP-VERTEX-DEGREE-CHECK: count incident edges per vertex; flag boundary
    # (degree < expected_degree) and non-manifold (degree > expected_degree + 2).
    # Returns per-vertex degree histogram + irregular vertex indices.
    # HONEST: edge-based degree only; does NOT analyse face-fan angular order.
    # Refs: Mantyla 1988 §3.4; Hoffmann 1989 §4. LLM tool: brep_check_vertex_degrees
    "kerf_cad_core.geom.vertex_degree_check",
    # NURBS-SURFACE-SHEAR-OFFSET: global linear shear transform on NurbsSurface
    # control points for warp compensation during finish-machining post-processing.
    # (Mortenson §4.8; Piegl & Tiller §6.1). LLM tool: nurbs_apply_surface_shear_offset
    "kerf_cad_core.geom.surface_shear_offset",
    # NURBS-CURVE-FIT-G2: degree-5 B-spline fit with G2 (curvature-continuous)
    # end conditions (Piegl & Tiller §9.4; Farin "CAGD" Ch 10).
    # Prescribe tangent + curvature vectors at both endpoints for surface blending.
    # HONEST: chord-length parameterisation; centripetal may give better results
    # for high-aspect-ratio data. LLM tool: nurbs_fit_curve_g2
    "kerf_cad_core.geom.curve_fit_g2",
    # BREP-WIRE-CLOSED-CHECK: ordered edge-list closure + SVD planarity (Mantyla §3; Hoffmann §4)
    # LLM tool: brep_check_wire_closed
    "kerf_cad_core.geom.wire_closed_check",
    # BREP-FACE-PLANE-DEVIATION: SVD least-squares best-fit plane from pre-sampled points;
    # max/RMS deviation + planarity classification (Pratt 1987 §3; Eberly §6.6).
    # STEP/IGES import validation + surface flatness QC.
    # LLM tool: geom_check_face_planarity
    "kerf_cad_core.geom.face_plane_deviation",
    # NURBS-SURFACE-ANALYTIC-DERIVATIVES (GK-P15): closed-form ∂S/∂u, ∂S/∂v,
    # ∂²S/∂u², ∂²S/∂u∂v, ∂²S/∂v² (P&T A3.6 + rational A4.4). Gaussian K, mean H.
    # SSIHardenedMarcher: near-tangent bisection fallback (Patrikalakis & Maekawa §5).
    # LLM tool: nurbs_surface_derivatives_analytic
    "kerf_cad_core.geom.surface_analytic_derivatives",
    # GK-P16: NURBS loft with cross-section curves + guide rails
    # (Piegl & Tiller §10.3 skinning + Gaussian displacement-blend guide deformation).
    # HONEST: approximate guide-rail constraint; deviations reported for QC.
    # LLM tool: nurbs_loft_with_guide_rails
    "kerf_cad_core.geom.loft_guide_rails",
    # GK-P22: sculpt brushes for SubD cages + triangle meshes (inflate/crease/smooth/pinch)
    # Wendland C2 falloff w(t)=(1-t^2)^2; Botsch-Sorkine 2008 S3; Sculptris/ZBrush brush math.
    # LLM tool: mesh_sculpt_brush
    "kerf_cad_core.mesh_sculpt_brushes",
    # GK-P21: displacement layer stack — multi-layer ordered displacement with per-layer mode
    # (add/subtract/multiply/replace) + mask + strength. ZBrush/Mudbox layer-stack model.
    # Aumann-McNamara 2009 Layered Displacement Maps; Lee-Moreton-Hoppe 2000 DSS.
    # HONEST: per-vertex only (no barycentric interpolation); assumes unit-length input normals.
    # LLM tool: mesh_apply_displacement_stack
    "kerf_cad_core.mesh_displacement_stack",
    # GK-P20: UV-unwrap hardening — seam-cut + shelf pack + distortion stats.
    # Sander et al. (2003) Multi-Chart Geometry Images + Lévy et al. (2002) LSCM.
    # HONEST: shelf packing only; 90°-increment rotation; sampling-based distortion.
    # LLM tool: nurbs_harden_uv_unwrap
    "kerf_cad_core.geom.uv_unwrap_hardening",
    # Wave 8B: LSCM UV unwrap LLM tool wrapper (Lévy et al. 2002)
    # LLM tool: lscm_uv_unwrap
    "kerf_cad_core.sculpt.lscm_uv_tool",
    # Wave 8: SubD limit tangent (Stam 1998 exact evaluation at extraordinary vertices)
    # LLM tools: subd_limit_tangent, subd_fractional_crease, subd_multires_eval
    "kerf_cad_core.subd.tools",
    # Wave 8: NURBS surface analytic derivative + fundamental forms (P&T §3.3 / do Carmo §3.2)
    # LLM tool: nurbs_surface_derivative
    "kerf_cad_core.geom.nurbs_derivative_tools",
    # Wave 8: B-rep HLR drawing projection (Appel 1967 QI + Markosian 1997 silhouette)
    # LLM tool: brep_to_2d_hlr
    "kerf_cad_core.drawings.tools",
    # Wave 8: SDF CSG + Marching Cubes polygonizer (Lorensen-Cline 1987 / Quilez 2008)
    # LLM tool: sdf_polygonize
    "kerf_cad_core.sdf.tools",
    # Wave 8: sculpt brush (grab/smooth/inflate/crease/pinch on triangle mesh)
    # LLM tool: sculpt_apply_brush  (distinct from mesh_sculpt_brush in mesh_sculpt_brushes.py)
    "kerf_cad_core.sculpt.tools",
    # Wave 8: AFR parametric DAG ordering (Han-Pratt-Regli 2000 + ISO 10303-224 AP224)
    # LLM tool: afr_topology_dag
    "kerf_cad_core.afr.tools",
    # Wave 8: photon-map caustic render (Jensen 1996 two-pass; Sellmeier dispersion)
    # LLM tool: optics_render_caustic
    "kerf_cad_core.optics.caustic_tools",
    # Wave 8: viewport LOD bridge (Clark 1976 hierarchical LOD; Akenine-Möller §19.9)
    # LLM tool: assembly_plan_viewport_lods
    "kerf_cad_core.assembly.lod_viewport_tools",
    # Wave 9A: assembly motion interference sweep
    "kerf_cad_core.brep.motion_interference_tools",
    # Wave 9A: LAS / E57 point cloud readers
    "kerf_cad_core.scan.las_e57_tools",  # scan_load_las + scan_load_e57
    # Wave 9A: civil parcel subdivision (BLM Manual §6) + plan-and-profile sheet (ASCE Manual 21)
    "kerf_cad_core.civil.parcels_tools",                # parcel_polygon_stats + parcel_subdivide
    "kerf_cad_core.civil.plan_profile_sheet_tools",     # civil_plan_profile_sheet
    # Wave 9B: ZBrush-equivalent organic sculpt depth
    "kerf_cad_core.sculpt.sculpt_extended_tools",       # dynamesh + polypaint + displacement_bake + character_rigging
    # Wave 9B: animation + skeletal rig
    "kerf_cad_core.animation.tools",                    # animation_evaluate_clip + animation_solve_ik + animation_apply_pose
    # Wave 9B: clo3d avatar + mozaik cabinet room layout
    "kerf_cad_core.apparel.avatar_tools",               # apparel_build_avatar + apparel_fit_dress_form (ISO 8559-1:2017)
    "kerf_cad_core.woodworking.cabinet_room_layout_tools",  # woodworking_auto_layout_cabinets + woodworking_detect_collisions (NKBA 2021)
    # Wave 9B: vectorworks Marionette + Braceworks rigging + matrixgold visual scripting
    "kerf_cad_core.rigging.structural_load_tools",         # rigging_analyze_structural_load + rigging_cable_catenary_tension (BS 7905, ANSI E1.2)
    "kerf_cad_core.visualscript.marionette_tools",         # visualscript_evaluate_graph + visualscript_topological_order + visualscript_list_node_types
    # Wave 9B: archviz render + theatrical lighting + luminance sim + Phoenix-FD visual fluid
    "kerf_cad_core.render.render_tools",   # render_parse_ies_file + render_theatrical_lighting_plot + render_lux_simulation + render_archviz_scene + render_fluid_smoke_step + render_fluid_flip_step
    # Wave 9D: Zemax metalens + STOP multiphysics
    "kerf_cad_core.optics.advanced_optics_tools",  # optics_design_metalens + optics_metalens_chromatic_efficiency + optics_stop_analysis + optics_thermal_expansion
    # Wave 9D: 8760-hr ASHRAE compliance + Title 24 + LEED v4 EAp2 + HVAC plant
    "kerf_cad_core.buildingenergy.compliance_8760_tools",  # be_simulate_8760, be_check_title24, be_evaluate_leed_eap2, be_simulate_hvac_plant
    # Wave 9D: FiberSim AFP/ATL composite paths + laser projection
    "kerf_cad_core.composites.afp_atl_tools",  # composites_generate_afp_paths + composites_export_apt_cl + composites_laser_projection + composites_develop_flat_pattern + composites_export_flat_dxf
    # Wave 10C: GMAT libration orbits + orbit determination
    "kerf_cad_core.aerospace.aerospace_tools",  # aerospace_compute_lagrange_points + aerospace_design_halo_orbit + aerospace_design_lyapunov_orbit + aerospace_design_lissajous_orbit + aerospace_batch_od + aerospace_ekf_od
    # Wave 11B: e-textiles + pattern grading + artioscad material cost
    # kerf_cad_core.apparel.e_textiles — conductive thread routing + wearable electronics (Kazani et al. 2014)
    # kerf_cad_core.apparel.pattern_grading — multi-size pattern grading (Aldrich 6e, Mullet 2e)
    # kerf_cad_core.apparel.seam_layout — seam types + allowances (ISO 4916, ASTM D6193)
    # kerf_cad_core.packaging.material_yield — sheet yield + material cost (PMMI handbook)
    # Wave 11B: classical controls (Routh/Bode/PID/SS/LQR)
    # transfer_function: TransferFunction, routh_hurwitz, bode_plot_data, nyquist_plot_data, gain_phase_margin, feedback
    # pid_tuning: PidParams, step_pid, ziegler_nichols_open_loop, ziegler_nichols_closed_loop, imc_tuning, lambda_tuning
    # state_space: StateSpace, is_controllable, is_observable, place_poles, lqr
    "kerf_cad_core.controls.tools",  # controls tools (already registered above; Wave 11B adds TF/PID/SS modules)
    # Wave 11B: civil — dynamic TIN + gravity pipe (Manning) + pressure pipe (Hazen-Williams) networks
    "kerf_cad_core.civil.civil_advanced_tools",
    # Wave 11B: aerospace — openrocket motor DB (RASP .eng + Estes/AeroTech catalogs)
    "kerf_cad_core.aerospace.motor_database",
    # Wave 12B: Ashby material selection — Cambridge Engineering Selector-equivalent
    # material DB + selection charts + multi-criteria optimization (Granta MI parity)
    # ashby_list_materials + ashby_get_material + ashby_select_materials +
    # ashby_build_chart + ashby_pareto_front
    # Ashby (2017) "Materials Selection in Mechanical Design" 5e; Ashby (2018) 4e
    "kerf_cad_core.materials.material_tools",
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
