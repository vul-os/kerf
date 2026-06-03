"""
kerf_cad_core.optics.advanced_optics_tools — Wave 9D LLM tools for Zemax metalens
design and STOP (Structural-Thermal-Optical Performance) multiphysics analysis.

Tools registered
----------------
  optics_design_metalens
      Design a hyperbolic metalens (metasurface lens) from a spec: diameter,
      focal length, wavelength, unit-cell period, pillar material, substrate.
      Returns pillar count, RMS phase error, estimated efficiency, and design
      summary.  Backed by metalens.design_hyperbolic_metalens.

  optics_metalens_chromatic_efficiency
      Evaluate diffraction efficiency of a metalens design across a wavelength
      range.  Returns a list of (wavelength_nm, efficiency_pct) pairs.

  optics_stop_analysis
      Perform a Structural-Thermal-Optical Performance (STOP) analysis on an
      optical system.  Takes surface descriptions, nodal temperatures and
      displacements, CTE coefficients, and wavelength.  Returns wavefront error,
      Strehl ratio, RMS spot radius, and most sensitive surface.
      Backed by stop_analysis.compute_stop_perturbation.

  optics_thermal_expansion
      Compute linear thermal expansion ΔL = α·L₀·ΔT for a named surface.

All tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: ...} — tools never raise.

Simplified flag
---------------
Both engines use simplified analytic models.  Production-grade metalens design
requires FDTD (e.g. Lumerical) per unit cell; production STOP requires full FEA
coupling (ANSYS/Abaqus) + Zernike sensitivity matrix from Zemax OpticStudio or CODE V.

References
----------
Khorasaninejad, M. et al. (2016). Science 352:1190–1194.
Aieta, F. et al. (2015). Science 347:1342–1345.
Doyle, K.B., Genberg, V.L., Michels, G.J. (2002). Integrated optomechanical analysis.
    SPIE Press PM130.
Wang, T-Y. et al. (2006). Proc. SPIE 6288.

Author: imranparuk
"""
from __future__ import annotations

import json
import math

import numpy as np

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.optics.metalens import (
    MetalensSpec,
    design_hyperbolic_metalens,
    metalens_efficiency_at,
)
from kerf_cad_core.optics.stop_analysis import (
    OpticalSurface,
    StopState,
    compute_stop_perturbation,
    thermal_expansion_displacement,
)


# ---------------------------------------------------------------------------
# Tool: optics_design_metalens
# ---------------------------------------------------------------------------

_optics_design_metalens_spec = ToolSpec(
    name="optics_design_metalens",
    description=(
        "Design a hyperbolic metalens (metasurface lens) using nanopillar phase "
        "modulation.\n"
        "\n"
        "Uses the standard hyperbolic phase profile φ(r) = -2π/λ·(√(r²+f²)-f) "
        "and maps phase to pillar radius via an FDTD-precomputed lookup table "
        "(v1 approximation for TiO₂, Si₃N₄, GaN at visible wavelengths).\n"
        "\n"
        "Returns:\n"
        "  n_pillars         — total nanopillar count inside the aperture\n"
        "  rms_phase_error_rad — RMS(φ_target − φ_achieved) [rad]\n"
        "  estimated_efficiency_pct — diffraction efficiency at design wavelength [%]\n"
        "  pillar_sample     — first 5 pillars (cx_mm, cy_mm, radius_nm, phase_rad)\n"
        "  honest_caveat     — transparency note about model limitations\n"
        "\n"
        "SIMPLIFIED: production design requires full 3-D FDTD + RCWA per unit cell "
        "(Khorasaninejad 2016 Science 352:1190).\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "required": ["diameter_mm", "focal_length_mm", "target_wavelength_nm"],
        "properties": {
            "diameter_mm": {
                "type": "number",
                "description": "Clear aperture diameter [mm]. E.g. 1.0.",
            },
            "focal_length_mm": {
                "type": "number",
                "description": "Design focal length [mm]. E.g. 100.0.",
            },
            "target_wavelength_nm": {
                "type": "number",
                "description": "Design wavelength [nm]. E.g. 532 (green), 633 (red). Default 532.",
            },
            "unit_cell_period_nm": {
                "type": "number",
                "description": "Sub-wavelength unit-cell pitch [nm]. Must be < λ. Default 450.",
            },
            "pillar_material": {
                "type": "string",
                "description": "Nanopillar material: 'TiO2' | 'Si3N4' | 'GaN'. Default 'TiO2'.",
            },
            "substrate_material": {
                "type": "string",
                "description": "Substrate: 'fused_silica' | 'sapphire'. Default 'fused_silica'.",
            },
            "pillar_height_nm": {
                "type": "number",
                "description": "Pillar height [nm]. Default 600.",
            },
        },
    },
)


