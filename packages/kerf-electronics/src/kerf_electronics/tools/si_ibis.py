"""
LLM-facing tools for IBIS parsing and channel simulation.

Registers two tools:

  si_ibis_parse           — parse an IBIS (.ibs) text, return a dict deck
  si_ibis_channel_response — simulate a channel driven by an IBIS model

Author: imranparuk
"""

from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.si.ibis_parser import (
    IBISParseError,
    parse_ibis,
    ibis_deck_to_dict,
)
from kerf_electronics.si.ibis_channel import (
    channel_response,
    eye_diagram_envelope,
)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _num(val: Any, name: str, required: bool = True, default: float | None = None):
    if val is None:
        if required:
            return None, f"{name} is required"
        return default, None
    if not isinstance(val, (int, float)):
        return None, f"{name} must be a number, got {val!r}"
    return float(val), None


# ── Tool 1: si_ibis_parse ───────────────────────────────────────────────────────

_IBIS_PARSE_SPEC = ToolSpec(
    name="si_ibis_parse",
    description=(
        "Parse an IBIS (.ibs) file text and return a structured deck containing "
        "component, pin, and model information (IV tables, ramp, waveforms). "
        "Supports IBIS 3.x / 4.x / 5.x keyword grammar. "
        "Unknown keywords are tolerated; malformed structure raises an error. "
        "Returns a JSON-serialisable dict with keys: ibis_ver, file_name, "
        "components, models (each with pulldown/pullup IV tables, ramp, waveforms)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ibs_text": {
                "type": "string",
                "description": "Full text content of the IBIS (.ibs) file.",
            },
        },
        "required": ["ibs_text"],
    },
)


@register(_IBIS_PARSE_SPEC)
async def si_ibis_parse(_ctx, payload: bytes) -> str:
    try:
        args = json.loads(payload)
    except Exception as e:
        return err_payload(f"Invalid JSON payload: {e}", "BAD_ARGS")

    ibs_text = args.get("ibs_text")
    if not isinstance(ibs_text, str) or not ibs_text.strip():
        return err_payload("ibs_text must be a non-empty string", "BAD_ARGS")

    try:
        deck = parse_ibis(ibs_text)
    except IBISParseError as e:
        return err_payload(str(e), "IBIS_PARSE_ERROR")
    except Exception as e:
        return err_payload(f"Unexpected parse error: {e}", "INTERNAL_ERROR")

    return ok_payload(ibis_deck_to_dict(deck))


# ── Tool 2: si_ibis_channel_response ────────────────────────────────────────────

_IBIS_CHANNEL_SPEC = ToolSpec(
    name="si_ibis_channel_response",
    description=(
        "Simulate a PCB channel driven by an IBIS model and compute the "
        "time-domain receiver waveform. "
        "Uses the IBIS model's pulldown/pullup IV tables and ramp dV/dt to drive "
        "a transmission line (specified by Z0, length, loss) terminated with R_term. "
        "Returns the receiver waveform as a list of [t_s, V] pairs, plus the "
        "one-way delay, and optionally the eye-diagram envelope (V_eye_high, V_eye_low). "
        "\n\nModel for ibis_model_dict: the dict returned by si_ibis_parse "
        "for a single model entry (one element of the 'models' list)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ibis_model_dict": {
                "type": "object",
                "description": (
                    "Single IBIS model dict (from si_ibis_parse result .models[i]). "
                    "Must contain 'name', 'pulldown', 'pullup', 'ramp' keys."
                ),
            },
            "z0_ohms": {
                "type": "number",
                "description": "Transmission-line characteristic impedance [Ω]. Default 50.",
            },
            "length_mm": {
                "type": "number",
                "description": "Physical line length [mm]. Default 100.",
            },
            "loss_db_per_m": {
                "type": "number",
                "description": "Combined conductor+dielectric attenuation [dB/m]. Default 0 (lossless).",
            },
            "er": {
                "type": "number",
                "description": "Effective relative permittivity (FR-4 ≈ 4.2). Default 4.2.",
            },
            "r_term_ohms": {
                "type": "number",
                "description": "Receiver termination resistance [Ω]. Default 50.",
            },
            "c_term_pf": {
                "type": "number",
                "description": "Receiver capacitance [pF]. Default 0.",
            },
            "v_supply": {
                "type": "number",
                "description": "Supply voltage [V]. Default 3.3.",
            },
            "eye_diagram": {
                "type": "boolean",
                "description": "If true, also compute PRBS-7 eye envelope. Default false.",
            },
            "n_pts": {
                "type": "integer",
                "description": "Number of time samples in the waveform. Default 300.",
            },
        },
        "required": ["ibis_model_dict"],
    },
)


