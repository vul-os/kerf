"""
kerf_cad_core.acoustics.tools — LLM tool wrappers for engineering acoustics.

Registers tools with the Kerf tool registry:

  acoustics_spl_sum             — logarithmic sum of SPL values
  acoustics_spl_subtract        — background-noise subtraction
  acoustics_spl_average         — energy-average (Leq)
  acoustics_point_source        — SPL at distance from point source
  acoustics_line_source         — SPL at distance from line source
  acoustics_inverse_square      — ΔL for distance change (point source)
  acoustics_sabine_rt60         — Sabine reverberation time
  acoustics_eyring_rt60         — Eyring reverberation time
  acoustics_room_constant       — room constant R
  acoustics_reverberant_spl     — reverberant-field SPL contribution
  acoustics_mass_law_tl         — mass-law transmission loss
  acoustics_composite_tl        — composite partition TL
  acoustics_spl_transmitted     — SPL after barrier
  acoustics_a_weighting         — A-weighting offset at a frequency
  acoustics_c_weighting         — C-weighting offset at a frequency
  acoustics_apply_weighting     — apply A/C weighting to octave-band SPLs
  acoustics_octave_combine      — combine octave bands to single level
  acoustics_nc_rating           — NC noise criteria rating
  acoustics_nr_rating           — NR noise rating curve
  acoustics_duct_attenuation    — lined/unlined duct insertion loss
  acoustics_duct_breakout       — breakout noise through duct wall
  acoustics_duct_regen          — regenerated noise from duct fitting
  acoustics_lw_from_lp          — Lw from measured Lp at distance
  acoustics_lp_from_lw          — Lp at distance from Lw

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
ISO 9613-1:1993  — Attenuation of sound during propagation outdoors
ISO 140-3:1995   — Measurement of airborne sound insulation
ASHRAE HVAC Applications 2019, Chapter 48
Beranek & Ver "Noise and Vibration Control Engineering" (1992)

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.acoustics.sound import (
    spl_sum,
    spl_subtract,
    spl_average,
    point_source_attenuation,
    line_source_attenuation,
    inverse_square_delta,
    sabine_rt60,
    eyring_rt60,
    room_constant,
    reverberant_spl,
    mass_law_tl,
    composite_tl,
    spl_transmitted,
    a_weighting_offset,
    c_weighting_offset,
    apply_weighting,
    octave_band_combine,
    nc_rating,
    nr_rating,
    duct_attenuation,
    duct_breakout_spl,
    duct_regen_spl,
    lw_from_lp,
    lp_from_lw,
)


# ---------------------------------------------------------------------------
# Tool: acoustics_spl_sum
# ---------------------------------------------------------------------------

_spl_sum_spec = ToolSpec(
    name="acoustics_spl_sum",
    description=(
        "Logarithmic (energy) sum of multiple sound pressure levels.\n"
        "\n"
        "Formula: L_total = 10·log₁₀(Σ 10^(Lᵢ/10))\n"
        "\n"
        "Use when combining SPLs from multiple simultaneous noise sources.\n"
        "Example: two identical 70 dB sources sum to ≈ 73 dB, not 140 dB.\n"
        "\n"
        "Errors: {ok:false, reason} for empty list or non-numeric values.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "levels_db": {
                "type": "array",
                "items": {"type": "number"},
                "description": "List of SPL values in dB. Must contain at least one element.",
            },
        },
        "required": ["levels_db"],
    },
)


@register(_spl_sum_spec, write=False)
async def run_acoustics_spl_sum(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    levels = a.get("levels_db")
    if levels is None:
        return json.dumps({"ok": False, "reason": "levels_db is required"})

    result = spl_sum(levels)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_spl_subtract
# ---------------------------------------------------------------------------

_spl_subtract_spec = ToolSpec(
    name="acoustics_spl_subtract",
    description=(
        "Subtract a background noise level from a total measurement to recover "
        "the source SPL.\n"
        "\n"
        "Formula: L_source = 10·log₁₀(10^(L_total/10) − 10^(L_bg/10))\n"
        "\n"
        "Requires spl_total > spl_bg.  Issues a warning if the difference is < 3 dB "
        "(high uncertainty region).\n"
        "\n"
        "Errors: {ok:false, reason} if spl_bg >= spl_total.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "spl_total": {
                "type": "number",
                "description": "Total SPL measured with source present (dB).",
            },
            "spl_bg": {
                "type": "number",
                "description": "Background SPL measured without source (dB).",
            },
        },
        "required": ["spl_total", "spl_bg"],
    },
)


@register(_spl_subtract_spec, write=False)
async def run_acoustics_spl_subtract(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("spl_total") is None:
        return json.dumps({"ok": False, "reason": "spl_total is required"})
    if a.get("spl_bg") is None:
        return json.dumps({"ok": False, "reason": "spl_bg is required"})

    result = spl_subtract(a["spl_total"], a["spl_bg"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_spl_average
# ---------------------------------------------------------------------------

_spl_average_spec = ToolSpec(
    name="acoustics_spl_average",
    description=(
        "Energy-average (Leq) of multiple sound pressure levels.\n"
        "\n"
        "Formula: L_avg = 10·log₁₀((1/N) × Σ 10^(Lᵢ/10))\n"
        "\n"
        "Errors: {ok:false, reason} for empty list.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "levels_db": {
                "type": "array",
                "items": {"type": "number"},
                "description": "List of SPL values in dB.",
            },
        },
        "required": ["levels_db"],
    },
)


@register(_spl_average_spec, write=False)
async def run_acoustics_spl_average(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    levels = a.get("levels_db")
    if levels is None:
        return json.dumps({"ok": False, "reason": "levels_db is required"})

    result = spl_average(levels)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_point_source
# ---------------------------------------------------------------------------

_point_source_spec = ToolSpec(
    name="acoustics_point_source",
    description=(
        "Free-field SPL at distance r from a point source (ISO 9613).\n"
        "\n"
        "Formula: Lp = Lw + 10·log₁₀(Q / (4π r²))\n"
        "\n"
        "Directivity Q:\n"
        "  Q=1 → free field (full sphere)\n"
        "  Q=2 → hemispherical (source on hard floor)\n"
        "  Q=4 → corner source (two reflecting surfaces)\n"
        "  Q=8 → three reflecting surfaces\n"
        "\n"
        "Returns Lp (dB).  Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Lw": {
                "type": "number",
                "description": "Sound power level (dB re 1 pW = 10⁻¹² W).",
            },
            "r": {
                "type": "number",
                "description": "Distance from source to receiver (m). Must be > 0.",
            },
            "Q": {
                "type": "number",
                "description": "Directivity factor (default 1.0). Must be > 0.",
            },
        },
        "required": ["Lw", "r"],
    },
)


@register(_point_source_spec, write=False)
async def run_acoustics_point_source(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("Lw") is None:
        return json.dumps({"ok": False, "reason": "Lw is required"})
    if a.get("r") is None:
        return json.dumps({"ok": False, "reason": "r is required"})

    kwargs: dict = {}
    if "Q" in a:
        kwargs["Q"] = a["Q"]

    result = point_source_attenuation(a["Lw"], a["r"], **kwargs)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_line_source
# ---------------------------------------------------------------------------

_line_source_spec = ToolSpec(
    name="acoustics_line_source",
    description=(
        "SPL at distance r from an infinite coherent line source.\n"
        "\n"
        "Formula: Lp = Lw/m − 10·log₁₀(2π r)\n"
        "\n"
        "Applies to roads, railways, pipelines where the source length >> distance.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Lw_per_m": {
                "type": "number",
                "description": "Sound power level per metre of source (dB re 1 pW/m).",
            },
            "r": {
                "type": "number",
                "description": "Perpendicular distance from line to receiver (m). Must be > 0.",
            },
        },
        "required": ["Lw_per_m", "r"],
    },
)


@register(_line_source_spec, write=False)
async def run_acoustics_line_source(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("Lw_per_m") is None:
        return json.dumps({"ok": False, "reason": "Lw_per_m is required"})
    if a.get("r") is None:
        return json.dumps({"ok": False, "reason": "r is required"})

    result = line_source_attenuation(a["Lw_per_m"], a["r"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_inverse_square
# ---------------------------------------------------------------------------

_inverse_square_spec = ToolSpec(
    name="acoustics_inverse_square",
    description=(
        "SPL change from distance change for a point source (inverse-square law).\n"
        "\n"
        "Formula: ΔL = −20·log₁₀(r2 / r1)\n"
        "\n"
        "Returns ΔL in dB.  Negative result means SPL decreases.\n"
        "Rule of thumb: 6 dB drop per doubling of distance.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r1": {
                "type": "number",
                "description": "Reference distance (m). Must be > 0.",
            },
            "r2": {
                "type": "number",
                "description": "New distance (m). Must be > 0.",
            },
        },
        "required": ["r1", "r2"],
    },
)


@register(_inverse_square_spec, write=False)
async def run_acoustics_inverse_square(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("r1") is None:
        return json.dumps({"ok": False, "reason": "r1 is required"})
    if a.get("r2") is None:
        return json.dumps({"ok": False, "reason": "r2 is required"})

    result = inverse_square_delta(a["r1"], a["r2"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_sabine_rt60
# ---------------------------------------------------------------------------

_sabine_rt60_spec = ToolSpec(
    name="acoustics_sabine_rt60",
    description=(
        "Sabine reverberation time RT60 for a room.\n"
        "\n"
        "Formula: RT60 = 0.161 × V / A    (seconds)\n"
        "where V = room volume (m³), A = total absorption (m² sabins) = Σ(Sᵢ αᵢ).\n"
        "\n"
        "Applicable for average absorption coefficient < ~0.2 (diffuse field assumption).\n"
        "For higher absorption use acoustics_eyring_rt60 instead.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "volume_m3": {
                "type": "number",
                "description": "Room volume (m³). Must be > 0.",
            },
            "total_absorption_m2": {
                "type": "number",
                "description": (
                    "Total acoustic absorption (m²). "
                    "Computed as Σ(surface_area_m2 × absorption_coefficient). "
                    "Must be > 0."
                ),
            },
        },
        "required": ["volume_m3", "total_absorption_m2"],
    },
)


@register(_sabine_rt60_spec, write=False)
async def run_acoustics_sabine_rt60(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("volume_m3") is None:
        return json.dumps({"ok": False, "reason": "volume_m3 is required"})
    if a.get("total_absorption_m2") is None:
        return json.dumps({"ok": False, "reason": "total_absorption_m2 is required"})

    result = sabine_rt60(a["volume_m3"], a["total_absorption_m2"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_eyring_rt60
# ---------------------------------------------------------------------------

_eyring_rt60_spec = ToolSpec(
    name="acoustics_eyring_rt60",
    description=(
        "Eyring reverberation time — more accurate than Sabine for higher absorption.\n"
        "\n"
        "Formula: RT60 = 0.161 × V / (−S × ln(1 − α_avg))    (seconds)\n"
        "\n"
        "Recommended when the average absorption coefficient α > 0.2.\n"
        "alpha_avg must be strictly between 0 and 1.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "volume_m3": {
                "type": "number",
                "description": "Room volume (m³). Must be > 0.",
            },
            "S_m2": {
                "type": "number",
                "description": "Total room surface area (m²). Must be > 0.",
            },
            "alpha_avg": {
                "type": "number",
                "description": "Average absorption coefficient (0 < α < 1).",
            },
        },
        "required": ["volume_m3", "S_m2", "alpha_avg"],
    },
)


@register(_eyring_rt60_spec, write=False)
async def run_acoustics_eyring_rt60(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("volume_m3", "S_m2", "alpha_avg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = eyring_rt60(a["volume_m3"], a["S_m2"], a["alpha_avg"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_room_constant
# ---------------------------------------------------------------------------

_room_constant_spec = ToolSpec(
    name="acoustics_room_constant",
    description=(
        "Room constant R used in combined direct + reverberant field SPL calculations.\n"
        "\n"
        "Formula: R = S × α / (1 − α)    (m²)\n"
        "\n"
        "Higher R means more absorption (quieter reverberant field).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "S_m2": {
                "type": "number",
                "description": "Total room surface area (m²). Must be > 0.",
            },
            "alpha_avg": {
                "type": "number",
                "description": "Average absorption coefficient (0 < α < 1).",
            },
        },
        "required": ["S_m2", "alpha_avg"],
    },
)


@register(_room_constant_spec, write=False)
async def run_acoustics_room_constant(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("S_m2", "alpha_avg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = room_constant(a["S_m2"], a["alpha_avg"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_reverberant_spl
# ---------------------------------------------------------------------------

_reverberant_spl_spec = ToolSpec(
    name="acoustics_reverberant_spl",
    description=(
        "Reverberant-field SPL contribution from a source with known Lw.\n"
        "\n"
        "Formula: Lp_rev = Lw + 10·log₁₀(4 / R)\n"
        "\n"
        "Use this to assess the diffuse-field noise level away from direct sound.\n"
        "Combine with direct-field SPL (acoustics_point_source) for total Lp.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Lw": {
                "type": "number",
                "description": "Sound power level (dB re 1 pW).",
            },
            "R": {
                "type": "number",
                "description": "Room constant R (m²) from acoustics_room_constant. Must be > 0.",
            },
        },
        "required": ["Lw", "R"],
    },
)


@register(_reverberant_spl_spec, write=False)
async def run_acoustics_reverberant_spl(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("Lw") is None:
        return json.dumps({"ok": False, "reason": "Lw is required"})
    if a.get("R") is None:
        return json.dumps({"ok": False, "reason": "R is required"})

    result = reverberant_spl(a["Lw"], a["R"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_mass_law_tl
# ---------------------------------------------------------------------------

_mass_law_tl_spec = ToolSpec(
    name="acoustics_mass_law_tl",
    description=(
        "Mass-law transmission loss (TL) for a single-leaf partition.\n"
        "\n"
        "Formula (field-incidence, ISO 140-3):\n"
        "    TL = 20·log₁₀(m × f) − 47    (dB)\n"
        "\n"
        "where m = surface density (kg/m²), f = frequency (Hz).\n"
        "Valid for limp homogeneous panels below the coincidence frequency.\n"
        "Issues a warning if TL < 0 (formula not applicable at low mass/frequency).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surface_density_kg_m2": {
                "type": "number",
                "description": "Surface density (kg/m²). Must be > 0.",
            },
            "freq_hz": {
                "type": "number",
                "description": "Frequency (Hz). Must be > 0.",
            },
        },
        "required": ["surface_density_kg_m2", "freq_hz"],
    },
)


@register(_mass_law_tl_spec, write=False)
async def run_acoustics_mass_law_tl(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("surface_density_kg_m2") is None:
        return json.dumps({"ok": False, "reason": "surface_density_kg_m2 is required"})
    if a.get("freq_hz") is None:
        return json.dumps({"ok": False, "reason": "freq_hz is required"})

    result = mass_law_tl(a["surface_density_kg_m2"], a["freq_hz"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_composite_tl
# ---------------------------------------------------------------------------

_composite_tl_spec = ToolSpec(
    name="acoustics_composite_tl",
    description=(
        "Composite partition transmission loss from multiple parallel elements "
        "(e.g. wall with a window and a door).\n"
        "\n"
        "Each element: {area_m2: <float>, tl_db: <float>}\n"
        "Formula: τ_avg = Σ(Sᵢ τᵢ)/ΣSᵢ  →  TL = −10·log₁₀(τ_avg)\n"
        "\n"
        "A single weak element (window) can dominate and reduce overall TL significantly.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": (
                    "List of partition elements. Each element must have "
                    "'area_m2' (m²) and 'tl_db' (dB)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "area_m2": {"type": "number"},
                        "tl_db":   {"type": "number"},
                    },
                    "required": ["area_m2", "tl_db"],
                },
            },
        },
        "required": ["elements"],
    },
)


@register(_composite_tl_spec, write=False)
async def run_acoustics_composite_tl(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("elements") is None:
        return json.dumps({"ok": False, "reason": "elements is required"})

    result = composite_tl(a["elements"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_spl_transmitted
# ---------------------------------------------------------------------------

_spl_transmitted_spec = ToolSpec(
    name="acoustics_spl_transmitted",
    description=(
        "SPL on the receiving side of a barrier given source-side SPL and TL.\n"
        "\n"
        "Formula: Lp_transmitted = Lp_source − TL\n"
        "\n"
        "Issues a warning if tl_db < 0 (physically unusual).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "spl_source": {
                "type": "number",
                "description": "Source-side SPL (dB).",
            },
            "tl_db": {
                "type": "number",
                "description": "Transmission loss of the barrier (dB). Normally >= 0.",
            },
        },
        "required": ["spl_source", "tl_db"],
    },
)


@register(_spl_transmitted_spec, write=False)
async def run_acoustics_spl_transmitted(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("spl_source") is None:
        return json.dumps({"ok": False, "reason": "spl_source is required"})
    if a.get("tl_db") is None:
        return json.dumps({"ok": False, "reason": "tl_db is required"})

    result = spl_transmitted(a["spl_source"], a["tl_db"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_a_weighting
# ---------------------------------------------------------------------------

_a_weighting_spec = ToolSpec(
    name="acoustics_a_weighting",
    description=(
        "A-weighting frequency correction at a given frequency (IEC 61672-1).\n"
        "\n"
        "A-weighting approximates human hearing sensitivity across the audio spectrum.\n"
        "Add the returned offset_db to the unweighted SPL to obtain dB(A).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {
                "type": "number",
                "description": "Frequency (Hz). Must be > 0.",
            },
        },
        "required": ["freq_hz"],
    },
)


@register(_a_weighting_spec, write=False)
async def run_acoustics_a_weighting(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("freq_hz") is None:
        return json.dumps({"ok": False, "reason": "freq_hz is required"})

    result = a_weighting_offset(a["freq_hz"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_c_weighting
# ---------------------------------------------------------------------------

_c_weighting_spec = ToolSpec(
    name="acoustics_c_weighting",
    description=(
        "C-weighting frequency correction at a given frequency (IEC 61672-1).\n"
        "\n"
        "C-weighting is nearly flat across the audible range; used for peak "
        "sound pressure levels and low-frequency noise assessment.\n"
        "Add the returned offset_db to the unweighted SPL to obtain dB(C).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {
                "type": "number",
                "description": "Frequency (Hz). Must be > 0.",
            },
        },
        "required": ["freq_hz"],
    },
)


@register(_c_weighting_spec, write=False)
async def run_acoustics_c_weighting(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("freq_hz") is None:
        return json.dumps({"ok": False, "reason": "freq_hz is required"})

    result = c_weighting_offset(a["freq_hz"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_apply_weighting
# ---------------------------------------------------------------------------

_apply_weighting_spec = ToolSpec(
    name="acoustics_apply_weighting",
    description=(
        "Apply A or C weighting corrections to octave-band SPL measurements.\n"
        "\n"
        "Accepted octave-band centre frequencies (Hz): "
        "31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000.\n"
        "\n"
        "Returns a dict of weighted SPL per band.  "
        "Follow with acoustics_octave_combine to get a single dB(A) or dB(C) number.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "octave_band_spls": {
                "type": "object",
                "description": (
                    "Object mapping centre frequency (Hz) to unweighted SPL (dB). "
                    "Keys should be integer Hz values as strings or numbers."
                ),
                "additionalProperties": {"type": "number"},
            },
            "weighting": {
                "type": "string",
                "enum": ["A", "C"],
                "description": "Weighting network: 'A' (default) or 'C'.",
            },
        },
        "required": ["octave_band_spls"],
    },
)


@register(_apply_weighting_spec, write=False)
async def run_acoustics_apply_weighting(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("octave_band_spls") is None:
        return json.dumps({"ok": False, "reason": "octave_band_spls is required"})

    kwargs: dict = {}
    if "weighting" in a:
        kwargs["weighting"] = a["weighting"]

    result = apply_weighting(a["octave_band_spls"], **kwargs)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_octave_combine
# ---------------------------------------------------------------------------

_octave_combine_spec = ToolSpec(
    name="acoustics_octave_combine",
    description=(
        "Combine weighted octave-band SPL values into a single overall level.\n"
        "\n"
        "Formula: L_total = 10·log₁₀(Σ 10^(Lᵢ/10))\n"
        "\n"
        "Typically used after acoustics_apply_weighting to get a single dB(A) value.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "weighted_spls": {
                "type": "object",
                "description": "Object mapping frequency (Hz) to weighted SPL (dB).",
                "additionalProperties": {"type": "number"},
            },
        },
        "required": ["weighted_spls"],
    },
)


@register(_octave_combine_spec, write=False)
async def run_acoustics_octave_combine(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("weighted_spls") is None:
        return json.dumps({"ok": False, "reason": "weighted_spls is required"})

    result = octave_band_combine(a["weighted_spls"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_nc_rating
# ---------------------------------------------------------------------------

_nc_rating_spec = ToolSpec(
    name="acoustics_nc_rating",
    description=(
        "Noise Criteria (NC) rating for an octave-band spectrum.\n"
        "\n"
        "The NC rating is the lowest NC curve that the measured spectrum does not exceed "
        "in any octave band (63–8000 Hz).  Range: NC-15 to NC-70.\n"
        "\n"
        "Typical design targets:\n"
        "  Private offices / bedrooms: NC-25 to NC-35\n"
        "  Open offices:               NC-35 to NC-45\n"
        "  Mechanical rooms:           NC-60 to NC-70\n"
        "\n"
        "Issues a warning if the spectrum exceeds NC-70.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "octave_band_spls": {
                "type": "object",
                "description": (
                    "Object mapping centre frequency (Hz) to SPL (dB). "
                    "Standard bands: 63, 125, 250, 500, 1000, 2000, 4000, 8000."
                ),
                "additionalProperties": {"type": "number"},
            },
        },
        "required": ["octave_band_spls"],
    },
)


@register(_nc_rating_spec, write=False)
async def run_acoustics_nc_rating(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("octave_band_spls") is None:
        return json.dumps({"ok": False, "reason": "octave_band_spls is required"})

    result = nc_rating(a["octave_band_spls"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_nr_rating
# ---------------------------------------------------------------------------

_nr_rating_spec = ToolSpec(
    name="acoustics_nr_rating",
    description=(
        "Noise Rating (NR) curve level for an octave-band spectrum (ISO 1996-1).\n"
        "\n"
        "The NR rating is the lowest NR curve at or above the measured spectrum.\n"
        "Range: NR-0 to NR-75.\n"
        "\n"
        "Typical design limits:\n"
        "  Concert halls:  NR-15 to NR-20\n"
        "  Offices:        NR-35 to NR-45\n"
        "  Factories:      NR-65 to NR-75\n"
        "\n"
        "Issues a warning if the spectrum exceeds NR-75.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "octave_band_spls": {
                "type": "object",
                "description": (
                    "Object mapping centre frequency (Hz) to SPL (dB). "
                    "Standard bands: 63, 125, 250, 500, 1000, 2000, 4000, 8000."
                ),
                "additionalProperties": {"type": "number"},
            },
        },
        "required": ["octave_band_spls"],
    },
)


@register(_nr_rating_spec, write=False)
async def run_acoustics_nr_rating(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("octave_band_spls") is None:
        return json.dumps({"ok": False, "reason": "octave_band_spls is required"})

    result = nr_rating(a["octave_band_spls"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_duct_attenuation
# ---------------------------------------------------------------------------

_duct_attenuation_spec = ToolSpec(
    name="acoustics_duct_attenuation",
    description=(
        "Approximate insertion loss (IL) for a straight HVAC duct section "
        "per octave band (ASHRAE 2019, Chapter 48).\n"
        "\n"
        "Returns per-band IL in dB for the 63–8000 Hz octave bands.\n"
        "\n"
        "lining options: 'lined' (fibrous insulation inside duct) or 'unlined'.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "length_m": {
                "type": "number",
                "description": "Duct section length (m). Must be > 0.",
            },
            "diam_m": {
                "type": "number",
                "description": "Hydraulic diameter (m). Must be > 0.",
            },
            "lining": {
                "type": "string",
                "enum": ["lined", "unlined"],
                "description": "'lined' or 'unlined' (default 'unlined').",
            },
        },
        "required": ["length_m", "diam_m"],
    },
)


@register(_duct_attenuation_spec, write=False)
async def run_acoustics_duct_attenuation(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("length_m") is None:
        return json.dumps({"ok": False, "reason": "length_m is required"})
    if a.get("diam_m") is None:
        return json.dumps({"ok": False, "reason": "diam_m is required"})

    kwargs: dict = {}
    if "lining" in a:
        kwargs["lining"] = a["lining"]

    result = duct_attenuation(a["length_m"], a["diam_m"], **kwargs)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_duct_breakout
# ---------------------------------------------------------------------------

_duct_breakout_spec = ToolSpec(
    name="acoustics_duct_breakout",
    description=(
        "Breakout noise SPL radiated through a duct wall section (ASHRAE 2019).\n"
        "\n"
        "Formula: Lp_out = Lw_in − TL + 10·log₁₀(perimeter × length)\n"
        "\n"
        "Use to assess noise break-out through unlined sheet metal ducts.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Lw_in": {
                "type": "number",
                "description": "Sound power level inside the duct (dB re 1 pW).",
            },
            "length_m": {
                "type": "number",
                "description": "Duct section length (m). Must be > 0.",
            },
            "perimeter_m": {
                "type": "number",
                "description": "Duct cross-section perimeter (m). Must be > 0.",
            },
            "tl_db": {
                "type": "number",
                "description": "Transmission loss of the duct wall (dB).",
            },
        },
        "required": ["Lw_in", "length_m", "perimeter_m", "tl_db"],
    },
)


@register(_duct_breakout_spec, write=False)
async def run_acoustics_duct_breakout(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Lw_in", "length_m", "perimeter_m", "tl_db"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = duct_breakout_spl(a["Lw_in"], a["length_m"], a["perimeter_m"], a["tl_db"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_duct_regen
# ---------------------------------------------------------------------------

_duct_regen_spec = ToolSpec(
    name="acoustics_duct_regen",
    description=(
        "Approximate regenerated (self-generated) noise Lw from a duct fitting "
        "(ASHRAE 2019, Chapter 48).\n"
        "\n"
        "Fitting types: 'elbow_90', 'elbow_45', 'tee_branch', 'tee_through', "
        "'reducer', 'diffuser'.\n"
        "\n"
        "Issues a warning if velocity > 15 m/s (outside typical HVAC design range).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "velocity_mps": {
                "type": "number",
                "description": "Duct air velocity upstream of fitting (m/s). Must be > 0.",
            },
            "diam_m": {
                "type": "number",
                "description": "Duct hydraulic diameter (m). Must be > 0.",
            },
            "fitting_type": {
                "type": "string",
                "enum": ["elbow_90", "elbow_45", "tee_branch", "tee_through", "reducer", "diffuser"],
                "description": "Type of fitting (default 'elbow_90').",
            },
        },
        "required": ["velocity_mps", "diam_m"],
    },
)


@register(_duct_regen_spec, write=False)
async def run_acoustics_duct_regen(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("velocity_mps") is None:
        return json.dumps({"ok": False, "reason": "velocity_mps is required"})
    if a.get("diam_m") is None:
        return json.dumps({"ok": False, "reason": "diam_m is required"})

    kwargs: dict = {}
    if "fitting_type" in a:
        kwargs["fitting_type"] = a["fitting_type"]

    result = duct_regen_spl(a["velocity_mps"], a["diam_m"], **kwargs)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_lw_from_lp
# ---------------------------------------------------------------------------

_lw_from_lp_spec = ToolSpec(
    name="acoustics_lw_from_lp",
    description=(
        "Estimate sound power level Lw from a measured SPL Lp at distance r.\n"
        "\n"
        "Formula (free field): Lw = Lp + 10·log₁₀(4π r² / Q)\n"
        "\n"
        "Assumes free-field conditions (no reverberant build-up).\n"
        "Q = directivity factor (1=free sphere, 2=hemisphere/hard floor).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lp_db": {
                "type": "number",
                "description": "Measured SPL at distance r_m (dB).",
            },
            "r_m": {
                "type": "number",
                "description": "Measurement distance from source (m). Must be > 0.",
            },
            "Q": {
                "type": "number",
                "description": "Directivity factor (default 1.0). Must be > 0.",
            },
        },
        "required": ["lp_db", "r_m"],
    },
)


@register(_lw_from_lp_spec, write=False)
async def run_acoustics_lw_from_lp(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("lp_db") is None:
        return json.dumps({"ok": False, "reason": "lp_db is required"})
    if a.get("r_m") is None:
        return json.dumps({"ok": False, "reason": "r_m is required"})

    kwargs: dict = {}
    if "Q" in a:
        kwargs["Q"] = a["Q"]

    result = lw_from_lp(a["lp_db"], a["r_m"], **kwargs)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: acoustics_lp_from_lw
# ---------------------------------------------------------------------------

_lp_from_lw_spec = ToolSpec(
    name="acoustics_lp_from_lw",
    description=(
        "Calculate SPL at distance r from sound power level Lw.\n"
        "\n"
        "Formula: Lp = Lw + 10·log₁₀(Q / (4π r²))\n"
        "\n"
        "Q = directivity factor:\n"
        "  Q=1 → free field (full sphere)\n"
        "  Q=2 → hemispherical (hard floor)\n"
        "  Q=4 → two perpendicular reflecting surfaces\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lw_db": {
                "type": "number",
                "description": "Sound power level (dB re 1 pW).",
            },
            "r_m": {
                "type": "number",
                "description": "Distance from source to receiver (m). Must be > 0.",
            },
            "Q": {
                "type": "number",
                "description": "Directivity factor (default 1.0). Must be > 0.",
            },
        },
        "required": ["lw_db", "r_m"],
    },
)


@register(_lp_from_lw_spec, write=False)
async def run_acoustics_lp_from_lw(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("lw_db") is None:
        return json.dumps({"ok": False, "reason": "lw_db is required"})
    if a.get("r_m") is None:
        return json.dumps({"ok": False, "reason": "r_m is required"})

    kwargs: dict = {}
    if "Q" in a:
        kwargs["Q"] = a["Q"]

    result = lp_from_lw(a["lw_db"], a["r_m"], **kwargs)
    return ok_payload(result) if result["ok"] else json.dumps(result)