@register(_optics_design_metalens_spec)
def optics_design_metalens(params: dict, ctx: ProjectCtx) -> dict:  # type: ignore[override]
    """LLM tool: design a hyperbolic metalens."""
    try:
        diameter_mm = float(params["diameter_mm"])
        focal_length_mm = float(params["focal_length_mm"])
        target_wavelength_nm = float(params.get("target_wavelength_nm", 532.0))
        unit_cell_period_nm = float(params.get("unit_cell_period_nm", 450.0))
        pillar_material = str(params.get("pillar_material", "TiO2"))
        substrate_material = str(params.get("substrate_material", "fused_silica"))
        pillar_height_nm = float(params.get("pillar_height_nm", 600.0))

        if diameter_mm <= 0:
            return err_payload("diameter_mm must be positive.")
        if focal_length_mm <= 0:
            return err_payload("focal_length_mm must be positive.")
        if target_wavelength_nm <= 0:
            return err_payload("target_wavelength_nm must be positive.")
        if unit_cell_period_nm <= 0 or unit_cell_period_nm >= target_wavelength_nm:
            return err_payload(
                f"unit_cell_period_nm ({unit_cell_period_nm}) must be in (0, λ={target_wavelength_nm})."
            )

        spec = MetalensSpec(
            diameter_mm=diameter_mm,
            focal_length_mm=focal_length_mm,
            target_wavelength_nm=target_wavelength_nm,
            unit_cell_period_nm=unit_cell_period_nm,
            pillar_material=pillar_material,
            substrate_material=substrate_material,
            pillar_height_nm=pillar_height_nm,
        )

        design = design_hyperbolic_metalens(spec)

        sample = [
            {
                "cx_mm": p.cx_mm,
                "cy_mm": p.cy_mm,
                "radius_nm": round(p.radius_nm, 2),
                "phase_target_rad": round(p.phase_target_rad, 4),
            }
            for p in design.pillars[:5]
        ]

        return ok_payload({
            "n_pillars": len(design.pillars),
            "rms_phase_error_rad": round(design.rms_phase_error_rad, 6),
            "estimated_efficiency_pct": round(design.estimated_efficiency_pct, 2),
            "pillar_sample": sample,
            "f_number": round(focal_length_mm / diameter_mm, 2),
            "numerical_aperture": round(
                math.sin(math.atan(diameter_mm / (2 * focal_length_mm))), 4
            ),
            "honest_caveat": design.honest_caveat,
        })

    except (KeyError, ValueError) as exc:
        return err_payload(str(exc))
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Tool: optics_metalens_chromatic_efficiency
# ---------------------------------------------------------------------------