def _rebuild_model_from_dict(d: dict):
    """Reconstruct an IBISModel from the ibis_deck_to_dict format."""
    from kerf_electronics.si.ibis_parser import (
        IBISModel, IBISRamp, TypMinMax
    )

    def _tmm(lst):
        if not lst or len(lst) < 3:
            return TypMinMax()
        return TypMinMax(typ=lst[0], min=lst[1], max=lst[2])

    def _rows(lst):
        if not lst:
            return []
        return [(r[0], r[1], r[2], r[3]) for r in lst if r and len(r) == 4]

    model = IBISModel()
    model.name = d.get("name", "")
    model.model_type = d.get("model_type", "")
    model.polarity = d.get("polarity", "")
    model.c_comp = _tmm(d.get("c_comp"))
    model.pulldown = _rows(d.get("pulldown", []))
    model.pullup = _rows(d.get("pullup", []))

    ramp_d = d.get("ramp")
    if ramp_d:
        ramp = IBISRamp()
        ramp.dv_dt_rise = _tmm(ramp_d.get("dv_dt_rise", []))
        ramp.dv_dt_fall = _tmm(ramp_d.get("dv_dt_fall", []))
        ramp.r_load = ramp_d.get("r_load")
        model.ramp = ramp

    return model


@register(_IBIS_CHANNEL_SPEC)
async def si_ibis_channel_response(_ctx, payload: bytes) -> str:
    try:
        args = json.loads(payload)
    except Exception as e:
        return err_payload(f"Invalid JSON payload: {e}", "BAD_ARGS")

    model_dict = args.get("ibis_model_dict")
    if not isinstance(model_dict, dict):
        return err_payload("ibis_model_dict must be an object", "BAD_ARGS")

    try:
        model = _rebuild_model_from_dict(model_dict)
    except Exception as e:
        return err_payload(f"Cannot reconstruct IBIS model: {e}", "BAD_ARGS")

    # Optional numeric parameters
    z0, e = _num(args.get("z0_ohms"), "z0_ohms", required=False, default=50.0)
    if e:
        return err_payload(e, "BAD_ARGS")
    length_mm, e = _num(args.get("length_mm"), "length_mm", required=False, default=100.0)
    if e:
        return err_payload(e, "BAD_ARGS")
    loss, e = _num(args.get("loss_db_per_m"), "loss_db_per_m", required=False, default=0.0)
    if e:
        return err_payload(e, "BAD_ARGS")
    er, e = _num(args.get("er"), "er", required=False, default=4.2)
    if e:
        return err_payload(e, "BAD_ARGS")
    r_term, e = _num(args.get("r_term_ohms"), "r_term_ohms", required=False, default=50.0)
    if e:
        return err_payload(e, "BAD_ARGS")
    c_term_pf, e = _num(args.get("c_term_pf"), "c_term_pf", required=False, default=0.0)
    if e:
        return err_payload(e, "BAD_ARGS")
    v_supply, e = _num(args.get("v_supply"), "v_supply", required=False, default=3.3)
    if e:
        return err_payload(e, "BAD_ARGS")

    n_pts = int(args.get("n_pts", 300))
    do_eye = bool(args.get("eye_diagram", False))

    length_m = length_mm / 1000.0
    c_term_f = (c_term_pf or 0.0) * 1e-12

    try:
        import math
        _C = 2.997924580e8
        td_s = length_m * math.sqrt(er) / _C
        td_ns = td_s * 1e9

        wave = channel_response(
            model=model,
            z0=z0,
            length_m=length_m,
            alpha_db_per_m=loss,
            er=er,
            r_term=r_term,
            c_term_f=c_term_f,
            v_supply=v_supply,
            n_pts=n_pts,
        )
    except Exception as exc:
        return err_payload(f"Channel simulation error: {exc}", "SIM_ERROR")

    # Truncate waveform to keep payload size manageable
    max_pts = 500
    step = max(1, len(wave) // max_pts)
    wave_out = [[round(t * 1e9, 4), round(v, 5)]
                for t, v in wave[::step]]

    result: dict = {
        "waveform_t_ns_V": wave_out,
        "td_ns": round(td_ns, 4),
        "z0_ohms": z0,
        "length_mm": length_mm,
        "er": er,
        "r_term_ohms": r_term,
        "model_name": model.name,
    }

    if do_eye:
        try:
            v_hi, v_lo = eye_diagram_envelope(
                model=model,
                z0=z0,
                length_m=length_m,
                alpha_db_per_m=loss,
                er=er,
                r_term=r_term,
                c_term_f=c_term_f,
                v_supply=v_supply,
                n_pts=max(100, n_pts // 3),
            )
            result["eye_high_V"] = round(v_hi, 4)
            result["eye_low_V"] = round(v_lo, 4)
            result["eye_height_V"] = round(v_hi - v_lo, 4)
        except Exception as exc:
            result["eye_warning"] = f"Eye diagram failed: {exc}"

    return ok_payload(result)


# Export for the tool loader
TOOLS = [t for t in [si_ibis_parse, si_ibis_channel_response]]
