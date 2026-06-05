"""
kerf-electronics plugin registration.

Wires RF, SPICE, autoroute and copper-pour routes + LLM tools into a Kerf plugin.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""

    # ── HTTP routes ──────────────────────────────────────────────────────
    from kerf_electronics.routes_rf import router as rf_router
    from kerf_electronics.routes_spice import router as spice_router
    from kerf_electronics.routes_autoroute import router as autoroute_router
    from kerf_electronics.routes_pour import router as pour_router

    app.include_router(rf_router, tags=["electronics"])
    app.include_router(spice_router, tags=["electronics"])
    app.include_router(autoroute_router, tags=["electronics"])
    app.include_router(pour_router, tags=["electronics"])

    # ── LLM tools ────────────────────────────────────────────────────────
    provides = []
    _register_tools(ctx, provides)

    # Probe which optional deps are available
    try:
        import skrf  # noqa: F401
        provides.append("electronics.rf")
    except ImportError:
        logger.info("kerf-electronics: scikit-rf not available; RF capability disabled")

    # ngspice is a system binary — always declare the route, gate at runtime
    provides.append("electronics.spice")

    # FreeRouting is auto-downloaded — always declare
    provides.append("electronics.autoroute")

    # Copper pour uses shapely (optional)
    provides.append("electronics.pour")

    # Fab output (Gerber, Excellon, P&P, BOM, IPC-2581) — pure Python, always available
    provides.append("electronics.fab")

    # IPC-D-356A netlist export + connectivity report — pure Python, always available
    provides.append("electronics.ipc_netlist")

    # Testpoint auto-placement + bed-of-nails fixture report — pure Python, always available
    provides.append("electronics.testpoint")

    # 3D STEP board export — requires pythonOCC (optional)
    try:
        from kerf_electronics.fab.board_step import _OCC_AVAILABLE as _step_occ
        if _step_occ:
            provides.append("electronics.board_step")
        else:
            logger.info(
                "kerf-electronics: pythonOCC not available; "
                "3D board STEP export disabled (export_board_step tool still registered "
                "and returns a friendly error when called without OCC)"
            )
    except ImportError:
        logger.info("kerf-electronics: board_step module unavailable")

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "electronics",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="electronics",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all electronics LLM tools into ctx.tools."""
    tool_modules = [
        "kerf_electronics.tools.kicad_bridge_tools",
        "kerf_electronics.tools.erc",
        "kerf_electronics.tools.buses",
        "kerf_electronics.tools.net_classes",
        "kerf_electronics.tools.length_tuning",
        "kerf_electronics.tools.via_stitching",
        "kerf_electronics.tools.shove_router",
        "kerf_electronics.tools.pad_overrides",
        "kerf_electronics.tools.hier_schematic",
        "kerf_electronics.tools.rf",
        "kerf_electronics.tools.autoroute",
        "kerf_electronics.tools.pour",
        "kerf_electronics.tools.pcb_drc",
        "kerf_electronics.tools.drc_presets",
        "kerf_electronics.tools.pcb_layer_tools",
        "kerf_electronics.tools.routing",
        "kerf_electronics.tools.sim",
        "kerf_electronics.tools.fab",
        "kerf_electronics.tools.diffpair",
        "kerf_electronics.tools.panelize",
        "kerf_electronics.tools.ipc_netlist",
        "kerf_electronics.tools.spice_lib",
        "kerf_electronics.tools.idf_export",
        "kerf_electronics.tools.lib_mgmt",
        "kerf_electronics.tools.netlist_export",
        "kerf_electronics.tools.testpoint",
        "kerf_electronics.tools.variants",
        "kerf_electronics.tools.odbpp_export",
        "kerf_electronics.tools.si",
        "kerf_electronics.tools.pdn",
        "kerf_electronics.tools.bom_cost",
        "kerf_electronics.tools.flex_stackup",
        "kerf_electronics.tools.eye",
        "kerf_electronics.tools.thermal",
        "kerf_electronics.emc.tools",
        "kerf_electronics.battery.tools",
        "kerf_electronics.rfmatch.tools",
        "kerf_electronics.afilter.tools",
        "kerf_electronics.leddriver.tools",
        "kerf_electronics.motordrive.tools",
        "kerf_electronics.powerconv.tools",
        "kerf_electronics.dsp.tools",
        "kerf_electronics.oscillator.tools",
        "kerf_electronics.stackup.tools",
        "kerf_electronics.protection.tools",
        "kerf_electronics.sensorcond.tools",
        "kerf_electronics.gatedrive.tools",
        "kerf_electronics.linkbudget.tools",
        "kerf_electronics.dataconv.tools",
        "kerf_electronics.elecsafety.tools",
        "kerf_electronics.thermoelectric.tools",
        "kerf_electronics.antenna.tools",
        "kerf_electronics.eereliability.tools",
        "kerf_electronics.magnetics.tools",
        "kerf_electronics.tracecurrent.tools",
        "kerf_electronics.photonics.tools",
        "kerf_electronics.charger.tools",
        "kerf_electronics.audio.tools",
        "kerf_electronics.tools.fab_bundle",
        "kerf_electronics.autoplace.tools",
        "kerf_electronics.schematic.capture",
        "kerf_electronics.emc_wizard",
        "kerf_electronics.sim_corner",
        "kerf_electronics.thermal_board",
        "kerf_electronics.pdn_wizard",
        "kerf_electronics.si_eye_wizard",
        # PDN AC impedance sweep + decap optimiser (orphaned from pdn/analyzer.py coverage)
        "kerf_electronics.pdn.ac_impedance",
        # Fibre-link LLM tools (fibre coupling, full link budget, dispersion penalty)
        "kerf_electronics.photonics.fibre_link",
        # Netlist-vs-layout consistency DRC (IPC-7351B §4.1-4.2)
        "kerf_electronics.tools.netlist_drc",
        # NEC 2023 Article 210.19(A) voltage-drop check for AC/DC conductor runs
        "kerf_electronics.tools.voltage_drop",
        # NEC 2023 Article 240.4 + Table 310.16 + 215 circuit-protection check
        "kerf_electronics.tools.circuit_protection",
        # NEC 2023 Article 310 wire ampacity derating — ambient + bundling
        "kerf_electronics.tools.wire_ampacity_derate",
        # IPC-2221B simplified PCB trace maximum current (trace_width, copper_oz, dT, location)
        "kerf_electronics.tools.pcb_trace_current",
        # Decoupling cap sizing: Z_target + bulk/bypass recommendation (Ott §13.3 + HJ §8.3)
        "kerf_electronics.decoupling_cap_size",
        # Differential pair intra-pair skew check (Johnson §12.4 + IPC-2141A §6)
        "kerf_electronics.diffpair_skew_check",
        # Pierce crystal oscillator external load capacitor calculator
        # (NXP AN-2867 §3 + AVR ATmega §28.5: CL=(C1·C2)/(C1+C2)+C_stray)
        "kerf_electronics.crystal_load_cap",
        # Passive LC / RC power-line EMI filter design — Ott §15.3 + CISPR 22
        # electronics_design_emi_filter: corner freq, L, C, attenuation
        "kerf_electronics.emi_filter_design",
        # Buck DC-DC converter CCM output voltage ripple — Erickson 3e §2.4 + Sandler §3
        # electronics_compute_buck_ripple: D, ΔiL, ΔV_cap, ΔV_ESR, total ΔV_out
        "kerf_electronics.dc_dc_ripple",
        # LDO dropout + thermal compliance check — TI Power Ref §3 + Sandler §4
        # electronics_check_ldo_dropout: headroom, dropout_compliant, P_diss, T_j, thermal_compliant
        "kerf_electronics.ldo_dropout_check",
        # MOSFET Safe Operating Area (SOA) check — IRF Hexfet Designer's Manual §5 + IPC-9701
        # electronics_check_fet_soa: within_soa, P_diss, T_J, soa_violation_modes, headroom_pct
        "kerf_electronics.fet_soa_check",
        # Inductor core saturation check — Erickson §15 + McLyman §10
        # electronics_check_inductor_saturation: B_peak_mT, B_sat_mT, saturation_margin_pct,
        #   saturated, recommended_max_I_dc_A; ferrite B_sat temp derating (−15%@100°C, −25%@125°C)
        "kerf_electronics.inductor_core_saturation",
        # Op-amp offset voltage + temperature drift — TI SLOA069 §3 + Analog Devices AN-580 §1
        # electronics_compute_op_amp_drift: Vos(T)=Vos_typ+TC_Vos×(T-Tref); input-/output-referred
        #   worst-case offset; error_pct_of_FS; recommended class (standard|precision|zero-drift|chopper)
        "kerf_electronics.op_amp_offset_drift",
        # Zener diode voltage clamp + series resistor design — H&H §2.2.4 + Vishay AN-2014-3
        # electronics_design_zener_clamp: R_series, R_series_power, I_zener_max, P_zener_max,
        #   recommended_zener_package (0.4W|0.5W|1W|3W|5W), recommended_R_E12_ohm, regulation_pct
        "kerf_electronics.zener_clamp_design",
        # Fuse I²t (melting energy) verification — IEC 60269 + Cooper Bussmann SPD §2–§4
        # electronics_check_fuse_i2t: applied_I2t, ratio_pct, clears_safely,
        #   breaking_capacity_adequate, recommended_fuse_class
        "kerf_electronics.tools.fuse_i2t",
        # IPC-2152 §6.3 + IPC-2221A §6 PCB via current-carrying capacity
        # electronics_compute_pcb_via_current: drill_diameter_mm, plating_thickness_um,
        #   via_length_mm, temp_rise_C, target_current_A → max_current_A,
        #   via_cross_section_um2, equivalent_trace_width_mm, N_vias_recommended
        "kerf_electronics.tools.pcb_via_current",
        # Optocoupler isolation circuit analysis (Vishay AN-38 + Avago AN-5078 + IEC 60747-5-5)
        # elec_analyze_optocoupler: IF_mA, CTR_min/typ/max, R_pullup, Vcc → IC min/typ/max,
        #   IC_sat, saturated_min_case, Vout_low, Vout_high, t_rise/fall, headroom_factor
        "kerf_electronics.optocoupler_ctr",
        # Zener temperature-coefficient drift model — Sze §4.5 + Vishay AN-2014-3 §2.4 + ON AN-961 §3
        # elec_compute_zener_drift: Vz(T)=Vz_nom+TC×(T−T_test); rZ≈0.01×Vz/Iz_test;
        #   zero-TC crossing near 5.6V (avalanche vs tunneling); drift>5%→recommend Vref IC
        "kerf_electronics.zener_tc_drift",
        # Wave 9C: SPICE foundry sign-off (BSIM4 + corner MC + multi-syntax netlist)
        # electronics_bsim4_iv: BSIM4.8 I-V point (Id, gm, Cgs, Vth)
        # electronics_bsim4_corner: PVT / Monte-Carlo corner sweep (TT/SS/FF/SF/FS + temp + Pelgrom)
        # electronics_generate_netlist: schematic → Spectre / ngspice / HSPICE netlist
        # electronics_parse_netlist: parse SPICE netlist → structured schematic graph
        "kerf_electronics.spice.foundry_tools",
        # Wave 10C: Altium MB3D multi-board workspace
        # electronics_mb3d_create_workspace: create workspace + placed boards
        # electronics_mb3d_add_connector: declare J1↔J2 mating connector pair
        # electronics_mb3d_validate_workspace: pin-count + overlap validation
        # electronics_mb3d_net_map: cross-board net map + floating pin + Z0 mismatch
        # electronics_mb3d_export_step: full STEP AP242 multi-board assembly export
        "kerf_electronics.multi_board.multi_board_tools",
        # Wave 11B: AC load-flow (Newton-Raphson)
        # power_build_y_bus: build bus admittance matrix Y_bus (G+jB)
        # power_ac_load_flow: Newton-Raphson AC load flow (Stevenson 1982 §9)
        "kerf_electronics.power.load_flow_tools",
        # Wave 12D: KiCad v10 diff-pair length tuner
        # electronics_tune_trace_to_length: serpentine meander insertion (rectangular/arc/45°)
        # electronics_tune_diff_pair_lengths: symmetric diff-pair matching (Hall & Heck 2009 §3.6)
        # Reference: IPC-2141A §6 + Wittwer 2012 DesignCon
        "kerf_electronics.routing.diffpair_tuner_tools",
        # IBIS 5.x channel simulator — si_ibis_parse + si_ibis_channel_response
        # Bergeron bounce-diagram model; PRBS-7 eye envelope (Hall & Heck 2009 §4)
        "kerf_electronics.tools.si_ibis",
        # 3D PCB clearance DRC + STEP component body import
        # pcb_3d_clearance_check: AABB body-to-body clearance (Altium §7.4 + IPC-7351B §4.5)
        # pcb_step_import_body: STEP AP214/AP242 component body bbox extraction
        "kerf_electronics.pcb_3d_clearance",
        # IDF 3.0 MCAD bridge — import side + round-trip validation
        # import_idf_board: parse .emn → board outline + holes + placements
        # validate_idf_roundtrip: export→reimport consistency check (Altium MCAD CoDesigner §6)
        "kerf_electronics.idf_roundtrip",
    ]

    for module_path in tool_modules:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            if hasattr(mod, "TOOLS"):
                for name, spec, handler in mod.TOOLS:
                    ctx.tools.register(name, spec, handler)
        except Exception as exc:
            logger.warning("kerf-electronics: failed to load %s: %s", module_path, exc)
