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
