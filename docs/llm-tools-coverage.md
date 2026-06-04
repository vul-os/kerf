# LLM Tools Coverage Report

*Generated: 2026-06-04 · Script: `scripts/audit_llm_docs.py`*

## Summary

| Metric | Value |
|--------|-------|
| Total modules | 293 |
| Modules with llm\_docs | 293 |
| Coverage | 293/293 (100%) |
| Docs created this run | 0 |
| Docs updated this run | 0 |
| Import errors | 0 |

## Domain coverage matrix

| Package | Domain | Modules | With docs | Coverage |
|---------|--------|---------|-----------|----------|
| `kerf-cad-core` | cad | 131 | 131 | 100% |
| `kerf-electronics` | electronics | 90 | 90 | 100% |
| `kerf-bim` | bim | 29 | 29 | 100% |
| `kerf-imports` | imports | 26 | 26 | 100% |
| `kerf-parts` | parts | 1 | 1 | 100% |
| `kerf-woodworking` | woodworking | 2 | 2 | 100% |
| `kerf-api` | api | 10 | 10 | 100% |
| `kerf-lca` | lca | 4 | 4 | 100% |

## Registered tools by package

### `kerf-cad-core`

| Module | Tools | Doc file |
|--------|-------|----------|
| `kerf_cad_core.feature_cut_from_sketch` | `feature_cut_from_sketch` | `feature_cut_from_sketch.md` |
| `kerf_cad_core.feature_hole_pattern_from_sketch` | `feature_hole_pattern_from_sketch` | `feature_hole_pattern_from_sketch.md` |
| `kerf_cad_core.feature_loft` | `feature_loft` | `feature_loft.md` |
| `kerf_cad_core.feature_section` | `feature_section` | `feature_section.md` |
| `kerf_cad_core.cam_layered` | `feature_cam_layered` | `cam_layered.md` |
| `kerf_cad_core.cam_toolpath_collision` | `cam_verify_toolpath_collision` | `cam_toolpath_collision.md` |
| `kerf_cad_core.cam_feedrate_lookahead` | `cam_optimize_feedrate_lookahead` | `cam_feedrate_lookahead.md` |
| `kerf_cad_core.cam_gcode_emit` | `cam_emit_gcode` | `cam_gcode_emit.md` |
| `kerf_cad_core.cam_lathe_profile` | `cam_emit_lathe_gcode` | `cam_lathe_profile.md` |
| `kerf_cad_core.cam_wire_edm_path` | `cam_emit_wire_edm_gcode` | `cam_wire_edm_path.md` |
| `kerf_cad_core.extrude_sketch_to_jscad` | `extrude_sketch_to_jscad` | `extrude_sketch_to_jscad.md` |
| `kerf_cad_core.surfacing` | `feature_sweep1`, `feature_sweep2`, `feature_network_srf`, `feature_blend_srf` +14 | `surfacing.md` |
| `kerf_cad_core.quad_remesh` | `feature_quad_remesh` | `quad_remesh.md` |
| `kerf_cad_core.jewelry.gemstones` | `jewelry_create_gemstone`, `jewelry_gem_report`, `jewelry_gem_catalog` | `gemstones.md` |
| `kerf_cad_core.jewelry.gem_seat` | `jewelry_cut_gem_seat`, `jewelry_cut_channel_seat`, `jewelry_cut_bezel_seat`, `jewelry_cut_fishtail_seat` +5 | `gem_seat.md` |
| `kerf_cad_core.jewelry.settings` | `jewelry_create_prong_head`, `jewelry_create_bezel`, `jewelry_create_channel`, `jewelry_pave_array` +21 | `settings.md` |
| `kerf_cad_core.jewelry.ring` | `jewelry_ring_size_to_diameter`, `jewelry_create_ring_shank`, `jewelry_create_eternity_band`, `jewelry_create_signet_ring` +7 | `ring.md` |
| `kerf_cad_core.jewelry.tool_metal_cost` | `jewelry_metal_cost` | `tool_metal_cost.md` |
| `kerf_cad_core.jewelry.chain` | `jewelry_chain_length`, `jewelry_create_chain`, `jewelry_create_tennis_bracelet`, `jewelry_create_station_necklace` +4 | `chain.md` |
| `kerf_cad_core.jewelry.findings` | `jewelry_list_findings`, `jewelry_create_finding` | `findings.md` |
| `kerf_cad_core.jewelry.decorative` | `jewelry_apply_milgrain`, `jewelry_apply_beading`, `jewelry_apply_filigree`, `jewelry_apply_twisted_wire` +2 | `decorative.md` |
| `kerf_cad_core.jewelry.pieces` | `jewelry_create_pendant`, `jewelry_create_earrings`, `jewelry_create_brooch`, `jewelry_create_cufflink` +1 | `pieces.md` |
| `kerf_cad_core.jewelry.casting_export` | `jewelry_casting_export` | `casting_export.md` |
| `kerf_cad_core.jewelry.templates` | `list_jewelry_templates`, `instantiate_jewelry_template` | `templates.md` |
| `kerf_cad_core.jewelry.pave_wizard` | `jewelry_pave_wizard`, `jewelry_pave_wizard_stats`, `jewelry_pave_wizard_update` | `pave_wizard.md` |
| `kerf_cad_core.jewelry.setter_checklist` | `jewelry_setter_checklist`, `jewelry_tool_inventory`, `jewelry_time_estimate_total` | `setter_checklist.md` |
| `kerf_cad_core.sheet_metal` | `sheet_metal_flange`, `sheet_metal_unfold`, `sheet_metal_flat_pattern` | `sheet_metal.md` |
| `kerf_cad_core.gdt.tools` | `gdt_apply_datum`, `gdt_apply_tolerance`, `gdt_validate_scheme`, `gdt_callout_report` | `gdt.md` |
| `kerf_cad_core.gdt.composite_tolerance_check` | `gdt_validate_composite_frame` | `composite_tolerance_check.md` |
| `kerf_cad_core.gdt.datum_shift_check` | `gdt_compute_datum_shift` | `datum_shift_check.md` |
| `kerf_cad_core.gdt.feature_of_size_dof` | `gdt_compute_fos_dof` | `feature_of_size_dof.md` |
| `kerf_cad_core.gdt.runout_check` | `gdt_check_runout` | `runout_check.md` |
| `kerf_cad_core.gdt.runout_circular` | `gdt_check_circular_runout` | `runout_circular.md` |
| `kerf_cad_core.gdt.dimension_chain` | `gdt_compute_dimension_chain` | `dimension_chain.md` |
| `kerf_cad_core.gdt.composite_position` | `gdt_check_composite_position` | `composite_position.md` |
| `kerf_cad_core.arch.tools` | `arch_wall`, `arch_door`, `arch_window`, `arch_slab` +2 | `arch.md` |
| `kerf_cad_core.struct.tools` | `struct_grid`, `struct_level`, `struct_column`, `struct_beam` +1 | `struct.md` |
| `kerf_cad_core.feature_thread` | `feature_tapped_hole`, `feature_thread_external`, `thread_lookup` | `feature_thread.md` |
| `kerf_cad_core.assembly.tools` | `assembly_create`, `assembly_add_component`, `assembly_add_mate`, `assembly_solve` +1 | `assembly.md` |
| `kerf_cad_core.assembly.perf` | `assembly_perf_report`, `assembly_lod_plan` | `perf.md` |
| `kerf_cad_core.weldment` | `weldment_frame`, `weldment_profile_lookup`, `weldment_cutlist` | `weldment.md` |
| `kerf_cad_core.civil.tools` | `civil_terrain`, `civil_pad`, `civil_earthwork`, `civil_grading_report` | `civil.md` |
| `kerf_cad_core.civil.alignment_tools` | `align_horizontal`, `align_spiral`, `align_vertical`, `align_station_at` | `alignment_tools.md` |
| `kerf_cad_core.civil.corridor_sheet_tools` | `civil_generate_corridor_sheets` | `corridor_sheet_tools.md` |
| `kerf_cad_core.gears` | `gear_spur`, `gear_helical`, `gear_internal`, `gear_rack` +1 | `gears.md` |
| `kerf_cad_core.geom.surface_boolean_robust` | — | `surface_boolean_robust.md` |
| `kerf_cad_core.geom.nurbs_boolean` | `nurbs_solid_boolean` | `nurbs_boolean.md` |
| `kerf_cad_core.geom.general_boolean` | — | `general_boolean.md` |
| `kerf_cad_core.geom.curve_footprint_on_plane` | `nurbs_curve_project_to_plane` | `curve_footprint_on_plane.md` |
| `kerf_cad_core.geom.osculating_circle` | `nurbs_osculating_circle` | `osculating_circle.md` |
| `kerf_cad_core.geom.face_developable_check` | `brep_check_face_developable` | `face_developable_check.md` |
| `kerf_cad_core.geom.fresnel_parameterize` | `nurbs_fresnel_parameterize_curve` | `fresnel_parameterize.md` |
| `kerf_cad_core.geom.curve_evolute` | `nurbs_compute_curve_evolute` | `curve_evolute.md` |
| `kerf_cad_core.geom.curve_inflection` | `nurbs_find_curve_inflections` | `curve_inflection.md` |
| `kerf_cad_core.geom.offset_far_correction` | `nurbs_surface_offset_robust` | `offset_far_correction.md` |
| `kerf_cad_core.geom.trim_curve` | `query_trim_curve_uv`, `validate_trim_curve` | `trim_curve.md` |
| `kerf_cad_core.geom.trim_loop_heal` | `nurbs_trim_loop_heal` | `trim_loop_heal.md` |
| `kerf_cad_core.geom.subd_decimate_to_cage_tool` | `subd_decimate_dense_mesh_to_cage` | `subd_decimate_to_cage_tool.md` |
| `kerf_cad_core.geom.subd_project_primitive_tools` | `subd_project_cage_to_sphere`, `subd_project_cage_to_cylinder`, `subd_project_cage_to_plane` | `subd_project_primitive_tools.md` |
| `kerf_cad_core.geom.subd_export_gltf` | `subd_export_limit_to_gltf` | `subd_export_gltf.md` |
| `kerf_cad_core.geom.subd_export_step` | `subd_export_limit_to_step` | `subd_export_step.md` |
| `kerf_cad_core.nesting.tools` | `nest_parts`, `nest_report` | `nesting.md` |
| `kerf_cad_core.nesting.optimize_nest_tool` | `manufacturing_optimize_nest` | `optimize_nest_tool.md` |
| `kerf_cad_core.harness.tools` | `harness_route`, `harness_bundle_diameter`, `harness_bom` | `harness.md` |
| `kerf_cad_core.clash.tools` | `clash_detect` | `clash.md` |
| `kerf_cad_core.marine.tools` | `marine_hull_from_offsets`, `marine_fairing_report`, `marine_hydrostatics`, `marine_hull_fair_surface` | `marine.md` |
| `kerf_cad_core.scan.tools` | `scan_load`, `scan_fit_plane`, `scan_fit_sphere`, `scan_fit_cylinder` +1 | `scan.md` |
| `kerf_cad_core.scan.nurbs_fit_tools` | `scan_fit_nurbs_surface` | `nurbs_fit_tools.md` |
| `kerf_cad_core.reverse_engineering.tools` | — | `reverse_engineering.md` |
| `kerf_cad_core.gdt_callouts.tools` | `gdt_auto_callouts`, `gdt_callout_balloon_table` | `gdt_callouts.md` |
| `kerf_cad_core.family.tools` | `family_define`, `family_add_type`, `family_instantiate`, `family_validate` | `family.md` |
| `kerf_cad_core.shaft.tools` | `shaft_diameter`, `shaft_critical_speed`, `bearing_l10`, `key_size` | `shaft.md` |
| `kerf_cad_core.gearbox.tools` | `gearbox_design`, `gearbox_ratio`, `gearbox_shaft_table` | `gearbox.md` |
| `kerf_cad_core.arch.spaces_tools` | `arch_room`, `arch_area_schedule`, `arch_occupancy_load` | `spaces_tools.md` |
| `kerf_cad_core.arch.column_load_check_tools` | `arch_check_column_load` | `column_load_check_tools.md` |
| `kerf_cad_core.arch.beam_deflection_tools` | `arch_compute_beam_deflection` | `beam_deflection_tools.md` |
| `kerf_cad_core.arch.footing_bearing_tools` | `arch_compute_bearing_capacity` | `footing_bearing_tools.md` |
| `kerf_cad_core.arch.slab_deflection_tools` | `arch_compute_slab_deflection` | `slab_deflection_tools.md` |
| `kerf_cad_core.arch.wind_load_asce7_tools` | `arch_compute_wind_load` | `wind_load_asce7_tools.md` |
| `kerf_cad_core.arch.lateral_bracing_check_tools` | `arch_check_lateral_bracing` | `lateral_bracing_check_tools.md` |
| `kerf_cad_core.arch.punching_shear_tools` | `arch_check_punching_shear` | `punching_shear_tools.md` |
| `kerf_cad_core.arch.wind_component_cladding_tools` | `arch_compute_wind_cc_pressure` | `wind_component_cladding_tools.md` |
| `kerf_cad_core.arch.base_plate_aisc_tools` | `arch_design_base_plate` | `base_plate_aisc_tools.md` |
| `kerf_cad_core.arch.shear_wall_oop_tools` | `arch_check_shear_wall_oop` | `shear_wall_oop_tools.md` |
| `kerf_cad_core.arch.diaphragm_shear_tools` | `arch_check_diaphragm_shear` | `diaphragm_shear_tools.md` |
| `kerf_cad_core.arch.retaining_wall_stability_tools` | `arch_check_retaining_wall_stability` | `retaining_wall_stability_tools.md` |
| `kerf_cad_core.arch.pier_axial_capacity_tools` | `arch_check_pier_axial` | `pier_axial_capacity_tools.md` |
| `kerf_cad_core.arch.bearing_wall_axial_tools` | `arch_check_bearing_wall_axial` | `bearing_wall_axial_tools.md` |
| `kerf_cad_core.arch.lintel_design_tools` | `arch_design_lintel` | `lintel_design_tools.md` |
| `kerf_cad_core.arch.anchor_bolt_pullout_tools` | `arch_check_anchor_pullout` | `anchor_bolt_pullout_tools.md` |
| `kerf_cad_core.arch.opening_in_wall_tools` | `arch_check_opening_in_wall` | `opening_in_wall_tools.md` |
| `kerf_cad_core.arch.slab_on_grade_tools` | `arch_check_slab_on_grade` | `slab_on_grade_tools.md` |
| `kerf_cad_core.arch.bolt_shear_aisc` | `arch_check_bolt_shear` | `bolt_shear_aisc.md` |
| `kerf_cad_core.arch.stair_stringer_tools` | `arch_design_stair_stringer` | `stair_stringer_tools.md` |
| `kerf_cad_core.civil.hydraulics_tools` | `hydraulics_pipe_network`, `hydraulics_manning` | `hydraulics_tools.md` |
| `kerf_cad_core.tolstack.tools` | `tolstack_analyze`, `tolstack_methods` | `tolstack.md` |
| `kerf_cad_core.kinematics.tools` | `four_bar_grashof`, `four_bar_position`, `four_bar_transmission_angle`, `four_bar_coupler_curve` +3 | `kinematics.md` |
| `kerf_cad_core.fea.tools` | `fea_solve_truss`, `fea_solve_bar_plastic` | `fea.md` |
| `kerf_cad_core.springs.tools` | `spring_compression`, `spring_extension`, `spring_torsion`, `spring_belleville` | `springs.md` |
| `kerf_cad_core.piping.tools` | `pipe_schedule_lookup`, `pipe_wall_thickness`, `pipe_pressure_drop`, `pipe_allowable_span` +3 | `piping.md` |
| `kerf_cad_core.piping.piping_advanced_tools` | `pipe_component_catalog_query`, `pipe_run_bom`, `plant_federation_clash` | `piping_advanced_tools.md` |
| `kerf_cad_core.hvac.tools` | `hvac_cfm_from_sensible_load`, `hvac_round_duct_diameter`, `hvac_rect_equiv_diameter`, `hvac_duct_friction_loss` +5 | `hvac.md` |
| `kerf_cad_core.turning.tools` | `turning_cutting_params`, `turning_roughing_passes`, `turning_finishing_pass`, `turning_facing` +4 | `turning.md` |
| `kerf_cad_core.steelconn.tools` | `electrode_strength`, `bolt_shear_capacity`, `bolt_bearing_capacity`, `bolt_tension_capacity` +6 | `steelconn.md` |
| `kerf_cad_core.pressvessel.tools` | `pv_cylindrical_shell_thickness`, `pv_spherical_head_thickness`, `pv_ellipsoidal_head_thickness`, `pv_torispherical_head_thickness` +4 | `pressvessel.md` |
| `kerf_cad_core.fasteners.tools` | `bolt_preload_from_torque`, `bolt_stiffness`, `clamped_member_stiffness`, `bolt_joint_load_factor` +5 | `fasteners.md` |
| `kerf_cad_core.fluidpower.tools` | `fp_cylinder`, `fp_pump`, `fp_motor`, `fp_accumulator` +5 | `fluidpower.md` |
| `kerf_cad_core.gearstrength.tools` | `agma_dynamic_factor`, `agma_geometry_factor_J`, `agma_geometry_factor_I`, `agma_bending_stress` +12 | `gearstrength.md` |
| `kerf_cad_core.vibration.tools` | — | `vibration.md` |
| `kerf_cad_core.fatigue.tools` | `fatigue_sn_cycles`, `fatigue_endurance_limit`, `fatigue_strain_life`, `fatigue_neuber_notch` +4 | `fatigue.md` |
| `kerf_cad_core.matsel.tools` | `matsel_get`, `matsel_list`, `matsel_filter`, `matsel_select` | `matsel.md` |
| `kerf_cad_core.pneumatics.tools` | `pneu_cylinder`, `pneu_air_consumption`, `pneu_valve_iso6358`, `pneu_valve_cv` +4 | `pneumatics.md` |
| `kerf_cad_core.heatxfer.tools` | `hx_composite_wall`, `hx_cylindrical_shell`, `hx_spherical_shell`, `hx_nusselt_flat_plate` +13 | `heatxfer.md` |
| `kerf_cad_core.beam.tools` | `beam_section_properties`, `beam_loads`, `beam_superpose`, `beam_buckling` +3 | `beam.md` |
| `kerf_cad_core.casting.tools` | `casting_shrinkage_allowance`, `casting_draft_angle_volume`, `casting_chvorinov`, `casting_riser_size` +3 | `casting.md` |
| `kerf_cad_core.injection.tools` | `injection_polymer_properties`, `injection_clamp_tonnage`, `injection_shot_volume_weight`, `injection_gate_runner_sizing` +6 | `injection.md` |
| `kerf_cad_core.surveying.tools` | `surveying_dms_to_dd`, `surveying_dd_to_dms`, `surveying_bearing_azimuth`, `surveying_forward` +8 | `surveying.md` |
| `kerf_cad_core.geotech.tools` | `geotech_bearing_capacity`, `geotech_settlement`, `geotech_lateral_earth_pressure`, `geotech_retaining_wall` +2 | `geotech.md` |
| `kerf_cad_core.hydrology.tools` | `hydrology_rational_peak_flow`, `hydrology_composite_runoff_coeff`, `hydrology_scs_runoff_depth`, `hydrology_scs_peak_flow` +5 | `hydrology.md` |
| `kerf_cad_core.welding.tools` | `weld_arc_heat_input`, `weld_carbon_equivalent_iiw`, `weld_preheat_temperature`, `weld_cooling_time_t85` +8 | `welding.md` |
| `kerf_cad_core.tolfits.tools` | `iso286_it_tolerance`, `iso286_shaft_limits`, `iso286_hole_limits`, `iso286_fit_analysis` +2 | `tolfits.md` |
| `kerf_cad_core.cncfeeds.tools` | `cnc_spindle_rpm`, `cnc_feed_rate`, `cnc_mrr_milling`, `cnc_mrr_drilling` +9 | `cncfeeds.md` |
| `kerf_cad_core.clutchbrake.tools` | `disc_clutch_torque`, `cone_clutch_torque`, `band_brake_torque`, `drum_brake_torque` +7 | `clutchbrake.md` |
| `kerf_cad_core.pumpsys.tools` | `pump_system_curve`, `pump_system_K_from_pipe`, `pump_curve_fit`, `pump_operating_point` +9 | `pumpsys.md` |
| `kerf_cad_core.beltchain.tools` | `vbelt_design`, `timing_belt_design`, `chain_drive_design` | `beltchain.md` |
| `kerf_cad_core.acoustics.tools` | `acoustics_spl_sum`, `acoustics_spl_subtract`, `acoustics_spl_average`, `acoustics_point_source` +20 | `acoustics.md` |
| `kerf_cad_core.bearings.tools` | `bearing_equivalent_load`, `bearing_rating_life`, `bearing_adjusted_life`, `bearing_static_safety` +6 | `bearings.md` |
| `kerf_cad_core.thermocycle.tools` | `thermo_isentropic_relations`, `thermo_isothermal_process`, `thermo_isobaric_process`, `thermo_isochoric_process` +11 | `thermocycle.md` |
| `kerf_cad_core.robotics.tools` | `robot_fk`, `robot_end_effector_pose`, `robot_ik_2r_planar`, `robot_ik_3r_planar` +5 | `robotics.md` |
| `kerf_cad_core.aero.tools` | `aero_atmosphere`, `aero_dynamic_pressure`, `aero_mach`, `aero_thin_airfoil` +6 | `aero.md` |
| `kerf_cad_core.optics.tools` | `optics_lensmaker`, `optics_thin_lens_imaging`, `optics_mirror_imaging`, `optics_two_lens_system` +42 | `optics.md` |

