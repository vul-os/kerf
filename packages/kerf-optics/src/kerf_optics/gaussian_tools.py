"""
kerf_optics LLM tools — Gaussian beam propagation (q-parameter).

Registered via plugin.py at startup alongside the paraxial ray-trace tools.

Tools
-----
gaussian_beam_propagate  — propagate a Gaussian beam through an ABCD system
                           and return beam parameters at each plane.
gaussian_beam_focus      — compute focused spot size and fibre coupling
                           efficiency for a given beam + optic configuration.
"""

from __future__ import annotations

import math
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_optics._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# gaussian_beam_propagate
# ---------------------------------------------------------------------------

gaussian_beam_propagate_spec = ToolSpec(
    name="gaussian_beam_propagate",
    description=(
        "Propagate a Gaussian beam through a sequence of optical elements using "
        "the complex beam parameter (q-parameter / ABCD) formalism.  Returns "
        "beam radius w, wavefront radius R, and Rayleigh length at each plane, "
        "plus the waist location and size after propagation.  "
        "Supports free-space gaps, thin lenses, thick lenses, and dielectric "
        "interfaces.  Input beam specified by waist+distance or w+R at the "
        "input plane."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "input_beam": {
                "type": "object",
                "description": (
                    "Input beam specification — one of:\n"
                    "  {mode:'waist', w0:<m>, z:<m>}  — waist radius and distance from waist\n"
                    "  {mode:'w_R',   w:<m>, R:<m>}   — beam radius and wavefront radius "
                    "(use R=1e30 for collimated)"
                ),
                "properties": {
                    "mode": {"type": "string", "enum": ["waist", "w_R"]},
                    "w0": {"type": "number"},
                    "z":  {"type": "number"},
                    "w":  {"type": "number"},
                    "R":  {"type": "number"},
                },
                "required": ["mode"],
            },
            "lambda_nm": {
                "type": "number",
                "description": "Vacuum wavelength in nanometres (e.g. 632.8 for HeNe).",
            },
            "n": {
                "type": "number",
                "description": "Refractive index of the surrounding medium (default 1.0).",
            },
            "elements": {
                "type": "array",
                "description": (
                    "Ordered list of optical elements:\n"
                    "  {type:'free_space', d:<m>}\n"
                    "  {type:'thin_lens',  f:<m>}\n"
                    "  {type:'thick_lens', f:<m>, d:<m>, n_lens:<index, default 1.5>}\n"
                    "  {type:'planar_interface', n1:<from>, n2:<to>}\n"
                    "  {type:'curved_interface', R:<m>, n1:<from>, n2:<to>}"
                ),
                "items": {"type": "object"},
                "minItems": 1,
            },
        },
        "required": ["input_beam", "lambda_nm", "elements"],
    },
)


def _build_gaussian_element(spec: dict):
    """Return a (label, M) tuple for a Gaussian ABCD element."""
    from kerf_optics.gaussian import (
        M_gaussian_free, M_gaussian_thin_lens, M_gaussian_thick_lens,
        M_gaussian_planar_interface, M_gaussian_curved_interface,
    )
    etype = spec.get("type", "").lower()
    if etype == "free_space":
        d = float(spec["d"])
        return (f"free_space d={d:.4g} m", M_gaussian_free(d))
    elif etype == "thin_lens":
        f = float(spec["f"])
        return (f"thin_lens f={f:.4g} m", M_gaussian_thin_lens(f))
    elif etype == "thick_lens":
        f = float(spec["f"])
        d = float(spec["d"])
        n_lens = float(spec.get("n_lens", 1.5))
        return (f"thick_lens f={f:.4g} m d={d:.4g} m", M_gaussian_thick_lens(f, d, n_lens))
    elif etype == "planar_interface":
        n1, n2 = float(spec["n1"]), float(spec["n2"])
        return (f"planar_interface {n1}→{n2}", M_gaussian_planar_interface(n1, n2))
    elif etype == "curved_interface":
        R = float(spec["R"])
        n1, n2 = float(spec["n1"]), float(spec["n2"])
        return (f"curved_interface R={R:.4g} {n1}→{n2}", M_gaussian_curved_interface(R, n1, n2))
    else:
        raise ValueError(f"unknown Gaussian element type: {spec.get('type')!r}")


