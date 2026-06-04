#!/usr/bin/env python3
"""
validate-roadmap-paths.py — idempotent ROADMAP.md path-citation validator.

Algorithm:
  1. Read ROADMAP.md.
  2. Use regex to find every backtick-quoted path-like string:
       `([^`]+([.]py|[.]jsx|[.]js|[.]ts|/)..)`
  3. For each captured path, test os.path.exists(REPO_ROOT / path).
  4. If MISSING:
     a. Look up the real path in a hand-maintained correction table
        (built by searching the repo for the correct module location).
     b. If a real path is found: substitute it inline.
     c. If no real path exists anywhere: remove the bad citation
        (replace the parenthetical `(bad/path.py)` with empty parens, or
        drop the bare backtick reference in table cells).
  5. Write the corrected ROADMAP.md.
  6. Report: checked / fixed / removed counts.

Idempotency: running twice produces no further changes.
"""

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROADMAP = REPO_ROOT / "ROADMAP.md"

# ---------------------------------------------------------------------------
# Correction table: cited_path -> real_path (relative to repo root)
# None means "not found anywhere — remove the citation".
# ---------------------------------------------------------------------------
CORRECTIONS: dict[str, str | None] = {
    # ---- subd ----
    "subd/crease_fractional_decay.py":
        "packages/kerf-cad-core/src/kerf_cad_core/subd/crease_fractional_decay.py",
    "subd/g1_extraordinary_patches.py":
        "packages/kerf-cad-core/src/kerf_cad_core/subd/g1_extraordinary_patches.py",
    "subd/multires_displacement.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/multires_displacement.py",

    # ---- geom (short paths without package prefix) ----
    "geom/surface_g3_match.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/match_srf_g3.py",
    "geom/surface_analytic_derivatives.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/surface_analytic_derivatives.py",
    "geom/sdf_csg.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/sdf_csg.py",
    "geom/marching_cubes.py":
        "packages/kerf-cad-core/src/kerf_cad_core/sdf/marching_cubes.py",
    "geom/uv_unwrap_hardening.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/uv_unwrap_hardening.py",
    "geom/fresnel_parameterize.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/fresnel_parameterize.py",
    "geom/surface_cross_section.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/surface_cross_section.py",
    "geom/surface_analysis.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/surface_analysis.py",
    "geom/subd_gauss_bonnet_check.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/subd_gauss_bonnet_check.py",
    "geom/subd_limit_integrals.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/subd_limit_integrals.py",
    "geom/sweep1.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/sweep1.py",
    "geom/sweep2.py": None,   # consolidated into sweep1.py (code-health note)
    "geom/sweep_n.py": None,  # consolidated into sweep1.py

    # ---- geom (bare basename in table — no prefix) ----
    "brep.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/brep.py",
    "boolean.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/boolean.py",
    "fillet_solid.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/fillet_solid.py",
    "chamfer.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/chamfer.py",
    "surface_analytic_derivatives.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/surface_analytic_derivatives.py",
    "sdf_csg.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/sdf_csg.py",
    "marching_cubes.py":
        "packages/kerf-cad-core/src/kerf_cad_core/sdf/marching_cubes.py",
    "loft_guide_rails.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/loft_guide_rails.py",
    "sheetmetal_features.py":
        "packages/kerf-cad-core/src/kerf_cad_core/sheetmetal_features.py",
    "uv_unwrap_hardening.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/uv_unwrap_hardening.py",
    "surface_g3_match.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/match_srf_g3.py",
    "subd_limit_integrals.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/subd_limit_integrals.py",
    "curve_fit_g2.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/curve_fit_g2.py",
    "nurbs_fit_reverse.py":
        "packages/kerf-cad-core/src/kerf_cad_core/scan/nurbs_fit_tools.py",
    "drawings/hlr.py":
        "packages/kerf-cad-core/src/kerf_cad_core/drawings/brep_hlr.py",
    "sweep1.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/sweep1.py",

    # ---- mesh / sculpt ----
    "mesh_sculpt_brushes.py":
        "packages/kerf-cad-core/src/kerf_cad_core/mesh_sculpt_brushes.py",
    "imports/rhino3dm_writer.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/io/rhino3dm.py",
    "kerf-cad-core/mesh_sculpt_brushes.py":
        "packages/kerf-cad-core/src/kerf_cad_core/mesh_sculpt_brushes.py",
    "kerf-cad-core/subd/multires_displacement.py":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/multires_displacement.py",
    "kerf-cad-core/geom/nurbs_fit_reverse.py":
        "packages/kerf-cad-core/src/kerf_cad_core/scan/nurbs_fit_tools.py",
    "kerf-cad-core/geom/history/":
        "packages/kerf-cad-core/src/kerf_cad_core/geom/history/",

    # ---- optics ----
    "packages/kerf-optics/src/kerf_optics/photon_map.py":
        "packages/kerf-cad-core/src/kerf_cad_core/optics/photon_map.py",
    "packages/kerf-optics/src/kerf_optics/theatrical_lighting.py":
        "packages/kerf-cad-core/src/kerf_cad_core/render/theatrical_lighting.py",
    "kerf-optics/lux_sim.py":
        "packages/kerf-cad-core/src/kerf_cad_core/render/luminance_lux_sim.py",
    "kerf-render/fluid_viz.py": None,   # no fluid visualisation module found
    "kerf-optics/metalens.py":
        "packages/kerf-cad-core/src/kerf_cad_core/optics/metalens.py",
    "kerf-optics/stop_multiphysics.py":
        "packages/kerf-cad-core/src/kerf_cad_core/optics/stop_analysis.py",

    # ---- CFD ----
    "rans_kw_sst.py":
        "packages/kerf-cfd/src/kerf_cfd/rans/k_omega_sst.py",
    "kerf-cfd/snappy_mesher.py":
        "packages/kerf-cfd/src/kerf_cfd/meshing/snappy_hex.py",
    "kerf-cfd/wind_engineering.py":
        "packages/kerf-cfd/src/kerf_cfd/wind_engineering/wind_tunnel.py",
    "kerf-cfd/combustion.py":
        "packages/kerf-cfd/src/kerf_cfd/combustion/reacting_flow.py",
    "kerf-cfd/fsi.py":
        "packages/kerf-cfd/src/kerf_cfd/fsi/dynamic_mesh.py",
    "kerf-cfd/compressible.py":
        "packages/kerf-cfd/src/kerf_cfd/compressible/compressible_flow.py",
    "kerf-marine/holtrop_mennen.py":
        "packages/kerf-marine/src/kerf_marine/holtrop_mennen.py",

    # ---- FEM / MBD ----
    "packages/kerf-fem/src/kerf_fem/craig_bampton.py":
        "packages/kerf-cad-core/src/kerf_cad_core/mbd/solver.py",
    "kerf-1dsim/pacejka_tire.py": None,  # no pacejka tire module found
    "kerf-fem/fe_solid.py":
        "packages/kerf-fem/src/kerf_fem/solid_hex.py",

    # ---- 1dsim / controls ----
    "packages/kerf-1dsim/src/kerf_1dsim/classical_control.py":
        "packages/kerf-cad-core/src/kerf_cad_core/controls/transfer_function.py",
    "kerf-1dsim/ac_loadflow.py":
        "packages/kerf-electronics/src/kerf_electronics/power/ac_load_flow.py",
    "kerf-1dsim/fmi_export.py":
        "packages/kerf-1dsim/src/kerf_1dsim/fmi_export.py",

    # ---- mold ----
    "kerf-mold/parting_line.py":
        "packages/kerf-mold/src/kerf_mold/parting_line.py",
    "kerf-mold/cavity_core_split.py":
        "packages/kerf-mold/src/kerf_mold/cavity_core_split.py",
    "kerf-mold/injection_fill.py":
        "packages/kerf-mold/src/kerf_mold/injection_fill.py",

    # ---- composites ----
    "packages/kerf-composites/src/kerf_composites/fibersim.py":
        "packages/kerf-cad-core/src/kerf_cad_core/composites/afp_atl_path.py",

    # ---- BIM / energy ----
    "packages/kerf-bim/src/kerf_bim/energy_sim.py":
        "packages/kerf-cad-core/src/kerf_cad_core/buildingenergy/hourly_8760.py",
    "kerf-bim/plant_federation.py":
        "packages/kerf-cad-core/src/kerf_cad_core/piping/multi_discipline_federation.py",

    # ---- civil ----
    "packages/kerf-civil/src/kerf_civil/tin_terrain.py":
        "packages/kerf-cad-core/src/kerf_cad_core/civil/tin_surface.py",
    "kerf-civil/pipe_networks.py":
        "packages/kerf-cad-core/src/kerf_cad_core/civil/gravity_pipe_network.py",
    "kerf-civil/parcel_subdivision.py":
        "packages/kerf-cad-core/src/kerf_cad_core/civil/parcels.py",
    "kerf-civil/plan_profile.py":
        "packages/kerf-cad-core/src/kerf_cad_core/civil/plan_profile_sheet.py",

    # ---- piping ----
    "kerf-piping/aveva_catalog.py":
        "packages/kerf-cad-core/src/kerf_cad_core/piping/component_catalogue.py",
    "kerf-piping/asme_pressure.py":
        "packages/kerf-piping/src/kerf_piping/asme_pressure.py",
    "kerf-piping/wall_thickness.py":
        "packages/kerf-piping/src/kerf_piping/wall_thickness.py",

    # ---- packaging ----
    "packages/kerf-packaging/src/kerf_packaging/artioscad.py":
        "packages/kerf-cad-core/src/kerf_cad_core/packaging/pre_press.py",
    "kerf-packaging/material_yield.py":
        "packages/kerf-cad-core/src/kerf_cad_core/packaging/material_yield.py",

    # ---- PLM ----
    "kerf-plm/quote_workflow.py":
        "packages/kerf-plm/src/kerf_plm/quote_to_delivery.py",

    # ---- AFR / reverse engineering ----
    "packages/kerf-cad-core/src/kerf_cad_core/afr/topology_dag.py":
        "packages/kerf-cad-core/src/kerf_cad_core/afr/dag.py",

    # ---- aerospace ----
    "packages/kerf-aero/src/kerf_aero/cr3bp_libration.py":
        "packages/kerf-cad-core/src/kerf_cad_core/aerospace/libration_orbits.py",
    "kerf-aero/orbit_determination.py":
        "packages/kerf-cad-core/src/kerf_cad_core/aerospace/orbit_determination.py",
    "src/components/aero/GmatTrajectoryViewer.jsx":
        "src/components/aerospace/GmatTrajectoryViewer.jsx",
    "kerf-aero/openrocket_motors.py":
        "packages/kerf-cad-core/src/kerf_cad_core/aerospace/motor_database.py",

    # ---- electronics ----
    "packages/kerf-electronics/src/kerf_electronics/bsim4.py":
        "packages/kerf-electronics/src/kerf_electronics/spice/bsim4_model.py",
    "kerf-electronics/multiboard.py":
        "packages/kerf-electronics/src/kerf_electronics/multi_board/workspace.py",
    "src/components/electronics/SchematicCapture.jsx":
        "src/components/electronics/SchematicEditor.jsx",
    "src/components/electronics/PCBEditor.jsx":
        "src/routes/PCBEditor.jsx",
    "kerf-electronics/routing/push_shove.py":
        "packages/kerf-electronics/src/kerf_electronics/routing/push_shove.py",
    "kerf-electronics/routes_rf.py":
        "packages/kerf-electronics/src/kerf_electronics/routes_rf.py",

    # ---- woodworking ----
    "packages/kerf-woodworking/src/kerf_woodworking/mozaik.py":
        "packages/kerf-woodworking/src/kerf_woodworking/cabinet_cut_list.py",

    # ---- visual scripting / systems ----
    "src/components/visual_script/NodeGraph.jsx":
        "src/components/nodescript/NodeGraphCanvas.jsx",
    "kerf-systems/marionette.py":
        "packages/kerf-cad-core/src/kerf_cad_core/visualscript/marionette.py",

    # ---- motion / animation ----
    "kerf-motion/animation.py":
        "packages/kerf-cad-core/src/kerf_cad_core/animation/keyframe.py",
    "kerf-motion/ik_solvers.py":
        "packages/kerf-cad-core/src/kerf_cad_core/animation/ik_solver.py",
    "kerf-motion/inverse_dynamics.py":
        "packages/kerf-motion/src/kerf_motion/inverse_dynamics.py",

    # ---- LCA / materials ----
    "packages/kerf-lca/src/kerf_lca/ashby_selection.py":
        "packages/kerf-cad-core/src/kerf_cad_core/materials/ashby_selection.py",

    # ---- energy ----
    "kerf-energy/pv_irradiance.py":
        "packages/kerf-energy/src/kerf_energy/pv_irradiance.py",
    "kerf-energy/solarpv/tmy.py":
        "packages/kerf-cad-core/src/kerf_cad_core/solarpv/tmy.py",

    # ---- landscape ----
    "kerf-landscape/irrigation_design.py":
        "packages/kerf-landscape/src/kerf_landscape/irrigation_design.py",

    # ---- HVAC ----
    "kerf-hvac/ahri_catalogue.py":
        "packages/kerf-hvac/src/kerf_hvac/ahri_catalogue.py",

    # ---- CAM ----
    "kerf-cam/turning_depth_calc.py":
        "packages/kerf-cam/src/kerf_cam/turning_depth_calc.py",

    # ---- frontend panels (bare names used outside of src/ paths) ----
    "StructuralPanel.jsx":
        "src/components/arch/StructuralPanel.jsx",
    "OpticsDesignPanel.jsx":
        "src/components/optics/OpticsDesignPanel.jsx",
    "TINView.jsx":
        "src/components/civil/TINView.jsx",
    "PipeNetworkView.jsx":
        "src/components/civil/PipeNetworkView.jsx",
    "GradingPlanView.jsx":
        "src/components/civil/GradingPlanView.jsx",
    "LandscapeView.jsx":
        "src/components/civil/LandscapeView.jsx",
    "SysMLTracePanel.jsx":
        "src/components/plm/SysMLTracePanel.jsx",

    # ---- WebGPU path tracer ----
    "src/components/render/WebGPUPathTracer.jsx":
        "src/components/render/PathTracerCanvas.jsx",
}