### `kerf-electronics`

| Module | Tools | Doc file |
|--------|-------|----------|
| `kerf_electronics.tools.kicad_bridge_tools` | `elec_export_kicad`, `elec_import_kicad_pcb` | `kicad_bridge_tools.md` |
| `kerf_electronics.tools.erc` | `run_erc` | `erc.md` |
| `kerf_electronics.tools.buses` | `expand_bus`, `add_bus`, `add_differential_pair`, `list_differential_pairs` | `buses.md` |
| `kerf_electronics.tools.net_classes` | `define_net_class`, `assign_net_to_class`, `remove_net_class`, `list_net_classes` +1 | `net_classes.md` |
| `kerf_electronics.tools.length_tuning` | `set_trace_target_length`, `tune_trace_to_target`, `report_diff_pair_skew`, `match_diff_pair` | `length_tuning.md` |
| `kerf_electronics.tools.via_stitching` | `add_via_stitching`, `apply_teardrops`, `remove_via_stitching` | `via_stitching.md` |
| `kerf_electronics.tools.shove_router` | `route_with_shove` | `shove_router.md` |
| `kerf_electronics.tools.pad_overrides` | `set_pad_mask_override`, `set_pad_paste_override`, `clear_pad_overrides` | `pad_overrides.md` |
| `kerf_electronics.tools.hier_schematic` | `add_sub_sheet`, `remove_sub_sheet`, `add_global_label`, `add_hierarchical_label` +3 | `hier_schematic.md` |
| `kerf_electronics.tools.rf` | `run_rf_study`, `rf_job_status`, `import_touchstone` | `rf.md` |
| `kerf_electronics.tools.autoroute` | `autoroute_circuit` | `autoroute.md` |
| `kerf_electronics.tools.pour` | `add_copper_pour`, `delete_copper_pour`, `set_pour_net`, `set_pour_clearance` | `pour.md` |
| `kerf_electronics.tools.pcb_drc` | `run_pcb_drc`, `set_drc_rule` | `pcb_drc.md` |
| `kerf_electronics.tools.drc_presets` | `list_drc_presets`, `run_drc_with_preset` | `drc_presets.md` |
| `kerf_electronics.tools.pcb_layer_tools` | `add_pcb_layer`, `remove_pcb_layer`, `set_layer_visibility`, `set_layer_color` +6 | `pcb_layer_tools.md` |
| `kerf_electronics.tools.routing` | `route_trace_segments`, `delete_trace`, `split_trace`, `merge_traces` +1 | `routing.md` |
| `kerf_electronics.tools.sim` | `run_simulation`, `sim_job_status` | `sim.md` |
| `kerf_electronics.tools.fab` | `export_gerber`, `export_fab_package`, `export_board_step` | `fab.md` |
| `kerf_electronics.tools.diffpair` | `add_diff_pair`, `route_diff_pair`, `calc_impedance`, `add_length_group` +1 | `diffpair.md` |
| `kerf_electronics.tools.panelize` | `panelize_board`, `panel_info` | `panelize.md` |
| `kerf_electronics.tools.ipc_netlist` | `export_ipc_netlist`, `netlist_report` | `ipc_netlist.md` |
| `kerf_electronics.tools.spice_lib` | `list_spice_models`, `assign_spice_model` | `spice_lib.md` |
| `kerf_electronics.tools.idf_export` | `export_idf` | `idf_export.md` |
| `kerf_electronics.tools.lib_mgmt` | `assign_footprint`, `check_library_assignments` | `lib_mgmt.md` |
| `kerf_electronics.tools.netlist_export` | `export_netlist`, `erc_report` | `netlist_export.md` |
| `kerf_electronics.tools.testpoint` | `generate_testpoints`, `fixture_report` | `testpoint.md` |
| `kerf_electronics.tools.variants` | `define_variant`, `list_variants`, `variant_bom`, `variant_fab` | `variants.md` |
| `kerf_electronics.tools.odbpp_export` | `export_odbpp` | `odbpp_export.md` |
| `kerf_electronics.tools.si` | `si_impedance`, `si_propagation`, `si_crosstalk`, `si_termination` +1 | `si.md` |
| `kerf_electronics.tools.pdn` | `pdn_ir_drop`, `pdn_target_impedance`, `pdn_report` | `pdn.md` |
| `kerf_electronics.tools.bom_cost` | `bom_cost_rollup`, `bom_dfm_report`, `bom_sourcing_risk` | `bom_cost.md` |
| `kerf_electronics.tools.flex_stackup` | `flex_stackup_define`, `flex_bend_check`, `flex_neutral_axis`, `flex_fab_summary` | `flex_stackup.md` |
| `kerf_electronics.tools.eye` | `eye_estimate`, `jitter_budget`, `eye_mask_check` | `eye.md` |
| `kerf_electronics.tools.thermal` | `thermal_junction`, `thermal_board_report`, `thermal_heatsink_required` | `thermal.md` |
| `kerf_electronics.emc.tools` | `emc_radiated_differential`, `emc_radiated_common_mode`, `emc_emission_margin`, `emc_near_field_crosstalk` +1 | `emc.md` |
| `kerf_electronics.battery.tools` | `battery_size_pack`, `battery_runtime`, `battery_charge_time`, `battery_report` | `battery.md` |
| `kerf_electronics.rfmatch.tools` | `rfmatch_reflection`, `rfmatch_lsection`, `rfmatch_pi`, `rfmatch_t` +4 | `rfmatch.md` |
| `kerf_electronics.afilter.tools` | `afilter_butterworth_order`, `afilter_chebyshev_order`, `afilter_bessel_order`, `afilter_butterworth_poles` +10 | `afilter.md` |
| `kerf_electronics.leddriver.tools` | `led_string_layout`, `led_series_resistor`, `led_driver_topology`, `led_buck_cc_design` +3 | `leddriver.md` |
| `kerf_electronics.motordrive.tools` | `motordrive_load_torque_power`, `motordrive_reflected_inertia`, `motordrive_inertia_match`, `motordrive_rms_torque` +8 | `motordrive.md` |
| `kerf_electronics.powerconv.tools` | `powerconv_buck_design`, `powerconv_boost_design`, `powerconv_buck_boost_design`, `powerconv_flyback_design` +2 | `powerconv.md` |
| `kerf_electronics.dsp.tools` | `dsp_fft`, `dsp_ifft`, `dsp_spectrum`, `dsp_bin_frequency` +15 | `dsp.md` |
| `kerf_electronics.oscillator.tools` | `osc_crystal_load_caps`, `osc_pierce_neg_resistance`, `osc_drive_level`, `osc_frequency_pulling` +8 | `oscillator.md` |
| `kerf_electronics.stackup.tools` | `stackup_copper_weight`, `stackup_microstrip_z0`, `stackup_embedded_microstrip_z0`, `stackup_stripline_z0_symmetric` +13 | `stackup.md` |
| `kerf_electronics.protection.tools` | `protection_fuse_select`, `protection_inrush_ntc_size`, `protection_tvs_mov_clamp`, `protection_reverse_polarity` +5 | `protection.md` |
| `kerf_electronics.sensorcond.tools` | `sensorcond_bridge_output`, `sensorcond_bridge_excitation`, `sensorcond_strain_to_stress`, `sensorcond_rtd_resistance` +11 | `sensorcond.md` |
| `kerf_electronics.gatedrive.tools` | `gatedrive_gate_drive_power`, `gatedrive_gate_resistor`, `gatedrive_miller_spurious`, `gatedrive_switching_loss` +5 | `gatedrive.md` |
| `kerf_electronics.linkbudget.tools` | `linkbudget_fspl`, `linkbudget_eirp`, `linkbudget_received_power`, `linkbudget_noise_cascade` +11 | `linkbudget.md` |
| `kerf_electronics.dataconv.tools` | `adc_ideal_snr`, `adc_snr_with_backoff`, `adc_enob_from_sinad`, `adc_interconvert_metrics` +9 | `dataconv.md` |
| `kerf_electronics.elecsafety.tools` | `elecsafety_pe_conductor_size`, `elecsafety_bonding_resistance`, `elecsafety_ground_electrode`, `elecsafety_gpr` +8 | `elecsafety.md` |
| `kerf_electronics.thermoelectric.tools` | `tec_figure_of_merit`, `tec_operating_point`, `tec_optimal_current`, `tec_delta_t_max` +7 | `thermoelectric.md` |
| `kerf_electronics.antenna.tools` | `antenna_half_wave_dipole`, `antenna_monopole`, `antenna_small_loop`, `antenna_microstrip_patch` +11 | `antenna.md` |
| `kerf_electronics.eereliability.tools` | `eerel_mil217f_parts_count`, `eerel_mil217f_part_stress`, `eerel_board_fit_mtbf`, `eerel_arrhenius_af` +8 | `eereliability.md` |
| `kerf_electronics.magnetics.tools` | `magnetics_core_select_ap`, `magnetics_core_select_kg`, `magnetics_transformer_turns`, `magnetics_inductor_turns` +6 | `magnetics.md` |
| `kerf_electronics.tracecurrent.tools` | `tracecurrent_ipc2152`, `tracecurrent_required_width`, `tracecurrent_resistance`, `tracecurrent_via_capacity` +5 | `tracecurrent.md` |
| `kerf_electronics.photonics.tools` | `photonics_wavelength_to_energy`, `photonics_led_liv`, `photonics_laser_threshold`, `photonics_photodiode_responsivity` +8 | `photonics.md` |
| `kerf_electronics.charger.tools` | `charger_cc_cv_profile`, `charger_power`, `charger_passive_balance`, `charger_active_balance` +5 | `charger.md` |
| `kerf_electronics.audio.tools` | `audio_amp_class_a`, `audio_amp_class_b`, `audio_amp_class_ab`, `audio_amp_class_d` +14 | `audio.md` |
| `kerf_electronics.tools.fab_bundle` | `fab_bundle_export`, `fab_readme_export`, `fab_vendor_presets` | `fab_bundle.md` |
| `kerf_electronics.autoplace.tools` | `auto_decouple`, `thermal_via_array`, `mounting_hole_keepout`, `power_plane_relief` +1 | `autoplace.md` |
| `kerf_electronics.schematic.capture` | — | `capture.md` |
| `kerf_electronics.emc_wizard` | `emc_precompliance_wizard` | `emc_wizard.md` |
| `kerf_electronics.sim_corner` | `run_mc_corner_analysis` | `sim_corner.md` |
| `kerf_electronics.thermal_board` | `board_thermal_map`, `board_thermal_recommend` | `thermal_board.md` |
| `kerf_electronics.pdn_wizard` | `pdn_decap_wizard`, `pdn_characterise_cap` | `pdn_wizard.md` |
| `kerf_electronics.si_eye_wizard` | `si_eye_precompliance_wizard` | `si_eye_wizard.md` |
| `kerf_electronics.pdn.ac_impedance` | `pdn_ac_impedance_sweep`, `pdn_recommend_decaps` | `ac_impedance.md` |
| `kerf_electronics.photonics.fibre_link` | `photonics_fibre_coupling`, `photonics_link_budget`, `photonics_dispersion_penalty` | `fibre_link.md` |
| `kerf_electronics.tools.netlist_drc` | `electronics_netlist_consistency` | `netlist_drc.md` |
| `kerf_electronics.tools.voltage_drop` | `electronics_check_voltage_drop` | `voltage_drop.md` |
| `kerf_electronics.tools.circuit_protection` | `electronics_check_circuit_protection` | `circuit_protection.md` |
| `kerf_electronics.tools.wire_ampacity_derate` | `electronics_compute_derated_ampacity` | `wire_ampacity_derate.md` |
| `kerf_electronics.tools.pcb_trace_current` | `electronics_compute_pcb_trace_current` | `pcb_trace_current.md` |
| `kerf_electronics.decoupling_cap_size` | `electronics_recommend_decoupling_caps` | `decoupling_cap_size.md` |
| `kerf_electronics.diffpair_skew_check` | `electronics_check_diffpair_skew` | `diffpair_skew_check.md` |
| `kerf_electronics.crystal_load_cap` | `electronics_compute_crystal_load_caps` | `crystal_load_cap.md` |
| `kerf_electronics.emi_filter_design` | `electronics_design_emi_filter` | `emi_filter_design.md` |
| `kerf_electronics.dc_dc_ripple` | `electronics_compute_buck_ripple` | `dc_dc_ripple.md` |
| `kerf_electronics.ldo_dropout_check` | `electronics_check_ldo_dropout` | `ldo_dropout_check.md` |
| `kerf_electronics.fet_soa_check` | `electronics_check_fet_soa` | `fet_soa_check.md` |
| `kerf_electronics.inductor_core_saturation` | `electronics_check_inductor_saturation` | `inductor_core_saturation.md` |
| `kerf_electronics.op_amp_offset_drift` | `electronics_compute_op_amp_drift` | `op_amp_offset_drift.md` |
| `kerf_electronics.zener_clamp_design` | `electronics_design_zener_clamp` | `zener_clamp_design.md` |
| `kerf_electronics.tools.fuse_i2t` | `electronics_check_fuse_i2t` | `fuse_i2t.md` |
| `kerf_electronics.tools.pcb_via_current` | `electronics_compute_pcb_via_current` | `pcb_via_current.md` |
| `kerf_electronics.optocoupler_ctr` | `elec_analyze_optocoupler` | `optocoupler_ctr.md` |
| `kerf_electronics.zener_tc_drift` | `elec_compute_zener_drift` | `zener_tc_drift.md` |
| `kerf_electronics.spice.foundry_tools` | `electronics_bsim4_iv`, `electronics_bsim4_corner`, `electronics_generate_netlist`, `electronics_parse_netlist` | `foundry_tools.md` |
| `kerf_electronics.multi_board.multi_board_tools` | `electronics_mb3d_create_workspace`, `electronics_mb3d_add_connector`, `electronics_mb3d_validate_workspace`, `electronics_mb3d_net_map` +1 | `multi_board_tools.md` |
| `kerf_electronics.power.load_flow_tools` | — | `load_flow_tools.md` |