_optics_metalens_chromatic_spec = ToolSpec(
    name="optics_metalens_chromatic_efficiency",
    description=(
        "Evaluate the diffraction efficiency of a metalens design across a range "
        "of wavelengths.\n"
        "\n"
        "First designs the metalens at the target wavelength (same parameters as "
        "optics_design_metalens), then sweeps wavelength_min_nm to wavelength_max_nm "
        "in n_points steps.\n"
        "\n"
        "Returns:\n"
        "  wavelength_nm_list    — list of wavelengths sampled\n"
        "  efficiency_pct_list   — corresponding efficiency [%]\n"
        "  peak_efficiency_pct   — maximum efficiency (at or near design wavelength)\n"
        "  fwhm_bandwidth_nm     — approximate full-width-half-maximum bandwidth [nm]\n"
        "\n"
        "SIMPLIFIED: uses a sinc²-Gaussian roll-off model (Aieta 2015).  Full "
        "dispersion requires FDTD sweep per wavelength.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "required": ["diameter_mm", "focal_length_mm", "target_wavelength_nm"],
        "properties": {
            "diameter_mm": {"type": "number"},
            "focal_length_mm": {"type": "number"},
            "target_wavelength_nm": {"type": "number"},
            "unit_cell_period_nm": {"type": "number"},
            "pillar_material": {"type": "string"},
            "substrate_material": {"type": "string"},
            "pillar_height_nm": {"type": "number"},
            "wavelength_min_nm": {
                "type": "number",
                "description": "Start of wavelength sweep [nm]. Default 400.",
            },
            "wavelength_max_nm": {
                "type": "number",
                "description": "End of wavelength sweep [nm]. Default 800.",
            },
            "n_points": {
                "type": "integer",
                "description": "Number of wavelength samples. Default 21. Max 201.",
            },
        },
    },
)


@register(_optics_metalens_chromatic_spec)
def optics_metalens_chromatic_efficiency(params: dict, ctx: ProjectCtx) -> dict:  # type: ignore[override]
    """LLM tool: chromatic efficiency sweep for a metalens design."""
    try:
        diameter_mm = float(params["diameter_mm"])
        focal_length_mm = float(params["focal_length_mm"])
        target_wavelength_nm = float(params.get("target_wavelength_nm", 532.0))
        unit_cell_period_nm = float(params.get("unit_cell_period_nm", 450.0))
        pillar_material = str(params.get("pillar_material", "TiO2"))
        substrate_material = str(params.get("substrate_material", "fused_silica"))
        pillar_height_nm = float(params.get("pillar_height_nm", 600.0))
        wl_min = float(params.get("wavelength_min_nm", 400.0))
        wl_max = float(params.get("wavelength_max_nm", 800.0))
        n_points = int(min(params.get("n_points", 21), 201))

        spec = MetalensSpec(
            diameter_mm=diameter_mm,
            focal_length_mm=focal_length_mm,
            target_wavelength_nm=target_wavelength_nm,
            unit_cell_period_nm=unit_cell_period_nm,
            pillar_material=pillar_material,
            substrate_material=substrate_material,
            pillar_height_nm=pillar_height_nm,
        )
        design = design_hyperbolic_metalens(spec)

        wavelengths = np.linspace(wl_min, wl_max, n_points).tolist()
        efficiencies = [round(metalens_efficiency_at(design, wl), 3) for wl in wavelengths]

        peak = max(efficiencies)
        half_peak = peak / 2.0
        # FWHM: count wavelengths above half-peak
        above = [w for w, e in zip(wavelengths, efficiencies) if e >= half_peak]
        fwhm = (max(above) - min(above)) if len(above) >= 2 else 0.0

        return ok_payload({
            "wavelength_nm_list": [round(w, 1) for w in wavelengths],
            "efficiency_pct_list": efficiencies,
            "peak_efficiency_pct": round(peak, 3),
            "fwhm_bandwidth_nm": round(fwhm, 1),
        })

    except (KeyError, ValueError) as exc:
        return err_payload(str(exc))
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Tool: optics_stop_analysis
# ---------------------------------------------------------------------------

