"""
kerf_optics LLM tools — Zernike polynomial wavefront analysis.

Registered via plugin.py at startup.

Tools
-----
optics_fit_zernike         — decompose a wavefront into Zernike modes.
optics_aberration_breakdown — map Zernike coefficients to classical aberration names.
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_optics._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# optics_fit_zernike
# ---------------------------------------------------------------------------

optics_fit_zernike_spec = ToolSpec(
    name="optics_fit_zernike",
    description=(
        "Decompose a 2-D optical wavefront error map into Zernike polynomial "
        "modes using the Noll (1976) ordering.  Returns Noll-indexed coefficients, "
        "a reconstructed wavefront (synthesised from the fitted modes), and RMS "
        "wavefront error.  Supports up to j=36 modes (6th radial order).  "
        "Wavefront values may be in any consistent unit (waves, nm, radians).\n\n"
        "Noll ordering: Z_1=piston, Z_2/Z_3=tilt, Z_4=defocus, Z_5/Z_6=astigmatism, "
        "Z_7/Z_8=coma, Z_9/Z_10=trefoil, Z_11=spherical."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wavefront": {
                "type": "array",
                "description": (
                    "2-D wavefront map as a list-of-lists (rows × columns).  "
                    "Use null (JSON null) for pixels outside the pupil aperture "
                    "(they are ignored in the fit).  Values in the centre of the "
                    "unit circle are fitted; the pupil is assumed to fill the square "
                    "grid with the unit circle inscribed."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": ["number", "null"]},
                },
                "minItems": 4,
            },
            "n_max": {
                "type": "integer",
                "description": (
                    "Number of Zernike modes to fit (Noll indices 1..n_max). "
                    "Default 8 (through coma).  Max 36."
                ),
                "minimum": 1,
                "maximum": 36,
            },
            "return_reconstructed": {
                "type": "boolean",
                "description": (
                    "If true, also return the wavefront reconstructed from the "
                    "fitted modes as a nested list.  Default false (saves bandwidth)."
                ),
            },
        },
        "required": ["wavefront"],
    },
)


async def run_optics_fit_zernike(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        import math
        import numpy as np
        from kerf_optics.zernike import (
            fit_zernike,
            reconstruct_wavefront,
            noll_index_to_mn,
            _NOLL_TO_CLASSICAL,
        )

        raw = args["wavefront"]
        n_max = int(args.get("n_max", 8))
        return_recon = bool(args.get("return_reconstructed", False))

        if n_max < 1 or n_max > 36:
            return err_payload("n_max must be in [1, 36]", "BAD_ARGS")

        # Convert to numpy array, replacing null/None with NaN
        rows = []
        for row in raw:
            rows.append([float(v) if v is not None else float("nan") for v in row])
        wavefront = np.array(rows, dtype=float)

        if wavefront.ndim != 2 or wavefront.shape[0] < 4 or wavefront.shape[1] < 4:
            return err_payload(
                "wavefront must be a 2-D array with at least 4 rows and 4 columns",
                "BAD_ARGS",
            )

        # Fit
        coeffs = fit_zernike(wavefront, n_max=n_max)

        # RMS (excluding piston j=1 for optical relevance)
        rms_all = math.sqrt(sum(c ** 2 for c in coeffs.values()))
        rms_no_piston = math.sqrt(
            sum(c ** 2 for j, c in coeffs.items() if j != 1)
        )

        # Annotated coefficient table
        coeff_table = []
        for j in range(1, n_max + 1):
            n, m = noll_index_to_mn(j)
            coeff_table.append({
                "noll_index": j,
                "n": n,
                "m": m,
                "name": _NOLL_TO_CLASSICAL.get(j, f"higher-order Z_{j}"),
                "coefficient": round(coeffs[j], 10),
            })

        payload: dict[str, Any] = {
            "n_max": n_max,
            "wavefront_shape": list(wavefront.shape),
            "coefficients": coeff_table,
            "rms_wavefront_error": round(rms_all, 10),
            "rms_wavefront_error_no_piston": round(rms_no_piston, 10),
        }

        if return_recon:
            recon = reconstruct_wavefront(coeffs, grid_size=wavefront.shape[0])
            payload["reconstructed_wavefront"] = recon.tolist()

        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "ZERNIKE_FIT_ERROR")


# ---------------------------------------------------------------------------
# optics_aberration_breakdown
# ---------------------------------------------------------------------------

optics_aberration_breakdown_spec = ToolSpec(
    name="optics_aberration_breakdown",
    description=(
        "Map Noll-indexed Zernike coefficients to classical optical aberration "
        "names (defocus, astigmatism, coma, spherical, etc.) and compute "
        "summary metrics: RMS wavefront error, Maréchal Strehl ratio approximation "
        "(valid when coefficients are in waves), and a ranked aberration table.\n\n"
        "Input can be the raw output of optics_fit_zernike (pass the 'coefficients' "
        "list) or a flat {noll_index: coefficient} mapping.\n\n"
        "References: Noll (1976); Born & Wolf §9.2; Mahajan SPIE Press (1998)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "coefficients": {
                "type": "object",
                "description": (
                    "Zernike coefficients as a JSON object mapping Noll index "
                    "(string or integer key) to float coefficient.  "
                    "Example: {\"4\": 0.35, \"11\": 0.05} for defocus + spherical."
                ),
                "additionalProperties": {"type": "number"},
            },
            "units": {
                "type": "string",
                "description": (
                    "Physical unit of the coefficients (e.g. 'waves', 'nm', 'radians'). "
                    "Used for labelling only; Strehl is only meaningful in waves. "
                    "Default 'waves'."
                ),
            },
        },
        "required": ["coefficients"],
    },
)


async def run_optics_aberration_breakdown(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_optics.zernike import classical_aberration_breakdown

        raw_coeffs = args["coefficients"]
        units = str(args.get("units", "waves"))

        # Accept both string and integer keys
        coeffs: dict[int, float] = {}
        for k, v in raw_coeffs.items():
            try:
                j = int(k)
            except (ValueError, TypeError):
                return err_payload(
                    f"coefficient key {k!r} is not a valid integer Noll index", "BAD_ARGS"
                )
            if j < 1:
                return err_payload(f"Noll index must be >= 1; got {j}", "BAD_ARGS")
            coeffs[j] = float(v)

        if not coeffs:
            return err_payload("coefficients dict is empty", "BAD_ARGS")

        breakdown = classical_aberration_breakdown(coeffs)
        breakdown["units"] = units

        # Add Strehl validity note
        rms = breakdown["rms_wavefront_error"]
        if units == "waves" and rms > 0.07:
            breakdown["strehl_note"] = (
                "Maréchal approximation not reliable for RMS > λ/14 (0.07 waves); "
                f"current RMS={rms:.4f} waves."
            )
        else:
            breakdown["strehl_note"] = (
                "Strehl approximation valid (Maréchal criterion)."
                if units == "waves"
                else "Strehl only meaningful when units='waves'."
            )

        return ok_payload(breakdown)

    except Exception as exc:
        return err_payload(str(exc), "ABERRATION_BREAKDOWN_ERROR")