### `kerf-bim`

| Module | Tools | Doc file |
|--------|-------|----------|
| `kerf_bim.tools.bim` | `create_bim`, `read_bim`, `compile_bim_to_ifc`, `read_ifc` | `bim.md` |
| `kerf_bim.tools.xref` | `bim_add_xref`, `bim_check_xref_status`, `bim_refresh_xref`, `bim_compose_federated` +1 | `xref.md` |
| `kerf_bim.tools.phase_filter` | — | `phase_filter.md` |
| `kerf_bim.tools.element_lock` | — | `element_lock.md` |
| `kerf_bim.tools.drawing_list` | `bim_auto_number_sheets`, `bim_validate_drawing_list`, `bim_compute_cross_references`, `bim_generate_drawing_index` +1 | `drawing_list.md` |
| `kerf_bim.tools.bcf` | — | `bcf.md` |
| `kerf_bim.tools.markup` | — | `markup.md` |
| `kerf_bim.tools.cobie` | `bim_get_standard_template`, `bim_apply_property_mapping`, `bim_validate_cobie`, `bim_export_cobie_excel` +1 | `cobie.md` |
| `kerf_bim.tools.bim_categories` | `set_element_category`, `set_element_host`, `unset_element_host`, `move_element` +2 | `bim_categories.md` |
| `kerf_bim.tools.family` | `create_family`, `add_family_param`, `add_family_type`, `instantiate_family` +3 | `family.md` |
| `kerf_bim.tools.schedule` | `create_schedule`, `update_schedule_filter`, `run_schedule` | `schedule.md` |
| `kerf_bim.tools.view` | `create_view`, `set_view_filters`, `add_view_annotation`, `run_view` | `view.md` |
| `kerf_bim.tools.sheet` | `create_sheet`, `add_viewport_to_sheet`, `remove_viewport`, `add_revision_cloud` | `sheet.md` |
| `kerf_bim.tools.stairs` | `create_stair`, `add_stair_flight`, `add_stair_landing`, `validate_stair` | `stairs.md` |
| `kerf_bim.tools.railings` | `create_railing`, `railing_from_stair`, `set_baluster_spacing`, `validate_railing` | `railings.md` |
| `kerf_bim.tools.mep` | `create_mep_route`, `add_mep_segment`, `add_mep_fitting`, `auto_route_mep` +1 | `mep.md` |
| `kerf_bim.tools.curtain_wall` | `create_curtain_wall`, `set_curtain_wall_division`, `set_curtain_wall_panel_type`, `set_curtain_wall_mullion_type` +1 | `curtain_wall.md` |
| `kerf_bim.tools.element_types` | `bulk_set_type_param`, `apply_type_to_instance`, `report_type_usage`, `clone_type` +1 | `element_types.md` |
| `kerf_bim.tools.import_ifc` | `import_ifc` | `import_ifc.md` |
| `kerf_bim.tools.export_ifc` | `export_ifc` | `export_ifc.md` |
| `kerf_bim.tools.family_library` | `list_family_library`, `get_family_from_library`, `list_family_library_categories` | `family_library.md` |
| `kerf_bim.tools.roof_geometry` | — | `roof_geometry.md` |
| `kerf_bim.tools.curtain_wall_geom` | — | `curtain_wall_geom.md` |
| `kerf_bim.tools.drafting` | — | `drafting.md` |
| `kerf_bim.tools.site_geometry` | — | `site_geometry.md` |
| `kerf_bim.tools.space` | `bim_create_space`, `bim_space_schedule` | `space.md` |
| `kerf_bim.tools.grid_framing` | — | `grid_framing.md` |
| `kerf_bim.tools.walls_slabs` | — | `walls_slabs.md` |
| `kerf_bim.tools.facade_ifc` | `bim_parse_facade_ifc`, `bim_facade_thermal_summary` | `facade_ifc.md` |