_optics_stop_spec = ToolSpec(
    name="optics_stop_analysis",
    description=(
        "Perform a Structural-Thermal-Optical Performance (STOP) analysis.\n"
        "\n"
        "Inputs a list of optical surfaces with their material, aperture, and nominal\n"
        "pose (as a flat 16-element row-major 4×4 matrix).  Thermal and structural\n"
        "states are given as nodal temperatures [K] and nodal displacements [mm].\n"
        "\n"
        "For each surface: computes rigid-body perturbation from thermal expansion\n"
        "(ΔL = α·L₀·ΔT) + structural displacement, estimates wavefront error\n"
        "contribution, then sums system WFE and Strehl ratio.\n"
        "\n"
        "Returns:\n"
        "  wavefront_error_rms_nm  — system RMS wavefront error [nm]\n"
        "  wavefront_error_pv_nm   — peak-to-valley WFE [nm]\n"
        "  rms_spot_radius_um      — geometric RMS spot radius [μm]\n"
        "  strehl_ratio            — Maréchal approximation exp(-(2π σ/λ)²)\n"
        "  most_sensitive_surface  — surface ID with largest WFE contribution\n"
        "  surface_axial_shifts_mm — dict{surface_id: axial shift [mm]}\n"
        "  honest_caveat           — model limitations\n"
        "\n"
        "SIMPLIFIED: production needs full FEA + Zernike sensitivity matrix.\n"
        "(Doyle-Genberg 2002 SPIE PM130; Wang et al. 2006 SPIE 6288)\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "required": ["surfaces"],
        "properties": {
            "surfaces": {
                "type": "array",
                "description": "List of optical surface definitions.",
                "items": {
                    "type": "object",
                    "required": ["surface_id", "aperture_radius_mm", "material"],
                    "properties": {
                        "surface_id": {"type": "string"},
                        "nominal_pose_flat": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Row-major 4×4 rigid transform (16 numbers). Default identity.",
                        },
                        "radius_of_curvature_mm": {
                            "type": "number",
                            "description": "Signed RoC [mm]. Use 1e30 for flat. Default 1e30.",
                        },
                        "aperture_radius_mm": {"type": "number"},
                        "material": {
                            "type": "string",
                            "description": "Material name (used as key into cte_coeffs).",
                        },
                    },
                },
            },
            "temperatures_at_node": {
                "type": "object",
                "description": "Dict {surface_id: temperature_K}. Missing → reference T = 293.15 K.",
                "additionalProperties": {"type": "number"},
            },
            "displacements_at_node": {
                "type": "object",
                "description": "Dict {surface_id: [dx, dy, dz] mm}. Missing → zero.",
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "number"},
                },
            },
            "cte_coeffs": {
                "type": "object",
                "description": "Dict {material: cte [1/K]}. E.g. {'N-BK7': 7.1e-6, 'Al6061': 23.6e-6}.",
                "additionalProperties": {"type": "number"},
            },
            "youngs_modulus": {
                "type": "object",
                "description": "Dict {material: E [GPa]}. Not used in v1 simplified model.",
                "additionalProperties": {"type": "number"},
            },
            "wavelength_nm": {
                "type": "number",
                "description": "Analysis wavelength [nm]. Default 633.",
            },
        },
    },
)


