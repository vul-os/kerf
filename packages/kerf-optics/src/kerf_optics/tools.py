"""
kerf_optics LLM tools — paraxial ray-trace and lens design.

Registered via plugin.py at startup.

Tools
-----
optics_trace_ray    — trace a ray (or bundle) through a multi-element lens
                      system and return spot size / focal length.
optics_lens_design  — first-order design helper: given target EFL and object
                      distance, solve for element parameters.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_optics._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# optics_trace_ray
# ---------------------------------------------------------------------------

optics_trace_ray_spec = ToolSpec(
    name="optics_trace_ray",
    description=(
        "Trace a ray (or a ray bundle) through a multi-element paraxial lens "
        "system using the ABCD ray-transfer matrix formalism.  Returns ray "
        "heights at each surface, effective focal length, and RMS spot radius "
        "at the exit plane.  Supports thin lenses, free-space gaps, curved "
        "interfaces, mirrors, and aperture stops."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": (
                    "Ordered list of optical elements (first = closest to source). "
                    "Each element is a dict with a 'type' key and type-specific "
                    "parameters:\n"
                    "  {type:'thin_lens', f:<focal_length_m>}\n"
                    "  {type:'free_space', d:<distance_m>, n:<index, default 1.0>}\n"
                    "  {type:'curved_interface', R:<radius_m>, n1:<from_index>, n2:<to_index>}\n"
                    "  {type:'mirror', R:<radius_m>}\n"
                    "  {type:'aperture', diameter:<m>}\n"
                    "  {type:'detector'}"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                    },
                    "required": ["type"],
                },
                "minItems": 1,
            },
            "rays": {
                "type": "array",
                "description": (
                    "Ray bundle: list of [y0, nu0] initial ray states. "
                    "y0 = height (m), nu0 = reduced angle n*theta. "
                    "Default: [[0.001, 0.0]] (on-axis marginal ray, h=1 mm)."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
        },
        "required": ["elements"],
    },
)


def _build_element(spec: dict):
    """Deserialise an element dict into the appropriate Element object."""
    from kerf_optics.lens_system import (
        ThinLens, FreeSpace, CurvedInterface, Mirror, Aperture, Detector
    )

    etype = spec.get("type", "").lower()
    if etype == "thin_lens":
        return ThinLens(f=float(spec["f"]))
    elif etype == "free_space":
        return FreeSpace(d=float(spec["d"]), n=float(spec.get("n", 1.0)))
    elif etype == "curved_interface":
        return CurvedInterface(
            R=float(spec["R"]),
            n1=float(spec["n1"]),
            n2=float(spec["n2"]),
        )
    elif etype == "mirror":
        return Mirror(R=float(spec["R"]))
    elif etype == "aperture":
        return Aperture(diameter=float(spec["diameter"]))
    elif etype == "detector":
        return Detector()
    else:
        raise ValueError(f"unknown element type: {spec.get('type')!r}")


async def run_optics_trace_ray(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_optics.lens_system import LensSystem

        raw_elements = args["elements"]
        elements = [_build_element(e) for e in raw_elements]

        raw_rays = args.get("rays")
        if raw_rays is None:
            rays = [(0.001, 0.0)]  # default: 1 mm marginal ray
        else:
            rays = [(float(r[0]), float(r[1])) for r in raw_rays]

        system = LensSystem(elements)
        M = system.system_matrix()
        histories = system.trace_bundle(rays)

        # Spot diagram
        spot = system.spot_diagram()

        # EFL if system has power
        C = M[1, 0]
        efl = (-1.0 / C) if abs(C) > 1e-14 else None

        # Format ray histories
        ray_data = []
        for i, hist in enumerate(histories):
            ray_data.append({
                "ray_index": i,
                "y0": hist[0][0],
                "nu0": hist[0][1],
                "surfaces": [
                    {"y": round(y, 8), "nu": round(nu, 8)}
                    for y, nu in hist[1:]
                ],
                "final_height": round(hist[-1][0], 8),
            })

        payload: dict[str, Any] = {
            "n_elements": len(elements),
            "efl": round(efl, 8) if efl is not None else None,
            "system_matrix": {
                "A": round(M[0, 0], 8),
                "B": round(M[0, 1], 8),
                "C": round(M[1, 0], 8),
                "D": round(M[1, 1], 8),
            },
            "rays": ray_data,
            "spot": {
                "rms_spot_m": round(spot["rms_spot"], 10),
                "n_rays": spot["n_rays"],
            },
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "OPTICS_ERROR")


# ---------------------------------------------------------------------------
# optics_lens_design
# ---------------------------------------------------------------------------

optics_lens_design_spec = ToolSpec(
    name="optics_lens_design",
    description=(
        "First-order paraxial lens design helper. Given a target effective "
        "focal length (EFL) and conjugate distances (object and image), "
        "solves for the lens arrangement and returns the thin-lens system "
        "parameters.  For a single-lens system, uses the thin-lens equation "
        "1/f = 1/di - 1/do. For a two-lens telephoto, computes the "
        "separation required to achieve the target EFL."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_efl": {
                "type": "number",
                "description": "Target effective focal length in metres.",
            },
            "object_distance": {
                "type": "number",
                "description": "Object distance (m) — positive = real object to the left.",
            },
            "design_type": {
                "type": "string",
                "enum": ["single", "telephoto"],
                "description": "'single' (one thin lens) or 'telephoto' (two lenses). Default 'single'.",
            },
            "f1": {
                "type": "number",
                "description": "(telephoto only) Focal length of the first element (m).",
            },
            "f2": {
                "type": "number",
                "description": "(telephoto only) Focal length of the second element (m). "
                               "If omitted, solved from target_efl and f1.",
            },
        },
        "required": ["target_efl", "object_distance"],
    },
)


async def run_optics_lens_design(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_optics.lens_system import LensSystem, FreeSpace, ThinLens
        from kerf_optics.ray_transfer import focal_length as _efl, image_distance as _imgdist

        target_efl = float(args["target_efl"])
        do = float(args["object_distance"])
        design_type = args.get("design_type", "single")

        if design_type == "single":
            # Thin-lens equation: 1/di = 1/f + 1/do  (note: do is positive)
            # Using sign convention di = 1/(1/f - 1/do) for do positive
            f = target_efl
            # image distance from thin lens equation
            if abs(1.0 / f - 1.0 / do) < 1e-14:
                raise ValueError("object at the focal point; image at infinity")
            di = 1.0 / (1.0 / f - 1.0 / do)

            system = LensSystem([FreeSpace(do), ThinLens(f), FreeSpace(di)])
            M = system.system_matrix()

            payload = {
                "design_type": "single",
                "f": f,
                "object_distance": do,
                "image_distance": round(di, 6),
                "efl_achieved": round(_efl(ThinLens(f).matrices()[0]), 6),
                "magnification": round(di / do, 6),
                "elements": [
                    {"type": "free_space", "d": do},
                    {"type": "thin_lens", "f": f},
                    {"type": "free_space", "d": round(di, 6)},
                ],
            }

        elif design_type == "telephoto":
            f1 = float(args.get("f1", target_efl * 1.5))
            if "f2" in args:
                f2 = float(args["f2"])
                # Compute separation from EFL formula:
                #   1/EFL = 1/f1 + 1/f2 - d/(f1*f2)  →  d = (1/f1 + 1/f2 - 1/EFL) * f1*f2
                d = (1.0 / f1 + 1.0 / f2 - 1.0 / target_efl) * f1 * f2
            else:
                # Solve f2 from EFL formula with a default separation d = f1/4
                d = f1 / 4.0
                # 1/EFL = 1/f1 + 1/f2 - d/(f1*f2)
                # 1/f2 = 1/EFL - 1/f1 + d/(f1*f2) — needs rearrangement
                # 1/f2 * (1 - d/f1) = 1/EFL - 1/f1
                # (1/f2) = (1/EFL - 1/f1) / (1 - d/f1)
                denom = 1.0 - d / f1
                if abs(denom) < 1e-14:
                    raise ValueError(f"degenerate telephoto: d == f1 ({f1})")
                inv_f2 = (1.0 / target_efl - 1.0 / f1) / denom
                if abs(inv_f2) < 1e-14:
                    raise ValueError("f2 → infinity; unsolvable telephoto")
                f2 = 1.0 / inv_f2

            # Build system up to lens2 (no image plane yet) and find image distance
            pre_system = LensSystem([FreeSpace(do), ThinLens(f1), FreeSpace(d), ThinLens(f2)])
            M = pre_system.system_matrix()

            # Image is located where height of an on-axis ray = 0; for ABCD: di = -D/C
            C = M[1, 0]
            if abs(C) < 1e-14:
                raise ValueError("telephoto system has no power")
            achieved_efl = -1.0 / C
            di = -M[1, 1] / C  # image distance from last element

            payload = {
                "design_type": "telephoto",
                "f1": round(f1, 6),
                "f2": round(f2, 6),
                "separation": round(d, 6),
                "object_distance": do,
                "image_distance_from_lens2": round(di, 6),
                "efl_achieved": round(achieved_efl, 6),
                "elements": [
                    {"type": "free_space", "d": do},
                    {"type": "thin_lens", "f": round(f1, 6)},
                    {"type": "free_space", "d": round(d, 6)},
                    {"type": "thin_lens", "f": round(f2, 6)},
                    {"type": "free_space", "d": round(di, 6)},
                ],
            }

        else:
            return err_payload(f"unknown design_type: {design_type!r}", "BAD_ARGS")

        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "OPTICS_DESIGN_ERROR")


# ---------------------------------------------------------------------------
# optics_tolerancing
# ---------------------------------------------------------------------------

optics_tolerancing_spec = ToolSpec(
    name="optics_tolerancing",
    description=(
        "Optical tolerance analysis (sensitivity + Monte Carlo) for a multi-element "
        "paraxial lens system.  Perturbs each tolerance parameter one-at-a-time (OAT) "
        "and also runs Monte Carlo trials.  Merit function options: 'efl' (|EFL − target|), "
        "'bfd' (|BFD − target|).  Returns per-parameter sensitivities, RSS budget, and "
        "Monte Carlo statistics (mean, std, P05, P95, yield)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": "Lens system elements (same format as optics_trace_ray).",
                "items": {"type": "object"},
                "minItems": 1,
            },
            "tolerances": {
                "type": "array",
                "description": (
                    "List of tolerance parameters. Each: "
                    "{element_index: int, param_name: str, delta: float, "
                    "nominal: float (optional), description: str (optional)}."
                ),
                "items": {"type": "object"},
                "minItems": 1,
            },
            "merit_type": {
                "type": "string",
                "enum": ["efl", "bfd"],
                "description": "Merit function: 'efl' or 'bfd'. Default 'efl'.",
            },
            "target_value": {
                "type": "number",
                "description": "Target value for the merit function (m). Default = nominal EFL.",
            },
            "n_mc_trials": {
                "type": "integer",
                "description": "Number of Monte Carlo trials. Default 500.",
            },
            "mc_distribution": {
                "type": "string",
                "enum": ["uniform", "normal"],
                "description": "Monte Carlo distribution: 'uniform' (default) or 'normal' (±3σ).",
            },
            "mc_seed": {
                "type": "integer",
                "description": "Monte Carlo random seed. Default 42.",
            },
        },
        "required": ["elements", "tolerances"],
    },
)


async def run_optics_tolerancing(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_optics.lens_system import LensSystem
        from kerf_optics.tolerancing import (
            ToleranceParam,
            sensitivity_analysis,
            monte_carlo_tolerancing,
            merit_efl,
            merit_bfd,
        )

        # Build system
        raw_elements = args["elements"]
        from kerf_optics.tools import _build_element
        elements = [_build_element(e) for e in raw_elements]
        system = LensSystem(elements)

        # Build tolerance params
        raw_tols = args["tolerances"]
        params = []
        for t in raw_tols:
            params.append(ToleranceParam(
                element_index=int(t["element_index"]),
                param_name=str(t["param_name"]),
                nominal=float(t["nominal"]) if "nominal" in t else None,
                delta=float(t["delta"]),
                description=str(t.get("description", "")),
            ))

        # Merit function
        merit_type = str(args.get("merit_type", "efl")).lower()
        M = system.system_matrix()
        C = M[1, 0]
        nominal_efl = -1.0 / C if abs(C) > 1e-14 else 1.0
        target = float(args.get("target_value", nominal_efl))

        if merit_type == "efl":
            merit_fn = merit_efl(target)
        elif merit_type == "bfd":
            merit_fn = merit_bfd(target)
        else:
            return err_payload(f"unknown merit_type: {merit_type!r}", "BAD_ARGS")

        # Sensitivity
        sens = sensitivity_analysis(system, params, merit_fn)

        # Monte Carlo
        n_mc = int(args.get("n_mc_trials", 500))
        mc_dist = str(args.get("mc_distribution", "uniform"))
        mc_seed = int(args.get("mc_seed", 42))
        mc = monte_carlo_tolerancing(
            system, params, merit_fn,
            n_trials=n_mc, distribution=mc_dist, seed=mc_seed,
        )

        payload: dict[str, Any] = {
            "merit_type": merit_type,
            "target_value": target,
            "merit_nominal": round(sens.merit_nominal, 8),
            "rss_budget": round(sens.rss_budget, 8),
            "sensitivity_table": [
                {k: (round(v, 8) if isinstance(v, float) else v)
                 for k, v in row.items()}
                for row in sens.sensitivity_table()
            ],
            "monte_carlo": mc.summary(),
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "TOLERANCING_ERROR")


# ---------------------------------------------------------------------------
# optics_mtf
# ---------------------------------------------------------------------------

optics_mtf_spec = ToolSpec(
    name="optics_mtf",
    description=(
        "Compute the Modulation Transfer Function (MTF) for a paraxial lens system. "
        "Returns the diffraction-limited MTF (circular aperture, incoherent) and the "
        "geometric MTF (Gaussian spot approximation) as functions of spatial frequency "
        "(line pairs/mm at the image plane).  Also reports the diffraction cut-off "
        "frequency, f-number, wavelength, and RMS spot radius."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": "Lens system elements (same format as optics_trace_ray).",
                "items": {"type": "object"},
                "minItems": 1,
            },
            "object_distance_m": {
                "type": "number",
                "description": "Object distance in metres (positive = real object). Default 1.0.",
            },
            "f_number": {
                "type": "number",
                "description": "Aperture f/# = focal_length / aperture_diameter. Default 4.0.",
            },
            "lambda_nm": {
                "type": "number",
                "description": "Wavelength in nanometres. Default 550 nm (green).",
            },
            "max_freq_lpmm": {
                "type": "number",
                "description": "Maximum spatial frequency in lp/mm for the output curve. "
                               "Default: 1.2× diffraction cut-off.",
            },
            "n_freq_points": {
                "type": "integer",
                "description": "Number of spatial frequency points. Default 50.",
            },
        },
        "required": ["elements"],
    },
)


async def run_optics_mtf(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        import numpy as np_inner
        from kerf_optics.lens_system import LensSystem
        from kerf_optics.mtf import mtf_from_lens_system, diffraction_cutoff_lpmm
        from kerf_optics.tools import _build_element

        raw_elements = args["elements"]
        elements = [_build_element(e) for e in raw_elements]
        system = LensSystem(elements)

        do = float(args.get("object_distance_m", 1.0))
        f_num = float(args.get("f_number", 4.0))
        lam = float(args.get("lambda_nm", 550.0))
        n_pts = int(args.get("n_freq_points", 50))

        nu_c = diffraction_cutoff_lpmm(f_num, lam)
        max_freq = float(args.get("max_freq_lpmm", 1.2 * nu_c))
        freqs = list(np_inner.linspace(0.0, max_freq, n_pts))

        result = mtf_from_lens_system(
            system,
            object_distance_m=do,
            f_number=f_num,
            lambda_nm=lam,
            spatial_freqs_lpmm=freqs,
        )

        payload: dict[str, Any] = result.to_dict()
        payload["mtf_at_50lpmm"] = round(result.mtf_50lpmm, 6)
        payload["mtf_at_100lpmm"] = round(result.mtf_100lpmm, 6)
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "MTF_ERROR")


# ---------------------------------------------------------------------------
# optics_pop_propagate
# ---------------------------------------------------------------------------

optics_pop_propagate_spec = ToolSpec(
    name="optics_pop_propagate",
    description=(
        "Physical-Optics Propagation (POP) / angular-spectrum + Fresnel/Fraunhofer "
        "scalar diffraction propagation of a monochromatic wavefront.  "
        "Generates a Gaussian TEM₀₀ source field, optionally applies a thin-lens "
        "or circular-aperture phase screen, then propagates by distance z.  "
        "Returns: intensity peak, beam waist (1/e² radius), energy conservation "
        "ratio, propagation method used, grid parameters, and Fresnel number.  "
        "Method auto-selects Angular Spectrum (near-field) or Fresnel (far-field)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lambda_um": {
                "type": "number",
                "description": "Wavelength in micrometres (e.g. 0.633 for HeNe, 1.064 for Nd:YAG). Default 0.633.",
            },
            "w0_mm": {
                "type": "number",
                "description": "Beam waist radius (1/e² field) in mm. Default 1.0.",
            },
            "z_mm": {
                "type": "number",
                "description": "Propagation distance in mm. Default 100.0.",
            },
            "grid_N": {
                "type": "integer",
                "description": "Grid size N×N pixels (power-of-2 recommended). Default 128.",
            },
            "dx_um": {
                "type": "number",
                "description": "Pixel pitch in micrometres. Default 20.0.",
            },
            "method": {
                "type": "string",
                "enum": ["auto", "asm", "fresnel"],
                "description": (
                    "Propagation method: 'auto' (Fresnel-number adaptive), "
                    "'asm' (Angular Spectrum — near-field), "
                    "'fresnel' (Fresnel TF — paraxial far-field). Default 'auto'."
                ),
            },
            "aperture_radius_mm": {
                "type": "number",
                "description": "Optional circular aperture radius (mm) applied before propagation. Omit = no aperture.",
            },
            "lens_focal_length_mm": {
                "type": "number",
                "description": "Optional thin-lens focal length (mm) applied before propagation. Omit = no lens.",
            },
        },
        "required": [],
    },
)


async def run_optics_pop_propagate(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        import math
        import numpy as np
        from kerf_optics.pop import (
            make_grid,
            gaussian_source,
            thin_lens_phase,
            circular_aperture,
            propagate,
            parseval_energy,
            gaussian_waist_analytic,
        )

        lambda_um = float(args.get("lambda_um", 0.633))
        w0_mm = float(args.get("w0_mm", 1.0))
        z_mm = float(args.get("z_mm", 100.0))
        N = int(args.get("grid_N", 128))
        dx_um = float(args.get("dx_um", 20.0))
        method = str(args.get("method", "auto"))

        # Convert to SI metres
        lambda_m = lambda_um * 1e-6
        w0_m = w0_mm * 1e-3
        z_m = z_mm * 1e-3
        dx_m = dx_um * 1e-6

        if lambda_m <= 0:
            return err_payload("lambda_um must be positive", "BAD_ARGS")
        if w0_m <= 0:
            return err_payload("w0_mm must be positive", "BAD_ARGS")
        if N < 16 or N > 1024:
            return err_payload("grid_N must be in [16, 1024]", "BAD_ARGS")
        if dx_m <= 0:
            return err_payload("dx_um must be positive", "BAD_ARGS")

        x, y = make_grid(N, dx_m)

        # Source field
        U = gaussian_source(x, y, w0=w0_m, lambda_m=lambda_m)

        E_in = parseval_energy(U, dx_m)

        # Optional lens
        lens_f = args.get("lens_focal_length_mm")
        if lens_f is not None:
            f_m = float(lens_f) * 1e-3
            if f_m != 0:
                lens_phase = thin_lens_phase(x, y, f=f_m, lambda_m=lambda_m)
                U = U * lens_phase

        # Optional aperture
        ap_r = args.get("aperture_radius_mm")
        if ap_r is not None:
            R_m = float(ap_r) * 1e-3
            mask = circular_aperture(x, y, radius=R_m)
            U = U * mask

        # Propagate
        U_out = propagate(U, dx=dx_m, z=z_m, lambda_m=lambda_m, method=method)

        # Determine actual method used
        if method == "auto":
            half_ap = (N * dx_m) / 2.0
            NF = half_ap ** 2 / (lambda_m * abs(z_m)) if z_m != 0 else float("inf")
            actual_method = "asm" if NF > 10.0 else "fresnel"
        else:
            actual_method = method
            NF = ((N * dx_m) / 2.0) ** 2 / (lambda_m * abs(z_m)) if z_m != 0 else float("inf")

        # Output field metrics
        I_out = np.abs(U_out) ** 2
        E_out = parseval_energy(U_out, dx_m)
        energy_ratio = float(E_out / E_in) if E_in > 0 else None

        I_peak = float(np.max(I_out))

        # Beam waist estimate: radius where I >= I_peak / e²
        I_threshold = I_peak / math.e ** 2
        r2 = x ** 2 + y ** 2
        beam_pixels = r2[I_out >= I_threshold]
        beam_waist_m = float(math.sqrt(float(np.max(beam_pixels)))) if len(beam_pixels) > 0 else None

        # Analytic beam waist for comparison (no lens)
        if lens_f is None and ap_r is None:
            w_analytic_m = gaussian_waist_analytic(w0=w0_m, lambda_m=lambda_m, z=z_m)
        else:
            w_analytic_m = None

        Rayleigh_m = math.pi * w0_m ** 2 / lambda_m

        payload: dict[str, Any] = {
            "lambda_um": lambda_um,
            "w0_mm": w0_mm,
            "z_mm": z_mm,
            "grid_N": N,
            "dx_um": dx_um,
            "method_requested": method,
            "method_used": actual_method,
            "fresnel_number": round(NF, 4) if math.isfinite(NF) else None,
            "Rayleigh_range_mm": round(Rayleigh_m * 1e3, 4),
            "intensity_peak": round(I_peak, 8),
            "energy_in": round(float(E_in), 8),
            "energy_out": round(float(E_out), 8),
            "energy_conservation_ratio": round(energy_ratio, 6) if energy_ratio is not None else None,
            "beam_waist_mm": round(beam_waist_m * 1e3, 4) if beam_waist_m is not None else None,
            "beam_waist_analytic_mm": round(w_analytic_m * 1e3, 4) if w_analytic_m is not None else None,
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "POP_ERROR")


# ---------------------------------------------------------------------------
# optics_sequential_trace
# ---------------------------------------------------------------------------

optics_sequential_trace_spec = ToolSpec(
    name="optics_sequential_trace",
    description=(
        "Zemax-style sequential multi-surface paraxial ray trace analysis.\n"
        "\n"
        "Traces rays through an ordered list of optical surfaces (object → image)\n"
        "and returns:\n"
        "  efl_d_mm         — effective focal length at primary wavelength (d-line 587.6 nm) [mm]\n"
        "  efl_per_wavelength — EFL at each traced wavelength (dict: wl_nm → efl_mm)\n"
        "  bfd_mm           — back focal distance [mm]\n"
        "  ffd_mm           — front focal distance [mm]\n"
        "  longitudinal_chromatic_aberration_mm — EFL shift F-line vs C-line [mm]\n"
        "  transverse_chromatic_aberration_mm   — lateral colour [mm]\n"
        "  rms_spot_mm      — paraxial RMS spot radius [mm]\n"
        "  geo_spot_mm      — geometric (max) spot radius [mm]\n"
        "  ee80_mm          — 80% encircled energy radius [mm]\n"
        "  strehl_ratio     — Maréchal approximation\n"
        "  seidel_coefficients — primary W040/W131/W222/W220/W311 aberrations\n"
        "  merit_function   — polychromatic RSS merit (RMS spot across wavelengths)\n"
        "\n"
        "Each surface: {radius_mm, thickness_mm, n_next, semi_diameter_mm, surface_type}\n"
        "surface_type: 'refract' (default) | 'reflect' | 'aperture_stop' | 'image'\n"
        "\n"
        "Paraxial ABCD model — first-order properties are exact; Seidel coefficients\n"
        "are thin-lens approximations.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "required": ["surfaces"],
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surfaces from front to rear.\n"
                    "Each surface: {radius_mm, thickness_mm, n_next, semi_diameter_mm (optional), "
                    "surface_type ('refract'|'reflect'|'aperture_stop'|'image', optional)}"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "radius_mm": {"type": "number", "description": "Radius of curvature [mm]. Use 1e30 for flat."},
                        "thickness_mm": {"type": "number", "description": "Axial distance to next surface [mm]."},
                        "n_next": {"type": "number", "description": "Refractive index of next medium. Default 1.0 (air)."},
                        "semi_diameter_mm": {"type": "number"},
                        "surface_type": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["radius_mm", "thickness_mm"],
                },
                "minItems": 1,
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (before first surface). Default 1.0.",
            },
            "object_distance_mm": {
                "type": "number",
                "description": "Object distance from first surface [mm]. Default 1000.",
            },
            "wavelengths_nm": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Wavelengths to trace [nm]. Default [486.1, 587.6, 656.3].",
            },
            "primary_wavelength_nm": {
                "type": "number",
                "description": "Primary (reference) wavelength [nm]. Default 587.6.",
            },
            "marginal_height_mm": {
                "type": "number",
                "description": "Marginal ray height at first surface [mm]. Default 0.5.",
            },
        },
    },
)


async def run_optics_sequential_trace(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        import math as _math
        from kerf_optics.sequential_trace import (
            SequentialSystem,
            SequentialSurface,
            trace_sequential,
        )

        raw_surfaces = args["surfaces"]
        surfaces = []
        for s in raw_surfaces:
            r = float(s.get("radius_mm", float("inf")))
            if not _math.isfinite(r):
                r = float("inf")
            surfaces.append(SequentialSurface(
                radius=r,
                thickness=float(s.get("thickness_mm", 0.0)),
                n_next=float(s.get("n_next", 1.0)),
                semi_diameter=float(s.get("semi_diameter_mm", float("inf"))),
                surface_type=str(s.get("surface_type", "refract")),
                label=str(s.get("label", "")),
            ))

        system = SequentialSystem(
            surfaces=surfaces,
            n_object=float(args.get("n_object", 1.0)),
        )

        wls = args.get("wavelengths_nm")
        primary = float(args.get("primary_wavelength_nm", 587.6))
        do = float(args.get("object_distance_mm", 1000.0))
        h = float(args.get("marginal_height_mm", 0.5))

        result = trace_sequential(
            system=system,
            wavelengths_nm=wls,
            object_distance_mm=do,
            primary_wavelength_nm=primary,
            marginal_height_mm=h,
        )

        return ok_payload(result.to_dict())

    except Exception as exc:
        return err_payload(str(exc), "SEQUENTIAL_TRACE_ERROR")


# ---------------------------------------------------------------------------
# optics_nest_tolerancing
# ---------------------------------------------------------------------------

optics_nest_tolerancing_spec = ToolSpec(
    name="optics_nest_tolerancing",
    description=(
        "NEST inverse sensitivity tolerancing: allocate per-parameter tolerances "
        "to meet a target RSS merit budget.\n"
        "\n"
        "Given a total RSS merit budget M, finds per-parameter tolerance δ_i such that:\n"
        "  √(Σ_i (s_i · δ_i)²) = M\n"
        "where s_i = |Δmerit / Δparam| (first-order sensitivity).\n"
        "\n"
        "Uses equal-contribution (EC) allocation or custom weights.  This is the\n"
        "'NEST' workflow in Zemax OpticStudio (Smith 2008 §14.3).\n"
        "\n"
        "Returns:\n"
        "  allocated_deltas  — list of δ_i for each parameter\n"
        "  sensitivity       — list of |s_i|\n"
        "  rss_check         — verified RSS (should equal merit_budget)\n"
        "  table             — per-parameter summary sorted by RSS contribution\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "required": ["elements", "tolerances", "merit_budget"],
        "properties": {
            "elements": {
                "type": "array",
                "description": "Lens system elements (same format as optics_trace_ray).",
                "items": {"type": "object"},
                "minItems": 1,
            },
            "tolerances": {
                "type": "array",
                "description": (
                    "List of tolerance parameters. Each: "
                    "{element_index, param_name, delta (finite-diff step), "
                    "nominal (optional), description (optional)}."
                ),
                "items": {"type": "object"},
                "minItems": 1,
            },
            "merit_budget": {
                "type": "number",
                "description": "Target total RSS merit budget (e.g. 0.005 m for 5 mm EFL error).",
            },
            "merit_type": {
                "type": "string",
                "enum": ["efl", "bfd"],
                "description": "Merit function type: 'efl' (default) or 'bfd'.",
            },
            "weights": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Optional per-parameter weight vector (same length as tolerances). "
                    "Larger weight → looser tolerance for that parameter. Default: equal."
                ),
            },
        },
    },
)


async def run_optics_nest_tolerancing(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_optics.lens_system import LensSystem
        from kerf_optics.tolerancing import (
            ToleranceParam,
            nest_tolerancing,
            merit_efl,
            merit_bfd,
        )
        from kerf_optics.tools import _build_element

        elements = [_build_element(e) for e in args["elements"]]
        system = LensSystem(elements)

        raw_tols = args["tolerances"]
        params = []
        for t in raw_tols:
            params.append(ToleranceParam(
                element_index=int(t["element_index"]),
                param_name=str(t["param_name"]),
                nominal=float(t["nominal"]) if "nominal" in t else None,
                delta=float(t.get("delta", 0.0)),
                description=str(t.get("description", "")),
            ))

        merit_type = str(args.get("merit_type", "efl")).lower()
        M = system.system_matrix()
        C = M[1, 0]
        nominal_efl = -1.0 / C if abs(C) > 1e-14 else 1.0
        if merit_type == "efl":
            merit_fn = merit_efl(nominal_efl)
        elif merit_type == "bfd":
            merit_fn = merit_bfd(nominal_efl)
        else:
            return err_payload(f"unknown merit_type: {merit_type!r}", "BAD_ARGS")

        merit_budget = float(args["merit_budget"])
        raw_weights = args.get("weights")
        weights = [float(w) for w in raw_weights] if raw_weights is not None else None

        result = nest_tolerancing(system, params, merit_fn, merit_budget, weights)

        payload: dict[str, Any] = {
            "merit_budget": merit_budget,
            "rss_check": round(result.rss_check, 8),
            "allocated_deltas": [round(d, 8) for d in result.allocated_deltas],
            "sensitivity": [round(s, 8) for s in result.sensitivity],
            "table": [
                {k: (round(v, 8) if isinstance(v, float) else v)
                 for k, v in row.items()}
                for row in result.table()
            ],
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "NEST_ERROR")


# ---------------------------------------------------------------------------
# optics_lighting_simulation
# ---------------------------------------------------------------------------

optics_lighting_simulation_spec = ToolSpec(
    name="optics_lighting_simulation",
    description=(
        "Photometric lighting simulation: compute illuminance (lux), luminous exitance, "
        "and luminance [cd/m²] on receiver surfaces from point light sources.\n"
        "\n"
        "Implements the inverse-square law + Lambert cosine model:\n"
        "  E_v = (I_v / d²) · cos(θ_i)\n"
        "where I_v = luminous intensity [cd] and θ_i = angle of incidence.\n"
        "\n"
        "Source distributions: 'lambertian' (diffuse hemisphere), 'spot' (Phong beam),\n"
        "'isotropic' (omnidirectional sphere).\n"
        "\n"
        "Returns per-surface: illuminance [lux], luminance [cd/m²], luminous flux [lm],\n"
        "uniformity ratio U₀ = E_min/E_avg across all surfaces, and CCT chromaticity.\n"
        "\n"
        "(DiLaura et al. 2011 IES Lighting Handbook §3.3; EN 12464-1:2021 workplane spec)\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "required": ["sources", "surfaces"],
        "properties": {
            "sources": {
                "type": "array",
                "description": "List of light source specifications.",
                "items": {
                    "type": "object",
                    "required": ["source_id", "position", "direction", "luminous_flux_lm"],
                    "properties": {
                        "source_id": {"type": "string"},
                        "position": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "[x, y, z] position [m].",
                        },
                        "direction": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "[dx, dy, dz] emission direction (normalised internally).",
                        },
                        "luminous_flux_lm": {
                            "type": "number",
                            "description": "Total luminous flux [lm]. E.g. 800 for 60W incandescent equivalent.",
                        },
                        "distribution": {
                            "type": "string",
                            "enum": ["lambertian", "spot", "isotropic"],
                            "description": "Spatial distribution. Default 'lambertian'.",
                        },
                        "half_angle_deg": {
                            "type": "number",
                            "description": "Spot half-beam angle [deg]. Relevant for 'spot' only. Default 30.",
                        },
                        "colour_temperature_K": {
                            "type": "number",
                            "description": "CCT [K]. Default 3000.",
                        },
                    },
                },
                "minItems": 1,
            },
            "surfaces": {
                "type": "array",
                "description": "List of receiver surfaces.",
                "items": {
                    "type": "object",
                    "required": ["surface_id", "centre", "normal", "area_m2"],
                    "properties": {
                        "surface_id": {"type": "string"},
                        "centre": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "[x, y, z] centre position [m].",
                        },
                        "normal": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Outward surface normal [dx, dy, dz].",
                        },
                        "area_m2": {
                            "type": "number",
                            "description": "Surface area [m²].",
                        },
                        "reflectance": {
                            "type": "number",
                            "description": "Lambertian reflectance [0, 1]. Default 0.7.",
                        },
                    },
                },
                "minItems": 1,
            },
            "ambient_lux": {
                "type": "number",
                "description": "Background ambient illuminance [lux]. Default 0.",
            },
        },
    },
)


async def run_optics_lighting_simulation(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_optics.lighting import (
            LightSource,
            Surface,
            PhotometricScene,
            compute_illuminance,
            correlated_colour_temperature_to_xy,
            uniformity_ratio,
        )

        # Build sources
        sources = []
        for sd in args["sources"]:
            sources.append(LightSource(
                source_id=str(sd["source_id"]),
                position=sd["position"],
                direction=sd["direction"],
                luminous_flux_lm=float(sd["luminous_flux_lm"]),
                distribution=str(sd.get("distribution", "lambertian")),
                half_angle_deg=float(sd.get("half_angle_deg", 30.0)),
                colour_temperature_K=float(sd.get("colour_temperature_K", 3000.0)),
            ))

        # Build surfaces
        surfaces = []
        for sd in args["surfaces"]:
            surfaces.append(Surface(
                surface_id=str(sd["surface_id"]),
                centre=sd["centre"],
                normal=sd["normal"],
                area_m2=float(sd["area_m2"]),
                reflectance=float(sd.get("reflectance", 0.7)),
            ))

        scene = PhotometricScene(
            sources=sources,
            surfaces=surfaces,
            ambient_lux=float(args.get("ambient_lux", 0.0)),
        )

        results = compute_illuminance(scene)

        # Build per-surface output
        surfaces_out = []
        all_lux = []
        for sid, r in results.items():
            all_lux.append(r.illuminance_lux)
            surfaces_out.append({
                "surface_id": sid,
                "illuminance_lux": round(r.illuminance_lux, 3),
                "luminance_cdpm2": round(r.luminance_cdpm2, 3),
                "luminous_exitance_lmpm2": round(r.luminous_exitance_lmpm2, 3),
                "luminous_flux_received_lm": round(r.luminous_flux_received_lm, 4),
                "contributions": {k: round(v, 3) for k, v in r.contributions.items()},
            })

        # Uniformity ratio
        u0 = uniformity_ratio(all_lux) if len(all_lux) > 1 else 1.0

        # CCT chromaticity for each source
        cct_out = {}
        for src in sources:
            try:
                x, y = correlated_colour_temperature_to_xy(src.colour_temperature_K)
                cct_out[src.source_id] = {
                    "cct_K": src.colour_temperature_K,
                    "cie_x": round(x, 4),
                    "cie_y": round(y, 4),
                }
            except ValueError:
                cct_out[src.source_id] = {"cct_K": src.colour_temperature_K, "cie_x": None, "cie_y": None}

        payload: dict[str, Any] = {
            "surfaces": surfaces_out,
            "uniformity_ratio": round(u0, 4),
            "mean_illuminance_lux": round(sum(all_lux) / len(all_lux), 3) if all_lux else 0.0,
            "min_illuminance_lux": round(min(all_lux), 3) if all_lux else 0.0,
            "max_illuminance_lux": round(max(all_lux), 3) if all_lux else 0.0,
            "source_cct": cct_out,
            "n_sources": len(sources),
            "n_surfaces": len(surfaces),
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "LIGHTING_ERROR")


# ---------------------------------------------------------------------------
# optics_daylighting_simulation
# ---------------------------------------------------------------------------

optics_daylighting_simulation_spec = ToolSpec(
    name="optics_daylighting_simulation",
    description=(
        "Compute daylight illuminance (lux) and daylight factor (DF %) on a grid of "
        "measurement points using CIE S 011 standard sky models (cie_clear, cie_overcast, "
        "cie_intermediate).  Sun position is computed from site latitude/longitude, date, "
        "and time using Spencer's (1971) algorithm.  Direct-beam and sky-diffuse "
        "contributions are both included (two-pass simplified radiosity, Cohen & Wallace 1993).\n"
        "\n"
        "Outputs per measurement point: illuminance_lux.  Summary: average, min, max, "
        "uniformity ratio (Emin/Eavg), daylight factor (DF % = interior_lux / 100,000 × 100, "
        "normalised to CIE standard overcast sky horizontal illuminance of 10,000–25,000 lux).\n"
        "\n"
        "sky_model:  'cie_clear' | 'cie_overcast' | 'cie_intermediate'\n"
        "Grid format: list of [x, y, z] points (metres, world space).\n"
        "\n"
        "References:\n"
        "  CIE S 011/E:2003 — Spatial Distribution of Daylight — CIE Standard General Sky.\n"
        "  Spencer, J.W. (1971). Fourier series representation of the Sun position. Search 2(5):172.\n"
        "  Cohen, M.F. and Wallace, J.R. (1993). Radiosity and Realistic Image Synthesis. §3.\n"
        "  Radiance 5.4 — gensky.c (sky model coefficients reference).\n"
        "Errors: {ok:false, code, message}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "latitude_deg": {
                "type": "number",
                "description": "Site latitude (degrees N, negative = South).  Required.",
            },
            "longitude_deg": {
                "type": "number",
                "description": "Site longitude (degrees E, negative = West).  Required.",
            },
            "date_iso": {
                "type": "string",
                "description": "Date in ISO format 'YYYY-MM-DD'.  Default '2026-06-21' (summer solstice).",
            },
            "time_local": {
                "type": "string",
                "description": "Local solar time 'HH:MM'.  Default '12:00' (solar noon).",
            },
            "timezone_offset_h": {
                "type": "number",
                "description": "UTC offset in hours (e.g. +2 for CEST, -5 for EST).  Default 0.",
            },
            "sky_model": {
                "type": "string",
                "enum": ["cie_clear", "cie_overcast", "cie_intermediate"],
                "description": (
                    "CIE S 011 standard sky model:\n"
                    "  cie_clear        — clear sunny sky (highest direct illuminance)\n"
                    "  cie_overcast     — CIE Standard Overcast Sky (Moon-Spencer)\n"
                    "  cie_intermediate — intermediate between clear and overcast"
                ),
            },
            "measurement_points": {
                "type": "array",
                "description": (
                    "Grid of measurement points [[x1,y1,z1], [x2,y2,z2], ...] in metres.  "
                    "Typically a horizontal work-plane at z=0.85 m (desk height).  "
                    "Maximum 1000 points."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 1,
                "maxItems": 1000,
            },
            "electric_luminaires": {
                "type": "array",
                "description": "Optional supplementary electric luminaires (same format as optics_lighting_simulation sources).",
                "items": {
                    "type": "object",
                    "properties": {
                        "position": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                        "direction": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                        "intensity_cd": {"type": "number", "description": "Luminous intensity [cd]."},
                        "beam_angle_deg": {"type": "number", "description": "Half-beam angle [deg], default 90."},
                    },
                    "required": ["position", "direction", "intensity_cd"],
                },
            },
        },
        "required": ["latitude_deg", "longitude_deg", "measurement_points"],
    },
)


async def run_optics_daylighting_simulation(
    args: "dict[str, Any]", ctx: "ProjectCtx"
) -> str:
    """Tool handler for optics_daylighting_simulation."""
    import sys
    import os as _os

    # Resolve kerf_cad_core.render.luminance_lux_sim — it may not be installed;
    # add all packages/*/src to sys.path for standalone use.
    _tools_dir = _os.path.dirname(_os.path.abspath(__file__))
    _packages_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_tools_dir))))
    for _entry in _os.listdir(_packages_root):
        if _entry.startswith("kerf-"):
            _src = _os.path.join(_packages_root, _entry, "src")
            if _os.path.isdir(_src) and _src not in sys.path:
                sys.path.insert(0, _src)

    try:
        from kerf_cad_core.render.luminance_lux_sim import (
            DaylightConditions,
            ElectricLuminaire,
            compute_daylight_lux,
        )
    except ImportError as exc:
        return err_payload(f"kerf_cad_core not available: {exc}", "IMPORT_ERROR")

    try:
        lat = float(args["latitude_deg"])
        lon = float(args["longitude_deg"])
        pts_raw = args["measurement_points"]
        if len(pts_raw) > 1000:
            return err_payload("measurement_points exceeds maximum of 1000", "BAD_ARGS")
        pts = [list(p) for p in pts_raw]

        sky_model = str(args.get("sky_model", "cie_clear"))
        if sky_model not in ("cie_clear", "cie_overcast", "cie_intermediate"):
            return err_payload(
                f"sky_model must be cie_clear|cie_overcast|cie_intermediate, got '{sky_model}'",
                "BAD_ARGS",
            )

        conditions = DaylightConditions(
            latitude_deg=lat,
            longitude_deg=lon,
            date_iso=str(args.get("date_iso", "2026-06-21")),
            time_local=str(args.get("time_local", "12:00")),
            timezone_offset_h=float(args.get("timezone_offset_h", 0.0)),
            sky_model=sky_model,
        )

        luminaires = []
        for lum_raw in args.get("electric_luminaires", []):
            luminaires.append(ElectricLuminaire(
                position=tuple(float(v) for v in lum_raw["position"]),
                direction=tuple(float(v) for v in lum_raw["direction"]),
                intensity_cd=float(lum_raw["intensity_cd"]),
                beam_angle_deg=float(lum_raw.get("beam_angle_deg", 90.0)),
            ))

        report = compute_daylight_lux(
            scene_geometry=[],
            measurement_points=pts,
            conditions=conditions,
            electric_luminaires=luminaires if luminaires else None,
        )

        # Daylight Factor: normalised to CIE design overcast horizontal illuminance
        # CIBSE Guide A (2015) / BS 8206-2 uses 10,000 lux as reference overcast sky.
        # IES LM-83 uses climate-based methods; for this simplified DF we use 10,000 lux.
        DF_REF_LUX = 10_000.0
        df_percent = round(report.average_lux / DF_REF_LUX * 100.0, 4)

        point_results = [
            {"point": list(p), "illuminance_lux": round(lux, 2), "daylight_factor_pct": round(lux / DF_REF_LUX * 100, 4)}
            for p, lux in zip(report.measurement_points, report.lux_values)
        ]

        payload: "dict[str, Any]" = {
            "sky_model": sky_model,
            "latitude_deg": lat,
            "longitude_deg": lon,
            "date_iso": conditions.date_iso,
            "time_local": conditions.time_local,
            "average_lux": round(report.average_lux, 2),
            "min_lux": round(report.min_lux, 2),
            "max_lux": round(report.max_lux, 2),
            "uniformity_ratio": round(report.uniformity_ratio, 4),
            "mean_daylight_factor_pct": df_percent,
            "n_points": len(pts),
            "points": point_results,
            "reference": (
                "CIE S 011/E:2003 standard sky; Spencer (1971) sun position; "
                "Cohen & Wallace (1993) radiosity; DF ref = 10,000 lux (CIBSE Guide A)."
            ),
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "DAYLIGHTING_ERROR")
