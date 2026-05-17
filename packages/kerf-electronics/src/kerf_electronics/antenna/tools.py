"""
Antenna element design — LLM tools.

Provides LLM-callable tools:

  antenna_half_wave_dipole    — half-wave dipole resonant dimensions, impedance, gain
  antenna_monopole            — quarter-wave monopole over ground (image theory)
  antenna_small_loop          — electrically-small loop radiation resistance & gain
  antenna_microstrip_patch    — rectangular microstrip patch design (W, L, inset feed)
  antenna_yagi_uda            — Yagi-Uda gain & element dimensions
  antenna_helical_axial       — axial-mode helical gain, HPBW, axial ratio
  antenna_horn_gain           — horn antenna gain from aperture dimensions
  antenna_directivity_gain    — directivity ↔ gain ↔ efficiency triangle
  antenna_beamwidth_dir       — beamwidth → directivity (Kraus approximation)
  antenna_aperture_eff        — effective aperture and aperture efficiency
  antenna_near_far_field      — Fraunhofer (far-field) boundary distances
  antenna_polarization_ar     — polarisation loss factor from axial ratio
  antenna_ground_plane_image  — ground-plane image impedance & gain effect
  antenna_array_factor_ula    — uniform linear array factor, grating-lobe check
  antenna_vswr_bw             — VSWR bandwidth from antenna Q factor

All handlers follow the kerf never-raise contract:
  Success: {"ok": True, ...}  via ok_payload
  Failure: {"ok": False, "error": ..., "code": ...}  via err_payload
  Never raise.

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register

from kerf_electronics.antenna.element import (
    half_wave_dipole,
    monopole,
    small_loop,
    microstrip_patch,
    yagi_uda,
    helical_axial,
    horn_gain,
    directivity_gain_efficiency,
    beamwidth_directivity,
    aperture_efficiency,
    near_far_field_boundary,
    polarization_axial_ratio,
    ground_plane_image,
    array_factor_ula,
    vswr_bandwidth_from_q,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. antenna_half_wave_dipole
# ═══════════════════════════════════════════════════════════════════════════════

_DIPOLE_SPEC = ToolSpec(
    name="antenna_half_wave_dipole",
    description=(
        "Design a half-wave dipole antenna.\n\n"
        "Returns resonant length, input impedance at the half-wave point (73.1 + j42.5 Ω), "
        "gain (2.15 dBi), directivity, E-plane HPBW (~78°), and VSWR=2 bandwidth.\n\n"
        "Reference: Balanis (2016) §4.3.\n\n"
        "Input: { freq_hz, efficiency?, wire_diameter_m? }\n"
        "Returns: { ok, resonant_length_m, R_in_ohm, X_in_ohm, gain_dbi, "
        "vswr_bw_hz, hpbw_e_plane_deg, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Operating frequency [Hz]."},
            "efficiency": {
                "type": "number",
                "description": "Radiation efficiency η (0–1, default 1.0).",
            },
            "wire_diameter_m": {
                "type": "number",
                "description": "Conductor diameter [m] (default 0.001 m = 1 mm).",
            },
        },
        "required": ["freq_hz"],
    },
)


@register(_DIPOLE_SPEC, write=False)
async def antenna_half_wave_dipole(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = half_wave_dipole(
        freq_hz=a.get("freq_hz"),
        efficiency=a.get("efficiency", 1.0),
        wire_diameter_m=a.get("wire_diameter_m", 0.001),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. antenna_monopole
# ═══════════════════════════════════════════════════════════════════════════════

_MONOPOLE_SPEC = ToolSpec(
    name="antenna_monopole",
    description=(
        "Design a quarter-wave monopole over an infinite ground plane.\n\n"
        "Uses image theory: input resistance 36.5 Ω (half the dipole value), "
        "gain 5.16 dBi.  Assumes infinite perfect ground.\n\n"
        "Reference: Balanis (2016) §4.7.\n\n"
        "Input: { freq_hz, efficiency? }\n"
        "Returns: { ok, resonant_length_m, R_in_ohm, gain_dbi, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Operating frequency [Hz]."},
            "efficiency": {
                "type": "number",
                "description": "Radiation efficiency η (0–1, default 1.0).",
            },
        },
        "required": ["freq_hz"],
    },
)


@register(_MONOPOLE_SPEC, write=False)
async def antenna_monopole(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = monopole(
        freq_hz=a.get("freq_hz"),
        efficiency=a.get("efficiency", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. antenna_small_loop
# ═══════════════════════════════════════════════════════════════════════════════

_SMALL_LOOP_SPEC = ToolSpec(
    name="antenna_small_loop",
    description=(
        "Electrically-small loop antenna design (ka < 0.5).\n\n"
        "Computes radiation resistance Rr = 31171 N² (A/λ²)², "
        "directivity 1.5, and gain.  Issues a warning when ka ≥ 0.5.\n\n"
        "Reference: Balanis (2016) §5.2.\n\n"
        "Input: { freq_hz, loop_area_m2, n_turns?, efficiency? }\n"
        "Returns: { ok, radiation_resistance_ohm, gain_dbi, ka, electrically_small, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Operating frequency [Hz]."},
            "loop_area_m2": {"type": "number", "description": "Enclosed loop area [m²]."},
            "n_turns": {
                "type": "integer",
                "description": "Number of turns (default 1).",
            },
            "efficiency": {
                "type": "number",
                "description": "Radiation efficiency η (0–1, default 1.0).",
            },
        },
        "required": ["freq_hz", "loop_area_m2"],
    },
)


@register(_SMALL_LOOP_SPEC, write=False)
async def antenna_small_loop(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = small_loop(
        freq_hz=a.get("freq_hz"),
        loop_area_m2=a.get("loop_area_m2"),
        n_turns=a.get("n_turns", 1),
        efficiency=a.get("efficiency", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. antenna_microstrip_patch
# ═══════════════════════════════════════════════════════════════════════════════

_PATCH_SPEC = ToolSpec(
    name="antenna_microstrip_patch",
    description=(
        "Design a rectangular microstrip patch antenna.\n\n"
        "Computes effective permittivity εr_eff, patch width W, resonant length L, "
        "fringing extension ΔL, edge radiation conductance, edge input impedance, "
        "and inset-feed distance y₀ for 50 Ω match.\n\n"
        "Reference: Balanis (2016) §14.2; Pozar (2012) §6.5.\n\n"
        "Input: { freq_hz, er, h_m, efficiency? }\n"
        "Returns: { ok, patch_width_m, patch_length_m, er_eff, edge_impedance_ohm, "
        "inset_feed_m, gain_dbi, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Design frequency [Hz]."},
            "er": {
                "type": "number",
                "description": "Substrate relative permittivity εr (e.g. 4.4 for FR4).",
            },
            "h_m": {
                "type": "number",
                "description": "Substrate thickness [m].",
            },
            "efficiency": {
                "type": "number",
                "description": "Radiation efficiency η (0–1, default 0.90).",
            },
        },
        "required": ["freq_hz", "er", "h_m"],
    },
)


@register(_PATCH_SPEC, write=False)
async def antenna_microstrip_patch(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = microstrip_patch(
        freq_hz=a.get("freq_hz"),
        er=a.get("er"),
        h_m=a.get("h_m"),
        efficiency=a.get("efficiency", 0.90),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. antenna_yagi_uda
# ═══════════════════════════════════════════════════════════════════════════════

_YAGI_SPEC = ToolSpec(
    name="antenna_yagi_uda",
    description=(
        "Design a Yagi-Uda antenna.\n\n"
        "Returns driven element, reflector, and director lengths and spacings, "
        "plus estimated gain and F/B ratio using Kraus empirical formulae.\n\n"
        "Reference: Balanis (2016) §10.3; Kraus (2002) Table 11-1.\n\n"
        "Input: { freq_hz, n_directors?, boom_wavelengths?, efficiency? }\n"
        "Returns: { ok, driven_length_m, reflector_length_m, director_length_m, "
        "gain_dbi, fb_ratio_db, hpbw_e_plane_deg, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Operating frequency [Hz]."},
            "n_directors": {
                "type": "integer",
                "description": "Number of director elements (0–10, default 3).",
            },
            "boom_wavelengths": {
                "type": "number",
                "description": "Total boom length in wavelengths (default 0.4 λ).",
            },
            "efficiency": {
                "type": "number",
                "description": "Radiation efficiency η (0–1, default 0.95).",
            },
        },
        "required": ["freq_hz"],
    },
)


@register(_YAGI_SPEC, write=False)
async def antenna_yagi_uda(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = yagi_uda(
        freq_hz=a.get("freq_hz"),
        n_directors=a.get("n_directors", 3),
        boom_wavelengths=a.get("boom_wavelengths", 0.4),
        efficiency=a.get("efficiency", 0.95),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. antenna_helical_axial
# ═══════════════════════════════════════════════════════════════════════════════

_HELIX_SPEC = ToolSpec(
    name="antenna_helical_axial",
    description=(
        "Design an axial-mode (end-fire) helical antenna.\n\n"
        "Valid range: 0.75 ≤ C/λ ≤ 1.33, pitch angle 12–14°.  "
        "Returns dimensions, gain, HPBW, axial ratio, and input impedance.\n\n"
        "Reference: Balanis (2016) §10.4; Kraus (2002) §7-5.\n\n"
        "Input: { freq_hz, n_turns, circumference_wavelengths?, pitch_angle_deg?, efficiency? }\n"
        "Returns: { ok, gain_dbi, hpbw_deg, axial_ratio, R_in_ohm, axial_length_m, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Operating frequency [Hz]."},
            "n_turns": {
                "type": "integer",
                "description": "Number of helix turns N (>= 3 recommended).",
            },
            "circumference_wavelengths": {
                "type": "number",
                "description": "Helix circumference C/λ (default 1.0; axial mode: 0.75–1.33).",
            },
            "pitch_angle_deg": {
                "type": "number",
                "description": "Pitch angle α [degrees] (default 12.5°; axial mode: 12–14°).",
            },
            "efficiency": {
                "type": "number",
                "description": "Radiation efficiency η (0–1, default 0.95).",
            },
        },
        "required": ["freq_hz", "n_turns"],
    },
)


@register(_HELIX_SPEC, write=False)
async def antenna_helical_axial(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = helical_axial(
        freq_hz=a.get("freq_hz"),
        n_turns=a.get("n_turns"),
        circumference_wavelengths=a.get("circumference_wavelengths", 1.0),
        pitch_angle_deg=a.get("pitch_angle_deg", 12.5),
        efficiency=a.get("efficiency", 0.95),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. antenna_horn_gain
# ═══════════════════════════════════════════════════════════════════════════════

_HORN_SPEC = ToolSpec(
    name="antenna_horn_gain",
    description=(
        "Compute horn antenna gain from aperture dimensions.\n\n"
        "G = η × ηap × 4π a b / λ², where ηap ≈ 0.51 for an optimum pyramidal horn.\n\n"
        "Reference: Balanis (2016) §13.2, §13.6.\n\n"
        "Input: { freq_hz, aperture_width_m, aperture_height_m, "
        "aperture_efficiency?, efficiency? }\n"
        "Returns: { ok, gain_dbi, hpbw_e_plane_deg, hpbw_h_plane_deg, "
        "effective_aperture_m2, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Operating frequency [Hz]."},
            "aperture_width_m": {
                "type": "number",
                "description": "Aperture width a [m] (H-plane dimension).",
            },
            "aperture_height_m": {
                "type": "number",
                "description": "Aperture height b [m] (E-plane dimension).",
            },
            "aperture_efficiency": {
                "type": "number",
                "description": "Aperture efficiency ηap (default 0.51 for optimum pyramidal horn).",
            },
            "efficiency": {
                "type": "number",
                "description": "Total radiation efficiency η (0–1, default 0.95).",
            },
        },
        "required": ["freq_hz", "aperture_width_m", "aperture_height_m"],
    },
)


@register(_HORN_SPEC, write=False)
async def antenna_horn_gain(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = horn_gain(
        freq_hz=a.get("freq_hz"),
        aperture_width_m=a.get("aperture_width_m"),
        aperture_height_m=a.get("aperture_height_m"),
        aperture_efficiency=a.get("aperture_efficiency", 0.51),
        efficiency=a.get("efficiency", 0.95),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. antenna_directivity_gain
# ═══════════════════════════════════════════════════════════════════════════════

_DGE_SPEC = ToolSpec(
    name="antenna_directivity_gain",
    description=(
        "Compute the third member of the directivity / gain / efficiency triangle.\n\n"
        "G [dBi] = 10 log10(η × D)\n\n"
        "Provide exactly 2 of the 3 parameters; the third is computed.\n\n"
        "Input: { directivity?, gain_dbi?, efficiency? }  — exactly 2 required\n"
        "Returns: { ok, directivity, gain_dbi, efficiency }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "directivity": {
                "type": "number",
                "description": "Linear directivity D (dimensionless, >= 1).",
            },
            "gain_dbi": {
                "type": "number",
                "description": "Antenna gain [dBi].",
            },
            "efficiency": {
                "type": "number",
                "description": "Radiation efficiency η (0–1).",
            },
        },
    },
)


@register(_DGE_SPEC, write=False)
async def antenna_directivity_gain(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = directivity_gain_efficiency(
        directivity=a.get("directivity"),
        gain_dbi=a.get("gain_dbi"),
        efficiency=a.get("efficiency"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. antenna_beamwidth_dir
# ═══════════════════════════════════════════════════════════════════════════════

_BWD_SPEC = ToolSpec(
    name="antenna_beamwidth_dir",
    description=(
        "Estimate directivity from E-plane and H-plane half-power beamwidths.\n\n"
        "Kraus approximation:  D ≈ 41253 / (θ_E × θ_H)  [degrees]\n"
        "Tai-Pereira:          D ≈ 72815 / (θ_E² + θ_H²)\n\n"
        "Reference: Kraus (2002) eq. 2-27; Balanis (2016) eq. 2-65/2-68.\n\n"
        "Input: { hpbw_e_deg, hpbw_h_deg }\n"
        "Returns: { ok, directivity_kraus, directivity_tai, gain_dbi_kraus, gain_dbi_tai }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hpbw_e_deg": {
                "type": "number",
                "description": "E-plane half-power beamwidth [degrees].",
            },
            "hpbw_h_deg": {
                "type": "number",
                "description": "H-plane half-power beamwidth [degrees].",
            },
        },
        "required": ["hpbw_e_deg", "hpbw_h_deg"],
    },
)


@register(_BWD_SPEC, write=False)
async def antenna_beamwidth_dir(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = beamwidth_directivity(
        hpbw_e_deg=a.get("hpbw_e_deg"),
        hpbw_h_deg=a.get("hpbw_h_deg"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. antenna_aperture_eff
# ═══════════════════════════════════════════════════════════════════════════════

_APE_SPEC = ToolSpec(
    name="antenna_aperture_eff",
    description=(
        "Compute effective aperture Aeff and (optionally) aperture efficiency ηap.\n\n"
        "Aeff = G λ² / (4π)\n"
        "If physical_aperture_m2 is given: ηap = Aeff / Ap\n\n"
        "Reference: Balanis (2016) §2.8.\n\n"
        "Input: { freq_hz, gain_dbi, physical_aperture_m2? }\n"
        "Returns: { ok, effective_aperture_m2, aperture_efficiency? }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Frequency [Hz]."},
            "gain_dbi": {"type": "number", "description": "Antenna gain [dBi]."},
            "physical_aperture_m2": {
                "type": "number",
                "description": "Physical aperture area [m²] (optional; if provided, ηap is computed).",
            },
        },
        "required": ["freq_hz", "gain_dbi"],
    },
)


@register(_APE_SPEC, write=False)
async def antenna_aperture_eff(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = aperture_efficiency(
        freq_hz=a.get("freq_hz"),
        gain_dbi=a.get("gain_dbi"),
        physical_aperture_m2=a.get("physical_aperture_m2"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. antenna_near_far_field
# ═══════════════════════════════════════════════════════════════════════════════

_NFF_SPEC = ToolSpec(
    name="antenna_near_far_field",
    description=(
        "Compute near-field / far-field boundary distances.\n\n"
        "Fraunhofer distance:    R_ff = 2D²/λ\n"
        "Reactive near-field:    R_nf = 0.62 sqrt(D³/λ)\n"
        "Plane-wave boundary:    R_pw = λ/(2π)\n\n"
        "Reference: Balanis (2016) §2.2.4.\n\n"
        "Input: { freq_hz, max_dimension_m }\n"
        "Returns: { ok, fraunhofer_distance_m, reactive_near_field_m, plane_wave_boundary_m }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Operating frequency [Hz]."},
            "max_dimension_m": {
                "type": "number",
                "description": "Maximum antenna dimension D [m].",
            },
        },
        "required": ["freq_hz", "max_dimension_m"],
    },
)


@register(_NFF_SPEC, write=False)
async def antenna_near_far_field(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = near_far_field_boundary(
        freq_hz=a.get("freq_hz"),
        max_dimension_m=a.get("max_dimension_m"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. antenna_polarization_ar
# ═══════════════════════════════════════════════════════════════════════════════

_POL_SPEC = ToolSpec(
    name="antenna_polarization_ar",
    description=(
        "Compute polarisation loss factor (PLF) from axial ratio.\n\n"
        "PLF_worst = ((AR − 1) / (AR + 1))²\n"
        "PLF_linear(τ) = cos²(τ)  for linear-to-linear with tilt τ.\n\n"
        "AR = 1 → circular; AR ≫ 1 → linear.  AR = E_major/E_minor ≥ 1.\n\n"
        "Reference: Balanis (2016) §2.12.\n\n"
        "Input: { axial_ratio, tilt_angle_deg? }\n"
        "Returns: { ok, plf_worst_case, plf_loss_db_worst, plf_linear_tilt, is_circular, is_linear }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "axial_ratio": {
                "type": "number",
                "description": "Axial ratio AR = E_max/E_min (>= 1; AR=1 = circular, AR→∞ = linear).",
            },
            "tilt_angle_deg": {
                "type": "number",
                "description": "Linear polarisation tilt angle [degrees] (default 0).",
            },
        },
        "required": ["axial_ratio"],
    },
)


@register(_POL_SPEC, write=False)
async def antenna_polarization_ar(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = polarization_axial_ratio(
        axial_ratio=a.get("axial_ratio"),
        tilt_angle_deg=a.get("tilt_angle_deg", 0.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. antenna_ground_plane_image
# ═══════════════════════════════════════════════════════════════════════════════

_GPI_SPEC = ToolSpec(
    name="antenna_ground_plane_image",
    description=(
        "Apply image theory to convert dipole parameters to monopole-over-ground.\n\n"
        "R_monopole = R_dipole / 2\n"
        "X_monopole = X_dipole / 2\n"
        "G_monopole = G_dipole + 3.01 dB  (radiation into upper half-space only)\n\n"
        "Reference: Balanis (2016) §4.7.\n\n"
        "Input: { dipole_R_in_ohm, dipole_X_in_ohm, dipole_gain_dbi }\n"
        "Returns: { ok, monopole_R_in_ohm, monopole_X_in_ohm, monopole_gain_dbi }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dipole_R_in_ohm": {
                "type": "number",
                "description": "Dipole input resistance [Ω].",
            },
            "dipole_X_in_ohm": {
                "type": "number",
                "description": "Dipole input reactance [Ω].",
            },
            "dipole_gain_dbi": {
                "type": "number",
                "description": "Dipole gain [dBi].",
            },
        },
        "required": ["dipole_R_in_ohm", "dipole_X_in_ohm", "dipole_gain_dbi"],
    },
)


@register(_GPI_SPEC, write=False)
async def antenna_ground_plane_image(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = ground_plane_image(
        dipole_R_in_ohm=a.get("dipole_R_in_ohm"),
        dipole_X_in_ohm=a.get("dipole_X_in_ohm"),
        dipole_gain_dbi=a.get("dipole_gain_dbi"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. antenna_array_factor_ula
# ═══════════════════════════════════════════════════════════════════════════════

_ULA_SPEC = ToolSpec(
    name="antenna_array_factor_ula",
    description=(
        "Uniform linear array (ULA) factor with beam steering and grating-lobe check.\n\n"
        "Array gain: G = 10 log10(N) [dBi over element gain]\n"
        "Grating-lobe condition: d/λ ≥ 1/(1 + |cos θ₀|)\n"
        "Issues a warning when grating lobes are present.\n\n"
        "Reference: Balanis (2016) §6.2.\n\n"
        "Input: { freq_hz, n_elements, element_spacing_m, scan_angle_deg?, check_grating_lobes? }\n"
        "Returns: { ok, array_gain_dbi, hpbw_deg, grating_lobe_present, "
        "grating_lobe_angles_deg, null_angles_deg, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Operating frequency [Hz]."},
            "n_elements": {
                "type": "integer",
                "description": "Number of array elements N.",
            },
            "element_spacing_m": {
                "type": "number",
                "description": "Element spacing d [m].",
            },
            "scan_angle_deg": {
                "type": "number",
                "description": "Main-beam scan angle θ₀ [degrees] (0=endfire, 90=broadside, default 90).",
            },
            "check_grating_lobes": {
                "type": "boolean",
                "description": "Issue warning if grating lobes are present (default true).",
            },
        },
        "required": ["freq_hz", "n_elements", "element_spacing_m"],
    },
)


@register(_ULA_SPEC, write=False)
async def antenna_array_factor_ula(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = array_factor_ula(
        freq_hz=a.get("freq_hz"),
        n_elements=a.get("n_elements"),
        element_spacing_m=a.get("element_spacing_m"),
        scan_angle_deg=a.get("scan_angle_deg", 90.0),
        check_grating_lobes=a.get("check_grating_lobes", True),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 15. antenna_vswr_bw
# ═══════════════════════════════════════════════════════════════════════════════

_VSWR_BW_SPEC = ToolSpec(
    name="antenna_vswr_bw",
    description=(
        "Compute VSWR bandwidth from antenna Q factor.\n\n"
        "BW_fraction = (S − 1) / (Q × sqrt(S))  [Yaghjian & Best 2005]\n"
        "where S = VSWR threshold (default 2.0).\n\n"
        "Reference: Yaghjian & Best (2005); Balanis (2016) §11.4.\n\n"
        "Input: { freq_hz, q_factor, vswr_limit? }\n"
        "Returns: { ok, bw_fraction, bw_hz, bw_lower_hz, bw_upper_hz, return_loss_db }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Centre frequency [Hz]."},
            "q_factor": {
                "type": "number",
                "description": "Antenna quality factor Q (> 0).",
            },
            "vswr_limit": {
                "type": "number",
                "description": "VSWR threshold (>= 1.0, default 2.0).",
            },
        },
        "required": ["freq_hz", "q_factor"],
    },
)


@register(_VSWR_BW_SPEC, write=False)
async def antenna_vswr_bw(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = vswr_bandwidth_from_q(
        freq_hz=a.get("freq_hz"),
        q_factor=a.get("q_factor"),
        vswr_limit=a.get("vswr_limit", 2.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_DIPOLE_SPEC.name,   _DIPOLE_SPEC,   antenna_half_wave_dipole),
    (_MONOPOLE_SPEC.name, _MONOPOLE_SPEC, antenna_monopole),
    (_SMALL_LOOP_SPEC.name, _SMALL_LOOP_SPEC, antenna_small_loop),
    (_PATCH_SPEC.name,    _PATCH_SPEC,    antenna_microstrip_patch),
    (_YAGI_SPEC.name,     _YAGI_SPEC,     antenna_yagi_uda),
    (_HELIX_SPEC.name,    _HELIX_SPEC,    antenna_helical_axial),
    (_HORN_SPEC.name,     _HORN_SPEC,     antenna_horn_gain),
    (_DGE_SPEC.name,      _DGE_SPEC,      antenna_directivity_gain),
    (_BWD_SPEC.name,      _BWD_SPEC,      antenna_beamwidth_dir),
    (_APE_SPEC.name,      _APE_SPEC,      antenna_aperture_eff),
    (_NFF_SPEC.name,      _NFF_SPEC,      antenna_near_far_field),
    (_POL_SPEC.name,      _POL_SPEC,      antenna_polarization_ar),
    (_GPI_SPEC.name,      _GPI_SPEC,      antenna_ground_plane_image),
    (_ULA_SPEC.name,      _ULA_SPEC,      antenna_array_factor_ula),
    (_VSWR_BW_SPEC.name,  _VSWR_BW_SPEC,  antenna_vswr_bw),
]