@register(_optics_stop_spec)
def optics_stop_analysis(params: dict, ctx: ProjectCtx) -> dict:  # type: ignore[override]
    """LLM tool: STOP multiphysics analysis."""
    try:
        wavelength_nm = float(params.get("wavelength_nm", 633.0))
        cte_coeffs = {k: float(v) for k, v in params.get("cte_coeffs", {}).items()}
        youngs_modulus = {k: float(v) for k, v in params.get("youngs_modulus", {}).items()}
        temperatures_raw = params.get("temperatures_at_node", {})
        displacements_raw = params.get("displacements_at_node", {})

        temperatures = {k: float(v) for k, v in temperatures_raw.items()}
        displacements = {
            k: np.array([float(x) for x in v], dtype=float)
            for k, v in displacements_raw.items()
        }

        surfaces = []
        for sd in params.get("surfaces", []):
            sid = str(sd["surface_id"])
            aperture = float(sd["aperture_radius_mm"])
            material = str(sd["material"])
            roc = float(sd.get("radius_of_curvature_mm", 1e30))
            flat = sd.get("nominal_pose_flat")
            if flat is not None and len(flat) == 16:
                pose = np.array(flat, dtype=float).reshape(4, 4)
            else:
                pose = np.eye(4, dtype=float)

            surfaces.append(OpticalSurface(
                surface_id=sid,
                nominal_pose=pose,
                radius_of_curvature_mm=roc,
                aperture_radius_mm=aperture,
                material=material,
            ))

        if not surfaces:
            return err_payload("No surfaces provided.")

        state = StopState(
            temperatures_at_node=temperatures,
            displacements_at_node=displacements,
        )

        report = compute_stop_perturbation(
            surfaces=surfaces,
            state=state,
            cte_coeffs=cte_coeffs,
            youngs_modulus=youngs_modulus,
            wavelength_nm=wavelength_nm,
        )

        axial_shifts = {
            sid: round(float(delta[2, 3]), 6)
            for sid, delta in report.surface_pose_perturbations.items()
        }

        return ok_payload({
            "wavefront_error_rms_nm": round(report.wavefront_error_rms_nm, 4),
            "wavefront_error_pv_nm": round(report.wavefront_error_pv_nm, 4),
            "rms_spot_radius_um": round(report.rms_spot_radius_um, 6),
            "strehl_ratio": round(report.strehl_ratio, 6),
            "most_sensitive_surface": report.most_sensitive_surface,
            "surface_axial_shifts_mm": axial_shifts,
            "honest_caveat": report.honest_caveat,
        })

    except (KeyError, ValueError) as exc:
        return err_payload(str(exc))
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Tool: optics_thermal_expansion
# ---------------------------------------------------------------------------

_optics_thermal_expansion_spec = ToolSpec(
    name="optics_thermal_expansion",
    description=(
        "Compute linear thermal expansion ΔL = α · L₀ · ΔT for an optical surface.\n"
        "\n"
        "For uniform temperature: exact.  For non-uniform fields use the mean T.\n"
        "\n"
        "Returns:\n"
        "  delta_L_mm        — thermal expansion displacement [mm]\n"
        "  delta_T_K         — temperature rise above reference (293.15 K)\n"
        "  cte               — CTE used [1/K]\n"
        "  original_size_mm  — L₀ used [mm]\n"
        "\n"
        "(Doyle-Genberg 2002 §3.2: ΔL = α·L₀·ΔT)\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "required": ["surface_id", "temperature_K", "cte", "original_size_mm"],
        "properties": {
            "surface_id": {"type": "string"},
            "temperature_K": {
                "type": "number",
                "description": "Nodal temperature [K].",
            },
            "cte": {
                "type": "number",
                "description": "Coefficient of thermal expansion [1/K]. E.g. 7.1e-6 for N-BK7.",
            },
            "original_size_mm": {
                "type": "number",
                "description": "Nominal dimension at reference temperature (293.15 K) [mm].",
            },
        },
    },
)


@register(_optics_thermal_expansion_spec)
def optics_thermal_expansion(params: dict, ctx: ProjectCtx) -> dict:  # type: ignore[override]
    """LLM tool: linear thermal expansion."""
    try:
        surface_id = str(params["surface_id"])
        temperature_K = float(params["temperature_K"])
        cte = float(params["cte"])
        original_size_mm = float(params["original_size_mm"])

        temperatures = {surface_id: temperature_K}
        delta_L = thermal_expansion_displacement(surface_id, temperatures, cte, original_size_mm)
        delta_T = temperature_K - 293.15

        return ok_payload({
            "delta_L_mm": round(delta_L, 9),
            "delta_T_K": round(delta_T, 4),
            "cte": cte,
            "original_size_mm": original_size_mm,
        })

    except (KeyError, ValueError) as exc:
        return err_payload(str(exc))
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Unexpected error: {exc}")
