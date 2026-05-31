"""kerf-mold plugin entry point.

Registers:
  - LLM tools: mold_check_moldability, mold_generate_parting_surface,
               mold_draft_angle_per_face  (via @register decorator in tools.py)
  - LLM tool:  mold_cooling_analysis  (Dittus-Boelter cooling circuit)
  - LLM tool:  brep_construct_parting_surface  (Yu-Fan 2003 §6 parting surface)
  - LLM tools: mold_plan_ejector_pins, mold_pin_conflicts
               (Yu-Fan 2003 §10 + SPI/ANSI B151.1 ejector pin layout)
  - LLM tool:  mold_verify_cooling_channels
               (Menges 2001 §6.5 cooling-channel conflict detection)
  - LLM tool:  mold_validate_draft
               (Menges 2001 §3.4 + Beaumont 2007 §4 draft-angle validation)
  - LLM tool:  mold_generate_runner_layout
               (Beaumont 2007 §6.5 + Menges 2001 §6 cold-runner tree design)
  - LLM tool:  mold_optimize_gate_placement
               (Beaumont 2007 §7 + Menges 2001 §6.6 gate location optimisation)
  - LLM tool:  mold_optimize_vent_placement
               (Beaumont 2007 §8.4 + Table 8.4 air-vent location optimisation)
  - LLM tool:  mold_verify_ejector_stroke
               (Beaumont 2007 §9 + Menges 2001 §7.4 ejector stroke verification)
  - LLM tool:  mold_check_flow_length
               (Beaumont 2007 §4 Table 4.2 + Menges 2001 §6.2.1 L/T ratio
                short-shot risk check)
  - LLM tool:  mold_compute_cooling_time_chen_chiang
               (Chen-Chiang 1985 + Menges 2001 §7.3.3 + Beaumont 2007 §10.4
                1-D Fourier cooling-time formula)
  - LLM tool:  mold_check_runner_balance
               (Beaumont 2007 §6.6 + Menges 2001 §6.6.4 naturally balanced
                runner network check via Hagen-Poiseuille path resistance)
  - LLM tool:  mold_check_gate_vestige
               (Beaumont 2007 §7.6 + Table 7.4 + Menges 2001 §6.6 gate-vestige
                estimation and cosmetic-class compliance check)
  - LLM tool:  mold_compute_demold_force
               (Beaumont 2007 §9.3 + Menges 2001 §7.4 + Table 7.6 demolding /
                ejection force per cavity; ejector pin count verification)
  - LLM tool:  mold_check_vent_depth
               (Beaumont 2007 §8.3 Table 8.2 + Menges 2001 §6.4 Table 6.7
                polymer-specific parting-line vent depth verification;
                too_shallow → short shot / burn marks; too_deep → flash)
  - LLM tool:  mold_check_cold_slug_design
               (Beaumont 2007 §6.7 + Menges 2001 §6.5 cold-slug well
                dimension check at runner junctions; diameter = 1.5× runner,
                depth = 2× runner, ±20 % tolerance; prevents flow lines and
                weak welds from cold leading-edge polymer slug)
  - LLM tool:  mold_generate_vent_slot_layout
               (Beaumont 2007 §8.5 + Menges 2001 §6.4 vent slot count and
                width layout; 0.5 % projected-area rule; speed-scaling for
                fast injection; minimum 4 slots + 10 mm steel bridge; heuristic
                rule — actual fill simulation needs Moldflow)
  - LLM tool:  mold_compute_cooling_pressure_drop
               (Beaumont 2007 §11.2 + White "Fluid Mechanics" §6.7
                Darcy-Weisbach multi-segment cooling-channel pressure drop +
                minor-loss K-factors; chiller pump head verification)
  - LLM tool:  mold_optimize_runner_diameter
               (Beaumont 2007 §6.5 + Menges 2001 §6.5 optimal cold-runner
                diameter: D=(W^0.25×√L)/3.7 with material-viscosity
                adjustment; cold-runner waste + fill-pressure proxy)
  - LLM tool:  mold_compute_warpage_index
               (Beaumont 2007 §10 Warpage Analysis + Menges 2001 §8 Post-mold
                shrinkage; heuristic 0–100 warpage-risk index from wall
                uniformity, gate location, polymer grade, post-ejection cooling
                time, and mold temperature; HONEST: screening tool only —
                real warpage prediction requires Moldflow/Moldex3D FEM)
  - LLM tool:  mold_check_melt_flow_ratio
               (Beaumont 2007 §4 + Menges 2001 §6.2 + ASTM D1238 MFR/MVR
                injection-speed envelope to avoid jetting, sink marks, and gate
                freeze-off; heuristic — real speed tuning needs mold trial DOE)
  - LLM tool:  mold_check_sprue_bushing_match
               (Beaumont 2007 §6.4 Sprue Bushing Design + DME standard sprue
                bushing catalogue §3.2: verify sprue bushing seat radius =
                nozzle_r + 0.5–1.0 mm; sprue orifice = nozzle_O + 0.5–1.0 mm;
                taper 1.5–3.0°/side; HONEST: cold-runner standard bushings only
                — hot-runner nozzle seats follow different design rules)
  - LLM tool:  mold_check_turbulent_re
               (Beaumont 2007 §11 + White "Fluid Mechanics" §8.1 + Incropera
                & DeWitt eq. 8.60: verify cooling-channel Reynolds number
                Re > 10 000 for fully-turbulent flow and Dittus-Boelter
                applicability; flag laminar Re<2300 and transitional zones;
                returns Re, flow_regime, velocity_m_per_s,
                recommended_min_flow_rate_L_per_min,
                dittus_boelter_applicable; HONEST: Re classification only —
                does NOT compute Nu/HTC, polymer-side boundary layer, or
                mold-steel thermal resistance)
  - LLM tool:  mold_design_core_pin_cooling
               (Menges 2001 §7.5 + Beaumont 2007 §11.4: baffle/bubbler
                cooling design for tall slender core pins; Reynolds number,
                Dittus-Boelter HTC, lumped-capacitance tip temperature,
                cycle-time estimate; bubbler ≈ 2× baffle HTC multiplier)
  - LLM tool:  mold_compute_ejector_pin_push
               (SPI/ANSI B151.1 + Roark's 9e §15.2: Euler critical buckling
                load F_cr = π²·E·I/(K·L)² for ejector pins; E=200 GPa for all
                tool-steel grades (M2/H13/S7/D2); I=π·d⁴/64 solid round;
                K end-condition coefficient 1.0 pinned-pinned / 0.5 fixed-fixed
                / 2.0 cantilever; DCR = required_force / F_cr; recommends
                smallest SPI-standard diameter with F_cr ≥ 1.1×required force;
                HONEST: Euler non-conservative for K·L/d < 30 — use Johnson
                formula in short-column regime; bushing friction and pin
                eccentricity NOT modelled)
"""
from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""
    # Register mold check / parting / draft tools explicitly via ctx
    from kerf_mold.tools import (
        _CHECK_SPEC, run_mold_check_moldability,
        _PARTING_SPEC, run_mold_generate_parting_surface,
        _DRAFT_SPEC, run_mold_draft_angle_per_face,
        _CONSTRUCT_PARTING_SPEC, run_brep_construct_parting_surface,
    )
    ctx.tools.register("mold_check_moldability",
                       _CHECK_SPEC, run_mold_check_moldability)
    ctx.tools.register("mold_generate_parting_surface",
                       _PARTING_SPEC, run_mold_generate_parting_surface)
    ctx.tools.register("mold_draft_angle_per_face",
                       _DRAFT_SPEC, run_mold_draft_angle_per_face)
    ctx.tools.register("brep_construct_parting_surface",
                       _CONSTRUCT_PARTING_SPEC, run_brep_construct_parting_surface)

    # Register cooling analysis tool
    from kerf_mold.cooling_tool import mold_cooling_analysis_spec, run_mold_cooling_analysis
    ctx.tools.register(
        "mold_cooling_analysis",
        mold_cooling_analysis_spec,
        run_mold_cooling_analysis,
    )

    # Register ejector pin layout tools
    from kerf_mold.ejector_pin_tool import (
        _PLAN_SPEC, run_mold_plan_ejector_pins,
        _CONFLICT_SPEC, run_mold_pin_conflicts,
    )
    ctx.tools.register(
        "mold_plan_ejector_pins",
        _PLAN_SPEC,
        run_mold_plan_ejector_pins,
    )
    ctx.tools.register(
        "mold_pin_conflicts",
        _CONFLICT_SPEC,
        run_mold_pin_conflicts,
    )
    # Register cooling-channel conflict verification tool
    from kerf_mold.cooling_channel_conflict_tool import (
        _VERIFY_SPEC, run_mold_verify_cooling_channels,
    )
    ctx.tools.register(
        "mold_verify_cooling_channels",
        _VERIFY_SPEC,
        run_mold_verify_cooling_channels,
    )

    # Register draft-angle validation tool
    from kerf_mold.draft_validation_tool import (
        _VALIDATE_DRAFT_SPEC, run_mold_validate_draft,
    )
    ctx.tools.register(
        "mold_validate_draft",
        _VALIDATE_DRAFT_SPEC,
        run_mold_validate_draft,
    )
    # Register runner-layout tool (Beaumont 2007 §6.5 + Menges 2001 §6)
    from kerf_mold.runner_layout_tool import (
        mold_runner_layout_spec, run_mold_generate_runner_layout,
    )
    ctx.tools.register(
        "mold_generate_runner_layout",
        mold_runner_layout_spec,
        run_mold_generate_runner_layout,
    )
    # Register gate placement optimisation tool (Beaumont 2007 §7 + Menges 2001 §6.6)
    from kerf_mold.gate_placement_tool import (
        mold_gate_placement_spec, run_mold_optimize_gate_placement,
    )
    ctx.tools.register(
        "mold_optimize_gate_placement",
        mold_gate_placement_spec,
        run_mold_optimize_gate_placement,
    )
    # Register vent placement optimisation tool (Beaumont 2007 §8.4 + Table 8.4)
    from kerf_mold.vent_placement_tool import (
        mold_vent_placement_spec, run_mold_optimize_vent_placement,
    )
    ctx.tools.register(
        "mold_optimize_vent_placement",
        mold_vent_placement_spec,
        run_mold_optimize_vent_placement,
    )
    # Register ejector stroke verification tool (Beaumont 2007 §9 + Menges 2001 §7.4)
    from kerf_mold.ejector_stroke_verify_tool import (
        mold_verify_ejector_stroke_spec, run_mold_verify_ejector_stroke,
    )
    ctx.tools.register(
        "mold_verify_ejector_stroke",
        mold_verify_ejector_stroke_spec,
        run_mold_verify_ejector_stroke,
    )
    # Register flow-length / wall-thickness (L/T) short-shot risk tool
    # (Beaumont 2007 §4 Table 4.2 + Menges 2001 §6.2.1)
    from kerf_mold.flow_length_check_tool import (
        mold_check_flow_length_spec, run_mold_check_flow_length,
    )
    ctx.tools.register(
        "mold_check_flow_length",
        mold_check_flow_length_spec,
        run_mold_check_flow_length,
    )

    # Register Chen-Chiang cooling-time tool
    # (Chen-Chiang 1985 + Menges 2001 §7.3.3 + Beaumont 2007 §10.4)
    from kerf_mold.cooling_time_chen_chiang_tool import (
        mold_cooling_time_chen_chiang_spec,
        run_mold_compute_cooling_time_chen_chiang,
    )
    ctx.tools.register(
        "mold_compute_cooling_time_chen_chiang",
        mold_cooling_time_chen_chiang_spec,
        run_mold_compute_cooling_time_chen_chiang,
    )

    # Register runner balance check tool
    # (Beaumont 2007 §6.6 + Menges 2001 §6.6.4)
    from kerf_mold.runner_balance_check_tool import (
        mold_runner_balance_check_spec,
        run_mold_check_runner_balance,
    )
    ctx.tools.register(
        "mold_check_runner_balance",
        mold_runner_balance_check_spec,
        run_mold_check_runner_balance,
    )
    # Register gate vestige check tool
    # (Beaumont 2007 §7.6 + Table 7.4 + Menges 2001 §6.6)
    from kerf_mold.gate_vestige_check_tool import (
        mold_check_gate_vestige_spec,
        run_mold_check_gate_vestige,
    )
    ctx.tools.register(
        "mold_check_gate_vestige",
        mold_check_gate_vestige_spec,
        run_mold_check_gate_vestige,
    )
    # Register demolding / ejection force tool
    # (Beaumont 2007 §9.3 + Menges 2001 §7.4 + Table 7.6)
    from kerf_mold.demold_force_check_tool import (
        mold_compute_demold_force_spec,
        run_mold_compute_demold_force,
    )
    ctx.tools.register(
        "mold_compute_demold_force",
        mold_compute_demold_force_spec,
        run_mold_compute_demold_force,
    )

    # Register vent depth check tool
    # (Beaumont 2007 §8.3 Table 8.2 + Menges 2001 §6.4 Table 6.7)
    from kerf_mold.vent_depth_check_tool import (
        mold_check_vent_depth_spec,
        run_mold_check_vent_depth,
    )
    ctx.tools.register(
        "mold_check_vent_depth",
        mold_check_vent_depth_spec,
        run_mold_check_vent_depth,
    )

    # Register cold-slug well check tool
    # (Beaumont 2007 §6.7 + Menges 2001 §6.5)
    from kerf_mold.cold_slug_check_tool import (
        mold_check_cold_slug_design_spec,
        run_mold_check_cold_slug_design,
    )
    ctx.tools.register(
        "mold_check_cold_slug_design",
        mold_check_cold_slug_design_spec,
        run_mold_check_cold_slug_design,
    )

    # Register vent slot layout tool
    # (Beaumont 2007 §8.5 + Menges 2001 §6.4)
    from kerf_mold.vent_slot_layout_tool import (
        mold_generate_vent_slot_layout_spec,
        run_mold_generate_vent_slot_layout,
    )
    ctx.tools.register(
        "mold_generate_vent_slot_layout",
        mold_generate_vent_slot_layout_spec,
        run_mold_generate_vent_slot_layout,
    )

    # Register cooling pressure-drop tool
    # (Beaumont 2007 §11.2 + White "Fluid Mechanics" §6.7)
    from kerf_mold.cooling_pressure_drop_tool import (
        mold_cooling_pressure_drop_spec,
        run_mold_compute_cooling_pressure_drop,
    )
    ctx.tools.register(
        "mold_compute_cooling_pressure_drop",
        mold_cooling_pressure_drop_spec,
        run_mold_compute_cooling_pressure_drop,
    )

    # Register runner-diameter optimisation tool
    # (Beaumont 2007 §6.5 + Menges 2001 §6.5)
    from kerf_mold.runner_diameter_optimize_tool import (
        mold_optimize_runner_diameter_spec,
        run_mold_optimize_runner_diameter,
    )
    ctx.tools.register(
        "mold_optimize_runner_diameter",
        mold_optimize_runner_diameter_spec,
        run_mold_optimize_runner_diameter,
    )

    # Register warpage index tool
    # (Beaumont 2007 §10 + Menges 2001 §8)
    from kerf_mold.warpage_index_tool import (
        mold_compute_warpage_index_spec,
        run_mold_compute_warpage_index,
    )
    ctx.tools.register(
        "mold_compute_warpage_index",
        mold_compute_warpage_index_spec,
        run_mold_compute_warpage_index,
    )
    # Register melt-flow-ratio injection-speed envelope tool
    # (Beaumont 2007 §4 + Menges 2001 §6.2 + ASTM D1238)
    from kerf_mold.melt_flow_ratio_check_tool import (
        mold_check_melt_flow_ratio_spec,
        run_mold_check_melt_flow_ratio,
    )
    ctx.tools.register(
        "mold_check_melt_flow_ratio",
        mold_check_melt_flow_ratio_spec,
        run_mold_check_melt_flow_ratio,
    )

    # Register sprue bushing match tool
    # (Beaumont 2007 §6.4 + DME standard sprue bushing catalogue §3.2)
    from kerf_mold.sprue_bushing_match_tool import (
        mold_check_sprue_bushing_match_spec,
        run_mold_check_sprue_bushing_match,
    )
    ctx.tools.register(
        "mold_check_sprue_bushing_match",
        mold_check_sprue_bushing_match_spec,
        run_mold_check_sprue_bushing_match,
    )

    # Register cooling-channel Reynolds-number turbulence check tool
    # (Beaumont 2007 §11 + White "Fluid Mechanics" §8.1 + Incropera eq. 8.60)
    from kerf_mold.cooling_turbulent_re_check_tool import (
        mold_check_turbulent_re_spec,
        run_mold_check_turbulent_re,
    )
    ctx.tools.register(
        "mold_check_turbulent_re",
        mold_check_turbulent_re_spec,
        run_mold_check_turbulent_re,
    )

    # Register ejector pin push-force / buckling check tool
    # (SPI/ANSI B151.1 + Roark's 9e §15.2 Euler critical load)
    from kerf_mold.ejector_pin_push_tool import (
        mold_compute_ejector_pin_push_spec,
        run_mold_compute_ejector_pin_push,
    )
    ctx.tools.register(
        "mold_compute_ejector_pin_push",
        mold_compute_ejector_pin_push_spec,
        run_mold_compute_ejector_pin_push,
    )

    # Register core-pin baffle/bubbler cooling design tool
    # (Menges 2001 §7.5 + Beaumont 2007 §11.4)
    from kerf_mold.core_pin_cooling_tool import (
        mold_design_core_pin_cooling_spec,
        run_mold_design_core_pin_cooling,
    )
    ctx.tools.register(
        "mold_design_core_pin_cooling",
        mold_design_core_pin_cooling_spec,
        run_mold_design_core_pin_cooling,
    )

    provides = [
        "mold.moldability",
        "mold.parting_surface",
        "mold.parting_surface_construction",
        "mold.draft_angle",
        "mold.cooling_analysis",
        "mold.ejector_pin_layout",
        "mold.cooling_channel_conflict",
        "mold.draft_validation",
        "mold.runner_layout",
        "mold.gate_placement",
        "mold.vent_placement",
        "mold.ejector_stroke_verify",
        "mold.flow_length_check",
        "mold.cooling_time_chen_chiang",
        "mold.runner_balance_check",
        "mold.gate_vestige_check",
        "mold.demold_force_check",
        "mold.vent_depth_check",
        "mold.cold_slug_check",
        "mold.vent_slot_layout",
        "mold.cooling_pressure_drop",
        "mold.runner_diameter_optimize",
        "mold.warpage_index",
        "mold.melt_flow_ratio_check",
        "mold.sprue_bushing_match",
        "mold.cooling_turbulent_re_check",
        "mold.ejector_pin_push",
        "mold.core_pin_cooling",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="mold",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "mold",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