async def run_gaussian_beam_propagate(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_optics.gaussian import (
            q_from_waist_and_distance, q_from_w_R,
            propagate_q, beam_radius, wavefront_radius,
            beam_waist_from_q, rayleigh_length,
        )
        import numpy as np

        lambda_nm = float(args["lambda_nm"])
        n = float(args.get("n", 1.0))

        # Build initial q
        ib = args["input_beam"]
        mode = ib["mode"]
        if mode == "waist":
            w0 = float(ib["w0"])
            z  = float(ib.get("z", 0.0))
            q = q_from_waist_and_distance(w0, z, lambda_nm, n)
        elif mode == "w_R":
            w = float(ib["w"])
            R = float(ib.get("R", math.inf))
            q = q_from_w_R(w, R, lambda_nm, n)
        else:
            return err_payload(f"unknown input_beam mode: {mode!r}", "BAD_ARGS")

        elements = [_build_gaussian_element(e) for e in args["elements"]]

        planes = []
        q_cur = q

        def _plane_info(label, q_val):
            w = beam_radius(q_val, lambda_nm, n)
            R = wavefront_radius(q_val)
            wr = beam_waist_from_q(q_val, lambda_nm, n)
            return {
                "label": label,
                "w_m": round(w, 12),
                "w_um": round(w * 1e6, 6),
                "R_m": round(R, 6) if not math.isinf(R) else None,
                "zR_m": round(wr.zR, 6),
                "w0_m": round(wr.w0, 12),
                "w0_um": round(wr.w0 * 1e6, 6),
                "z_from_waist_m": round(wr.z, 6),
            }

        planes.append(_plane_info("input", q_cur))

        for label, M in elements:
            q_cur = propagate_q(q_cur, M)
            planes.append(_plane_info(label, q_cur))

        return ok_payload({"lambda_nm": lambda_nm, "n": n, "planes": planes})

    except Exception as exc:
        return err_payload(str(exc), "GAUSSIAN_ERROR")


# ---------------------------------------------------------------------------
# gaussian_beam_focus
# ---------------------------------------------------------------------------

gaussian_beam_focus_spec = ToolSpec(
    name="gaussian_beam_focus",
    description=(
        "Compute focused spot size and fibre coupling efficiency for a Gaussian "
        "beam passed through a thin focusing lens.  Returns the 1/e² spot "
        "radius at the focal plane, the Rayleigh length there, and the coupling "
        "efficiency into a single-mode fibre (optional)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "w_in": {
                "type": "number",
                "description": "Input beam 1/e² radius at the lens (metres).",
            },
            "f": {
                "type": "number",
                "description": "Lens focal length (metres).",
            },
            "lambda_nm": {
                "type": "number",
                "description": "Vacuum wavelength (nm).",
            },
            "M2": {
                "type": "number",
                "description": "Beam quality factor (default 1.0).",
            },
            "n": {
                "type": "number",
                "description": "Refractive index (default 1.0).",
            },
            "fibre_MFD_um": {
                "type": "number",
                "description": "(Optional) Fibre mode field diameter in µm for coupling calc.",
            },
            "misalignment_um": {
                "type": "number",
                "description": "(Optional) Lateral misalignment in µm (default 0).",
            },
            "theta_misalign_mrad": {
                "type": "number",
                "description": "(Optional) Angular tilt misalignment in mrad (default 0).",
            },
        },
        "required": ["w_in", "f", "lambda_nm"],
    },
)


async def run_gaussian_beam_focus(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_optics.gaussian import (
            q_from_w_R, M_gaussian_thin_lens, M_gaussian_free,
            propagate_q, beam_radius, beam_waist_from_q, rayleigh_length,
            fibre_coupling_efficiency,
        )
        import numpy as np

        w_in = float(args["w_in"])
        f = float(args["f"])
        lambda_nm = float(args["lambda_nm"])
        M2 = float(args.get("M2", 1.0))
        n = float(args.get("n", 1.0))

        lam = lambda_nm * 1e-9

        # Input beam: collimated (R=inf) at the lens
        q_in = q_from_w_R(w_in, math.inf, lambda_nm, n)

        # Pass through thin lens
        M_lens = M_gaussian_thin_lens(f)
        q_after_lens = propagate_q(q_in, M_lens)

        # Propagate to waist (focal plane for collimated input ≈ f)
        wr = beam_waist_from_q(q_after_lens, lambda_nm, n)
        # Distance to waist from lens: wr.z is negative (beam converging), waist at |wr.z|
        d_to_waist = abs(wr.z)
        M_prop = M_gaussian_free(d_to_waist)
        q_at_waist = propagate_q(q_after_lens, M_prop)

        w0_ideal = beam_radius(q_at_waist, lambda_nm, n)
        zR_at_waist = rayleigh_length(w0_ideal, lambda_nm, n)

        # M²-scaled real spot
        w0_real = w0_ideal * math.sqrt(M2)
        zR_real = zR_at_waist / M2

        # Paraxial approximation for comparison
        w0_paraxial = lam * f / (math.pi * w_in)

        payload: dict[str, Any] = {
            "input_beam_radius_m": w_in,
            "focal_length_m": f,
            "lambda_nm": lambda_nm,
            "M2": M2,
            "distance_to_waist_m": round(d_to_waist, 8),
            "w0_ideal_m": round(w0_ideal, 12),
            "w0_ideal_um": round(w0_ideal * 1e6, 6),
            "w0_real_m": round(w0_real, 12),
            "w0_real_um": round(w0_real * 1e6, 6),
            "w0_paraxial_um": round(w0_paraxial * 1e6, 6),
            "zR_ideal_m": round(zR_at_waist, 8),
            "zR_real_m": round(zR_real, 8),
        }

        if "fibre_MFD_um" in args:
            fibre_MFD = float(args["fibre_MFD_um"]) * 1e-6  # m
            d_lat = float(args.get("misalignment_um", 0.0))
            theta_ang = float(args.get("theta_misalign_mrad", 0.0))
            eta = fibre_coupling_efficiency(
                w_beam=w0_real,
                w_fibre_MFD=fibre_MFD,
                misalignment_um=d_lat,
                theta_misalign_mrad=theta_ang,
                lambda_nm=lambda_nm,
            )
            payload["fibre_coupling_efficiency"] = round(eta, 6)
            payload["fibre_MFD_um"] = float(args["fibre_MFD_um"])

        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "GAUSSIAN_FOCUS_ERROR")