### `kerf-imports`

| Module | Tools | Doc file |
|--------|-------|----------|
| `kerf_imports.tools.import_3dm` | `import_3dm`, `export_3dm` | `import_3dm.md` |
| `kerf_imports.tools.import_freecad` | `import_freecad_project` | `import_freecad.md` |
| `kerf_imports.tools.import_dxf` | `import_dxf` | `import_dxf.md` |
| `kerf_imports.tools.subd` | `create_subd`, `subdivide_subd`, `extrude_face_subd`, `bevel_edge_subd` +1 | `subd.md` |
| `kerf_imports.tools.mesh` | `mesh_validate`, `mesh_decimate`, `mesh_smooth`, `mesh_repair` +3 | `mesh.md` |
| `kerf_imports.tools.curve_ops` | `curve_project_to_surface`, `curve_intersect`, `curve_blend`, `curve_match` +3 | `curve_ops.md` |
| `kerf_imports.tools.draft` | `create_draft`, `add_draft_entity`, `offset_draft_entity`, `fillet_draft_corner` +2 | `draft.md` |
| `kerf_imports.tools.inspection` | `compare_models` | `inspection.md` |
| `kerf_imports.tools.graph` | `create_graph`, `add_graph_node`, `connect_graph_nodes`, `set_graph_param` +1 | `graph.md` |
| `kerf_imports.tools.feature_draft` | `feature_draft` | `feature_draft.md` |
| `kerf_imports.tools.feature_mirror` | `feature_mirror` | `feature_mirror.md` |
| `kerf_imports.tools.feature_helix` | `feature_helix` | `feature_helix.md` |
| `kerf_imports.tools.feature_multi_transform` | `feature_multi_transform` | `feature_multi_transform.md` |
| `kerf_imports.tools.feature_rib` | `feature_rib` | `feature_rib.md` |
| `kerf_imports.tools.sheet_revisions` | `add_sheet_revision`, `set_active_sheet_revision`, `list_sheet_revisions`, `update_title_block_field` | `sheet_revisions.md` |
| `kerf_imports.tools.import_dwg` | `import_dwg` | `import_dwg.md` |
| `kerf_imports.heal` | `heal_mesh`, `validate_watertight`, `step_ap242_metadata`, `interop_report` | `heal.md` |
| `kerf_imports.jt_reader` | `import_jt` | `jt_reader.md` |
| `kerf_imports.parasolid_reader` | `import_xt` | `parasolid_reader.md` |
| `kerf_imports.dxf_writer` | `export_dxf` | `dxf_writer.md` |
| `kerf_imports.qif_reader` | `import_qif` | `qif_reader.md` |
| `kerf_imports.ibis_reader` | `import_ibis` | `ibis_reader.md` |
| `kerf_imports.eagle_reader` | `import_eagle` | `eagle_reader.md` |
| `kerf_imports.pads_reader` | `import_pads` | `pads_reader.md` |
| `kerf_imports.geda_reader` | `import_geda` | `geda_reader.md` |
| `kerf_imports.allegro_reader` | `import_allegro` | `allegro_reader.md` |