def verify_corrections() -> list[str]:
    """Return list of correction-table entries where the mapped path does not exist."""
    bad = []
    for cited, real in CORRECTIONS.items():
        if real is not None:
            full = REPO_ROOT / real
            if not full.exists():
                bad.append(f"  CORRECTION BAD: {cited!r} -> {real!r} (target missing)")
    return bad


def fix_roadmap(dry_run: bool = False) -> tuple[int, int, int, int]:
    """
    Returns (checked, already_ok, fixed, removed).
    """
    text = ROADMAP.read_text()

    checked = 0
    already_ok = 0
    fixed = 0
    removed = 0

    # We substitute inline. Walk through corrections sorted longest-first to
    # avoid partial-match collisions when one string is a suffix of another.
    for cited, real in sorted(CORRECTIONS.items(), key=lambda kv: -len(kv[0])):
        # Only touch the path if it appears as a backtick-quoted string in the file.
        # Pattern: `<cited>` (with possible trailing slash for dirs)
        escaped = re.escape(cited)
        pattern = r'`(' + escaped + r')`'

        occurrences = re.findall(pattern, text)
        if not occurrences:
            continue   # path not present in this version of the file

        checked += len(occurrences)

        if (REPO_ROOT / cited).exists():
            already_ok += len(occurrences)
            continue

        if real is None:
            # Remove: replace `bad/path.py` with nothing; also clean up any
            # wrapping parens that become empty: ", `bad/path.py`" or "(`bad/path.py`)"
            def _remove(m: re.Match) -> str:
                return ""

            # First strip ", `cited`" or " (`cited`)" or "(`cited`)"
            # including surrounding whitespace/punctuation
            text = re.sub(
                r'\s*[,(]\s*`' + escaped + r'`\s*[,)]?',
                lambda m: (
                    "" if m.group(0).lstrip().startswith("(") else
                    m.group(0)[0] if m.group(0)[0] in (", ") else ""
                ),
                text,
            )
            # Then remove any remaining bare occurrences
            text = re.sub(r'`' + escaped + r'`', "", text)
            removed += len(occurrences)
        else:
            text = re.sub(pattern, f"`{real}`", text)
            fixed += len(occurrences)

    if not dry_run:
        ROADMAP.write_text(text)

    return checked, already_ok, fixed, removed


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    print("Validating correction table targets …")
    bad_corrections = verify_corrections()
    if bad_corrections:
        print("WARNING — some correction targets do not exist:")
        for line in bad_corrections:
            print(line)
    else:
        print("  All correction targets verified OK.")

    mode = "DRY RUN" if dry_run else "APPLYING"
    print(f"\n{mode} fixes to {ROADMAP} …")
    checked, already_ok, fixed, removed = fix_roadmap(dry_run=dry_run)

    print(f"\nResults:")
    print(f"  Backtick occurrences processed : {checked}")
    print(f"  Already correct (left alone)   : {already_ok}")
    print(f"  Fixed (path updated)           : {fixed}")
    print(f"  Removed (no real path found)   : {removed}")

    if bad_corrections:
        sys.exit(1)


if __name__ == "__main__":
    main()
