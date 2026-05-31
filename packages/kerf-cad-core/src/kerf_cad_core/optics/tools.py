"""
kerf_cad_core.optics.tools — LLM tool wrappers for geometric optics & lens design.

Registers tools with the Kerf tool registry:

  optics_lensmaker          — lensmaker's equation (thin & thick lens)
  optics_thin_lens_imaging  — Gaussian thin-lens imaging
  optics_mirror_imaging     — spherical mirror imaging
  optics_two_lens_system    — two-lens effective focal length
  optics_abcd_system        — ABCD ray-transfer matrix cascade
  optics_fnumber            — F-number
  optics_numerical_aperture — numerical aperture
  optics_depth_of_field     — depth of field + hyperfocal
  optics_airy_spot          — diffraction-limited Airy disk radius
  optics_snell              — Snell refraction + TIR detection
  optics_critical_angle     — critical angle for TIR
  optics_brewster_angle     — Brewster's polarisation angle
  optics_prism_deviation    — prism deviation angle
  optics_chromatic_aberration — longitudinal chromatic aberration (Abbe)
  optics_achromat_powers    — achromatic doublet element powers
  optics_compute_spot_diagram — fan-of-rays spot diagram; RMS + EE80 radius; SVG

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Hecht, E. — "Optics", 5th ed. (2017)
Smith, W.J. — "Modern Optical Engineering", 4th ed. (2008)

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.optics.lens_stack_trace import (
    paraxial_properties,
    trace_lens_stack,
)
from kerf_cad_core.optics.mtf_across_field import (
    mtf_at_field,
    mtf_curves_across_field,
)
from kerf_cad_core.optics.lens import (
    lensmaker,
    thin_lens_imaging,
    mirror_imaging,
    two_lens_system,
    abcd_free_space,
    abcd_refraction,
    abcd_thin_lens,
    abcd_thick_lens,
    abcd_mirror,
    abcd_system,
    fnumber,
    numerical_aperture,
    depth_of_field,
    hyperfocal_distance,
    airy_spot_radius,
    snell,
    critical_angle,
    brewster_angle,
    prism_deviation,
    chromatic_aberration,
    achromat_powers,
)


# ---------------------------------------------------------------------------
# Tool: optics_lensmaker
# ---------------------------------------------------------------------------

_lensmaker_spec = ToolSpec(
    name="optics_lensmaker",
    description=(
        "Compute the focal length of a lens using the lensmaker's equation.\n"
        "\n"
        "Thin lens (d=0, default):  1/f = (n-1)*(1/R1 - 1/R2)\n"
        "Thick lens (d > 0):        1/f = (n-1)*[1/R1 - 1/R2 + (n-1)*d/(n*R1*R2)]\n"
        "\n"
        "Sign convention (Cartesian): R > 0 if centre of curvature is to the right.\n"
        "Use R = 1e18 (effectively infinity) for a flat surface.\n"
        "\n"
        "Returns focal length f_m (m), optical power (dioptres), and lens_type.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "R1": {
                "type": "number",
                "description": "Radius of curvature of the first surface (m). Non-zero.",
            },
            "R2": {
                "type": "number",
                "description": "Radius of curvature of the second surface (m). Non-zero.",
            },
            "n": {
                "type": "number",
                "description": "Refractive index of lens material (>= 1.0).",
            },
            "d": {
                "type": "number",
                "description": "Centre thickness (m). 0 for thin-lens approximation (default).",
            },
        },
        "required": ["R1", "R2", "n"],
    },
)


@register(_lensmaker_spec, write=False)
async def run_lensmaker(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("R1", "R2", "n"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "d" in a:
        kwargs["d"] = a["d"]

    result = lensmaker(a["R1"], a["R2"], a["n"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_thin_lens_imaging
# ---------------------------------------------------------------------------

_thin_lens_imaging_spec = ToolSpec(
    name="optics_thin_lens_imaging",
    description=(
        "Thin-lens Gaussian imaging formula: image distance and magnification.\n"
        "\n"
        "  1/s_i = 1/f - 1/s_o      m = -s_i / s_o\n"
        "\n"
        "Returns s_i_m (image distance, m), magnification, image_type "
        "('real' or 'virtual'), and erect (True if upright).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "f": {
                "type": "number",
                "description": "Focal length (m). Negative for diverging lens.",
            },
            "s_o": {
                "type": "number",
                "description": "Object distance (m). Positive for real object.",
            },
        },
        "required": ["f", "s_o"],
    },
)


@register(_thin_lens_imaging_spec, write=False)
async def run_thin_lens_imaging(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("f", "s_o"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = thin_lens_imaging(a["f"], a["s_o"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_mirror_imaging
# ---------------------------------------------------------------------------

_mirror_imaging_spec = ToolSpec(
    name="optics_mirror_imaging",
    description=(
        "Spherical mirror imaging formula.\n"
        "\n"
        "  f = R/2     1/s_i + 1/s_o = 2/R     m = -s_i / s_o\n"
        "\n"
        "Sign convention: R > 0 = concave (converging), R < 0 = convex (diverging).\n"
        "Returns s_i_m, magnification, f_m, mirror_type, image_type, erect.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "R": {
                "type": "number",
                "description": "Radius of curvature (m). Non-zero. Positive = concave.",
            },
            "s_o": {
                "type": "number",
                "description": "Object distance (m). Positive = real object.",
            },
        },
        "required": ["R", "s_o"],
    },
)


@register(_mirror_imaging_spec, write=False)
async def run_mirror_imaging(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("R", "s_o"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = mirror_imaging(a["R"], a["s_o"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_two_lens_system
# ---------------------------------------------------------------------------

_two_lens_system_spec = ToolSpec(
    name="optics_two_lens_system",
    description=(
        "Two thin-lens system: effective focal length and principal-plane positions.\n"
        "\n"
        "  1/f_eff = 1/f1 + 1/f2 - d/(f1*f2)\n"
        "\n"
        "Returns f_eff_m, combined power (dioptres), delta_H_m (front principal "
        "plane from L1), delta_H_prime_m (rear principal plane from L2).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "f1": {
                "type": "number",
                "description": "Focal length of first lens (m). Non-zero.",
            },
            "f2": {
                "type": "number",
                "description": "Focal length of second lens (m). Non-zero.",
            },
            "d": {
                "type": "number",
                "description": "Separation between the two lenses (m). Must be >= 0.",
            },
        },
        "required": ["f1", "f2", "d"],
    },
)


@register(_two_lens_system_spec, write=False)
async def run_two_lens_system(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("f1", "f2", "d"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = two_lens_system(a["f1"], a["f2"], a["d"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_abcd_system
# ---------------------------------------------------------------------------

_abcd_system_spec = ToolSpec(
    name="optics_abcd_system",
    description=(
        "Cascade a list of ABCD ray-transfer matrices into the system matrix.\n"
        "\n"
        "Supported element types (pass as list of objects in 'elements'):\n"
        "  {\"type\": \"free_space\", \"d\": <m>}\n"
        "  {\"type\": \"thin_lens\", \"f\": <m>}\n"
        "  {\"type\": \"mirror\", \"R\": <m>}\n"
        "  {\"type\": \"refraction\", \"n1\": <>, \"n2\": <>, \"R\": <m>}\n"
        "\n"
        "Elements are listed in the order the ray encounters them (left to right).\n"
        "Returns A, B, C, D of the system matrix.\n"
        "\n"
        "Errors: {ok:false, reason} for unknown element type or invalid inputs.  "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": (
                    "List of optical element objects, each with a 'type' field "
                    "and corresponding parameters."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["elements"],
    },
)


@register(_abcd_system_spec, write=False)
async def run_abcd_system(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    elements = a.get("elements")
    if elements is None:
        return json.dumps({"ok": False, "reason": "elements is required"})
    if not isinstance(elements, list) or len(elements) == 0:
        return json.dumps({"ok": False, "reason": "elements must be a non-empty list"})

    matrices = []
    for i, elem in enumerate(elements):
        if not isinstance(elem, dict):
            return json.dumps({"ok": False, "reason": f"element[{i}] must be an object"})
        etype = elem.get("type", "")
        if etype == "free_space":
            m = abcd_free_space(elem.get("d", 0))
        elif etype == "thin_lens":
            m = abcd_thin_lens(elem.get("f", 0))
        elif etype == "mirror":
            m = abcd_mirror(elem.get("R", 0))
        elif etype == "refraction":
            m = abcd_refraction(
                elem.get("n1", 1), elem.get("n2", 1), elem.get("R", 1e18)
            )
        else:
            return json.dumps({
                "ok": False,
                "reason": f"element[{i}] unknown type {etype!r}; "
                          "supported: free_space, thin_lens, mirror, refraction",
            })
        if not m.get("ok"):
            return json.dumps({"ok": False, "reason": f"element[{i}]: {m.get('reason')}"})
        matrices.append(m)

    # Cascade in ray-encounter order: last element first in matrix list
    result = abcd_system(list(reversed(matrices)))
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_fnumber
# ---------------------------------------------------------------------------

_fnumber_spec = ToolSpec(
    name="optics_fnumber",
    description=(
        "Compute the F-number (f/#) of a lens.\n"
        "\n"
        "  N = f / D\n"
        "\n"
        "Parameters: f (focal length, m), D (entrance-pupil diameter, m).\n"
        "Returns f_number, f_m, D_m.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "f": {"type": "number", "description": "Focal length (m). Must be > 0."},
            "D": {"type": "number", "description": "Entrance-pupil diameter (m). Must be > 0."},
        },
        "required": ["f", "D"],
    },
)


@register(_fnumber_spec, write=False)
async def run_fnumber(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("f", "D"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = fnumber(a["f"], a["D"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_numerical_aperture
# ---------------------------------------------------------------------------

_numerical_aperture_spec = ToolSpec(
    name="optics_numerical_aperture",
    description=(
        "Compute the numerical aperture NA = n * sin(θ).\n"
        "\n"
        "Parameters: n (refractive index >= 1), half_angle_rad (acceptance half-angle, rad).\n"
        "Returns NA, n, half_angle_rad.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n": {"type": "number", "description": "Refractive index of medium (>= 1)."},
            "half_angle_rad": {
                "type": "number",
                "description": "Half-angle of acceptance cone (rad). [0, π/2].",
            },
        },
        "required": ["n", "half_angle_rad"],
    },
)


@register(_numerical_aperture_spec, write=False)
async def run_numerical_aperture(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("n", "half_angle_rad"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = numerical_aperture(a["n"], a["half_angle_rad"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_depth_of_field
# ---------------------------------------------------------------------------

_depth_of_field_spec = ToolSpec(
    name="optics_depth_of_field",
    description=(
        "Compute depth of field (DOF) and hyperfocal distance for a camera lens.\n"
        "\n"
        "  H = f² / (N * c)     (hyperfocal distance)\n"
        "  DOF_near = s_o*(H-f)/(H+s_o-2f)\n"
        "  DOF_far  = s_o*(H-f)/(H-s_o)   [∞ if s_o >= H]\n"
        "\n"
        "Returns DOF_total_m, DOF_near_m, DOF_far_m, hyperfocal_m.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "f": {"type": "number", "description": "Focal length (m). Must be > 0."},
            "N": {"type": "number", "description": "F-number. Must be > 0."},
            "c": {"type": "number", "description": "Circle of confusion diameter (m). Must be > 0."},
            "s_o": {"type": "number", "description": "Subject distance from lens (m). Must be > 0."},
        },
        "required": ["f", "N", "c", "s_o"],
    },
)


@register(_depth_of_field_spec, write=False)
async def run_depth_of_field(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("f", "N", "c", "s_o"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = depth_of_field(a["f"], a["N"], a["c"], a["s_o"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_airy_spot
# ---------------------------------------------------------------------------

_airy_spot_spec = ToolSpec(
    name="optics_airy_spot",
    description=(
        "Compute the diffraction-limited Airy disk radius (first dark ring).\n"
        "\n"
        "  r_Airy = 1.22 * λ * N\n"
        "\n"
        "Parameters: wavelength (m), N (F-number).\n"
        "Returns r_airy_m, diameter_m.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wavelength": {
                "type": "number",
                "description": "Wavelength of light (m). E.g. 550e-9 for green light.",
            },
            "N": {"type": "number", "description": "F-number. Must be > 0."},
        },
        "required": ["wavelength", "N"],
    },
)


@register(_airy_spot_spec, write=False)
async def run_airy_spot(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("wavelength", "N"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = airy_spot_radius(a["wavelength"], a["N"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_snell
# ---------------------------------------------------------------------------

_snell_spec = ToolSpec(
    name="optics_snell",
    description=(
        "Apply Snell's law of refraction: n1*sin(θ1) = n2*sin(θ2).\n"
        "\n"
        "Returns theta2_rad and tir=True when total internal reflection occurs "
        "(theta2_rad = NaN on TIR).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n1": {"type": "number", "description": "Refractive index of incident medium (>= 1)."},
            "theta1_rad": {"type": "number", "description": "Angle of incidence (rad). [0, π/2]."},
            "n2": {"type": "number", "description": "Refractive index of transmitted medium (>= 1)."},
        },
        "required": ["n1", "theta1_rad", "n2"],
    },
)


@register(_snell_spec, write=False)
async def run_snell(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("n1", "theta1_rad", "n2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = snell(a["n1"], a["theta1_rad"], a["n2"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_critical_angle
# ---------------------------------------------------------------------------

_critical_angle_spec = ToolSpec(
    name="optics_critical_angle",
    description=(
        "Compute the critical angle for total internal reflection.\n"
        "\n"
        "  θ_c = arcsin(n2 / n1)    [requires n1 > n2]\n"
        "\n"
        "Returns theta_c_rad, theta_c_deg, tir_possible.\n"
        "Sets tir_possible=False (with a warning) if n1 <= n2.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n1": {"type": "number", "description": "Refractive index of denser medium (>= 1)."},
            "n2": {"type": "number", "description": "Refractive index of less-dense medium (>= 1)."},
        },
        "required": ["n1", "n2"],
    },
)


@register(_critical_angle_spec, write=False)
async def run_critical_angle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("n1", "n2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = critical_angle(a["n1"], a["n2"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_brewster_angle
# ---------------------------------------------------------------------------

_brewster_angle_spec = ToolSpec(
    name="optics_brewster_angle",
    description=(
        "Compute Brewster's angle (polarisation angle).\n"
        "\n"
        "  θ_B = arctan(n2 / n1)\n"
        "\n"
        "At this angle, p-polarised (TM) light is not reflected.\n"
        "Returns theta_B_rad, theta_B_deg.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n1": {"type": "number", "description": "Refractive index of incident medium (>= 1)."},
            "n2": {"type": "number", "description": "Refractive index of transmitted medium (>= 1)."},
        },
        "required": ["n1", "n2"],
    },
)


@register(_brewster_angle_spec, write=False)
async def run_brewster_angle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("n1", "n2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = brewster_angle(a["n1"], a["n2"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_prism_deviation
# ---------------------------------------------------------------------------

_prism_deviation_spec = ToolSpec(
    name="optics_prism_deviation",
    description=(
        "Compute the deviation angle for a ray through a prism.\n"
        "\n"
        "Uses exact Snell's law at both surfaces. Returns delta_rad, delta_deg.\n"
        "Sets tir=True and delta=NaN if total internal reflection occurs at either surface.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n": {"type": "number", "description": "Refractive index of prism material (>= 1)."},
            "apex_rad": {
                "type": "number",
                "description": "Apex angle of prism (rad). Range: (0, π/2].",
            },
            "theta_i_rad": {
                "type": "number",
                "description": "Angle of incidence at first surface (rad). [0, π/2).",
            },
        },
        "required": ["n", "apex_rad", "theta_i_rad"],
    },
)


@register(_prism_deviation_spec, write=False)
async def run_prism_deviation(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("n", "apex_rad", "theta_i_rad"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = prism_deviation(a["n"], a["apex_rad"], a["theta_i_rad"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_chromatic_aberration
# ---------------------------------------------------------------------------

_chromatic_aberration_spec = ToolSpec(
    name="optics_chromatic_aberration",
    description=(
        "Compute longitudinal chromatic aberration (LCA) using the Abbe number.\n"
        "\n"
        "  LCA = f / V\n"
        "\n"
        "where V = (n_d - 1) / (n_F - n_C) is the Abbe V-number.\n"
        "Typical values: crown glass V≈64, flint glass V≈36.\n"
        "\n"
        "Returns LCA_m (m), f_m, V.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "f": {"type": "number", "description": "Focal length (m). Non-zero."},
            "V": {"type": "number", "description": "Abbe V-number. Must be > 0."},
        },
        "required": ["f", "V"],
    },
)


@register(_chromatic_aberration_spec, write=False)
async def run_chromatic_aberration(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("f", "V"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = chromatic_aberration(a["f"], a["V"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_achromat_powers
# ---------------------------------------------------------------------------

_achromat_powers_spec = ToolSpec(
    name="optics_achromat_powers",
    description=(
        "Compute crown/flint element powers for an achromatic doublet.\n"
        "\n"
        "Achromatic condition:\n"
        "  phi1/V1 + phi2/V2 = 0    with phi1 + phi2 = 1/f_total\n"
        "\n"
        "  phi1 = phi_total * V1 / (V1 - V2)\n"
        "  phi2 = -phi_total * V2 / (V1 - V2)\n"
        "\n"
        "Typical: V1 = crown (~64), V2 = flint (~36).\n"
        "Returns phi1_m, phi2_m, f1_m, f2_m.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "f_total": {
                "type": "number",
                "description": "Target combined focal length (m). Non-zero.",
            },
            "V1": {
                "type": "number",
                "description": "Abbe number of first (crown) element. Must be > 0.",
            },
            "V2": {
                "type": "number",
                "description": "Abbe number of second (flint) element. Must be > 0. Must differ from V1.",
            },
        },
        "required": ["f_total", "V1", "V2"],
    },
)


@register(_achromat_powers_spec, write=False)
async def run_achromat_powers(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("f_total", "V1", "V2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = achromat_powers(a["f_total"], a["V1"], a["V2"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_ray_trace_lens_stack
# ---------------------------------------------------------------------------

_ray_trace_lens_stack_spec = ToolSpec(
    name="optics_ray_trace_lens_stack",
    description=(
        "Sequential paraxial + meridional ray trace through a multi-element lens stack.\n"
        "\n"
        "Traces a single ray (specified by height and angle at the first surface) through\n"
        "an ordered list of optical surfaces using:\n"
        "  * Paraxial refraction (Welford 1986 §3.3, nu-form).\n"
        "  * Exact meridional Snell's law + Newton-Raphson conic intersect\n"
        "    (Welford 1986 §5.2-5.3).\n"
        "\n"
        "Also computes system paraxial properties (EFL, BFL, FFL).\n"
        "\n"
        "NOTE v1 scope: ray heights + angles at each surface; EFL / BFL / FFL.\n"
        "OUT OF SCOPE: Seidel aberration coefficients, polychromatic traces,\n"
        "vignetting, skew rays.\n"
        "\n"
        "Surface definition (each element of 'surfaces' array):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface.\n"
        "  k  : conic constant (default 0 = sphere).\n"
        "\n"
        "Oracle: biconvex BK7 (n=1.5168, R1=+50 mm, R2=-50 mm, t=5 mm) => EFL ~48.4 mm\n"
        "(Hecht 'Optics' 5e §6.4 thick-lens formula).\n"
        "\n"
        "Returns paraxial_surfaces, meridional_surfaces (per-surface Y/L/M),\n"
        "paraxial_image_distance_mm, meridional_image_Y_mm, EFL_mm, BFL_mm, FFL_mm.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {
                            "type": "number",
                            "description": "Curvature 1/R (mm^-1). 0 = flat.",
                        },
                        "t": {
                            "type": "number",
                            "description": "Thickness to next surface (mm).",
                        },
                        "n": {
                            "type": "number",
                            "description": "Refractive index after surface (>= 1.0).",
                        },
                        "k": {
                            "type": "number",
                            "description": "Conic constant (default 0 = sphere).",
                        },
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "ray_h": {
                "type": "number",
                "description": "Ray height at first surface (mm).",
            },
            "ray_u": {
                "type": "number",
                "description": "Ray angle in object space (rad). Small for paraxial.",
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces", "ray_h", "ray_u"],
    },
)


@register(_ray_trace_lens_stack_spec, write=False)
async def run_ray_trace_lens_stack(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})
    if a.get("ray_h") is None:
        return json.dumps({"ok": False, "reason": "ray_h is required"})
    if a.get("ray_u") is None:
        return json.dumps({"ok": False, "reason": "ray_u is required"})

    n_object = a.get("n_object", 1.0)

    trace_result = trace_lens_stack(
        a["surfaces"], a["ray_h"], a["ray_u"], n_object=n_object
    )
    if not trace_result.get("ok"):
        return json.dumps(trace_result)

    props_result = paraxial_properties(a["surfaces"], n_object=n_object)

    combined = dict(trace_result)
    if props_result.get("ok"):
        combined["EFL_mm"] = props_result["EFL_mm"]
        combined["BFL_mm"] = props_result["BFL_mm"]
        combined["FFL_mm"] = props_result["FFL_mm"]
        combined["power_mm_inv"] = props_result["power_mm_inv"]
    else:
        combined["paraxial_properties_error"] = props_result.get("reason")

    return ok_payload(combined)


# ---------------------------------------------------------------------------
# Tool: optics_mtf_across_field
# ---------------------------------------------------------------------------

_mtf_across_field_spec = ToolSpec(
    name="optics_mtf_across_field",
    description=(
        "Compute the tangential Modulation Transfer Function (MTF) as a function of\n"
        "field angle (off-axis position) for a multi-element lens stack.\n"
        "\n"
        "Algorithm (Hecht 'Optics' 5e SS11.2; Welford 1986 SS11.4):\n"
        "  1. Trace a uniform aperture bundle from a point source at infinity at each\n"
        "     field angle through the lens stack using exact meridional Snell traces.\n"
        "  2. Histogram ray-intercept Y positions at the paraxial image plane -> line-PSF.\n"
        "  3. FFT(PSF) -> MTF;  MTF[0] is normalised to 1.0.\n"
        "\n"
        "Honest limits:\n"
        "  * Monochromatic only. Polychromatic MTF requires integrating MTF(lambda)\n"
        "    weighted by the spectral power density -- out of scope.\n"
        "  * Tangential plane only; sagittal MTF is not computed.\n"
        "  * Wavefront-based MTF (Strehl / OTF phase) is out of scope.\n"
        "\n"
        "Surface definition (same as optics_ray_trace_lens_stack):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface.\n"
        "  k  : conic constant (default 0 = sphere).\n"
        "\n"
        "Pass field_angles_deg as a list (e.g. [0, 5, 10, 14]) to get MTF curves for\n"
        "all angles in a single call.\n"
        "\n"
        "Returns for each field angle:\n"
        "  frequencies_lp_per_mm : spatial frequency axis (lp/mm)\n"
        "  mtf                   : MTF values in [0, 1]\n"
        "  psf_bins_mm / psf     : line-PSF histogram\n"
        "  n_rays_traced / n_rays_vignetted\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number", "description": "Curvature 1/R (mm^-1). 0 = flat."},
                        "t": {"type": "number", "description": "Thickness to next surface (mm)."},
                        "n": {"type": "number", "description": "Refractive index after surface (>= 1.0)."},
                        "k": {"type": "number", "description": "Conic constant (default 0 = sphere)."},
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "field_angles_deg": {
                "type": "array",
                "description": (
                    "List of field angles in degrees (e.g. [0, 5, 10, 14]). "
                    "0 = on-axis. Ordering is preserved in the output."
                ),
                "items": {"type": "number"},
            },
            "samples_per_aperture": {
                "type": "integer",
                "description": (
                    "Number of rays sampled across the entrance-pupil diameter (default 50). "
                    "More rays give a smoother PSF and finer MTF sampling."
                ),
            },
            "aperture_radius_mm": {
                "type": "number",
                "description": (
                    "Half-diameter of the entrance pupil in mm (default 10 mm). "
                    "Should be <= the physical clear aperture of the first surface."
                ),
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces", "field_angles_deg"],
    },
)


@register(_mtf_across_field_spec, write=False)
async def run_mtf_across_field(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})
    if a.get("field_angles_deg") is None:
        return json.dumps({"ok": False, "reason": "field_angles_deg is required"})

    kwargs: dict = {}
    if "samples_per_aperture" in a:
        kwargs["samples_per_aperture"] = int(a["samples_per_aperture"])
    if "aperture_radius_mm" in a:
        kwargs["aperture_radius_mm"] = float(a["aperture_radius_mm"])
    if "n_object" in a:
        kwargs["n_object"] = float(a["n_object"])

    result = mtf_curves_across_field(
        a["surfaces"],
        a["field_angles_deg"],
        **kwargs,
    )
    return ok_payload(result)

from kerf_cad_core.optics.seidel_aberrations import seidel_coefficients  # noqa: E402
from kerf_cad_core.optics.chief_ray_vignetting import compute_vignetting  # noqa: E402
from kerf_cad_core.optics.pupil_diagram import compute_pupil_diagram  # noqa: E402
from kerf_cad_core.optics.defocus_curve import compute_defocus_curve  # noqa: E402
from kerf_cad_core.optics.distortion_map import compute_distortion_map  # noqa: E402

# Tool: optics_seidel_aberrations
# ---------------------------------------------------------------------------

_seidel_aberrations_spec = ToolSpec(
    name="optics_seidel_aberrations",
    description=(
        "Compute the five Seidel third-order aberration coefficients (S_I-S_V)\n"
        "for a sequential lens stack via dual paraxial-ray trace.\n"
        "\n"
        "Theory (Welford 1986 §6.2 / Born & Wolf §5.3):\n"
        "  Traces a *marginal ray* (full aperture, on-axis) and a *chief ray*\n"
        "  (zero height at stop, full field angle) through all surfaces.\n"
        "  Per-surface contributions are summed:\n"
        "\n"
        "    S_I   = -A^2    * h * delta(u/n)   [spherical aberration]\n"
        "    S_II  = -A*Abar * h * delta(u/n)   [coma]\n"
        "    S_III = -Abar^2 * h * delta(u/n)   [astigmatism]\n"
        "    S_IV  = -H^2    * delta(c/n)        [Petzval field curvature]\n"
        "    S_V   = (S_III + S_IV) * Abar/A    [distortion]\n"
        "\n"
        "  where A = n*i (marginal refraction invariant), Abar = n*ibar (chief),\n"
        "  H = Lagrange invariant (n*u*ybar - n*ubar*y), constant across surfaces.\n"
        "\n"
        "  Positive S_I = under-corrected spherical aberration (converging singlet).\n"
        "\n"
        "HONEST FLAG: Third-order only. Higher-order aberrations require Hopkins\n"
        "exact finite-ray OPD. Monochromatic; chromatic aberrations excluded.\n"
        "Stop assumed at first surface (entrance pupil = front surface).\n"
        "\n"
        "Surface definition (each element of 'surfaces' array):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface.\n"
        "  k  : conic constant (default 0 = sphere, unused for paraxial Seidel).\n"
        "\n"
        "Returns S_I, S_II, S_III, S_IV, S_V, H_lagrange, per_surface contributions,\n"
        "and total_wavefront_aberration_waves (RSS / 8*lambda at 550 nm).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, unused)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {
                            "type": "number",
                            "description": "Curvature 1/R (mm^-1). 0 = flat.",
                        },
                        "t": {
                            "type": "number",
                            "description": "Thickness to next surface (mm).",
                        },
                        "n": {
                            "type": "number",
                            "description": "Refractive index after surface (>= 1.0).",
                        },
                        "k": {
                            "type": "number",
                            "description": "Conic constant (default 0 = sphere).",
                        },
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "aperture": {
                "type": "number",
                "description": "Marginal ray height at first surface (mm). Default 1.0.",
            },
            "field_angle_deg": {
                "type": "number",
                "description": "Chief-ray field angle (degrees). Default 5.0.",
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces"],
    },
)


@register(_seidel_aberrations_spec, write=False)
async def run_seidel_aberrations(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})

    kwargs: dict = {}
    if "aperture" in a:
        kwargs["aperture"] = float(a["aperture"])
    if "field_angle_deg" in a:
        kwargs["field_angle_deg"] = float(a["field_angle_deg"])
    if "n_object" in a:
        kwargs["n_object"] = float(a["n_object"])

    result = seidel_coefficients(a["surfaces"], **kwargs)
    if isinstance(result, dict):  # error dict
        return json.dumps(result)
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_compute_vignetting
# ---------------------------------------------------------------------------

_compute_vignetting_spec = ToolSpec(
    name="optics_compute_vignetting",
    description=(
        "Compute vignetting (relative illumination) across field angles for a\n"
        "sequential lens stack.\n"
        "\n"
        "Algorithm (Welford 1986 §4.5 / Hecht §6.6):\n"
        "  1. For each field angle θ, trace N marginal rays uniformly around the\n"
        "     entrance-pupil perimeter using the exact paraxial height formula.\n"
        "  2. At each surface, check if the ray height exceeds the surface clear\n"
        "     aperture (physical lens rim radius).  Rays that exceed any CA are\n"
        "     blocked.\n"
        "  3. Relative illumination (RI) = n_surviving / N_M.\n"
        "  4. Compare RI against the natural cos⁴(θ) photometric baseline.\n"
        "\n"
        "cos⁴ baseline: for a lens with no physical clipping, illumination falls\n"
        "off as cos⁴(θ) due to projected-area + obliquity (Hecht §6.6).\n"
        "Physical clipping causes RI to drop below this baseline.\n"
        "\n"
        "HONEST FLAG: circular, rotationally-symmetric apertures only.\n"
        "Anamorphic / off-axis stops, polychromatic pupil walk: NOT modelled.\n"
        "Sagittal-ray component is projected onto the meridional plane.\n"
        "\n"
        "Surface definition (each element of 'surfaces' array):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface.\n"
        "  k  : conic constant (default 0 = sphere).\n"
        "\n"
        "Returns per-field:\n"
        "  relative_illumination   : fraction of marginal rays that survive [0,1]\n"
        "  cos4_baseline           : natural cos⁴(θ) baseline\n"
        "  excess_vignetting       : RI / cos⁴ (< 1 means clipping beyond natural)\n"
        "  per_field_blocked_surfaces : surface indices where clipping occurred\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number", "description": "Curvature 1/R (mm^-1). 0 = flat."},
                        "t": {"type": "number", "description": "Thickness to next surface (mm)."},
                        "n": {"type": "number", "description": "Refractive index after surface (>= 1.0)."},
                        "k": {"type": "number", "description": "Conic constant (default 0 = sphere)."},
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "field_angles_deg": {
                "type": "array",
                "description": (
                    "List of field angles in degrees (e.g. [0, 5, 10, 14]). "
                    "0 = on-axis."
                ),
                "items": {"type": "number"},
            },
            "aperture_radius_mm": {
                "type": "number",
                "description": (
                    "Entrance-pupil half-diameter (mm). Default 10 mm. "
                    "Should be <= the physical clear aperture of the first surface."
                ),
            },
            "clear_apertures_mm": {
                "type": "array",
                "description": (
                    "Per-surface clear aperture radius (mm). "
                    "Length must equal number of surfaces. "
                    "Use 1e18 for surfaces with no physical rim (infinite aperture). "
                    "If omitted, all surfaces are treated as infinite — produces pure cos⁴."
                ),
                "items": {"type": "number"},
            },
            "n_marginal_rays": {
                "type": "integer",
                "description": (
                    "Number of marginal rays sampled around the pupil perimeter. "
                    "Default 8. Minimum 4."
                ),
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces", "field_angles_deg"],
    },
)


@register(_compute_vignetting_spec, write=False)
async def run_compute_vignetting(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})
    if a.get("field_angles_deg") is None:
        return json.dumps({"ok": False, "reason": "field_angles_deg is required"})

    kwargs: dict = {}
    if "aperture_radius_mm" in a:
        kwargs["aperture_radius_mm"] = float(a["aperture_radius_mm"])
    if "clear_apertures_mm" in a:
        kwargs["clear_apertures_mm"] = a["clear_apertures_mm"]
    if "n_marginal_rays" in a:
        kwargs["n_marginal_rays"] = int(a["n_marginal_rays"])
    if "n_object" in a:
        kwargs["n_object"] = float(a["n_object"])

    result = compute_vignetting(
        a["surfaces"],
        a["field_angles_deg"],
        **kwargs,
    )
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_pupil_diagram
# ---------------------------------------------------------------------------

_pupil_diagram_spec = ToolSpec(
    name="optics_pupil_diagram",
    description=(
        "Generate spot diagrams and pupil illumination maps for a sequential lens stack.\n"
        "\n"
        "Algorithm (Welford 1986 §8.2 / Hecht §5.7):\n"
        "  1. For each field angle, fill the entrance pupil with a uniform grid of N\n"
        "     ray positions (px, py) over the unit disk.\n"
        "  2. Trace each ray through the lens stack using exact meridional Snell traces\n"
        "     + Newton-Raphson conic intersect (trace_lens_stack).\n"
        "  3. Collect (x, y) intercepts at the paraxial image plane:\n"
        "       y_img : exact meridional trace result\n"
        "       x_img : first-order sagittal estimate = -px * R_ap * BFL/EFL\n"
        "  4. Compute RMS spot radius (2-D), meridional y-only RMS, and max ray\n"
        "     distance from chief ray.\n"
        "  5. Return surviving pupil coordinates (exit-pupil illumination map).\n"
        "\n"
        "Depth bar (Welford 1986 §8.2):\n"
        "  * Stigmatic stack (flat surface, c=0): y-RMS < 1e-6 mm (single-point focus).\n"
        "  * BK7 biconvex on-axis: y-RMS > 0 (spherical aberration).\n"
        "  * BK7 biconvex at 14 deg: y-RMS >> y-RMS at 0 deg (coma dominates off-axis).\n"
        "  * Use rms_spot_y_mm (meridional-only) as the aberration diagnostic;\n"
        "    rms_spot_radius_mm (2-D) includes the first-order sagittal x contribution\n"
        "    which is nearly constant across field angles.\n"
        "\n"
        "HONEST FLAGS:\n"
        "  * Monochromatic only. Polychromatic spot diagrams require per-wavelength\n"
        "    tracing weighted by spectral power density (out of scope).\n"
        "  * Sagittal (x) intercepts are first-order estimates; rigorous x requires\n"
        "    full 3-D skew-ray tracing (not implemented).\n"
        "  * Exit-pupil position is a paraxial estimate (BFL); rigorous location\n"
        "    requires chief-ray back-trace from image space (Welford 1986 §3.5).\n"
        "  * Physical aperture clipping not applied; use optics_compute_vignetting.\n"
        "\n"
        "Surface definition (same as optics_ray_trace_lens_stack):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface.\n"
        "  k  : conic constant (default 0 = sphere).\n"
        "\n"
        "Returns for each field angle:\n"
        "  intercepts_mm          : list of [x_mm, y_mm] intercepts at image plane\n"
        "  chief_ray_y_mm         : chief-ray y intercept\n"
        "  rms_spot_radius_mm     : 2-D RMS spot radius (mm, includes sagittal x)\n"
        "  rms_spot_y_mm          : meridional y-only RMS (aberration signal)\n"
        "  max_ray_distance_mm    : max ray distance from chief ray (mm)\n"
        "  n_rays_traced          : number of rays successfully traced\n"
        "  pupil_coords_surviving : surviving [px, py] pupil positions\n"
        "Plus top-level: rms_spot_size_per_field, rms_spot_y_per_field,\n"
        "exit_pupil_pos_mm, EFL_mm.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number", "description": "Curvature 1/R (mm^-1). 0 = flat."},
                        "t": {"type": "number", "description": "Thickness to next surface (mm)."},
                        "n": {"type": "number", "description": "Refractive index after surface (>= 1.0)."},
                        "k": {"type": "number", "description": "Conic constant (default 0 = sphere)."},
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "field_angles_deg": {
                "type": "array",
                "description": (
                    "List of field angles in degrees (e.g. [0, 5, 10, 14]). "
                    "0 = on-axis."
                ),
                "items": {"type": "number"},
            },
            "n_rays_per_field": {
                "type": "integer",
                "description": (
                    "Target number of rays per field angle (default 200). "
                    "Actual count may be slightly less due to unit-disk clipping."
                ),
            },
            "aperture_radius_mm": {
                "type": "number",
                "description": (
                    "Entrance-pupil half-diameter (mm). Default 10 mm. "
                    "Should be <= physical clear aperture of first surface."
                ),
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces", "field_angles_deg"],
    },
)


@register(_pupil_diagram_spec, write=False)
async def run_pupil_diagram(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})
    if a.get("field_angles_deg") is None:
        return json.dumps({"ok": False, "reason": "field_angles_deg is required"})

    kwargs: dict = {}
    if "n_rays_per_field" in a:
        kwargs["n_rays_per_field"] = int(a["n_rays_per_field"])
    if "aperture_radius_mm" in a:
        kwargs["aperture_radius_mm"] = float(a["aperture_radius_mm"])
    if "n_object" in a:
        kwargs["n_object"] = float(a["n_object"])

    result = compute_pupil_diagram(
        a["surfaces"],
        a["field_angles_deg"],
        **kwargs,
    )
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_defocus_curve
# ---------------------------------------------------------------------------

_defocus_curve_spec = ToolSpec(
    name="optics_defocus_curve",
    description=(
        "Compute the through-focus RMS spot-size curve (defocus curve) for a lens stack.\n"
        "\n"
        "Algorithm (Welford 1986 §11.5 / Hecht §6.5):\n"
        "  1. Determine paraxial image distance (BFL) via marginal paraxial trace.\n"
        "  2. For each of `samples` defocus steps Dz in [-defocus_range_mm, +defocus_range_mm],\n"
        "     trace a uniform aperture bundle at field_angle_deg through the stack.\n"
        "  3. Propagate each ray to the shifted evaluation plane (BFL + Dz).\n"
        "  4. Compute meridional RMS = sqrt(mean((y - mean_y)^2)) over surviving rays.\n"
        "  5. best_focus_shift_mm = Dz at minimum RMS.\n"
        "\n"
        "Depth bar:\n"
        "  * Ideal paraxial singlet at 0 deg: parabolic RMS curve; minimum at Dz=0.\n"
        "  * Full-aperture singlet: spherical aberration shifts RMS minimum to Dz < 0\n"
        "    (marginal best focus is closer to the lens than paraxial best focus).\n"
        "  * Off-axis field: field curvature / astigmatism shifts the minimum further.\n"
        "\n"
        "HONEST FLAGS:\n"
        "  * MONOCHROMATIC ONLY. Polychromatic defocus curves require per-wavelength\n"
        "    traces weighted by spectral power density (not implemented).\n"
        "  * MERIDIONAL (tangential) RMS only. Astigmatic sagittal/tangential focus\n"
        "    splitting requires full 3-D skew-ray trace (not implemented).\n"
        "  * Dz=0 is the paraxial BFL. For aberrated systems the RMS minimum may lie\n"
        "    at Dz != 0; best_focus_shift_mm quantifies this offset.\n"
        "\n"
        "Surface definition (same as optics_ray_trace_lens_stack):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface.\n"
        "  k  : conic constant (default 0 = sphere).\n"
        "\n"
        "Returns:\n"
        "  defocus_axis_mm      : list[float] -- Dz values (mm), length = samples\n"
        "  rms_per_defocus_mm   : list[float] -- RMS spot radius at each Dz (mm)\n"
        "  best_focus_shift_mm  : float -- Dz at RMS minimum\n"
        "  min_rms_mm           : float -- RMS value at best focus\n"
        "  bfl_mm               : float -- nominal paraxial BFL (mm)\n"
        "  n_rays_valid         : list[int] -- surviving ray counts per step\n"
        "  honest_flag          : str -- caveats\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number", "description": "Curvature 1/R (mm^-1). 0 = flat."},
                        "t": {"type": "number", "description": "Thickness to next surface (mm)."},
                        "n": {"type": "number", "description": "Refractive index after surface (>= 1.0)."},
                        "k": {"type": "number", "description": "Conic constant (default 0 = sphere)."},
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "field_angle_deg": {
                "type": "number",
                "description": "Field angle from optical axis (degrees, default 0.0 = on-axis).",
            },
            "defocus_range_mm": {
                "type": "number",
                "description": (
                    "Half-width of the defocus scan (mm, default 0.5). "
                    "Scans Dz in [-defocus_range_mm, +defocus_range_mm]."
                ),
            },
            "samples": {
                "type": "integer",
                "description": "Number of defocus steps (default 21, minimum 3).",
            },
            "aperture_radius_mm": {
                "type": "number",
                "description": "Entrance-pupil half-diameter (mm, default 10 mm).",
            },
            "n_rays": {
                "type": "integer",
                "description": "Number of rays across the entrance-pupil diameter (default 51).",
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces"],
    },
)


@register(_defocus_curve_spec, write=False)
async def run_defocus_curve(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})

    kwargs: dict = {}
    if "field_angle_deg" in a:
        kwargs["field_angle_deg"] = float(a["field_angle_deg"])
    if "defocus_range_mm" in a:
        kwargs["defocus_range_mm"] = float(a["defocus_range_mm"])
    if "samples" in a:
        kwargs["samples"] = int(a["samples"])
    if "aperture_radius_mm" in a:
        kwargs["aperture_radius_mm"] = float(a["aperture_radius_mm"])
    if "n_rays" in a:
        kwargs["n_rays"] = int(a["n_rays"])
    if "n_object" in a:
        kwargs["n_object"] = float(a["n_object"])

    result = compute_defocus_curve(a["surfaces"], **kwargs)
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_distortion_map
# ---------------------------------------------------------------------------

_distortion_map_spec = ToolSpec(
    name="optics_distortion_map",
    description=(
        "Compute the geometric (tangential) distortion map for a sequential lens stack.\n"
        "\n"
        "For each field angle θ, traces the chief ray (height=0 at first surface,\n"
        "aperture stop = first surface) and computes:\n"
        "  y_actual    = exact meridional image-plane intercept (chief ray).\n"
        "  y_paraxial  = f_eff * tan(θ)  (ideal first-order image height).\n"
        "  distortion  = (y_actual - y_paraxial) / |y_paraxial| × 100  [%]\n"
        "\n"
        "Sign convention (Hecht §5.6 / ISO 9039):\n"
        "  barrel distortion     → D < 0  (image compressed at edges)\n"
        "  pincushion distortion → D > 0  (image stretched at edges)\n"
        "\n"
        "Also returns the Seidel third-order S_V additive prediction\n"
        "(Welford §6.3) for comparison: accurate for small θ, diverges at\n"
        "large field where higher-order terms dominate.\n"
        "\n"
        "Depth bar:\n"
        "  Symmetric equiconvex singlet at small field: |D| < 2%\n"
        "    (S_V ≈ 0 by bending symmetry; Welford §6.4).\n"
        "  BK7 biconvex singlet at 20 deg field: |D| > 5% typical\n"
        "    for an uncorrected singlet with high S_V coefficient.\n"
        "\n"
        "HONEST FLAGS:\n"
        "  * Monochromatic only. Lateral chromatic distortion requires per-wavelength\n"
        "    chief-ray traces weighted by spectral power (not implemented).\n"
        "  * Tangential (meridional) distortion only. For rotationally symmetric\n"
        "    systems sagittal distortion is identical; astigmatic differences ignored.\n"
        "  * Aperture stop assumed at first surface (chief ray height = 0 there).\n"
        "\n"
        "Surface definition (same as optics_ray_trace_lens_stack):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface.\n"
        "  k  : conic constant (default 0 = sphere).\n"
        "\n"
        "Returns:\n"
        "  field_angles_deg         : input field angles (degrees)\n"
        "  y_actual_mm              : actual chief-ray image heights (mm)\n"
        "  y_paraxial_mm            : ideal paraxial image heights (mm)\n"
        "  distortion_percent       : (y_actual - y_paraxial)/|y_paraxial| × 100\n"
        "  max_distortion_pct       : max |distortion| across all field angles\n"
        "  kind                     : 'barrel' | 'pincushion' | 'mixed' | 'none'\n"
        "  EFL_mm                   : effective focal length used for y_paraxial\n"
        "  seidel_distortion_percent: Seidel S_V third-order additive prediction (%)\n"
        "  honest_flag              : caveats\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises.\n"
        "\n"
        "References: Hecht §5.6; Welford 1986 §6.3."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number", "description": "Curvature 1/R (mm^-1). 0 = flat."},
                        "t": {"type": "number", "description": "Thickness to next surface (mm)."},
                        "n": {"type": "number", "description": "Refractive index after surface (>= 1.0)."},
                        "k": {"type": "number", "description": "Conic constant (default 0 = sphere)."},
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "field_angles_deg": {
                "type": "array",
                "description": (
                    "List of field angles in degrees (e.g. [0, 5, 10, 15, 20]). "
                    "0 = on-axis (distortion = 0 by definition)."
                ),
                "items": {"type": "number"},
            },
            "aperture_mm": {
                "type": "number",
                "description": (
                    "Marginal ray height for Seidel cross-check and paraxial EFL "
                    "computation (mm). Default 1.0 mm."
                ),
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces", "field_angles_deg"],
    },
)


@register(_distortion_map_spec, write=False)
async def run_distortion_map(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})
    if a.get("field_angles_deg") is None:
        return json.dumps({"ok": False, "reason": "field_angles_deg is required"})

    kwargs: dict = {}
    if "aperture_mm" in a:
        kwargs["aperture_mm"] = float(a["aperture_mm"])
    if "n_object" in a:
        kwargs["n_object"] = float(a["n_object"])

    result = compute_distortion_map(
        a["surfaces"],
        a["field_angles_deg"],
        **kwargs,
    )
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_compute_coma
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.coma_compute import compute_coma  # noqa: E402

_compute_coma_spec = ToolSpec(
    name="optics_compute_coma",
    description=(
        "Compute coma aberration metrics from a lens stack across multiple field angles.\n"
        "\n"
        "Algorithm (Welford 1986 §11.4 / Born & Wolf §5.3):\n"
        "  1. Establish the paraxial focal plane (marginal ray h=aperture, u=0).\n"
        "  2. For each field angle, trace N rim rays at heights h=ap·cos(φ) with\n"
        "     angle u=tan(θ_f) using exact meridional Snell traces.\n"
        "  3. Propagate each ray to the paraxial focal plane.\n"
        "  4. Tangential coma = |mean(Y_tang) − y₀|, where Y_tang are the tangential-\n"
        "     fan ray intercepts and y₀ is the paraxial chief-ray image height\n"
        "     (Welford §11.4 — the comatic flare length).\n"
        "  5. Sagittal coma = tangential_coma / 3 (Welford §11.4 eq. 11.4.4).\n"
        "  6. total_coma = sqrt(tangential² + sagittal²).\n"
        "  7. Seidel prediction = 3 × |S_II| × |y₀|\n"
        "     where S_II is the Seidel coma coefficient (Born & Wolf §5.3 eq. 5.3.29).\n"
        "\n"
        "Depth bar:\n"
        "  * Afocal / flat stacks (c=0): coma = 0 (no focal plane).\n"
        "  * BK7 biconvex (R=±50 mm, t=5 mm, n=1.5168) at 14° field, 5 mm aperture:\n"
        "    total_coma > 1 μm (1e-3 mm).\n"
        "  * Field-angle scaling: total_coma ∝ |tan(θ)| (linear in small-angle limit).\n"
        "  * Seidel match: < 50% error at ≤ 5° field.\n"
        "\n"
        "HONEST FLAG: Third-order (Seidel) coma only. Higher-order coma (Hopkins\n"
        "5th-order, oblique spherical aberration) requires finite-ray OPD analysis\n"
        "(not implemented). Monochromatic; chromatic coma excluded.\n"
        "Stop assumed at first surface.\n"
        "\n"
        "Surface definition (same as optics_ray_trace_lens_stack):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface.\n"
        "  k  : conic constant (default 0 = sphere).\n"
        "\n"
        "Returns:\n"
        "  S_II                 : float  Seidel coma coefficient\n"
        "  aperture_radius_mm   : float  pupil rim radius used\n"
        "  per_field            : list   one entry per field angle:\n"
        "    field_angle_deg      : input angle (deg)\n"
        "    tangential_coma_mm   : comatic flare length in tangential plane (mm)\n"
        "    sagittal_coma_mm     : coma in sagittal plane = tan_coma/3 (mm)\n"
        "    total_coma_mm        : sqrt(tan² + sag²) (mm)\n"
        "    seidel_prediction_mm : 3×|S_II|×|y_chief| (mm)\n"
        "    seidel_match_fraction: |total − seidel_total|/seidel_total; null when seidel≈0\n"
        "    chief_ray_y_mm       : paraxial chief-ray image height (mm)\n"
        "    n_rays_valid         : number of successfully traced rim rays\n"
        "  honest_flag          : str caveats\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises.\n"
        "\n"
        "References: Welford (1986) §11.4; Born & Wolf (1999) §5.3."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number", "description": "Curvature 1/R (mm^-1). 0 = flat."},
                        "t": {"type": "number", "description": "Thickness to next surface (mm)."},
                        "n": {"type": "number", "description": "Refractive index after surface (>= 1.0)."},
                        "k": {"type": "number", "description": "Conic constant (default 0 = sphere)."},
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "field_angles_deg": {
                "type": "array",
                "description": (
                    "List of field angles in degrees (e.g. [0, 5, 10, 14]). "
                    "0 = on-axis (coma = 0 by symmetry)."
                ),
                "items": {"type": "number"},
            },
            "n_pupil_rays": {
                "type": "integer",
                "description": (
                    "Number of rim rays sampled around the entrance pupil (default 16). "
                    "Must be >= 4."
                ),
            },
            "aperture_radius_mm": {
                "type": "number",
                "description": (
                    "Entrance-pupil rim radius (mm). Default 1.0. "
                    "Should be <= physical clear aperture of the first surface."
                ),
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces", "field_angles_deg"],
    },
)


@register(_compute_coma_spec, write=False)
async def run_optics_compute_coma(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})
    if a.get("field_angles_deg") is None:
        return json.dumps({"ok": False, "reason": "field_angles_deg is required"})

    kwargs: dict = {}
    if "n_pupil_rays" in a:
        kwargs["n_pupil_rays"] = int(a["n_pupil_rays"])
    if "aperture_radius_mm" in a:
        kwargs["aperture_radius_mm"] = float(a["aperture_radius_mm"])
    if "n_object" in a:
        kwargs["n_object"] = float(a["n_object"])

    result = compute_coma(
        a["surfaces"],
        a["field_angles_deg"],
        **kwargs,
    )
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())

# Tool: optics_compute_chromatic_focus
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.chromatic_focus import (  # noqa: E402
    GLASS_SELLMEIER,
    ChromaticReport,
    LensElement,
    compute_chromatic_focus,
)

_compute_chromatic_focus_spec = ToolSpec(
    name="optics_compute_chromatic_focus",
    description=(
        "Compute longitudinal chromatic aberration (LCA) through a thin-lens stack\n"
        "using Sellmeier dispersion for each glass element.\n"
        "\n"
        "For each wavelength λ, refractive indices n(λ) are evaluated from the\n"
        "Sellmeier equation:\n"
        "  n²(λ) = 1 + Σ B_i·λ²/(λ² − C_i)   [λ in μm; Schott catalog coefficients]\n"
        "\n"
        "The paraxial back focal length (BFL) is derived via thin-lens ABCD matrix\n"
        "reduction at each wavelength. Primary LCA is:\n"
        "  LCA = BFL(F, 486 nm) − BFL(C, 656 nm)\n"
        "\n"
        "Depth bar (Hecht §6.3 / Welford §6.5):\n"
        "  BK7 singlet f=100 mm: V = (n_d−1)/(n_F−n_C) ≈ 64.2; LCA ≈ f/V ≈ 1.56 mm.\n"
        "  BK7+F2 achromatic doublet: LCA < 0.1 mm (F-line focus ≈ C-line focus).\n"
        "  SF6 singlet f=100 mm: V ≈ 25.4; LCA ≈ 3.9 mm (high LCA dense flint).\n"
        "\n"
        "HONEST FLAGS:\n"
        "  * PARAXIAL THIN-LENS LCA ONLY. Chromatic lateral aberration (transverse\n"
        "    colour) is NOT computed (requires real chief-ray traces per wavelength).\n"
        "  * Thick-lens principal-plane shifts with wavelength are not modelled.\n"
        "  * V_number is reported only for single-element stacks; multi-element\n"
        "    stacks require system-level Abbe analysis (not implemented).\n"
        "\n"
        "Supported glasses: BK7, F2, SF6, K5, SF11, BK10 (Schott catalog 2023).\n"
        "\n"
        "Each element of 'stack' requires:\n"
        "  glass          — glass name string (e.g. 'BK7')\n"
        "  R1             — front radius of curvature (mm). Non-zero; use 1e18 for flat.\n"
        "  R2             — rear radius of curvature (mm). Non-zero; use -1e18 for flat.\n"
        "  separation_mm  — axial gap to next element (mm). 0 for last element.\n"
        "\n"
        "Returns:\n"
        "  per_wavelength_focal_mm — dict mapping e.g. '486nm' -> BFL (mm)\n"
        "  lca_FC_mm               — BFL(486nm) − BFL(656nm)  (mm; negative = blue shorter)\n"
        "  lca_percent             — |LCA| / mean_BFL × 100\n"
        "  V_number                — Abbe V-number (singlet only; null for multi-element)\n"
        "  mean_BFL_mm             — mean BFL across requested wavelengths\n"
        "  honest_flag             — scope caveats\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises.\n"
        "\n"
        "References: Hecht §6.3; Welford (1986) §6.5; Schott Optical Glass catalog 2023."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stack": {
                "type": "array",
                "description": (
                    "Ordered list of thin-lens elements, front to back. "
                    "Each element: glass (str), R1 (mm), R2 (mm), separation_mm (mm, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "glass": {
                            "type": "string",
                            "description": (
                                "Schott glass name. Supported: "
                                "BK7, F2, SF6, K5, SF11, BK10."
                            ),
                        },
                        "R1": {
                            "type": "number",
                            "description": (
                                "Front surface radius of curvature (mm). "
                                "Non-zero; use 1e18 for flat surface."
                            ),
                        },
                        "R2": {
                            "type": "number",
                            "description": (
                                "Rear surface radius of curvature (mm). "
                                "Non-zero; use -1e18 for flat surface."
                            ),
                        },
                        "separation_mm": {
                            "type": "number",
                            "description": (
                                "Axial gap to next element (mm). "
                                "Use 0 for last element or cemented pair."
                            ),
                        },
                    },
                    "required": ["glass", "R1", "R2"],
                },
            },
            "wavelengths_nm": {
                "type": "array",
                "description": (
                    "Wavelengths to evaluate (nm). "
                    "Defaults to [486, 587, 656] (F, d, C Fraunhofer lines)."
                ),
                "items": {"type": "number"},
            },
        },
        "required": ["stack"],
    },
)


@register(_compute_chromatic_focus_spec, write=False)
async def run_compute_chromatic_focus(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_stack = a.get("stack")
    if raw_stack is None:
        return json.dumps({"ok": False, "reason": "stack is required"})
    if not isinstance(raw_stack, list) or len(raw_stack) == 0:
        return json.dumps({"ok": False, "reason": "stack must be a non-empty list"})

    elements = []
    for i, elem in enumerate(raw_stack):
        if not isinstance(elem, dict):
            return json.dumps({"ok": False, "reason": f"stack[{i}] must be an object"})
        glass = elem.get("glass")
        if not isinstance(glass, str):
            return json.dumps({"ok": False, "reason": f"stack[{i}].glass must be a string"})
        R1 = elem.get("R1")
        R2 = elem.get("R2")
        if R1 is None or R2 is None:
            return json.dumps({"ok": False, "reason": f"stack[{i}] requires R1 and R2"})
        sep = float(elem.get("separation_mm", 0.0))
        elements.append(LensElement(glass=glass, R1=float(R1), R2=float(R2), separation_mm=sep))

    wavelengths = a.get("wavelengths_nm")
    if wavelengths is not None:
        if not isinstance(wavelengths, list) or len(wavelengths) == 0:
            return json.dumps({"ok": False, "reason": "wavelengths_nm must be a non-empty list"})

    result = compute_chromatic_focus(elements, wavelengths_nm=wavelengths)
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_compute_abbe_number
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.abbe_number import (  # noqa: E402
    AbbeReport,
    compute_abbe_number,
)

_compute_abbe_number_spec = ToolSpec(
    name="optics_compute_abbe_number",
    description=(
        "Compute the Abbe number (V-number) and secondary-spectrum partial\n"
        "dispersion for a named Schott glass using its Sellmeier coefficients.\n"
        "\n"
        "Abbe number (ISO 10110 / Hecht §6.3):\n"
        "  V_d = (n_d − 1) / (n_F − n_C)\n"
        "\n"
        "where n_d, n_F, n_C are refractive indices at Fraunhofer lines:\n"
        "  d  — helium  d-line  587.56 nm  (photopic peak)\n"
        "  F  — hydrogen F-line 486.13 nm  (blue)\n"
        "  C  — hydrogen C-line 656.27 nm  (red)\n"
        "\n"
        "High V (> 55) = crown glass (low dispersion); e.g. BK7 V ≈ 64.17.\n"
        "Low  V (< 40) = flint glass (high dispersion); e.g. SF11 V ≈ 25.76.\n"
        "\n"
        "Secondary spectrum partial dispersion P_{F,g}:\n"
        "  P_FC_g = (n_g − n_F) / (n_F − n_C)\n"
        "where n_g is the refractive index at the mercury g-line (435.84 nm).\n"
        "Matching P_{F,g} between two glasses suppresses residual secondary\n"
        "spectrum (apochromat condition, Hecht §6.3 / Conrady criterion).\n"
        "\n"
        "Supported glasses: BK7, F2, SF6, K5, SF11, BK10 (Schott catalog 2023).\n"
        "\n"
        "Depth bar (Schott catalog values):\n"
        "  BK7:  V_d = 64.17  (n_d = 1.5168)\n"
        "  F2:   V_d = 36.37  (n_d = 1.6200)\n"
        "  SF11: V_d = 25.76  (n_d = 1.7847)\n"
        "  SF6:  V_d = 25.43  (n_d = 1.8052)\n"
        "  K5:   V_d = 59.48  (n_d = 1.5225)\n"
        "  BK10: V_d = 67.02  (n_d = 1.4978)\n"
        "\n"
        "Returns glass_name, n_d, n_F, n_C, n_g, V_d, P_FC_g, honest_flag.\n"
        "\n"
        "HONEST FLAG: Sellmeier coefficients are catalog nominal/melt-mean values;\n"
        "melt-to-melt V_d variation ±0.3–0.5% (Schott TIE-31). Only six glasses\n"
        "are available; other glasses require adding their Sellmeier coefficients.\n"
        "\n"
        "Errors: {ok:false, reason} for unknown glass or invalid input. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "glass_name": {
                "type": "string",
                "description": (
                    "Schott glass name (case-sensitive). "
                    "One of: BK7, F2, SF6, K5, SF11, BK10."
                ),
            },
        },
        "required": ["glass_name"],
    },
)


@register(_compute_abbe_number_spec, write=False)
async def run_compute_abbe_number(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    glass_name = a.get("glass_name")
    if not glass_name:
        return json.dumps({"ok": False, "reason": "glass_name is required"})

    result = compute_abbe_number(glass_name)
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())


from kerf_cad_core.optics.relative_illum_map import (  # noqa: E402
    RelIllumMapReport,
    compute_relative_illum_map,
)

# ---------------------------------------------------------------------------
# Tool: optics_compute_relative_illum_map
# ---------------------------------------------------------------------------

_relative_illum_map_spec = ToolSpec(
    name="optics_compute_relative_illum_map",
    description=(
        "Compute a 2-D relative illumination (RI) map across the image plane\n"
        "for a sequential lens stack.\n"
        "\n"
        "For each grid point (x, y) on the sensor the field angle\n"
        "  theta(x, y) = arctan(sqrt(x^2+y^2) / EFL)\n"
        "is computed and RI(theta) is evaluated by tracing a bundle of marginal\n"
        "rays through all lens surfaces and counting the surviving fraction.\n"
        "\n"
        "Theory (Welford 1986 §4.5 / Hecht §6.6 / Slyusarev §3.4):\n"
        "  cos4_map: natural cos4(theta) photometric baseline — 1.0 at centre,\n"
        "    falling to cos4(theta_corner) at corners (Hecht §6.6 eq. 6.68).\n"
        "  ri_map: physical aperture clipping model — 1.0 everywhere without\n"
        "    clear_apertures_mm; drops below 1.0 when finite CAs block marginal rays.\n"
        "  Real system with clipping: ri_map shows sharper drop than cos4 baseline.\n"
        "  Wide-angle lens (theta_max > 50 deg): cos4_corner < 16%.\n"
        "\n"
        "Returns:\n"
        "  ri_map      : 2-D list (grid x grid), physical clipping model RI.\n"
        "  cos4_map    : 2-D list (grid x grid), cos4(theta) natural baseline.\n"
        "  corner_ri   : RI at sensor corner (physical clipping).\n"
        "  corner_cos4 : cos4 baseline at corner.\n"
        "  max_field_angle : degrees at sensor corner.\n"
        "  efl_mm      : effective focal length used (mm).\n"
        "\n"
        "HONEST FLAGS:\n"
        "  * Monochromatic only (polychromatic pupil walk out of scope).\n"
        "  * Rotationally symmetric stack assumed; map is azimuthally symmetric.\n"
        "  * Sensor acceptance tilt / field-lens telecentricity not modelled.\n"
        "\n"
        "Surface definition (same as optics_ray_trace_lens_stack):\n"
        "  c : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t : thickness to NEXT surface (mm). Last surface: 0.\n"
        "  n : refractive index after surface (>= 1.0).\n"
        "  k : conic constant (default 0 = sphere).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises.\n"
        "\n"
        "References: Welford 1986 §4.5; Hecht §6.6; Slyusarev §3.4."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number", "description": "Curvature 1/R (mm^-1). 0 = flat."},
                        "t": {"type": "number", "description": "Thickness to next surface (mm)."},
                        "n": {"type": "number", "description": "Refractive index after surface (>= 1.0)."},
                        "k": {"type": "number", "description": "Conic constant (default 0 = sphere)."},
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "image_grid_size": {
                "type": "integer",
                "description": (
                    "Number of grid points per side (default 33, minimum 3). "
                    "Odd values place a sample at the exact image centre."
                ),
            },
            "sensor_half_height_mm": {
                "type": "number",
                "description": (
                    "Half-side of the square sensor (mm). "
                    "Default 15 mm (30 mm sensor — full-frame 35 mm equivalent)."
                ),
            },
            "aperture_radius_mm": {
                "type": "number",
                "description": "Entrance-pupil half-diameter (mm). Default 10 mm.",
            },
            "clear_apertures_mm": {
                "type": "array",
                "description": (
                    "Per-surface clear aperture radius (mm). "
                    "Length must equal number of surfaces. "
                    "Use 1e18 for surfaces with no physical rim. "
                    "If omitted, all surfaces are infinite — ri_map = all 1.0."
                ),
                "items": {"type": "number"},
            },
            "n_marginal_rays": {
                "type": "integer",
                "description": "Marginal rays per field angle (default 8, minimum 4).",
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces"],
    },
)


@register(_relative_illum_map_spec, write=False)
async def run_optics_relative_illum_map(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})

    kwargs: dict = {}
    if "image_grid_size" in a:
        kwargs["image_grid_size"] = int(a["image_grid_size"])
    if "sensor_half_height_mm" in a:
        kwargs["sensor_half_height_mm"] = float(a["sensor_half_height_mm"])
    if "aperture_radius_mm" in a:
        kwargs["aperture_radius_mm"] = float(a["aperture_radius_mm"])
    if "clear_apertures_mm" in a:
        kwargs["clear_apertures_mm"] = a["clear_apertures_mm"]
    if "n_marginal_rays" in a:
        kwargs["n_marginal_rays"] = int(a["n_marginal_rays"])
    if "n_object" in a:
        kwargs["n_object"] = float(a["n_object"])

    result = compute_relative_illum_map(a["surfaces"], **kwargs)
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())
# Tool: optics_compute_entrance_pupil
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.entrance_pupil import (  # noqa: E402
    EntrancePupilReport,
    compute_entrance_pupil,
)

_entrance_pupil_spec = ToolSpec(
    name="optics_compute_entrance_pupil",
    description=(
        "Compute the paraxial entrance pupil position and size for a lens stack.\n"
        "\n"
        "The entrance pupil is the image of the aperture stop formed by all lens\n"
        "elements in front of the stop, as seen from object space.\n"
        "Its position and semi-diameter define the light-gathering cone accepted\n"
        "by the system (Welford 1986 §4.4; Hecht §6.6).\n"
        "\n"
        "Algorithm (Welford 1986 §4.4):\n"
        "  For each surface j = stop_surface_index−1 … 0 (right to left):\n"
        "    1. Transfer backward by t[j] (gap from surface j to next surface).\n"
        "    2. Refract at surface j with negated curvature (reverse-trace convention).\n"
        "  Then:\n"
        "    position_z_mm = -h_exit / u_exit  (axis crossing from first surface).\n"
        "    radius_mm = D * stop_radius  where D is the (2,2) paraxial matrix element.\n"
        "    magnification = radius_mm / (stop_diameter_mm / 2).\n"
        "\n"
        "Depth bar:\n"
        "  * Stop at first surface (stop_surface_index=0): pupil at z=0, m=1.\n"
        "    (Thin-lens identity; Hecht §6.6.)\n"
        "  * Converging front lens, rear stop (d << f): pupil at positive z,\n"
        "    slightly demagnified (m < 1). (BK7 biconvex, stop at rear surface.)\n"
        "  * Diverging front lens, rear stop: pupil at negative z (virtual),\n"
        "    magnified (m > 1). (Hecht §6.6 virtual-pupil example.)\n"
        "\n"
        "HONEST FLAGS:\n"
        "  * PARAXIAL ONLY.  Real chief-ray entrance pupil requires finite-ray\n"
        "    chief-ray back-tracing from the stop (not implemented).\n"
        "  * EXIT PUPIL is a separate computation (not in this tool).\n"
        "  * Stop modelled as a thin plane; thick stops not handled.\n"
        "  * Paraxial approximation degrades for fast (f/# < 2) or wide-field systems.\n"
        "\n"
        "Surface definition (same as optics_ray_trace_lens_stack):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface.\n"
        "  k  : conic constant (default 0; unused for paraxial trace).\n"
        "\n"
        "Returns:\n"
        "  position_z_mm  : entrance pupil z-position from first surface (mm).\n"
        "                   Negative = virtual pupil in front of the first surface.\n"
        "  radius_mm      : entrance pupil semi-diameter (mm).\n"
        "  diameter_mm    : full entrance pupil diameter (mm).\n"
        "  magnification  : D matrix element of front group (radius / stop_radius).\n"
        "  honest_flag    : scope caveats.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises.\n"
        "\n"
        "References: Welford (1986) §4.4; Hecht §6.6."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number", "description": "Curvature 1/R (mm^-1). 0 = flat."},
                        "t": {"type": "number", "description": "Thickness to next surface (mm)."},
                        "n": {"type": "number", "description": "Refractive index after surface (>= 1.0)."},
                        "k": {"type": "number", "description": "Conic constant (default 0 = sphere)."},
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "stop_diameter_mm": {
                "type": "number",
                "description": "Full diameter of the aperture stop (mm). Must be > 0.",
            },
            "stop_surface_index": {
                "type": "integer",
                "description": (
                    "0-based index of the aperture-stop surface (default 0 = first surface). "
                    "The stop is at the vertex plane of this surface."
                ),
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces", "stop_diameter_mm"],
    },
)


@register(_entrance_pupil_spec, write=False)
async def run_compute_entrance_pupil(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})
    if a.get("stop_diameter_mm") is None:
        return json.dumps({"ok": False, "reason": "stop_diameter_mm is required"})

    kwargs: dict = {}
    if "stop_surface_index" in a:
        kwargs["stop_surface_index"] = int(a["stop_surface_index"])
    if "n_object" in a:
        kwargs["n_object"] = float(a["n_object"])

    result = compute_entrance_pupil(
        a["surfaces"],
        float(a["stop_diameter_mm"]),
        **kwargs,
    )
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_compute_exit_pupil
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.exit_pupil import (  # noqa: E402
    ExitPupilReport,
    compute_exit_pupil,
)

_exit_pupil_spec = ToolSpec(
    name="optics_compute_exit_pupil",
    description=(
        "Compute the paraxial exit pupil position and size for a lens stack.\n"
        "\n"
        "The exit pupil is the image of the aperture stop formed by all lens\n"
        "elements behind the stop, as seen from image space.\n"
        "Its position and semi-diameter define the cone of rays converging\n"
        "toward each image point (Welford 1986 §4.4; Hecht §6.6).\n"
        "\n"
        "Algorithm (Welford 1986 §4.4, two-ray forward trace):\n"
        "  Ray 1 (h=stop_r, nu=0) and Ray 2 (h=0, nu=1) are traced forward\n"
        "  from the stop through the rear sub-stack.\n"
        "  position_z_mm = -h2_last / u2_last  (image of stop via B-element; Welford eq. 4.4.5)\n"
        "  radius_mm = |h1_last + z_ep * u1_last|  (stop edge image height at exit pupil plane)\n"
        "  magnification = radius_mm / (stop_diameter_mm / 2)\n"
        "\n"
        "Depth bar:\n"
        "  * Stop at last surface (stop_surface_index=N-1): pupil at z=0, m=1.\n"
        "    (Thin-lens identity; Hecht §6.6.)\n"
        "  * Thin lens (t=0), stop at front surface: pupil at z=0, m=1.\n"
        "  * BK7 biconvex, stop at first surface: virtual pupil (z<0) just\n"
        "    inside the rear surface; m approx 1.035.\n"
        "  * Afocal telescope (f_obj=100mm, f_eye=25mm): stop at objective ->\n"
        "    Ramsden disk at z=31.25mm, radius=1.25mm, m=0.25 = 1/M_telescope.\n"
        "    (Hecht §6.6 Ramsden disk.)\n"
        "\n"
        "HONEST FLAGS:\n"
        "  * PARAXIAL ONLY.  Real chief-ray exit pupil requires finite-ray\n"
        "    chief-ray back-tracing from image space to the stop (not implemented).\n"
        "  * ENTRANCE PUPIL is a separate computation (optics_compute_entrance_pupil).\n"
        "  * Stop modelled as a thin plane; thick stops not handled.\n"
        "  * Paraxial approximation degrades for fast (f/# < 2) or wide-field systems.\n"
        "\n"
        "Surface definition (same as optics_ray_trace_lens_stack):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface.\n"
        "  k  : conic constant (default 0; unused for paraxial trace).\n"
        "\n"
        "Returns:\n"
        "  position_z_mm  : exit pupil z-position from last surface (mm).\n"
        "                   Positive = real pupil behind the last surface.\n"
        "                   Negative = virtual pupil inside the barrel.\n"
        "  radius_mm      : exit pupil semi-diameter (mm).\n"
        "  diameter_mm    : full exit pupil diameter (mm).\n"
        "  magnification  : radius / stop_radius (rear group transverse mag).\n"
        "  honest_flag    : scope caveats.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises.\n"
        "\n"
        "References: Welford (1986) §4.4; Hecht §6.6."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of optical surface dicts. Each must have: "
                    "c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number", "description": "Curvature 1/R (mm^-1). 0 = flat."},
                        "t": {"type": "number", "description": "Thickness to next surface (mm)."},
                        "n": {"type": "number", "description": "Refractive index after surface (>= 1.0)."},
                        "k": {"type": "number", "description": "Conic constant (default 0 = sphere)."},
                    },
                    "required": ["c", "t", "n"],
                },
            },
            "stop_diameter_mm": {
                "type": "number",
                "description": "Full diameter of the aperture stop (mm). Must be > 0.",
            },
            "stop_surface_index": {
                "type": "integer",
                "description": (
                    "0-based index of the aperture-stop surface (default 0 = first surface). "
                    "The stop is at the vertex plane of this surface."
                ),
            },
            "n_object": {
                "type": "number",
                "description": "Refractive index of object space (default 1.0 = air).",
            },
        },
        "required": ["surfaces", "stop_diameter_mm"],
    },
)


@register(_exit_pupil_spec, write=False)
async def run_compute_exit_pupil(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})
    if a.get("stop_diameter_mm") is None:
        return json.dumps({"ok": False, "reason": "stop_diameter_mm is required"})

    kwargs: dict = {}
    if "stop_surface_index" in a:
        kwargs["stop_surface_index"] = int(a["stop_surface_index"])
    if "n_object" in a:
        kwargs["n_object"] = float(a["n_object"])

    result = compute_exit_pupil(
        a["surfaces"],
        float(a["stop_diameter_mm"]),
        **kwargs,
    )
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_compute_petzval_curvature
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.petzval_curvature import (  # noqa: E402
    PetzvalReport,
    compute_petzval_curvature,
)

_petzval_curvature_spec = ToolSpec(
    name="optics_compute_petzval_curvature",
    description=(
        "Compute Petzval field curvature (1/R_P) for a sequential optical system.\n"
        "\n"
        "Theory (Hecht 'Optics' 5e §6.3.2 / Born & Wolf §4.5):\n"
        "  The Petzval sum is the curvature of the Petzval sphere — the ideal image\n"
        "  surface for a system free of astigmatism:\n"
        "\n"
        "    P = Σ_i (n_after_i − n_before_i) / (n_before_i · n_after_i · R_i)\n"
        "\n"
        "  Petzval radius R_P = 1/P.\n"
        "  P = 0 (flat-field condition) requires compensating positive and negative\n"
        "  contributions from lens elements with appropriate glass choice and bending.\n"
        "\n"
        "Oracle: single thin BK7 lens (n=1.5168, R1=+50 mm, R2=−50 mm):\n"
        "  Surface 1: P_1 = (1.5168−1)/(1·1.5168·50) = 0.006813 mm⁻¹\n"
        "  Surface 2: P_2 = (1−1.5168)/(1.5168·1·(−50)) = 0.006813 mm⁻¹ → wait\n"
        "  Correct:   P_2 = (1.0 − 1.5168) / (1.5168 · 1.0 · (−50)) = +0.006813\n"
        "  Total P ≈ 0.013657 mm⁻¹  →  R_P ≈ 73.2 mm.\n"
        "\n"
        "Input format:\n"
        "  'surfaces' is a list of dicts, each with:\n"
        "    radius_mm      : float  Radius of curvature (mm). Use 1e18 for plano.\n"
        "    n_index_before : float  Refractive index before this surface (>= 1.0).\n"
        "    n_index_after  : float  Refractive index after this surface (>= 1.0).\n"
        "\n"
        "  Note: unlike optics_ray_trace_lens_stack (which uses curvature c=1/R),\n"
        "  THIS tool uses radius_mm directly for clarity.\n"
        "\n"
        "Returns:\n"
        "  petzval_sum_mm_inv       : P = 1/R_P (mm⁻¹). 0 = flat field.\n"
        "  petzval_radius_mm        : R_P = 1/P (mm). null when P=0 (flat).\n"
        "  field_flatness_score     : 0..1 quality score; 1.0 = flat field.\n"
        "  per_surface_contributions: per-surface breakdown with radius, n values,\n"
        "                             contribution, and is_plano flag.\n"
        "  honest_caveat            : scope caveats (astigmatism, thick-lens effects).\n"
        "\n"
        "HONEST FLAG:\n"
        "  Petzval sum is a PARAXIAL quantity. It equals the Seidel S_IV\n"
        "  field-curvature coefficient but does NOT include astigmatism (S_III).\n"
        "  Real curved-field appearance includes both S_III and S_IV.\n"
        "  P=0 guarantees a flat Petzval sphere but NOT zero field curvature in\n"
        "  the presence of astigmatism (Hecht §6.3.2).\n"
        "  Thick-lens and pupil-shift corrections to P are ignored.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises.\n"
        "\n"
        "References: Hecht §6.3.2; Born & Wolf §4.5; Smith 'Modern Optical Engineering' §4.4."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of refracting surface dicts. Each must have: "
                    "radius_mm (float; use 1e18 for plano), "
                    "n_index_before (float >= 1.0), "
                    "n_index_after (float >= 1.0)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "radius_mm": {
                            "type": "number",
                            "description": (
                                "Radius of curvature (mm). Sign: R > 0 if centre of "
                                "curvature is to the right. Use 1e18 for a flat (plano) surface."
                            ),
                        },
                        "n_index_before": {
                            "type": "number",
                            "description": "Refractive index of medium before this surface (>= 1.0).",
                        },
                        "n_index_after": {
                            "type": "number",
                            "description": "Refractive index of medium after this surface (>= 1.0).",
                        },
                    },
                    "required": ["radius_mm", "n_index_before", "n_index_after"],
                },
            },
        },
        "required": ["surfaces"],
    },
)


@register(_petzval_curvature_spec, write=False)
async def run_compute_petzval_curvature(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surfaces") is None:
        return json.dumps({"ok": False, "reason": "surfaces is required"})

    result = compute_petzval_curvature({"surfaces": a["surfaces"]})
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_compute_diffraction_mtf
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.mtf_diffraction import (  # noqa: E402
    MTFReport,
    compute_diffraction_mtf,
)

_diffraction_mtf_spec = ToolSpec(
    name="optics_compute_diffraction_mtf",
    description=(
        "Compute the diffraction-limited Modulation Transfer Function MTF(ν) for a\n"
        "circular aperture as a function of spatial frequency (cyc/mm).\n"
        "\n"
        "Theory (Goodman 'Introduction to Fourier Optics' §6.4, eq. 6-49;\n"
        "        Hecht 'Optics' 5e §11.3.3):\n"
        "\n"
        "  ν_0 = 1 / (λ · F#)               [diffraction cutoff, cyc/mm]\n"
        "\n"
        "  MTF(ν) = (2/π)·[arccos(ν/ν_0) − (ν/ν_0)·√(1−(ν/ν_0)²)]   ν ≤ ν_0\n"
        "  MTF(ν) = 0                                                   ν > ν_0\n"
        "\n"
        "This is the theoretical UPPER BOUND for a perfect, aberration-free lens.\n"
        "Any real system will have lower MTF due to aberrations, defocus, or sensor\n"
        "blur.  See honest_caveat in the response.\n"
        "\n"
        "Parameters\n"
        "----------\n"
        "wavelength_nm         : wavelength of light in nm (e.g. 550 for green).\n"
        "f_number              : F-number of the system (e.g. 4 for f/4).\n"
        "num_samples           : frequency samples in [0, max_freq] (default 200).\n"
        "max_freq_cyc_per_mm   : upper frequency limit (default 1.05 × ν_0).\n"
        "\n"
        "Returns\n"
        "-------\n"
        "cutoff_freq_cyc_per_mm : ν_0 = 1/(λ·F#) in cyc/mm.\n"
        "mtf_curve              : list of [ν, MTF(ν)] pairs.\n"
        "mtf_at_50_percent      : frequency at which MTF ≈ 0.50.\n"
        "honest_caveat          : plain-English scope limitations.\n"
        "\n"
        "Analytic oracle (λ=550 nm, F/4):\n"
        "  ν_0 = 454.5 cyc/mm; MTF(0)=1.0; MTF(ν_0)=0; MTF(ν_0/2)≈0.391.\n"
        "\n"
        "HONEST: diffraction-limited only — no aberrations, no defocus, no sensor MTF,\n"
        "no polychromatic weighting, on-axis only, circular aperture only.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wavelength_nm": {
                "type": "number",
                "description": (
                    "Wavelength of light in nanometres (nm). "
                    "E.g. 550 for green, 486 for blue (F-line), 656 for red (C-line). "
                    "Must be > 0."
                ),
            },
            "f_number": {
                "type": "number",
                "description": (
                    "System F-number (f/#). E.g. 4 for f/4, 1.4 for f/1.4. "
                    "Must be > 0."
                ),
            },
            "num_samples": {
                "type": "integer",
                "description": (
                    "Number of equally-spaced frequency samples from 0 to "
                    "max_freq_cyc_per_mm. Default 200. Must be >= 2."
                ),
            },
            "max_freq_cyc_per_mm": {
                "type": "number",
                "description": (
                    "Upper frequency limit for the output curve (cyc/mm). "
                    "If omitted, defaults to 1.05 × ν_0 so the zero-crossing "
                    "is visible. Must be > 0 if provided."
                ),
            },
        },
        "required": ["wavelength_nm", "f_number"],
    },
)


@register(_diffraction_mtf_spec, write=False)
async def run_diffraction_mtf(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field_name in ("wavelength_nm", "f_number"):
        if a.get(field_name) is None:
            return json.dumps({"ok": False, "reason": f"{field_name} is required"})

    kwargs: dict = {}
    if "num_samples" in a:
        kwargs["num_samples"] = int(a["num_samples"])
    if "max_freq_cyc_per_mm" in a:
        kwargs["max_freq_cyc_per_mm"] = float(a["max_freq_cyc_per_mm"])

    result = compute_diffraction_mtf(
        wavelength_nm=float(a["wavelength_nm"]),
        f_number=float(a["f_number"]),
        **kwargs,
    )
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_fit_zernike_wavefront
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.optics.zernike_fit import (
        ZernikeFitReport,
        fit_zernike_wavefront,
    )
    _ZERNIKE_FIT_AVAILABLE = True
except ImportError:  # numpy not installed
    _ZERNIKE_FIT_AVAILABLE = False

_fit_zernike_spec = ToolSpec(
    name="optics_fit_zernike_wavefront",
    description=(
        "Fit the first N Zernike polynomial coefficients (Noll 1976 ordering,\n"
        "j=1..15) to sampled wavefront data W(ρ,θ) over a unit-disk pupil using\n"
        "least-squares regression (numpy.linalg.lstsq).\n"
        "\n"
        "Noll j-index and aberration name mapping (first 15 terms):\n"
        "  j=1  piston         j=2  tip             j=3  tilt\n"
        "  j=4  defocus        j=5  astigmatism_45  j=6  astigmatism_0\n"
        "  j=7  coma_y         j=8  coma_x          j=9  trefoil_y\n"
        "  j=10 trefoil_x      j=11 spherical       j=12 secondary_astig_0\n"
        "  j=13 secondary_astig_45  j=14 tetrafoil_x  j=15 tetrafoil_y\n"
        "\n"
        "Explicit polynomial formulas (Noll 1976 orthonormal on unit disk):\n"
        "  Z_1  = 1\n"
        "  Z_2  = 2ρ cos θ\n"
        "  Z_3  = 2ρ sin θ\n"
        "  Z_4  = √3 (2ρ²−1)\n"
        "  Z_5  = √6 ρ² sin 2θ\n"
        "  Z_6  = √6 ρ² cos 2θ\n"
        "  Z_7  = √8 (3ρ³−2ρ) sin θ\n"
        "  Z_8  = √8 (3ρ³−2ρ) cos θ\n"
        "  Z_9  = √8 ρ³ sin 3θ\n"
        "  Z_10 = √8 ρ³ cos 3θ\n"
        "  Z_11 = √5 (6ρ⁴−6ρ²+1)\n"
        "  Z_12 = √10 (4ρ⁴−3ρ²) cos 2θ\n"
        "  Z_13 = √10 (4ρ⁴−3ρ²) sin 2θ\n"
        "  Z_14 = √10 ρ⁴ cos 4θ\n"
        "  Z_15 = √10 ρ⁴ sin 4θ\n"
        "\n"
        "Returns:\n"
        "  coefficients       : list of N floats [c_1..c_N] in Noll order\n"
        "  rms_residual_waves : RMS of (W_measured − W_fitted) [same units as W]\n"
        "  dominant_aberration: name of argmax(|c_j|) for j ≥ 2 (piston excluded)\n"
        "  coefficient_names  : list of N strings\n"
        "  honest_caveat      : scope limitations\n"
        "\n"
        "Honest limits:\n"
        "  * First 15 Noll terms only; higher-order wavefront content aliases into\n"
        "    residual — report rms_residual to expose unmodelled power.\n"
        "  * Unit-disk pupil (ρ ∈ [0,1]); no elliptical aperture, no obscuration.\n"
        "  * Requires ≥ num_terms samples; returns error for under-determined system.\n"
        "\n"
        "References: Noll (1976) J. Opt. Soc. Am. 66 207; Born & Wolf §9.2;\n"
        "Wyant & Creath (1992) Applied Optics and Optical Engineering XI ch.1.\n"
        "\n"
        "Errors: {ok: false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "samples": {
                "type": "array",
                "description": (
                    "List of wavefront sample points.  Each element must be a\n"
                    "3-element array [rho, theta, W] where:\n"
                    "  rho   : normalised pupil radius in [0, 1]\n"
                    "  theta : pupil angle (radians)\n"
                    "  W     : wavefront value at this point (waves)"
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 1,
            },
            "num_terms": {
                "type": "integer",
                "description": (
                    "Number of Noll-ordered Zernike terms to fit (1..15). "
                    "Default 15.  Must be ≤ number of samples."
                ),
            },
        },
        "required": ["samples"],
    },
)


@register(_fit_zernike_spec, write=False)
async def run_fit_zernike_wavefront(ctx: ProjectCtx, args: bytes) -> str:
    if not _ZERNIKE_FIT_AVAILABLE:
        return err_payload("numpy is required for Zernike fitting", "MISSING_DEP")

    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("samples") is None:
        return json.dumps({"ok": False, "reason": "samples is required"})

    raw_samples = a["samples"]
    if not isinstance(raw_samples, list) or len(raw_samples) == 0:
        return json.dumps({"ok": False, "reason": "samples must be a non-empty list"})

    num_terms = int(a.get("num_terms", 15))

    try:
        sample_tuples = [(float(s[0]), float(s[1]), float(s[2])) for s in raw_samples]
    except (TypeError, IndexError, ValueError) as exc:
        return json.dumps({
            "ok": False,
            "reason": f"each sample must be [rho, theta, W]: {exc}",
        })

    try:
        report = fit_zernike_wavefront(sample_tuples, num_terms=num_terms)
    except ValueError as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    except TypeError as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"unexpected error: {exc}"})

    return ok_payload(report.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_analyze_wavefront_alignment
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.optics.piston_tip_tilt import (  # noqa: E402
        PistonTipTiltReport,
        analyze_wavefront_alignment,
    )
    _PISTON_TIP_TILT_AVAILABLE = True
except ImportError:
    _PISTON_TIP_TILT_AVAILABLE = False

_wavefront_alignment_spec = ToolSpec(
    name="optics_analyze_wavefront_alignment",
    description=(
        "Extract piston (Z₁), tip (Z₂), tilt (Z₃), and defocus (Z₄) Zernike\n"
        "alignment components from a sampled wavefront W(ρ,θ) and report each\n"
        "in waves at the specified wavelength.\n"
        "\n"
        "This is the most common alignment-quality metric in optical-shop testing\n"
        "(Hecht §11.3; Born & Wolf §9.2; Wyant & Creath 1992 §3).\n"
        "\n"
        "Noll j-index mapping for the four alignment terms:\n"
        "  Z₁ (j=1)  piston  = 1                    [constant OPD offset]\n"
        "  Z₂ (j=2)  tip     = 2ρ cosθ              [wavefront tilt about y-axis]\n"
        "  Z₃ (j=3)  tilt    = 2ρ sinθ              [wavefront tilt about x-axis]\n"
        "  Z₄ (j=4)  defocus = √3(2ρ²−1)            [longitudinal focus error]\n"
        "\n"
        "Input wavefront W must be in nanometres (nm). The tool divides each\n"
        "Zernike coefficient by wavelength_nm to express results in waves.\n"
        "\n"
        "Returns:\n"
        "  piston_waves         : Z₁ coefficient in waves\n"
        "  tip_waves            : Z₂ coefficient in waves\n"
        "  tilt_waves           : Z₃ coefficient in waves\n"
        "  defocus_waves        : Z₄ coefficient in waves\n"
        "  residual_rms_waves   : RMS of (W_measured − W_fitted_4terms) in waves;\n"
        "                         non-zero → higher-order aberration content present\n"
        "  dominant_misalignment: 'piston'|'tip'|'tilt'|'defocus'|'none'\n"
        "  honest_caveat        : scope limitations\n"
        "\n"
        "Honest limits:\n"
        "  * Circular unit-disk pupil only (ρ ∈ [0,1]); no obscuration or\n"
        "    elliptical aperture.\n"
        "  * Alignment analysis only: corrects rigid-body misalignment (piston,\n"
        "    tip, tilt, defocus). Does NOT characterise higher-order aberrations\n"
        "    (coma, astigmatism, spherical, etc.) — use optics_fit_zernike_wavefront\n"
        "    for full 15-term decomposition.\n"
        "  * Requires ≥ 4 wavefront samples (minimum for a 4-term fit).\n"
        "\n"
        "References: Hecht (2017) §11.3; Born & Wolf (1999) §9.2;\n"
        "Wyant & Creath (1992) Applied Optics and Optical Engineering XI ch.1;\n"
        "Noll (1976) J. Opt. Soc. Am. 66 207.\n"
        "\n"
        "Errors: {ok: false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "samples": {
                "type": "array",
                "description": (
                    "List of wavefront sample points.  Each element must be a\n"
                    "3-element array [rho, theta, W_nm] where:\n"
                    "  rho   : normalised pupil radius in [0, 1]\n"
                    "  theta : pupil angle (radians)\n"
                    "  W_nm  : wavefront OPD at this point in nanometres (nm)"
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 4,
            },
            "wavelength_nm": {
                "type": "number",
                "description": (
                    "Reference wavelength in nanometres (nm). E.g. 632.8 for HeNe. "
                    "All wave values in the report are W_nm / wavelength_nm. "
                    "Must be > 0."
                ),
            },
        },
        "required": ["samples", "wavelength_nm"],
    },
)


@register(_wavefront_alignment_spec, write=False)
async def run_wavefront_alignment(ctx: ProjectCtx, args: bytes) -> str:
    if not _PISTON_TIP_TILT_AVAILABLE:
        return err_payload("numpy is required for wavefront alignment analysis", "MISSING_DEP")

    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("samples") is None:
        return json.dumps({"ok": False, "reason": "samples is required"})
    if a.get("wavelength_nm") is None:
        return json.dumps({"ok": False, "reason": "wavelength_nm is required"})

    raw_samples = a["samples"]
    if not isinstance(raw_samples, list) or len(raw_samples) == 0:
        return json.dumps({"ok": False, "reason": "samples must be a non-empty list"})

    try:
        wavelength_nm = float(a["wavelength_nm"])
    except (TypeError, ValueError) as exc:
        return json.dumps({"ok": False, "reason": f"wavelength_nm must be a number: {exc}"})

    try:
        sample_tuples = [(float(s[0]), float(s[1]), float(s[2])) for s in raw_samples]
    except (TypeError, IndexError, ValueError) as exc:
        return json.dumps({
            "ok": False,
            "reason": f"each sample must be [rho, theta, W_nm]: {exc}",
        })

    try:
        report = analyze_wavefront_alignment(sample_tuples, wavelength_nm=wavelength_nm)
    except ValueError as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    except TypeError as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"unexpected error: {exc}"})

    return ok_payload(report.to_dict())


# ---------------------------------------------------------------------------
# Tool: optics_compute_spot_diagram
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.spot_diagram import (  # noqa: E402
    SpotDiagramResult,
    compute_spot_diagram,
)

_spot_diagram_spec = ToolSpec(
    name="optics_compute_spot_diagram",
    description=(
        "Trace a fan of rays through a sequential lens system and compute the\n"
        "spot diagram at the paraxial image plane.\n"
        "\n"
        "Algorithm (Hecht 'Optics' 5e §6.3 / Welford 'Aberrations' §6):\n"
        "  1. Generate a ceil(sqrt(num_rays)) × ceil(sqrt(num_rays)) Cartesian\n"
        "     pupil grid over the unit disk (Welford §8.2 uniform sampling).\n"
        "  2. Trace each ray through the lens stack using exact meridional Snell\n"
        "     + Newton-Raphson conic intersect (Welford §5.2-5.3).\n"
        "  3. Collect (x, y) intercepts at the paraxial image plane:\n"
        "       y_img : exact meridional trace result\n"
        "       x_img : first-order sagittal estimate (Hecht §5.7)\n"
        "  4. Compute:\n"
        "       centroid          = (mean_x, mean_y)\n"
        "       rms_radius_mm     = sqrt(mean((xi-cx)^2 + (yi-cy)^2))  [Welford §8.2]\n"
        "       encircled_80pct   = radius enclosing 80% of rays from centroid [Hecht §6.3]\n"
        "  5. Render SVG with RMS ring (red), EE80 ring (green), Airy-disk ring (orange),\n"
        "     centroid marker, and scale bar.\n"
        "\n"
        "Surface definition (lens_system_dict.surfaces list):\n"
        "  c  : curvature 1/R (mm^-1). 0 = flat.\n"
        "  t  : thickness to NEXT surface vertex (mm). Last surface: 0.\n"
        "  n  : refractive index of medium AFTER this surface (>= 1.0).\n"
        "  k  : conic constant (default 0 = sphere).\n"
        "\n"
        "Optional lens_system_dict keys:\n"
        "  aperture_radius_mm : entrance-pupil half-diameter (mm, default 10).\n"
        "  n_object           : object-space refractive index (default 1.0).\n"
        "\n"
        "Oracle (Hecht §6.3):\n"
        "  BK7 biconvex (R1=+50, R2=-50, n=1.5168, t=5mm), 0° field, aperture 5mm:\n"
        "    rms_radius_mm > 0 (spherical aberration).\n"
        "  Same lens at 10° field: rms_radius > on-axis rms (coma grows off-axis).\n"
        "  Ideal thin lens (paraxial, no aberrations): rms ≈ 0.\n"
        "\n"
        "Returns:\n"
        "  image_points_xy           : list of [x_mm, y_mm] intercepts\n"
        "  rms_radius_mm             : 2-D RMS spot radius (mm)\n"
        "  encircled_80pct_radius_mm : radius enclosing 80% of rays (mm)\n"
        "  centroid_xy               : [x_mean, y_mean] (mm)\n"
        "  svg_diagram               : SVG string\n"
        "  honest_caveat             : scope limitations\n"
        "  n_rays                    : number of rays successfully traced\n"
        "\n"
        "HONEST FLAGS:\n"
        "  * Monochromatic only — wavelength_nm used for Airy reference only;\n"
        "    chromatic aberration NOT modelled.\n"
        "  * Sagittal (x) intercepts are first-order estimates; rigorous x requires\n"
        "    full 3-D skew-ray tracing.\n"
        "  * Physical aperture clipping not applied.\n"
        "  * encircled_80pct is geometric (ray-counting), not diffraction-based.\n"
        "  * Stop assumed at first surface.\n"
        "\n"
        "References: Hecht (2017) §6.3, §10.2; Welford (1986) §5.2-5.3, §6, §8.2.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lens_system_dict": {
                "type": "object",
                "description": (
                    "Lens system description with key 'surfaces' (list of surface dicts, "
                    "each with c, t, n; optional k). "
                    "Optional keys: aperture_radius_mm (default 10), n_object (default 1.0)."
                ),
                "properties": {
                    "surfaces": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "c": {"type": "number", "description": "Curvature 1/R (mm^-1). 0 = flat."},
                                "t": {"type": "number", "description": "Thickness to next surface (mm)."},
                                "n": {"type": "number", "description": "Refractive index after surface (>= 1.0)."},
                                "k": {"type": "number", "description": "Conic constant (default 0 = sphere)."},
                            },
                            "required": ["c", "t", "n"],
                        },
                    },
                    "aperture_radius_mm": {
                        "type": "number",
                        "description": "Entrance-pupil half-diameter (mm). Default 10.",
                    },
                    "n_object": {
                        "type": "number",
                        "description": "Refractive index of object space. Default 1.0.",
                    },
                },
                "required": ["surfaces"],
            },
            "field_angle_deg": {
                "type": "number",
                "description": "Field angle (degrees). 0 = on-axis.",
            },
            "wavelength_nm": {
                "type": "number",
                "description": (
                    "Wavelength (nm). Used for Airy-disk reference only; "
                    "chromatic aberration not modelled. E.g. 550.0 for green."
                ),
            },
            "num_rays": {
                "type": "integer",
                "description": (
                    "Target number of rays to trace (default 49). "
                    "A ceil(sqrt(num_rays)) grid is built; actual count may be slightly less."
                ),
            },
        },
        "required": ["lens_system_dict", "field_angle_deg", "wavelength_nm"],
    },
)


@register(_spot_diagram_spec, write=False)
async def run_compute_spot_diagram(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("lens_system_dict") is None:
        return json.dumps({"ok": False, "reason": "lens_system_dict is required"})
    if a.get("field_angle_deg") is None:
        return json.dumps({"ok": False, "reason": "field_angle_deg is required"})
    if a.get("wavelength_nm") is None:
        return json.dumps({"ok": False, "reason": "wavelength_nm is required"})

    kwargs: dict = {}
    if "num_rays" in a:
        kwargs["num_rays"] = int(a["num_rays"])

    result = compute_spot_diagram(
        a["lens_system_dict"],
        a["field_angle_deg"],
        a["wavelength_nm"],
        **kwargs,
    )
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: optics_compute_sagitta_arrow_chart
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.sagitta_arrow_chart import (  # noqa: E402
    AsphericSurfaceSpec,
    compute_sagitta_arrow_chart,
)

_sagitta_arrow_chart_spec = ToolSpec(
    name="optics_compute_sagitta_arrow_chart",
    description=(
        "Compute the sagitta z(r) of a conic + even-power aspheric optical surface\n"
        "across the clear aperture radius and produce an SVG chart with sagittal\n"
        "arrow markers showing local slope dz/dr.\n"
        "\n"
        "Standard surface formula (ISO 10110-12 §6.2 / Welford §3.3):\n"
        "\n"
        "  z(r) = c·r² / (1 + √(1−(1+k)·c²·r²))  +  Σ aᵢ·r^(2i+4)\n"
        "\n"
        "where c = 1/R, k = conic constant, and aᵢ are even-power aspheric\n"
        "coefficients (a₀ multiplies r⁴, a₁ → r⁶, etc.).\n"
        "\n"
        "Conic constant guide:\n"
        "  k =  0   → sphere\n"
        "  k = -1   → paraboloid\n"
        "  k < -1   → hyperboloid\n"
        "  k > -1 (≠0) → oblate / prolate ellipsoid\n"
        "\n"
        "Returns:\n"
        "  sagitta_samples         : list of [r, z] pairs (mm)\n"
        "  max_sagitta_mm          : z at the aperture edge\n"
        "  conic_only_sagitta_mm   : edge z from conic term only\n"
        "  aspheric_contribution_mm: max_sagitta − conic_only\n"
        "  svg_chart               : SVG string (polyline + arrow markers + axes)\n"
        "  honest_caveat           : scope limitations\n"
        "\n"
        "HONEST FLAGS:\n"
        "  * Conic + even-power polynomial asphere only (ISO 10110-12 §6.2).\n"
        "  * NO Zernike surfaces, freeform/XY polynomial, Q-polynomial, or\n"
        "    off-axis / tilted / decentred surfaces.\n"
        "  * Arrow markers show dz/dr (local slope), not the surface normal.\n"
        "  * Validity requires (1+k)·c²·r² ≤ 1 at the aperture edge.\n"
        "\n"
        "References: Welford §3.3; ISO 10110-12:2019.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "radius_mm": {
                "type": "number",
                "description": (
                    "Paraxial radius of curvature R (mm). Non-zero and finite. "
                    "c = 1/R. Use a large value (e.g. 1e12) for a flat surface."
                ),
            },
            "conic_k": {
                "type": "number",
                "description": (
                    "Conic constant k. 0 = sphere, -1 = paraboloid, "
                    "< -1 = hyperboloid, > 0 = oblate ellipsoid."
                ),
            },
            "aspheric_coeffs": {
                "type": "array",
                "description": (
                    "Even-power aspheric coefficients [a₀, a₁, a₂, …] (mm^-3, mm^-5, …). "
                    "a₀ multiplies r⁴, a₁ multiplies r⁶, etc. "
                    "Pass [] for a pure conic surface."
                ),
                "items": {"type": "number"},
            },
            "clear_aperture_radius_mm": {
                "type": "number",
                "description": "Semi-diameter of the clear aperture (mm). Must be > 0.",
            },
            "num_samples": {
                "type": "integer",
                "description": (
                    "Number of radial sample points (default 50). "
                    "Samples are at r = i·R_ap/num_samples for i = 0…num_samples."
                ),
            },
        },
        "required": [
            "radius_mm",
            "conic_k",
            "aspheric_coeffs",
            "clear_aperture_radius_mm",
        ],
    },
)


@register(_sagitta_arrow_chart_spec, write=False)
async def run_compute_sagitta_arrow_chart(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for _fname in ("radius_mm", "conic_k", "aspheric_coeffs", "clear_aperture_radius_mm"):
        if a.get(_fname) is None:
            return json.dumps({"ok": False, "reason": f"{_fname} is required"})

    spec = AsphericSurfaceSpec(
        radius_mm=float(a["radius_mm"]),
        conic_k=float(a["conic_k"]),
        aspheric_coeffs=[float(x) for x in a["aspheric_coeffs"]],
        clear_aperture_radius_mm=float(a["clear_aperture_radius_mm"]),
    )

    kwargs: dict = {}
    if "num_samples" in a:
        kwargs["num_samples"] = int(a["num_samples"])

    result = compute_sagitta_arrow_chart(spec, **kwargs)
    if isinstance(result, dict):
        return json.dumps(result)
    return ok_payload(result.to_dict())