### `kerf-parts`

| Module | Tools | Doc file |
|--------|-------|----------|
| `kerf_parts.tools` | — | `parts.md` |

### `kerf-woodworking`

| Module | Tools | Doc file |
|--------|-------|----------|
| `kerf_woodworking.tools` | `woodworking_mortise_tenon`, `woodworking_dovetail`, `woodworking_finger_joint`, `woodworking_dowel` +9 | `woodworking.md` |
| `kerf_woodworking.woodworking_advanced_tools` | — | `woodworking_advanced_tools.md` |

### `kerf-api`

| Module | Tools | Doc file |
|--------|-------|----------|
| `kerf_api.tools.file_ops` | `list_files`, `read_file`, `write_file`, `edit_file` +5 | `file_ops.md` |
| `kerf_api.tools.object_ops` | `duplicate_object`, `delete_object` | `object_ops.md` |
| `kerf_api.tools.scaffold` | `create_sketch`, `create_feature`, `create_part`, `create_circuit` +3 | `scaffold.md` |
| `kerf_api.tools.revisions` | `list_revisions`, `restore_revision` | `revisions.md` |
| `kerf_api.tools.configurations` | `add_configuration`, `set_active_config` | `configurations.md` |
| `kerf_api.tools.equations` | `read_equations`, `set_equation` | `equations.md` |
| `kerf_api.tools.validation` | `validate_jscad`, `generate_bom` | `validation.md` |
| `kerf_api.tools.project_layers` | `create_layer`, `delete_layer`, `set_project_layer_visibility`, `set_project_layer_color` +2 | `project_layers.md` |
| `kerf_api.tools.material` | `read_material`, `find_material_by_name`, `set_part_material` | `material.md` |
| `kerf_api.tools.brep_interference` | `brep_interference_volume`, `brep_assembly_interference_matrix` | `brep_interference.md` |

### `kerf-lca`

| Module | Tools | Doc file |
|--------|-------|----------|
| `kerf_lca.tools.lca_report` | `lca_report` | `lca_report.md` |
| `kerf_lca.tools.lifecycle_phases` | `lifecycle_phases` | `lifecycle_phases.md` |
| `kerf_lca.tools.multi_impact` | `multi_impact` | `multi_impact.md` |
| `kerf_lca.tools.embodied_carbon` | `lca_lookup_material`, `lca_compute_embodied_carbon` | `embodied_carbon.md` |
